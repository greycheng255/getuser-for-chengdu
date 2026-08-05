# -*- coding: utf-8 -*-
"""
即时发布记录持久化（任务 P2-1）

仅定时发布任务此前有 scheduled_publish_tasks 表留存；即时发布
POST /api/publish/multi-platform 没有持久化。本模块补齐该缺口：

表 publish_records：
- record_id      SERIAL PK
- task_id        VARCHAR(64)   关联 BatchVideoTask 或 UUID
- platform       VARCHAR(32)
- account_id     BIGINT
- title          VARCHAR(500)
- content        TEXT
- video_path     TEXT
- post_url       TEXT          发布后的链接
- platform_id    VARCHAR(128)  平台返回的帖子 ID（tweet_id / note_id 等）
- status         VARCHAR(32)   success / failed / skipped
- error_message  TEXT
- owner_user_id  BIGINT
- source_post_id VARCHAR(128)  素材溯源
- published_at   TIMESTAMPTZ DEFAULT NOW()
- metadata       JSONB

方法：ensure_table / save_record / list_records / get_record
单例：get_publish_records_store()
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PublishRecordsStore:
    """即时发布记录存储（异步 PostgreSQL）"""

    TABLE_NAME = "publish_records"
    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """幂等建表"""
        if PublishRecordsStore._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        f"CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} ("
                        "  record_id SERIAL PRIMARY KEY,"
                        "  task_id VARCHAR(64),"
                        "  platform VARCHAR(32) NOT NULL,"
                        "  account_id BIGINT,"
                        "  title VARCHAR(500),"
                        "  content TEXT,"
                        "  video_path TEXT,"
                        "  post_url TEXT,"
                        "  platform_id VARCHAR(128),"
                        "  status VARCHAR(32) NOT NULL,"
                        "  error_code VARCHAR(32),"
                        "  error_message TEXT,"
                        "  retryable BOOLEAN DEFAULT FALSE,"
                        "  started_at TIMESTAMPTZ,"
                        "  finished_at TIMESTAMPTZ,"
                        "  owner_user_id BIGINT,"
                        "  source_post_id VARCHAR(128),"
                        "  published_at TIMESTAMPTZ DEFAULT NOW(),"
                        "  metadata JSONB)"
                    )
                )
                for column_ddl in (
                    "error_code VARCHAR(32)",
                    "retryable BOOLEAN DEFAULT FALSE",
                    "started_at TIMESTAMPTZ",
                    "finished_at TIMESTAMPTZ",
                ):
                    await conn.execute(sql_text(
                        f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN IF NOT EXISTS {column_ddl}"
                    ))
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_publish_records_platform "
                        f"ON {self.TABLE_NAME} (platform)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_publish_records_status "
                        f"ON {self.TABLE_NAME} (status)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_publish_records_owner "
                        f"ON {self.TABLE_NAME} (owner_user_id)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_publish_records_published_at "
                        f"ON {self.TABLE_NAME} (published_at)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_publish_records_task_id "
                        f"ON {self.TABLE_NAME} (task_id)"
                    )
                )
            PublishRecordsStore._ensured = True
        except Exception as e:
            logger.warning(f"[PublishRecordsStore] ensure_table failed: {e}")

    async def save_record(
        self,
        *,
        task_id: Optional[str] = None,
        platform: str,
        account_id: Optional[int] = None,
        title: str = "",
        content: str = "",
        video_path: Optional[str] = None,
        post_url: Optional[str] = None,
        platform_id: Optional[str] = None,
        status: str = "success",  # success / failed / skipped
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        retryable: bool = False,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        owner_user_id: Optional[int] = None,
        source_post_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        published_at: Optional[datetime] = None,
    ) -> Optional[int]:
        """保存一条发布记录，返回 record_id（失败返回 None，不抛异常）"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None

            task_id = task_id or str(uuid.uuid4())
            metadata_str = json.dumps(metadata or {}, ensure_ascii=False)
            published_at_val = published_at or datetime.utcnow()

            async with engine.begin() as conn:
                rows = await conn.execute(
                    sql_text(
                        "INSERT INTO publish_records "
                        "(task_id, platform, account_id, title, content, video_path, "
                        " post_url, platform_id, status, error_message, owner_user_id, "
                        " source_post_id, published_at, metadata, error_code, retryable, "
                        " started_at, finished_at) "
                        "VALUES (:tid, :pf, :aid, :title, :content, :vp, :pu, :pid, "
                        "        :st, :em, :ouid, :spid, :pa, :md, :ec, :retry, :sa, :fa) "
                        "RETURNING record_id"
                    ),
                    {
                        "tid": task_id,
                        "pf": platform,
                        "aid": account_id,
                        "title": (title or "")[:500],
                        "content": content or "",
                        "vp": video_path,
                        "pu": post_url,
                        "pid": platform_id,
                        "st": status,
                        "em": (error_message or "")[:4000] if error_message else None,
                        "ec": error_code,
                        "retry": bool(retryable),
                        "sa": started_at,
                        "fa": finished_at,
                        "ouid": owner_user_id,
                        "spid": source_post_id,
                        "pa": published_at_val,
                        "md": metadata_str,
                    },
                )
                row = rows.fetchone()
                if row is None:
                    return None
                return int(row[0])
        except Exception as e:
            logger.warning(f"[PublishRecordsStore] save_record failed: {e}")
            return None

    async def list_records(
        self,
        *,
        platform: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询发布记录列表"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []

            where_parts: List[str] = []
            params: Dict[str, Any] = {"limit": limit, "offset": offset}
            if platform:
                where_parts.append("platform = :pf")
                params["pf"] = platform
            if status:
                where_parts.append("status = :st")
                params["st"] = status
            if user_id is not None:
                where_parts.append("owner_user_id = :ouid")
                params["ouid"] = user_id
            if start_date:
                where_parts.append("published_at >= :sd")
                params["sd"] = start_date
            if end_date:
                where_parts.append("published_at < :ed")
                params["ed"] = end_date
            where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            sql = (
                "SELECT record_id, task_id, platform, account_id, title, content, "
                "  video_path, post_url, platform_id, status, error_message, "
                "  owner_user_id, source_post_id, published_at, metadata, error_code, "
                "  retryable, started_at, finished_at "
                f"FROM {self.TABLE_NAME} {where_sql} "
                "ORDER BY published_at DESC LIMIT :limit OFFSET :offset"
            )
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[PublishRecordsStore] list_records failed: {e}")
            return []

    async def get_record(self, record_id: int) -> Optional[Dict[str, Any]]:
        """获取单条发布记录"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT record_id, task_id, platform, account_id, title, content, "
                        "  video_path, post_url, platform_id, status, error_message, "
                        "  owner_user_id, source_post_id, published_at, metadata, error_code, "
                        "  retryable, started_at, finished_at "
                        f"FROM {self.TABLE_NAME} WHERE record_id = :rid"
                    ),
                    {"rid": record_id},
                )
                row = rows.fetchone()
                if row is None:
                    return None
                return self._row_to_dict(row)
        except Exception as e:
            logger.warning(f"[PublishRecordsStore] get_record failed: {e}")
            return None

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        """数据库行转 dict（兼容 Row._mapping）"""
        r = row._mapping if hasattr(row, "_mapping") else dict(row)
        metadata = r.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                pass
        published_at = r.get("published_at")
        if hasattr(published_at, "isoformat"):
            published_at = published_at.isoformat()
        return {
            "id": r.get("record_id"),
            "record_id": r.get("record_id"),
            "task_id": r.get("task_id"),
            "platform": r.get("platform"),
            "account_id": r.get("account_id"),
            "title": r.get("title"),
            "content": r.get("content"),
            "video_path": r.get("video_path"),
            "post_url": r.get("post_url"),
            "platform_id": r.get("platform_id"),
            "status": r.get("status"),
            "error_message": r.get("error_message"),
            "error_code": r.get("error_code"),
            "retryable": bool(r.get("retryable")),
            "started_at": r.get("started_at").isoformat() if hasattr(r.get("started_at"), "isoformat") else r.get("started_at"),
            "finished_at": r.get("finished_at").isoformat() if hasattr(r.get("finished_at"), "isoformat") else r.get("finished_at"),
            "owner_user_id": r.get("owner_user_id"),
            "source_post_id": r.get("source_post_id"),
            "published_at": published_at,
            "metadata": metadata if isinstance(metadata, dict) else {},
        }


# ============ 单例 ============

_store: Optional[PublishRecordsStore] = None


def get_publish_records_store() -> PublishRecordsStore:
    global _store
    if _store is None:
        _store = PublishRecordsStore()
    return _store
