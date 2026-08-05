# -*- coding: utf-8 -*-
"""
独立机器人账号池

阶段一 P0 任务 1.5：补齐 PRD 5.4 互动主体"独立机器人账号池"概念，
与发布账号池分离。

设计：
1. 独立数据表 bot_accounts（与 publisher_accounts 分离）
2. BotAccountPool 单例服务，独立 cookie 池管理
3. 复用 account_health 评分逻辑，但独立存储
4. 支持按平台/分组/地区筛选
5. 集成到 BaseInteractor._get_account（替代从 publisher 账号池获取）

分组：
- domestic_new（国内新号）
- domestic_mature（国内成熟号）
- overseas_us（海外美国号）
- overseas_eu（海外欧洲号）
- overseas_sea（海外东南亚号）
"""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from api.schemas.accounts import AccountCreateRequest, AccountRole, AccountStatus, AccountUpdateRequest
from api.services.account_feature_flags import unified_account_read_enabled, unified_account_write_enabled
from api.services.unified_account_service import (
    AccountNotFoundError,
    UnifiedAccountService,
    stable_legacy_account_id,
)

logger = logging.getLogger(__name__)


class BotAccountStatus(str, Enum):
    """机器人账号状态"""
    ACTIVE = "active"
    COOLING = "cooling"            # 冷却中
    DISABLED = "disabled"
    LOGIN_EXPIRED = "login_expired"


class BotAccountGroup(str, Enum):
    """机器人账号分组"""
    DOMESTIC_NEW = "domestic_new"
    DOMESTIC_MATURE = "domestic_mature"
    OVERSEAS_US = "overseas_us"
    OVERSEAS_EU = "overseas_eu"
    OVERSEAS_SEA = "overseas_sea"


@dataclass
class BotAccount:
    """机器人账号"""
    account_id: str = ""
    platform: str = ""                # douyin / xiaohongshu / weibo / bilibili / zhihu / kuaishou / ...
    cookie: str = ""
    label: str = ""                   # 用户自定义标签
    group: str = BotAccountGroup.DOMESTIC_NEW.value
    region: str = "cn"                # cn / us / eu / sea
    status: str = BotAccountStatus.ACTIVE.value
    health_score: float = 100.0
    success_count: int = 0
    failure_count: int = 0
    cooldown_until: Optional[str] = None
    last_used_at: Optional[str] = None
    owner_user_id: Optional[int] = None
    created_at: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # 不返回原始 cookie（脱敏）
        if d.get("cookie"):
            d["cookie_masked"] = "***"
        d.pop("cookie", None)
        return d


