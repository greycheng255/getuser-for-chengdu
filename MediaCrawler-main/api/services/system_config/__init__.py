# -*- coding: utf-8 -*-
"""系统配置服务(评分规则 / 通知设置等 KV 配置持久化)"""
from .system_config_service import (
    SystemConfigService,
    get_system_config_service,
)

__all__ = [
    "SystemConfigService",
    "get_system_config_service",
]
