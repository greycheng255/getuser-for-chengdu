# -*- coding: utf-8 -*-
"""
套餐与计费 API 路由(v6.6 商业化)

提供:
- GET  /api/plans                套餐列表(公开,供前端展示)
- GET  /api/plans/me             当前用户套餐状态与用量
- POST /api/plans/upgrade        套餐升级(扣余额)
- POST /api/plans/recharge       余额充值
- GET  /api/plans/users          管理员:所有用户套餐概览
- PUT  /api/plans/users/{id}     管理员:手动调整用户套餐
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.auth import get_current_user, is_admin, require_admin
from ..services.plan import (
    PLAN_CONFIGS,
    get_user_plan_info,
    upgrade_plan,
    recharge_balance,
    list_all_plans,
    reset_usage_period,
    record_usage,
)

router = APIRouter(prefix="/plans", tags=["plans"])


# ============ 请求模型 ============

class UpgradePlanRequest(BaseModel):
    plan_type: str = Field(..., description="目标套餐: free / basic / pro / enterprise")
    duration: str = Field("monthly", description="订阅周期: monthly / yearly")


class RechargeRequest(BaseModel):
    amount_yuan: float = Field(..., gt=0, description="充值金额(元)")


class AdminUpdateUserPlanRequest(BaseModel):
    plan_type: Optional[str] = None
    plan_expires_ts: Optional[int] = None
    balance: Optional[int] = None  # 单位:分
    reset_usage: bool = False


# ============ 公开接口 ============

@router.get("")
async def list_plans():
    """套餐列表(公开,无需登录,供前端定价页展示)"""
    return {"plans": list_all_plans()}


# ============ 用户接口 ============

@router.get("/me")
async def get_my_plan(current_user: dict = Depends(get_current_user)):
    """获取当前用户套餐状态、配额与用量"""
    info = get_user_plan_info(current_user)
    return {
        "success": True,
        "plan": info,
    }


@router.post("/upgrade")
async def upgrade_my_plan(
    req: UpgradePlanRequest,
    current_user: dict = Depends(get_current_user),
):
    """升级套餐(从余额扣费)

    - 月订阅:30 天有效
    - 年订阅:365 天有效
    - 免费套餐:永久有效,不扣费
    """
    if req.plan_type not in PLAN_CONFIGS:
        raise HTTPException(status_code=400, detail=f"未知套餐: {req.plan_type}")

    if req.duration not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="duration 必须为 monthly 或 yearly")

    result = await upgrade_plan(
        user_id=current_user["id"],
        new_plan_type=req.plan_type,
        duration=req.duration,
        admin_override=False,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/recharge")
async def recharge_my_balance(
    req: RechargeRequest,
    current_user: dict = Depends(get_current_user),
):
    """余额充值(元转分)"""
    amount_cents = int(req.amount_yuan * 100)
    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="充值金额必须大于 0")
    result = await recharge_balance(current_user["id"], amount_cents)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ============ 管理员接口 ============

@router.get("/users")
async def list_users_plans(admin: dict = Depends(require_admin)):
    """管理员:查看所有用户套餐状态(复用 auth.list_all_users)"""
    from ..services.auth import list_all_users
    users = await list_all_users()
    # 仅返回套餐相关字段
    summaries = []
    for u in users:
        info = get_user_plan_info(u)
        summaries.append({
            "id": u["id"],
            "username": u["username"],
            "nickname": u["nickname"],
            "role": u["role"],
            "status": u["status"],
            "plan_type": info["plan_type"],
            "plan_name": info["plan_name"],
            "is_active": info["is_active"],
            "expires_ts": info["expires_ts"],
            "balance": info["balance"],
            "balance_yuan": (info["balance"] or 0) / 100,
            "usage_notes_count": info["usage_notes_count"],
            "usage_comments_count": info["usage_comments_count"],
            "usage_leads_count": info["usage_leads_count"],
        })
    return {"users": summaries, "total": len(summaries)}


@router.put("/users/{user_id}")
async def admin_update_user_plan(
    user_id: int,
    req: AdminUpdateUserPlanRequest,
    admin: dict = Depends(require_admin),
):
    """管理员:手动调整用户套餐/余额/有效期

    - 可直接设置 plan_type、plan_expires_ts、balance
    - reset_usage=true 时重置用户用量周期
    """
    from ..services.auth import update_user, get_user_by_id

    target = await get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    updates = {}
    if req.plan_type is not None:
        if req.plan_type not in PLAN_CONFIGS:
            raise HTTPException(status_code=400, detail=f"未知套餐: {req.plan_type}")
        updates["plan_type"] = req.plan_type
    if req.plan_expires_ts is not None:
        updates["plan_expires_ts"] = req.plan_expires_ts
    if req.balance is not None:
        updates["balance"] = req.balance

    if updates:
        await update_user(user_id, **updates)

    if req.reset_usage:
        await reset_usage_period(user_id)

    updated = await get_user_by_id(user_id)
    return {
        "success": True,
        "message": "用户套餐已更新",
        "user": updated,
    }
