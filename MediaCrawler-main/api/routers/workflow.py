# -*- coding: utf-8 -*-
"""
工作流 API 路由（P0：闭环引擎）

提供：
1. POST /api/workflow/start - 启动工作流
2. GET /api/workflow/{wf_id}/status - 获取工作流状态
3. GET /api/workflow/list - 列出所有工作流
4. POST /api/workflow/{wf_id}/resume - 恢复工作流
5. POST /api/workflow/{wf_id}/stages/{stage_id}/execute - 手动执行阶段
6. GET /api/workflow/stages - 获取工作流阶段定义
7. POST /api/workflow/auto-publish/daily - 每日自动发布
8. POST /api/workflow/kb-submission - 知识库提交策略
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.workflow import (
    get_auto_publish_workflow,
    get_kb_submission_service,
    get_workflow_engine,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow", tags=["workflow"])


class StartWorkflowRequest(BaseModel):
    brand_name: str = Field(..., description="品牌名称")
    industry: str = Field(default="", description="行业")
    keywords: list = Field(default_factory=list, description="关键词列表")
    platforms: list = Field(default_factory=list, description="目标平台列表")
    auto_run: bool = Field(default=True, description="是否自动运行")


class AutoPublishRequest(BaseModel):
    name: str = ""
    industry: str = ""
    products: str = ""
    target_audience: str = ""


@router.post("/start")
async def start_workflow(req: StartWorkflowRequest):
    """启动工作流"""
    engine = get_workflow_engine()
    try:
        return await engine.start_workflow(
            brand_name=req.brand_name,
            industry=req.industry,
            keywords=req.keywords,
            platforms=req.platforms,
            auto_run=req.auto_run,
        )
    except Exception as e:
        logger.exception("启动工作流失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{wf_id}/status")
async def get_status(wf_id: str):
    """获取工作流状态"""
    engine = get_workflow_engine()
    return await engine.get_status(wf_id)


@router.get("/list")
async def list_workflows(limit: int = Query(20, ge=1, le=100)):
    """列出所有工作流"""
    engine = get_workflow_engine()
    return await engine.list_workflows(limit)


@router.post("/{wf_id}/resume")
async def resume_workflow(wf_id: str):
    """恢复工作流（从当前阶段继续）"""
    engine = get_workflow_engine()
    return await engine.resume_workflow(wf_id)


@router.post("/{wf_id}/stages/{stage_id}/execute")
async def execute_stage(wf_id: str, stage_id: str):
    """手动执行单个阶段"""
    engine = get_workflow_engine()
    return await engine.execute_stage(wf_id, stage_id)


@router.get("/stages")
async def get_stages():
    """获取工作流阶段定义"""
    from ..services.workflow import WORKFLOW_STAGES
    return {"stages": WORKFLOW_STAGES}


@router.post("/auto-publish/daily")
async def auto_publish_daily(req: AutoPublishRequest):
    """每日自动发布流程"""
    workflow = get_auto_publish_workflow()
    try:
        brand_info = {
            "name": req.name,
            "industry": req.industry,
            "products": req.products,
            "target_audience": req.target_audience,
        }
        return await workflow.run_daily_publish(brand_info)
    except Exception as e:
        logger.exception("每日自动发布失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kb-submission")
async def kb_submission(req: AutoPublishRequest):
    """获取 AI 知识库提交策略"""
    svc = get_kb_submission_service()
    brand_info = {
        "name": req.name,
        "industry": req.industry,
        "products": req.products,
        "target_audience": req.target_audience,
    }
    return await svc.submit_to_ai_platforms(brand_info)
