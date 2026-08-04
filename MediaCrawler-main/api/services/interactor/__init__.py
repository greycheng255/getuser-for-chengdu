# -*- coding: utf-8 -*-
"""
多平台互动服务（第二阶段：多平台互动能力扩展）

对应 PRD 5.4 智能机器人互动，将互动能力从 X 单平台扩展到国内主流平台。

目录结构：
    interactor/
    ├── __init__.py               # 模块导出
    ├── interaction_models.py     # 互动任务/结果/监控评论数据类
    ├── base_interactor.py        # BaseInteractor 抽象基类（模板方法）
    ├── interactor_factory.py     # 注册式工厂
    ├── multi_interactor.py       # 多平台并行互动编排
    └── interaction_monitor.py    # 统一评论监控服务（多平台并行）
    └── platforms/
        ├── douyin_interactor.py
        ├── xiaohongshu_interactor.py
        ├── bilibili_interactor.py
        ├── weibo_interactor.py
        └── zhihu_interactor.py
"""
from .base_interactor import BaseInteractor
from .interactor_factory import InteractorFactory
from .interaction_models import (
    InteractionType,
    InteractionStatus,
    InteractionResult,
    InteractionTask,
    MonitoredComment,
)
from .multi_interactor import MultiInteractor, get_multi_interactor
from .interaction_scheduler import InteractionScheduler, get_interaction_scheduler
from .script_library import ScriptLibrary, get_script_library
from .script_generator import ScriptGenerator, get_script_generator
from .bot_account_pool import BotAccountPool, get_bot_account_pool
from .interaction_config import (
    InteractionConfig,
    InteractionConfigService,
    get_interaction_config_service,
)

__all__ = [
    "BaseInteractor",
    "InteractorFactory",
    "InteractionType",
    "InteractionStatus",
    "InteractionResult",
    "InteractionTask",
    "MonitoredComment",
    "MultiInteractor",
    "get_multi_interactor",
    "InteractionScheduler",
    "get_interaction_scheduler",
    "ScriptLibrary",
    "get_script_library",
    "ScriptGenerator",
    "get_script_generator",
    "BotAccountPool",
    "get_bot_account_pool",
    "InteractionConfig",
    "InteractionConfigService",
    "get_interaction_config_service",
]
