# -*- coding: utf-8 -*-
"""
品牌诊断服务（P1：品牌诊断）

对应 PRD 5.6 风控合规 - 品牌可见度分析、舆情风险评估。

迁移自 GEO-main brand_diagnosis_service.py：
- 适配 PostgreSQL 异步（原 SQLite）
- 适配 MediaCrawler 数据库引擎
- 保留 AI 平台收录检测、可见度盲点识别、舆情风险评估逻辑

目录结构：
    brand/
    ├── __init__.py
    └── brand_diagnosis_service.py
"""
from .brand_diagnosis_service import (
    BrandDiagnosisService,
    get_brand_diagnosis_service,
)

__all__ = [
    "BrandDiagnosisService",
    "get_brand_diagnosis_service",
]
