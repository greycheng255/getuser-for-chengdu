# -*- coding: utf-8 -*-
"""
账号健康度评分 + 异常预警

对应 PRD 5.6 风控优化 - 账号健康度评分 / 账号异常预警。

基于 publisher_accounts 表的 successes/failures/cooldown_until 字段计算健康度，
异常时生成预警记录。

设计：异步 + PostgreSQL，与 account_service 协同。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from api.schemas.accounts import AccountRole
from api.services.account_feature_flags import unified_account_read_enabled
from api.services.unified_account_service import AccountNotFoundError, get_unified_account_service

logger = logging.getLogger(__name__)


class HealthLevel(str, Enum):
    EXCELLENT = "excellent"  # 90-100
    GOOD = "good"  # 70-89
    WARNING = "warning"  # 50-69
    DANGER = "danger"  # 30-49
    CRITICAL = "critical"  # 0-29


@dataclass
class AccountHealth:
    account_id: int
    platform: str
    account_name: str
    health_score: float  # 0-100
    health_level: str
    successes: int
    failures: int
    in_cooldown: bool
    cooldown_until: Optional[str]
    today_count: int
    daily_limit: int
    anomalies: List[str]  # 检测到的异常


class AccountHealthService:
    """账号健康度服务"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self):
        if AccountHealthService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS account_anomaly_alerts ("
                        "  id SERIAL PRIMARY KEY,"
                        "  account_id INT,"
                        "  platform VARCHAR(32),"
                        "  alert_type VARCHAR(32),"  # rate_limited / banned / login_expired / high_failure
                        "  alert_level VARCHAR(16),"  # warning / danger / critical
                        "  description TEXT,"
                        "  is_resolved BOOLEAN DEFAULT FALSE,"
                        "  created_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
            AccountHealthService._ensured = True
        except Exception as e:
            logger.warning(f"[Health] 建表失败: {e}")

    async def get_health(self, account_id: int) -> Optional[AccountHealth]:
        """获取单个账号健康度"""
        if unified_account_read_enabled():
            try:
                item = await get_unified_account_service().get_account_by_internal_id(account_id)
            except AccountNotFoundError:
                return None
            if item["role"] not in {AccountRole.PUBLISHER.value, AccountRole.BOTH.value}:
                return None
            row = (
                item["id"], item["platform"], item["account_name"], item["status"],
                item["status"] not in {"disabled", "expired", "invalid", "needs_relogin"},
                item["daily_limit"], item["today_count"], item["failure_count"],
                item["success_count"], item["cooldown_until"],
            )
            return self._compute_health(row)
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, platform, account_name, status, is_active, "
                        "daily_limit, today_count, failures, successes, cooldown_until "
                        "FROM publisher_accounts WHERE id=:i"
                    ),
                    {"i": account_id},
                )
                r = rows.fetchone()
                if not r:
                    return None
                return self._compute_health(r)
        except Exception as e:
            logger.warning(f"[Health] 查询健康度失败: {e}")
            return None

    async def list_health_by_platform(self, platform: str = "") -> List[Dict[str, Any]]:
        """列出所有账号健康度"""
        if unified_account_read_enabled():
            result = await get_unified_account_service().list_accounts_for_role(
                role=AccountRole.PUBLISHER,
                owner_user_id=None,
                platform=platform or None,
            )
            results = []
            for item in result["items"]:
                h = self._compute_health((
                    item["id"], item["platform"], item["account_name"], item["status"],
                    item["status"] not in {"disabled", "expired", "invalid", "needs_relogin"},
                    item["daily_limit"], item["today_count"], item["failure_count"],
                    item["success_count"], item["cooldown_until"],
                ))
                results.append({
                    "account_id": h.account_id,
                    "platform": h.platform,
                    "account_name": h.account_name,
                    "health_score": h.health_score,
                    "health_level": h.health_level,
                    "successes": h.successes,
                    "failures": h.failures,
                    "in_cooldown": h.in_cooldown,
                    "today_count": h.today_count,
                    "daily_limit": h.daily_limit,
                    "anomalies": h.anomalies,
                })
            return results
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                if platform:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, platform, account_name, status, is_active, "
                            "daily_limit, today_count, failures, successes, cooldown_until "
                            "FROM publisher_accounts WHERE platform=:p ORDER BY id"
                        ),
                        {"p": platform},
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, platform, account_name, status, is_active, "
                            "daily_limit, today_count, failures, successes, cooldown_until "
                            "FROM publisher_accounts ORDER BY id"
                        )
                    )
                results = []
                for r in rows.fetchall():
                    h = self._compute_health(r)
                    results.append(
                        {
                            "account_id": h.account_id,
                            "platform": h.platform,
                            "account_name": h.account_name,
                            "health_score": h.health_score,
                            "health_level": h.health_level,
                            "successes": h.successes,
                            "failures": h.failures,
                            "in_cooldown": h.in_cooldown,
                            "today_count": h.today_count,
                            "daily_limit": h.daily_limit,
                            "anomalies": h.anomalies,
                        }
                    )
                return results
        except Exception as e:
            logger.warning(f"[Health] 查询健康度列表失败: {e}")
            return []

    def _compute_health(self, row) -> AccountHealth:
        """计算健康度评分

        评分维度：
        - 成功率（40%）：successes / (successes + failures)
        - 冷却状态（30%）：未冷却满分，冷却中扣分
        - 配额使用（20%）：今日用量越少越好
        - 账号状态（10%）：active 满分
        """
        aid, platform, name, status, is_active, daily_limit, today_count, failures, successes, cooldown_until = row
        anomalies: List[str] = []
        import time
        now = int(time.time())
        in_cooldown = bool(cooldown_until and cooldown_until > now)

        # 1. 成功率（40分）
        total_ops = successes + failures
        if total_ops == 0:
            success_score = 40  # 新账号满分
        else:
            success_rate = successes / total_ops
            success_score = success_rate * 40
            if success_rate < 0.5:
                anomalies.append(f"成功率偏低({success_rate:.0%})")

        # 2. 冷却状态（30分）
        if in_cooldown:
            cooldown_score = 0
            anomalies.append(f"账号冷却中(至 {cooldown_until})")
        else:
            cooldown_score = 30

        # 3. 配额使用（20分）
        if daily_limit > 0:
            usage_rate = today_count / daily_limit
            quota_score = (1 - usage_rate) * 20
            if usage_rate >= 0.8:
                anomalies.append(f"今日配额接近上限({today_count}/{daily_limit})")
        else:
            quota_score = 20

        # 4. 账号状态（10分）
        if status == "active" and is_active:
            status_score = 10
        else:
            status_score = 0
            anomalies.append(f"账号状态异常({status})")

        # 异常检测
        if failures >= 3:
            anomalies.append(f"连续失败 {failures} 次")
        if status == "needs_relogin":
            anomalies.append("登录失效，需重新登录")

        total_score = success_score + cooldown_score + quota_score + status_score
        level = self._score_to_level(total_score)

        # 严重异常自动生成预警
        return AccountHealth(
            account_id=aid,
            platform=platform,
            account_name=name,
            health_score=round(total_score, 1),
            health_level=level,
            successes=successes,
            failures=failures,
            in_cooldown=in_cooldown,
            cooldown_until=str(cooldown_until) if cooldown_until else None,
            today_count=today_count,
            daily_limit=daily_limit,
            anomalies=anomalies,
        )

    def _score_to_level(self, score: float) -> str:
        if score >= 90:
            return HealthLevel.EXCELLENT.value
        if score >= 70:
            return HealthLevel.GOOD.value
        if score >= 50:
            return HealthLevel.WARNING.value
        if score >= 30:
            return HealthLevel.DANGER.value
        return HealthLevel.CRITICAL.value

    async def check_anomalies(self) -> List[Dict[str, Any]]:
        """扫描所有账号，生成异常预警"""
        await self.ensure_table()
        all_health = await self.list_health_by_platform()
        alerts_created = []
        for h in all_health:
            if not h["anomalies"]:
                continue
            # 根据健康度确定预警级别
            level = "warning"
            if h["health_score"] < 30:
                level = "critical"
            elif h["health_score"] < 50:
                level = "danger"
            alert_type = "high_failure"
            if "冷却中" in " ".join(h["anomalies"]):
                alert_type = "rate_limited"
            elif "登录失效" in " ".join(h["anomalies"]):
                alert_type = "login_expired"
            elif "账号状态异常" in " ".join(h["anomalies"]):
                alert_type = "banned"
            alert_id = await self._create_alert(
                h["account_id"], h["platform"], alert_type, level,
                f"{h['account_name']}: {'; '.join(h['anomalies'])}",
            )
            if alert_id:
                alerts_created.append({"alert_id": alert_id, **h})
        return alerts_created

    async def _create_alert(
        self, account_id: int, platform: str, alert_type: str, level: str, desc: str
    ) -> Optional[int]:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                # 去重：同一账号同一类型未解决的预警不重复创建
                existing = await conn.execute(
                    sql_text(
                        "SELECT id FROM account_anomaly_alerts "
                        "WHERE account_id=:a AND alert_type=:t AND is_resolved=FALSE "
                        "LIMIT 1"
                    ),
                    {"a": account_id, "t": alert_type},
                )
                if existing.fetchone():
                    return None
                row = await conn.execute(
                    sql_text(
                        "INSERT INTO account_anomaly_alerts "
                        "(account_id, platform, alert_type, alert_level, description) "
                        "VALUES (:a, :p, :t, :l, :d) RETURNING id"
                    ),
                    {"a": account_id, "p": platform, "t": alert_type, "l": level, "d": desc[:500]},
                )
                r = row.fetchone()
                return r[0] if r else None
        except Exception as e:
            logger.warning(f"[Health] 创建预警失败: {e}")
            return None

    async def list_alerts(self, only_unresolved: bool = True) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            sql = (
                "SELECT id, account_id, platform, alert_type, alert_level, "
                "description, is_resolved, created_at FROM account_anomaly_alerts"
            )
            if only_unresolved:
                sql += " WHERE is_resolved=FALSE"
            sql += " ORDER BY id DESC LIMIT 100"
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql))
                return [
                    {
                        "id": r[0],
                        "account_id": r[1],
                        "platform": r[2],
                        "alert_type": r[3],
                        "alert_level": r[4],
                        "description": r[5],
                        "is_resolved": r[6],
                        "created_at": str(r[7]) if r[7] else None,
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[Health] 查询预警失败: {e}")
            return []

    async def resolve_alert(self, alert_id: int) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text("UPDATE account_anomaly_alerts SET is_resolved=TRUE WHERE id=:i"),
                    {"i": alert_id},
                )
            return True
        except Exception:
            return False


_health: Optional[AccountHealthService] = None


def get_account_health_service() -> AccountHealthService:
    global _health
    if _health is None:
        _health = AccountHealthService()
    return _health
