# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/__init__.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

from .crawler import router as crawler_router
from .data import router as data_router
from .websocket import router as websocket_router
from .customer_lead import router as customer_lead_router
from .tasks import router as tasks_router
from .cookies import router as cookies_router
from .auth import router as auth_router
from .business import router as business_router
from .external_api import router as external_api_router
from .config import router as config_router
from .notifications import router as notifications_router
from .plan import router as plan_router
from .x_twitter import router as x_twitter_router
from .x_twitter_workbench import router as x_twitter_workbench_router
from .x_workbench_crawl import router as x_workbench_crawl_router
from .x_workbench_templates import router as x_workbench_templates_router
from .x_workbench_analytics import router as x_workbench_analytics_router
from .x_workbench_export import router as x_workbench_export_router
from .x_workbench_notifications import router as x_workbench_notifications_router
from .x_workbench_auto_mode import router as x_workbench_auto_mode_router
from .x_workbench_advanced import router as x_workbench_advanced_router
from .x_workbench_advanced import _ws_router as x_workbench_ws_router
from .hotpoint import router as hotpoint_router
from ..services.agent_client import router as agent_router

__all__ = ["crawler_router", "data_router", "websocket_router", "customer_lead_router", "tasks_router", "cookies_router", "auth_router", "business_router", "agent_router", "external_api_router", "config_router", "notifications_router", "plan_router", "x_twitter_router", "x_twitter_workbench_router", "x_workbench_crawl_router", "x_workbench_templates_router", "x_workbench_analytics_router", "x_workbench_export_router", "x_workbench_notifications_router", "x_workbench_auto_mode_router", "x_workbench_advanced_router", "x_workbench_ws_router", "hotpoint_router"]
