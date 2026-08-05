# -*- coding: utf-8 -*-
"""
评论监控核心服务

职责：
1. 任务 CRUD（comment_monitor_task 表）
2. 后台监控协程管理（_run_task_with_watchdog）
3. 评论抓取（account 模式 → fetch_user_posts 逐个抓；video 模式 → 直接抓）
4. 评论落库去重（comment_monitor_record 表 + 内存 set）
5. AI 意图识别 + 自动转 CustomerLead（评分 ≥ 50 且 is_lead）
6. 自动回复（复用 MultiInteractor + InteractionTask）
7. 启动时恢复 status=running 的任务（start_all_persistent_tasks）

参考实现：api/services/interactor/interaction_monitor.py 的 watchdog 模式。
"""
import asyncio
import json
import logging
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .lead_extractor import LeadExtractionResult, get_lead_extractor
from .platform_comment_fetcher import (
    CommentFetcherFactory,
    UnifiedComment,
)

logger = logging.getLogger(__name__)

# ============ 常量 ============
DEFAULT_CHECK_INTERVAL = 300  # 5 分钟
MAX_REPLY_PER_CYCLE = 5       # 每轮最多自动回复数（频次控制）
MAX_AI_BATCH = 8              # 单次 AI 批量调用上限
DEDUP_SET_LIMIT = 1000        # 内存去重 set 上限


