# -*- coding: utf-8 -*-
"""OpenNotebook OAuth2/PKCE 连接与按用户凭证管理。"""
from __future__ import annotations

import base64
import asyncio
import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_session import get_session
from database.user_models import (
    OpenNotebookConnectionModel,
    OpenNotebookOAuthFlowModel,
    UserModel,
)


OAUTH_FLOW_TTL_SECONDS = 10 * 60
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 60
DISCOVERY_CACHE_SECONDS = 5 * 60
DISCOVERY_MAX_BYTES = 128 * 1024
_refresh_locks: dict[str, asyncio.Lock] = {}
_discovery_cache: dict[str, tuple[float, dict[str, str]]] = {}
_TRUE_VALUES = {"1", "true", "yes", "on"}


class OpenNotebookOAuthError(RuntimeError):
    """OpenNotebook OAuth 或用户连接错误。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "OPENNOTEBOOK_OAUTH_ERROR",
        reauth_required: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.reauth_required = reauth_required


@dataclass(frozen=True)
class OpenNotebookCredentials:
    connection_id: int
    owner_user_id: str
    credential_version: int
    access_token: str
    token_type: str
    tenant_id: str
    workspace_id: str
    workspace_name: str
    grant_id: str


def _now() -> int:
    return int(time.time())


def _allow_insecure_http() -> bool:
    """Remote plain HTTP is an explicit development-only escape hatch."""
    return os.getenv("OPENNOTEBOOK_ALLOW_INSECURE_HTTP", "false").strip().lower() in _TRUE_VALUES


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _default_frontend_base(api_base_url: str) -> str:
    """Local Vite uses :35174; deployed same-origin installations need no override."""
    parsed = urlsplit(api_base_url)
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.port == 35092:
        hostname = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
        return urlunsplit((parsed.scheme, f"{hostname}:35174", "", "", ""))
    return api_base_url


def validate_service_url(name: str, value: str, *, base_url: bool = False) -> str:
    """Validate an absolute service/callback URL and enforce TLS off loopback.

    HTTP is safe by default only for the exact loopback hosts used by local
    development.  A remote HTTP deployment must opt in explicitly so a copied
    production ``.env`` cannot silently send OAuth codes or bearer tokens in
    cleartext.
    """
    value = value.strip()
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        # Accessing ``port`` also validates malformed/non-numeric ports.
        parsed.port
    except ValueError as exc:
        raise OpenNotebookOAuthError(
            f"{name} 不是有效的绝对 URL",
            code="OPENNOTEBOOK_INSECURE_URL",
        ) from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in value)
    ):
        raise OpenNotebookOAuthError(
            f"{name} 必须是无用户凭证的绝对 HTTP(S) URL",
            code="OPENNOTEBOOK_INSECURE_URL",
        )
    if base_url and (parsed.query or parsed.fragment):
        raise OpenNotebookOAuthError(
            f"{name} 基础 URL 不能包含 query 或 fragment",
            code="OPENNOTEBOOK_INSECURE_URL",
        )
    if parsed.fragment:
        raise OpenNotebookOAuthError(
            f"{name} 不能包含 fragment",
            code="OPENNOTEBOOK_INSECURE_URL",
        )

    is_loopback = hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "http" and not is_loopback and not _allow_insecure_http():
        raise OpenNotebookOAuthError(
            f"{name} 的非本机地址必须使用 HTTPS；仅开发环境可显式设置 "
            "OPENNOTEBOOK_ALLOW_INSECURE_HTTP=true",
            code="OPENNOTEBOOK_INSECURE_URL",
        )
    return value.rstrip("/") if base_url else value


def oauth_config() -> dict[str, str]:
    """读取本地 Client 配置；新部署仅需一个 Discovery issuer URL。"""
    issuer_url = os.getenv("OPENNOTEBOOK_URL", "").strip().rstrip("/")
    api_url = os.getenv("OPENNOTEBOOK_API_URL", "").strip().rstrip("/")
    public_url = os.getenv("OPENNOTEBOOK_PUBLIC_URL", api_url).strip().rstrip("/")
    client_id = os.getenv("OPENNOTEBOOK_CLIENT_ID", "").strip()
    client_secret = os.getenv("OPENNOTEBOOK_CLIENT_SECRET", "").strip()
    public_client_value = os.getenv("OPENNOTEBOOK_OAUTH_PUBLIC_CLIENT", "").strip().lower()
    public_client = (
        public_client_value in _TRUE_VALUES
        if public_client_value
        else not bool(client_secret)
    )

    media_api_url = os.getenv(
        "MEDIACRAWLER_API_URL",
        os.getenv("AGENT_BASE_URL", "http://localhost:35092"),
    ).strip().rstrip("/")
    media_public_url = os.getenv("MEDIACRAWLER_PUBLIC_URL", "").strip().rstrip("/")
    redirect_uri = os.getenv(
        "OPENNOTEBOOK_REDIRECT_URI",
        _join_url(media_api_url, "/api/integrations/opennotebook/callback"),
    ).strip()
    frontend_callback_url = os.getenv(
        "OPENNOTEBOOK_FRONTEND_CALLBACK_URL",
        _join_url(
            media_public_url or _default_frontend_base(media_api_url),
            "/integrations/opennotebook/callback",
        ),
    ).strip()
    scope = os.getenv("OPENNOTEBOOK_OAUTH_SCOPE", "*").strip() or "*"

    if not issuer_url and (not api_url or not public_url):
        raise OpenNotebookOAuthError(
            "OPENNOTEBOOK_URL 未配置",
            code="OPENNOTEBOOK_NOT_CONFIGURED",
        )
    if not client_id:
        raise OpenNotebookOAuthError(
            "OPENNOTEBOOK_CLIENT_ID 未配置",
            code="OPENNOTEBOOK_NOT_CONFIGURED",
        )
    if issuer_url:
        issuer_url = validate_service_url("OPENNOTEBOOK_URL", issuer_url, base_url=True)
    else:
        api_url = validate_service_url("OPENNOTEBOOK_API_URL", api_url, base_url=True)
        public_url = validate_service_url("OPENNOTEBOOK_PUBLIC_URL", public_url, base_url=True)
    redirect_uri = validate_service_url("OPENNOTEBOOK_REDIRECT_URI", redirect_uri)
    frontend_callback_url = validate_service_url(
        "OPENNOTEBOOK_FRONTEND_CALLBACK_URL", frontend_callback_url,
    )
    try:
        UUID(client_id)
    except ValueError as exc:
        raise OpenNotebookOAuthError(
            "OPENNOTEBOOK_CLIENT_ID 必须是 OpenNotebook 注册的 UUID",
            code="OPENNOTEBOOK_NOT_CONFIGURED",
        ) from exc
    if not public_client and not client_secret:
        raise OpenNotebookOAuthError(
            "Confidential OAuth Client 必须配置 OPENNOTEBOOK_CLIENT_SECRET",
            code="OPENNOTEBOOK_NOT_CONFIGURED",
        )
    return {
        "issuer": issuer_url,
        "discovery_url": (
            _join_url(issuer_url, "/.well-known/openid-configuration")
            if issuer_url
            else ""
        ),
        "api_url": api_url,
        "public_url": public_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "public_client": "true" if public_client else "false",
        "client_auth_method": "none" if public_client else "client_secret_basic",
        "redirect_uri": redirect_uri,
        "frontend_callback_url": frontend_callback_url,
        "scope": scope,
    }


def _api_endpoint(api_url: str, path: str) -> str:
    """OPENNOTEBOOK_API_URL 支持根 URL 或已带 /api/v1 的 URL。"""
    base = api_url.rstrip("/")
    normalized = "/" + path.lstrip("/")
    if base.endswith("/api/v1") and normalized.startswith("/api/v1/"):
        normalized = normalized[len("/api/v1") :]
    return base + normalized


def _metadata_string(
    payload: dict[str, Any],
    name: str,
    *,
    base_url: bool = False,
) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise OpenNotebookOAuthError(
            f"OpenNotebook Discovery 缺少 {name}",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )
    try:
        return validate_service_url(name, value.strip(), base_url=base_url)
    except OpenNotebookOAuthError as exc:
        raise OpenNotebookOAuthError(
            f"OpenNotebook Discovery 的 {name} 无效: {exc}",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        ) from exc


def _metadata_list(payload: dict[str, Any], name: str) -> set[str]:
    value = payload.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OpenNotebookOAuthError(
            f"OpenNotebook Discovery 的 {name} 格式无效",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )
    return set(value)


async def oauth_provider_config() -> dict[str, str]:
    """通过 Discovery 解析端点；旧环境变量部署继续使用显式地址。"""
    cfg = oauth_config()
    if not cfg["discovery_url"]:
        return {
            **cfg,
            "authorization_endpoint": _join_url(cfg["public_url"], "/oauth/authorize"),
            "token_endpoint": _api_endpoint(cfg["api_url"], "/api/v1/oauth/token"),
            "revocation_endpoint": _api_endpoint(cfg["api_url"], "/api/v1/oauth/revoke"),
            "agent_endpoint": _api_endpoint(cfg["api_url"], "/api/v1/agent"),
        }

    cached = _discovery_cache.get(cfg["issuer"])
    if cached and cached[0] > time.monotonic():
        return {**cfg, **cached[1]}

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(
                cfg["discovery_url"],
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise OpenNotebookOAuthError(
            f"OpenNotebook Discovery 请求失败: {exc}",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        ) from exc
    if response.status_code != 200:
        raise OpenNotebookOAuthError(
            f"OpenNotebook Discovery 请求失败: {_response_error(response)}",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )
    if len(response.content) > DISCOVERY_MAX_BYTES:
        raise OpenNotebookOAuthError(
            "OpenNotebook Discovery 响应过大",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenNotebookOAuthError(
            "OpenNotebook Discovery 响应不是有效 JSON",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        ) from exc
    if not isinstance(payload, dict):
        raise OpenNotebookOAuthError(
            "OpenNotebook Discovery 响应格式无效",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )

    _metadata_string(payload, "issuer", base_url=True)
    if payload["issuer"] != cfg["issuer"]:
        raise OpenNotebookOAuthError(
            "OpenNotebook Discovery issuer 与 OPENNOTEBOOK_URL 不一致",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )
    if "code" not in _metadata_list(payload, "response_types_supported"):
        raise OpenNotebookOAuthError(
            "OpenNotebook Discovery 不支持 authorization code",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )
    if "S256" not in _metadata_list(payload, "code_challenge_methods_supported"):
        raise OpenNotebookOAuthError(
            "OpenNotebook Discovery 不支持 PKCE S256",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )
    grant_types = _metadata_list(payload, "grant_types_supported")
    if not {"authorization_code", "refresh_token"}.issubset(grant_types):
        raise OpenNotebookOAuthError(
            "OpenNotebook Discovery 缺少所需 grant type",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )
    if cfg["scope"] not in _metadata_list(payload, "scopes_supported"):
        raise OpenNotebookOAuthError(
            f"OpenNotebook Discovery 不支持 scope {cfg['scope']}",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )
    auth_methods = _metadata_list(payload, "token_endpoint_auth_methods_supported")
    if cfg["client_auth_method"] not in auth_methods:
        raise OpenNotebookOAuthError(
            f"OpenNotebook Discovery 不支持 {cfg['client_auth_method']}",
            code="OPENNOTEBOOK_DISCOVERY_FAILED",
        )

    discovered = {
        "api_url": _metadata_string(payload, "opennotebook_api_base", base_url=True),
        "authorization_endpoint": _metadata_string(payload, "authorization_endpoint"),
        "token_endpoint": _metadata_string(payload, "token_endpoint"),
        "revocation_endpoint": _metadata_string(payload, "revocation_endpoint"),
        "agent_endpoint": _metadata_string(payload, "agent_endpoint", base_url=True),
    }
    _discovery_cache[cfg["issuer"]] = (
        time.monotonic() + DISCOVERY_CACHE_SECONDS,
        discovered,
    )
    return {**cfg, **discovered}


def _fernet() -> Fernet:
    configured = os.getenv("OPENNOTEBOOK_CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if configured:
        try:
            return Fernet(configured.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise OpenNotebookOAuthError(
                "OPENNOTEBOOK_CREDENTIAL_ENCRYPTION_KEY 格式无效",
                code="OPENNOTEBOOK_ENCRYPTION_CONFIG_ERROR",
            ) from exc

    raise OpenNotebookOAuthError(
        "OPENNOTEBOOK_CREDENTIAL_ENCRYPTION_KEY 未配置",
        code="OPENNOTEBOOK_NOT_CONFIGURED",
    )


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise OpenNotebookOAuthError(
            "OpenNotebook 凭证无法解密，请重新授权",
            code="OPENNOTEBOOK_REAUTH_REQUIRED",
            reauth_required=True,
        ) from exc


def state_digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def build_authorization_url(*, state: str, code_challenge: str) -> str:
    cfg = await oauth_provider_config()
    endpoint = urlsplit(cfg["authorization_endpoint"])
    query = dict(parse_qsl(endpoint.query, keep_blank_values=True))
    query.update(
        {
            "response_type": "code",
            "client_id": cfg["client_id"],
            "redirect_uri": cfg["redirect_uri"],
            "scope": cfg["scope"],
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return urlunsplit(
        (endpoint.scheme, endpoint.netloc, endpoint.path, urlencode(query), "")
    )


def _response_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300] or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        detail = payload.get("error_description") or payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("code")
        if detail:
            return str(detail)[:300]
    return f"HTTP {response.status_code}"


def _unwrap_token_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if (
        not isinstance(payload, dict)
        or not payload.get("access_token")
        or not payload.get("refresh_token")
    ):
        raise OpenNotebookOAuthError(
            "OpenNotebook Token 响应格式异常（缺少 access_token 或 refresh_token）",
            code="OPENNOTEBOOK_TOKEN_RESPONSE_INVALID",
        )
    return payload


def _client_auth(cfg: dict[str, str], form: dict[str, str]) -> httpx.BasicAuth | None:
    """Confidential client 默认使用 RFC6749 client_secret_basic。"""
    if cfg["public_client"] == "true":
        return None
    return httpx.BasicAuth(cfg["client_id"], cfg["client_secret"])


async def exchange_authorization_code(code: str, verifier: str) -> dict[str, Any]:
    cfg = await oauth_provider_config()
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg["redirect_uri"],
        "client_id": cfg["client_id"],
        "code_verifier": verifier,
    }
    auth = _client_auth(cfg, form)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                cfg["token_endpoint"],
                data=form,
                headers={"Accept": "application/json"},
                auth=auth,
            )
    except httpx.HTTPError as exc:
        raise OpenNotebookOAuthError(
            f"OpenNotebook 授权码交换失败: {exc}",
            code="OPENNOTEBOOK_TOKEN_EXCHANGE_FAILED",
        ) from exc
    if response.status_code >= 400:
        raise OpenNotebookOAuthError(
            f"OpenNotebook 授权码交换失败: {_response_error(response)}",
            code="OPENNOTEBOOK_TOKEN_EXCHANGE_FAILED",
        )
    return _unwrap_token_payload(response.json())


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    cfg = await oauth_provider_config()
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": cfg["client_id"],
    }
    auth = _client_auth(cfg, form)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                cfg["token_endpoint"],
                data=form,
                headers={"Accept": "application/json"},
                auth=auth,
            )
    except httpx.HTTPError as exc:
        raise OpenNotebookOAuthError(
            f"OpenNotebook Token 刷新失败: {exc}",
            code="OPENNOTEBOOK_REFRESH_FAILED",
        ) from exc
    if response.status_code >= 400:
        raise OpenNotebookOAuthError(
            f"OpenNotebook 授权已失效: {_response_error(response)}",
            code="OPENNOTEBOOK_REAUTH_REQUIRED",
            reauth_required=response.status_code in (400, 401, 403),
        )
    return _unwrap_token_payload(response.json())


async def revoke_remote_token(token: str, *, token_type_hint: str) -> None:
    if not token:
        return
    cfg = await oauth_provider_config()
    form = {
        "token": token,
        "token_type_hint": token_type_hint,
        "client_id": cfg["client_id"],
    }
    auth = _client_auth(cfg, form)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                cfg["revocation_endpoint"],
                data=form,
                headers={"Accept": "application/json"},
                auth=auth,
            )
    except httpx.HTTPError as exc:
        raise OpenNotebookOAuthError(
            f"OpenNotebook 远程授权撤销失败: {exc}",
            code="OPENNOTEBOOK_REVOKE_FAILED",
        ) from exc
    if not 200 <= response.status_code < 300:
        raise OpenNotebookOAuthError(
            f"OpenNotebook 远程授权撤销失败: {_response_error(response)}",
            code="OPENNOTEBOOK_REVOKE_FAILED",
        )


async def revoke_token_pair(*, refresh_token: str, access_token: str) -> None:
    """Revoke both views of a grant and fail closed if either request fails."""
    errors: list[OpenNotebookOAuthError] = []
    for token, token_type_hint in (
        (refresh_token, "refresh_token"),
        (access_token, "access_token"),
    ):
        if not token:
            continue
        try:
            await revoke_remote_token(token, token_type_hint=token_type_hint)
        except OpenNotebookOAuthError as exc:
            errors.append(exc)
    if errors:
        raise errors[0]


async def resolve_workspace(token_payload: dict[str, Any]) -> tuple[str, str]:
    """Token metadata 优先，其次 DEFAULT_WORKSPACE_ID，最后取工作区列表首项。"""
    workspace_id = str(token_payload.get("workspace_id") or "").strip()
    workspace_name = str(token_payload.get("workspace_name") or "").strip()
    default_workspace_id = os.getenv("DEFAULT_WORKSPACE_ID", "").strip()
    if workspace_id:
        return workspace_id, workspace_name

    access_token = str(token_payload.get("access_token") or "")
    tenant_id = str(token_payload.get("tenant_id") or "")
    cfg = await oauth_provider_config()
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                _api_endpoint(cfg["api_url"], "/api/v1/workspaces"),
                headers=headers,
                params={"limit": 200},
            )
        if response.status_code >= 400:
            return default_workspace_id, ""
        payload: Any = response.json()
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("data") or payload.get("workspaces") or []
            if isinstance(payload, dict):
                payload = payload.get("items") or []
        workspaces = payload if isinstance(payload, list) else []
        selected: dict[str, Any] | None = None
        if default_workspace_id:
            selected = next(
                (item for item in workspaces if str(item.get("id") or "") == default_workspace_id),
                None,
            )
        selected = selected or (workspaces[0] if workspaces else None)
        if selected:
            return str(selected.get("id") or ""), str(selected.get("name") or "")
    except (httpx.HTTPError, ValueError, TypeError):
        pass
    return default_workspace_id, ""


def _expiry(now: int, payload: dict[str, Any], field: str) -> int:
    try:
        seconds = int(payload.get(field) or 0)
    except (TypeError, ValueError):
        seconds = 0
    return now + seconds if seconds > 0 else 0


def _scope_text(scope: Any) -> str:
    return " ".join(str(item) for item in scope) if isinstance(scope, list) else str(scope or "*")


def _lock_for(owner_user_id: str) -> asyncio.Lock:
    lock = _refresh_locks.get(owner_user_id)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[owner_user_id] = lock
    return lock


def credential_lock(owner_user_id: str) -> asyncio.Lock:
    """Shared per-user lock for OAuth save, refresh, and disconnect."""
    return _lock_for(owner_user_id)


async def lock_active_owner(
    session: AsyncSession,
    owner_user_id: str,
) -> UserModel:
    """Fence OAuth writes against user deletion across API workers."""
    try:
        user_id = int(owner_user_id)
    except (TypeError, ValueError) as exc:
        raise OpenNotebookOAuthError(
            "MediaCrawler 用户不存在或已停用",
            code="OPENNOTEBOOK_OWNER_INACTIVE",
        ) from exc
    result = await session.execute(
        select(UserModel)
        .where(UserModel.id == user_id)
        .with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None or user.status != "active":
        raise OpenNotebookOAuthError(
            "MediaCrawler 用户不存在或已停用",
            code="OPENNOTEBOOK_OWNER_INACTIVE",
        )
    return user


async def save_connection(
    owner_user_id: str,
    token_payload: dict[str, Any],
    *,
    workspace_id: str,
    workspace_name: str,
    expected_credential_version: int | None = None,
    oauth_flow_id: int | None = None,
    _lock_held: bool = False,
) -> OpenNotebookConnectionModel:
    async def _save_locked() -> OpenNotebookConnectionModel:
        now = _now()
        async with get_session() as session:
            # Global DB lock order is owner user -> connection -> flow. User
            # deletion follows the same order, so a callback cannot recreate
            # credentials for an owner that was deleted in another worker.
            await lock_active_owner(session, owner_user_id)
            result = await session.execute(
                select(OpenNotebookConnectionModel)
                .where(OpenNotebookConnectionModel.owner_user_id == owner_user_id)
                .with_for_update()
            )
            connection = result.scalar_one_or_none()
            current_version = int(connection.credential_version or 0) if connection else 0
            if (
                expected_credential_version is not None
                and current_version != expected_credential_version
            ):
                raise OpenNotebookOAuthError(
                    "OpenNotebook 连接状态已变化，请重新连接",
                    code="OPENNOTEBOOK_CONNECTION_CHANGED",
                )

            flow = None
            if oauth_flow_id is not None:
                flow_result = await session.execute(
                    select(OpenNotebookOAuthFlowModel)
                    .where(
                        OpenNotebookOAuthFlowModel.id == oauth_flow_id,
                        OpenNotebookOAuthFlowModel.owner_user_id == owner_user_id,
                        OpenNotebookOAuthFlowModel.consumed_ts > 0,
                    )
                    .with_for_update()
                )
                flow = flow_result.scalar_one_or_none()
                if flow is None:
                    raise OpenNotebookOAuthError(
                        "OpenNotebook 登录流程已被取消，请重新连接",
                        code="OPENNOTEBOOK_CONNECTION_CHANGED",
                    )

            new_grant_id = str(token_payload.get("grant_id") or "")
            if (
                connection is not None
                and connection.status == "active"
                and connection.grant_id
                and new_grant_id
                and connection.grant_id != new_grant_id
            ):
                old_refresh_token = decrypt_secret(
                    connection.refresh_token_ciphertext or ""
                )
                old_access_token = decrypt_secret(
                    connection.access_token_ciphertext or ""
                )
                if old_refresh_token or old_access_token:
                    # A different grant must not be orphaned when an account is
                    # replaced. The same grant is never revoked because that
                    # would also invalidate the newly issued token family.
                    await revoke_token_pair(
                        refresh_token=old_refresh_token,
                        access_token=old_access_token,
                    )

            values = {
                "provider_user_id": str(token_payload.get("user_id") or ""),
                "tenant_id": str(token_payload.get("tenant_id") or ""),
                "workspace_id": workspace_id,
                "workspace_name": workspace_name,
                "grant_id": new_grant_id,
                "scope": _scope_text(token_payload.get("scope")),
                "token_type": str(token_payload.get("token_type") or "Bearer"),
                "access_token_ciphertext": encrypt_secret(
                    str(token_payload["access_token"])
                ),
                "refresh_token_ciphertext": encrypt_secret(
                    str(token_payload.get("refresh_token") or "")
                ),
                "access_token_expires_ts": _expiry(now, token_payload, "expires_in"),
                "refresh_token_expires_ts": _expiry(
                    now, token_payload, "refresh_expires_in"
                ),
                "status": "active",
                "credential_version": current_version + 1,
                "last_error": "",
                "updated_ts": now,
            }
            if connection is None:
                connection = OpenNotebookConnectionModel(
                    owner_user_id=owner_user_id,
                    created_ts=now,
                    **values,
                )
                session.add(connection)
                await session.flush()
            else:
                saved = await session.execute(
                    update(OpenNotebookConnectionModel)
                    .where(
                        OpenNotebookConnectionModel.id == connection.id,
                        OpenNotebookConnectionModel.credential_version == current_version,
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )
                if saved.rowcount != 1:
                    raise OpenNotebookOAuthError(
                        "OpenNotebook 连接状态已变化，请重新连接",
                        code="OPENNOTEBOOK_CONNECTION_CHANGED",
                    )
                await session.refresh(connection)
            if flow is not None:
                await session.delete(flow)
            await session.flush()
            await session.refresh(connection)
            return connection

    if _lock_held:
        return await _save_locked()
    async with _lock_for(owner_user_id):
        return await _save_locked()


async def get_connection(owner_user_id: str) -> OpenNotebookConnectionModel | None:
    async with get_session() as session:
        result = await session.execute(
            select(OpenNotebookConnectionModel).where(
                OpenNotebookConnectionModel.owner_user_id == owner_user_id
            )
        )
        return result.scalar_one_or_none()


async def connection_status(owner_user_id: str) -> dict[str, Any]:
    connection = await get_connection(owner_user_id)
    if connection is None or connection.status == "revoked" or not connection.access_token_ciphertext:
        return {"connected": False, "status": "disconnected", "needs_reauth": False}
    now = _now()
    access_expired = bool(connection.access_token_expires_ts) and connection.access_token_expires_ts <= now
    refresh_unavailable = (
        not connection.refresh_token_ciphertext
        or (
            bool(connection.refresh_token_expires_ts)
            and connection.refresh_token_expires_ts <= now
        )
    )
    needs_reauth = connection.status == "reauth_required" or (access_expired and refresh_unavailable)
    return {
        "connected": connection.status == "active" and not needs_reauth,
        "status": "reauth_required" if needs_reauth else (connection.status or "active"),
        "needs_reauth": needs_reauth,
        "provider_user_id": connection.provider_user_id or "",
        "tenant_id": connection.tenant_id or "",
        "workspace_id": connection.workspace_id or "",
        "workspace_name": connection.workspace_name or "",
        "grant_id": connection.grant_id or "",
        "scope": connection.scope or "*",
        "access_token_expires_ts": connection.access_token_expires_ts or 0,
        "refresh_token_expires_ts": connection.refresh_token_expires_ts or 0,
        "connected_at": connection.created_ts or 0,
        "updated_at": connection.updated_ts or 0,
    }


async def mark_reauth_required(
    credentials: OpenNotebookCredentials,
    message: str,
) -> bool:
    """Mark only the exact credential generation that received a terminal 401.

    A response from an older request can arrive after a refresh or a brand-new
    OAuth grant has already been saved.  The shared owner lock, row lock, and
    version/grant CAS keep that stale response from invalidating fresh tokens.
    """
    async with _lock_for(credentials.owner_user_id):
        async with get_session() as session:
            result = await session.execute(
                select(OpenNotebookConnectionModel)
                .where(
                    OpenNotebookConnectionModel.id == credentials.connection_id,
                    OpenNotebookConnectionModel.owner_user_id
                    == credentials.owner_user_id,
                )
                .with_for_update()
            )
            connection = result.scalar_one_or_none()
            if (
                connection is None
                or connection.status != "active"
                or int(connection.credential_version or 0)
                != credentials.credential_version
                or (connection.grant_id or "") != credentials.grant_id
            ):
                return False

            marked = await session.execute(
                update(OpenNotebookConnectionModel)
                .where(
                    OpenNotebookConnectionModel.id == credentials.connection_id,
                    OpenNotebookConnectionModel.owner_user_id
                    == credentials.owner_user_id,
                    OpenNotebookConnectionModel.status == "active",
                    OpenNotebookConnectionModel.credential_version
                    == credentials.credential_version,
                    OpenNotebookConnectionModel.grant_id == connection.grant_id,
                )
                .values(
                    status="reauth_required",
                    credential_version=credentials.credential_version + 1,
                    last_error=message[:500],
                    updated_ts=_now(),
                )
                .execution_options(synchronize_session=False)
            )
            return marked.rowcount == 1


async def get_valid_credentials(
    owner_user_id: str,
    *,
    force_refresh: bool = False,
) -> OpenNotebookCredentials:
    connection = await get_connection(owner_user_id)
    if connection is None or connection.status == "revoked" or not connection.access_token_ciphertext:
        raise OpenNotebookOAuthError(
            "请先连接 OpenNotebook",
            code="OPENNOTEBOOK_NOT_CONNECTED",
            reauth_required=True,
        )
    if connection.status == "reauth_required":
        raise OpenNotebookOAuthError(
            "OpenNotebook 授权已失效，请重新连接",
            code="OPENNOTEBOOK_REAUTH_REQUIRED",
            reauth_required=True,
        )

    now = _now()
    should_refresh = force_refresh or (
        bool(connection.access_token_expires_ts)
        and connection.access_token_expires_ts <= now + ACCESS_TOKEN_REFRESH_SKEW_SECONDS
    )
    if should_refresh:
        initial_version = int(connection.credential_version or 0)
        async with _lock_for(owner_user_id):
            # PostgreSQL/MySQL 通过行锁跨 worker 串行化 refresh/disconnect；
            # SQLite 单进程部署由上面的 per-user 锁保护。credential_version
            # 的 CAS 同时阻止过期 refresh 结果覆盖已经断开的连接。
            async with get_session() as session:
                result = await session.execute(
                    select(OpenNotebookConnectionModel)
                    .where(OpenNotebookConnectionModel.owner_user_id == owner_user_id)
                    .with_for_update()
                )
                locked = result.scalar_one_or_none()
                if locked is None:
                    raise OpenNotebookOAuthError(
                        "请先连接 OpenNotebook",
                        code="OPENNOTEBOOK_NOT_CONNECTED",
                        reauth_required=True,
                    )
                if locked.status == "revoked" or not locked.access_token_ciphertext:
                    raise OpenNotebookOAuthError(
                        "OpenNotebook 已断开，请重新连接",
                        code="OPENNOTEBOOK_NOT_CONNECTED",
                        reauth_required=True,
                    )
                if locked.status != "active":
                    raise OpenNotebookOAuthError(
                        "OpenNotebook 授权已失效，请重新连接",
                        code="OPENNOTEBOOK_REAUTH_REQUIRED",
                        reauth_required=True,
                    )
                now = _now()
                still_needs_refresh = (
                    force_refresh and int(locked.credential_version or 0) == initial_version
                ) or (
                    bool(locked.access_token_expires_ts)
                    and locked.access_token_expires_ts <= now + ACCESS_TOKEN_REFRESH_SKEW_SECONDS
                )
                if still_needs_refresh:
                    refresh_version = int(locked.credential_version or 0)
                    refresh_token = decrypt_secret(locked.refresh_token_ciphertext or "")
                    if not refresh_token or (
                        locked.refresh_token_expires_ts
                        and locked.refresh_token_expires_ts <= now
                    ):
                        await session.execute(
                            update(OpenNotebookConnectionModel)
                            .where(
                                OpenNotebookConnectionModel.id == locked.id,
                                OpenNotebookConnectionModel.status == "active",
                                OpenNotebookConnectionModel.credential_version == refresh_version,
                            )
                            .values(
                                status="reauth_required",
                                credential_version=refresh_version + 1,
                                last_error="Refresh Token 不存在或已过期",
                                updated_ts=now,
                            )
                            .execution_options(synchronize_session=False)
                        )
                        await session.commit()
                        raise OpenNotebookOAuthError(
                            "OpenNotebook 授权已过期，请重新连接",
                            code="OPENNOTEBOOK_REAUTH_REQUIRED",
                            reauth_required=True,
                        )
                    try:
                        payload = await refresh_access_token(refresh_token)
                    except OpenNotebookOAuthError as exc:
                        if exc.reauth_required:
                            await session.execute(
                                update(OpenNotebookConnectionModel)
                                .where(
                                    OpenNotebookConnectionModel.id == locked.id,
                                    OpenNotebookConnectionModel.status == "active",
                                    OpenNotebookConnectionModel.credential_version == refresh_version,
                                )
                                .values(
                                    status="reauth_required",
                                    credential_version=refresh_version + 1,
                                    last_error=str(exc)[:500],
                                    updated_ts=now,
                                )
                                .execution_options(synchronize_session=False)
                            )
                            await session.commit()
                        raise

                    # Refresh Token 轮换必须与 Access Token 在同一行锁事务中替换。
                    payload.setdefault("refresh_token", refresh_token)
                    if not payload.get("refresh_expires_in") and locked.refresh_token_expires_ts:
                        payload["refresh_expires_in"] = max(0, locked.refresh_token_expires_ts - now)
                    refreshed = await session.execute(
                        update(OpenNotebookConnectionModel)
                        .where(
                            OpenNotebookConnectionModel.id == locked.id,
                            OpenNotebookConnectionModel.status == "active",
                            OpenNotebookConnectionModel.credential_version == refresh_version,
                        )
                        .values(
                            provider_user_id=str(
                                payload.get("user_id") or locked.provider_user_id or ""
                            ),
                            tenant_id=str(payload.get("tenant_id") or locked.tenant_id or ""),
                            grant_id=str(payload.get("grant_id") or locked.grant_id or ""),
                            scope=_scope_text(payload.get("scope") or locked.scope),
                            token_type=str(payload.get("token_type") or "Bearer"),
                            access_token_ciphertext=encrypt_secret(str(payload["access_token"])),
                            refresh_token_ciphertext=encrypt_secret(
                                str(payload.get("refresh_token") or "")
                            ),
                            access_token_expires_ts=_expiry(now, payload, "expires_in"),
                            refresh_token_expires_ts=_expiry(
                                now, payload, "refresh_expires_in"
                            ),
                            status="active",
                            credential_version=refresh_version + 1,
                            last_error="",
                            last_refresh_ts=now,
                            updated_ts=now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if refreshed.rowcount != 1:
                        await session.rollback()
                        raise OpenNotebookOAuthError(
                            "OpenNotebook 连接状态已变化，请重试",
                            code="OPENNOTEBOOK_CONNECTION_CHANGED",
                        )
                    await session.refresh(locked)
                connection = locked

    access_token = decrypt_secret(connection.access_token_ciphertext)
    if not connection.workspace_id:
        raise OpenNotebookOAuthError(
            "OpenNotebook 账号没有可用工作区",
            code="OPENNOTEBOOK_WORKSPACE_REQUIRED",
        )
    async with get_session() as session:
        result = await session.execute(
            select(OpenNotebookConnectionModel).where(OpenNotebookConnectionModel.id == connection.id)
        )
        row = result.scalar_one_or_none()
        if row:
            row.last_used_ts = now
    return OpenNotebookCredentials(
        connection_id=connection.id,
        owner_user_id=owner_user_id,
        credential_version=int(connection.credential_version or 0),
        access_token=access_token,
        token_type=connection.token_type or "Bearer",
        tenant_id=connection.tenant_id or "",
        workspace_id=connection.workspace_id or "",
        workspace_name=connection.workspace_name or "",
        grant_id=connection.grant_id or "",
    )


async def disconnect(
    owner_user_id: str,
    *,
    _lock_held: bool = False,
    _session: AsyncSession | None = None,
) -> bool:
    # The same per-user lock is used by refresh.  The DB row lock extends over
    # remote revoke so another worker cannot rotate the token between reading it
    # and revoking it.  Local ciphertext is cleared only after a 2xx revoke; on
    # network/5xx failure the transaction rolls back and the user can retry.
    async def _disconnect_locked() -> bool:
        async def _disconnect_in_session(session: AsyncSession) -> bool:
            result = await session.execute(
                select(OpenNotebookConnectionModel)
                .where(OpenNotebookConnectionModel.owner_user_id == owner_user_id)
                .with_for_update()
            )
            row = result.scalar_one_or_none()
            if row is None:
                await session.execute(
                    delete(OpenNotebookOAuthFlowModel).where(
                        OpenNotebookOAuthFlowModel.owner_user_id == owner_user_id
                    )
                )
                return False

            disconnect_version = int(row.credential_version or 0)
            refresh_token = decrypt_secret(row.refresh_token_ciphertext or "")
            access_token = decrypt_secret(row.access_token_ciphertext or "")
            await revoke_token_pair(
                refresh_token=refresh_token,
                access_token=access_token,
            )

            disconnected = await session.execute(
                update(OpenNotebookConnectionModel)
                .where(
                    OpenNotebookConnectionModel.id == row.id,
                    OpenNotebookConnectionModel.credential_version == disconnect_version,
                )
                .values(
                    status="revoked",
                    access_token_ciphertext="",
                    refresh_token_ciphertext="",
                    access_token_expires_ts=0,
                    refresh_token_expires_ts=0,
                    credential_version=disconnect_version + 1,
                    updated_ts=_now(),
                    last_error="",
                )
                .execution_options(synchronize_session=False)
            )
            if disconnected.rowcount != 1:
                raise OpenNotebookOAuthError(
                    "OpenNotebook 连接状态已变化，请重试断开",
                    code="OPENNOTEBOOK_CONNECTION_CHANGED",
                )
            await session.execute(
                delete(OpenNotebookOAuthFlowModel).where(
                    OpenNotebookOAuthFlowModel.owner_user_id == owner_user_id
                )
            )
            return True

        if _session is not None:
            return await _disconnect_in_session(_session)
        async with get_session() as session:
            return await _disconnect_in_session(session)

    if _lock_held:
        return await _disconnect_locked()
    async with _lock_for(owner_user_id):
        return await _disconnect_locked()
