# -*- coding: utf-8 -*-
"""
互动任务调度器

阶段二 P1 任务 2.2：补齐 PRD 5.4 时效控制 + 频次控制。

核心能力：
1. 发布后延迟 5-30 分钟启动互动（随机），避免机器化特征
2. 单条内容互动量自定义区间（点赞数 / 评论数 / 关注数）
3. 点赞评论比例配置（如 5:1，5 个点赞配 1 条评论）
4. 后台 asyncio 任务调度，支持取消 / 查询状态
5. 互动任务持久化到 interaction_schedule_tasks 表
6. 与 BotAccountPool 集成：每次互动从池中轮换账号
7. 与 InteractionType 扩展：支持 like / comment / reply / follow / collect / retweet

设计要点（项目 memory 风控规避要求）：
- 模拟真人节奏：互动间隔 30s-3min 随机
- 同一账号 24h 内不重复互动同一帖子
- 单账号单日互动总量上限可配置
- 失败重试 3 次，超过则放弃该任务
"""

import asyncio
import json
import logging
import random
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============ 默认配置（PRD 5.4 时效控制） ============

DEFAULT_DELAY_MIN_SECONDS = 300       # 发布后 5 分钟启动
DEFAULT_DELAY_MAX_SECONDS = 1800      # 发布后 30 分钟启动
DEFAULT_INTERACTION_INTERVAL_MIN = 30  # 互动间隔下限 30s
DEFAULT_INTERACTION_INTERVAL_MAX = 180  # 互动间隔上限 3min
DEFAULT_LIKE_COMMENT_RATIO = 5.0        # 5 个点赞配 1 条评论
DEFAULT_MAX_INTERACTIONS_PER_DAY = 50   # 单账号单日互动上限
DEFAULT_MAX_RETRIES = 3                 # 失败重试上限


class ScheduleTaskStatus(str, Enum):
    """调度任务状态"""
    PENDING = "pending"        # 等待延迟启动
    RUNNING = "running"        # 正在执行互动
    COMPLETED = "completed"    # 全部互动完成
    CANCELLED = "cancelled"    # 已取消
    FAILED = "failed"          # 失败


@dataclass
class InteractionQuotaConfig:
    """单条内容互动量配置（PRD 5.4 频次控制）"""
    min_likes: int = 3                 # 最少点赞数
    max_likes: int = 10                # 最多点赞数
    min_comments: int = 1              # 最少评论数
    max_comments: int = 3              # 最多评论数
    follows: int = 0                   # 关注数（默认不关注）
    collects: int = 0                  # 收藏数
    retweets: int = 0                  # 转发数
    like_comment_ratio: float = DEFAULT_LIKE_COMMENT_RATIO  # 点赞评论比例
    delay_min_seconds: int = DEFAULT_DELAY_MIN_SECONDS      # 启动延迟下限
    delay_max_seconds: int = DEFAULT_DELAY_MAX_SECONDS      # 启动延迟上限
    interval_min_seconds: int = DEFAULT_INTERACTION_INTERVAL_MIN  # 互动间隔下限
    interval_max_seconds: int = DEFAULT_INTERACTION_INTERVAL_MAX  # 互动间隔上限
    max_retries: int = DEFAULT_MAX_RETRIES

    def validate(self) -> List[str]:
        errors = []
        if self.min_likes < 0 or self.max_likes < self.min_likes:
            errors.append("点赞数区间无效")
        if self.min_comments < 0 or self.max_comments < self.min_comments:
            errors.append("评论数区间无效")
        if self.like_comment_ratio <= 0:
            errors.append("点赞评论比例必须 > 0")
        if self.delay_min_seconds < 0 or self.delay_max_seconds < self.delay_min_seconds:
            errors.append("启动延迟区间无效")
        if self.interval_min_seconds < 0 or self.interval_max_seconds < self.interval_min_seconds:
            errors.append("互动间隔区间无效")
        return errors

    def sample_actual_counts(self) -> Dict[str, int]:
        """随机采样实际互动数量（在区间内）"""
        likes = random.randint(self.min_likes, self.max_likes)
        comments = random.randint(self.min_comments, self.max_comments)
        # 按比例约束：comments <= likes / ratio
        if self.like_comment_ratio > 0:
            max_comments_by_ratio = max(1, int(likes / self.like_comment_ratio))
            comments = min(comments, max_comments_by_ratio)
        return {
            "likes": likes,
            "comments": comments,
            "follows": self.follows,
            "collects": self.collects,
            "retweets": self.retweets,
        }


