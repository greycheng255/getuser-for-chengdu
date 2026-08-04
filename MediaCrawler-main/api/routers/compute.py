# -*- coding: utf-8 -*-
"""
算力计费 API 路由

端点：
  POST   /accounts            创建算力账户
  POST   /accounts/{account_id}/recharge  充值
  POST   /accounts/{account_id}/consume   消耗
  GET    /accounts/{account_id}/balance   查询余额
  GET    /accounts/{account_id}/transactions  交易记录
  GET    /costs               算力消耗标准
  POST   /convert/yuan-to-compute  元转算力
  POST   /convert/compute-to-yuan  算力转元
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user
from ..services.compute.compute_service import get_compute_service, COMPUTE_COSTS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compute", tags=["compute"])


class CreateAccountRequest(BaseModel):
    initial_balance: int = Field(0, ge=0, description="初始余额（算力币）")
    account_type: str = Field("normal", description="账户类型: normal/agent/vip")


class RechargeRequest(BaseModel):
    amount: int = Field(..., gt=0, description="充值金额（算力币）")
    description: str = Field("", description="充值说明")


class ConsumeRequest(BaseModel):
    resource_type: str = Field(..., description="资源类型: mixcut_video/digital_human/ai_reply 等")
    amount: Optional[int] = Field(None, ge=0, description="消耗量（不传则使用标准价格）")
    description: str = Field("", description="消耗说明")
    related_resource: str = Field("", description="关联资源ID")


@router.post("/accounts")
async def create_account(
    req: CreateAccountRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建算力账户"""
    svc = get_compute_service()
    result = await svc.create_account(
        owner_user_id=str(current_user["id"]),
        initial_balance=req.initial_balance,
        account_type=req.account_type,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "创建失败"))
    return result


@router.post("/accounts/{account_id}/recharge")
async def recharge(
    account_id: str,
    req: RechargeRequest,
    current_user: dict = Depends(get_current_user),
):
    """充值算力"""
    svc = get_compute_service()
    result = await svc.recharge(
        account_id=account_id,
        amount=req.amount,
        description=req.description,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "充值失败"))
    return result


@router.post("/accounts/{account_id}/consume")
async def consume(
    account_id: str,
    req: ConsumeRequest,
    current_user: dict = Depends(get_current_user),
):
    """消耗算力"""
    svc = get_compute_service()
    result = await svc.consume(
        account_id=account_id,
        resource_type=req.resource_type,
        amount=req.amount,
        description=req.description,
        related_resource=req.related_resource,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "消耗失败"))
    return result


@router.get("/accounts/{account_id}/balance")
async def get_balance(
    account_id: str,
    current_user: dict = Depends(get_current_user),
):
    """查询余额"""
    svc = get_compute_service()
    result = await svc.get_balance(account_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason", "查询失败"))
    return result


@router.get("/accounts/{account_id}/transactions")
async def get_transactions(
    account_id: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """获取交易记录"""
    svc = get_compute_service()
    txs = await svc.get_transactions(account_id, limit=limit)
    return {"transactions": txs, "total": len(txs)}


@router.get("/costs")
async def get_costs(current_user: dict = Depends(get_current_user)):
    """获取算力消耗标准"""
    return {"costs": COMPUTE_COSTS, "yuan_to_compute": 10000}


@router.post("/convert/yuan-to-compute")
async def yuan_to_compute(
    yuan: float = Query(..., gt=0, description="金额（元）"),
    current_user: dict = Depends(get_current_user),
):
    """元转算力币"""
    svc = get_compute_service()
    compute = await svc.yuan_to_compute(yuan)
    return {"yuan": yuan, "compute": compute}


@router.post("/convert/compute-to-yuan")
async def compute_to_yuan(
    compute: int = Query(..., gt=0, description="算力币数量"),
    current_user: dict = Depends(get_current_user),
):
    """算力币转元"""
    svc = get_compute_service()
    yuan = await svc.compute_to_yuan(compute)
    return {"compute": compute, "yuan": yuan}
