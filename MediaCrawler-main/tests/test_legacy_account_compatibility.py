import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from api.services.interactor.bot_account_pool import BotAccountPool, BotAccountStatus
from api.services.publisher.account_service import PlatformAccountService, _publisher_accounts_table
from database.models import UnifiedAccount


@pytest.fixture
async def account_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFIED_ACCOUNT_WRITE_ENABLED", "true")
    monkeypatch.setenv("UNIFIED_ACCOUNT_READ_ENABLED", "true")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compat.db'}")
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(UnifiedAccount.__table__.create)
    yield engine, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_services_share_unified_account_and_never_create_legacy_tables(account_runtime):
    engine, factory = account_runtime
    publisher = PlatformAccountService(factory)
    bot_pool = BotAccountPool(factory)

    published = await publisher.save_account(
        user_id=7,
        platform="dy",
        cookies="session=publisher-secret",
        account_name="shared-account",
        daily_limit=10,
    )
    interacted = await bot_pool.add_account(
        platform="douyin",
        cookie="session=interactor-secret",
        label="shared-account",
        owner_user_id=7,
    )

    assert published.account_id == interacted.account_id
    async with factory() as session:
        accounts = (await session.execute(select(UnifiedAccount))).scalars().all()
    assert len(accounts) == 1
    assert accounts[0].role == "both"

    async with engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert "publisher_accounts" not in table_names
    assert "bot_accounts" not in table_names

    publisher_list = await publisher.list_accounts(platform="dy", user_id=7)
    bot_list = await bot_pool.list_accounts(platform="douyin", owner_user_id=7)
    assert publisher_list[0].to_dict()["cookies_preview"] == "***"
    assert bot_list[0]["account_id"] == published.account_id
    assert "cookie" not in bot_list[0]


@pytest.mark.asyncio
async def test_cooldown_is_shared_by_publish_and_interact(account_runtime):
    _, factory = account_runtime
    publisher = PlatformAccountService(factory)
    bot_pool = BotAccountPool(factory)
    account = await publisher.save_account(
        user_id=9,
        platform="xhs",
        cookies="session=secret",
        account_name="risk-shared",
        daily_limit=10,
    )
    await bot_pool.add_account(
        platform="xiaohongshu",
        cookie="session=secret",
        label="risk-shared",
        owner_user_id=9,
    )

    status = None
    for _ in range(3):
        status, _ = await bot_pool.mark_failed(account.account_id)
    assert status == BotAccountStatus.COOLING.value
    assert await publisher.acquire_cookie("xiaohongshu", user_id=9) is None

    assert await publisher.reset_cooldown(account.id) is True
    assert await publisher.acquire_cookie("xiaohongshu", user_id=9) is not None


@pytest.mark.asyncio
async def test_read_flag_can_restore_legacy_publisher_reads(account_runtime, monkeypatch):
    engine, factory = account_runtime
    async with engine.begin() as conn:
        await conn.run_sync(_publisher_accounts_table().create)
        await conn.execute(
            _publisher_accounts_table().insert().values(
                user_id=3,
                platform="douyin",
                account_name="legacy-only",
                cookies="legacy-secret",
                status="active",
                is_active=1,
                daily_limit=5,
            )
        )
    monkeypatch.setenv("UNIFIED_ACCOUNT_READ_ENABLED", "false")
    accounts = await PlatformAccountService(factory).list_accounts(platform="douyin", user_id=3)
    assert len(accounts) == 1
    assert accounts[0].account_name == "legacy-only"
    assert accounts[0].to_dict()["cookies_preview"] == "***"
