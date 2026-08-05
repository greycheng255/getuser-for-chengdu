import json

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from database.models import UnifiedAccount
from tools.migrate_to_unified_accounts import LegacyAccountMigrator


@pytest.fixture
async def migration_runtime(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE publisher_accounts (id INTEGER PRIMARY KEY, user_id INTEGER, platform VARCHAR(32), "
            "account_name VARCHAR(128), cookies TEXT, status VARCHAR(32), is_active INTEGER, daily_limit INTEGER, "
            "today_count INTEGER, failures INTEGER, successes INTEGER, cooldown_until INTEGER, last_used_ts INTEGER, "
            "created_at DATETIME, updated_at DATETIME, `group` VARCHAR(64), region VARCHAR(16))"
        ))
        await conn.execute(text(
            "CREATE TABLE bot_accounts (account_id VARCHAR(64) PRIMARY KEY, platform VARCHAR(32), cookie TEXT, "
            "label VARCHAR(128), account_group VARCHAR(32), region VARCHAR(16), status VARCHAR(16), "
            "health_score FLOAT, success_count INTEGER, failure_count INTEGER, cooldown_until DATETIME, "
            "last_used_at DATETIME, owner_user_id INTEGER, extra TEXT, created_at DATETIME)"
        ))
    yield engine, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_is_idempotent_and_merges_roles(migration_runtime):
    engine, factory = migration_runtime
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO publisher_accounts "
            "(id,user_id,platform,account_name,cookies,status,is_active,daily_limit,today_count,failures,successes,`group`,region) "
            "VALUES (1,7,'dy','shared','pub=1','active',1,5,1,0,3,'mature','cn')"
        ))
        await conn.execute(text(
            "INSERT INTO bot_accounts "
            "(account_id,platform,cookie,label,account_group,region,status,health_score,success_count,failure_count,owner_user_id) "
            "VALUES ('bot-1','douyin','bot=2','shared','mature','cn','active',90,2,1,7)"
        ))

    migrator = LegacyAccountMigrator(factory, engine)
    dry_run = await migrator.run("dry-run", "batch-dry")
    assert dry_run["candidate_count"] == 1
    assert dry_run["merged_count"] == 1
    assert dry_run["conflict_count"] == 1
    async with engine.connect() as conn:
        target_exists_after_dry_run = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("unified_accounts")
        )
    assert target_exists_after_dry_run is False

    first = await migrator.run("apply", "batch-one")
    second = await migrator.run("apply", "batch-two")
    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert second["unchanged_count"] == 1

    async with factory() as session:
        account = (await session.execute(text("SELECT * FROM unified_accounts"))).mappings().one()
    assert account["platform"] == "douyin"
    assert account["role"] == "both"
    assert json.loads(account["auth_data"]) == {"cookies": "pub=1"}
    assert account["migration_batch_id"] == "batch-one"

    validation = await migrator.run("validate", "batch-validate")
    assert validation["valid"] is True
    assert validation["coverage_rate"] == 1.0


@pytest.mark.asyncio
async def test_validate_and_rollback_plan_do_not_create_target_table(
    migration_runtime,
):
    engine, factory = migration_runtime
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO publisher_accounts "
            "(id,user_id,platform,account_name,cookies,status,is_active) "
            "VALUES (1,1,'dy','read-only-check','cookie=1','active',1)"
        ))

    migrator = LegacyAccountMigrator(factory, engine)
    validation = await migrator.run("validate", "batch-validate-missing")
    plan = await migrator.run("rollback-plan", "batch-not-applied")

    assert validation["target_table_exists"] is False
    assert validation["valid"] is False
    assert validation["coverage_rate"] == 0.0
    assert plan["target_table_exists"] is False
    assert plan["rollback_candidate_count"] == 0
    async with engine.connect() as conn:
        target_exists = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("unified_accounts")
        )
    assert target_exists is False


@pytest.mark.asyncio
async def test_migration_reports_invalid_rows(migration_runtime):
    engine, factory = migration_runtime
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO publisher_accounts (id,user_id,platform,account_name,cookies,status,is_active) "
            "VALUES (1,1,'dy','','cookie=1','unknown',1)"
        ))
        await conn.execute(text(
            "INSERT INTO bot_accounts (account_id,platform,cookie,label,status) "
            "VALUES ('','xhs','cookie=2','missing-id','active')"
        ))

    report = await LegacyAccountMigrator(factory, engine).run("dry-run", "batch-invalid")
    assert report["candidate_count"] == 0
    assert report["failed_count"] == 2
    assert report["valid"] is False


@pytest.mark.asyncio
async def test_migration_rollback_requires_confirmation_and_is_batch_scoped(
    migration_runtime,
):
    engine, factory = migration_runtime
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO publisher_accounts "
            "(id,user_id,platform,account_name,cookies,status,is_active) "
            "VALUES (1,1,'dy','rollback-target','cookie=1','active',1)"
        ))

    migrator = LegacyAccountMigrator(factory, engine)
    applied = await migrator.run("apply", "batch-rollback")
    assert applied["created_count"] == 1

    plan = await migrator.run("rollback-plan", "batch-rollback")
    assert plan["rollback_candidate_count"] == 1
    assert plan["deleted_count"] == 0

    with pytest.raises(ValueError, match="--confirm-rollback"):
        await migrator.run("rollback", "batch-rollback")

    rolled_back = await migrator.run(
        "rollback", "batch-rollback", confirm_rollback=True
    )
    assert rolled_back["deleted_count"] == 1
    assert rolled_back["valid"] is True
    async with factory() as session:
        remaining = (await session.execute(
            text("SELECT COUNT(*) FROM unified_accounts")
        )).scalar_one()
    assert remaining == 0
