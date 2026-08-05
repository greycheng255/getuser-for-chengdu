# -*- coding: utf-8 -*-
"""统一账号 API 独立回归测试。

项目 ``api.routers`` 包会聚合导入所有历史路由；本测试直接加载目标路由文件，
避免统一账号专项测试被其他可选平台依赖阻断。
"""

import importlib.util
import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.services.unified_account_service import UnifiedAccountService
from database.models import UnifiedAccount

os.environ.setdefault("JWT_SECRET_KEY", "unified-account-regression-test-secret")


def _load_accounts_router_module():
    path = Path(__file__).resolve().parents[1] / "api" / "routers" / "accounts.py"
    spec = importlib.util.spec_from_file_location("unified_accounts_router_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


accounts_router_module = _load_accounts_router_module()


@pytest_asyncio.fixture
async def api_context(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(UnifiedAccount.__table__.create)
    service = UnifiedAccountService(async_sessionmaker(engine, expire_on_commit=False))
    current_user = {"id": "user-1", "role": "operator", "status": "active"}

    async def override_current_user():
        return current_user

    monkeypatch.setattr(accounts_router_module, "get_unified_account_service", lambda: service)
    app = FastAPI()
    app.include_router(accounts_router_module.router, prefix="/api")
    app.dependency_overrides[accounts_router_module.get_current_user] = override_current_user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, service, current_user
    await engine.dispose()


@pytest.mark.asyncio
async def test_account_api_crud_and_sensitive_data_masking(api_context):
    client, _, _ = api_context
    create = await client.post(
        "/api/accounts",
        json={
            "account_id": "acct_api_1",
            "platform": "dy",
            "account_name": "接口测试账号",
            "role": "both",
            "auth_data": {"cookie": "do-not-leak", "token": "also-secret"},
            "capabilities": ["image", "comment"],
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["platform"] == "douyin"
    assert body["auth_configured"] is True
    assert body["auth_preview"] == {"cookie": "***", "token": "***"}
    assert "do-not-leak" not in create.text
    assert "also-secret" not in create.text

    listed = await client.get("/api/accounts?platform=douyin&role=both")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    updated = await client.put(
        "/api/accounts/acct_api_1",
        json={"priority": 99, "status": "cooldown"},
    )
    assert updated.status_code == 200
    assert updated.json()["priority"] == 99

    reset = await client.post("/api/accounts/acct_api_1/reset-cooldown")
    assert reset.status_code == 200
    assert reset.json()["status"] == "active"

    disabled = await client.delete("/api/accounts/acct_api_1")
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    detail = await client.get("/api/accounts/acct_api_1")
    assert detail.status_code == 200
    assert detail.json()["status"] == "disabled"


@pytest.mark.asyncio
async def test_account_api_batch_stats_and_duplicate_conflict(api_context):
    client, _, _ = api_context
    response = await client.post(
        "/api/accounts/batch",
        json={
            "items": [
                {
                    "account_id": "acct_batch_1",
                    "platform": "xhs",
                    "role": "publisher",
                    "auth_data": {"cookie": "secret"},
                },
                {
                    "account_id": "acct_batch_2",
                    "platform": "douyin",
                    "role": "interactor",
                    "auth_data": {"cookie": "secret"},
                },
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["created"]) == 2
    assert response.json()["failed"] == []

    duplicate = await client.post(
        "/api/accounts",
        json={"account_id": "acct_batch_1", "platform": "xiaohongshu"},
    )
    assert duplicate.status_code == 409

    stats = await client.get("/api/accounts/stats")
    assert stats.status_code == 200
    assert stats.json()["total"] == 2
    assert stats.json()["by_platform"] == {"douyin": 1, "xiaohongshu": 1}


@pytest.mark.asyncio
async def test_account_api_enforces_owner_scope(api_context):
    client, service, current_user = api_context
    await service.create_account(
        "user-2",
        accounts_router_module.AccountCreateRequest(
            account_id="acct_user_2",
            platform="douyin",
            auth_data={"cookie": "hidden"},
        ),
    )
    not_found = await client.get("/api/accounts/acct_user_2")
    assert not_found.status_code == 404
    assert (await client.get("/api/accounts")).json()["total"] == 0

    current_user["role"] = "admin"
    admin_list = await client.get("/api/accounts")
    assert admin_list.status_code == 200
    assert admin_list.json()["total"] == 1


@pytest.mark.asyncio
async def test_account_api_validation_errors_are_explicit(api_context):
    client, _, _ = api_context
    invalid_platform = await client.post(
        "/api/accounts",
        json={"platform": "not-supported", "role": "publisher"},
    )
    assert invalid_platform.status_code == 422

    invalid_capability = await client.post(
        "/api/accounts",
        json={"platform": "douyin", "capabilities": ["hack"]},
    )
    assert invalid_capability.status_code == 422

    missing = await client.post("/api/accounts/not-found/validate")
    assert missing.status_code == 404
