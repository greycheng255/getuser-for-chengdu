# -*- coding: utf-8 -*-
"""
通用工具服务（P2：通用工具）

提供 Cookie 刷新器和统一错误处理。

迁移自 GEO-main：
- cookie_refresher.py：定期刷新各平台 cookie 保持登录状态
- error_handler.py：统一错误捕获和处理

目录结构：
    utils/
    ├── __init__.py
    ├── cookie_refresher.py
    └── error_handler.py
"""
from .cookie_refresher import CookieRefresher, get_cookie_refresher_service
from .error_handler import (
    APIError,
    AuthenticationError,
    AuthorizationError,
    ErrorHandlerService,
    ErrorLogger,
    NotFoundError,
    PerformanceMonitor,
    RateLimitError,
    ServerError,
    ValidationError,
    get_error_handler_service,
    handle_api_error,
    handle_generic_error,
)

__all__ = [
    "CookieRefresher",
    "get_cookie_refresher_service",
    "APIError",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "ErrorLogger",
    "PerformanceMonitor",
    "ErrorHandlerService",
    "get_error_handler_service",
    "handle_api_error",
    "handle_generic_error",
]
