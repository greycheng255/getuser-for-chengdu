# -*- coding: utf-8 -*-
"""
内容风控服务（第三阶段：内容风控增强）

对应 PRD 5.6 风控合规 - 内容风控：
1. 违规词检测（复用 publisher/content_adapter.py 的词库）
2. 查重检测（与历史发布内容相似度比对）
3. 发布前自动审核（拦截违规/重复内容）
4. 审核日志记录（PostgreSQL 持久化）
5. 舆情监控（迁移自 GEO sentiment_monitor_service.py）

目录结构：
    moderation/
    ├── __init__.py
    ├── moderation_service.py    # 内容审核 + 查重 + 日志
    ├── sentiment_monitor.py     # 舆情监控（迁移自 GEO）
    └── dedup.py                 # 文本相似度/查重算法
"""
from .moderation_service import (
    ModerationService,
    ModerationResult,
    ModerationDecision,
    get_moderation_service,
)
from .dedup import TextDedup, SimilarityResult
from .sentiment_monitor import (
    SentimentMonitorService,
    SentimentType,
    AlertLevel,
    get_sentiment_monitor,
)

__all__ = [
    "ModerationService",
    "ModerationResult",
    "ModerationDecision",
    "get_moderation_service",
    "TextDedup",
    "SimilarityResult",
    "SentimentMonitorService",
    "SentimentType",
    "AlertLevel",
    "get_sentiment_monitor",
]
