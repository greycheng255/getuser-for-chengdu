# -*- coding: utf-8 -*-
"""
定时发布调度器

对应 PRD 5.3 发布策略：
1. 定时发布：scheduled_at 字段 + 后台轮询执行
2. 错峰发布：按平台活跃时段自动推荐/调整发布时间
3. 频次控制：发布前检查账号当日配额（复用 account_service）
4. 失败重试：单平台失败自动换账号重试（复用 publisher 的 cookie 池）

设计：异步 + PostgreSQL，后台 asyncio.Task 轮询。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 轮询间隔（秒）
DEFAULT_POLL_INTERVAL = 60


# 各平台活跃时段（错峰发布依据，24h 制）
# 数据来源：常见运营经验，可按需调整
PlatformPeakHours = {
    "douyin": [(12, 14), (19, 23)],  # 午休 + 晚间黄金
    "xiaohongshu": [(7, 9), (12, 14), (20, 22)],  # 通勤 + 午休 + 晚间
    "bilibili": [(18, 23)],  # 晚间
    "weibo": [(12, 14), (20, 22)],
    "zhihu": [(9, 11), (20, 23)],
    "x_twitter": [(9, 12), (20, 23)],  # 海外时间（UTC）
    "kuaishou": [(12, 14), (19, 23)],
    "wechat_public": [(7, 9), (12, 14), (20, 22)],
}


@dataclass
class ScheduledTask:
    """定时发布任务"""

    id: Optional[int] = None
    task_id: str = ""  # UUID
    title: str = ""
    content: str = ""
    images: List[str] = field(default_factory=list)
    video_path: str = ""
    target_platforms: List[str] = field(default_factory=list)
    user_id: int = 1
    source_post_id: str = ""
    scheduled_at: Optional[datetime] = None  # 定时发布时间
    status: str = "pending"  # pending / publishing / success / partial / failed
    created_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error_message: str = ""
    source_pipeline_id: str = ""  # 关联流水线任务，用于发布后回调触发互动


class PublishScheduler:
    """定时发布调度器"""

    def __init__(self, poll_interval: int = DEFAULT_POLL_INTERVAL):
        self.poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self):
        if PublishScheduler._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS scheduled_publish_tasks ("
                        "  id SERIAL PRIMARY KEY,"
                        "  task_id VARCHAR(32) UNIQUE,"
                        "  title VARCHAR(256),"
                        "  content TEXT,"
                        "  images TEXT,"
                        "  video_path TEXT,"
                        "  target_platforms VARCHAR(256),"
                        "  user_id INT,"
                        "  source_post_id VARCHAR(64),"
                        "  scheduled_at TIMESTAMP,"
                        "  status VARCHAR(16) DEFAULT 'pending',"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  executed_at TIMESTAMP,"
                        "  result TEXT,"
                        "  error_message TEXT,"
                        "  source_pipeline_id VARCHAR(64)"
                        ")"
                    )
                )
                # 兼容旧表：列已存在时静默忽略
                try:
                    await conn.execute(
                        sql_text(
                            "ALTER TABLE scheduled_publish_tasks "
                            "ADD COLUMN source_pipeline_id VARCHAR(64)"
                        )
                    )
                except Exception:
                    pass
            PublishScheduler._ensured = True
        except Exception as e:
            logger.warning(f"[Scheduler] 建表失败: {e}")

    # ==================== 错峰发布时间计算 ====================

    def get_peak_hours(self, platform: str) -> List[tuple]:
        return PlatformPeakHours.get(platform, [(9, 12), (19, 22)])

    def recommend_publish_time(
        self, platform: str, base_time: Optional[datetime] = None,
        *,
        strategy: str = "scheduled",
        avoid_times: Optional[List[datetime]] = None,
        min_gap_minutes: int = 30,
    ) -> datetime:
        """推荐最佳发布时间（错峰）

        策略：
        - immediate：立即发布
        - scheduled：从 base_time 开始，找到下一个活跃时段
        - smart_stagger（任务 2.4）：智能错峰，避免与同账号已发布时间冲突
        """
        from .peak_hours import (
            get_peak_hours_service, ScheduleStrategy,
        )
        svc = get_peak_hours_service()

        if strategy == ScheduleStrategy.IMMEDIATE.value:
            return base_time or datetime.utcnow()

        if strategy == ScheduleStrategy.SMART_STAGGER.value:
            return svc.recommend_publish_time(
                platform, base_time,
                strategy=strategy,
                avoid_times=avoid_times,
                min_gap_minutes=min_gap_minutes,
            )

        # 默认 scheduled 策略（兼容旧调用）
        base = base_time or datetime.utcnow()
        # 转为本地时区考虑（这里用 UTC+8 近似）
        peak_hours = self.get_peak_hours(platform)
        # 从 base+1h 开始逐小时扫描
        for i in range(1, 72):  # 扫描未来 3 天
            candidate = base + timedelta(hours=i)
            # 取整点
            candidate = candidate.replace(minute=0, second=0, microsecond=0)
            hour = candidate.hour
            for start, end in peak_hours:
                if start <= hour < end:
                    return candidate
        # 兜底：24h 后
        return base + timedelta(hours=24)

    # ==================== 任务管理 ====================

    async def schedule_task(self, task: ScheduledTask) -> Optional[int]:
        """创建定时发布任务"""
        await self.ensure_table()
        if not task.scheduled_at:
            task.scheduled_at = datetime.utcnow() + timedelta(minutes=10)
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                row = await conn.execute(
                    sql_text(
                        "INSERT INTO scheduled_publish_tasks "
                        "(task_id, title, content, images, video_path, target_platforms, "
                        "user_id, source_post_id, scheduled_at, status, source_pipeline_id) "
                        "VALUES (:tid, :t, :c, :img, :v, :tp, :u, :sp, :sa, 'pending', :spi) "
                        "RETURNING id"
                    ),
                    {
                        "tid": task.task_id,
                        "t": task.title[:256],
                        "c": task.content,
                        "img": "|||".join(task.images),
                        "v": task.video_path,
                        "tp": ",".join(task.target_platforms),
                        "u": task.user_id,
                        "sp": task.source_post_id,
                        "sa": task.scheduled_at,
                        "spi": getattr(task, "source_pipeline_id", "") or "",
                    },
                )
                r = row.fetchone()
                logger.info(
                    f"[Scheduler] 已创建定时任务 #{r[0]} 定于 {task.scheduled_at} "
                    f"平台={task.target_platforms}"
                )
                return r[0] if r else None
        except Exception as e:
            logger.error(f"[Scheduler] 创建任务失败: {e}")
            return None

    async def list_pending_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """列出待执行任务"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, task_id, title, target_platforms, scheduled_at, status "
                        "FROM scheduled_publish_tasks WHERE status='pending' "
                        "ORDER BY scheduled_at ASC LIMIT :l"
                    ),
                    {"l": limit},
                )
                return [
                    {
                        "id": r[0],
                        "task_id": r[1],
                        "title": r[2],
                        "target_platforms": (r[3] or "").split(","),
                        "scheduled_at": str(r[4]) if r[4] else None,
                        "status": r[5],
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[Scheduler] 查询任务失败: {e}")
            return []

    async def list_all_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, task_id, title, target_platforms, scheduled_at, status, "
                        "executed_at, error_message, source_pipeline_id "
                        "FROM scheduled_publish_tasks ORDER BY id DESC LIMIT :l"
                    ),
                    {"l": limit},
                )
                return [
                    {
                        "id": r[0],
                        "task_id": r[1],
                        "title": r[2],
                        "target_platforms": (r[3] or "").split(","),
                        "scheduled_at": str(r[4]) if r[4] else None,
                        "status": r[5],
                        "executed_at": str(r[6]) if r[6] else None,
                        "error_message": r[7],
                        "source_pipeline_id": r[8] or "",
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[Scheduler] 查询任务失败: {e}")
            return []

    async def cancel_task(self, task_id: int) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE scheduled_publish_tasks SET status='cancelled' "
                        "WHERE id=:i AND status='pending'"
                    ),
                    {"i": task_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[Scheduler] 取消任务失败: {e}")
            return False

    # ==================== 调度主循环 ====================

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_with_watchdog())
        logger.info("[Scheduler] 定时发布调度器已启动")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def _run_with_watchdog(self):
        while self._running:
            try:
                await self._poll_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"[Scheduler] 调度异常，10s 后重启: {e}")
                await asyncio.sleep(10)

    async def _poll_loop(self):
        while self._running:
            try:
                await self._execute_due_tasks()
            except Exception as e:
                logger.error(f"[Scheduler] 轮询异常: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _execute_due_tasks(self):
        """执行到期的定时任务"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            now = datetime.utcnow()
            async with engine.begin() as conn:
                # 标记到期任务为 publishing
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, task_id, title, content, images, video_path, "
                        "target_platforms, user_id, source_post_id, source_pipeline_id "
                        "FROM scheduled_publish_tasks "
                        "WHERE status='pending' AND scheduled_at<=:now LIMIT 10"
                    ),
                    {"now": now},
                )
                tasks = rows.fetchall()
            if not tasks:
                return
            logger.info(f"[Scheduler] 发现 {len(tasks)} 个到期任务")
            for row in tasks:
                await self._execute_one(row)
        except Exception as e:
            logger.error(f"[Scheduler] 执行到期任务异常: {e}")

    async def _execute_one(self, row):
        """执行单个定时任务"""
        (
            task_id, task_uuid, title, content, images_str, video_path,
            platforms_str, user_id, source_post_id, source_pipeline_id,
        ) = row
        platforms = [p for p in (platforms_str or "").split(",") if p]
        images = [i for i in (images_str or "").split("|||") if i]
        source_pipeline_id = source_pipeline_id or ""
        try:
            # 标记为 publishing
            await self._update_status(task_id, "publishing")
            # 调用多平台发布
            from api.services.publisher import (
                PublishTask,
                PublishStatus,
                get_multi_publisher,
            )

            pub_task = PublishTask(
                source_post_id=source_post_id or "",
                title=title or "",
                content=content or "",
                images=images,
                video_path=video_path or None,
                target_platforms=platforms,
                user_id=user_id,
            )
            result = await get_multi_publisher().publish_to_multiple_platforms(pub_task)
            status = "success" if result.status == PublishStatus.SUCCESS else (
                "partial" if result.status == PublishStatus.PARTIAL else "failed"
            )
            await self._update_status(
                task_id,
                status,
                result=result.to_dict(),
                executed_at=datetime.utcnow(),
            )
            logger.info(f"[Scheduler] 任务 #{task_id} 执行完成: {status}")

            # 审计日志：定时任务执行结果（P1-6）
            try:
                from api.services.utils.audit_log import (
                    get_audit_log_service, AuditActionType,
                )
                audit_status = "success" if status == "success" else (
                    "partial" if status == "partial" else "failed"
                )
                await get_audit_log_service().log(
                    action_type=AuditActionType.PUBLISH.value,
                    user_id=user_id,
                    platform=",".join(platforms),
                    target=task_uuid or str(task_id),
                    description=(
                        f"定时发布任务执行: task_id={task_id} status={status} "
                        f"title={title[:50] if title else ''}"
                    ),
                    request_data={
                        "task_id": task_id,
                        "task_uuid": task_uuid,
                        "platforms": platforms,
                    },
                    response_data={
                        "status": status,
                        "platform_results": {
                            pf: {"success": r.success, "error": r.error}
                            for pf, r in result.platform_results.items()
                        },
                    },
                    status=audit_status,
                    error_message="" if status == "success" else result.error_message,
                )
            except Exception as audit_e:
                logger.warning(f"[Scheduler] 记录审计日志失败: {audit_e}")

            # 发布完成 → 回调流水线触发 Step6 话术库互动
            if source_pipeline_id and status in ("success", "partial"):
                try:
                    publish_results = []
                    for pf, pr in result.platform_results.items():
                        pr_dict = (
                            pr.to_dict() if hasattr(pr, "to_dict")
                            else {"success": getattr(pr, "success", False),
                                  "error": getattr(pr, "error", "")}
                        )
                        pr_dict["platform"] = pf
                        publish_results.append(pr_dict)
                    from api.services.ai.unified_pipeline import get_unified_pipeline
                    cb = await get_unified_pipeline().proceed_after_publish(
                        source_pipeline_id, publish_results
                    )
                    logger.info(
                        f"[Scheduler] 任务 #{task_id} 流水线回调: "
                        f"interaction_task_id={cb.get('interaction_task_id')}"
                    )
                except Exception as cb_e:
                    logger.warning(f"[Scheduler] 触发流水线互动失败(非致命): {cb_e}")
        except Exception as e:
            logger.error(f"[Scheduler] 任务 #{task_id} 执行失败: {e}")
            await self._update_status(
                task_id, "failed", error_message=str(e), executed_at=datetime.utcnow()
            )
            # 审计日志：定时任务执行失败（P1-6）
            try:
                from api.services.utils.audit_log import (
                    get_audit_log_service, AuditActionType,
                )
                await get_audit_log_service().log(
                    action_type=AuditActionType.PUBLISH.value,
                    user_id=user_id,
                    platform=",".join(platforms),
                    target=task_uuid or str(task_id),
                    description=f"定时发布任务执行失败: task_id={task_id}",
                    request_data={
                        "task_id": task_id,
                        "task_uuid": task_uuid,
                        "platforms": platforms,
                    },
                    response_data={"error": str(e)},
                    status="failed",
                    error_message=str(e),
                )
            except Exception as audit_e:
                logger.warning(f"[Scheduler] 记录失败审计日志失败: {audit_e}")

    async def _update_status(
        self,
        task_id: int,
        status: str,
        result: Optional[Dict] = None,
        error_message: str = "",
        executed_at: Optional[datetime] = None,
    ):
        try:
            import json
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE scheduled_publish_tasks SET status=:s, result=:r, "
                        "error_message=:e, executed_at=:ea WHERE id=:i"
                    ),
                    {
                        "s": status,
                        "r": json.dumps(result, ensure_ascii=False) if result else None,
                        "e": error_message[:500],
                        "ea": executed_at,
                        "i": task_id,
                    },
                )
        except Exception as e:
            logger.warning(f"[Scheduler] 更新状态失败: {e}")


_scheduler: Optional[PublishScheduler] = None


def get_publish_scheduler() -> PublishScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = PublishScheduler()
    return _scheduler
