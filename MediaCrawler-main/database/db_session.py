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
        # 获客采集增强: customer_lead 加8字段 + crawler_task 加5字段 + lead_comment_reply 新表
        await _ensure_lead_capture_columns(engine, db_type)


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


# 获客采集增强字段清单 (从 getuser-canrun 迁移)
# customer_lead 表: 角色标签 + 去重指纹 + 联系方式 + 回复监控
_LEAD_COLUMNS = [
    ("content_hash", "VARCHAR(64) DEFAULT ''"),         # md5 指纹,用于精确去重
    ("dup_count", "INTEGER DEFAULT 1"),                 # 重复命中次数(相似内容累加)
    ("role_tag", "VARCHAR(20) DEFAULT ''"),             # 角色分类: supplier/consumer/neutral
    ("contact_phone", "VARCHAR(20) DEFAULT ''"),        # 采集到的联系电话
    ("contact_wechat", "VARCHAR(64) DEFAULT ''"),       # 采集到的微信号
    ("bio_text", "TEXT"),                               # 用户主页简介(联系方式提取来源)
    ("contact_status", "VARCHAR(16) DEFAULT 'none'"),   # 联系方式采集状态: none/pending/found/not_found
    ("reply_monitor_ts", "BIGINT DEFAULT 0"),           # 上次回复监控扫描时间戳
]
# crawler_task 表: 精准获客配置(业务意图+意向词+排除词+角色+地区)
_TASK_LEAD_COLUMNS = [
    ("business_intent", "TEXT"),                        # 业务意图描述(如"寻找需要学琵琶的用户")
    ("intent_keywords", "TEXT"),                        # 意向词 JSON 数组(严格双词匹配用)
    ("exclude_keywords", "TEXT"),                       # 排除词 JSON 数组(命中即丢弃)
    ("target_role", "VARCHAR(20) DEFAULT 'c端用户'"),    # 目标角色: c端用户/厂家供应商/不限
    ("target_regions", "TEXT"),                         # 目标地区 JSON 数组(可选)
]
# lead_comment_reply 表: 线索评论回复监控(抖音版)
_LEAD_REPLY_TABLE_SQL_POSTGRES = """
CREATE TABLE IF NOT EXISTS lead_comment_reply (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER,
    task_id VARCHAR(255) DEFAULT '',
    platform VARCHAR(20) DEFAULT 'douyin',
    aweme_id VARCHAR(255) DEFAULT '',
    comment_id VARCHAR(255) DEFAULT '',
    parent_comment_id VARCHAR(255) DEFAULT '',
    user_id VARCHAR(255) DEFAULT '',
    sec_uid VARCHAR(255) DEFAULT '',
    nickname VARCHAR(255) DEFAULT '',
    avatar TEXT,
    content TEXT,
    like_count VARCHAR(255) DEFAULT '0',
    create_time BIGINT DEFAULT 0,
    is_from_lead INTEGER DEFAULT 0,
    is_read INTEGER DEFAULT 0,
    owner_user_id VARCHAR(64) DEFAULT '',
    add_ts BIGINT DEFAULT 0
)
"""
_LEAD_REPLY_TABLE_SQL_SQLITE = """
CREATE TABLE IF NOT EXISTS lead_comment_reply (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    task_id VARCHAR(255) DEFAULT '',
    platform VARCHAR(20) DEFAULT 'douyin',
    aweme_id VARCHAR(255) DEFAULT '',
    comment_id VARCHAR(255) DEFAULT '',
    parent_comment_id VARCHAR(255) DEFAULT '',
    user_id VARCHAR(255) DEFAULT '',
    sec_uid VARCHAR(255) DEFAULT '',
    nickname VARCHAR(255) DEFAULT '',
    avatar TEXT,
    content TEXT,
    like_count VARCHAR(255) DEFAULT '0',
    create_time BIGINT DEFAULT 0,
    is_from_lead INTEGER DEFAULT 0,
    is_read INTEGER DEFAULT 0,
    owner_user_id VARCHAR(64) DEFAULT '',
    add_ts BIGINT DEFAULT 0
)
"""
_LEAD_REPLY_TABLE_SQL_MYSQL = """
CREATE TABLE IF NOT EXISTS lead_comment_reply (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lead_id INT,
    task_id VARCHAR(255) DEFAULT '',
    platform VARCHAR(20) DEFAULT 'douyin',
    aweme_id VARCHAR(255) DEFAULT '',
    comment_id VARCHAR(255) DEFAULT '',
    parent_comment_id VARCHAR(255) DEFAULT '',
    user_id VARCHAR(255) DEFAULT '',
    sec_uid VARCHAR(255) DEFAULT '',
    nickname VARCHAR(255) DEFAULT '',
    avatar TEXT,
    content TEXT,
    like_count VARCHAR(255) DEFAULT '0',
    create_time BIGINT DEFAULT 0,
    is_from_lead TINYINT(1) DEFAULT 0,
    is_read TINYINT(1) DEFAULT 0,
    owner_user_id VARCHAR(64) DEFAULT '',
    add_ts BIGINT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""
# lead_comment_reply 字段补齐清单(对齐 getuser-canrun 源 schema)
# 用于存量表(旧 schema 缺字段)的 ALTER 补齐
_LEAD_REPLY_COLUMNS = [
    ("task_id", "VARCHAR(255) DEFAULT ''"),
    ("platform", "VARCHAR(20) DEFAULT 'douyin'"),
    ("aweme_id", "VARCHAR(255) DEFAULT ''"),
    ("comment_id", "VARCHAR(255) DEFAULT ''"),
    ("parent_comment_id", "VARCHAR(255) DEFAULT ''"),
    ("sec_uid", "VARCHAR(255) DEFAULT ''"),
    ("nickname", "VARCHAR(255) DEFAULT ''"),
    ("avatar", "TEXT"),
    ("like_count", "VARCHAR(255) DEFAULT '0'"),
    ("create_time", "BIGINT DEFAULT 0"),
    ("owner_user_id", "VARCHAR(64) DEFAULT ''"),
    ("add_ts", "BIGINT DEFAULT 0"),
]
# sys_user_cookie 表 purpose 字段(Cookie 用途分离: crawl/outreach/both)
_USER_COOKIE_PURPOSE_COLUMN = ("purpose", "VARCHAR(20) DEFAULT 'both'")


async def _ensure_lead_capture_columns(engine, db_type: str):
    """获客采集增强迁移: 补充 customer_lead/crawler_task 字段 + 创建 lead_comment_reply 表。

    覆盖 getuser-canrun 迁移方案 v2.0 的 A 类数据基础:
    - customer_lead +8 字段: 去重指纹/角色标签/联系方式/回复监控时间
    - crawler_task +5 字段: 精准获客配置(业务意图/意向词/排除词/目标角色/目标地区)
    - lead_comment_reply 新表: 线索评论回复监控(抖音版,对齐源 schema)
    - sys_user_cookie +purpose 字段: Cookie 用途分离(crawl/outreach/both)
    支持 PostgreSQL / SQLite / MySQL。
    """
    # 通用索引清单(三方言共用)
    _lead_reply_indexes = [
        "ix_lead_comment_reply_lead_id ON lead_comment_reply (lead_id)",
        "ix_lead_comment_reply_task_id ON lead_comment_reply (task_id)",
        "ix_lead_comment_reply_aweme_id ON lead_comment_reply (aweme_id)",
        "ix_lead_comment_reply_comment_id ON lead_comment_reply (comment_id)",
        "ix_lead_comment_reply_owner_user_id ON lead_comment_reply (owner_user_id)",
        "ix_customer_lead_content_hash ON customer_lead (content_hash)",
        "ix_customer_lead_role_tag ON customer_lead (role_tag)",
    ]

    if db_type == "postgres":
        async with engine.begin() as conn:
            for name, definition in _LEAD_COLUMNS:
                await conn.execute(
                    text(f"ALTER TABLE customer_lead ADD COLUMN IF NOT EXISTS {name} {definition}")
                )
            for name, definition in _TASK_LEAD_COLUMNS:
                await conn.execute(
                    text(f"ALTER TABLE crawler_task ADD COLUMN IF NOT EXISTS {name} {definition}")
                )
            # sys_user_cookie.purpose 字段(Cookie 用途分离)
            await conn.execute(
                text(f"ALTER TABLE sys_user_cookie ADD COLUMN IF NOT EXISTS "
                     f"{_USER_COOKIE_PURPOSE_COLUMN[0]} {_USER_COOKIE_PURPOSE_COLUMN[1]}")
            )
            # lead_comment_reply: 建表 + 字段补齐(存量旧 schema 表补字段)
            await conn.execute(text(_LEAD_REPLY_TABLE_SQL_POSTGRES))
            for name, definition in _LEAD_REPLY_COLUMNS:
                await conn.execute(
                    text(f"ALTER TABLE lead_comment_reply ADD COLUMN IF NOT EXISTS {name} {definition}")
                )
            for idx_clause in _lead_reply_indexes:
                await conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_clause}"))
    elif db_type == "sqlite":
        async with engine.begin() as conn:
            for name, definition in _LEAD_COLUMNS:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE customer_lead ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass  # 字段已存在
            for name, definition in _TASK_LEAD_COLUMNS:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE crawler_task ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass
            try:
                await conn.execute(
                    text(f"ALTER TABLE sys_user_cookie ADD COLUMN "
                         f"{_USER_COOKIE_PURPOSE_COLUMN[0]} {_USER_COOKIE_PURPOSE_COLUMN[1]}")
                )
            except Exception:
                pass
            await conn.execute(text(_LEAD_REPLY_TABLE_SQL_SQLITE))
            for name, definition in _LEAD_REPLY_COLUMNS:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE lead_comment_reply ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass
            for idx_clause in _lead_reply_indexes:
                try:
                    await conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_clause}"))
                except Exception:
                    pass
    elif db_type in ("mysql", "db"):
        async with engine.begin() as conn:
            for name, definition in _LEAD_COLUMNS:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE customer_lead ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass
            for name, definition in _TASK_LEAD_COLUMNS:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE crawler_task ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass
            try:
                await conn.execute(
                    text(f"ALTER TABLE sys_user_cookie ADD COLUMN "
                         f"{_USER_COOKIE_PURPOSE_COLUMN[0]} {_USER_COOKIE_PURPOSE_COLUMN[1]}")
                )
            except Exception:
                pass
            await conn.execute(text(_LEAD_REPLY_TABLE_SQL_MYSQL))
            for name, definition in _LEAD_REPLY_COLUMNS:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE lead_comment_reply ADD COLUMN {name} {definition}")
                    )
                except Exception:
                    pass
            # MySQL 8.0.29 之前不支持 IF NOT EXISTS,用 try 包裹
            for idx_clause in _lead_reply_indexes:
                try:
                    await conn.execute(text(f"CREATE INDEX {idx_clause}"))
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
