# -*- coding: utf-8 -*-
"""
内容日历服务

迁移自 GEO-main/geo_system/backend/content_calendar_service.py，适配：
1. 异步 + PostgreSQL（原为同步 sqlite3）
2. 简化数据模型，聚焦发布日历 / 内容计划

对应 PRD 5.3 发布策略 - 发布队列（可视化发布日历）。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContentStatus(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ContentItem:
    id: Optional[int] = None
    title: str = ""
    content: str = ""
    content_type: str = "article"  # article / video / image
    status: str = ContentStatus.DRAFT.value
    priority: str = "medium"  # low / medium / high
    planned_date: Optional[datetime] = None
    target_platforms: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ContentCalendarService:
    """内容日历服务（异步）"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self):
        if ContentCalendarService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS content_calendar ("
                        "  id SERIAL PRIMARY KEY,"
                        "  title VARCHAR(256),"
                        "  content TEXT,"
                        "  content_type VARCHAR(32),"
                        "  status VARCHAR(16) DEFAULT 'draft',"
                        "  priority VARCHAR(16) DEFAULT 'medium',"
                        "  planned_date TIMESTAMP,"
                        "  target_platforms VARCHAR(256),"
                        "  tags VARCHAR(256),"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  updated_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
            ContentCalendarService._ensured = True
        except Exception as e:
            logger.warning(f"[Calendar] 建表失败: {e}")

    async def create_item(self, item: ContentItem) -> Optional[int]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                row = await conn.execute(
                    sql_text(
                        "INSERT INTO content_calendar "
                        "(title, content, content_type, status, priority, planned_date, "
                        "target_platforms, tags) "
                        "VALUES (:t, :c, :ct, :s, :p, :pd, :tp, :tg) RETURNING id"
                    ),
                    {
                        "t": item.title[:256],
                        "c": item.content,
                        "ct": item.content_type,
                        "s": item.status,
                        "p": item.priority,
                        "pd": item.planned_date,
                        "tp": ",".join(item.target_platforms),
                        "tg": ",".join(item.tags),
                    },
                )
                r = row.fetchone()
                return r[0] if r else None
        except Exception as e:
            logger.error(f"[Calendar] 创建内容失败: {e}")
            return None

    async def list_items(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        status: str = "",
    ) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            conditions = []
            params: Dict[str, Any] = {}
            if start_date:
                conditions.append("planned_date>=:sd")
                params["sd"] = start_date
            if end_date:
                conditions.append("planned_date<:ed")
                params["ed"] = end_date
            if status:
                conditions.append("status=:s")
                params["s"] = status
            sql = "SELECT id, title, content, content_type, status, priority, planned_date, target_platforms, tags FROM content_calendar"
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY planned_date ASC NULLS LAST, id DESC LIMIT 200"
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                return [
                    {
                        "id": r[0],
                        "title": r[1],
                        "content": r[2],
                        "content_type": r[3],
                        "status": r[4],
                        "priority": r[5],
                        "planned_date": str(r[6]) if r[6] else None,
                        "target_platforms": (r[7] or "").split(",") if r[7] else [],
                        "tags": (r[8] or "").split(",") if r[8] else [],
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[Calendar] 查询失败: {e}")
            return []

    async def update_status(self, item_id: int, status: str) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE content_calendar SET status=:s, updated_at=NOW() WHERE id=:i"
                    ),
                    {"s": status, "i": item_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[Calendar] 更新状态失败: {e}")
            return False

    async def get_calendar_view(self, year: int, month: int) -> Dict[str, Any]:
        """获取月度日历视图"""
        start = datetime(year, month, 1)
        end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        items = await self.list_items(start_date=start, end_date=end)
        days: Dict[int, List[Dict]] = {}
        for it in items:
            if it["planned_date"]:
                # 解析日期
                try:
                    d = datetime.fromisoformat(it["planned_date"].replace("Z", ""))
                    day = d.day
                    days.setdefault(day, []).append(
                        {
                            "id": it["id"],
                            "title": it["title"],
                            "status": it["status"],
                            "priority": it["priority"],
                        }
                    )
                except Exception:
                    continue
        return {"year": year, "month": month, "days": days}

    async def get_upcoming(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取未来 N 天的内容计划"""
        start = datetime.utcnow()
        end = start + timedelta(days=days)
        return await self.list_items(start_date=start, end_date=end)


_calendar: Optional[ContentCalendarService] = None


def get_content_calendar() -> ContentCalendarService:
    global _calendar
    if _calendar is None:
        _calendar = ContentCalendarService()
    return _calendar
