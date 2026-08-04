# -*- coding: utf-8 -*-
"""
关键词研究服务（P1：关键词研究）

对应 PRD 5.1 热点信息搜集 - 关键词挖掘/分析/趋势追踪。

迁移自 GEO-main keyword_research_service.py：
- 适配 PostgreSQL 异步（原 SQLite）
- 适配 MediaCrawler 数据库引擎
- 保留关键词挖掘/分析/推荐/趋势追踪逻辑

目录结构：
    keyword/
    ├── __init__.py
    └── keyword_research_service.py
"""
from .keyword_research_service import (
    KeywordResearchService,
    get_keyword_research_service,
)

__all__ = [
    "KeywordResearchService",
    "get_keyword_research_service",
]
