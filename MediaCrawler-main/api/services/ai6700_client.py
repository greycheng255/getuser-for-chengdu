# -*- coding: utf-8 -*-
"""Small shared helpers for the temporary AI6700 integration."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from config.onellm_config import OneLLMConfig, load_onellm_config


class AI6700BalanceError(RuntimeError):
    """The mandatory preflight balance check failed."""

    def __init__(
        self,
        message: str,
        status_code: int = 502,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def ai6700_headers(settings: OneLLMConfig | None = None) -> dict[str, str]:
    settings = settings or load_onellm_config()
    if not settings.api_key:
        raise AI6700BalanceError("ONELLM_API_KEY 未配置", 503)
    return {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json; charset=utf-8",
    }


def ai6700_error_message(response: httpx.Response) -> str:
    """Extract both AI6700 legacy and standard error payloads safely."""
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text[:500] or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        detail = (
            payload.get("msg")
            or payload.get("detail")
            or payload.get("message")
            or payload.get("error")
        )
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("code") or detail)
        if detail:
            return str(detail)
    return str(payload)[:500]


async def ensure_ai6700_balance(
    settings: OneLLMConfig | None = None,
) -> dict[str, Any]:
    """Run AI6700's required balance preflight before a paid call."""
    settings = settings or load_onellm_config()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                settings.endpoint("skills/balance"),
                headers=ai6700_headers(settings),
            )
    except httpx.HTTPError as exc:
        raise AI6700BalanceError(
            f"AI6700 余额查询失败: {exc}",
            retryable=True,
        ) from exc

    if response.status_code >= 400:
        status_code = 503 if response.status_code == 401 else response.status_code
        raise AI6700BalanceError(
            f"AI6700 余额查询失败: {ai6700_error_message(response)}",
            status_code,
            retryable=response.status_code >= 500,
        )

    try:
        payload = response.json()
        balance = Decimal(str(payload["balance"]))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise AI6700BalanceError("AI6700 余额响应格式异常") from exc
    if balance <= 0:
        raise AI6700BalanceError(
            "AI6700 算力余额不足，请前往平台充值",
            402,
        )
    return payload
