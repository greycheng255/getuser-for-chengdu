# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/conftest.py
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

"""
Pytest configuration and shared fixtures
"""

import pytest
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def project_root_path():
    """Return project root path"""
    return project_root


@pytest.fixture
def sample_xhs_note():
    """Sample Xiaohongshu note data for testing"""
    return {
        "note_id": "test_note_123",
        "type": "normal",
        "title": "Test Title",
        "desc": "This is a test description",
        "video_url": "",
        "time": 1700000000,
        "last_update_time": 1700000000,
        "user_id": "user_123",
        "nickname": "Test User",
        "avatar": "https://example.com/avatar.jpg",
        "liked_count": 100,
        "collected_count": 50,
        "comment_count": 25,
        "share_count": 10,
        "ip_location": "Shanghai",
        "image_list": "https://example.com/img1.jpg,https://example.com/img2.jpg",
        "tag_list": "test,programming,Python",
        "note_url": "https://www.xiaohongshu.com/explore/test_note_123",
        "source_keyword": "test keyword",
        "xsec_token": "test_token_123"
    }


@pytest.fixture
def sample_xhs_comment():
    """Sample Xiaohongshu comment data for testing"""
    return {
        "comment_id": "comment_123",
        "create_time": 1700000000,
        "ip_location": "Beijing",
        "note_id": "test_note_123",
        "content": "This is a test comment",
        "user_id": "user_456",
        "nickname": "Comment User",
        "avatar": "https://example.com/avatar2.jpg",
        "sub_comment_count": 5,
        "pictures": "",
        "parent_comment_id": 0,
        "like_count": 15
    }


@pytest.fixture
def sample_xhs_creator():
    """Sample Xiaohongshu creator data for testing"""
    return {
        "user_id": "creator_123",
        "nickname": "Creator Name",
        "gender": "Female",
        "avatar": "https://example.com/creator_avatar.jpg",
        "desc": "This is the creator bio",
        "ip_location": "Guangzhou",
        "follows": 500,
        "fans": 10000,
        "interaction": 50000,
        "tag_list": '{"profession": "Designer", "interest": "Photography"}'
    }


# ====================================================================
# API 测试基础设施(第四批自动化测试)
# 提供临时 SQLite + httpx AsyncClient + 鉴权 override
# ====================================================================

@pytest.fixture(scope="session")
def test_engine(tmp_path_factory):
    """会话级临时 SQLite engine(文件库),所有 API 测试共用

    注:用文件库而非 :memory:,因当前环境 sqlite3 模块对 in-memory 的
    deserialize 符号支持异常(undefined symbol sqlite3_deserialize)。
    """
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine
    from database.models import Base
    # 显式导入所有模型,确保 Base.metadata 完整
    from database import user_models  # noqa: F401
    from database.models import (  # noqa: F401
        CustomerLead, IntentRule, CrawlerTaskModel, KeywordCategory,
        OutreachRecord, OutreachTaskModel,
    )

    db_path = tmp_path_factory.mktemp("sqlite") / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    # account_pool 表在 account_pool.py 内动态注册到 Base.metadata
    from api.services.account_pool import _ensure_db_model
    _ensure_db_model()

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init())
    yield engine
    # 不 dispose,避免重复 import sqlite3 C 扩展触发符号错误


@pytest.fixture
async def app_client(test_engine):
    """httpx AsyncClient + ASGITransport

    - patch database.db_session.get_async_engine 指向临时 engine
    - override get_current_user 返回测试管理员
    - 每个测试前清空所有表(隔离)
    - 不触发 FastAPI lifespan(避免 startup_event 副作用)
    """
    import httpx
    import database.db_session as dbs
    from api.services.auth import get_current_user
    from api.main import app

    original_engine_fn = dbs.get_async_engine
    dbs.get_async_engine = lambda *a, **kw: test_engine

    async def fake_current_user():
        return {"id": 1, "username": "testadmin", "role": "admin", "status": "active"}

    app.dependency_overrides[get_current_user] = fake_current_user

    # 清空所有表(保证测试隔离) - 在 yield 前清,确保每个测试开始时干净
    async with test_engine.begin() as conn:
        from sqlalchemy import text
        # 只清测试实际用到的表
        for tbl in ["customer_lead", "intent_rule", "keyword_category",
                    "crawler_task", "task_log", "outreach_record", "outreach_task",
                    "notification", "user_need_analysis", "ad_content", "product_info"]:
            try:
                await conn.execute(text(f"DELETE FROM {tbl}"))
            except Exception:
                pass

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    dbs.get_async_engine = original_engine_fn
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
async def user_context(app_client, test_engine):
    """用户身份上下文管理器:临时切换到指定用户,退出后恢复 admin

    用法:
        async with user_context(2) as client:
            await client.get("/api/leads/list")  # user2 身份
        await app_client.get("/api/leads/list")  # 恢复 admin 身份
    """
    import database.db_session as dbs
    from api.services.auth import get_current_user
    from api.main import app

    dbs.get_async_engine = lambda *a, **kw: test_engine
    _original_override = app.dependency_overrides.get(get_current_user)

    class UserContext:
        def __init__(self, user_id, role="user"):
            self.user_id = user_id
            self.role = role

        async def __aenter__(self):
            async def fake_user():
                return {"id": self.user_id, "username": f"user{self.user_id}", "role": self.role, "status": "active"}
            app.dependency_overrides[get_current_user] = fake_user
            return app_client

        async def __aexit__(self, *_):
            if _original_override is not None:
                app.dependency_overrides[get_current_user] = _original_override
            else:
                app.dependency_overrides.pop(get_current_user, None)

    yield UserContext


@pytest.fixture
def seed_lead(test_engine):
    """插入一条测试线索,返回其 id"""
    import asyncio
    import time
    from database.models import CustomerLead
    from sqlalchemy import insert

    async def _insert(**overrides):
        now_ms = int(time.time() * 1000)
        row = {
            "task_id": "task_test_1",
            "platform": "douyin",
            "data_type": "comment",
            "data_id": "d1",
            "user_id": "u1",
            "sec_uid": "",
            "nickname": "测试用户",
            "avatar": "",
            "ip_location": "",
            "content": "想学这个,多少钱",
            "title": "",
            "url": "",
            "matched_keywords": "",
            "intent_type": "inquiry",
            "lead_score": 60,
            "status": "new",
            "notes": "",
            "add_ts": now_ms,
            "last_modify_ts": now_ms,
            "owner_user_id": "1",
        }
        row.update(overrides)
        async with test_engine.begin() as conn:
            result = await conn.execute(insert(CustomerLead).values(row))
            return result.inserted_primary_key[0]

    return _insert
