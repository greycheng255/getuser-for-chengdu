# -*- coding: utf-8 -*-
"""
客户分配调度 API 路由

端点：
  POST   /plans                          创建分配计划（含账号配置 + 客户筛选）
  GET    /plans                          列出计划
  GET    /plans/{plan_id}                计划详情（含账号 + 进度）
  DELETE /plans/{plan_id}                删除计划
  GET    /plans/{plan_id}/accounts       账号列表
  GET    /plans/{plan_id}/records        客户分配记录（支持 account_idx/status 筛选）
  POST   /plans/{plan_id}/next           获取账号 N 的下一批待发客户（核心调度）
  POST   /plans/{plan_id}/mark-replied   标记客户已回复（去重）
  POST   /plans/{plan_id}/batch-mark     批量标记已回复
  GET    /plans/{plan_id}/progress       计划进度统计
  GET    /preview-customers              预览符合条件的客户数（创建计划前用）
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..services.auth import get_current_user, is_admin
from ..services.dispatch.customer_dispatch_service import get_customer_dispatch_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/customer-dispatch", tags=["customer-dispatch"])


# ============ 请求模型 ============

class AccountConfig(BaseModel):
    account_alias: str = Field("", description="账号昵称，如 账号1/小王")
    cookie_id: str = Field("", description="关联的 cookie/账号 ID")
    batch_size: int = Field(20, ge=1, le=1000, description="该账号负责的客户数")


class CustomRange(BaseModel):
    account_idx: int = Field(..., ge=1, description="账号序号（1-based，对应 accounts 列表顺序）")
    range_start: int = Field(..., ge=1, description="区间起始序号（1-based）")
    range_end: int = Field(..., ge=1, description="区间结束序号（1-based）")


class CreatePlanRequest(BaseModel):
    name: str = Field(..., description="计划名称")
    platform: str = Field("douyin", description="平台：douyin/xhs/ks/bili/wb")
    filter_keywords: str = Field("", description="客户筛选关键词")
    min_lead_score: int = Field(0, ge=0, le=100, description="最低线索评分")
    accounts: List[AccountConfig] = Field(..., min_items=1, description="账号配置列表")
    customer_lead_ids: Optional[List[int]] = Field(
        None, description="显式指定的客户ID列表（不传则按筛选条件查）"
    )
    custom_ranges: Optional[List[CustomRange]] = Field(
        None,
        description="手动指定区间（支持重叠）。不传则按 batch_size 比例自动分配。"
        "如[{account_idx:1,range_start:1,range_end:100},{account_idx:2,range_start:50,range_end:150}]",
    )


class GetNextRequest(BaseModel):
    account_idx: int = Field(..., ge=1, description="账号序号（1-based）")
    batch_size: int = Field(20, ge=1, le=200, description="本批次大小")


class MarkRepliedRequest(BaseModel):
    customer_lead_id: int = Field(..., description="客户 lead ID")
    account_idx: int = Field(..., ge=1, description="回复的账号序号")
    contact_log: str = Field("", description="联系记录/备注")


class BatchMarkRepliedRequest(BaseModel):
    customer_lead_ids: List[int] = Field(..., min_items=1, description="客户 lead ID 列表")
    account_idx: int = Field(..., ge=1, description="回复的账号序号")


# ============ 端点 ============

@router.get("/preview-customers")
async def preview_customers(
    platform: str = "douyin",
    filter_keywords: str = "",
    min_lead_score: int = 0,
    current_user: dict = Depends(get_current_user),
):
    """预览符合条件的客户数（创建计划前用）"""
    svc = get_customer_dispatch_service()
    await svc.ensure_table()
    # 复用 service 内部方法
    lead_ids = await svc._fetch_customer_leads(
        platform=platform, filter_keywords=filter_keywords,
        min_lead_score=min_lead_score, owner_user_id=str(current_user["id"]),
    )
    return {
        "count": len(lead_ids),
        "platform": platform,
        "filter_keywords": filter_keywords,
        "min_lead_score": min_lead_score,
    }


@router.post("/plans")
async def create_plan(
    req: CreatePlanRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建分配计划 + 预分配客户到账号"""
    svc = get_customer_dispatch_service()
    result = await svc.create_plan(
        name=req.name, platform=req.platform,
        filter_keywords=req.filter_keywords,
        min_lead_score=req.min_lead_score,
        account_configs=[a.dict() for a in req.accounts],
        owner_user_id=str(current_user["id"]),
        customer_lead_ids=req.customer_lead_ids,
        custom_ranges=[r.dict() for r in req.custom_ranges] if req.custom_ranges else None,
    )
    if not result.get("created"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("reason", "创建失败"),
        )
    return result