class CommentMonitorService:
    """评论监控服务（单例）"""

    _ensured = False

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    def __init__(self):
        self._running_tasks: Dict[str, asyncio.Task] = {}  # task_id → asyncio.Task
        self._dedup_sets: Dict[str, set] = {}  # task_id → 已处理 comment_id 集合
        self._lock = asyncio.Lock()

    # ==================== 表初始化 ====================

    async def ensure_table(self) -> None:
        """创建 comment_monitor_task / comment_monitor_record 表"""
        if CommentMonitorService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                # 1. 监控任务表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS comment_monitor_task ("
                        "  id SERIAL PRIMARY KEY,"
                        "  task_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  platform VARCHAR(20) NOT NULL,"
                        "  monitor_type VARCHAR(20) NOT NULL,"  # account / video
                        "  target_id VARCHAR(255) NOT NULL,"
                        "  target_nickname VARCHAR(255) DEFAULT '',"
                        "  keywords TEXT DEFAULT '',"
                        "  enable_auto_reply BOOLEAN DEFAULT FALSE,"
                        "  enable_lead_extract BOOLEAN DEFAULT TRUE,"
                        "  check_interval INTEGER DEFAULT 300,"
                        "  max_comments_per_check INTEGER DEFAULT 100,"
                        "  status VARCHAR(20) DEFAULT 'pending',"
                        "  last_check_at BIGINT DEFAULT 0,"
                        "  last_check_new_count INTEGER DEFAULT 0,"
                        "  last_error TEXT DEFAULT '',"
                        "  owner_user_id VARCHAR(64) DEFAULT '' ,"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_cmt_task_owner "
                        "ON comment_monitor_task(owner_user_id, status)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_cmt_task_platform "
                        "ON comment_monitor_task(platform, monitor_type)"
                    )
                )

                # 2. 评论记录表（去重 + 审计）
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS comment_monitor_record ("
                        "  id SERIAL PRIMARY KEY,"
                        "  task_id VARCHAR(64) NOT NULL,"
                        "  platform VARCHAR(20) NOT NULL,"
                        "  comment_id VARCHAR(255) NOT NULL,"
                        "  comment_text TEXT DEFAULT '',"
                        "  author_id VARCHAR(255) DEFAULT '',"
                        "  author_nickname VARCHAR(255) DEFAULT '',"
                        "  author_sec_uid VARCHAR(255) DEFAULT '',"
                        "  author_avatar TEXT DEFAULT '',"
                        "  source_post_id VARCHAR(255) DEFAULT '',"
                        "  source_post_url TEXT DEFAULT '',"
                        "  parent_comment_id VARCHAR(255) DEFAULT '',"
                        "  like_count INTEGER DEFAULT 0,"
                        "  intent_type VARCHAR(50) DEFAULT '',"
                        "  lead_score INTEGER DEFAULT 0,"
                        "  matched_keywords TEXT DEFAULT '',"
                        "  is_replied BOOLEAN DEFAULT FALSE,"
                        "  reply_content TEXT DEFAULT '',"
                        "  converted_to_lead BOOLEAN DEFAULT FALSE,"
                        "  lead_id INTEGER DEFAULT 0,"
                        "  captured_at BIGINT DEFAULT 0,"
                        "  created_at BIGINT DEFAULT 0,"
                        "  UNIQUE(task_id, comment_id)"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_cmt_record_task "
                        "ON comment_monitor_record(task_id, created_at DESC)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_cmt_record_lead "
                        "ON comment_monitor_record(lead_score DESC, converted_to_lead)"
                    )
                )
            CommentMonitorService._ensured = True
            print("[comment_monitor] 表已就绪")
        except Exception as e:
            logger.warning(f"[comment_monitor] ensure_table failed: {e}")

    # ==================== 任务 CRUD ====================

    async def create_task(
        self,
        *,
        platform: str,
        monitor_type: str,
        target_id: str,
        target_nickname: str = "",
        keywords: str = "",
        enable_auto_reply: bool = False,
        enable_lead_extract: bool = True,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        max_comments_per_check: int = 100,
        owner_user_id: str = "",
    ) -> Dict:
        await self.ensure_table()
        task_id = f"cmt_{uuid.uuid4().hex[:12]}"
        now = int(time.time())
        row = {
            "task_id": task_id,
            "platform": platform,
            "monitor_type": monitor_type,
            "target_id": target_id,
            "target_nickname": target_nickname,
            "keywords": keywords,
            "enable_auto_reply": enable_auto_reply,
            "enable_lead_extract": enable_lead_extract,
            "check_interval": check_interval,
            "max_comments_per_check": max_comments_per_check,
            "status": "pending",
            "owner_user_id": owner_user_id,
            "created_at": now,
            "updated_at": now,
        }
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO comment_monitor_task "
                        "(task_id, platform, monitor_type, target_id, target_nickname, "
                        " keywords, enable_auto_reply, enable_lead_extract, "
                        " check_interval, max_comments_per_check, status, owner_user_id, "
                        " created_at, updated_at) "
                        "VALUES (:tid, :pf, :mt, :tgid, :tn, :kw, :ar, :le, :ci, :mc, "
                        " :st, :ouid, :ca, :ua)"
                    ),
                    {
                        "tid": row["task_id"],
                        "pf": row["platform"],
                        "mt": row["monitor_type"],
                        "tgid": row["target_id"],
                        "tn": row["target_nickname"],
                        "kw": row["keywords"],
                        "ar": row["enable_auto_reply"],
                        "le": row["enable_lead_extract"],
                        "ci": row["check_interval"],
                        "mc": row["max_comments_per_check"],
                        "st": row["status"],
                        "ouid": row["owner_user_id"],
                        "ca": row["created_at"],
                        "ua": row["updated_at"],
                    },
                )
        except Exception as e:
            logger.error(f"[comment_monitor] create_task failed: {e}")
            raise
        return row

    async def list_tasks(
        self,
        *,
        owner_user_id: str = "",
        platform: Optional[str] = None,
        status: Optional[str] = None,
        monitor_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        is_admin: bool = False,
    ) -> Dict:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = []
            params: Dict[str, Any] = {}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            if platform:
                conditions.append("platform = :pf")
                params["pf"] = platform
            if status:
                conditions.append("status = :st")
                params["st"] = status
            if monitor_type:
                conditions.append("monitor_type = :mt")
                params["mt"] = monitor_type
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

            async with engine.connect() as conn:
                # count
                cnt = await conn.execute(
                    sql_text(f"SELECT COUNT(*) FROM comment_monitor_task{where}"), params
                )
                total = int(cnt.fetchone()[0] or 0)
                # list
                offset = (page - 1) * page_size
                params["lim"] = page_size
                params["off"] = offset
                rows = await conn.execute(
                    sql_text(
                        f"SELECT task_id, platform, monitor_type, target_id, target_nickname, "
                        f" keywords, enable_auto_reply, enable_lead_extract, check_interval, "
                        f" max_comments_per_check, status, last_check_at, last_check_new_count, "
                        f" last_error, owner_user_id, created_at, updated_at "
                        f"FROM comment_monitor_task{where} "
                        f"ORDER BY created_at DESC LIMIT :lim OFFSET :off"
                    ),
                    params,
                )
                items = [self._row_to_task_dict(r) for r in rows.fetchall()]
            return {"total": total, "page": page, "page_size": page_size, "items": items}
        except Exception as e:
            logger.error(f"[comment_monitor] list_tasks failed: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "items": []}

    async def get_task(self, task_id: str, owner_user_id: str = "", is_admin: bool = False) -> Optional[Dict]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["task_id = :tid"]
            params = {"tid": task_id}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT task_id, platform, monitor_type, target_id, target_nickname, "
                        " keywords, enable_auto_reply, enable_lead_extract, check_interval, "
                        " max_comments_per_check, status, last_check_at, last_check_new_count, "
                        " last_error, owner_user_id, created_at, updated_at "
                        "FROM comment_monitor_task WHERE " + " AND ".join(conditions)
                    ),
                    params,
                )
                r = rows.fetchone()
                return self._row_to_task_dict(r) if r else None
        except Exception as e:
            logger.error(f"[comment_monitor] get_task failed: {e}")
            return None

    async def update_task(
        self,
        task_id: str,
        *,
        owner_user_id: str = "",
        is_admin: bool = False,
        **fields,
    ) -> bool:
        await self.ensure_table()
        allowed = {
            "target_nickname", "keywords", "enable_auto_reply",
            "enable_lead_extract", "check_interval", "max_comments_per_check",
            "status",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return False
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["task_id = :tid"]
            params: Dict[str, Any] = {"tid": task_id, "ua": int(time.time())}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            set_parts = []
            for k, v in updates.items():
                ph = f"_{k}"
                set_parts.append(f"{k} = :{ph}")
                params[ph] = v
            set_parts.append("updated_at = :ua")
            sql = (
                "UPDATE comment_monitor_task SET "
                + ", ".join(set_parts)
                + " WHERE " + " AND ".join(conditions)
            )
            async with engine.begin() as conn:
                res = await conn.execute(sql_text(sql), params)
                return res.rowcount > 0
        except Exception as e:
            logger.error(f"[comment_monitor] update_task failed: {e}")
            return False

    async def delete_task(self, task_id: str, owner_user_id: str = "", is_admin: bool = False) -> bool:
        await self.ensure_table()
        # 先停掉运行中的协程
        await self.stop_task(task_id, owner_user_id=owner_user_id, is_admin=is_admin)
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["task_id = :tid"]
            params = {"tid": task_id}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "DELETE FROM comment_monitor_record WHERE task_id = :tid"
                    ),
                    {"tid": task_id},
                )
                res = await conn.execute(
                    sql_text(
                        "DELETE FROM comment_monitor_task WHERE "
                        + " AND ".join(conditions)
                    ),
                    params,
                )
                return res.rowcount > 0
        except Exception as e:
            logger.error(f"[comment_monitor] delete_task failed: {e}")
            return False

    # ==================== 启停管理 ====================

    async def start_task(self, task_id: str, owner_user_id: str = "", is_admin: bool = False) -> bool:
        """启动监控任务（status 改 running + 后台协程）"""
        task = await self.get_task(task_id, owner_user_id=owner_user_id, is_admin=is_admin)
        if not task:
            return False
        if task_id in self._running_tasks and not self._running_tasks[task_id].done():
            return True  # 已在运行
        await self.update_task(
            task_id, owner_user_id=owner_user_id, is_admin=is_admin,
            status="running", last_error="",
        )
        # 启动后台协程
        t = asyncio.create_task(self._run_task_with_watchdog(task_id))
        self._running_tasks[task_id] = t
        logger.info(f"[comment_monitor] 任务已启动: {task_id}")
        return True

    async def stop_task(self, task_id: str, owner_user_id: str = "", is_admin: bool = False) -> bool:
        """停止监控任务"""
        t = self._running_tasks.pop(task_id, None)
        if t and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        await self.update_task(
            task_id, owner_user_id=owner_user_id, is_admin=is_admin, status="stopped"
        )
        # 清理去重 set
        self._dedup_sets.pop(task_id, None)
        logger.info(f"[comment_monitor] 任务已停止: {task_id}")
        return True

    def is_task_running(self, task_id: str) -> bool:
        t = self._running_tasks.get(task_id)
        return t is not None and not t.done()

    async def start_all_persistent_tasks(self) -> int:
        """应用启动时恢复所有 status=running 的任务（main.py startup 调用）"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT task_id FROM comment_monitor_task WHERE status = 'running'"
                    )
                )
                task_ids = [r[0] for r in rows.fetchall()]
            count = 0
            for tid in task_ids:
                try:
                    t = asyncio.create_task(self._run_task_with_watchdog(tid))
                    self._running_tasks[tid] = t
                    count += 1
                except Exception as e:
                    logger.warning(f"[comment_monitor] 恢复任务 {tid} 失败: {e}")
            if count:
                print(f"[comment_monitor] 已恢复 {count} 个监控任务")
            return count
        except Exception as e:
            logger.warning(f"[comment_monitor] start_all_persistent_tasks failed: {e}")
            return 0

    # ==================== 监控主循环 ====================

    async def _run_task_with_watchdog(self, task_id: str):
        """带 watchdog 自动重启的监控循环"""
        while True:
            try:
                await self._monitor_loop(task_id)
            except asyncio.CancelledError:
                logger.info(f"[comment_monitor] 监控协程被取消: {task_id}")
                break
            except Exception as e:
                logger.exception(f"[comment_monitor] 监控异常，10s 后重启 task={task_id}: {e}")
                await self._set_last_error(task_id, str(e)[:500])
                await asyncio.sleep(10)

    async def _monitor_loop(self, task_id: str):
        """单任务监控主循环"""
        task = await self.get_task(task_id)
        if not task:
            logger.warning(f"[comment_monitor] 任务不存在: {task_id}")
            return
        interval = max(60, int(task.get("check_interval") or DEFAULT_CHECK_INTERVAL))
        while True:
            # 检查是否仍 running（被手动 stop 后退出）
            cur = await self.get_task(task_id)
            if not cur or cur.get("status") != "running":
                logger.info(f"[comment_monitor] 任务 {task_id} 状态={cur.get('status') if cur else 'gone'}，退出循环")
                break
            try:
                await self._check_once(task_id)
            except Exception as e:
                logger.exception(f"[comment_monitor] _check_once 异常: {e}")
                await self._set_last_error(task_id, str(e)[:500])
            # 加抖动避免所有任务同时触发
            jitter = random.uniform(0, 30)
            await asyncio.sleep(interval + jitter)

    async def _check_once(self, task_id: str):
        """单次检查：抓评论 → 去重 → 落库 → AI识别 → 自动回复"""
        task = await self.get_task(task_id)
        if not task:
            return
        platform = task["platform"]
        monitor_type = task["monitor_type"]
        target_id = task["target_id"]
        keywords = [k.strip() for k in (task.get("keywords") or "").split(",") if k.strip()]
        owner_user_id = task.get("owner_user_id") or ""

        # 取 owner_user_id int
        try:
            uid_int = int(owner_user_id) if owner_user_id else None
        except Exception:
            uid_int = None

        try:
            fetcher = CommentFetcherFactory.create(platform, owner_user_id=uid_int)
        except NotImplementedError as e:
            await self._set_last_error(task_id, str(e)[:500])
            return

        # 抓取评论
        all_comments: List[UnifiedComment] = []
        if monitor_type == "account":
            all_comments = await self._check_account_comments(fetcher, target_id, task)
        else:  # video
            all_comments = await self._check_video_comments(fetcher, target_id, task)

        # 去重
        new_comments = await self._dedupe_comments(task_id, all_comments)
        if not new_comments:
            await self._update_check_status(task_id, 0, "")
            return

        # 落库 + AI 识别 + 自动回复
        await self._process_new_comments(task, new_comments, fetcher, keywords)
        await self._update_check_status(task_id, len(new_comments), "")

    async def _check_account_comments(
        self, fetcher, sec_user_id: str, task: Dict
    ) -> List[UnifiedComment]:
        """监控账号：先取最近视频，再逐个抓评论"""
        try:
            posts = await fetcher.fetch_user_posts(sec_user_id)
        except Exception as e:
            logger.warning(f"[comment_monitor] fetch_user_posts 失败: {e}")
            return []
        if not posts:
            return []
        all_comments: List[UnifiedComment] = []
        max_per = int(task.get("max_comments_per_check") or 100)
        # 限制每次最多检查 5 个最新视频（控制耗时）
        for post in posts[:5]:
            post_id = post.get("post_id", "")
            if not post_id:
                continue
            try:
                result = await fetcher.fetch_comments(post_id, max_count=max_per)
                if result and result.comments:
                    # 补 post_url
                    for c in result.comments:
                        if not c.post_url:
                            c.post_url = post.get("url", "")
                    all_comments.extend(result.comments)
            except Exception as e:
                logger.warning(f"[comment_monitor] 抓视频评论失败 post={post_id}: {e}")
        return all_comments

    async def _check_video_comments(
        self, fetcher, target_id: str, task: Dict
    ) -> List[UnifiedComment]:
        """监控单视频：直接抓评论"""
        max_per = int(task.get("max_comments_per_check") or 100)
        try:
            result = await fetcher.fetch_comments(target_id, max_count=max_per)
            return result.comments if result else []
        except Exception as e:
            logger.warning(f"[comment_monitor] fetch_comments 失败: {e}")
            return []

    async def _dedupe_comments(
        self, task_id: str, comments: List[UnifiedComment]
    ) -> List[UnifiedComment]:
        """去重：内存 set + 数据库 UNIQUE 兜底"""
        if not comments:
            return []
        s = self._dedup_sets.setdefault(task_id, set())
        new = []
        for c in comments:
            key = c.comment_id or f"{c.post_id}:{c.author_id}:{c.comment_text[:32]}"
            if not key:
                continue
            if key in s:
                continue
            s.add(key)
            new.append(c)
        # 内存 set 超限裁剪（保留最近 1000 条）
        if len(s) > DEDUP_SET_LIMIT:
            self._dedup_sets[task_id] = set(list(s)[-DEDUP_SET_LIMIT:])
        return new

    async def _process_new_comments(
        self,
        task: Dict,
        comments: List[UnifiedComment],
        fetcher,
        keywords: List[str],
    ):
        """新评论落库 + AI 识别 + 转 CustomerLead + 自动回复"""
        task_id = task["task_id"]
        platform = task["platform"]
        enable_lead = bool(task.get("enable_lead_extract"))
        enable_reply = bool(task.get("enable_auto_reply"))
        owner_user_id = task.get("owner_user_id") or ""

        # AI 批量识别（仅 enable_lead 时）
        lead_results: Dict[str, LeadExtractionResult] = {}
        if enable_lead and comments:
            try:
                extractor = get_lead_extractor()
                # 分批调用 AI（每批 ≤ MAX_AI_BATCH）
                for i in range(0, len(comments), MAX_AI_BATCH):
                    batch = comments[i: i + MAX_AI_BATCH]
                    results = await extractor.extract_batch(
                        batch, keywords=keywords, post_title=task.get("target_nickname", "")
                    )
                    for j, c in enumerate(batch):
                        if j < len(results):
                            lead_results[c.comment_id] = results[j]
                    # 单任务每轮最多 AI 调用 5 次（5 * 8 = 40 条上限）
                    if i // MAX_AI_BATCH >= 4:
                        break
            except Exception as e:
                logger.warning(f"[comment_monitor] AI 批量识别失败: {e}")

        # 落库评论记录
        replied_count = 0
        for c in comments:
            lr = lead_results.get(c.comment_id)
            intent_type = lr.intent_type if lr else ""
            lead_score = lr.lead_score if lr else 0
            matched_kw = ",".join(lr.matched_keywords) if lr else ""
            is_lead = lr.is_lead if lr else False

            # 转 CustomerLead（评分 ≥ 50 且 is_lead）
            lead_id = 0
            if is_lead and lead_score >= 50:
                try:
                    lead_id = await self._convert_to_lead(
                        task=task, comment=c,
                        intent_type=intent_type, lead_score=lead_score,
                        matched_keywords=matched_kw,
                    )
                except Exception as e:
                    logger.warning(f"[comment_monitor] 转 CustomerLead 失败: {e}")

            # 自动回复（优先回复高意向评论）
            reply_content = ""
            is_replied = False
            if enable_reply and replied_count < MAX_REPLY_PER_CYCLE:
                # 优先：is_lead 或 命中关键词
                should_reply = is_lead or bool(matched_kw)
                if should_reply:
                    reply = await self._generate_reply(c, task)
                    if reply:
                        ok = await self._send_reply(fetcher, c, reply, task)
                        if ok:
                            reply_content = reply
                            is_replied = True
                            replied_count += 1
                            await asyncio.sleep(random.uniform(3, 8))  # 风控规避

            # 落库 record
            await self._save_record(
                task_id=task_id, platform=platform, comment=c,
                intent_type=intent_type, lead_score=lead_score,
                matched_keywords=matched_kw,
                is_replied=is_replied, reply_content=reply_content,
                converted_to_lead=(lead_id > 0), lead_id=lead_id,
            )

    # ==================== 辅助：评论记录 / 线索 / 回复 ====================

    async def _save_record(
        self,
        *,
        task_id: str,
        platform: str,
        comment: UnifiedComment,
        intent_type: str,
        lead_score: int,
        matched_keywords: str,
        is_replied: bool,
        reply_content: str,
        converted_to_lead: bool,
        lead_id: int,
    ) -> None:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            now = int(time.time())
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO comment_monitor_record "
                        "(task_id, platform, comment_id, comment_text, author_id, "
                        " author_nickname, author_sec_uid, author_avatar, source_post_id, "
                        " source_post_url, parent_comment_id, like_count, intent_type, "
                        " lead_score, matched_keywords, is_replied, reply_content, "
                        " converted_to_lead, lead_id, captured_at, created_at) "
                        "VALUES (:tid, :pf, :cid, :ct, :aid, :an, :asid, :av, :spid, :spu, "
                        " :pcid, :lc, :it, :ls, :mk, :ir, :rc, :cl, :lid, :cat, :ca) "
                        "ON CONFLICT (task_id, comment_id) DO NOTHING"
                    ),
                    {
                        "tid": task_id, "pf": platform,
                        "cid": comment.comment_id, "ct": comment.comment_text,
                        "aid": comment.author_id, "an": comment.author_nickname,
                        "asid": comment.author_sec_uid, "av": comment.author_avatar,
                        "spid": comment.post_id, "spu": comment.post_url,
                        "pcid": comment.parent_comment_id,
                        "lc": comment.like_count,
                        "it": intent_type, "ls": lead_score,
                        "mk": matched_keywords,
                        "ir": is_replied, "rc": reply_content,
                        "cl": converted_to_lead, "lid": lead_id,
                        "cat": comment.created_ts or now,
                        "ca": now,
                    },
                )
        except Exception as e:
            logger.warning(f"[comment_monitor] _save_record 失败: {e}")

    async def _convert_to_lead(
        self,
        *,
        task: Dict,
        comment: UnifiedComment,
        intent_type: str,
        lead_score: int,
        matched_keywords: str,
    ) -> int:
        """插入 customer_lead 表（复用现有模型），返回 lead id"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            now = int(time.time())
            platform = task["platform"]
            owner_user_id = task.get("owner_user_id") or ""
            async with engine.begin() as conn:
                # 检查是否已存在（避免重复转）
                existing = await conn.execute(
                    sql_text(
                        "SELECT id FROM customer_lead "
                        "WHERE platform = :pf AND data_id = :did "
                        "AND owner_user_id = :ouid LIMIT 1"
                    ),
                    {"pf": platform, "did": comment.comment_id, "ouid": owner_user_id},
                )
                row = existing.fetchone()
                if row:
                    return int(row[0])
                # 平台映射 data_type
                data_type_map = {
                    "douyin": "comment", "xhs": "comment", "ks": "comment",
                    "bili": "comment", "wb": "comment",
                }
                # comment_url / profile_url（已知字段）
                comment_url = comment.post_url or ""
                profile_url = ""
                if comment.author_sec_uid:
                    if platform == "douyin":
                        profile_url = f"https://www.douyin.com/user/{comment.author_sec_uid}"
                    elif platform == "xhs":
                        profile_url = f"https://www.xiaohongshu.com/user/profile/{comment.author_sec_uid}"
                result = await conn.execute(
                    sql_text(
                        "INSERT INTO customer_lead "
                        "(task_id, platform, data_type, data_id, user_id, sec_uid, "
                        " nickname, avatar, content, title, url, matched_keywords, "
                        " intent_type, lead_score, status, add_ts, last_modify_ts, "
                        " create_time, owner_user_id, source_aweme_id, comment_url, "
                        " profile_url) "
                        "VALUES (:tid, :pf, :dt, :did, :uid, :suid, :nk, :av, :ct, :tt, :url, "
                        " :mk, :it, :ls, 'new', :now, :now, :ct2, :ouid, :said, :curl, :purl) "
                        "RETURNING id"
                    ),
                    {
                        "tid": task["task_id"], "pf": platform,
                        "dt": data_type_map.get(platform, "comment"),
                        "did": comment.comment_id,
                        "uid": comment.author_id, "suid": comment.author_sec_uid,
                        "nk": comment.author_nickname, "av": comment.author_avatar,
                        "ct": comment.comment_text,
                        "tt": task.get("target_nickname", "") or "",
                        "url": comment.post_url,
                        "mk": matched_keywords,
                        "it": intent_type, "ls": lead_score,
                        "now": now,
                        "ct2": comment.created_ts or now,
                        "ouid": owner_user_id,
                        "said": comment.post_id,
                        "curl": comment_url, "purl": profile_url,
                    },
                )
                r = result.fetchone()
                return int(r[0]) if r else 0
        except Exception as e:
            logger.warning(f"[comment_monitor] _convert_to_lead 失败: {e}")
            return 0

    async def _generate_reply(self, comment: UnifiedComment, task: Dict) -> Optional[str]:
        """调用 AI 生成自然回复

        优先级：
        1. 云客 AI 客服（YunkeClient，对接 122.51.51.177:8063）—— 可用则用
        2. 本地 AI Agent Client —— 兜底
        """
        # ---- 1. 优先：云客 AI 客服 ----
        try:
            from api.services.ai_customer_service.yunke_client import get_yunke_client
            yunke = get_yunke_client()
            if yunke.is_configured():
                context_lines = [
                    f"【场景】我方在 {task['platform']} 平台发布视频，收到一条用户评论，请帮我生成一条简短、自然、有人情味的回复（不超过80字，不要硬广，可适当引导关注或私信）。",
                    f"【视频/笔记标题】{task.get('target_nickname', '')}",
                    f"【用户评论】{comment.comment_text}",
                    f"【要求】直接输出回复内容，不要解释，不要带'我是AI'之类话术。",
                ]
                question = "\n".join(context_lines)
                result = await yunke.ask(question=question, max_poll_seconds=20.0)
                if result.get("ok"):
                    answer = (result.get("answer") or "").strip()
                    if answer:
                        logger.info(
                            f"[comment_monitor] Yunke 生成回复 comment_id={comment.comment_id}"
                        )
                        return answer
                else:
                    logger.debug(
                        f"[comment_monitor] Yunke 未返回回复，回退本地AI: {result.get('error')}"
                    )
        except Exception as e:
            logger.warning(f"[comment_monitor] Yunke 调用异常，回退本地AI: {e}")

        # ---- 2. 兜底：本地 AI Agent ----
        try:
            from api.services.ai_agent_client import (
                get_ai_agent_client,
                is_ai_in_cooldown,
                is_ai_expected_error,
            )

            if is_ai_in_cooldown():
                return None
            prompt = (
                f"有人在{task['platform']}视频下评论了：\n"
                f"对方说：{comment.comment_text}\n"
                f"请生成一条简短、自然、有人情味的回复（不超过50字），"
                f"不要硬广，可以适当引导关注或咨询。直接输出回复内容，不要解释。"
            )
            client = get_ai_agent_client()
            reply = await client.generate_text(prompt)
            return reply.strip() if reply else None
        except Exception as e:
            try:
                from api.services.ai_agent_client import is_ai_expected_error
                if is_ai_expected_error(e):
                    logger.debug(f"[comment_monitor] AI 预期内错误跳过回复: {e}")
                else:
                    logger.warning(f"[comment_monitor] AI 生成回复失败: {e}")
            except Exception:
                pass
            return None

    async def _send_reply(
        self, fetcher, comment: UnifiedComment, reply: str, task: Dict
    ) -> bool:
        """通过 MultiInteractor 发送评论回复"""
        try:
            from api.services.interactor.interaction_models import (
                InteractionTask, InteractionType,
            )
            from api.services.interactor.multi_interactor import get_multi_interactor

            # 平台名映射 → interactor 平台
            platform_map = {
                "douyin": "douyin", "xhs": "xhs", "ks": "ks",
                "bili": "bili", "wb": "wb",
            }
            interactor_platform = platform_map.get(task["platform"])
            if not interactor_platform:
                return False

            target_url = comment.post_url or ""
            if not target_url:
                return False

            try:
                uid_int = int(task.get("owner_user_id") or 0) or None
            except Exception:
                uid_int = None

            itask = InteractionTask(
                interaction_type=InteractionType.REPLY.value,
                target_url=target_url,
                target_id=comment.comment_id,
                content=reply,
                target_platforms=[interactor_platform],
                user_id=uid_int,
                task_id=f"cmt_reply_{uuid.uuid4().hex[:8]}",
            )
            interactor = get_multi_interactor()
            result = await interactor.interact_across_platforms(
                itask, use_account_pool=True
            )
            pr = result.platform_results.get(interactor_platform)
            return bool(pr and pr.success)
        except Exception as e:
            logger.warning(f"[comment_monitor] _send_reply 失败: {e}")
            return False

    # ==================== 状态更新 ====================

    async def _update_check_status(self, task_id: str, new_count: int, error: str):
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE comment_monitor_task "
                        "SET last_check_at = :now, last_check_new_count = :nc, "
                        "    last_error = :err, updated_at = :now "
                        "WHERE task_id = :tid"
                    ),
                    {
                        "tid": task_id, "nc": new_count,
                        "err": error, "now": int(time.time()),
                    },
                )
        except Exception as e:
            logger.warning(f"[comment_monitor] _update_check_status 失败: {e}")

    async def _set_last_error(self, task_id: str, err: str):
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE comment_monitor_task "
                        "SET last_error = :err, updated_at = :now WHERE task_id = :tid"
                    ),
                    {"tid": task_id, "err": err, "now": int(time.time())},
                )
        except Exception:
            pass

    # ==================== 抓取记录查询 ====================

    async def list_records(
        self,
        task_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        only_lead: bool = False,
        min_score: int = 0,
        owner_user_id: str = "",
        is_admin: bool = False,
    ) -> Dict:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["r.task_id = :tid"]
            params: Dict[str, Any] = {"tid": task_id}
            # owner 隔离：通过 join task 表
            if not is_admin and owner_user_id:
                conditions.append("t.owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            if only_lead:
                conditions.append("r.converted_to_lead = TRUE")
            if min_score > 0:
                conditions.append("r.lead_score >= :ms")
                params["ms"] = min_score
            where = " AND ".join(conditions)
            async with engine.connect() as conn:
                cnt = await conn.execute(
                    sql_text(
                        f"SELECT COUNT(*) FROM comment_monitor_record r "
                        f"JOIN comment_monitor_task t ON t.task_id = r.task_id "
                        f"WHERE {where}"
                    ),
                    params,
                )
                total = int(cnt.fetchone()[0] or 0)
                offset = (page - 1) * page_size
                params["lim"] = page_size
                params["off"] = offset
                rows = await conn.execute(
                    sql_text(
                        f"SELECT r.id, r.task_id, r.platform, r.comment_id, r.comment_text, "
                        f" r.author_id, r.author_nickname, r.author_sec_uid, r.author_avatar, "
                        f" r.source_post_id, r.source_post_url, r.parent_comment_id, "
                        f" r.like_count, r.intent_type, r.lead_score, r.matched_keywords, "
                        f" r.is_replied, r.reply_content, r.converted_to_lead, r.lead_id, "
                        f" r.captured_at, r.created_at "
                        f"FROM comment_monitor_record r "
                        f"JOIN comment_monitor_task t ON t.task_id = r.task_id "
                        f"WHERE {where} "
                        f"ORDER BY r.created_at DESC LIMIT :lim OFFSET :off"
                    ),
                    params,
                )
                items = []
                for r in rows.fetchall():
                    items.append({
                        "id": r[0], "task_id": r[1], "platform": r[2],
                        "comment_id": r[3], "comment_text": r[4],
                        "author_id": r[5], "author_nickname": r[6],
                        "author_sec_uid": r[7], "author_avatar": r[8],
                        "source_post_id": r[9], "source_post_url": r[10],
                        "parent_comment_id": r[11], "like_count": r[12],
                        "intent_type": r[13], "lead_score": r[14],
                        "matched_keywords": r[15],
                        "is_replied": bool(r[16]), "reply_content": r[17],
                        "converted_to_lead": bool(r[18]), "lead_id": r[19],
                        "captured_at": r[20], "created_at": r[21],
                    })
            return {"total": total, "page": page, "page_size": page_size, "items": items}
        except Exception as e:
            logger.error(f"[comment_monitor] list_records failed: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "items": []}

    async def get_task_stats(self, task_id: str, owner_user_id: str = "", is_admin: bool = False) -> Dict:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["r.task_id = :tid"]
            params: Dict[str, Any] = {"tid": task_id}
            if not is_admin and owner_user_id:
                conditions.append("t.owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            where = " AND ".join(conditions)
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT "
                        f" COUNT(*) AS total, "
                        f" COUNT(*) FILTER (WHERE converted_to_lead = TRUE) AS lead_count, "
                        f" COUNT(*) FILTER (WHERE is_replied = TRUE) AS replied_count, "
                        f" AVG(lead_score)::float AS avg_score, "
                        f" MAX(lead_score) AS max_score "
                        f"FROM comment_monitor_record r "
                        f"JOIN comment_monitor_task t ON t.task_id = r.task_id "
                        f"WHERE {where}"
                    ),
                    params,
                )
                r = rows.fetchone()
                return {
                    "task_id": task_id,
                    "total_comments": int(r[0] or 0),
                    "total_leads": int(r[1] or 0),
                    "total_replied": int(r[2] or 0),
                    "avg_lead_score": round(float(r[3] or 0), 1),
                    "max_lead_score": int(r[4] or 0),
                }
        except Exception as e:
            logger.error(f"[comment_monitor] get_task_stats failed: {e}")
            return {
                "task_id": task_id, "total_comments": 0, "total_leads": 0,
                "total_replied": 0, "avg_lead_score": 0, "max_lead_score": 0,
            }

    async def check_now(self, task_id: str, owner_user_id: str = "", is_admin: bool = False) -> bool:
        """立即触发一次检查（不等待下次轮询）"""
        task = await self.get_task(task_id, owner_user_id=owner_user_id, is_admin=is_admin)
        if not task:
            return False
        asyncio.create_task(self._check_once(task_id))
        return True

    # ==================== 工具 ====================

    @staticmethod
    def _row_to_task_dict(r) -> Dict:
        if r is None:
            return {}
        return {
            "task_id": r[0], "platform": r[1], "monitor_type": r[2],
            "target_id": r[3], "target_nickname": r[4], "keywords": r[5],
            "enable_auto_reply": bool(r[6]), "enable_lead_extract": bool(r[7]),
            "check_interval": r[8], "max_comments_per_check": r[9],
            "status": r[10], "last_check_at": r[11],
            "last_check_new_count": r[12], "last_error": r[13],
            "owner_user_id": r[14], "created_at": r[15], "updated_at": r[16],
        }


# ============ 单例 ============
_comment_monitor_service: Optional[CommentMonitorService] = None


def get_comment_monitor_service() -> CommentMonitorService:
    global _comment_monitor_service
    if _comment_monitor_service is None:
        _comment_monitor_service = CommentMonitorService()
    return _comment_monitor_service