@dataclass
class ScheduleTask:
    """互动调度任务"""
    task_id: str = ""
    post_url: str = ""                       # 目标帖子 URL
    platform: str = ""                       # 平台名
    user_id: Optional[int] = None            # 发布用户 ID
    config: Dict[str, Any] = field(default_factory=dict)  # InteractionQuotaConfig 转 dict
    scheduled_at: Optional[str] = None       # 创建时间
    planned_start_at: Optional[str] = None   # 计划启动时间（延迟后）
    actual_start_at: Optional[str] = None    # 实际启动时间
    completed_at: Optional[str] = None       # 完成时间
    status: str = ScheduleTaskStatus.PENDING.value
    target_counts: Dict[str, int] = field(default_factory=dict)  # 实际采样数量
    completed_counts: Dict[str, int] = field(default_factory=dict)
    failed_counts: Dict[str, int] = field(default_factory=dict)
    error_message: Optional[str] = None
    account_ids_used: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _to_dt(v) -> Optional[datetime]:
    """将字符串/datetime 转为 datetime 对象，供 asyncpg 写入 TIMESTAMP 列。

    asyncpg 不接受 isoformat 字符串，必须传 datetime 对象。
    dataclass 字段保留字符串（供 datetime.fromisoformat 解析与 JSON 序列化），
    仅在持久化时调用本函数转换。
    """
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except Exception:
        return None


