from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from database.models import (
    XTwitterExplainerVideoTask,
    XTwitterPost,
    XTwitterVideoBreakdown,
)
from database.user_models import (
    OpenNotebookConnectionModel,
    OpenNotebookOAuthFlowModel,
    UserModel,
)


@pytest.fixture(autouse=True)
def oauth_env(monkeypatch):
    monkeypatch.delenv("OPENNOTEBOOK_URL", raising=False)
    monkeypatch.delenv("MEDIACRAWLER_API_URL", raising=False)
    monkeypatch.delenv("MEDIACRAWLER_PUBLIC_URL", raising=False)
    monkeypatch.delenv("OPENNOTEBOOK_ALLOW_INSECURE_HTTP", raising=False)
    monkeypatch.setenv("AGENT_API_URL", "https://onb.test/api/v1/agent")
    monkeypatch.setenv("OPENNOTEBOOK_PUBLIC_URL", "https://onb-ui.test")
    monkeypatch.setenv("OPENNOTEBOOK_API_URL", "https://onb.test")
    monkeypatch.setenv("OPENNOTEBOOK_CLIENT_ID", "11111111-1111-4111-8111-111111111111")
    monkeypatch.setenv("OPENNOTEBOOK_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "OPENNOTEBOOK_REDIRECT_URI",
        "http://localhost:35092/api/integrations/opennotebook/callback",
    )
    monkeypatch.setenv(
        "OPENNOTEBOOK_FRONTEND_CALLBACK_URL",
        "http://localhost:35174/integrations/opennotebook/callback",
    )
    monkeypatch.setenv("OPENNOTEBOOK_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    import api.services.opennotebook_oauth as oauth

    oauth._discovery_cache.clear()


@pytest.mark.parametrize(
    "variable",
    [
        "AGENT_API_URL",
        "OPENNOTEBOOK_PUBLIC_URL",
        "OPENNOTEBOOK_API_URL",
        "OPENNOTEBOOK_REDIRECT_URI",
        "OPENNOTEBOOK_FRONTEND_CALLBACK_URL",
    ],
)
def test_oauth_config_rejects_remote_http_by_default(monkeypatch, variable):
    import api.services.opennotebook_oauth as oauth

    monkeypatch.setenv(variable, "http://remote.example.test/service")
    with pytest.raises(oauth.OpenNotebookOAuthError) as caught:
        oauth.oauth_config()
    assert caught.value.code == "OPENNOTEBOOK_INSECURE_URL"


def test_oauth_config_allows_loopback_http_and_explicit_dev_opt_in(monkeypatch):
    import api.services.opennotebook_oauth as oauth

    monkeypatch.setenv("AGENT_API_URL", "http://127.0.0.1:8000/api/v1/agent")
    monkeypatch.setenv("OPENNOTEBOOK_PUBLIC_URL", "http://localhost:3000")
    monkeypatch.setenv("OPENNOTEBOOK_API_URL", "http://[::1]:8000")
    cfg = oauth.oauth_config()
    assert cfg["api_url"] == "http://[::1]:8000"

    monkeypatch.setenv("OPENNOTEBOOK_PUBLIC_URL", "http://remote.example.test")
    monkeypatch.setenv("OPENNOTEBOOK_ALLOW_INSECURE_HTTP", "true")
    assert oauth.oauth_config()["public_url"] == "http://remote.example.test"


def test_minimal_discovery_config_derives_callbacks_and_client_mode(monkeypatch):
    import api.services.opennotebook_oauth as oauth

    for variable in (
        "AGENT_API_URL",
        "OPENNOTEBOOK_PUBLIC_URL",
        "OPENNOTEBOOK_API_URL",
        "OPENNOTEBOOK_REDIRECT_URI",
        "OPENNOTEBOOK_FRONTEND_CALLBACK_URL",
        "OPENNOTEBOOK_CLIENT_AUTH_METHOD",
        "OPENNOTEBOOK_OAUTH_PUBLIC_CLIENT",
        "OPENNOTEBOOK_OAUTH_SCOPE",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("OPENNOTEBOOK_URL", "https://api.onb.test")
    monkeypatch.setenv("AGENT_BASE_URL", "http://localhost:35092")

    cfg = oauth.oauth_config()

    assert cfg["discovery_url"] == "https://api.onb.test/.well-known/openid-configuration"
    assert cfg["redirect_uri"] == "http://localhost:35092/api/integrations/opennotebook/callback"
    assert cfg["frontend_callback_url"] == "http://localhost:35174/integrations/opennotebook/callback"
    assert cfg["client_auth_method"] == "client_secret_basic"
    assert cfg["scope"] == "*"


@pytest.mark.asyncio
async def test_discovery_resolves_and_caches_all_provider_endpoints(monkeypatch):
    import api.services.opennotebook_oauth as oauth

    for variable in (
        "AGENT_API_URL",
        "OPENNOTEBOOK_PUBLIC_URL",
        "OPENNOTEBOOK_API_URL",
        "OPENNOTEBOOK_REDIRECT_URI",
        "OPENNOTEBOOK_FRONTEND_CALLBACK_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("OPENNOTEBOOK_URL", "https://api.onb.test")
    oauth._discovery_cache.clear()
    calls = 0

    class FakeResponse:
        status_code = 200
        content = b"{}"
        text = ""

        @staticmethod
        def json():
            return {
                "issuer": "https://api.onb.test",
                "authorization_endpoint": "https://onb.test/oauth/authorize",
                "token_endpoint": "https://api.onb.test/api/v1/oauth/token",
                "revocation_endpoint": "https://api.onb.test/api/v1/oauth/revoke",
                "opennotebook_api_base": "https://api.onb.test",
                "agent_endpoint": "https://api.onb.test/api/v1/agent",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "scopes_supported": ["*"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "none"],
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout, follow_redirects):
            assert timeout == 10.0
            assert follow_redirects is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url, *, headers):
            nonlocal calls
            calls += 1
            assert url == "https://api.onb.test/.well-known/openid-configuration"
            assert headers == {"Accept": "application/json"}
            return FakeResponse()

    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeAsyncClient)

    first = await oauth.oauth_provider_config()
    second = await oauth.oauth_provider_config()

    assert calls == 1
    assert first["authorization_endpoint"] == "https://onb.test/oauth/authorize"
    assert first["token_endpoint"] == "https://api.onb.test/api/v1/oauth/token"
    assert first["revocation_endpoint"] == "https://api.onb.test/api/v1/oauth/revoke"
    assert first["agent_endpoint"] == "https://api.onb.test/api/v1/agent"
    assert second == first


@pytest.mark.asyncio
async def test_insecure_url_is_mapped_to_service_unavailable(app_client, monkeypatch):
    monkeypatch.setenv("OPENNOTEBOOK_PUBLIC_URL", "http://remote.example.test")
    response = await app_client.post(
        "/api/integrations/opennotebook/start",
        json={"return_to": "/x-workbench"},
    )
    assert response.status_code == 503


async def _clear(test_engine):
    import api.services.opennotebook_oauth as oauth
    from api.utils.rate_limit import _limiter

    oauth._refresh_locks.clear()
    _limiter._buckets.clear()
    async with test_engine.begin() as conn:
        for model in (
            XTwitterExplainerVideoTask,
            OpenNotebookOAuthFlowModel,
            OpenNotebookConnectionModel,
            XTwitterVideoBreakdown,
            XTwitterPost,
        ):
            await conn.execute(delete(model))
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        if await session.get(UserModel, 1) is None:
            session.add(
                UserModel(
                    id=1,
                    username="oauth-test-user-1",
                    password_hash="unused-test-hash",
                    nickname="OAuth Test User",
                    role="admin",
                    status="active",
                    created_ts=1,
                )
            )
            await session.commit()


async def _seed_video_context(test_engine, post_id: str) -> None:
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add(
            XTwitterPost(
                post_id=post_id,
                post_url=f"https://x.test/{post_id}",
                content=f"content {post_id}",
                username="author",
                video_url="",
                image_urls="[]",
                add_ts=1,
            )
        )
        session.add(
            XTwitterVideoBreakdown(
                post_id=post_id,
                post_url=f"https://x.test/{post_id}",
                script=f"script {post_id}",
                storyboards="[]",
                key_points="[]",
                suggested_comments="[]",
                add_ts=1,
            )
        )
        await session.commit()


def _test_credentials(owner_user_id: str = "1"):
    import api.services.opennotebook_oauth as oauth

    return oauth.OpenNotebookCredentials(
        connection_id=9,
        owner_user_id=owner_user_id,
        credential_version=3,
        access_token="access",
        token_type="Bearer",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        grant_id="grant-1",
    )


@pytest.mark.asyncio
async def test_mysql_additive_migrations_cover_oauth_and_video_idempotency():
    import database.db_session as dbs

    statements = []

    class FakeConnection:
        async def execute(self, statement):
            statements.append(str(statement))

    class FakeBegin:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    engine = FakeEngine()
    await dbs._ensure_opennotebook_oauth_columns(engine, "mysql")
    await dbs._ensure_explainer_video_idempotency(engine, "mysql")
    sql = "\n".join(statements)

    assert "browser_binding_hash" in sql
    assert "expected_credential_version" in sql
    assert "idempotency_key" in sql
    assert "submission_payload" in sql
    assert "grant_id" in sql
    assert "CREATE UNIQUE INDEX uq_explainer_video_owner_idempotency" in sql


@pytest.mark.asyncio
async def test_token_exchange_uses_form_pkce_and_client_secret_basic(monkeypatch):
    import httpx
    import api.services.opennotebook_oauth as oauth

    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "access_token": "access",
                "refresh_token": "refresh",
                "token_type": "Bearer",
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, data, headers, auth):
            captured.update(url=url, data=data, headers=headers, auth=auth)
            return FakeResponse()

    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeAsyncClient)
    result = await oauth.exchange_authorization_code("code-1", "verifier-1")

    assert result["access_token"] == "access"
    assert captured["url"] == "https://onb.test/api/v1/oauth/token"
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code_verifier"] == "verifier-1"
    assert "client_secret" not in captured["data"]
    assert isinstance(captured["auth"], httpx.BasicAuth)


