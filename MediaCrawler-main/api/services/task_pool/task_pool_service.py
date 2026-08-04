# -*- coding: utf-8 -*-
"""
任务池 + 多轮触达调度服务

核心职责：
1. 统一管理所有来源的意向客户（评论监控/白名单/关键词/本地商家）
2. 多轮递进触达策略：Day1关注→Day2私信→Day3评论→直到客户回复
3. 去重机制：同一客户不重复触达同一阶段
4. 触达记录追踪

参考：知了系统的任务池 + 持续性互动策略
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 触达阶段定义
TOUCH_STAGES = {
    1: {"name": "关注", "action": "follow", "delay_hours": 0},
    2: {"name": "私信", "action": "dm", "delay_hours": 24},
    3: {"name": "评论", "action": "comment", "delay_hours": 48},
    4: {"name": "二触私信", "action": "dm_followup", "delay_hours": 72},
}


class TaskPoolService:
    """任务池服务（单例）"""

    _ensured = False
    _instance = None

    def __init__(self):
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "TaskPoolService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """创建 task_pool / touch_record 表"""
        if TaskPoolService._ensured:
            return
        try:
            engine = self._get_engine()
            if engine is None:
                return
            from sqlalchemy import text as sql_text

            async with engine.begin() as conn:
                # 任务池表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS task_pool ("
                        "  id SERIAL PRIMARY KEY,"
                        "  task_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  source VARCHAR(50) NOT NULL,"
                        "  platform VARCHAR(20) NOT NULL,"
                        "  customer_id VARCHAR(255) NOT NULL,"
                        "  customer_name VARCHAR(255) DEFAULT '',"
                        "  customer_url VARCHAR(500) DEFAULT '',"
                        "  comment_text TEXT DEFAULT '',"
                        "  video_id VARCHAR(255) DEFAULT '',"
                        "  video_title TEXT DEFAULT '',"
                        "  intent_type VARCHAR(50) DEFAULT '',"
                        "  lead_score INTEGER DEFAULT 0,"
                        "  matched_keywords TEXT DEFAULT '',"
                        "  current_stage INTEGER DEFAULT 1,"
                        "  status VARCHAR(20) DEFAULT 'pending',"
                        "  replied BOOLEAN DEFAULT FALSE,"
                        "  owner_user_id VARCHAR(64) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_task_pool_status "
                        "ON task_pool(status, current_stage)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_task_pool_dedup "
                        "ON task_pool(platform, customer_id, source)"
                    )
                )

                # 触达记录表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS touch_record ("
                        "  id SERIAL PRIMARY KEY,"
                        "  record_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  task_id VARCHAR(64) NOT NULL,"
                        "  stage INTEGER NOT NULL,"
                        "  action VARCHAR(50) NOT NULL,"
                        "  result VARCHAR(50) DEFAULT '',"
                        "  detail TEXT DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_touch_task "
                        "ON touch_record(task_id, stage)"
                    )
                )

            TaskPoolService._ensured = True
            logger.info("[TaskPool] 表创建完成")
        except Exception as e:
            logger.warning(f"[TaskPool] 建表失败(非致命): {e}")

    async def add_to_pool(
        self,
        source: str,
        platform: str,
        customer_id: str,
        customer_name: str = "",
        customer_url: str = "",
        comment_text: str = "",
        video_id: str = "",
        video_title: str = "",
        intent_type: str = "",
        lead_score: int = 0,
        matched_keywords: str = "",
        owner_user_id: str = "",
    ) -> Dict[str, Any]:
        """添加意向客户到任务池（自动去重）"""
        task_id = f"tp_{uuid.uuid4().hex[:12]}"
        now = int(time.time())

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO task_pool "
                        "(task_id, source, platform, customer_id, customer_name, customer_url, "
                        "comment_text, video_id, video_title, intent_type, lead_score, "
                        "matched_keywords, status, owner_user_id, created_at, updated_at) "
                        "VALUES (:tid, :src, :plat, :cid, :cname, :curl, "
                        ":ctext, :vid, :vtitle, :intent, :score, "
                        ":kw, 'pending', :owner, :now, :now) "
                        "ON CONFLICT (platform, customer_id, source) DO NOTHING"
                    ),
                    {
                        "tid": task_id,
                        "src": source,
                        "plat": platform,
                        "cid": customer_id,
                        "cname": customer_name,
                        "curl": customer_url,
                        "ctext": comment_text,
                        "vid": video_id,
                        "vtitle": video_title,
                        "intent": intent_type,
                        "score": lead_score,
                        "kw": matched_keywords,
                        "owner": owner_user_id,
                        "now": now,
                    },
                )

            logger.info(f"[TaskPool] 添加客户: {task_id} ({platform}/{customer_name}) 来源={source}")
            return {"ok": True, "task_id": task_id}
        except Exception as e:
            logger.warning(f"[TaskPool] 添加失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def batch_add_to_pool(
        self,
        customers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """批量添加意向客户到任务池（单次事务，减少数据库往返）

        Args:
            customers: 客户列表，每个元素需包含 source/platform/customer_id

        Returns:
            {"ok": True, "added": N, "skipped": M}
        """
        if not customers:
            return {"ok": True, "added": 0, "skipped": 0}

        now = int(time.time())
        added = 0
        skipped = 0

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                for cust in customers:
                    task_id = f"tp_{uuid.uuid4().hex[:12]}"
                    result = await conn.execute(
                        sql_text(
                            "INSERT INTO task_pool "
                            "(task_id, source, platform, customer_id, customer_name, customer_url, "
                            "comment_text, video_id, video_title, intent_type, lead_score, "
                            "matched_keywords, status, owner_user_id, created_at, updated_at) "
                            "VALUES (:tid, :src, :plat, :cid, :cname, :curl, "
                            ":ctext, :vid, :vtitle, :intent, :score, "
                            ":kw, 'pending', :owner, :now, :now) "
                            "ON CONFLICT (platform, customer_id, source) DO NOTHING"
                        ),
                        {
                            "tid": task_id,
                            "src": cust.get("source", "batch"),
                            "plat": cust.get("platform", ""),
                            "cid": cust.get("customer_id", ""),
                            "cname": cust.get("customer_name", ""),
                            "curl": cust.get("customer_url", ""),
                            "ctext": cust.get("comment_text", ""),
                            "vid": cust.get("video_id", ""),
                            "vtitle": cust.get("video_title", ""),
                            "intent": cust.get("intent_type", ""),
                            "score": cust.get("lead_score", 0),
                            "kw": cust.get("matched_keywords", ""),
                            "owner": cust.get("owner_user_id", ""),
                            "now": now,
                        },
                    )
                    # rowcount=1 表示插入成功，0 表示被 ON CONFLICT 跳过
                    if result.rowcount > 0:
                        added += 1
                    else:
                        skipped += 1

            logger.info(f"[TaskPool] 批量添加完成: added={added}, skipped={skipped}")
            return {"ok": True, "added": added, "skipped": skipped}
        except Exception as e:
            logger.warning(f"[TaskPool] 批量添加失败: {e}")
            return {"ok": False, "reason": str(e), "added": added, "skipped": skipped}

    async def get_next_touch_tasks(
        self,
        platform: Optional[str] = None,
        stage: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """获取待触达任务（按阶段筛选）"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []

            conditions = ["status = 'pending'", "replied = FALSE"]
            params: Dict[str, Any] = {"limit": limit}

            if platform:
                conditions.append("platform = :platform")
                params["platform"] = platform
            if stage is not None:
                conditions.append("current_stage = :stage")
                params["stage"] = stage

            where = " AND ".join(conditions)

            # 只读查询用 connect() 而非 begin()，避免不必要的事务开销
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT * FROM task_pool WHERE {where} "
                        "ORDER BY lead_score DESC, created_at ASC LIMIT :limit"
                    ),
                    params,
                )

            return [dict(r._mapping) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[TaskPool] 获取任务失败: {e}")
            return []

    async def advance_stage(self, task_id: str, new_stage: int, result: str = "") -> bool:
        """推进触达阶段"""
        if new_stage not in TOUCH_STAGES:
            logger.warning(f"[TaskPool] 无效阶段: {new_stage}")
            return False

        now = int(time.time())
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            stage_info = TOUCH_STAGES[new_stage]
            record_id = f"tr_{uuid.uuid4().hex[:12]}"

            # 单事务：更新任务 + 写入触达记录
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE task_pool SET current_stage = :stage, updated_at = :now "
                        "WHERE task_id = :tid"
                    ),
                    {"stage": new_stage, "now": now, "tid": task_id},
                )
                await conn.execute(
                    sql_text(
                        "INSERT INTO touch_record "
                        "(record_id, task_id, stage, action, result, created_at) "
                        "VALUES (:rid, :tid, :stage, :action, :result, :now)"
                    ),
                    {
                        "rid": record_id,
                        "tid": task_id,
                        "stage": new_stage,
                        "action": stage_info["action"],
                        "result": result,
                        "now": now,
                    },
                )

            logger.info(f"[TaskPool] 推进阶段: {task_id} → stage {new_stage} ({stage_info['name']})")
            return True
        except Exception as e:
            logger.warning(f"[TaskPool] 推进阶段失败: {e}")
            return False

    async def mark_replied(self, task_id: str) -> bool:
        """标记客户已回复"""
        now = int(time.time())
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE task_pool SET status = 'replied', replied = TRUE, updated_at = :now "
                        "WHERE task_id = :tid"
                    ),
                    {"now": now, "tid": task_id},
                )
            logger.info(f"[TaskPool] 标记已回复: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"[TaskPool] 标记回复失败: {e}")
            return False

    async def get_pool_stats(self, owner_user_id: str = "") -> Dict[str, Any]:
        """获取任务池统计（优化：单次查询替代4次，使用条件聚合）"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return {}

            params: Dict[str, Any] = {}
            owner_clause = ""
            if owner_user_id:
                owner_clause = " AND owner_user_id = :owner"
                params["owner"] = owner_user_id

            # 合并为单条 SQL：用 SUM(CASE...) 条件聚合替代 4 次独立查询
            async with engine.connect() as conn:
                row = await conn.execute(
                    sql_text(
                        "SELECT "
                        "  count(*) AS total, "
                        "  SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending, "
                        "  SUM(CASE WHEN replied = TRUE THEN 1 ELSE 0 END) AS replied "
                        "FROM task_pool WHERE 1=1" + owner_clause
                    ),
                    params,
                )
                stats_row = row.fetchone()

                # 阶段分布单独查（GROUP BY 无法合并到上面的聚合）
                stages = await conn.execute(
                    sql_text(
                        "SELECT current_stage, count(*) FROM task_pool "
                        "WHERE status='pending'" + owner_clause + " "
                        "GROUP BY current_stage"
                    ),
                    params,
                )

            stage_dist = {r[0]: r[1] for r in stages.fetchall()}

            return {
                "total": stats_row[0] if stats_row else 0,
                "pending": stats_row[1] if stats_row else 0,
                "replied": stats_row[2] if stats_row else 0,
                "stage_distribution": stage_dist,
            }
        except Exception as e:
            logger.warning(f"[TaskPool] 统计失败: {e}")
            return {}

    async def run_touch_scheduler(self) -> Dict[str, int]:
        """执行一轮触达调度：检查各阶段到期任务并推进"""
        now = int(time.time())
        results = {"advanced": 0, "replied": 0, "skipped": 0}

        for stage_num, stage_info in TOUCH_STAGES.items():
            tasks = await self.get_next_touch_tasks(stage=stage_num, limit=100)

            for task in tasks:
                created_at = task.get("created_at", 0)
                delay_seconds = stage_info["delay_hours"] * 3600

                # 检查是否到达触达时间
                if now - created_at < delay_seconds:
                    results["skipped"] += 1
                    continue

                # 推进到下一阶段
                next_stage = stage_num + 1
                if next_stage in TOUCH_STAGES:
                    ok = await self.advance_stage(task["task_id"], next_stage, "scheduled")
                    if ok:
                        results["advanced"] += 1
                else:
                    # 已达最大阶段，标记为待人工处理
                    await self.advance_stage(task["task_id"], stage_num, "max_stage_reached")

        return results


def get_task_pool_service() -> TaskPoolService:
    return TaskPoolService.get_instance()
