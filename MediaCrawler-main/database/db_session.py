# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/database/db_session.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
from .models import Base
# 显式导入 user_models 以便 Base.metadata 包含 sys_user 表
from . import user_models  # noqa: F401
import config
from config.db_config import mysql_db_config, sqlite_db_config, postgres_db_config

# Keep a cache of engines
_engines = {}


async def create_database_if_not_exists(db_type: str):
    if db_type == "mysql" or db_type == "db":
        # Connect to the server without a database
        server_url = f"mysql+asyncmy://{mysql_db_config['user']}:{mysql_db_config['password']}@{mysql_db_config['host']}:{mysql_db_config['port']}"
        engine = create_async_engine(server_url, echo=False)
        async with engine.connect() as conn:
            await conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {mysql_db_config['db_name']}"))
        await engine.dispose()
    elif db_type == "postgres":
        # Connect to the default 'postgres' database
        server_url = f"postgresql+asyncpg://{postgres_db_config['user']}:{postgres_db_config['password']}@{postgres_db_config['host']}:{postgres_db_config['port']}/postgres"
        print(f"[init_db] Connecting to Postgres: host={postgres_db_config['host']}, port={postgres_db_config['port']}, user={postgres_db_config['user']}, dbname=postgres")
        # Isolation level AUTOCOMMIT is required for CREATE DATABASE
        engine = create_async_engine(server_url, echo=False, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            # Check if database exists
            result = await conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{postgres_db_config['db_name']}'"))
            if not result.scalar():
                await conn.execute(text(f"CREATE DATABASE {postgres_db_config['db_name']}"))
        await engine.dispose()


def get_async_engine(db_type: str = None):
    if db_type is None:
        db_type = config.SAVE_DATA_OPTION

    if db_type in _engines:
        return _engines[db_type]

    if db_type in ["json", "jsonl", "csv"]:
        return None

    if db_type == "sqlite":
        db_url = f"sqlite+aiosqlite:///{sqlite_db_config['db_path']}"
    elif db_type == "mysql" or db_type == "db":
        db_url = f"mysql+asyncmy://{mysql_db_config['user']}:{mysql_db_config['password']}@{mysql_db_config['host']}:{mysql_db_config['port']}/{mysql_db_config['db_name']}"
    elif db_type == "postgres":
        db_url = f"postgresql+asyncpg://{postgres_db_config['user']}:{postgres_db_config['password']}@{postgres_db_config['host']}:{postgres_db_config['port']}/{postgres_db_config['db_name']}"
    else:
        raise ValueError(f"Unsupported database type: {db_type}")

    engine = create_async_engine(db_url, echo=False)
    _engines[db_type] = engine
    return engine


async def create_tables(db_type: str = None):
    if db_type is None:
        db_type = config.SAVE_DATA_OPTION
    await create_database_if_not_exists(db_type)
    engine = get_async_engine(db_type)
    if engine:
        async with engine.begin() as conn:
            # 只创建不存在的表，不删除已有数据
            await conn.run_sync(Base.metadata.create_all)
        # 给已有业务表补充 owner_user_id 字段(数据隔离)
        await _migrate_owner_user_id(engine, db_type)
        # OAuth flow 的安全绑定字段可能来自增量升级，create_all 不会补列。
        await _ensure_opennotebook_oauth_columns(engine, db_type)
        # 付费视频提交的持久幂等字段/唯一索引也需要覆盖存量数据库。
        await _ensure_explainer_video_idempotency(engine, db_type)
        # 补充高频查询字段索引(对存量数据库生效,create_all 不会改已有表结构)
        await _ensure_indexes(engine, db_type)


async def _ensure_opennotebook_oauth_columns(engine, db_type: str):
    table = "sys_user_opennotebook_oauth_flow"
    columns = [
        ("browser_binding_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("expected_credential_version", "INTEGER NOT NULL DEFAULT 0"),
    ]
    if db_type == "postgres":
        async with engine.begin() as conn:
            for name, definition in columns:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {definition}")
                )
    elif db_type == "sqlite":
        async with engine.begin() as conn:
            for name, definition in columns:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass
    elif db_type in ("mysql", "db"):
        async with engine.begin() as conn:
            for name, definition in columns:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass


async def _ensure_explainer_video_idempotency(engine, db_type: str):
    table = "x_twitter_explainer_video_task"
    columns = [
        ("idempotency_key", "VARCHAR(64) NULL"),
        ("request_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("submission_payload", "TEXT"),
        ("grant_id", "VARCHAR(128) NOT NULL DEFAULT ''"),
    ]
    index = "uq_explainer_video_owner_idempotency"
    if db_type == "postgres":
        async with engine.begin() as conn:
            for name, definition in columns:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {definition}")
                )
            await conn.execute(
                text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {index} "
                    f"ON {table} (owner_user_id, idempotency_key)"
                )
            )
    elif db_type == "sqlite":
        async with engine.begin() as conn:
            for name, definition in columns:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass
            await conn.execute(
                text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {index} "
                    f"ON {table} (owner_user_id, idempotency_key)"
                )
            )
    elif db_type in ("mysql", "db"):
        async with engine.begin() as conn:
            for name, definition in columns:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass
            try:
                await conn.execute(
                    text(
                        f"CREATE UNIQUE INDEX {index} "
                        f"ON {table} (owner_user_id, idempotency_key)"
                    )
                )
            except Exception:
                pass