def test_token_response_requires_access_and_refresh_tokens():
    import api.services.opennotebook_oauth as oauth

    for payload in (
        {"access_token": "access-only"},
        {"refresh_token": "refresh-only"},
    ):
        with pytest.raises(oauth.OpenNotebookOAuthError) as caught:
            oauth._unwrap_token_payload(payload)
        assert caught.value.code == "OPENNOTEBOOK_TOKEN_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_oauth_callback_stores_encrypted_user_connection_and_rejects_replay(
    app_client,
    user_context,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    started = await app_client.post(
        "/api/integrations/opennotebook/start",
        json={"return_to": "/x-workbench"},
    )
    assert started.status_code == 200
    assert "mc_opennotebook_oauth_binding=" in started.headers["set-cookie"]
    assert "HttpOnly" in started.headers["set-cookie"]
    assert "SameSite=lax" in started.headers["set-cookie"]
    authorization_url = started.json()["authorization_url"]
    authorization_query = parse_qs(urlparse(authorization_url).query)
    assert authorization_query["code_challenge_method"] == ["S256"]
    assert "code_challenge" in authorization_query
    state = authorization_query["state"][0]

    async def fake_exchange(code: str, verifier: str):
        assert code == "one-time-code"
        assert verifier
        return {
            "access_token": "short-access-token",
            "refresh_token": "rotating-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_expires_in": 86400,
            "scope": "*",
            "grant_id": "grant-1",
            "user_id": "onb-user-1",
            "tenant_id": "tenant-1",
        }

    async def fake_workspace(payload):
        return "workspace-1", "视频工作区"

    import api.routers.opennotebook_integration as integration_router

    monkeypatch.setattr(integration_router, "exchange_authorization_code", fake_exchange)
    monkeypatch.setattr(integration_router, "resolve_workspace", fake_workspace)

    callback = await app_client.get(
        "/api/integrations/opennotebook/callback",
        params={"code": "one-time-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert "result=success" in callback.headers["location"]
    assert "access_token" not in callback.headers["location"]
    assert "mc_opennotebook_oauth_binding=" in callback.headers["set-cookie"]

    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        connection = (
            await session.execute(
                select(OpenNotebookConnectionModel).where(
                    OpenNotebookConnectionModel.owner_user_id == "1"
                )
            )
        ).scalar_one()
        assert connection.tenant_id == "tenant-1"
        assert connection.workspace_id == "workspace-1"
        assert connection.grant_id == "grant-1"
        assert "short-access-token" not in connection.access_token_ciphertext
        assert "rotating-refresh-token" not in connection.refresh_token_ciphertext

    status = await app_client.get("/api/integrations/opennotebook/status")
    assert status.status_code == 200
    assert status.json()["connected"] is True
    assert "access_token" not in status.json()

    async with user_context(2) as other_client:
        other_status = await other_client.get("/api/integrations/opennotebook/status")
    assert other_status.json() == {
        "connected": False,
        "status": "disconnected",
        "needs_reauth": False,
    }

    replay = await app_client.get(
        "/api/integrations/opennotebook/callback",
        params={"code": "one-time-code", "state": state},
        follow_redirects=False,
    )
    assert replay.status_code == 302
    assert "invalid_or_expired_state" in replay.headers["location"]


@pytest.mark.asyncio
async def test_callback_without_initiating_browser_binding_is_rejected(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    started = await app_client.post(
        "/api/integrations/opennotebook/start",
        json={"return_to": "/x-workbench"},
    )
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    app_client.cookies.clear()

    import api.routers.opennotebook_integration as integration_router

    exchanged = False

    async def should_not_exchange(code: str, verifier: str):
        nonlocal exchanged
        exchanged = True
        return {"access_token": "must-not-be-saved"}

    monkeypatch.setattr(
        integration_router,
        "exchange_authorization_code",
        should_not_exchange,
    )
    callback = await app_client.get(
        "/api/integrations/opennotebook/callback",
        params={"code": "victim-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert "invalid_browser_binding" in callback.headers["location"]
    assert exchanged is False

    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        connection = (
            await session.execute(
                select(OpenNotebookConnectionModel).where(
                    OpenNotebookConnectionModel.owner_user_id == "1"
                )
            )
        ).scalar_one_or_none()
    assert connection is None


@pytest.mark.asyncio
async def test_callback_losing_disconnect_version_fence_revokes_new_tokens(
    app_client,
    test_engine,
    monkeypatch,
):
    """Simulate callback/disconnect in separate workers without a shared lock."""
    await _clear(test_engine)
    import api.routers.opennotebook_integration as integration_router
    import api.services.opennotebook_oauth as oauth

    await oauth.save_connection(
        "1",
        {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
            "grant_id": "old-grant",
        },
        workspace_id="workspace-1",
        workspace_name="Workspace",
    )

    class WorkerLocalLock:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(
        integration_router,
        "credential_lock",
        lambda owner_user_id: WorkerLocalLock(),
    )
    started = await app_client.post(
        "/api/integrations/opennotebook/start",
        json={"return_to": "/x-workbench"},
    )
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]

    exchange_started = asyncio.Event()
    release_exchange = asyncio.Event()

    async def delayed_exchange(code: str, verifier: str):
        exchange_started.set()
        await release_exchange.wait()
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
            "grant_id": "new-grant",
        }

    async def fake_workspace(payload):
        return "workspace-1", "Workspace"

    revoked = []

    async def fake_revoke(token: str, *, token_type_hint: str):
        revoked.append((token, token_type_hint))

    monkeypatch.setattr(
        integration_router,
        "exchange_authorization_code",
        delayed_exchange,
    )
    monkeypatch.setattr(integration_router, "resolve_workspace", fake_workspace)
    monkeypatch.setattr(oauth, "revoke_remote_token", fake_revoke)

    callback_task = asyncio.create_task(
        app_client.get(
            "/api/integrations/opennotebook/callback",
            params={"code": "new-code", "state": state},
            follow_redirects=False,
        )
    )
    await exchange_started.wait()
    assert await oauth.disconnect("1") is True
    release_exchange.set()
    callback = await callback_task

    assert callback.status_code == 302
    assert "token_exchange_failed" in callback.headers["location"]
    assert revoked == [
        ("old-refresh", "refresh_token"),
        ("old-access", "access_token"),
        ("new-refresh", "refresh_token"),
        ("new-access", "access_token"),
    ]
    assert (await oauth.connection_status("1"))["connected"] is False


@pytest.mark.asyncio
async def test_refresh_rotation_and_disconnect_are_user_scoped(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    import api.services.opennotebook_oauth as oauth

    connection = await oauth.save_connection(
        "1",
        {
            "access_token": "expired-access",
            "refresh_token": "refresh-v1",
            "token_type": "Bearer",
            "expires_in": 1,
            "refresh_expires_in": 3600,
            "scope": "*",
            "tenant_id": "tenant-1",
            "grant_id": "grant-1",
            "user_id": "user-1",
        },
        workspace_id="workspace-1",
        workspace_name="Workspace",
    )
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(OpenNotebookConnectionModel, connection.id)
        row.access_token_expires_ts = 1
        await session.commit()

    refresh_calls = []

    async def fake_refresh(refresh_token: str):
        refresh_calls.append(refresh_token)
        return {
            "access_token": "access-v2",
            "refresh_token": "refresh-v2",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
        }

    revoked = []

    async def fake_revoke(token: str, *, token_type_hint: str):
        revoked.append((token, token_type_hint))

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(oauth, "revoke_remote_token", fake_revoke)

    credentials = await oauth.get_valid_credentials("1")
    assert credentials.access_token == "access-v2"
    assert refresh_calls == ["refresh-v1"]

    disconnected = await app_client.post("/api/integrations/opennotebook/disconnect")
    assert disconnected.status_code == 200
    assert disconnected.json()["connected"] is False
    assert revoked == [
        ("refresh-v2", "refresh_token"),
        ("access-v2", "access_token"),
    ]
    status = await app_client.get("/api/integrations/opennotebook/status")
    assert status.json()["connected"] is False


@pytest.mark.asyncio
async def test_disconnect_non_2xx_maps_to_502_and_preserves_credentials(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    import api.services.opennotebook_oauth as oauth
    revoke_hints = []

    connection = await oauth.save_connection(
        "1",
        {
            "access_token": "keep-access",
            "refresh_token": "keep-refresh",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
            "tenant_id": "tenant-1",
        },
        workspace_id="workspace-1",
        workspace_name="Workspace",
    )

    class FakeResponse:
        status_code = 503
        text = "unavailable"

        @staticmethod
        def json():
            return {"detail": "unavailable"}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, data, headers, auth):
            revoke_hints.append(data["token_type_hint"])
            return FakeResponse()

    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeAsyncClient)
    response = await app_client.post("/api/integrations/opennotebook/disconnect")
    assert response.status_code == 502
    assert revoke_hints == ["refresh_token", "access_token"]

    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(OpenNotebookConnectionModel, connection.id)
        assert row.status == "active"
        assert oauth.decrypt_secret(row.access_token_ciphertext) == "keep-access"
        assert oauth.decrypt_secret(row.refresh_token_ciphertext) == "keep-refresh"


@pytest.mark.asyncio
async def test_disconnect_waits_for_rotation_and_revokes_latest_refresh(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    import api.services.opennotebook_oauth as oauth

    connection = await oauth.save_connection(
        "1",
        {
            "access_token": "expired-access",
            "refresh_token": "refresh-before-rotation",
            "expires_in": 1,
            "refresh_expires_in": 3600,
        },
        workspace_id="workspace-1",
        workspace_name="Workspace",
    )
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(OpenNotebookConnectionModel, connection.id)
        row.access_token_expires_ts = 1
        await session.commit()

    refresh_started = asyncio.Event()
    release_refresh = asyncio.Event()
    revoked = []

    async def fake_refresh(refresh_token: str):
        assert refresh_token == "refresh-before-rotation"
        refresh_started.set()
        await release_refresh.wait()
        return {
            "access_token": "access-after-rotation",
            "refresh_token": "refresh-after-rotation",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
        }

    async def fake_revoke(token: str, *, token_type_hint: str):
        revoked.append((token, token_type_hint))

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(oauth, "revoke_remote_token", fake_revoke)

    refresh_task = asyncio.create_task(oauth.get_valid_credentials("1"))
    await refresh_started.wait()
    disconnect_task = asyncio.create_task(oauth.disconnect("1"))
    await asyncio.sleep(0)
    assert disconnect_task.done() is False
    release_refresh.set()

    credentials = await refresh_task
    assert credentials.access_token == "access-after-rotation"
    assert await disconnect_task is True
    assert revoked == [
        ("refresh-after-rotation", "refresh_token"),
        ("access-after-rotation", "access_token"),
    ]
    status = await oauth.connection_status("1")
    assert status["connected"] is False


@pytest.mark.asyncio
async def test_refresh_waiting_on_disconnect_cannot_restore_active_connection(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    import api.services.opennotebook_oauth as oauth

    connection = await oauth.save_connection(
        "1",
        {
            "access_token": "expired-access",
            "refresh_token": "refresh-to-revoke",
            "expires_in": 1,
            "refresh_expires_in": 3600,
        },
        workspace_id="workspace-1",
        workspace_name="Workspace",
    )
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(OpenNotebookConnectionModel, connection.id)
        row.access_token_expires_ts = 1
        await session.commit()

    revoke_started = asyncio.Event()
    release_revoke = asyncio.Event()
    refresh_calls = 0

    async def blocking_revoke(token: str, *, token_type_hint: str):
        revoke_started.set()
        await release_revoke.wait()

    async def should_not_refresh(refresh_token: str):
        nonlocal refresh_calls
        refresh_calls += 1
        return {"access_token": "must-not-write"}

    monkeypatch.setattr(oauth, "revoke_remote_token", blocking_revoke)
    monkeypatch.setattr(oauth, "refresh_access_token", should_not_refresh)

    disconnect_task = asyncio.create_task(oauth.disconnect("1"))
    await revoke_started.wait()
    refresh_task = asyncio.create_task(oauth.get_valid_credentials("1"))
    await asyncio.sleep(0)
    release_revoke.set()
    assert await disconnect_task is True
    with pytest.raises(oauth.OpenNotebookOAuthError):
        await refresh_task
    assert refresh_calls == 0

    async with factory() as session:
        row = await session.get(OpenNotebookConnectionModel, connection.id)
        assert row.status == "revoked"
        assert row.access_token_ciphertext == ""


async def _seed_deletable_user_artifacts(test_engine, user_id: int):
    import api.services.opennotebook_oauth as oauth

    owner_user_id = str(user_id)
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await session.execute(delete(UserModel).where(UserModel.id == user_id))
        session.add(
            UserModel(
                id=user_id,
                username=f"delete-user-{user_id}",
                password_hash="unused-test-hash",
                nickname="Delete Me",
                role="operator",
                status="active",
                created_ts=1,
            )
        )
        await session.commit()

    await oauth.save_connection(
        owner_user_id,
        {
            "access_token": f"access-{user_id}",
            "refresh_token": f"refresh-{user_id}",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
            "grant_id": f"grant-{user_id}",
        },
        workspace_id="workspace-1",
        workspace_name="Workspace",
    )
    async with factory() as session:
        session.add(
            OpenNotebookOAuthFlowModel(
                state_hash=f"{user_id:064x}",
                owner_user_id=owner_user_id,
                browser_binding_hash=f"{user_id + 1:064x}",
                expected_credential_version=1,
                code_verifier_ciphertext="encrypted-verifier",
                return_to="/x-workbench",
                expires_ts=9999999999,
                consumed_ts=0,
                created_ts=1,
            )
        )
        session.add(
            XTwitterExplainerVideoTask(
                local_task_id=f"delete-task-{user_id}",
                owner_user_id=owner_user_id,
                post_id="post-delete",
                status="running",
                created_ts=1,
                updated_ts=1,
            )
        )
        await session.commit()
    return factory


@pytest.mark.asyncio
async def test_delete_user_revokes_and_removes_oauth_flow_connection_and_video_tasks(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    user_id = 42001
    factory = await _seed_deletable_user_artifacts(test_engine, user_id)
    import api.services.auth as auth
    import api.services.opennotebook_oauth as oauth

    revoked = []

    async def fake_revoke(token: str, *, token_type_hint: str):
        revoked.append((token, token_type_hint))

    monkeypatch.setattr(auth, "_get_session_factory", lambda: factory)
    monkeypatch.setattr(oauth, "revoke_remote_token", fake_revoke)
    assert await auth.delete_user(user_id) is True
    assert revoked == [
        (f"refresh-{user_id}", "refresh_token"),
        (f"access-{user_id}", "access_token"),
    ]

    owner_user_id = str(user_id)
    async with factory() as session:
        assert await session.get(UserModel, user_id) is None
        for model in (
            OpenNotebookConnectionModel,
            OpenNotebookOAuthFlowModel,
            XTwitterExplainerVideoTask,
        ):
            remaining = (
                await session.execute(
                    select(model).where(model.owner_user_id == owner_user_id)
                )
            ).scalars().all()
            assert remaining == []


@pytest.mark.asyncio
async def test_delete_user_revoke_failure_preserves_user_and_all_artifacts(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    user_id = 42002
    factory = await _seed_deletable_user_artifacts(test_engine, user_id)
    import api.services.auth as auth
    import api.services.opennotebook_oauth as oauth

    async def failed_revoke(token: str, *, token_type_hint: str):
        raise oauth.OpenNotebookOAuthError(
            "upstream unavailable",
            code="OPENNOTEBOOK_REVOKE_FAILED",
        )

    monkeypatch.setattr(auth, "_get_session_factory", lambda: factory)
    monkeypatch.setattr(oauth, "revoke_remote_token", failed_revoke)
    response = await app_client.delete(f"/api/auth/users/{user_id}")
    assert response.status_code == 502
    assert "upstream unavailable" in response.json()["message"]

    owner_user_id = str(user_id)
    async with factory() as session:
        assert await session.get(UserModel, user_id) is not None
        connection = (
            await session.execute(
                select(OpenNotebookConnectionModel).where(
                    OpenNotebookConnectionModel.owner_user_id == owner_user_id
                )
            )
        ).scalar_one()
        assert connection.status == "active"
        assert connection.access_token_ciphertext
        for model in (OpenNotebookOAuthFlowModel, XTwitterExplainerVideoTask):
            remaining = (
                await session.execute(
                    select(model).where(model.owner_user_id == owner_user_id)
                )
            ).scalars().all()
            assert len(remaining) == 1


@pytest.mark.asyncio
async def test_authenticated_start_waiting_behind_delete_cannot_recreate_flow(
    app_client,
    user_context,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    user_id = 42003
    factory = await _seed_deletable_user_artifacts(test_engine, user_id)
    import api.services.auth as auth
    import api.services.opennotebook_oauth as oauth

    async def fake_revoke(token: str, *, token_type_hint: str):
        return None

    monkeypatch.setattr(auth, "_get_session_factory", lambda: factory)
    monkeypatch.setattr(oauth, "revoke_remote_token", fake_revoke)
    owner_user_id = str(user_id)
    owner_lock = oauth.credential_lock(owner_user_id)
    await owner_lock.acquire()
    try:
        # Queue deletion first. The start request has already passed its mocked
        # authentication dependency when it later waits on the same owner lock.
        delete_task = asyncio.create_task(auth.delete_user(user_id))
        await asyncio.sleep(0)
        async with user_context(user_id) as client:
            start_task = asyncio.create_task(
                client.post(
                    "/api/integrations/opennotebook/start",
                    json={"return_to": "/x-workbench"},
                )
            )
            await asyncio.sleep(0.01)
            owner_lock.release()
            assert await delete_task is True
            started = await start_task
    finally:
        if owner_lock.locked():
            owner_lock.release()

    assert started.status_code == 409
    async with factory() as session:
        assert await session.get(UserModel, user_id) is None
        flows = (
            await session.execute(
                select(OpenNotebookOAuthFlowModel).where(
                    OpenNotebookOAuthFlowModel.owner_user_id == owner_user_id
                )
            )
        ).scalars().all()
    assert flows == []


@pytest.mark.asyncio
async def test_callback_candidate_waiting_behind_delete_cannot_save_new_grant(
    app_client,
    user_context,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    user_id = 42004
    factory = await _seed_deletable_user_artifacts(test_engine, user_id)
    import api.routers.opennotebook_integration as integration_router
    import api.services.auth as auth
    import api.services.opennotebook_oauth as oauth

    async def fake_revoke(token: str, *, token_type_hint: str):
        return None

    exchange_calls = 0

    async def should_not_exchange(code: str, verifier: str):
        nonlocal exchange_calls
        exchange_calls += 1
        raise AssertionError("deleted owner must be fenced before code exchange")

    monkeypatch.setattr(auth, "_get_session_factory", lambda: factory)
    monkeypatch.setattr(oauth, "revoke_remote_token", fake_revoke)
    monkeypatch.setattr(
        integration_router,
        "exchange_authorization_code",
        should_not_exchange,
    )
    async with user_context(user_id) as client:
        started = await client.post(
            "/api/integrations/opennotebook/start",
            json={"return_to": "/x-workbench"},
        )
        assert started.status_code == 200
        state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]

        owner_user_id = str(user_id)
        owner_lock = oauth.credential_lock(owner_user_id)
        await owner_lock.acquire()
        try:
            delete_task = asyncio.create_task(auth.delete_user(user_id))
            await asyncio.sleep(0)
            callback_task = asyncio.create_task(
                client.get(
                    "/api/integrations/opennotebook/callback",
                    params={"code": "late-code", "state": state},
                    follow_redirects=False,
                )
            )
            # The callback may read a valid candidate, but deletion is first in
            # the lifecycle-lock queue and removes it before the locked re-read.
            await asyncio.sleep(0.01)
            owner_lock.release()
            assert await delete_task is True
            callback = await callback_task
        finally:
            if owner_lock.locked():
                owner_lock.release()

    assert callback.status_code == 302
    assert "invalid_or_expired_state" in callback.headers["location"]
    assert exchange_calls == 0
    async with factory() as session:
        assert await session.get(UserModel, user_id) is None
        connection = (
            await session.execute(
                select(OpenNotebookConnectionModel).where(
                    OpenNotebookConnectionModel.owner_user_id == owner_user_id
                )
            )
        ).scalar_one_or_none()
    assert connection is None


@pytest.mark.asyncio
async def test_concurrent_refresh_rotates_refresh_token_once(
    app_client, test_engine, monkeypatch
):
    await _clear(test_engine)
    import api.services.opennotebook_oauth as oauth

    connection = await oauth.save_connection(
        "1",
        {
            "access_token": "expired-access",
            "refresh_token": "refresh-once",
            "expires_in": 1,
            "refresh_expires_in": 3600,
            "tenant_id": "tenant-1",
        },
        workspace_id="workspace-1",
        workspace_name="Workspace",
    )
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(OpenNotebookConnectionModel, connection.id)
        row.access_token_expires_ts = 1
        await session.commit()

    calls = 0

    async def fake_refresh(refresh_token: str):
        nonlocal calls
        calls += 1
        assert refresh_token == "refresh-once"
        await asyncio.sleep(0.05)
        return {
            "access_token": "fresh-access",
            "refresh_token": "fresh-refresh",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
        }

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh)
    first, second = await asyncio.gather(
        oauth.get_valid_credentials("1"),
        oauth.get_valid_credentials("1"),
    )
    assert calls == 1
    assert first.access_token == second.access_token == "fresh-access"


@pytest.mark.asyncio
async def test_late_401_cannot_mark_new_grant_reauth_required(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    import api.services.opennotebook_oauth as oauth

    async def fake_revoke_pair(**kwargs):
        return None

    monkeypatch.setattr(oauth, "revoke_token_pair", fake_revoke_pair)
    await oauth.save_connection(
        "1",
        {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
            "tenant_id": "tenant-1",
            "grant_id": "grant-old",
        },
        workspace_id="workspace-1",
        workspace_name="Workspace",
    )
    stale_credentials = await oauth.get_valid_credentials("1")

    await oauth.save_connection(
        "1",
        {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
            "tenant_id": "tenant-1",
            "grant_id": "grant-new",
        },
        workspace_id="workspace-1",
        workspace_name="Workspace",
    )

    assert await oauth.mark_reauth_required(stale_credentials, "late 401") is False
    connection = await oauth.get_connection("1")
    assert connection is not None
    assert connection.status == "active"
    assert connection.grant_id == "grant-new"
    assert connection.credential_version > stale_credentials.credential_version


@pytest.mark.asyncio
async def test_concurrent_video_intent_creates_one_task_and_one_provider_submit(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    await _seed_video_context(test_engine, "post-concurrent")
    import api.services.explainer_video_client as video_client
    import api.services.opennotebook_oauth as oauth

    credentials = _test_credentials()
    submit_calls = []

    async def fake_credentials(owner_user_id: str, *, force_refresh: bool = False):
        assert owner_user_id == "1"
        assert force_refresh is False
        return credentials

    async def fake_submit(**kwargs):
        submit_calls.append(kwargs)
        await asyncio.sleep(0.05)
        return {
            "task_id": "provider-concurrent",
            "status": "running",
            "model": "kwvideo-v2",
            "model_name": "Seedance 2.0 首尾帧",
            "reference_count": 0,
        }

    monkeypatch.setattr(oauth, "get_valid_credentials", fake_credentials)
    monkeypatch.setattr(video_client, "submit_explainer_video", fake_submit)
    body = {
        "post_id": "post-concurrent",
        "idempotency_key": "eaf2dfd8-f6c3-40f4-a172-4b42ca35b953",
    }

    first, second = await asyncio.gather(
        app_client.post("/api/x-workbench/explainer-video", json=body),
        app_client.post("/api/x-workbench/explainer-video", json=body),
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]
    assert len(submit_calls) == 1
    assert submit_calls[0]["idempotency_key"].startswith("mc:")
    assert body["idempotency_key"] not in submit_calls[0]["idempotency_key"]

    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.execute(select(XTwitterExplainerVideoTask))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].provider_task_id == "provider-concurrent"


@pytest.mark.asyncio
async def test_response_loss_retry_reuses_local_task_snapshot_and_upstream_key(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    await _seed_video_context(test_engine, "post-loss")
    import api.services.explainer_video_client as video_client
    import api.services.opennotebook_oauth as oauth

    credentials = _test_credentials()
    submit_calls = []

    async def fake_credentials(owner_user_id: str, *, force_refresh: bool = False):
        return credentials

    async def fake_submit(**kwargs):
        submit_calls.append(kwargs)
        if len(submit_calls) == 1:
            raise video_client.AgentVideoError("provider response lost", 502)
        return {
            "task_id": "provider-recovered",
            "status": "running",
            "model": "kwvideo-v2",
            "model_name": "Seedance 2.0 首尾帧",
            "reference_count": 0,
        }

    monkeypatch.setattr(oauth, "get_valid_credentials", fake_credentials)
    monkeypatch.setattr(video_client, "submit_explainer_video", fake_submit)
    body = {
        "post_id": "post-loss",
        "idempotency_key": "79038e56-077a-405a-aa52-484081f3af84",
    }

    lost = await app_client.post("/api/x-workbench/explainer-video", json=body)
    assert lost.status_code == 502
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        first_task = (
            await session.execute(select(XTwitterExplainerVideoTask))
        ).scalar_one()
        first_local_task_id = first_task.local_task_id
        original_snapshot = first_task.submission_payload

    recovered = await app_client.post(
        "/api/x-workbench/explainer-video",
        json=body,
    )
    assert recovered.status_code == 200
    assert recovered.json()["task_id"] == first_local_task_id
    assert len(submit_calls) == 2
    assert submit_calls[0]["idempotency_key"] == submit_calls[1]["idempotency_key"]
    assert submit_calls[0]["prompt"] == submit_calls[1]["prompt"]

    async with factory() as session:
        rows = (
            await session.execute(select(XTwitterExplainerVideoTask))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].submission_payload == original_snapshot
    assert rows[0].provider_task_id == "provider-recovered"


@pytest.mark.asyncio
async def test_response_loss_retry_cannot_cross_opennotebook_grants(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    await _seed_video_context(test_engine, "post-grant-change")
    import api.services.explainer_video_client as video_client
    import api.services.opennotebook_oauth as oauth

    current_credentials = _test_credentials()
    submit_calls = 0

    async def fake_credentials(owner_user_id: str, *, force_refresh: bool = False):
        return current_credentials

    async def lost_submit(**kwargs):
        nonlocal submit_calls
        submit_calls += 1
        raise video_client.AgentVideoError("provider response lost", 502)

    monkeypatch.setattr(oauth, "get_valid_credentials", fake_credentials)
    monkeypatch.setattr(video_client, "submit_explainer_video", lost_submit)
    body = {
        "post_id": "post-grant-change",
        "idempotency_key": "34c1c0eb-ef69-4568-aedf-80042c3b06fc",
    }
    first = await app_client.post("/api/x-workbench/explainer-video", json=body)
    assert first.status_code == 502

    current_credentials = oauth.OpenNotebookCredentials(
        connection_id=10,
        owner_user_id="1",
        credential_version=1,
        access_token="other-access",
        token_type="Bearer",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        grant_id="grant-other-account",
    )
    retry = await app_client.post("/api/x-workbench/explainer-video", json=body)

    assert retry.status_code == 409
    assert retry.json()["data"]["reason"] == "OPENNOTEBOOK_CONNECTION_CHANGED"
    assert submit_calls == 1


@pytest.mark.asyncio
async def test_video_intent_reuse_with_different_post_is_conflict(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    await _seed_video_context(test_engine, "post-original")
    await _seed_video_context(test_engine, "post-conflict")
    import api.services.explainer_video_client as video_client
    import api.services.opennotebook_oauth as oauth

    async def fake_credentials(owner_user_id: str, *, force_refresh: bool = False):
        return _test_credentials()

    calls = 0

    async def fake_submit(**kwargs):
        nonlocal calls
        calls += 1
        return {
            "task_id": "provider-original",
            "status": "running",
            "model": "kwvideo-v2",
            "model_name": "Seedance 2.0 首尾帧",
            "reference_count": 0,
        }

    monkeypatch.setattr(oauth, "get_valid_credentials", fake_credentials)
    monkeypatch.setattr(video_client, "submit_explainer_video", fake_submit)
    key = "e4cc9cd2-e14d-4169-be26-13981821129e"
    original = await app_client.post(
        "/api/x-workbench/explainer-video",
        json={"post_id": "post-original", "idempotency_key": key},
    )
    conflict = await app_client.post(
        "/api/x-workbench/explainer-video",
        json={"post_id": "post-conflict", "idempotency_key": key},
    )

    assert original.status_code == 200
    assert conflict.status_code == 409
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"post_id": "post-invalid"},
        {"post_id": "post-invalid", "idempotency_key": "not-a-uuid"},
        {
            "post_id": "post-invalid",
            "idempotency_key": "00000000-0000-1000-8000-000000000000",
        },
    ],
)
async def test_video_intent_requires_uuid4(app_client, body):
    response = await app_client.post(
        "/api/x-workbench/explainer-video",
        json=body,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unconnected_generation_maps_to_409_and_task_status_is_owner_scoped(
    app_client,
    user_context,
    test_engine,
):
    await _clear(test_engine)
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add(
            XTwitterPost(
                post_id="post-1",
                post_url="https://x.test/post-1",
                content="content",
                username="author",
                video_url="",
                image_urls="[]",
                add_ts=1,
            )
        )
        session.add(
            XTwitterVideoBreakdown(
                post_id="post-1",
                post_url="https://x.test/post-1",
                script="script",
                storyboards="[]",
                key_points="[]",
                suggested_comments="[]",
                add_ts=1,
            )
        )
        session.add(
            XTwitterExplainerVideoTask(
                local_task_id="private-task",
                provider_task_id="",
                owner_user_id="1",
                post_id="post-1",
                status="error",
                error="submit failed",
                created_ts=1,
                updated_ts=1,
            )
        )
        await session.commit()

    generation = await app_client.post(
        "/api/x-workbench/explainer-video",
        json={
            "post_id": "post-1",
            "idempotency_key": "53b19ea9-d354-4e11-b862-03ca33a059bd",
        },
    )
    assert generation.status_code == 409
    assert generation.json()["data"]["reason"] == "OPENNOTEBOOK_NOT_CONNECTED"

    owner_status = await app_client.get(
        "/api/x-workbench/explainer-video/private-task"
    )
    assert owner_status.status_code == 200
    assert owner_status.json()["error"] == "submit failed"

    async with user_context(2) as other_client:
        other_status = await other_client.get(
            "/api/x-workbench/explainer-video/private-task"
        )
    assert other_status.status_code == 404


@pytest.mark.asyncio
async def test_upstream_401_is_mapped_to_reauth_conflict_not_local_401(
    app_client,
    test_engine,
    monkeypatch,
):
    await _clear(test_engine)
    factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add(
            XTwitterPost(
                post_id="post-auth",
                post_url="https://x.test/post-auth",
                content="content",
                username="author",
                video_url="",
                image_urls="[]",
                add_ts=1,
            )
        )
        session.add(
            XTwitterVideoBreakdown(
                post_id="post-auth",
                post_url="https://x.test/post-auth",
                script="script",
                storyboards="[]",
                key_points="[]",
                suggested_comments="[]",
                add_ts=1,
            )
        )
        await session.commit()

    import api.services.explainer_video_client as video_client
    import api.services.opennotebook_oauth as oauth

    credentials = oauth.OpenNotebookCredentials(
        connection_id=9,
        owner_user_id="1",
        credential_version=3,
        access_token="access",
        token_type="Bearer",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        grant_id="grant-1",
    )
    credential_calls = []
    submission_keys = []

    async def fake_credentials(owner_user_id: str, *, force_refresh: bool = False):
        credential_calls.append((owner_user_id, force_refresh))
        return credentials

    async def unauthorized_submit(**kwargs):
        submission_keys.append(kwargs["idempotency_key"])
        raise video_client.AgentVideoError("expired", 401)

    async def fake_mark(failed_credentials, message: str):
        assert failed_credentials == credentials

    monkeypatch.setattr(oauth, "get_valid_credentials", fake_credentials)
    monkeypatch.setattr(oauth, "mark_reauth_required", fake_mark)
    monkeypatch.setattr(video_client, "submit_explainer_video", unauthorized_submit)

    response = await app_client.post(
        "/api/x-workbench/explainer-video",
        json={
            "post_id": "post-auth",
            "idempotency_key": "cf3a7c82-b714-40ee-9d89-0abc79a38ba2",
        },
    )
    assert response.status_code == 409
    assert response.status_code != 401
    assert response.json()["data"]["reason"] == "OPENNOTEBOOK_REAUTH_REQUIRED"
    assert credential_calls == [("1", False), ("1", True)]
    assert len(submission_keys) == 2
    assert submission_keys[0] == submission_keys[1]
