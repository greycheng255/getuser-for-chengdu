# -*- coding: utf-8 -*-
"""
多平台发布服务（第一阶段：多平台发布能力扩展）

迁移自 GEO-main 项目，适配 MediaCrawler 的异步架构 + 数据库层 + Cookie 池。

目录结构：
    publisher/
    ├── __init__.py              # 模块导出
    ├── base_publisher.py        # BasePublisher 抽象基类（模板方法）
    ├── publisher_factory.py     # 注册式工厂
    ├── stealth_browser.py       # 共享反检测浏览器（迁移自 GEO）
    ├── platform_configs.py      # 平台元数据 + 风控词库
    ├── content_adapter.py       # 多平台内容适配器
    ├── account_service.py       # 平台账号管理（异步，对接 MediaCrawler DB）
    ├── publish_task.py          # PublishTask / PublishResult 数据类
    ├── exceptions.py            # 业务异常
    ├── multi_publisher.py       # 多平台并行/串行编排器
    └── platforms/
        ├── __init__.py
        ├── douyin_publisher.py        # 抖音图文
        ├── xiaohongshu_publisher.py   # 小红书图文
        ├── bilibili_publisher.py      # B站专栏
        ├── weibo_publisher.py         # 微博图文
        └── zhihu_publisher.py         # 知乎专栏
"""
from .base_publisher import BasePublisher
from .publisher_factory import PublisherFactory
from .publish_task import PublishTask, PublishResult, PublishStatus
from .exceptions import (
    PublisherError,
    LoginExpiredError,
    BizError,
    RateLimitError,
    ContentBlockedError,
)
from .multi_publisher import MultiPlatformPublisher, get_multi_publisher
from .account_service import PlatformAccountService, get_account_service

__all__ = [
    "BasePublisher",
    "PublisherFactory",
    "PublishTask",
    "PublishResult",
    "PublishStatus",
    "PublisherError",
    "LoginExpiredError",
    "BizError",
    "RateLimitError",
    "ContentBlockedError",
    "MultiPlatformPublisher",
    "PlatformAccountService",
    "get_account_service",
    "get_multi_publisher",
]
