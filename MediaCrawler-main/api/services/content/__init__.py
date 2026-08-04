# -*- coding: utf-8 -*-
"""
内容模板服务（P0：内容模板）

对应 PRD 5.2 视频智能生成 - 内容参数配置 / 营销文案标准化生产。

迁移自 GEO-main content_template_service.py：
- 纯内存模板系统，无数据库依赖
- 提供 6 类内置模板（测评/科普/推荐/对比/指南/案例）
- 支持 AI 提示词生成、自定义模板

目录结构：
    content/
    ├── __init__.py
    └── content_template_service.py
"""
from .content_template_service import (
    ContentTemplate,
    ContentTemplateService,
    ContentTone,
    TemplateType,
    get_content_template_service,
)

__all__ = [
    "ContentTemplate",
    "ContentTemplateService",
    "ContentTone",
    "TemplateType",
    "get_content_template_service",
]