class InteractionScheduler:
    """互动调度器（异步任务调度）

    用法：
        scheduler = get_interaction_scheduler()
        await scheduler.ensure_table()
        task_id = await scheduler.schedule_interaction(
            post_url="https://...",
            platform="douyin",
            user_id=1,
            quota=InteractionQuotaConfig(min_likes=5, max_likes=15),
        )
    """

    _ensured = False  # DDL 仅首次执行一次，避免每次请求都跑 CREATE TABLE/INDEX

    def __init__(self):
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._task_cache: Dict[str, ScheduleTask] = {}
        self._started = False

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """建表"""
        if InteractionScheduler._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS interaction_schedule_tasks ("
                        "  task_id VARCHAR(64) PRIMARY KEY,"
                        "  post_url TEXT NOT NULL,"
                        "  platform VARCHAR(32) NOT NULL,"
                        "  user_id INTEGER,"
                        "  config TEXT,"
                        "  scheduled_at TIMESTAMP,"
                        "  planned_start_at TIMESTAMP,"
                        "  actual_start_at TIMESTAMP,"
                        "  completed_at TIMESTAMP,"
                        "  status VARCHAR(16) DEFAULT 'pending',"
                        "  target_counts TEXT,"
                        "  completed_counts TEXT,"
                        "  failed_counts TEXT,"
                        "  error_message TEXT,"
                        "  account_ids_used TEXT)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_schedule_tasks_status "
                        "ON interaction_schedule_tasks(status, planned_start_at)"
                    )
                )
            InteractionScheduler._ensured = True
        except Exception as e:
            logger.warning(f"[InteractionScheduler] ensure_table failed: {e}")

    # ============ 任务创建 ============

    async def schedule_interaction(
        self,
        post_url: str,
        platform: str,
        user_id: Optional[int] = None,
        quota: Optional[InteractionQuotaConfig] = None,
        delay_seconds: Optional[int] = None,
        auto_start: bool = True,
    ) -> str:
        """调度一次互动任务

        Args:
            post_url: 目标帖子 URL
            platform: 平台名
            user_id: 发布用户 ID
            quota: 互动量配置，None 时使用默认值
            delay_seconds: 显式指定启动延迟（秒），None 则随机 5-30 分钟
            auto_start: 是否自动启动后台任务

        Returns:
            task_id
        """
        await self.ensure_table()
        quota = quota or InteractionQuotaConfig()
        # 计算启动延迟
        if delay_seconds is not None:
            actual_delay = max(0, delay_seconds)
        else:
            actual_delay = random.randint(
                quota.delay_min_seconds, quota.delay_max_seconds
            )

        task = ScheduleTask(
            task_id=f"sched_{uuid.uuid4().hex[:12]}",
            post_url=post_url,
            platform=platform,
            user_id=user_id,
            config=asdict(quota),
            scheduled_at=datetime.now().isoformat(),
            planned_start_at=(datetime.now() + timedelta(seconds=actual_delay)).isoformat(),
            target_counts=quota.sample_actual_counts(),
            completed_counts={"likes": 0, "comments": 0, "follows": 0, "collects": 0, "retweets": 0},
            failed_counts={"likes": 0, "comments": 0, "follows": 0, "collects": 0, "retweets": 0},
        )
        await self._persist_task(task)
        self._task_cache[task.task_id] = task

        if auto_start:
            await self.start_task(task.task_id)

        logger.info(
            f"[InteractionScheduler] 任务已调度 task_id={task.task_id} "
            f"platform={platform} 延迟={actual_delay}s 目标={task.target_counts}"
        )
        return task.task_id

    # ============ 任务执行 ============

    async def start_task(self, task_id: str) -> bool:
        """启动后台任务"""
        if task_id in self._running_tasks:
            logger.warning(f"[InteractionScheduler] 任务 {task_id} 已在运行")
            return False

        task = await self.get_task(task_id)
        if not task:
            return False
        if task.status not in (
            ScheduleTaskStatus.PENDING.value, ScheduleTaskStatus.FAILED.value
        ):
            return False

        asyncio_task = asyncio.create_task(self._run_task(task_id))
        self._running_tasks[task_id] = asyncio_task
        return True

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()
            del self._running_tasks[task_id]
        task = await self.get_task(task_id)
        if task:
            task.status = ScheduleTaskStatus.CANCELLED.value
            task.completed_at = datetime.now().isoformat()
            await self._persist_task(task)
            return True
        return False

    async def _run_task(self, task_id: str) -> None:
        """后台执行任务"""
        task = await self.get_task(task_id)
        if not task:
            return

        try:
            # 1. 等待启动延迟
            now = datetime.now()
            planned = datetime.fromisoformat(task.planned_start_at)
            wait_seconds = (planned - now).total_seconds()
            if wait_seconds > 0:
                logger.info(
                    f"[InteractionScheduler] task={task_id} 等待 {int(wait_seconds)}s 启动"
                )
                await asyncio.sleep(wait_seconds)

            task.actual_start_at = datetime.now().isoformat()
            task.status = ScheduleTaskStatus.RUNNING.value
            await self._persist_task(task)

            # 2. 重建 quota 配置
            quota = InteractionQuotaConfig(**task.config)
            targets = task.target_counts

            # 3. 依次执行互动（点赞 → 评论 → 关注 → 收藏 → 转发）
            interaction_plan = self._build_interaction_plan(targets, quota)

            for action_type, account_id in interaction_plan:
                if task.status == ScheduleTaskStatus.CANCELLED.value:
                    return
                # 执行单次互动
                ok = await self._execute_single_interaction(
                    task, action_type, account_id
                )
                if ok:
                    task.completed_counts[action_type] = (
                        task.completed_counts.get(action_type, 0) + 1
                    )
                else:
                    task.failed_counts[action_type] = (
                        task.failed_counts.get(action_type, 0) + 1
                    )
                if account_id and account_id not in task.account_ids_used:
                    task.account_ids_used.append(account_id)
                await self._persist_task(task)
                # 模拟真人互动间隔
                interval = random.randint(
                    quota.interval_min_seconds, quota.interval_max_seconds
                )
                await asyncio.sleep(interval)

            task.status = ScheduleTaskStatus.COMPLETED.value
            task.completed_at = datetime.now().isoformat()
            await self._persist_task(task)
            logger.info(
                f"[InteractionScheduler] task={task_id} 完成 "
                f"成功={task.completed_counts} 失败={task.failed_counts}"
            )
        except asyncio.CancelledError:
            task.status = ScheduleTaskStatus.CANCELLED.value
            task.completed_at = datetime.now().isoformat()
            await self._persist_task(task)
            raise
        except Exception as e:
            logger.exception(f"[InteractionScheduler] task={task_id} 异常")
            task.status = ScheduleTaskStatus.FAILED.value
            task.error_message = str(e)
            task.completed_at = datetime.now().isoformat()
            await self._persist_task(task)
        finally:
            self._running_tasks.pop(task_id, None)

    def _build_interaction_plan(
        self, targets: Dict[str, int], quota: InteractionQuotaConfig
    ) -> List[tuple]:
        """构建互动执行计划：[(action_type, account_id_placeholder), ...]

        account_id 此处用 None 占位，执行时从账号池获取。
        """
        plan: List[tuple] = []
        # 点赞
        for _ in range(targets.get("likes", 0)):
            plan.append(("likes", None))
        # 评论
        for _ in range(targets.get("comments", 0)):
            plan.append(("comments", None))
        # 关注
        for _ in range(targets.get("follows", 0)):
            plan.append(("follows", None))
        # 收藏
        for _ in range(targets.get("collects", 0)):
            plan.append(("collects", None))
        # 转发
        for _ in range(targets.get("retweets", 0)):
            plan.append(("retweets", None))
        # 打乱顺序（避免机械点赞后才评论）
        random.shuffle(plan)
        return plan

    async def _execute_single_interaction(
        self, task: ScheduleTask, action_type: str, account_id_placeholder: Optional[str]
    ) -> bool:
        """执行单次互动

        从 BotAccountPool 获取账号，调用对应 Interactor 执行互动。
        """
        account = None
        interaction_type_str = action_type.rstrip("s")  # likes -> like, comments -> comment
        try:
            from .bot_account_pool import get_bot_account_pool
            from .interactor_factory import InteractorFactory
            from .interaction_models import InteractionType

            pool = get_bot_account_pool()
            # 根据平台和地区获取账号
            region = self._resolve_region_for_platform(task.platform)
            account = await pool.get_account(
                platform=task.platform,
                region=region,
                owner_user_id=task.user_id,
            )
            if not account:
                logger.warning(
                    f"[InteractionScheduler] task={task.task_id} 无可用账号 "
                    f"platform={task.platform} region={region}"
                )
                # 写一条 skipped 记录便于审计
                await self._record_interaction(
                    task=task,
                    action_type=action_type,
                    account_id_str=None,
                    success=False,
                    status="skipped",
                    error="无可用账号",
                    content="",
                )
                return False

            # ===== 频次硬限制校验（任务 P1-7）=====
            quota_blocked = False
            try:
                from api.services.risk_control.quota_config import (
                    get_quota_config_service,
                )
                quota_svc = get_quota_config_service()
                quota_result = await quota_svc.check_interaction_quota(
                    platform=task.platform,
                    account_id=str(account.account_id),
                    interaction_type=interaction_type_str,
                    owner_user_id=task.user_id,
                )
                if not quota_result.allowed:
                    quota_blocked = True
                    logger.warning(
                        f"[InteractionScheduler] task={task.task_id} 互动配额拒绝: "
                        f"{quota_result.reason}"
                    )
                    await self._record_interaction(
                        task=task,
                        action_type=action_type,
                        account_id_str=str(account.account_id),
                        success=False,
                        status="skipped",
                        error=f"quota_exceeded: {quota_result.reason}",
                        content="",
                    )
                    return False
            except Exception as e:
                logger.warning(
                    f"[InteractionScheduler] 配额校验异常(忽略，继续执行): {e}"
                )

            # 创建互动器实例（InteractorFactory.create 已返回实例，无需再次调用）
            try:
                interactor = InteractorFactory.create(
                    task.platform,
                    cookies=account.cookie,
                    user_id=account.owner_user_id,
                    region=region,
                )
            except Exception as e:
                logger.warning(f"[InteractionScheduler] 平台 {task.platform} 无互动器: {e}")
                await self._record_interaction(
                    task=task,
                    action_type=action_type,
                    account_id_str=str(account.account_id),
                    success=False,
                    status="failed",
                    error=f"无互动器: {e}",
                    content="",
                )
                return False

            # 执行互动
            action_map = {
                "likes": InteractionType.LIKE,
                "comments": InteractionType.COMMENT,
                "follows": InteractionType.FOLLOW,
                "collects": InteractionType.COLLECT,
                "retweets": InteractionType.RETWEET,
            }
            itype = action_map.get(action_type)
            if not itype:
                return False

            # 评论需要内容（从话术库获取，缺省用占位文案）
            content = ""
            if itype == InteractionType.COMMENT:
                content = await self._fetch_script(task.platform, task.post_url)

            try:
                if itype == InteractionType.LIKE:
                    result = await interactor.like(task.post_url)
                elif itype == InteractionType.COMMENT:
                    result = await interactor.comment(task.post_url, content)
                elif itype == InteractionType.FOLLOW:
                    result = await interactor.follow(task.post_url)
                elif itype == InteractionType.COLLECT:
                    if hasattr(interactor, "collect"):
                        result = await interactor.collect(task.post_url)
                    else:
                        await self._record_interaction(
                            task=task,
                            action_type=action_type,
                            account_id_str=str(account.account_id),
                            success=False,
                            status="failed",
                            error="平台不支持 collect",
                            content=content,
                        )
                        return False
                elif itype == InteractionType.RETWEET:
                    if hasattr(interactor, "retweet"):
                        result = await interactor.retweet(task.post_url)
                    else:
                        await self._record_interaction(
                            task=task,
                            action_type=action_type,
                            account_id_str=str(account.account_id),
                            success=False,
                            status="failed",
                            error="平台不支持 retweet",
                            content=content,
                        )
                        return False
                else:
                    return False
            except Exception as e:
                logger.warning(
                    f"[InteractionScheduler] task={task.task_id} 互动异常: {e}"
                )
                await pool.mark_failed(account.account_id, failure_type=action_type)
                await self._record_interaction(
                    task=task,
                    action_type=action_type,
                    account_id_str=str(account.account_id),
                    success=False,
                    status="failed",
                    error=f"互动异常: {e}",
                    content=content,
                )
                return False

            # ===== 记录配额使用（任务 P1-7，容错） =====
            if not quota_blocked:
                try:
                    from api.services.risk_control.quota_config import (
                        get_quota_config_service,
                    )
                    await get_quota_config_service().record_usage(
                        platform=task.platform,
                        account_id=str(account.account_id),
                        action_type="interaction",
                        target_url=task.post_url,
                        owner_user_id=task.user_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"[InteractionScheduler] record_usage 异常(忽略): {e}"
                    )

            # 反馈账号池 + 持久化互动记录（任务 P1-5）
            if result.success:
                await pool.mark_success(account.account_id)
                await self._record_interaction(
                    task=task,
                    action_type=action_type,
                    account_id_str=str(account.account_id),
                    success=True,
                    status="success",
                    error="",
                    content=content,
                )
                return True
            else:
                await pool.mark_failed(
                    account.account_id, failure_type=result.error or action_type
                )
                await self._record_interaction(
                    task=task,
                    action_type=action_type,
                    account_id_str=str(account.account_id),
                    success=False,
                    status="failed",
                    error=result.error or "",
                    content=content,
                )
                return False
        except Exception as e:
            logger.warning(
                f"[InteractionScheduler] task={task.task_id} "
                f"action={action_type} 执行异常: {e}"
            )
            await self._record_interaction(
                task=task,
                action_type=action_type,
                account_id_str=(
                    str(account.account_id) if account is not None else None
                ),
                success=False,
                status="failed",
                error=f"执行异常: {e}",
                content="",
            )
            return False

    async def _record_interaction(
        self,
        *,
        task: ScheduleTask,
        action_type: str,
        account_id_str: Optional[str],
        success: bool,
        status: str,
        error: str,
        content: str,
    ) -> None:
        """写入 multi_interaction_records 表（任务 P1-5）

        与 MultiInteractor._record_interaction 保持一致的字段对齐。
        容错：写入失败仅 log warning，不阻断主流程。
        """
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return

            interaction_id = f"sch_{uuid.uuid4().hex[:16]}"
            now = datetime.now()
            # likes -> like, comments -> comment
            itype_str = action_type.rstrip("s")

            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO multi_interaction_records "
                        "(interaction_id, task_id, platform, account_id, "
                        " interaction_type, target_url, target_id, content, "
                        " status, error, retry_count, owner_user_id, "
                        " created_at, completed_at) "
                        "VALUES (:iid, :tid, :pf, :aid, :itype, :turl, :tid2, "
                        "        :content, :st, :err, :rc, :ouid, :ca, :comp)"
                    ),
                    {
                        "iid": interaction_id,
                        "tid": task.task_id or "",
                        "pf": task.platform,
                        "aid": None,  # account_id_str 不一定是 int，保留 None 避免类型错
                        "itype": itype_str,
                        "turl": task.post_url or "",
                        "tid2": "",
                        "content": content or "",
                        "st": status,
                        "err": (error or "")[:1000] if error else None,
                        "rc": 0,
                        "ouid": task.user_id,
                        "ca": now,
                        "comp": now,
                    },
                )
        except Exception as e:
            logger.warning(
                f"[InteractionScheduler] 写 multi_interaction_records 失败(忽略): {e}"
            )

        # ===== 合规归档互动记录（任务 P2-9，无论成功/失败） =====
        # 容错：失败仅 log warning，不阻断主流程。
        # 避免循环依赖：compliance_archive 不反向依赖 interactor。
        try:
            from api.services.moderation.compliance_archive import (
                ArchiveType,
                get_compliance_archive_service,
            )
            await get_compliance_archive_service().archive(
                archive_type=ArchiveType.INTERACTION.value,
                platform=task.platform,
                account_id=account_id_str or "",
                target_url=task.post_url,
                content=content or "",
                metadata={
                    "task_id": task.task_id,
                    "action_type": action_type,
                    "interaction_type": action_type.rstrip("s"),
                    "success": success,
                    "status": status,
                    "error": error,
                    "source": "interaction_scheduler",
                },
                owner_user_id=task.user_id,
            )
        except Exception as arch_e:
            logger.warning(
                f"[InteractionScheduler] 合规归档失败(忽略): {arch_e}"
            )

    def _resolve_region_for_platform(self, platform: str) -> str:
        """根据平台推断地域（用于账号池筛选）"""
        overseas_platforms = {
            "tiktok", "instagram", "youtube", "facebook",
            "x_twitter", "x_twitter_publisher",
        }
        if platform in overseas_platforms:
            return "us"
        return "cn"

    async def _fetch_script(self, platform: str, post_url: str) -> str:
        """从话术库获取评论内容（任务 2.5 实现，此处先占位）"""
        try:
            from .script_library import get_script_library
            library = get_script_library()
            script = await library.pick_random(
                platform=platform,
                script_type="comment",
                scene="comment_reply",
            )
            if script:
                return script.content
        except Exception:
            pass
        # 兜底：通用话术
        fallback_scripts = [
            "干货满满，学到了！",
            "这个角度很新颖，受教了。",
            "内容很实用，已关注。",
            "讲得真清楚，期待更新。",
            "收藏了，慢慢消化。",
        ]
        return random.choice(fallback_scripts)

    # ============ 任务查询 ============

    async def get_task(self, task_id: str) -> Optional[ScheduleTask]:
        """查询任务详情"""
        if task_id in self._task_cache:
            return self._task_cache[task_id]
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM interaction_schedule_tasks WHERE task_id = :tid"),
                    {"tid": task_id},
                )
                row = rows.fetchone()
                if not row:
                    return None
                task = self._row_to_task(row)
                self._task_cache[task_id] = task
                return task
        except Exception as e:
            logger.warning(f"[InteractionScheduler] get_task failed: {e}")
            return None

    async def list_tasks(
        self,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        user_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询任务列表"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                sql = "SELECT * FROM interaction_schedule_tasks WHERE 1=1"
                params: Dict[str, Any] = {"limit": limit, "offset": offset}
                if status:
                    sql += " AND status = :st"
                    params["st"] = status
                if platform:
                    sql += " AND platform = :pf"
                    params["pf"] = platform
                if user_id is not None:
                    sql += " AND user_id = :uid"
                    params["uid"] = user_id
                sql += " ORDER BY scheduled_at DESC LIMIT :limit OFFSET :offset"
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_task(r).to_dict() for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[InteractionScheduler] list_tasks failed: {e}")
            return []

    async def get_pending_count(self) -> int:
        """查询待执行任务数"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return 0
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT COUNT(*) FROM interaction_schedule_tasks "
                        "WHERE status IN ('pending', 'running')"
                    )
                )
                return int(rows.fetchone()[0] or 0)
        except Exception:
            return 0

    # ============ 持久化 ============

    async def _persist_task(self, task: ScheduleTask) -> None:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO interaction_schedule_tasks "
                        "(task_id, post_url, platform, user_id, config, scheduled_at, "
                        " planned_start_at, actual_start_at, completed_at, status, "
                        " target_counts, completed_counts, failed_counts, "
                        " error_message, account_ids_used) "
                        "VALUES (:tid, :pu, :pf, :uid, :cfg, :sa, :psa, :asa, :ca, :st, "
                        " :tc, :cc, :fc, :em, :aiu) "
                        "ON CONFLICT (task_id) DO UPDATE SET "
                        " status = :st, actual_start_at = :asa, completed_at = :ca, "
                        " target_counts = :tc, completed_counts = :cc, "
                        " failed_counts = :fc, error_message = :em, "
                        " account_ids_used = :aiu"
                    ),
                    {
                        "tid": task.task_id,
                        "pu": task.post_url,
                        "pf": task.platform,
                        "uid": task.user_id,
                        "cfg": json.dumps(task.config, ensure_ascii=False),
                        "sa": _to_dt(task.scheduled_at),
                        "psa": _to_dt(task.planned_start_at),
                        "asa": _to_dt(task.actual_start_at),
                        "ca": _to_dt(task.completed_at),
                        "st": task.status,
                        "tc": json.dumps(task.target_counts, ensure_ascii=False),
                        "cc": json.dumps(task.completed_counts, ensure_ascii=False),
                        "fc": json.dumps(task.failed_counts, ensure_ascii=False),
                        "em": task.error_message,
                        "aiu": json.dumps(task.account_ids_used, ensure_ascii=False),
                    },
                )
            self._task_cache[task.task_id] = task
        except Exception as e:
            logger.warning(f"[InteractionScheduler] _persist_task failed: {e}")

    def _row_to_task(self, row) -> ScheduleTask:
        def _loads(s, default):
            if not s:
                return default
            try:
                return json.loads(s)
            except Exception:
                return default

        return ScheduleTask(
            task_id=row[0],
            post_url=row[1] or "",
            platform=row[2] or "",
            user_id=row[3],
            config=_loads(row[4], {}),
            scheduled_at=str(row[5]) if row[5] else None,
            planned_start_at=str(row[6]) if row[6] else None,
            actual_start_at=str(row[7]) if row[7] else None,
            completed_at=str(row[8]) if row[8] else None,
            status=row[9] or ScheduleTaskStatus.PENDING.value,
            target_counts=_loads(row[10], {}),
            completed_counts=_loads(row[11], {}),
            failed_counts=_loads(row[12], {}),
            error_message=row[13],
            account_ids_used=_loads(row[14], []),
        )

    # ============ 单例 ============

    def is_running(self) -> bool:
        return self._started


# ============ 单例 ============

_scheduler: Optional[InteractionScheduler] = None


def get_interaction_scheduler() -> InteractionScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = InteractionScheduler()
    return _scheduler
