# -*- coding: utf-8 -*-
"""
私信自动回复服务（第七阶段）

对应 PRD 5.4 智能机器人互动 - 自动回复私信（P3）：
1. 私信监控：X/抖音/小红书私信列表定时检查
2. AI 自动回复：识别意图（咨询/投诉/合作/闲聊）+ 结合营销素材回复
3. 转人工触发：复杂问题/高价值客户

目录结构：
    dm/
    ├── __init__.py
    ├── dm_models.py       # 私信数据模型
    ├── dm_monitor.py      # 私信监控服务（多平台并行）
    └── dm_replier.py      # AI 私信回复（意图识别 + 转人工）
"""
from .dm_models import DirectMessage, MessageIntent, ConversationState
from .dm_monitor import DMMonitorService, get_dm_monitor
from .dm_replier import DMReplier, get_dm_replier
from .dm_platform_capabilities import (
    DMPlatformCapability,
    DMPlatformRegistry,
    get_dm_platform_registry,
    PLATFORM_CAPABILITIES,
)

__all__ = [
    "DirectMessage",
    "MessageIntent",
    "ConversationState",
    "DMMonitorService",
    "get_dm_monitor",
    "DMReplier",
    "get_dm_replier",
    "DMPlatformCapability",
    "DMPlatformRegistry",
    "get_dm_platform_registry",
    "PLATFORM_CAPABILITIES",
]
