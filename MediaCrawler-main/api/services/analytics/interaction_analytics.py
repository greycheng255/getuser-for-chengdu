# -*- coding: utf-8 -*-
"""
互动数据精细化分析 + 多账号权重优化

对应 PRD 5.5 后台数据统计 + 5.4 互动运营精细化：
1. 互动完成率、互动增量、异常互动识别
2. 按平台 / 账号 / 内容维度分析
3. 多账号权重动态调整（联动 account_weight.py）

设计：异步 + PostgreSQL，所有查询都为只读，无副作用。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ==================== 数据类 ====================


@dataclass
class InteractionStat:
    """互动统计聚合结果"""

    platform: str = ""
    account_id: Optional[int] = None
    target_id: str = ""
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    pending: int = 0
    success_rate: float = 0.0
    completion_rate: float = 0.0  # 完成率 = (success+failed+skipped) / total
    by_type: Dict[str, int] = field(default_factory=dict)
    delta: int = 0  # 较上期增量
    delta_ratio: float = 0.0  # 增长率
    period_start: Optional[str] = None
    period_end: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "account_id": self.account_id,
            "target_id": self.target_id,
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "pending": self.pending,
            "success_rate": round(self.success_rate, 4),
            "completion_rate": round(self.completion_rate, 4),
            "by_type": self.by_type,
            "delta": self.delta,
            "delta_ratio": round(self.delta_ratio, 4),
            "period_start": self.period_start,
            "period_end": self.period_end,
        }


@dataclass
class AnomalyInteraction:
    """异常互动记录"""

    interaction_id: str
    platform: str
    account_id: Optional[int]
    interaction_type: str
    target_id: str
    reason: str  # too_fast / duplicate_content / off_hours / abnormal_volume
    detail: str = ""
    detected_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "platform": self.platform,
            "account_id": self.account_id,
            "interaction_type": self.interaction_type,
            "target_id": self.target_id,
            "reason": self.reason,
            "detail": self.detail,
            "detected_at": self.detected_at,
        }


# ==================== 服务 ====================


class InteractionAnalyticsService:
    """互动数据精细化分析服务

    数据源：multi_interaction_records 表（MultiInteractor 执行时入库）。
    若表不存在则降级返回空结果，避免阻塞主流程。
    """

    TABLE_NAME = "multi_interaction_records"
    _ensured = False  # 类级别标志：DDL 仅首次执行一次，避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self):
        """幂等建表，仅用于初次部署。首次执行后置位，后续直接跳过以节省远程 DB 往返。"""
        if InteractionAnalyticsService._ensured:
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
                        "  id SERIAL PRIMARY KEY,"
                        "  interaction_id VARCHAR(64) UNIQUE,"
                        "  task_id VARCHAR(64),"
                        "  platform VARCHAR(32) NOT NULL,"
                        "  account_id INT,"
                        "  interaction_type VARCHAR(16) NOT NULL,"
                        "  target_url TEXT,"
                        "  target_id VARCHAR(128),"
                        "  content TEXT,"
                        "  status VARCHAR(16) DEFAULT 'pending',"
                        "  error TEXT,"
                        "  retry_count INT DEFAULT 0,"
                        "  owner_user_id INT,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  completed_at TIMESTAMP"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_interaction_platform_time "
                        f"ON {self.TABLE_NAME} (platform, created_at)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_interaction_account_time "
                        f"ON {self.TABLE_NAME} (account_id, created_at)"
                    )
                )
                # created_at 单列索引：无 platform/account 过滤时的时间范围查询走此索引
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_interaction_created_at "
                        f"ON {self.TABLE_NAME} (created_at)"
                    )
                )
            InteractionAnalyticsService._ensured = True
        except Exception as e:
            logger.warning(f"[InteractionAnalytics] 建表失败: {e}")

    # ==================== 统计查询 ====================

    async def aggregate(
        self,
        *,
        platform: Optional[str] = None,
        account_id: Optional[int] = None,
        target_id: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        group_by: str = "platform",  # platform / account / target / type
    ) -> List[InteractionStat]:
        """聚合统计。group_by 决定分组维度。

        优化：当期+上期查询并行执行（原串行 2 次远程 DB 往返 → 并行，耗时减半）
        """
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []

            now = datetime.utcnow()
            end_dt = end or now
            start_dt = start or (end_dt - timedelta(days=7))

            group_col = {
                "platform": "platform",
                "account": "account_id",
                "target": "target_id",
                "type": "interaction_type",
            }.get(group_by, "platform")

            # 并行执行当期+上期查询（独立查询，无依赖）
            current_task = self._query_period(
                start_dt, end_dt, group_col, platform, account_id, target_id, group_by
            )
            prev_task = self._query_prev_period_map(
                start_dt, end_dt, group_col, platform, account_id, target_id
            )
            current_rows, prev_map = await asyncio.gather(current_task, prev_task)

            # 构建结果 + 填充增量
            results: List[InteractionStat] = []
            for r in current_rows:
                total = int(r[1] or 0)
                success = int(r[2] or 0)
                failed = int(r[3] or 0)
                skipped = int(r[4] or 0)
                pending = int(r[5] or 0)
                completed = success + failed + skipped
                stat = InteractionStat(
                    platform=platform or str(r[0] or ""),
                    account_id=account_id,
                    target_id=target_id or "",
                    total=total,
                    success=success,
                    failed=failed,
                    skipped=skipped,
                    pending=pending,
                    success_rate=(success / total) if total else 0.0,
                    completion_rate=(completed / total) if total else 0.0,
                    period_start=start_dt.isoformat(),
                    period_end=end_dt.isoformat(),
                )
                # 反填分组键
                if group_by == "platform":
                    stat.platform = str(r[0] or "")
                elif group_by == "account":
                    stat.account_id = int(r[0]) if r[0] is not None else None
                elif group_by == "target":
                    stat.target_id = str(r[0] or "")
                results.append(stat)

            # 填充同比增量（从 prev_map 直接读取，无额外 DB 查询）
            self._fill_delta_from_map(results, prev_map, group_col)
            return results
        except Exception as e:
            logger.warning(f"[InteractionAnalytics] aggregate 失败: {e}")
            return []

    async def _query_period(
        self, start_dt, end_dt, group_col, platform, account_id, target_id, group_by
    ):
        """查询单个时间段的聚合数据，返回原始行列表"""
        from sqlalchemy import text as sql_text

        engine = self._get_engine()
        where_parts = ["created_at >= :start", "created_at < :end"]
        params: Dict[str, Any] = {"start": start_dt, "end": end_dt}
        if platform:
            where_parts.append("platform = :platform")
            params["platform"] = platform
        if account_id is not None:
            where_parts.append("account_id = :account_id")
            params["account_id"] = account_id
        if target_id:
            where_parts.append("target_id = :target_id")
            params["target_id"] = target_id
        where_sql = " AND ".join(where_parts)

        sql = (
            f"SELECT {group_col} AS gkey, "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success, "
            "  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed, "
            "  SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped, "
            "  SUM(CASE WHEN status='pending' OR status='retrying' THEN 1 ELSE 0 END) AS pending "
            f"FROM {self.TABLE_NAME} "
            f"WHERE {where_sql} "
            f"GROUP BY {group_col} ORDER BY total DESC"
        )
        async with engine.connect() as conn:
            rows = await conn.execute(sql_text(sql), params)
            return rows.fetchall()

    async def _query_prev_period_map(
        self, start_dt, end_dt, group_col, platform, account_id, target_id
    ) -> Dict[str, int]:
        """查询上一周期各分组的总数，返回 {group_key: count} 映射"""
        from sqlalchemy import text as sql_text

        engine = self._get_engine()
        duration = end_dt - start_dt
        prev_start = start_dt - duration
        prev_end = start_dt

        where_parts = ["created_at >= :pstart", "created_at < :pend"]
        params: Dict[str, Any] = {"pstart": prev_start, "pend": prev_end}
        if platform:
            where_parts.append("platform = :platform")
            params["platform"] = platform
        if account_id is not None:
            where_parts.append("account_id = :account_id")
            params["account_id"] = account_id
        if target_id:
            where_parts.append("target_id = :target_id")
            params["target_id"] = target_id
        where_sql = " AND ".join(where_parts)

        sql = (
            f"SELECT {group_col} AS gkey, COUNT(*) AS total "
            f"FROM {self.TABLE_NAME} WHERE {where_sql} "
            f"GROUP BY {group_col}"
        )
        prev_map: Dict[str, int] = {}
        async with engine.connect() as conn:
            rows = await conn.execute(sql_text(sql), params)
            for r in rows.fetchall():
                prev_map[str(r[0])] = int(r[1] or 0)
        return prev_map

    @staticmethod
    def _fill_delta_from_map(
        current_stats: List["InteractionStat"],
        prev_map: Dict[str, int],
        group_col: str,
    ):
        """从预查询的上期映射填充同比增量（无 DB 查询）"""
        for stat in current_stats:
            key = (
                stat.platform
                if group_col == "platform"
                else (str(stat.account_id) if group_col == "account" else stat.target_id)
            )
            prev_total = prev_map.get(str(key), 0)
            stat.delta = stat.total - prev_total
            if prev_total > 0:
                stat.delta_ratio = (stat.total - prev_total) / prev_total
            elif stat.total > 0:
                stat.delta_ratio = 1.0

    async def _fill_delta(
        self,
        current_stats: List[InteractionStat],
        start: datetime,
        end: datetime,
        group_col: str,
        platform: Optional[str],
        account_id: Optional[int],
        target_id: Optional[str],
    ):
        """计算同比上期增量"""
        if not current_stats:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return

            duration = end - start
            prev_start = start - duration
            prev_end = start

            where_parts = ["created_at >= :pstart", "created_at < :pend"]
            params: Dict[str, Any] = {"pstart": prev_start, "pend": prev_end}
            if platform:
                where_parts.append("platform = :platform")
                params["platform"] = platform
            if account_id is not None:
                where_parts.append("account_id = :account_id")
                params["account_id"] = account_id
            if target_id:
                where_parts.append("target_id = :target_id")
                params["target_id"] = target_id
            where_sql = " AND ".join(where_parts)

            sql = (
                f"SELECT {group_col} AS gkey, COUNT(*) AS total "
                f"FROM {self.TABLE_NAME} WHERE {where_sql} "
                f"GROUP BY {group_col}"
            )

            prev_map: Dict[str, int] = {}
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                for r in rows.fetchall():
                    prev_map[str(r[0])] = int(r[1] or 0)

            for stat in current_stats:
                key = (
                    stat.platform
                    if group_col == "platform"
                    else (str(stat.account_id) if group_col == "account_id" else stat.target_id)
                )
                prev_total = prev_map.get(key, 0)
                stat.delta = stat.total - prev_total
                if prev_total > 0:
                    stat.delta_ratio = (stat.total - prev_total) / prev_total
                elif stat.total > 0:
                    stat.delta_ratio = 1.0
        except Exception as e:
            logger.debug(f"[InteractionAnalytics] 增量计算失败: {e}")

    # ==================== 异常识别 ====================

    async def detect_anomalies(
        self,
        *,
        platform: Optional[str] = None,
        account_id: Optional[int] = None,
        since: Optional[datetime] = None,
        max_interval_seconds: int = 5,
        off_hours: Tuple[int, int] = (0, 6),
        duplicate_threshold: int = 3,
    ) -> List[AnomalyInteraction]:
        """识别异常互动：
        - too_fast: 同账号两次互动间隔 < max_interval_seconds
        - off_hours: 0-6 点异常时段互动
        - duplicate_content: 同账号近期重复内容
        - abnormal_volume: 单账号单日互动 > 100（疑似脚本）
        """
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []

            since_dt = since or (datetime.utcnow() - timedelta(days=1))
            params: Dict[str, Any] = {"since": since_dt}
            where_parts = ["created_at >= :since"]
            if platform:
                where_parts.append("platform = :platform")
                params["platform"] = platform
            if account_id is not None:
                where_parts.append("account_id = :account_id")
                params["account_id"] = account_id
            where_sql = " AND ".join(where_parts)

            sql = (
                "SELECT interaction_id, platform, account_id, interaction_type, "
                "  target_id, content, status, created_at "
                f"FROM {self.TABLE_NAME} WHERE {where_sql} "
                "ORDER BY account_id, created_at"
            )

            anomalies: List[AnomalyInteraction] = []
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                records = rows.fetchall()

            # 1. too_fast & off_hours
            last_ts: Dict[int, datetime] = {}
            for r in records:
                aid = int(r[2]) if r[2] is not None else 0
                ts = r[7]
                if ts is None:
                    continue
                ts = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
                # off hours
                if off_hours[0] <= ts.hour < off_hours[1]:
                    anomalies.append(
                        AnomalyInteraction(
                            interaction_id=str(r[0] or ""),
                            platform=str(r[1] or ""),
                            account_id=aid or None,
                            interaction_type=str(r[3] or ""),
                            target_id=str(r[5] or ""),
                            reason="off_hours",
                            detail=f"互动发生在 {ts.hour} 点（异常时段）",
                            detected_at=datetime.utcnow().isoformat(),
                        )
                    )
                # too fast
                if aid in last_ts and (ts - last_ts[aid]).total_seconds() < max_interval_seconds:
                    anomalies.append(
                        AnomalyInteraction(
                            interaction_id=str(r[0] or ""),
                            platform=str(r[1] or ""),
                            account_id=aid or None,
                            interaction_type=str(r[3] or ""),
                            target_id=str(r[5] or ""),
                            reason="too_fast",
                            detail=f"间隔 {int((ts - last_ts[aid]).total_seconds())}s 小于 {max_interval_seconds}s",
                            detected_at=datetime.utcnow().isoformat(),
                        )
                    )
                last_ts[aid] = ts

            # 2. duplicate content
            content_map: Dict[Tuple[int, str], List[Any]] = {}
            for r in records:
                aid = int(r[2]) if r[2] is not None else 0
                content = (r[5] or "").strip() if r[5] else ""
                if not content:
                    continue
                key = (aid, content)
                content_map.setdefault(key, []).append(r)
            for (aid, content), recs in content_map.items():
                if len(recs) >= duplicate_threshold:
                    first = recs[0]
                    anomalies.append(
                        AnomalyInteraction(
                            interaction_id=str(first[0] or ""),
                            platform=str(first[1] or ""),
                            account_id=aid or None,
                            interaction_type=str(first[3] or ""),
                            target_id=str(first[5] or ""),
                            reason="duplicate_content",
                            detail=f"同账号相同内容出现 {len(recs)} 次",
                            detected_at=datetime.utcnow().isoformat(),
                        )
                    )

            # 3. abnormal volume
            volume_map: Dict[Tuple[str, int], int] = {}
            for r in records:
                aid = int(r[2]) if r[2] is not None else 0
                key = (str(r[1] or ""), aid)
                volume_map[key] = volume_map.get(key, 0) + 1
            for (pf, aid), vol in volume_map.items():
                if vol > 100:
                    anomalies.append(
                        AnomalyInteraction(
                            interaction_id="",
                            platform=pf,
                            account_id=aid or None,
                            interaction_type="",
                            target_id="",
                            reason="abnormal_volume",
                            detail=f"单日互动 {vol} 次疑似脚本",
                            detected_at=datetime.utcnow().isoformat(),
                        )
                    )

            return anomalies
        except Exception as e:
            logger.warning(f"[InteractionAnalytics] 异常识别失败: {e}")
            return []

    # ==================== 互动增量（趋势） ====================

    async def trend(
        self,
        *,
        platform: Optional[str] = None,
        account_id: Optional[int] = None,
        days: int = 14,
    ) -> List[Dict[str, Any]]:
        """按天返回互动数趋势"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []

            end = datetime.utcnow()
            start = end - timedelta(days=days)
            where_parts = ["created_at >= :start", "created_at < :end"]
            params: Dict[str, Any] = {"start": start, "end": end}
            if platform:
                where_parts.append("platform = :platform")
                params["platform"] = platform
            if account_id is not None:
                where_parts.append("account_id = :account_id")
                params["account_id"] = account_id
            where_sql = " AND ".join(where_parts)

            sql = (
                "SELECT DATE(created_at) AS d, "
                "  COUNT(*) AS total, "
                "  SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success "
                f"FROM {self.TABLE_NAME} WHERE {where_sql} "
                "GROUP BY DATE(created_at) ORDER BY d"
            )
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                return [
                    {
                        "date": str(r[0]),
                        "total": int(r[1] or 0),
                        "success": int(r[2] or 0),
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[InteractionAnalytics] trend 失败: {e}")
            return []


# ==================== 单例 ====================

_singleton: Optional[InteractionAnalyticsService] = None


def get_interaction_analytics() -> InteractionAnalyticsService:
    global _singleton
    if _singleton is None:
        _singleton = InteractionAnalyticsService()
    return _singleton
