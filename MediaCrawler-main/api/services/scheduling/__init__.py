# -*- coding: utf-8 -*-
"""
发布策略服务（第四阶段：发布策略 + 营销植入）

对应 PRD 5.3 多平台分发 - 发布策略：
1. 定时发布（scheduled_at + 后台调度器）
2. 错峰发布（按平台活跃时段自动选择最佳发布时间）
3. 频次控制（单账号每日上限，复用 account_service）
4. 发布队列 / 内容日历（迁移自 GEO content_calendar_service.py）

目录结构：
    scheduling/
    ├── __init__.py
    ├── publish_scheduler.py     # 定时发布调度器 + 错峰逻辑
    └── content_calendar.py      # 内容日历（迁移自 GEO）
"""
from .publish_scheduler import (
    PublishScheduler,
    ScheduledTask,
    PlatformPeakHours,
    get_publish_scheduler,
)
from .content_calendar import (
    ContentCalendarService,
    ContentItem,
    ContentStatus,
    get_content_calendar,
)

__all__ = [
    "PublishScheduler",
    "ScheduledTask",
    "PlatformPeakHours",
    "get_publish_scheduler",
    "ContentCalendarService",
    "ContentItem",
    "ContentStatus",
    "get_content_calendar",
]
