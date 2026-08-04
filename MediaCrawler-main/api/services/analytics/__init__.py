# -*- coding: utf-8 -*-
"""
数据统计服务（第五阶段：数据统计 + 报表）

对应 PRD 5.5 数据统计：
1. 全链路数据统计：热点抓取量/视频生成量/发布量/发布成功率/互动量
2. 数据可视化：平台维度/时间维度/内容维度
3. 报表导出：Excel/CSV 导出

迁移自 GEO-main/geo_system/backend/analytics_service.py，适配：
1. 异步 + MediaCrawler 现有数据表（sent_comments / publisher_accounts /
   scheduled_publish_tasks / moderation_log / sentiment_items）
2. 不再单建 metrics 表，改为从业务表实时聚合

目录结构：
    analytics/
    ├── __init__.py
    ├── analytics_service.py   # 多源数据聚合统计
    └── export_service.py      # 报表导出（CSV/Excel）
"""
from .analytics_service import AnalyticsService, get_analytics_service
from .export_service import ExportService, get_export_service
from .external_metrics import ExternalMetricsCollector, get_external_metrics_collector
from .viral_review import ViralDetector, ViralReviewService, get_viral_review_service
from .interaction_analytics import (
    InteractionAnalyticsService,
    get_interaction_analytics,
    InteractionStat,
    AnomalyInteraction,
)

__all__ = [
    "AnalyticsService",
    "get_analytics_service",
    "ExportService",
    "get_export_service",
    "ExternalMetricsCollector",
    "get_external_metrics_collector",
    "ViralDetector",
    "ViralReviewService",
    "get_viral_review_service",
    "InteractionAnalyticsService",
    "get_interaction_analytics",
    "InteractionStat",
    "AnomalyInteraction",
]
