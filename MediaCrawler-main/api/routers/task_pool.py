# -*- coding: utf-8 -*-
"""
任务池 API 路由

端点：
  POST   /tasks              添加客户到任务池
  GET    /tasks              列出待触达任务
  POST   /tasks/{task_id}/advance  推进触达阶段
  POST   /tasks/{task_id}/replied   标记已回复
  GET    /stats              任务池统计
  POST   /scheduler/run      手动触发一轮触达调度
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user, is_admin
from ..services.task_pool.task_pool_service import get_task_pool_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/task-pool", tags=["task-pool"])


class AddTaskRequest(BaseModel):
    source: str = Field(..., description="来源: comment_monitor/competitor/keyword/local_life")
    platform: str = Field(..., description="平台: douyin/xiaohongshu/kuaishou/video_number/bilibili")
    customer_id: str = Field(..., description="客户ID")
    customer_name: str = Field("", description="客户名称")
    customer_url: str = Field("", description="客户主页URL")
    comment_text: str = Field("", description="评论内容")
    video_id: str = Field("", description="视频ID")
    video_title: str = Field("", description="视频标题")
    intent_type: str = Field("", description="意向类型")
    lead_score: int = Field(0, ge=0, le=100, description="线索评分")
    matched_keywords: str = Field("", description="匹配关键词")


class AdvanceStageRequest(BaseModel):
    new_stage: int = Field(..., ge=1, le=4, description="目标阶段: 1=关注,2=私信,3=评论,4=二触私信")


@router.post("/tasks")
async def add_task(
    req: AddTaskRequest,
    current_user: dict = Depends(get_current_user),
):
    """添加客户到任务池"""
    svc = get_task_pool_service()
    result = await svc.add_to_pool(
        source=req.source,
        platform=req.platform,
        customer_id=req.customer_id,
        customer_name=req.customer_name,
        customer_url=req.customer_url,
        comment_text=req.comment_text,
        video_id=req.video_id,
        video_title=req.video_title,
        intent_type=req.intent_type,
        lead_score=req.lead_score,
        matched_keywords=req.matched_keywords,
        owner_user_id=str(current_user["id"]),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "添加失败"))
    return result


@router.get("/tasks")
async def list_tasks(
    platform: Optional[str] = Query(None),
    stage: Optional[int] = Query(None, ge=1, le=4),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """列出待触达任务"""
    svc = get_task_pool_service()
    tasks = await svc.get_next_touch_tasks(
        platform=platform,
        stage=stage,
        limit=limit,
    )
    return {"tasks": tasks, "total": len(tasks)}


@router.post("/tasks/{task_id}/advance")
async def advance_stage(
    task_id: str,
    req: AdvanceStageRequest,
    current_user: dict = Depends(get_current_user),
):
    """推进触达阶段"""
    svc = get_task_pool_service()
    ok = await svc.advance_stage(task_id, req.new_stage)
    if not ok:
        raise HTTPException(status_code=400, detail="推进失败")
    return {"ok": True}


@router.post("/tasks/{task_id}/replied")
async def mark_replied(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """标记客户已回复"""
    svc = get_task_pool_service()
    ok = await svc.mark_replied(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="标记失败")
    return {"ok": True}


@router.get("/stats")
async def get_stats(current_user: dict = Depends(get_current_user)):
    """任务池统计"""
    svc = get_task_pool_service()
    return await svc.get_pool_stats(owner_user_id=str(current_user["id"]))


@router.post("/scheduler/run")
async def run_scheduler(current_user: dict = Depends(get_current_user)):
    """手动触发一轮触达调度"""
    svc = get_task_pool_service()
    result = await svc.run_touch_scheduler()
    return result
