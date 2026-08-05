# -*- coding: utf-8 -*-
"""统一账号业务服务。

该服务是发布、互动、风控和统计后续共同使用的账号数据入口。本阶段只新增
统一能力，不会自动迁移或删除 ``publisher_accounts``、``bot_accounts``。
"""

import asyncio
import hashlib
import json
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from api.schemas.accounts import (
    AccountCreateRequest,
    AccountRole,
    AccountStatus,
    AccountUpdateRequest,
    normalize_platform,
)
from database.models import UnifiedAccount


class UnifiedAccountError(Exception):
    """统一账号服务基础异常。"""


class AccountNotFoundError(UnifiedAccountError):
    pass


class DuplicateAccountError(UnifiedAccountError):
    pass


def stable_legacy_account_id(owner_user_id: str, platform: str, identity: str) -> str:
    raw = f"{owner_user_id}|{normalize_platform(platform)}|{identity.strip().lower()}".encode("utf-8")
    return f"legacy_{hashlib.sha256(raw).hexdigest()[:24]}"


def _json_dumps(value: Any, field_name: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise UnifiedAccountError(f"{field_name} 必须是可序列化的 JSON 数据") from exc


def _json_loads(value: str, fallback: Any) -> Any:
    try:
        parsed = json.loads(value or "")
        return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _mask_auth_data(auth_data: Dict[str, Any]) -> Dict[str, str]:
    """只返回已配置的认证字段名，绝不返回认证值片段。"""

    return {str(key): "***" for key, value in auth_data.items() if value not in (None, "", [], {})}


def account_to_dict(account: UnifiedAccount) -> Dict[str, Any]:
    auth_data = _json_loads(account.auth_data, {})
    capabilities = _json_loads(account.capabilities, [])
    now = int(time.time())
    return {
        "id": account.id,
        "account_id": account.account_id,
        "owner_user_id": account.owner_user_id,
        "platform": account.platform,
        "account_name": account.account_name,
        "role": account.role,
        "status": account.status,
        "auth_configured": bool(auth_data),
        "auth_preview": _mask_auth_data(auth_data if isinstance(auth_data, dict) else {}),
        "capabilities": capabilities if isinstance(capabilities, list) else [],
        "group_name": account.group_name,
        "region": account.region,
        "priority": account.priority,
        "weight": account.weight,
        "health_score": account.health_score,
        "daily_limit": account.daily_limit,
        "today_count": account.today_count,
        "success_count": account.success_count,
        "failure_count": account.failure_count,
        "cooldown_until": account.cooldown_until,
        "in_cooldown": account.cooldown_until > now,
        "last_used_ts": account.last_used_ts,
        "created_ts": account.created_ts,
        "updated_ts": account.updated_ts,
    }


class UnifiedAccountService:
    """统一账号 CRUD、状态和调度服务。"""

    MAX_FAILURES = 3
    DEFAULT_COOLDOWN_SECONDS = 1800

    def __init__(self, session_factory=None):
        self._session_factory = session_factory
        self._local_acquire_lock = asyncio.Lock()

    def _get_session_factory(self):
        if self._session_factory is None:
            from database.db_session import get_async_engine

            engine = get_async_engine()
            if engine is None:
                raise UnifiedAccountError("当前存储类型不支持统一账号数据库服务")
            self._session_factory = sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
        return self._session_factory

    async def create_account(
        self,
        owner_user_id: str,
        request: AccountCreateRequest,
    ) -> Dict[str, Any]:
        now = int(time.time())
        account = UnifiedAccount(
            account_id=request.account_id or f"acct_{uuid.uuid4().hex[:20]}",
            owner_user_id=str(owner_user_id),
            platform=normalize_platform(request.platform),
            account_name=request.account_name,
            role=request.role.value,
            status=request.status.value,
            auth_data=_json_dumps(request.auth_data, "auth_data"),
            capabilities=_json_dumps(request.capabilities, "capabilities"),
            group_name=request.group_name,
            region=request.region,
            priority=request.priority,
            weight=request.weight,
            health_score=request.health_score,
            daily_limit=request.daily_limit,
            today_count=0,
            today_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            success_count=0,
            failure_count=0,
            cooldown_until=0,
            last_used_ts=0,
            created_ts=now,
            updated_ts=now,
        )
        factory = self._get_session_factory()
        try:
            async with factory() as session:
                async with session.begin():
                    session.add(account)
                    await session.flush()
                    await session.refresh(account)
                return account_to_dict(account)
        except IntegrityError as exc:
            raise DuplicateAccountError(
                f"账号已存在: owner={owner_user_id}, platform={request.platform}, "
                f"account_id={account.account_id}"
            ) from exc

    async def batch_create_accounts(
        self,
        owner_user_id: str,
        requests: List[AccountCreateRequest],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        created: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        for index, request in enumerate(requests):
            try:
                created.append(await self.create_account(owner_user_id, request))
            except UnifiedAccountError as exc:
                failed.append(
                    {
                        "index": index,
                        "account_id": request.account_id,
                        "platform": request.platform,
                        "error": str(exc),
                    }
                )
        return created, failed

    async def get_account(
        self,
        account_id: str,
        owner_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        factory = self._get_session_factory()
        async with factory() as session:
            stmt = select(UnifiedAccount).where(UnifiedAccount.account_id == account_id)
            if owner_user_id is not None:
                stmt = stmt.where(UnifiedAccount.owner_user_id == str(owner_user_id))
            stmt = stmt.order_by(UnifiedAccount.id.asc()).limit(1)
            account = (await session.execute(stmt)).scalar_one_or_none()
            if account is None:
                raise AccountNotFoundError(f"账号不存在: {account_id}")
            return account_to_dict(account)

    async def get_account_auth_data(
        self,
        account_id: str,
        owner_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """供受信任的服务层读取认证信息；API 路由不得直接返回此结果。"""

        factory = self._get_session_factory()
        async with factory() as session:
            account = await self._find_model(session, account_id, owner_user_id, for_update=False)
            auth_data = _json_loads(account.auth_data, {})
            return auth_data if isinstance(auth_data, dict) else {}

    async def get_account_by_internal_id(
        self,
        internal_id: int,
        owner_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        factory = self._get_session_factory()
        async with factory() as session:
            stmt = select(UnifiedAccount).where(UnifiedAccount.id == internal_id)
            if owner_user_id is not None:
                stmt = stmt.where(UnifiedAccount.owner_user_id == str(owner_user_id))
            account = (await session.execute(stmt.limit(1))).scalar_one_or_none()
            if account is None:
                raise AccountNotFoundError(f"账号不存在: {internal_id}")
            return account_to_dict(account)

    async def get_account_auth_data_by_internal_id(self, internal_id: int) -> Dict[str, Any]:
        factory = self._get_session_factory()
        async with factory() as session:
            account = (
                await session.execute(select(UnifiedAccount).where(UnifiedAccount.id == internal_id).limit(1))
            ).scalar_one_or_none()
            if account is None:
                raise AccountNotFoundError(f"账号不存在: {internal_id}")
            auth_data = _json_loads(account.auth_data, {})
            return auth_data if isinstance(auth_data, dict) else {}

    async def list_accounts_for_role(
        self,
        *,
        role: AccountRole,
        owner_user_id: Optional[str],
        platform: Optional[str] = None,
        group_name: Optional[str] = None,
        status: Optional[AccountStatus] = None,
        page: int = 1,
        page_size: int = 500,
    ) -> Dict[str, Any]:
        filters = [UnifiedAccount.role.in_([role.value, AccountRole.BOTH.value])]
        if owner_user_id is not None:
            filters.append(UnifiedAccount.owner_user_id == str(owner_user_id))
        if platform:
            filters.append(UnifiedAccount.platform == normalize_platform(platform))
        if group_name:
            filters.append(UnifiedAccount.group_name == group_name)
        if status:
            filters.append(UnifiedAccount.status == status.value)
        factory = self._get_session_factory()
        async with factory() as session:
            total = int(
                (await session.execute(select(func.count(UnifiedAccount.id)).where(*filters))).scalar_one()
            )
            stmt = (
                select(UnifiedAccount)
                .where(*filters)
                .order_by(UnifiedAccount.priority.desc(), UnifiedAccount.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            accounts = (await session.execute(stmt)).scalars().all()
            return {
                "items": [account_to_dict(account) for account in accounts],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    async def list_accounts(
        self,
        *,
        owner_user_id: Optional[str],
        platform: Optional[str] = None,
        role: Optional[AccountRole] = None,
        status: Optional[AccountStatus] = None,
        group_name: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        filters = []
        if owner_user_id is not None:
            filters.append(UnifiedAccount.owner_user_id == str(owner_user_id))
        if platform:
            filters.append(UnifiedAccount.platform == normalize_platform(platform))
        if role:
            filters.append(UnifiedAccount.role == role.value)
        if status:
            filters.append(UnifiedAccount.status == status.value)
        if group_name:
            filters.append(UnifiedAccount.group_name == group_name)

        factory = self._get_session_factory()
        async with factory() as session:
            count_stmt = select(func.count(UnifiedAccount.id))
            query = select(UnifiedAccount)
            if filters:
                count_stmt = count_stmt.where(*filters)
                query = query.where(*filters)
            total = int((await session.execute(count_stmt)).scalar_one())
            query = (
                query.order_by(UnifiedAccount.priority.desc(), UnifiedAccount.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            accounts = (await session.execute(query)).scalars().all()
            return {
                "items": [account_to_dict(account) for account in accounts],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    async def update_account(
        self,
        account_id: str,
        owner_user_id: Optional[str],
        request: AccountUpdateRequest,
    ) -> Dict[str, Any]:
        values = request.model_dump(exclude_unset=True)
        if not values:
            raise UnifiedAccountError("没有可更新的字段")
        if "role" in values:
            values["role"] = values["role"].value
        if "status" in values:
            values["status"] = values["status"].value
        if "platform" in values:
            values["platform"] = normalize_platform(values["platform"])
        if "auth_data" in values:
            values["auth_data"] = _json_dumps(values["auth_data"], "auth_data")
        if "capabilities" in values:
            values["capabilities"] = _json_dumps(values["capabilities"], "capabilities")
        values["updated_ts"] = int(time.time())

        factory = self._get_session_factory()
        try:
            async with factory() as session:
                async with session.begin():
                    account = await self._find_model(session, account_id, owner_user_id, for_update=True)
                    for key, value in values.items():
                        setattr(account, key, value)
                    await session.flush()
                    await session.refresh(account)
                return account_to_dict(account)
        except IntegrityError as exc:
            raise DuplicateAccountError("更新后的账号标识与现有账号冲突") from exc

    async def disable_account(
        self,
        account_id: str,
        owner_user_id: Optional[str],
    ) -> Dict[str, Any]:
        return await self.update_account(
            account_id,
            owner_user_id,
            AccountUpdateRequest(status=AccountStatus.DISABLED),
        )

    async def delete_migration_batch(self, batch_id: str) -> int:
        """删除指定迁移批次，供迁移回滚使用；普通账号不受影响。"""

        factory = self._get_session_factory()
        async with factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(UnifiedAccount).where(UnifiedAccount.migration_batch_id == batch_id)
                )
            return int(result.rowcount or 0)

    async def reset_cooldown(
        self,
        account_id: str,
        owner_user_id: Optional[str],
    ) -> Dict[str, Any]:
        factory = self._get_session_factory()
        async with factory() as session:
            async with session.begin():
                account = await self._find_model(session, account_id, owner_user_id, for_update=True)
                account.cooldown_until = 0
                if account.status == AccountStatus.COOLDOWN.value:
                    account.status = AccountStatus.ACTIVE.value
                account.updated_ts = int(time.time())
                await session.flush()
                await session.refresh(account)
            return account_to_dict(account)

    async def acquire_account(
        self,
        *,
        platform: str,
        role: AccountRole,
        owner_user_id: Optional[str],
        capability: Optional[str] = None,
        group_name: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """原子选取可用账号。

        PostgreSQL 使用 ``FOR UPDATE SKIP LOCKED``；进程内锁同时保护 SQLite
        测试环境和不支持行锁的数据库。
        """

        normalized_platform = normalize_platform(platform)
        now = int(time.time())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        factory = self._get_session_factory()
        async with self._local_acquire_lock:
            async with factory() as session:
                async with session.begin():
                    filters = [
                        UnifiedAccount.platform == normalized_platform,
                        UnifiedAccount.role.in_([role.value, AccountRole.BOTH.value]),
                        or_(
                            UnifiedAccount.status == AccountStatus.ACTIVE.value,
                            and_(
                                UnifiedAccount.status == AccountStatus.COOLDOWN.value,
                                UnifiedAccount.cooldown_until <= now,
                            ),
                        ),
                        UnifiedAccount.cooldown_until <= now,
                        UnifiedAccount.health_score > 0,
                    ]
                    if owner_user_id is not None:
                        filters.append(UnifiedAccount.owner_user_id == str(owner_user_id))
                    if group_name:
                        filters.append(UnifiedAccount.group_name == group_name)
                    if region:
                        filters.append(UnifiedAccount.region == region)
                    stmt = (
                        select(UnifiedAccount)
                        .where(*filters)
                        .order_by(
                            UnifiedAccount.priority.desc(),
                            UnifiedAccount.health_score.desc(),
                            UnifiedAccount.last_used_ts.asc(),
                        )
                        .limit(50)
                        .with_for_update(skip_locked=True)
                    )
                    candidates = (await session.execute(stmt)).scalars().all()
                    selected = None
                    for account in candidates:
                        capabilities = _json_loads(account.capabilities, [])
                        if capability and capability not in capabilities:
                            continue
                        if account.today_date != today:
                            account.today_date = today
                            account.today_count = 0
                        if account.daily_limit > 0 and account.today_count >= account.daily_limit:
                            continue
                        selected = account
                        break
                    if selected is None:
                        return None
                    selected.status = AccountStatus.ACTIVE.value
                    selected.last_used_ts = now
                    selected.today_count += 1
                    selected.updated_ts = now
                    await session.flush()
                    await session.refresh(selected)
                    return account_to_dict(selected)

    async def reset_daily_counts(self, role: Optional[AccountRole] = None) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        factory = self._get_session_factory()
        async with factory() as session:
            async with session.begin():
                stmt = select(UnifiedAccount).where(UnifiedAccount.today_date != today).with_for_update()
                if role:
                    stmt = stmt.where(UnifiedAccount.role.in_([role.value, AccountRole.BOTH.value]))
                accounts = (await session.execute(stmt)).scalars().all()
                for account in accounts:
                    account.today_count = 0
                    account.today_date = today
                    account.updated_ts = int(time.time())
            return len(accounts)

    async def mark_success(
        self,
        account_id: str,
        owner_user_id: Optional[str],
    ) -> Dict[str, Any]:
        factory = self._get_session_factory()
        async with factory() as session:
            async with session.begin():
                account = await self._find_model(session, account_id, owner_user_id, for_update=True)
                account.success_count += 1
                account.failure_count = 0
                if account.status == AccountStatus.COOLDOWN.value:
                    account.status = AccountStatus.ACTIVE.value
                    account.cooldown_until = 0
                account.updated_ts = int(time.time())
                await session.flush()
                await session.refresh(account)
            return account_to_dict(account)

    async def mark_failure(
        self,
        account_id: str,
        owner_user_id: Optional[str],
        *,
        status: Optional[AccountStatus] = None,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ) -> Dict[str, Any]:
        now = int(time.time())
        factory = self._get_session_factory()
        async with factory() as session:
            async with session.begin():
                account = await self._find_model(session, account_id, owner_user_id, for_update=True)
                account.failure_count += 1
                if status in {
                    AccountStatus.EXPIRED,
                    AccountStatus.INVALID,
                    AccountStatus.NEEDS_RELOGIN,
                    AccountStatus.DISABLED,
                }:
                    account.status = status.value
                elif status == AccountStatus.COOLDOWN or account.failure_count >= self.MAX_FAILURES:
                    account.status = AccountStatus.COOLDOWN.value
                    account.cooldown_until = now + max(0, cooldown_seconds)
                account.health_score = max(0, account.health_score - 10)
                account.updated_ts = now
                await session.flush()
                await session.refresh(account)
            return account_to_dict(account)

    async def get_stats(self, owner_user_id: Optional[str]) -> Dict[str, Any]:
        factory = self._get_session_factory()
        async with factory() as session:
            stmt = select(UnifiedAccount.platform, UnifiedAccount.role, UnifiedAccount.status)
            if owner_user_id is not None:
                stmt = stmt.where(UnifiedAccount.owner_user_id == str(owner_user_id))
            rows = (await session.execute(stmt)).all()
        return {
            "total": len(rows),
            "by_platform": dict(Counter(row.platform for row in rows)),
            "by_role": dict(Counter(row.role for row in rows)),
            "by_status": dict(Counter(row.status for row in rows)),
        }

    async def validate_local_account(
        self,
        account_id: str,
        owner_user_id: Optional[str],
    ) -> Dict[str, Any]:
        account = await self.get_account(account_id, owner_user_id)
        unavailable = {
            AccountStatus.EXPIRED.value,
            AccountStatus.INVALID.value,
            AccountStatus.NEEDS_RELOGIN.value,
            AccountStatus.DISABLED.value,
        }
        return {
            "account_id": account_id,
            "valid": account["auth_configured"] and account["status"] not in unavailable,
            "mode": "local",
            "status": account["status"],
            "message": "仅校验本地认证配置和账号状态；平台远程登录校验将在适配器接入阶段完成",
        }

    async def _find_model(
        self,
        session: AsyncSession,
        account_id: str,
        owner_user_id: Optional[str],
        *,
        for_update: bool,
    ) -> UnifiedAccount:
        stmt = select(UnifiedAccount).where(UnifiedAccount.account_id == account_id)
        if owner_user_id is not None:
            stmt = stmt.where(UnifiedAccount.owner_user_id == str(owner_user_id))
        stmt = stmt.order_by(UnifiedAccount.id.asc()).limit(1)
        if for_update:
            stmt = stmt.with_for_update()
        account = (await session.execute(stmt)).scalar_one_or_none()
        if account is None:
            raise AccountNotFoundError(f"账号不存在: {account_id}")
        return account


_service: Optional[UnifiedAccountService] = None


def get_unified_account_service() -> UnifiedAccountService:
    global _service
    if _service is None:
        _service = UnifiedAccountService()
    return _service
