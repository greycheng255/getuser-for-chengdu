# -*- coding: utf-8 -*-
"""MediaCrawler 连接 OpenNotebook 的 OAuth2 Authorization Code + PKCE 路由。"""
from __future__ import annotations

import hmac
import logging
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from api.services.auth import get_current_user
from api.services.opennotebook_oauth import (
    OAUTH_FLOW_TTL_SECONDS,
    OpenNotebookOAuthError,
    build_authorization_url,
    connection_status,
    credential_lock,
    decrypt_secret,
    disconnect,
    encrypt_secret,
    exchange_authorization_code,
    get_connection,
    lock_active_owner,
    oauth_config,
    pkce_challenge,
    resolve_workspace,
    revoke_token_pair,
    save_connection,
    state_digest,
)
from api.utils.exceptions import ConflictError
from database.db_session import get_session
from database.user_models import OpenNotebookConnectionModel, OpenNotebookOAuthFlowModel


router = APIRouter(prefix="/integrations/opennotebook", tags=["opennotebook-integration"])
logger = logging.getLogger(__name__)
OAUTH_BINDING_COOKIE = "mc_opennotebook_oauth_binding"
OAUTH_CALLBACK_COOKIE_PATH_FALLBACK = "/api/integrations/opennotebook/callback"


class OAuthStartRequest(BaseModel):
    return_to: str = Field(default="/x-workbench", max_length=255)


def _now() -> int:
    return int(time.time())


def _safe_return_to(value: str) -> str:
    value = (value or "").strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/x-workbench"
    return value


def _callback_redirect(*, result: str, return_to: str = "/x-workbench", error: str = "") -> str:
    try:
        base = oauth_config()["frontend_callback_url"]
    except OpenNotebookOAuthError:
        base = "http://localhost:35174/integrations/opennotebook/callback"
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"result": result, "return_to": _safe_return_to(return_to)})
    if error:
        query["error"] = error
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _binding_cookie_path() -> str:
    try:
        return urlsplit(oauth_config()["redirect_uri"]).path or "/"
    except OpenNotebookOAuthError:
        return OAUTH_CALLBACK_COOKIE_PATH_FALLBACK


def _redirect_response(
    *,
    result: str,
    return_to: str = "/x-workbench",
    error: str = "",
    clear_binding: bool = False,
) -> RedirectResponse:
    response = RedirectResponse(
        _callback_redirect(result=result, return_to=return_to, error=error),
        status_code=302,
    )
    if clear_binding:
        response.delete_cookie(
            OAUTH_BINDING_COOKIE,
            path=_binding_cookie_path(),
            httponly=True,
            samesite="lax",
        )
    return response


def _raise_connection_error(exc: OpenNotebookOAuthError) -> None:
    if exc.code in {
        "OPENNOTEBOOK_NOT_CONFIGURED",
        "OPENNOTEBOOK_ENCRYPTION_CONFIG_ERROR",
        "OPENNOTEBOOK_INSECURE_URL",
    }:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not exc.reauth_required and exc.code in {
        "OPENNOTEBOOK_REFRESH_FAILED",
        "OPENNOTEBOOK_TOKEN_EXCHANGE_FAILED",
        "OPENNOTEBOOK_TOKEN_RESPONSE_INVALID",
        "OPENNOTEBOOK_OAUTH_ERROR",
        "OPENNOTEBOOK_REVOKE_FAILED",
        "OPENNOTEBOOK_DISCOVERY_FAILED",
    }:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise ConflictError(
        str(exc),
        code=4091,
        data={"reason": exc.code, "needs_reauth": exc.reauth_required},
    ) from exc


