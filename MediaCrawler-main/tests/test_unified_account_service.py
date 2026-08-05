# -*- coding: utf-8 -*-
"""统一账号契约和服务专项测试。"""

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.schemas.accounts import (
    AccountCreateRequest,
    AccountRole,
    AccountStatus,
    AccountUpdateRequest,
    normalize_platform,
)
from api.services.unified_account_service import (
    AccountNotFoundError,
    DuplicateAccountError,
    UnifiedAccountService,
)
from database.models import UnifiedAccount


@pytest_asyncio.fixture
async def account_service():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(UnifiedAccount.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = UnifiedAccountService(factory)
    try:
        yield service
    finally:
        await engine.dispose()


def account_request(**overrides):
    values = {
        "platform": "douyin",
        "account_name": "测试账号",
        "role": AccountRole.PUBLISHER,
        "auth_data": {"cookie": "secret-cookie", "token": "secret-token"},
        "capabilities": ["image", "video"],
        "group_name": "domestic_new",
        "daily_limit": 2,
    }
    values.update(overrides)
    return AccountCreateRequest(**values)


def test_platform_aliases_are_normalized():
    assert normalize_platform("DY") == "douyin"
    assert normalize_platform("xhs") == "xiaohongshu"
    assert normalize_platform("twitter") == "x_twitter"


def test_invalid_platform_and_capability_are_rejected():
    with pytest.raises(ValueError):
        normalize_platform("unknown-platform")
    with pytest.raises(ValidationError):
        account_request(capabilities=["image", "unsupported"])


@pytest.mark.asyncio
async def test_create_list_update_and_mask_auth(account_service):
    created = await account_service.create_account(
        "user-1",
        account_request(account_id="acct_test_1", platform="dy"),
    )
    assert created["platform"] == "douyin"
    assert created["auth_configured"] is True
    assert created["auth_preview"] == {"cookie": "***", "token": "***"}
    assert "secret-cookie" not in str(created)

    result = await account_service.list_accounts(
        owner_user_id="user-1",
        platform="douyin",
        role=AccountRole.PUBLISHER,
    )
    assert result["total"] == 1
    assert result["items"][0]["account_id"] == "acct_test_1"

    updated = await account_service.update_account(
        "acct_test_1",
        "user-1",
        AccountUpdateRequest(role=AccountRole.BOTH, priority=20),
    )
    assert updated["role"] == "both"
    assert updated["priority"] == 20


@pytest.mark.asyncio
async def test_duplicate_account_is_rejected(account_service):
    request = account_request(account_id="acct_duplicate")
    await account_service.create_account("user-1", request)
    with pytest.raises(DuplicateAccountError):
        await account_service.create_account("user-1", request)


@pytest.mark.asyncio
async def test_accounts_are_isolated_by_owner(account_service):
    await account_service.create_account(
        "user-1",
        account_request(account_id="acct_owner_1"),
    )
    await account_service.create_account(
        "user-2",
        account_request(account_id="acct_owner_2"),
    )

    user_1 = await account_service.list_accounts(owner_user_id="user-1")
    assert user_1["total"] == 1
    assert user_1["items"][0]["account_id"] == "acct_owner_1"

    with pytest.raises(AccountNotFoundError):
        await account_service.get_account("acct_owner_2", "user-1")


@pytest.mark.asyncio
async def test_acquire_honors_role_capability_priority_and_daily_limit(account_service):
    await account_service.create_account(
        "user-1",
        account_request(
            account_id="acct_low",
            role=AccountRole.BOTH,
            priority=1,
            daily_limit=5,
        ),
    )
    await account_service.create_account(
        "user-1",
        account_request(
            account_id="acct_high",
            role=AccountRole.PUBLISHER,
            priority=100,
            capabilities=["video"],
            daily_limit=1,
        ),
    )

    first = await account_service.acquire_account(
        platform="douyin",
        role=AccountRole.PUBLISHER,
        owner_user_id="user-1",
        capability="video",
    )
    assert first["account_id"] == "acct_high"
    assert first["today_count"] == 1

    second = await account_service.acquire_account(
        platform="douyin",
        role=AccountRole.PUBLISHER,
        owner_user_id="user-1",
        capability="video",
    )
    assert second["account_id"] == "acct_low"

    no_interactor = await account_service.acquire_account(
        platform="douyin",
        role=AccountRole.INTERACTOR,
        owner_user_id="user-1",
        capability="video",
    )
    assert no_interactor["account_id"] == "acct_low"


@pytest.mark.asyncio
async def test_failures_trigger_cooldown_and_reset(account_service):
    await account_service.create_account(
        "user-1",
        account_request(account_id="acct_cooldown", daily_limit=0),
    )
    await account_service.mark_failure("acct_cooldown", "user-1")
    await account_service.mark_failure("acct_cooldown", "user-1")
    failed = await account_service.mark_failure(
        "acct_cooldown",
        "user-1",
        cooldown_seconds=60,
    )
    assert failed["status"] == AccountStatus.COOLDOWN.value
    assert failed["in_cooldown"] is True
    assert failed["health_score"] == 70

    unavailable = await account_service.acquire_account(
        platform="douyin",
        role=AccountRole.PUBLISHER,
        owner_user_id="user-1",
    )
    assert unavailable is None

    reset = await account_service.reset_cooldown("acct_cooldown", "user-1")
    assert reset["status"] == AccountStatus.ACTIVE.value
    assert reset["in_cooldown"] is False


@pytest.mark.asyncio
async def test_disable_is_soft_delete(account_service):
    await account_service.create_account(
        "user-1",
        account_request(account_id="acct_disabled"),
    )
    disabled = await account_service.disable_account("acct_disabled", "user-1")
    assert disabled["status"] == AccountStatus.DISABLED.value
    assert (await account_service.get_account("acct_disabled", "user-1"))["status"] == "disabled"
