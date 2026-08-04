# -*- coding: utf-8 -*-
"""
效果监控服务（P1：效果监控）

对应 PRD 5.5 数据统计 - 搜索排名、AI 引用、流量分析。

迁移自 GEO-main monitoring_service.py：
- 适配 PostgreSQL 异步（原 psycopg2 同步）
- 适配 MediaCrawler 数据库引擎
- 保留搜索排名爬虫、AI 引用分析、批量检测、流量统计逻辑

目录结构：
    monitoring/
    ├── __init__.py
    └── monitoring_service.py
"""
from .monitoring_service import (
    MonitoringService,
    get_monitoring_service,
)

__all__ = [
    "MonitoringService",
    "get_monitoring_service",
]