async def _cleanup_rejected_token(
    owner_user_id: str,
    token_payload: dict,
) -> bool:
    """Compensate a successful exchange that could not be saved locally."""
    refresh_token = str(token_payload.get("refresh_token") or "")
    access_token = str(token_payload.get("access_token") or "")
    if not refresh_token and not access_token:
        return True

    # Never revoke a newly rotated token from the same grant that is still the
    # active local connection (for example, a benign concurrent refresh).
    current = await get_connection(owner_user_id)
    new_grant_id = str(token_payload.get("grant_id") or "")
    if (
        current is not None
        and current.status == "active"
        and current.grant_id
        and current.grant_id == new_grant_id
    ):
        return True
    try:
        await revoke_token_pair(
            refresh_token=refresh_token,
            access_token=access_token,
        )
        return True
    except OpenNotebookOAuthError:
        logger.exception(
            "Failed to revoke rejected OpenNotebook token for owner=%s grant=%s",
            owner_user_id,
            new_grant_id,
        )
        return False


@router.post("/start")
async def start_opennotebook_oauth(
    body: OAuthStartRequest,
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """为当前 MediaCrawler 用户创建一次性 state/PKCE 授权会话。"""
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    browser_binding = secrets.token_urlsafe(32)
    try:
        cfg = oauth_config()
        encrypted_verifier = encrypt_secret(verifier)
    except OpenNotebookOAuthError as exc:
        _raise_connection_error(exc)
    now = _now()
    owner_user_id = str(current_user["id"])
    return_to = _safe_return_to(body.return_to)
    try:
        async with credential_lock(owner_user_id):
            async with get_session() as session:
                await lock_active_owner(session, owner_user_id)
                connection_result = await session.execute(
                    select(OpenNotebookConnectionModel)
                    .where(OpenNotebookConnectionModel.owner_user_id == owner_user_id)
                    .with_for_update()
                )
                connection = connection_result.scalar_one_or_none()
                expected_version = int(connection.credential_version or 0) if connection else 0
                # 每个用户只保留最新授权；disconnect 删除此行即可取消尚在交换中的流程。
                await session.execute(
                    delete(OpenNotebookOAuthFlowModel).where(
                        OpenNotebookOAuthFlowModel.owner_user_id == owner_user_id
                    )
                )
                session.add(
                    OpenNotebookOAuthFlowModel(
                        state_hash=state_digest(state),
                        owner_user_id=owner_user_id,
                        browser_binding_hash=state_digest(browser_binding),
                        expected_credential_version=expected_version,
                        code_verifier_ciphertext=encrypted_verifier,
                        return_to=return_to,
                        created_ts=now,
                        expires_ts=now + OAUTH_FLOW_TTL_SECONDS,
                        consumed_ts=0,
                    )
                )
    except OpenNotebookOAuthError as exc:
        _raise_connection_error(exc)
    try:
        authorization_url = await build_authorization_url(
            state=state,
            code_challenge=pkce_challenge(verifier),
        )
    except OpenNotebookOAuthError as exc:
        _raise_connection_error(exc)
    response.set_cookie(
        OAUTH_BINDING_COOKIE,
        browser_binding,
        max_age=OAUTH_FLOW_TTL_SECONDS,
        httponly=True,
        secure=urlsplit(cfg["redirect_uri"]).scheme == "https",
        samesite="lax",
        path=urlsplit(cfg["redirect_uri"]).path or "/",
    )
    return {
        "authorization_url": authorization_url,
        "expires_ts": now + OAUTH_FLOW_TTL_SECONDS,
    }


@router.get("/callback")
async def opennotebook_oauth_callback(
    request: Request,
    code: str = Query(default="", max_length=2048),
    state: str = Query(default="", max_length=1024),
    error: str = Query(default="", max_length=255),
):
    """OpenNotebook 公开回调；仅依赖一次性 state，不依赖浏览器 Bearer Token。"""
    if not state:
        return _redirect_response(
            result="error",
            error="invalid_state",
        )

    now = _now()
    # Look up only enough metadata to validate the initiating browser. State
    # alone is bearer-like and does not prevent OAuth account-linking CSRF.
    async with get_session() as session:
        result = await session.execute(
            select(OpenNotebookOAuthFlowModel)
            .where(
                OpenNotebookOAuthFlowModel.state_hash == state_digest(state),
                OpenNotebookOAuthFlowModel.consumed_ts == 0,
                OpenNotebookOAuthFlowModel.expires_ts > now,
            )
        )
        candidate = result.scalar_one_or_none()

    if candidate is None:
        return _redirect_response(
            result="error",
            error="invalid_or_expired_state",
        )
    browser_binding = request.cookies.get(OAUTH_BINDING_COOKIE, "")
    if not browser_binding or not hmac.compare_digest(
        state_digest(browser_binding),
        candidate.browser_binding_hash or "",
    ):
        return _redirect_response(
            result="error",
            return_to=candidate.return_to or "/x-workbench",
            error="invalid_browser_binding",
        )

    owner_user_id = candidate.owner_user_id
    async with credential_lock(owner_user_id):
        flow: OpenNotebookOAuthFlowModel | None = None
        async with get_session() as session:
            result = await session.execute(
                select(OpenNotebookOAuthFlowModel)
                .where(
                    OpenNotebookOAuthFlowModel.id == candidate.id,
                    OpenNotebookOAuthFlowModel.state_hash == state_digest(state),
                    OpenNotebookOAuthFlowModel.consumed_ts == 0,
                    OpenNotebookOAuthFlowModel.expires_ts > _now(),
                )
                .with_for_update()
            )
            flow = result.scalar_one_or_none()
            if flow and hmac.compare_digest(
                state_digest(browser_binding),
                flow.browser_binding_hash or "",
            ):
                # Consume before token exchange; failures cannot replay the code.
                flow.consumed_ts = _now()
                await session.flush()
            else:
                flow = None

        if flow is None:
            return _redirect_response(
                result="error",
                error="invalid_or_expired_state",
                clear_binding=True,
            )
        return_to = flow.return_to or "/x-workbench"
        if error:
            return _redirect_response(
                result="error",
                return_to=return_to,
                error="authorization_denied",
                clear_binding=True,
            )
        if not code:
            return _redirect_response(
                result="error",
                return_to=return_to,
                error="missing_code",
                clear_binding=True,
            )

        token_payload: dict | None = None
        try:
            verifier = decrypt_secret(flow.code_verifier_ciphertext)
            token_payload = await exchange_authorization_code(code, verifier)
            workspace_id, workspace_name = await resolve_workspace(token_payload)
            await save_connection(
                owner_user_id,
                token_payload,
                workspace_id=workspace_id,
                workspace_name=workspace_name,
                expected_credential_version=flow.expected_credential_version or 0,
                oauth_flow_id=flow.id,
                _lock_held=True,
            )
        except Exception as exc:
            logger.warning(
                "OpenNotebook callback could not persist credentials for owner=%s: %s",
                owner_user_id,
                exc,
            )
            cleanup_ok = True
            if token_payload is not None:
                cleanup_ok = await _cleanup_rejected_token(owner_user_id, token_payload)
            return _redirect_response(
                result="error",
                return_to=return_to,
                error=(
                    "token_exchange_failed"
                    if cleanup_ok
                    else "token_cleanup_failed"
                ),
                clear_binding=True,
            )

    return _redirect_response(
        result="success",
        return_to=return_to,
        clear_binding=True,
    )


@router.get("/status")
async def get_opennotebook_status(current_user: dict = Depends(get_current_user)):
    """只返回当前用户的脱敏连接元数据。"""
    return await connection_status(str(current_user["id"]))


@router.post("/disconnect")
async def disconnect_opennotebook(current_user: dict = Depends(get_current_user)):
    """远程撤销成功后清除当前用户的本地凭证。"""
    try:
        disconnected = await disconnect(str(current_user["id"]))
    except OpenNotebookOAuthError as exc:
        _raise_connection_error(exc)
    return {"connected": False, "disconnected": disconnected}


def raise_opennotebook_conflict(exc: OpenNotebookOAuthError) -> None:
    """供视频生成路由统一映射为 409，避免前端把上游 401 当成本地登录失效。"""
    _raise_connection_error(exc)
