# -*- coding: utf-8 -*-
"""
多账号权重优化

对应 PRD 5.6 风控优化 + 5.4 多账号权重动态调整：
1. 基于账号健康分、互动效果、违规记录动态调整账号权重
2. 权重影响账号在池中的选取优先级
3. 与 BotAccountPool / PublisherAccountService 协同（读取+建议，不直接接管）

设计：
- 权重值范围 [0, 100]，默认 50
- 输入维度：成功率、健康分、近期违规次数、互动效果评分、账号年龄
- 输出：综合权重 + 调整原因
- 异步持久化到 account_weights 表（按账号+平台维度）
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from api.services.account_feature_flags import unified_account_read_enabled

logger = logging.getLogger(__name__)


# ==================== 数据类 ====================


@dataclass
class AccountWeight:
    """账号权重"""

    account_id: int
    platform: str
    weight: float = 50.0  # 0-100
    factors: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "platform": self.platform,
            "weight": round(self.weight, 2),
            "factors": {k: round(v, 2) for k, v in self.factors.items()},
            "reasons": self.reasons,
            "updated_at": self.updated_at,
        }


@dataclass
class WeightFactors:
    """权重计算输入因子"""

    success_rate: float = 1.0  # 0-1
    health_score: float = 50.0  # 0-100
    violations_recent: int = 0  # 近7日违规次数
    interaction_score: float = 0.5  # 0-1 互动效果（基于互动成功率/转化率）
    account_age_days: int = 0
    is_in_cooldown: bool = False
    today_count: int = 0
    daily_limit: int = 100


# ==================== 服务 ====================


class AccountWeightService:
    """账号权重动态调整服务

    权重公式（综合 100 分）：
    - 健康分维度（35%）：min(health_score, 100)
    - 成功率维度（25%）：success_rate * 100
    - 互动效果维度（20%）：interaction_score * 100
    - 违规惩罚（10%）：max(0, 10 - violations_recent * 2)
    - 账号成熟度（10%）：min(account_age_days / 90, 1) * 10

    冷却中 → 权重强制为 0
    今日配额用尽 → 权重 *0.3
    """

    TABLE_NAME = "account_weights"
    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self):
        if AccountWeightService._ensured:
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
                        "  account_id INT NOT NULL,"
                        "  platform VARCHAR(32) NOT NULL,"
                        "  weight NUMERIC(6,2) DEFAULT 50.00,"
                        "  factors JSONB,"
                        "  reasons TEXT,"
                        "  updated_at TIMESTAMP DEFAULT NOW(),"
                        "  UNIQUE (account_id, platform)"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_account_weights_platform "
                        f"ON {self.TABLE_NAME} (platform, weight DESC)"
                    )
                )
            AccountWeightService._ensured = True
        except Exception as e:
            logger.warning(f"[AccountWeight] 建表失败: {e}")

    # ==================== 权重计算 ====================

    def compute(self, factors: WeightFactors) -> AccountWeight:
        """根据因子计算权重（纯函数，便于测试）"""
        reasons: List[str] = []

        # 冷却强制 0
        if factors.is_in_cooldown:
            return AccountWeight(
                account_id=0,
                platform="",
                weight=0.0,
                factors={"cooldown": 0},
                reasons=["账号冷却中，权重置零"],
                updated_at=datetime.utcnow().isoformat(),
            )

        # 健康分维度（35%）
        health_factor = min(max(factors.health_score, 0), 100)
        if health_factor < 30:
            reasons.append(f"健康分偏低({health_factor:.0f})")

        # 成功率维度（25%）
        sr = min(max(factors.success_rate, 0), 1.0)
        if sr < 0.5:
            reasons.append(f"成功率偏低({sr:.0%})")

        # 互动效果维度（20%）
        ivs = min(max(factors.interaction_score, 0), 1.0)

        # 违规惩罚（10%）
        violation_score = max(0.0, 10.0 - factors.violations_recent * 2.0)
        if factors.violations_recent > 0:
            reasons.append(f"近期违规 {factors.violations_recent} 次")

        # 成熟度（10%）
        maturity_score = min(factors.account_age_days / 90.0, 1.0) * 10.0

        weight = (
            health_factor * 0.35
            + sr * 100 * 0.25
            + ivs * 100 * 0.20
            + violation_score
            + maturity_score
        )

        # 配额耗尽降权
        if factors.daily_limit > 0 and factors.today_count >= factors.daily_limit:
            weight *= 0.3
            reasons.append("今日配额已耗尽，权重降至 30%")

        weight = max(0.0, min(weight, 100.0))

        return AccountWeight(
            account_id=0,
            platform="",
            weight=weight,
            factors={
                "health": round(health_factor, 2),
                "success_rate": round(sr, 4),
                "interaction": round(ivs, 4),
                "violation": round(violation_score, 2),
                "maturity": round(maturity_score, 2),
            },
            reasons=reasons,
            updated_at=datetime.utcnow().isoformat(),
        )

    # ==================== 因子收集 ====================

    async def collect_factors(
        self, account_id: int, platform: str
    ) -> WeightFactors:
        """收集账号权重因子（从 publisher_accounts + account_anomaly_alerts + interaction_analytics）"""
        factors = WeightFactors()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return factors

            # 1. 账号基础字段；统一读取开启后不再依赖 publisher_accounts。
            async with engine.connect() as conn:
                if unified_account_read_enabled():
                    account_sql = (
                        "SELECT platform, account_name, status, "
                        "CASE WHEN status IN ('active','cooldown') THEN 1 ELSE 0 END AS is_active, "
                        "daily_limit, today_count, failure_count AS failures, "
                        "success_count AS successes, cooldown_until, created_ts AS created_at "
                        "FROM unified_accounts WHERE id=:i AND role IN ('publisher','both')"
                    )
                else:
                    account_sql = (
                        "SELECT platform, account_name, status, is_active, daily_limit, "
                        "today_count, failures, successes, cooldown_until, created_at "
                        "FROM publisher_accounts WHERE id=:i"
                    )
                rows = await conn.execute(
                    sql_text(account_sql),
                    {"i": account_id},
                )
                r = rows.fetchone()
                if r:
                    import time
                    now_ts = int(time.time())
                    cooldown_until_ts = 0
                    if r[8] is not None:
                        try:
                            cooldown_until_ts = int(r[8])
                        except (TypeError, ValueError):
                            cooldown_until_ts = 0
                    factors.is_in_cooldown = bool(cooldown_until_ts and cooldown_until_ts > now_ts)
                    factors.today_count = int(r[6] or 0)
                    factors.daily_limit = int(r[5] or 100)
                    successes = int(r[7] or 0)
                    failures = int(r[8] if False else 0)  # r[8] = cooldown_until，failures 在 r[7]
                    # 重新对齐字段（按 SELECT 顺序：0 platform,1 name,2 status,3 is_active,
                    # 4 daily_limit,5 today_count,6 failures,7 successes,8 cooldown_until,9 created_at）
                    successes = int(r[7] or 0)
                    failures = int(r[6] or 0)
                    total = successes + failures
                    factors.success_rate = (successes / total) if total else 1.0
                    if r[9] is not None:
                        try:
                            created = (
                                r[9]
                                if isinstance(r[9], datetime)
                                else datetime.fromtimestamp(r[9])
                                if isinstance(r[9], (int, float))
                                else datetime.fromisoformat(str(r[9]))
                            )
                            factors.account_age_days = max(0, (datetime.utcnow() - created).days)
                        except Exception:
                            pass

                # 2. account_anomaly_alerts：近 7 日违规数
                since = datetime.utcnow() - timedelta(days=7)
                vrows = await conn.execute(
                    sql_text(
                        "SELECT COUNT(*) FROM account_anomaly_alerts "
                        "WHERE account_id=:i AND created_at >= :s AND is_resolved=FALSE"
                    ),
                    {"i": account_id, "s": since},
                )
                vrow = vrows.fetchone()
                factors.violations_recent = int(vrow[0] or 0) if vrow else 0

            # 3. 互动效果：从 multi_interaction_records 表
            factors.interaction_score = await self._calc_interaction_score(account_id, platform)

            # 4. 健康分：复用 AccountHealthService 的近似算法
            factors.health_score = self._approx_health_score(factors)
        except Exception as e:
            logger.warning(f"[AccountWeight] 收集因子失败 account={account_id}: {e}")

        return factors

    async def _calc_interaction_score(self, account_id: int, platform: str) -> float:
        """从互动记录计算效果评分"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return 0.5
            since = datetime.utcnow() - timedelta(days=7)
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT COUNT(*), "
                        "  SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) "
                        "FROM multi_interaction_records "
                        "WHERE account_id=:i AND platform=:p AND created_at >= :s"
                    ),
                    {"i": account_id, "p": platform, "s": since},
                )
                r = rows.fetchone()
                if not r or not r[0]:
                    return 0.5
                total = int(r[0])
                success = int(r[1] or 0)
                return success / total
        except Exception:
            return 0.5

    def _approx_health_score(self, factors: WeightFactors) -> float:
        """近似健康分（与 AccountHealthService 算法一致）"""
        score = 0.0
        # 成功率 40
        score += factors.success_rate * 40
        # 冷却 30
        if not factors.is_in_cooldown:
            score += 30
        # 配额 20
        if factors.daily_limit > 0:
            usage = factors.today_count / factors.daily_limit
            score += max(0.0, (1 - usage) * 20)
        else:
            score += 20
        # 状态 10
        score += 10
        # 违规扣分
        score -= factors.violations_recent * 5
        return max(0.0, min(score, 100.0))

    # ==================== 持久化 ====================

    async def update_weight(self, account_id: int, platform: str) -> Optional[AccountWeight]:
        """收集因子 + 计算权重 + 持久化"""
        await self.ensure_table()
        factors = await self.collect_factors(account_id, platform)
        weight = self.compute(factors)
        weight.account_id = account_id
        weight.platform = platform
        try:
            from sqlalchemy import text as sql_text
            import json

            engine = self._get_engine()
            if engine is None:
                return weight
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        f"INSERT INTO {self.TABLE_NAME} (account_id, platform, weight, factors, reasons, updated_at) "
                        "VALUES (:a, :p, :w, :f, :r, NOW()) "
                        "ON CONFLICT (account_id, platform) DO UPDATE SET "
                        "  weight = EXCLUDED.weight, "
                        "  factors = EXCLUDED.factors, "
                        "  reasons = EXCLUDED.reasons, "
                        "  updated_at = NOW()"
                    ),
                    {
                        "a": account_id,
                        "p": platform,
                        "w": weight.weight,
                        "f": json.dumps(weight.factors, ensure_ascii=False),
                        "r": " | ".join(weight.reasons),
                    },
                )
        except Exception as e:
            logger.warning(f"[AccountWeight] 持久化失败: {e}")
        return weight

    async def get_weight(self, account_id: int, platform: str) -> Optional[AccountWeight]:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT weight, factors, reasons, updated_at "
                        f"FROM {self.TABLE_NAME} WHERE account_id=:a AND platform=:p"
                    ),
                    {"a": account_id, "p": platform},
                )
                r = rows.fetchone()
                if not r:
                    return None
                import json
                factors = r[1] if isinstance(r[1], dict) else (
                    json.loads(r[1]) if r[1] else {}
                )
                return AccountWeight(
                    account_id=account_id,
                    platform=platform,
                    weight=float(r[0]),
                    factors=factors,
                    reasons=(r[2] or "").split(" | ") if r[2] else [],
                    updated_at=str(r[3]) if r[3] else None,
                )
        except Exception as e:
            logger.warning(f"[AccountWeight] 查询失败: {e}")
            return None

    async def list_by_platform(self, platform: str, limit: int = 100) -> List[AccountWeight]:
        """按权重降序列出某平台账号（用于 BotAccountPool/Publisher 选取）"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT account_id, platform, weight, factors, reasons, updated_at "
                        f"FROM {self.TABLE_NAME} WHERE platform=:p "
                        "ORDER BY weight DESC LIMIT :l"
                    ),
                    {"p": platform, "l": limit},
                )
                import json
                results: List[AccountWeight] = []
                for r in rows.fetchall():
                    factors = r[3] if isinstance(r[3], dict) else (
                        json.loads(r[3]) if r[3] else {}
                    )
                    results.append(
                        AccountWeight(
                            account_id=int(r[0]),
                            platform=str(r[1]),
                            weight=float(r[2]),
                            factors=factors,
                            reasons=(r[4] or "").split(" | ") if r[4] else [],
                            updated_at=str(r[5]) if r[5] else None,
                        )
                    )
                return results
        except Exception as e:
            logger.warning(f"[AccountWeight] 列表查询失败: {e}")
            return []

    async def refresh_all(self, platform: Optional[str] = None) -> int:
        """批量刷新权重，返回刷新账号数

        性能优化：每 10 个账号 sleep 0.5s 让出事件循环，避免长时间占用导致 CPU 100%。
        每个账号 collect_factors 做 3 次 DB 查询，串行遍历会长时间阻塞事件循环。
        """
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return 0
            async with engine.connect() as conn:
                if unified_account_read_enabled() and platform:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, platform FROM unified_accounts "
                            "WHERE platform=:p AND role IN ('publisher','both') AND status='active'"
                        ),
                        {"p": platform},
                    )
                elif unified_account_read_enabled():
                    rows = await conn.execute(sql_text(
                        "SELECT id, platform FROM unified_accounts "
                        "WHERE role IN ('publisher','both') AND status='active'"
                    ))
                elif platform:
                    rows = await conn.execute(
                        sql_text("SELECT id, platform FROM publisher_accounts WHERE platform=:p AND is_active=TRUE"),
                        {"p": platform},
                    )
                else:
                    rows = await conn.execute(
                        sql_text("SELECT id, platform FROM publisher_accounts WHERE is_active=1")
                    )
                accounts = [(int(r[0]), str(r[1])) for r in rows.fetchall()]

            count = 0
            for idx, (aid, pf) in enumerate(accounts):
                await self.update_weight(aid, pf)
                count += 1
                # 每 10 个账号让出事件循环，避免长时间阻塞（CPU 100% 优化）
                if idx > 0 and idx % 10 == 0:
                    await asyncio.sleep(0.5)
            logger.info(f"[AccountWeight] 已刷新 {count} 个账号权重")
            return count
        except Exception as e:
            logger.warning(f"[AccountWeight] 批量刷新失败: {e}")
            return 0


# ==================== 单例 ====================

_singleton: Optional[AccountWeightService] = None


def get_account_weight_service() -> AccountWeightService:
    global _singleton
    if _singleton is None:
        _singleton = AccountWeightService()
    return _singleton
