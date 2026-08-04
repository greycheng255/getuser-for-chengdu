# -*- coding: utf-8 -*-
"""
AI 自动驾驶舱 API 路由

端点：
  POST   /generate          输入目标，AI 生成获客计划
  GET    /plans             列出计划
  GET    /plans/{plan_id}   计划详情
  PUT    /plans/{plan_id}/status  更新计划状态
  POST   /plans/{plan_id}/execute  执行计划
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user, is_admin
from ..services.ai_pilot.ai_pilot_service import get_ai_pilot_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-pilot", tags=["ai-pilot"])


class GeneratePlanRequest(BaseModel):
    user_goal: str = Field(..., description="获客目标（自然语言），如'帮我找50个企业服务客户并加到微信'")


class UpdatePlanStatusRequest(BaseModel):
    status: str = Field(..., description="状态: draft/active/paused/completed")


@router.post("/generate")
async def generate_plan(
    req: GeneratePlanRequest,
    current_user: dict = Depends(get_current_user),
):
    """输入目标，AI 自动生成获客计划"""
    svc = get_ai_pilot_service()
    result = await svc.generate_plan(
        user_goal=req.user_goal,
        owner_user_id=str(current_user["id"]),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "生成失败"))
    return result


@router.get("/plans")
async def list_plans(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """列出获客计划"""
    svc = get_ai_pilot_service()
    return await svc.list_plans(
        owner_user_id=str(current_user["id"]),
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: str,
    current_user: dict = Depends(get_current_user),
):
    """计划详情"""
    svc = get_ai_pilot_service()
    plan = await svc.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    return plan


@router.put("/plans/{plan_id}/status")
async def update_plan_status(
    plan_id: str,
    req: UpdatePlanStatusRequest,
    current_user: dict = Depends(get_current_user),
):
    """更新计划状态"""
    svc = get_ai_pilot_service()
    ok = await svc.update_plan_status(plan_id, req.status)
    if not ok:
        raise HTTPException(status_code=400, detail="更新失败")
    return {"ok": True}


@router.post("/plans/{plan_id}/execute")
async def execute_plan(
    plan_id: str,
    current_user: dict = Depends(get_current_user),
):
    """执行计划：拆解为子任务"""
    svc = get_ai_pilot_service()
    result = await svc.execute_plan(plan_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "执行失败"))
    return result