@router.get("/plans")
async def list_plans(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """列出计划"""
    svc = get_customer_dispatch_service()
    result = await svc.list_plans(
        owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
        page=page, page_size=page_size,
    )
    return result


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: str,
    current_user: dict = Depends(get_current_user),
):
    """计划详情"""
    svc = get_customer_dispatch_service()
    plan = await svc.get_plan(
        plan_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="计划不存在")
    return plan


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除计划"""
    svc = get_customer_dispatch_service()
    ok = await svc.delete_plan(
        plan_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="计划不存在")
    return {"success": True, "message": "ok"}


@router.get("/plans/{plan_id}/accounts")
async def list_accounts(
    plan_id: str,
    current_user: dict = Depends(get_current_user),
):
    """账号列表"""
    svc = get_customer_dispatch_service()
    # 校验归属
    plan = await svc.get_plan(
        plan_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="计划不存在")
    return plan.get("accounts", [])


@router.get("/plans/{plan_id}/records")
async def list_records(
    plan_id: str,
    account_idx: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """客户分配记录"""
    svc = get_customer_dispatch_service()
    result = await svc.list_records(
        plan_id, account_idx=account_idx, status=status_filter,
        page=page, page_size=page_size,
        owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    return result


@router.post("/plans/{plan_id}/next")
async def get_next(
    plan_id: str,
    req: GetNextRequest,
    current_user: dict = Depends(get_current_user),
):
    """获取账号 N 的下一批待发客户（核心调度）"""
    svc = get_customer_dispatch_service()
    result = await svc.get_next_for_account(
        plan_id, req.account_idx, req.batch_size,
        owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("reason", "获取失败"),
        )
    return result


@router.post("/plans/{plan_id}/mark-replied")
async def mark_replied(
    plan_id: str,
    req: MarkRepliedRequest,
    current_user: dict = Depends(get_current_user),
):
    """标记客户已回复（去重核心操作）"""
    svc = get_customer_dispatch_service()
    ok = await svc.mark_replied(
        plan_id, req.customer_lead_id, req.account_idx, req.contact_log,
        owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="标记失败（客户不存在或已回复）",
        )
    return {"success": True, "message": "已标记为已回复"}


@router.post("/plans/{plan_id}/batch-mark")
async def batch_mark_replied(
    plan_id: str,
    req: BatchMarkRepliedRequest,
    current_user: dict = Depends(get_current_user),
):
    """批量标记已回复"""
    svc = get_customer_dispatch_service()
    success = await svc.batch_mark_replied(
        plan_id, req.customer_lead_ids, req.account_idx,
        owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    return {"success": success, "total": len(req.customer_lead_ids), "failed": len(req.customer_lead_ids) - success}


@router.get("/plans/{plan_id}/progress")
async def get_progress(
    plan_id: str,
    current_user: dict = Depends(get_current_user),
):
    """计划进度统计"""
    svc = get_customer_dispatch_service()
    # 校验归属
    plan = await svc.get_plan(
        plan_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="计划不存在")
    progress = await svc.get_plan_progress(plan_id)
    return progress
