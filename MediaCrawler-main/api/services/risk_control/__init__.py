# -*- coding: utf-8 -*-
"""
风控优化服务（第六阶段）

对应 PRD 5.6 风控合规 - 操作风控 / 账号风控：
1. 账号健康度评分：综合发布频率/互动频率/异常记录
2. 账号异常预警：限流/封禁/登录失效实时检测
3. IP 代理池：海外平台匹配对应国家 IP
4. 模拟真人操作节奏：随机停留/随机数量（已在 BaseInteractor 实现）

目录结构：
    risk_control/
    ├── __init__.py
    ├── account_health.py    # 账号健康度评分 + 异常预警
    └── proxy_pool.py        # IP 代理池管理
"""
from .account_health import AccountHealthService, HealthLevel, get_account_health_service
from .proxy_pool import ProxyPool, ProxyInfo, get_proxy_pool
from .quota_config import QuotaConfigService, get_quota_config_service
from .account_weight import (
    AccountWeightService,
    AccountWeight,
    WeightFactors,
    get_account_weight_service,
)

__all__ = [
    "AccountHealthService",
    "HealthLevel",
    "get_account_health_service",
    "ProxyPool",
    "ProxyInfo",
    "get_proxy_pool",
    "QuotaConfigService",
    "get_quota_config_service",
    "AccountWeightService",
    "AccountWeight",
    "WeightFactors",
    "get_account_weight_service",
]