class BotAccountPool:
    """机器人账号池服务（异步 PostgreSQL）"""

    # 失败 3 次进入冷却 30 分钟（与项目 memory 一致）
    MAX_FAILURES = 3
    COOLDOWN_SECONDS = 1800
    _ensured = False  # DDL 仅首次执行一次，避免每次请求都跑 CREATE TABLE/INDEX

    def __init__(self, session_factory=None):
        self._unified_service = UnifiedAccountService(session_factory)

    async def _from_unified(self, item: Dict[str, Any], *, include_auth: bool = False) -> BotAccount:
        cookie = ""
        if include_auth:
            auth_data = await self._unified_service.get_account_auth_data(
                item["account_id"], item.get("owner_user_id")
            )
            cookie = str(auth_data.get("cookies") or auth_data.get("cookie") or "")
        cooldown_until = item.get("cooldown_until") or 0
        last_used = item.get("last_used_ts") or 0
        status = item.get("status", BotAccountStatus.ACTIVE.value)
        if status == AccountStatus.COOLDOWN.value:
            status = BotAccountStatus.COOLING.value
        elif status in {AccountStatus.EXPIRED.value, AccountStatus.NEEDS_RELOGIN.value}:
            status = BotAccountStatus.LOGIN_EXPIRED.value
        owner = str(item.get("owner_user_id", ""))
        return BotAccount(
            account_id=item.get("account_id", ""),
            platform=item.get("platform", ""),
            cookie=cookie,
            label=item.get("account_name", ""),
            group=item.get("group_name", ""),
            region=item.get("region", ""),
            status=status,
            health_score=float(item.get("health_score", 100)),
            success_count=item.get("success_count", 0),
            failure_count=item.get("failure_count", 0),
            cooldown_until=datetime.fromtimestamp(cooldown_until).isoformat() if cooldown_until else None,
            last_used_at=datetime.fromtimestamp(last_used).isoformat() if last_used else None,
            owner_user_id=int(owner) if owner.isdigit() else None,
        )

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if unified_account_write_enabled():
            return
        if BotAccountPool._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS bot_accounts ("
                        "  account_id VARCHAR(64) PRIMARY KEY,"
                        "  platform VARCHAR(32) NOT NULL,"
                        "  cookie TEXT,"
                        "  label VARCHAR(128),"
                        "  account_group VARCHAR(32) DEFAULT 'domestic_new',"
                        "  region VARCHAR(16) DEFAULT 'cn',"
                        "  status VARCHAR(16) DEFAULT 'active',"
                        "  health_score FLOAT DEFAULT 100.0,"
                        "  success_count INTEGER DEFAULT 0,"
                        "  failure_count INTEGER DEFAULT 0,"
                        "  cooldown_until TIMESTAMP,"
                        "  last_used_at TIMESTAMP,"
                        "  owner_user_id INTEGER,"
                        "  extra TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW())"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_bot_accounts_platform_status "
                        "ON bot_accounts(platform, status)"
                    )
                )
            BotAccountPool._ensured = True
        except Exception as e:
            logger.warning(f"[BotAccountPool] ensure_table failed: {e}")

    async def add_account(
        self,
        platform: str,
        cookie: str,
        label: str = "",
        group: str = BotAccountGroup.DOMESTIC_NEW.value,
        region: str = "cn",
        owner_user_id: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> BotAccount:
        """添加机器人账号"""
        if unified_account_write_enabled():
            owner = str(owner_user_id) if owner_user_id is not None else ""
            account_name = label or f"{platform}_bot_{int(time.time())}"
            account_id = stable_legacy_account_id(owner, platform, account_name)
            try:
                existing = await self._unified_service.get_account(account_id, owner)
                role = (
                    AccountRole.BOTH
                    if existing["role"] == AccountRole.PUBLISHER.value
                    else AccountRole(existing["role"])
                )
                item = await self._unified_service.update_account(
                    account_id,
                    owner,
                    AccountUpdateRequest(
                        account_name=account_name,
                        role=role,
                        status=AccountStatus.ACTIVE,
                        auth_data={"cookies": cookie},
                        capabilities=list(dict.fromkeys(existing["capabilities"] + ["comment", "dm"])),
                        group_name=group,
                        region=region,
                    ),
                )
            except AccountNotFoundError:
                item = await self._unified_service.create_account(
                    owner,
                    AccountCreateRequest(
                        account_id=account_id,
                        platform=platform,
                        account_name=account_name,
                        role=AccountRole.INTERACTOR,
                        auth_data={"cookies": cookie},
                        capabilities=["comment", "dm"],
                        group_name=group,
                        region=region,
                    ),
                )
            return await self._from_unified(item, include_auth=True)
        await self.ensure_table()
        account = BotAccount(
            account_id=f"bot_{uuid.uuid4().hex[:12]}",
            platform=platform,
            cookie=cookie,
            label=label or f"{platform}_bot_{int(time.time())}",
            group=group,
            region=region,
            owner_user_id=owner_user_id,
            created_at=datetime.now().isoformat(),
            extra=extra or {},
        )
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return account
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO bot_accounts "
                        "(account_id, platform, cookie, label, account_group, region, status, "
                        " health_score, success_count, failure_count, owner_user_id, extra, created_at) "
                        "VALUES (:aid, :pf, :ck, :lb, :gp, :rg, :st, 100.0, 0, 0, :ouid, :ex, :ca)"
                    ),
                    {
                        "aid": account.account_id,
                        "pf": account.platform,
                        "ck": account.cookie,
                        "lb": account.label,
                        "gp": account.group,
                        "rg": account.region,
                        "st": account.status,
                        "ouid": account.owner_user_id,
                        "ex": json.dumps(account.extra, ensure_ascii=False),
                        "ca": datetime.now(),
                    },
                )
        except Exception as e:
            logger.warning(f"[BotAccountPool] add_account failed: {e}")
        return account

    async def get_account(
        self,
        platform: str,
        group: Optional[str] = None,
        region: Optional[str] = None,
        owner_user_id: Optional[int] = None,
    ) -> Optional[BotAccount]:
        """获取一个可用机器人账号（轮换策略）"""
        if unified_account_read_enabled():
            item = await self._unified_service.acquire_account(
                platform=platform,
                role=AccountRole.INTERACTOR,
                owner_user_id=str(owner_user_id) if owner_user_id is not None else None,
                group_name=group,
                region=region,
            )
            return await self._from_unified(item, include_auth=True) if item else None
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                sql = (
                    "SELECT * FROM bot_accounts "
                    "WHERE platform = :pf AND status = 'active' "
                    "AND (cooldown_until IS NULL OR cooldown_until < NOW()) "
                )
                params: Dict[str, Any] = {"pf": platform}
                if group:
                    sql += " AND account_group = :gp"
                    params["gp"] = group
                if region:
                    sql += " AND region = :rg"
                    params["rg"] = region
                if owner_user_id is not None:
                    sql += " AND owner_user_id = :ouid"
                    params["ouid"] = owner_user_id
                # 轮换：按 last_used_at ASC（最久未用的优先）
                sql += " ORDER BY last_used_at NULLS FIRST, health_score DESC LIMIT 1"
                rows = await conn.execute(sql_text(sql), params)
                row = rows.fetchone()
                if not row:
                    return None
                account = self._row_to_account(row)
                # 标记使用
                await conn.execute(
                    sql_text(
                        "UPDATE bot_accounts SET last_used_at = NOW() WHERE account_id = :aid"
                    ),
                    {"aid": account.account_id},
                )
                return account
        except Exception as e:
            logger.warning(f"[BotAccountPool] get_account failed: {e}")
            return None

    async def list_accounts(
        self,
        platform: Optional[str] = None,
        group: Optional[str] = None,
        region: Optional[str] = None,
        status: Optional[str] = None,
        owner_user_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if unified_account_read_enabled():
            mapped_status = status
            if status == BotAccountStatus.COOLING.value:
                mapped_status = AccountStatus.COOLDOWN.value
            elif status == BotAccountStatus.LOGIN_EXPIRED.value:
                mapped_status = AccountStatus.NEEDS_RELOGIN.value
            status_enum = AccountStatus(mapped_status) if mapped_status else None
            result = await self._unified_service.list_accounts_for_role(
                role=AccountRole.INTERACTOR,
                owner_user_id=str(owner_user_id) if owner_user_id is not None else None,
                platform=platform,
                group_name=group,
                status=status_enum,
                page=(offset // limit) + 1,
                page_size=limit,
            )
            items = [item for item in result["items"] if not region or item.get("region") == region]
            return [(await self._from_unified(item)).to_dict() for item in items]
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:  # 只读查询，使用 connect()
                sql = "SELECT * FROM bot_accounts WHERE 1=1"
                params: Dict[str, Any] = {"limit": limit, "offset": offset}
                if platform:
                    sql += " AND platform = :pf"
                    params["pf"] = platform
                if group:
                    sql += " AND account_group = :gp"
                    params["gp"] = group
                if region:
                    sql += " AND region = :rg"
                    params["rg"] = region
                if status:
                    sql += " AND status = :st"
                    params["st"] = status
                if owner_user_id is not None:
                    sql += " AND owner_user_id = :ouid"
                    params["ouid"] = owner_user_id
                sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_account(r).to_dict() for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[BotAccountPool] list_accounts failed: {e}")
            return []

    async def mark_success(self, account_id: str) -> None:
        """标记成功使用"""
        if unified_account_write_enabled():
            try:
                item = await self._unified_service.get_account(account_id)
                await self._unified_service.mark_success(account_id, item["owner_user_id"])
            except AccountNotFoundError:
                pass
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                # 健康分 +5（上限 100），success_count +1，failure_count 重置为 0
                await conn.execute(
                    sql_text(
                        "UPDATE bot_accounts SET "
                        " success_count = success_count + 1, "
                        " failure_count = 0, "
                        " health_score = LEAST(100.0, health_score + 5.0), "
                        " status = 'active', "
                        " cooldown_until = NULL "
                        "WHERE account_id = :aid"
                    ),
                    {"aid": account_id},
                )
        except Exception as e:
            logger.warning(f"[BotAccountPool] mark_success failed: {e}")

    async def mark_failed(
        self, account_id: str, failure_type: str = "unknown"
    ) -> Tuple[str, Optional[str]]:
        """标记失败，返回 (新状态, 冷却截止时间)"""
        if unified_account_write_enabled():
            try:
                item = await self._unified_service.get_account(account_id)
                updated = await self._unified_service.mark_failure(
                    account_id,
                    item["owner_user_id"],
                    cooldown_seconds=self.COOLDOWN_SECONDS,
                )
                if updated["status"] == AccountStatus.COOLDOWN.value:
                    return (
                        BotAccountStatus.COOLING.value,
                        datetime.fromtimestamp(updated["cooldown_until"]).isoformat(),
                    )
                if updated["status"] == AccountStatus.DISABLED.value:
                    return (BotAccountStatus.DISABLED.value, None)
                return (BotAccountStatus.ACTIVE.value, None)
            except AccountNotFoundError:
                return (BotAccountStatus.ACTIVE.value, None)
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return (BotAccountStatus.ACTIVE.value, None)
            async with engine.begin() as conn:
                # 健康分 -15，failure_count +1
                await conn.execute(
                    sql_text(
                        "UPDATE bot_accounts SET "
                        " failure_count = failure_count + 1, "
                        " health_score = GREATEST(0.0, health_score - 15.0) "
                        "WHERE account_id = :aid "
                        "RETURNING failure_count, health_score"
                    ),
                    {"aid": account_id},
                )
                # 重新查询状态
                rows = await conn.execute(
                    sql_text(
                        "SELECT failure_count, health_score FROM bot_accounts WHERE account_id = :aid"
                    ),
                    {"aid": account_id},
                )
                row = rows.fetchone()
                if not row:
                    return (BotAccountStatus.ACTIVE.value, None)
                failure_count = row[0] or 0
                health_score = float(row[1] or 0)
                # 失败 >= MAX_FAILURES 进入冷却
                if failure_count >= self.MAX_FAILURES:
                    cooldown_until = datetime.now() + _timedelta(seconds=self.COOLDOWN_SECONDS)
                    new_status = BotAccountStatus.COOLING.value
                    await conn.execute(
                        sql_text(
                            "UPDATE bot_accounts SET status = :st, cooldown_until = :cu "
                            "WHERE account_id = :aid"
                        ),
                        {"st": new_status, "cu": cooldown_until, "aid": account_id},
                    )
                    # 触发账号异常预警
                    try:
                        from api.services.alert.alert_center import emit_account_anomaly
                        await emit_account_anomaly(
                            platform="unknown",
                            account_label=account_id,
                            failure_type=failure_type,
                            details=f"连续失败 {failure_count} 次，已进入冷却 {self.COOLDOWN_SECONDS}s",
                        )
                    except Exception:
                        pass
                    return (new_status, cooldown_until.isoformat())
                # 健康分过低
                if health_score < 30:
                    new_status = BotAccountStatus.DISABLED.value
                    await conn.execute(
                        sql_text(
                            "UPDATE bot_accounts SET status = :st WHERE account_id = :aid"
                        ),
                        {"st": new_status, "aid": account_id},
                    )
                    return (new_status, None)
            return (BotAccountStatus.ACTIVE.value, None)
        except Exception as e:
            logger.warning(f"[BotAccountPool] mark_failed failed: {e}")
            return (BotAccountStatus.ACTIVE.value, None)

    async def delete_account(self, account_id: str) -> bool:
        if unified_account_write_enabled():
            try:
                item = await self._unified_service.get_account(account_id)
                await self._unified_service.disable_account(account_id, item["owner_user_id"])
                return True
            except AccountNotFoundError:
                return False
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text("DELETE FROM bot_accounts WHERE account_id = :aid"),
                    {"aid": account_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[BotAccountPool] delete_account failed: {e}")
            return False

    async def batch_add_from_cookies(
        self,
        platform: str,
        cookies_list: List[str],
        group: str = BotAccountGroup.DOMESTIC_NEW.value,
        region: str = "cn",
        owner_user_id: Optional[int] = None,
    ) -> List[BotAccount]:
        """批量从 cookie 字符串列表添加账号"""
        results = []
        for i, ck in enumerate(cookies_list):
            if not ck or not ck.strip():
                continue
            acc = await self.add_account(
                platform=platform,
                cookie=ck.strip(),
                label=f"{platform}_bot_{int(time.time())}_{i+1}",
                group=group,
                region=region,
                owner_user_id=owner_user_id,
            )
            results.append(acc)
        return results

    async def stats(self, platform: Optional[str] = None) -> Dict[str, Any]:
        """账号池统计"""
        if unified_account_read_enabled():
            result = await self._unified_service.list_accounts_for_role(
                role=AccountRole.INTERACTOR,
                owner_user_id=None,
                platform=platform,
            )
            stats: Dict[str, int] = {}
            for item in result["items"]:
                status = item["status"]
                if status == AccountStatus.COOLDOWN.value:
                    status = BotAccountStatus.COOLING.value
                stats[status] = stats.get(status, 0) + 1
            stats["total"] = result["total"]
            return stats
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return {}
            async with engine.connect() as conn:
                if platform:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT status, COUNT(*) FROM bot_accounts WHERE platform = :pf "
                            "GROUP BY status"
                        ),
                        {"pf": platform},
                    )
                else:
                    rows = await conn.execute(
                        sql_text("SELECT status, COUNT(*) FROM bot_accounts GROUP BY status")
                    )
                stats = {r[0]: int(r[1]) for r in rows.fetchall()}
                stats["total"] = sum(stats.values())
                return stats
        except Exception as e:
            logger.warning(f"[BotAccountPool] stats failed: {e}")
            return {}

    def _row_to_account(self, row) -> BotAccount:
        try:
            extra = json.loads(row[13]) if row[13] else {}
        except Exception:
            extra = {}
        return BotAccount(
            account_id=row[0],
            platform=row[1],
            cookie=row[2] or "",
            label=row[3] or "",
            group=row[4] or BotAccountGroup.DOMESTIC_NEW.value,
            region=row[5] or "cn",
            status=row[6] or BotAccountStatus.ACTIVE.value,
            health_score=float(row[7] or 100.0),
            success_count=int(row[8] or 0),
            failure_count=int(row[9] or 0),
            cooldown_until=str(row[10]) if row[10] else None,
            last_used_at=str(row[11]) if row[11] else None,
            owner_user_id=row[12],
            extra=extra,
            created_at=str(row[14]) if row[14] else None,
        )


# timedelta 兼容辅助
def _timedelta(seconds: int):
    from datetime import timedelta
    return timedelta(seconds=seconds)


# ============ 单例 ============
_pool: Optional[BotAccountPool] = None


def get_bot_account_pool() -> BotAccountPool:
    global _pool
    if _pool is None:
        _pool = BotAccountPool()
    return _pool
