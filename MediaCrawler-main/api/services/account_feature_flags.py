# -*- coding: utf-8 -*-
"""统一账号切换开关。

开关只控制数据源选择。旧 API 是否保留由路由注册控制；统一写入开启时，
旧 API 必须委托统一服务，禁止同时写入旧表。
"""

import os


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def unified_account_write_enabled() -> bool:
    return _as_bool("UNIFIED_ACCOUNT_WRITE_ENABLED", False)


def unified_account_read_enabled() -> bool:
    return _as_bool("UNIFIED_ACCOUNT_READ_ENABLED", False)


def legacy_account_api_enabled() -> bool:
    return _as_bool("LEGACY_ACCOUNT_API_ENABLED", True)
