# -*- coding: utf-8 -*-
"""
白名单同行监控 API 路由

端点：
  POST   /accounts              添加同行监控
  GET    /accounts              列出同行
  DELETE /accounts/{account_id} 删除同行
  POST   /accounts/{account_id}/scan  立即扫描
  GET    /scan-records          扫描记录
  GET    /stats                 统计信息
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user, is_admin
from ..services.competitor.competitor_monitor_service import get_competitor_monitor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/competitor-monitor", tags=["competitor-monitor"])


class AddCompetitorRequest(BaseModel):
    platform: str = Field(..., description="平台: douyin/xiaohongshu/kuaishou/video_number")
    account_url: str = Field(..., description="同行账号URL或ID")
    account_name: str = Field("", description="同行账号名称")
    scan_range: int = Field(10, ge=1, le=50, description="扫描最新N条视频")
    comment_days: int = Field(7, ge=1, le=30, description="只看近N天的评论")


@router.post("/accounts")
async def add_competitor(
    req: AddCompetitorRequest,
    current_user: dict = Depends(get_current_user),
):
    """添加同行监控账号"""
    svc = get_competitor_monitor_service()
    result = await svc.add_competitor(
        platform=req.platform,
        account_url=req.account_url,
        account_name=req.account_name,
        scan_range=req.scan_range,
        comment_days=req.comment_days,
        owner_user_id=str(current_user["id"]),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "添加失败"))
    return result


@router.get("/accounts")
async def list_competitors(
    platform: Optional[str] = Query(None),
    status: str = Query("active"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """列出同行监控账号"""
    svc = get_competitor_monitor_service()
    return await svc.list_competitors(
        platform=platform,
        status=status,
        owner_user_id=str(current_user["id"]),
        page=page,
        page_size=page_size,
    )


@router.delete("/accounts/{account_id}")
async def remove_competitor(
    account_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除同行监控"""
    svc = get_competitor_monitor_service()
    ok = await svc.remove_competitor(account_id)
    if not ok:
        raise HTTPException(status_code=400, detail="删除失败")
    return {"ok": True}


@router.post("/accounts/{account_id}/scan")
async def scan_competitor(
    account_id: str,
    current_user: dict = Depends(get_current_user),
):
    """立即扫描同行账号"""
    svc = get_competitor_monitor_service()
    result = await svc.scan_competitor(account_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "扫描失败"))
    return result


@router.get("/scan-records")
async def get_scan_records(
    account_id: Optional[str] = Query(None),
    is_lead: Optional[bool] = Query(None),
    processed: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """获取扫描记录"""
    svc = get_competitor_monitor_service()
    return await svc.get_scan_records(
        account_id=account_id,
        is_lead=is_lead,
        processed=processed,
        page=page,
        page_size=page_size,
    )


@router.get("/stats")
async def get_stats(current_user: dict = Depends(get_current_user)):
    """获取统计信息"""
    svc = get_competitor_monitor_service()
    return await svc.get_stats(owner_user_id=str(current_user["id"]))
