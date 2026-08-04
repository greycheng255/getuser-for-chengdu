# -*- coding: utf-8 -*-
"""
舆情监控服务

迁移自 GEO-main/geo_system/backend/sentiment_monitor_service.py，适配：
1. 异步（原为同步 sqlite3）
2. MediaCrawler 的 get_async_engine（原为独立 db_path）
3. 简化数据模型，聚焦品牌舆情预警

对应 PRD 5.6 风控合规 - 账号风控 / 舆情监控。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SentimentType(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    CRITICAL = "critical"


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    DANGER = "danger"
    CRITICAL = "critical"


# 负面情感关键词（简易规则，可扩展为 AI 分类）
NEGATIVE_KEYWORDS = [
    "差评", "垃圾", "骗子", "投诉", "维权", "退款", "假货", "劣质",
    "失望", "上当", "坑人", "套路", "黑心", "违法", "举报",
]
CRITICAL_KEYWORDS = [
    "报警", "起诉", "立案", "封查", "曝光", "维权到底", "集体投诉",
]


@dataclass
class SentimentItem:
    platform: str
    brand_name: str
    content: str
    url: str = ""
    sentiment: str = SentimentType.NEUTRAL.value
    sentiment_score: float = 0.0
    keywords: List[str] = field(default_factory=list)
    author: str = ""
    captured_at: Optional[str] = None


@dataclass
class SentimentAlert:
    id: Optional[int]
    brand_name: str
    alert_level: str
    alert_type: str
    title: str
    description: str
    created_at: Optional[str] = None
    is_resolved: bool = False


class SentimentMonitorService:
    """舆情监控服务（异步）"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self):
        if SentimentMonitorService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS sentiment_items ("
                        "  id SERIAL PRIMARY KEY,"
                        "  platform VARCHAR(32),"
                        "  brand_name VARCHAR(64),"
                        "  content TEXT,"
                        "  url TEXT,"
                        "  sentiment VARCHAR(16),"
                        "  sentiment_score FLOAT,"
                        "  keywords TEXT,"
                        "  author VARCHAR(64),"
                        "  captured_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS sentiment_alerts ("
                        "  id SERIAL PRIMARY KEY,"
                        "  brand_name VARCHAR(64),"
                        "  alert_level VARCHAR(16),"
                        "  alert_type VARCHAR(32),"
                        "  title VARCHAR(256),"
                        "  description TEXT,"
                        "  is_resolved BOOLEAN DEFAULT FALSE,"
                        "  created_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
            SentimentMonitorService._ensured = True
        except Exception as e:
            logger.warning(f"[Sentiment] 建表失败: {e}")

    def classify_sentiment(self, content: str) -> tuple:
        """简易情感分类（规则版）

        Returns:
            (sentiment, score, keywords)
        """
        hits_critical = [k for k in CRITICAL_KEYWORDS if k in content]
        hits_negative = [k for k in NEGATIVE_KEYWORDS if k in content]
        if hits_critical:
            return (
                SentimentType.CRITICAL.value,
                -0.9,
                hits_critical + hits_negative,
            )
        if hits_negative:
            score = -0.3 - 0.1 * len(hits_negative)
            return (SentimentType.NEGATIVE.value, max(score, -0.8), hits_negative)
        return (SentimentType.NEUTRAL.value, 0.0, [])

    async def record_item(self, item: SentimentItem) -> Optional[int]:
        """记录一条舆情"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                row = await conn.execute(
                    sql_text(
                        "INSERT INTO sentiment_items "
                        "(platform, brand_name, content, url, sentiment, sentiment_score, keywords, author) "
                        "VALUES (:p, :b, :c, :u, :s, :sc, :k, :a) RETURNING id"
                    ),
                    {
                        "p": item.platform,
                        "b": item.brand_name,
                        "c": item.content[:2000],
                        "u": item.url,
                        "s": item.sentiment,
                        "sc": item.sentiment_score,
                        "k": ",".join(item.keywords)[:500],
                        "a": item.author,
                    },
                )
                r = row.fetchone()
                # 严重负面自动生成预警
                if item.sentiment in (SentimentType.CRITICAL.value, SentimentType.NEGATIVE.value):
                    level = (
                        AlertLevel.CRITICAL.value
                        if item.sentiment == SentimentType.CRITICAL.value
                        else AlertLevel.WARNING.value
                    )
                    await conn.execute(
                        sql_text(
                            "INSERT INTO sentiment_alerts "
                            "(brand_name, alert_level, alert_type, title, description) "
                            "VALUES (:b, :l, :t, :ti, :d)"
                        ),
                        {
                            "b": item.brand_name,
                            "l": level,
                            "t": f"negative_sentiment_{item.sentiment}",
                            "ti": f"{item.brand_name} 发现{item.sentiment}舆情",
                            "d": item.content[:500],
                        },
                    )
                return r[0] if r else None
        except Exception as e:
            logger.warning(f"[Sentiment] 记录舆情失败: {e}")
            return None

    async def get_stats(self, brand_name: str, days: int = 7) -> Dict[str, Any]:
        """获取舆情统计"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return {}
            since = datetime.utcnow() - timedelta(days=days)
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT sentiment, COUNT(*) FROM sentiment_items "
                        "WHERE brand_name=:b AND captured_at>=:s "
                        "GROUP BY sentiment"
                    ),
                    {"b": brand_name, "s": since},
                )
                counts = {r[0]: r[1] for r in rows.fetchall()}
                total = sum(counts.values())
                score = (
                    (counts.get(SentimentType.POSITIVE.value, 0)
                     - counts.get(SentimentType.NEGATIVE.value, 0) * 2
                     - counts.get(SentimentType.CRITICAL.value, 0) * 5)
                    / total
                    if total
                    else 0.0
                )
                return {
                    "brand_name": brand_name,
                    "days": days,
                    "total": total,
                    "positive": counts.get(SentimentType.POSITIVE.value, 0),
                    "neutral": counts.get(SentimentType.NEUTRAL.value, 0),
                    "negative": counts.get(SentimentType.NEGATIVE.value, 0),
                    "critical": counts.get(SentimentType.CRITICAL.value, 0),
                    "sentiment_score": round(score, 3),
                }
        except Exception as e:
            logger.warning(f"[Sentiment] 统计失败: {e}")
            return {}

    async def list_alerts(
        self, brand_name: str = "", only_unresolved: bool = True
    ) -> List[Dict[str, Any]]:
        """列出预警"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                sql = "SELECT id, brand_name, alert_level, alert_type, title, description, is_resolved, created_at FROM sentiment_alerts"
                conditions = []
                params: Dict[str, Any] = {}
                if brand_name:
                    conditions.append("brand_name=:b")
                    params["b"] = brand_name
                if only_unresolved:
                    conditions.append("is_resolved=FALSE")
                if conditions:
                    sql += " WHERE " + " AND ".join(conditions)
                sql += " ORDER BY id DESC LIMIT 100"
                rows = await conn.execute(sql_text(sql), params)
                return [
                    {
                        "id": r[0],
                        "brand_name": r[1],
                        "alert_level": r[2],
                        "alert_type": r[3],
                        "title": r[4],
                        "description": r[5],
                        "is_resolved": r[6],
                        "created_at": str(r[7]) if r[7] else None,
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[Sentiment] 查询预警失败: {e}")
            return []

    async def resolve_alert(self, alert_id: int) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text("UPDATE sentiment_alerts SET is_resolved=TRUE WHERE id=:i"),
                    {"i": alert_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[Sentiment] 解决预警失败: {e}")
            return False


_monitor: Optional[SentimentMonitorService] = None


def get_sentiment_monitor() -> SentimentMonitorService:
    global _monitor
    if _monitor is None:
        _monitor = SentimentMonitorService()
    return _monitor