# 需要补充索引的字段清单 (table_name, column_name)
# 仅列出模型新增 index=True 但存量数据库可能缺失的字段
_INDEX_TARGETS = [
    ("x_twitter_sent_comment", "sent_status"),
    ("x_twitter_sent_comment", "sent_at"),
    ("x_twitter_sent_comment", "monitoring"),
    ("x_twitter_reply", "auto_reply_status"),
    ("x_twitter_reply", "auto_replied_at"),
    ("x_twitter_trending_post", "crawl_ts"),
]


async def _ensure_indexes(engine, db_type: str):
    """为存量数据库补充索引(IF NOT EXISTS)。

    SQLAlchemy 的 create_all 不会修改已存在表结构,新增的 index=True
    不会自动生效,需要手动 CREATE INDEX。
    支持 PostgreSQL / SQLite / MySQL。
    """
    if db_type == "postgres":
        async with engine.begin() as conn:
            for table, column in _INDEX_TARGETS:
                idx_name = f"ix_{table}_{column}"
                await conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({column})")
                )
    elif db_type == "sqlite":
        async with engine.begin() as conn:
            for table, column in _INDEX_TARGETS:
                idx_name = f"ix_{table}_{column}"
                # SQLite 支持 IF NOT EXISTS
                try:
                    await conn.execute(
                        text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({column})")
                    )
                except Exception:
                    pass
    elif db_type in ("mysql", "db"):
        async with engine.begin() as conn:
            for table, column in _INDEX_TARGETS:
                idx_name = f"ix_{table}_{column}"
                # MySQL 不支持 IF NOT EXISTS (8.0.29 之前),用 try 包裹
                try:
                    await conn.execute(
                        text(f"CREATE INDEX {idx_name} ON {table} ({column})")
                    )
                except Exception:
                    pass


async def _migrate_owner_user_id(engine, db_type: str):
    """为业务表补充 owner_user_id 字段(IF NOT EXISTS)。

    支持 PostgreSQL / SQLite / MySQL。
    SQLAlchemy 的 create_all 不会修改已存在表结构,需要手动 ALTER。
    """
    tables = [
        "crawler_task",
        "customer_lead",
        "outreach_record",
        "outreach_task",
        "auto_outreach_job",
        "lead_assignment",
    ]
    if db_type == "postgres":
        async with engine.begin() as conn:
            for t in tables:
                await conn.execute(
                    text(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(64) DEFAULT '' ")
                )
                await conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{t}_owner_user_id ON {t} (owner_user_id)"))
    elif db_type == "sqlite":
        async with engine.begin() as conn:
            for t in tables:
                try:
                    await conn.execute(text(f"ALTER TABLE {t} ADD COLUMN owner_user_id VARCHAR(64) DEFAULT ''"))
                except Exception:
                    pass  # 字段已存在
    elif db_type in ("mysql", "db"):
        async with engine.begin() as conn:
            for t in tables:
                # MySQL 不支持 IF NOT EXISTS for ADD COLUMN(8.0+ 部分支持),用 try 包裹
                try:
                    await conn.execute(text(f"ALTER TABLE {t} ADD COLUMN owner_user_id VARCHAR(64) DEFAULT ''"))
                    await conn.execute(text(f"CREATE INDEX ix_{t}_owner_user_id ON {t} (owner_user_id)"))
                except Exception:
                    pass


@asynccontextmanager
async def get_session() -> AsyncSession:
    engine = get_async_engine(config.SAVE_DATA_OPTION)
    if not engine:
        yield None
        return
    AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = AsyncSessionFactory()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise e
    finally:
        await session.close()
