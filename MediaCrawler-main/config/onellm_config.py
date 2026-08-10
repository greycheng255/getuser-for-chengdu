# -*- coding: utf-8 -*-
"""Shared AI gateway configuration (temporarily backed by AI6700)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


DEFAULT_ONELLM_BASE_URL = "https://api.lk888.ai/api"

__all__ = [
    "DEFAULT_ONELLM_BASE_URL",
    "OneLLMConfig",
    "load_onellm_config",
    "ONELLM_API_KEY",
    "ONELLM_BASE_URL",
    "ONELLM_CHAT_MODEL",
    "ONELLM_VIDEO_MODEL",
    "ONELLM_REFERENCE_VIDEO_MODEL",
]


@dataclass(frozen=True)
class OneLLMConfig:
    api_key: str
    base_url: str
    chat_model: str
    video_model: str
    reference_video_model: str

    def endpoint(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"


def _normalize_base_url(value: str) -> str:
    raw = (value or DEFAULT_ONELLM_BASE_URL).strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("ONELLM_BASE_URL 必须是有效的 http(s) URL")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("ONELLM_BASE_URL 不能包含凭据、query 或 fragment")

    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        path = f"{path}/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def load_onellm_config() -> OneLLMConfig:
    """Load the shared AI6700 identity and model configuration for all calls."""
    return OneLLMConfig(
        api_key=os.getenv("ONELLM_API_KEY", "").strip(),
        base_url=_normalize_base_url(
            os.getenv("ONELLM_BASE_URL", DEFAULT_ONELLM_BASE_URL)
        ),
        chat_model=os.getenv("ONELLM_CHAT_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash",
        video_model=os.getenv("ONELLM_VIDEO_MODEL", "kwvideo-v2").strip()
        or "kwvideo-v2",
        reference_video_model=os.getenv(
            "ONELLM_REFERENCE_VIDEO_MODEL", "kwvideo-v2-ref"
        ).strip()
        or "kwvideo-v2-ref",
    )


_SETTINGS = load_onellm_config()

ONELLM_API_KEY = _SETTINGS.api_key
ONELLM_BASE_URL = _SETTINGS.base_url
ONELLM_CHAT_MODEL = _SETTINGS.chat_model
ONELLM_VIDEO_MODEL = _SETTINGS.video_model
ONELLM_REFERENCE_VIDEO_MODEL = _SETTINGS.reference_video_model
