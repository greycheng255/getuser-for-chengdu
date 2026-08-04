# -*- coding: utf-8 -*-
"""
设备管理 API 路由

端点：
  POST   /devices             注册设备
  POST   /devices/{device_id}/heartbeat  设备心跳
  GET    /devices             列出设备
  GET    /devices/{device_id} 设备详情
  PUT    /devices/{device_id}/features  更新设备功能
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user
from ..services.device.device_service import get_device_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/device", tags=["device"])


class RegisterDeviceRequest(BaseModel):
    device_name: str = Field(..., description="设备名称")
    device_type: str = Field(..., description="设备类型: phone/pc/tablet")
    platform: str = Field("", description="平台: douyin/xiaohongshu/kuaishou/video_number")
    account_bound: str = Field("", description="绑定的账号")
    enabled_features: Optional[List[str]] = Field(None, description="启用的功能列表")


class HeartbeatResponse(BaseModel):
    ok: bool
    timestamp: int


class UpdateFeaturesRequest(BaseModel):
    enabled_features: List[str] = Field(..., description="启用的功能列表")


@router.post("/devices")
async def register_device(
    req: RegisterDeviceRequest,
    current_user: dict = Depends(get_current_user),
):
    """注册设备"""
    svc = get_device_service()
    result = await svc.register_device(
        device_name=req.device_name,
        device_type=req.device_type,
        platform=req.platform,
        account_bound=req.account_bound,
        enabled_features=req.enabled_features,
        owner_user_id=str(current_user["id"]),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "注册失败"))
    return result


@router.post("/devices/{device_id}/heartbeat")
async def heartbeat(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    """设备心跳"""
    svc = get_device_service()
    result = await svc.heartbeat(device_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "心跳失败"))
    return result


@router.get("/devices")
async def list_devices(current_user: dict = Depends(get_current_user)):
    """列出设备"""
    svc = get_device_service()
    devices = await svc.list_devices(owner_user_id=str(current_user["id"]))
    return {"devices": devices, "total": len(devices)}


@router.get("/devices/{device_id}")
async def get_device(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取设备详情"""
    svc = get_device_service()
    device = await svc.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


@router.put("/devices/{device_id}/features")
async def update_features(
    device_id: str,
    req: UpdateFeaturesRequest,
    current_user: dict = Depends(get_current_user),
):
    """更新设备功能"""
    svc = get_device_service()
    ok = await svc.update_device_features(device_id, req.enabled_features)
    if not ok:
        raise HTTPException(status_code=400, detail="更新失败")
    return {"ok": True}
