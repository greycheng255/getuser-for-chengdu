# -*- coding: utf-8 -*-
"""
平台账号服务（异步版）

迁移自 GEO-main 的 platform_account_postgres.py，适配 MediaCrawler 的：
1. SQLAlchemy async + MediaCrawler 的 get_session()
2. 多账号/平台（去除 UNIQUE(user_id, platform) 约束，支持 Cookie 池）
3. 集成 cookie_pool_manager 的冷却/失效机制

数据库表：publisher_accounts（新建）
- id, user_id, platform, account_name, cookies, status, is_active,
  daily_limit, today_count, last_login_time, last_publish_time, cookie_expires_at,
  failures, successes, cooldown_until, last_used_ts,
  created_at, updated_at
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Cookie 池配置（与 MediaCrawler 现有 cookie_pool_manager 对齐）
MAX_FAILURES = 3
COOLDOWN_SECONDS = 1800  # 30 分钟


@dataclass
class PublisherAccount:
    """发布账号（内存模型）"""

    id: Optional[int] = None
    user_id: int = 1
    platform: str = ""
    account_name: str = ""
    cookies: str = ""  # JSON 字符串或单值
    status: str = "active"  # active / expired / invalid / needs_relogin / cooldown
    is_active: bool = True
    daily_limit: int = 5
    today_count: int = 0
    today_date: str = ""  # YYYY-MM-DD，用于判断是否重置
    last_login_time: Optional[datetime] = None
    last_publish_time: Optional[datetime] = None
    cookie_expires_at: Optional[datetime] = None
    failures: int = 0
    successes: int = 0
    cooldown_until: int = 0
    last_used_ts: int = 0
    # 阶段四任务 4.3：账号分组（domestic_new / domestic_mature / overseas_us / overseas_eu）
    group: str = ""
    region: str = ""  # 地域（CN / US / EU / SEA 等）
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def is_available(self) -> bool:
        """是否可用（未冷却 + 配额未满）"""
        now = int(time.time())
        if self.cooldown_until > now:
            return False
        if self.today_count >= self.daily_limit:
            return False
        return self.is_active and self.status in ("active",)

    def to_dict(self, *, mask_cookies: bool = True) -> Dict[str, Any]:
        """转字典（可选脱敏 cookie）"""
        cookies_display = self.cookies
        if mask_cookies and cookies_display:
            cookies_display = cookies_display[:30] + "..." if len(cookies_display) > 30 else cookies_display
        return {
            "id": self.id,
            "user_id": self.user_id,
            "platform": self.platform,
            "account_name": self.account_name,
            "cookies_preview": cookies_display,
            "status": self.status,
            "is_active": self.is_active,
            "daily_limit": self.daily_limit,
            "today_count": self.today_count,
            "last_login_time": self.last_login_time.isoformat() if self.last_login_time else None,
            "last_publish_time": self.last_publish_time.isoformat() if self.last_publish_time else None,
            "failures": self.failures,
            "successes": self.successes,
            "cooldown_until": self.cooldown_until,
            "in_cooldown": self.cooldown_until > int(time.time()),
            "group": self.group,
            "region": self.region,
        }


class PlatformAccountService:
    """平台账号服务（异步）

    提供：
    1. 多账号/平台管理（替代 GEO 的 UNIQUE(user_id, platform) 单账号模式）
    2. Cookie 池 acquire/mark_success/mark_failure（与 MediaCrawler cookie_pool_manager 对齐）
    3. 每日配额管理（daily_limit + today_count + 0 点重置）
    4. 数据库持久化（PostgreSQL）
    """

    def __init__(self, session_factory):
        """
        Args:
            session_factory: 异步 session 工厂，如 MediaCrawler 的 get_session
                             （async context manager，返回 AsyncSession）
        """
        self._session_factory = session_factory
        self._lock = asyncio.Lock()

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self):
        """确保 publisher_accounts 表存在（首次调用时建表）

        复用 MediaCrawler 的 get_async_engine，避免引入新依赖。
        """
        if PlatformAccountService._ensured:
            return
        engine = self._get_engine()
        if engine is None:
            logger.warning("[AccountService] 无法获取数据库 engine，跳过建表")
            return
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda c: _ensure_publisher_accounts_table(c))
            logger.info("[AccountService] publisher_accounts 表已就绪")
            PlatformAccountService._ensured = True
        except Exception as e:
            logger.error(f"[AccountService] 建表失败: {e}")
            raise

    async def get_account_by_id(self, account_id: int) -> Optional[PublisherAccount]:
        """根据 ID 获取账号"""
        async with self._session_factory() as session:
            row = await session.execute(
                _select_account_by_id(account_id)
            )
            r = row.fetchone()
            return _row_to_account(r) if r else None

    async def list_accounts(
        self,
        platform: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> List[PublisherAccount]:
        """列出所有账号（可按平台/用户过滤）"""
        try:
            async with self._session_factory() as session:
                stmt = select(_publisher_accounts_table())
                if platform:
                    stmt = stmt.where(_publisher_accounts_table().c.platform == platform)
                if user_id is not None:
                    stmt = stmt.where(_publisher_accounts_table().c.user_id == user_id)
                stmt = stmt.order_by(_publisher_accounts_table().c.id.asc())
                result = await session.execute(stmt)
                return [_row_to_account(r) for r in result.fetchall()]
        except Exception as e:
            # 表可能还未创建，自动建表后返回空列表
            if "does not exist" in str(e).lower() or "relation" in str(e).lower():
                logger.info("[AccountService] 表不存在，自动建表")
                try:
                    await self.ensure_table()
                except Exception:
                    pass
                return []
            logger.error(f"[AccountService] 查询账号失败: {e}")
            return []

    async def save_account(
        self,
        user_id: int,
        platform: str,
        cookies: str,
        account_name: str = "",
        daily_limit: int = 5,
    ) -> PublisherAccount:
        """添加或更新账号（UPSERT 模式）"""
        # 表可能还未创建，先确保表存在
        try:
            await self.ensure_table()
        except Exception as e:
            logger.warning(f"[AccountService] save_account 建表失败: {e}")

        async with self._session_factory() as session:
            now = datetime.utcnow()
            today = now.strftime("%Y-%m-%d")

            # 使用 PostgreSQL UPSERT
            stmt = pg_insert(_publisher_accounts_table()).values(
                user_id=user_id,
                platform=platform,
                account_name=account_name or f"{platform}_{int(time.time())}",
                cookies=cookies,
                status="active",
                is_active=True,
                daily_limit=daily_limit,
                today_count=0,
                today_date=today,
                last_login_time=now,
                created_at=now,
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "platform", "account_name"],
                set_=dict(
                    cookies=stmt.excluded.cookies,
                    status="active",
                    is_active=True,
                    daily_limit=stmt.excluded.daily_limit,
                    last_login_time=now,
                    updated_at=now,
                ),
            )
            await session.execute(stmt)
            await session.commit()

            # 查回最新记录
            result = await session.execute(
                select(_publisher_accounts_table())
                .where(
                    and_(
                        _publisher_accounts_table().c.user_id == user_id,
                        _publisher_accounts_table().c.platform == platform,
                    )
                )
                .order_by(_publisher_accounts_table().c.id.desc())
                .limit(1)
            )
            r = result.fetchone()
            return _row_to_account(r)

    async def acquire_cookie(self, platform: str, user_id: int = 1) -> Optional[PublisherAccount]:
        """从池中获取一个可用账号

        策略：
        - 优先 successes 高且未冷却且今日有配额的
        - 全部不可用时返回 None
        - 更新 last_used_ts + today_count
        """
        async with self._lock:
            accounts = await self.list_accounts(platform=platform, user_id=user_id)
            if not accounts:
                logger.warning(f"[AccountService][{platform}] 无可用账号")
                return None

            now = int(time.time())
            today = datetime.utcnow().strftime("%Y-%m-%d")

            # 重置今日配额
            for acc in accounts:
                if acc.today_date != today:
                    acc.today_count = 0
                    acc.today_date = today

            available = [a for a in accounts if a.is_available()]
            if not available:
                # 全部不可用，返回最早可用的（不强制占用）
                earliest = min(accounts, key=lambda x: x.cooldown_until)
                logger.warning(
                    f"[AccountService][{platform}] 全部不可用，最早可用 cooldown_until={earliest.cooldown_until}"
                )
                return None

            # 优先按 account_weights 表的权重排序，fallback 到 successes 降序、last_used_ts 升序
            weight_map = await self._load_account_weights(platform)
            def _sort_key(x):
                w = weight_map.get(x.id, 50.0)
                # 权重为主，成功率与空闲度为辅，last_used_ts 越小（越久未用）越优先
                return (w, x.successes, -x.last_used_ts)
            chosen = max(available, key=_sort_key)
            chosen.last_used_ts = now
            chosen.today_count += 1

            # 同步到数据库
            async with self._session_factory() as session:
                await session.execute(
                    update(_publisher_accounts_table())
                    .where(_publisher_accounts_table().c.id == chosen.id)
                    .values(
                        last_used_ts=now,
                        today_count=chosen.today_count,
                        today_date=today,
                        last_publish_time=datetime.utcnow(),
                    )
                )
                await session.commit()

            logger.info(
                f"[AccountService][{platform}] 选中账号 {chosen.account_name}"
                f"（成功 {chosen.successes} / 失败 {chosen.failures} / 今日 {chosen.today_count}/{chosen.daily_limit}）"
            )
            return chosen

    async def _load_account_weights(self, platform: str) -> Dict[int, float]:
        """从 account_weights 表加载账号权重（接入 AccountWeightService）

        若表不存在或查询失败，返回空 dict，acquire_cookie 会 fallback 到默认权重 50.0。
        """
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return {}
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT account_id, weight FROM account_weights "
                        "WHERE platform=:p AND updated_at >= NOW() - INTERVAL '7 days'"
                    ),
                    {"p": platform},
                )
                return {int(r[0]): float(r[1]) for r in rows.fetchall() if r[0] is not None}
        except Exception:
            # 表可能未建或字段不一致，静默 fallback
            return {}

    async def mark_success(self, account_id: int):
        """标记账号使用成功"""
        async with self._session_factory() as session:
            await session.execute(
                update(_publisher_accounts_table())
                .where(_publisher_accounts_table().c.id == account_id)
                .values(
                    successes=_publisher_accounts_table().c.successes + 1,
                    failures=0,
                    cooldown_until=0,
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()

    async def mark_failure(self, account_id: int, reason: str = ""):
        """标记账号使用失败（连续 3 次进入冷却）"""
        async with self._session_factory() as session:
            # 先读当前 failures
            result = await session.execute(
                select(_publisher_accounts_table().c.failures)
                .where(_publisher_accounts_table().c.id == account_id)
            )
            row = result.fetchone()
            current_failures = row[0] if row else 0
            new_failures = current_failures + 1

            update_values = {
                "failures": new_failures,
                "updated_at": datetime.utcnow(),
            }
            if new_failures >= MAX_FAILURES:
                update_values["cooldown_until"] = int(time.time()) + COOLDOWN_SECONDS
                update_values["failures"] = 0  # 重置失败计数，进入冷却
                update_values["status"] = "cooldown"
                logger.warning(
                    f"[AccountService] 账号 {account_id} 连续失败 {MAX_FAILURES} 次，"
                    f"冷却 {COOLDOWN_SECONDS}s（原因: {reason}）"
                )
            await session.execute(
                update(_publisher_accounts_table())
                .where(_publisher_accounts_table().c.id == account_id)
                .values(**update_values)
            )
            await session.commit()

    async def mark_login_expired(self, account_id: int):
        """标记账号登录失效"""
        async with self._session_factory() as session:
            await session.execute(
                update(_publisher_accounts_table())
                .where(_publisher_accounts_table().c.id == account_id)
                .values(status="needs_relogin", is_active=False, updated_at=datetime.utcnow())
            )
            await session.commit()

    async def reset_daily_counts(self):
        """每日 0 点重置所有账号的今日配额（定时任务调用）"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with self._session_factory() as session:
            await session.execute(
                update(_publisher_accounts_table())
                .where(_publisher_accounts_table().c.today_date != today)
                .values(today_count=0, today_date=today)
            )
            await session.commit()
        logger.info("[AccountService] 已重置每日配额")

    async def get_pool_status(self, platform: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取池状态（前端展示用）"""
        accounts = await self.list_accounts(platform=platform)
        return [a.to_dict() for a in accounts]

    # ==================== 账号分组管理（阶段四任务 4.3） ====================

    async def list_by_group(
        self,
        group: str = "",
        platform: str = "",
        user_id: Optional[int] = None,
    ) -> List[PublisherAccount]:
        """按分组列出账号"""
        try:
            await self.ensure_table()
            async with self._session_factory() as session:
                stmt = select(_publisher_accounts_table())
                if group:
                    stmt = stmt.where(_publisher_accounts_table().c.group == group)
                if platform:
                    stmt = stmt.where(_publisher_accounts_table().c.platform == platform)
                if user_id is not None:
                    stmt = stmt.where(_publisher_accounts_table().c.user_id == user_id)
                stmt = stmt.order_by(_publisher_accounts_table().c.id.asc())
                result = await session.execute(stmt)
                return [_row_to_account(r) for r in result.fetchall()]
        except Exception as e:
            logger.warning(f"[AccountService] 按分组查询失败: {e}")
            return []

    async def list_by_region(
        self,
        region: str = "",
        platform: str = "",
    ) -> List[PublisherAccount]:
        """按地域列出账号"""
        try:
            await self.ensure_table()
            async with self._session_factory() as session:
                stmt = select(_publisher_accounts_table())
                if region:
                    stmt = stmt.where(_publisher_accounts_table().c.region == region)
                if platform:
                    stmt = stmt.where(_publisher_accounts_table().c.platform == platform)
                stmt = stmt.order_by(_publisher_accounts_table().c.id.asc())
                result = await session.execute(stmt)
                return [_row_to_account(r) for r in result.fetchall()]
        except Exception as e:
            logger.warning(f"[AccountService] 按地域查询失败: {e}")
            return []

    async def set_group(
        self, account_id: int, group: str, region: str = ""
    ) -> bool:
        """设置账号分组与地域"""
        try:
            async with self._session_factory() as session:
                values: Dict[str, Any] = {
                    "group": group,
                    "updated_at": datetime.utcnow(),
                }
                if region:
                    values["region"] = region
                stmt = (
                    update(_publisher_accounts_table())
                    .where(_publisher_accounts_table().c.id == account_id)
                    .values(**values)
                )
                await session.execute(stmt)
                await session.commit()
            logger.info(f"[AccountService] 账号 #{account_id} 分组已设为 {group}/{region}")
            return True
        except Exception as e:
            logger.warning(f"[AccountService] 设置分组失败: {e}")
            return False

    async def list_groups(self) -> List[Dict[str, Any]]:
        """列出所有已使用的分组及其账号数"""
        try:
            await self.ensure_table()
            from sqlalchemy import func as sa_func
            async with self._session_factory() as session:
                stmt = (
                    select(
                        _publisher_accounts_table().c.group,
                        _publisher_accounts_table().c.region,
                        sa_func.count(_publisher_accounts_table().c.id),
                    )
                    .where(_publisher_accounts_table().c.group != "")
                    .group_by(
                        _publisher_accounts_table().c.group,
                        _publisher_accounts_table().c.region,
                    )
                    .order_by(_publisher_accounts_table().c.group.asc())
                )
                result = await session.execute(stmt)
                return [
                    {"group": r[0], "region": r[1], "count": int(r[2])}
                    for r in result.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[AccountService] 列出分组失败: {e}")
            return []

    async def acquire_cookie_by_group(
        self,
        platform: str,
        group: str = "",
        region: str = "",
        user_id: int = 1,
    ) -> Optional[PublisherAccount]:
        """按分组 + 地域获取可用账号（海外平台优先匹配本地 IP）"""
        accounts = await self.list_by_group(group=group, platform=platform, user_id=user_id)
        if not accounts and region:
            accounts = await self.list_by_region(region=region, platform=platform)
        if not accounts:
            # 兜底：直接按平台取
            return await self.acquire_cookie(platform, user_id=user_id)
        # 在分组内选取可用账号（同 acquire_cookie 的轮换逻辑）
        import random
        available = [a for a in accounts if a.is_available()]
        if not available:
            return None
        chosen = random.choice(available)
        try:
            async with self._session_factory() as session:
                stmt = (
                    update(_publisher_accounts_table())
                    .where(_publisher_accounts_table().c.id == chosen.id)
                    .values(
                        last_used_ts=int(time.time()),
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.execute(stmt)
                await session.commit()
        except Exception:
            pass
        return chosen


# ==================== 数据库表定义（轻量级，独立于 MediaCrawler models）====================

from sqlalchemy import Column, DateTime, Integer, String, Table, MetaData, UniqueConstraint
from sqlalchemy.engine import Connection

_TABLE_NAME = "publisher_accounts"
_metadata = MetaData()

_publisher_accounts_tbl = Table(
    _TABLE_NAME,
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, default=1, index=True),
    Column("platform", String(32), nullable=False, index=True),
    Column("account_name", String(128), nullable=False),
    Column("cookies", String(8192), nullable=False),
    Column("status", String(32), nullable=False, default="active"),
    Column("is_active", Integer, nullable=False, default=1),
    Column("daily_limit", Integer, nullable=False, default=5),
    Column("today_count", Integer, nullable=False, default=0),
    Column("today_date", String(10), nullable=False, default=""),
    Column("last_login_time", DateTime, nullable=True),
    Column("last_publish_time", DateTime, nullable=True),
    Column("cookie_expires_at", DateTime, nullable=True),
    Column("failures", Integer, nullable=False, default=0),
    Column("successes", Integer, nullable=False, default=0),
    Column("cooldown_until", Integer, nullable=False, default=0),
    Column("last_used_ts", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("updated_at", DateTime, nullable=False, default=datetime.utcnow),
    # 唯一约束：支持 save_account 的 ON CONFLICT (user_id, platform, account_name) DO UPDATE
    UniqueConstraint("user_id", "platform", "account_name", name="uq_publisher_accounts_user_platform_name"),
)


def _ensure_publisher_accounts_table(conn: Connection):
    """建表（幂等）+ 列迁移（阶段四任务 4.3 增加 group/region 字段）+ 唯一约束补建"""
    _metadata.create_all(conn, tables=[_publisher_accounts_tbl], checkfirst=True)
    # 幂等增加新列（已存在则跳过）
    from sqlalchemy import text as sql_text, inspect as sa_inspect
    insp = sa_inspect(conn)
    existing_cols = {c["name"] for c in insp.get_columns(_TABLE_NAME)}
    if "group" not in existing_cols:
        conn.execute(sql_text(f'ALTER TABLE {_TABLE_NAME} ADD COLUMN "group" VARCHAR(64) DEFAULT \'\''))
    if "region" not in existing_cols:
        conn.execute(sql_text(f"ALTER TABLE {_TABLE_NAME} ADD COLUMN region VARCHAR(32) DEFAULT ''"))
    # 幂等补建唯一索引（save_account 用 ON CONFLICT (user_id, platform, account_name)）
    existing_indexes = {idx["name"] for idx in insp.get_indexes(_TABLE_NAME)}
    if "uq_publisher_accounts_user_platform_name" not in existing_indexes:
        try:
            conn.execute(sql_text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_publisher_accounts_user_platform_name "
                f"ON {_TABLE_NAME} (user_id, platform, account_name)"
            ))
        except Exception as e:
            # 可能因历史重复数据导致建索引失败，记录日志但不阻断启动
            logger.warning(f"[AccountService] 补建唯一索引失败（可能有重复数据）: {e}")


def _publisher_accounts_table():
    """获取 Table 对象（延迟导入以避免循环依赖）"""
    return _publisher_accounts_tbl


def _select_account_by_id(account_id: int):
    return select(_publisher_accounts_tbl).where(_publisher_accounts_tbl.c.id == account_id)


def _row_to_account(row) -> PublisherAccount:
    """数据库行转 PublisherAccount 对象"""
    if row is None:
        return None
    # row 是 Row 对象，支持 _mapping
    r = row._mapping if hasattr(row, "_mapping") else dict(row)
    return PublisherAccount(
        id=r.get("id"),
        user_id=r.get("user_id", 1),
        platform=r.get("platform", ""),
        account_name=r.get("account_name", ""),
        cookies=r.get("cookies", ""),
        status=r.get("status", "active"),
        is_active=bool(r.get("is_active", 1)),
        daily_limit=r.get("daily_limit", 5),
        today_count=r.get("today_count", 0),
        today_date=r.get("today_date", ""),
        last_login_time=r.get("last_login_time"),
        last_publish_time=r.get("last_publish_time"),
        cookie_expires_at=r.get("cookie_expires_at"),
        failures=r.get("failures", 0),
        successes=r.get("successes", 0),
        cooldown_until=r.get("cooldown_until", 0),
        last_used_ts=r.get("last_used_ts", 0),
        group=r.get("group", "") or "",
        region=r.get("region", "") or "",
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


# 模块级单例（懒加载）
_account_service: Optional[PlatformAccountService] = None


def get_account_service() -> PlatformAccountService:
    """获取 PlatformAccountService 单例"""
    global _account_service
    if _account_service is None:
        # 复用 MediaCrawler 的 get_session（@asynccontextmanager）
        from database.db_session import get_session
        _account_service = PlatformAccountService(session_factory=get_session)
    return _account_service
