# -*- coding: utf-8 -*-
"""
工作流引擎服务（P0：闭环引擎）

对应 PRD 工作流引擎 - 多模块协作闭环编排。

迁移自 GEO-main workflow_engine.py + auto_publish_workflow.py：
- 适配 PostgreSQL 异步（原 SQLite/内存）
- 集成 MediaCrawler 已迁移的 publisher/interactor/moderation/scheduling/analytics/ai
- 工作流阶段：热点搜集 → 内容生成 → 视频生成 → 内容审核 → 多平台分发 → 互动监控 → 数据统计

目录结构：
    workflow/
    ├── __init__.py
    ├── workflow_engine.py        # 核心闭环工作流引擎
    └── auto_publish_workflow.py  # 自动化发布工作流
"""
from .workflow_engine import (
    WORKFLOW_STAGES,
    WorkflowEngine,
    get_workflow_engine,
)
from .auto_publish_workflow import (
    AutoPublishWorkflow,
    KnowledgeBaseSubmission,
    get_auto_publish_workflow,
    get_kb_submission_service,
)

__all__ = [
    "WORKFLOW_STAGES",
    "WorkflowEngine",
    "get_workflow_engine",
    "AutoPublishWorkflow",
    "KnowledgeBaseSubmission",
    "get_auto_publish_workflow",
    "get_kb_submission_service",
]
