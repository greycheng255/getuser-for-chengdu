# -*- coding: utf-8 -*-
"""
系统配置 API 路由(阶段三 P2-7)

提供评分规则 / 通知设置等 KV 配置的后端持久化接口:
- GET    /api/system-config/{key}      读取配置(可选 user_id 参数)
- POST   /api/system-config/{key}      写入配置(可选 user_id 参数)
- DELETE /api/system-config/{key}      删除配置(可选 user_id 参数)
- GET    /api/system-config            列出配置(可选 config_type / user_id 参数)
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user
from ..services.system_config import get_system_config_service

router = APIRouter(prefix="/system-config", tags=["system-config"])


class SetConfigRequest(BaseModel):
    """写入配置请求"""
    value: Any = Field(..., description="配置值(任意可 JSON 序列化的对象)")
    config_type: str = Field(default="", description="配置类型(如 scoring / notification)")
    user_id: Optional[int] = Field(default=None, description="用户 ID,空=全局配置")


@router.get("/{key}")
async def get_config(
    key: str,
    user_id: Optional[int] = Query(None, description="用户 ID,空=全局配置"),
    current_user: dict = Depends(get_current_user),
):
    """读取配置值(自动 JSON 反序列化)"""
    svc = get_system_config_service()
    value = await svc.get_config(key, user_id=user_id)
    if value is None:
        return {"key": key, "value": None, "found": False}
    return {"key": key, "value": value, "found": True}


@router.post("/{key}")
async def set_config(
    key: str,
    req: SetConfigRequest,
    current_user: dict = Depends(get_current_user),
):
    """写入配置值(UPSERT,自动 JSON 序列化)"""
    # 非 admin 用户只能写自己的配置(user_id 必须为当前用户 ID)
    target_user_id = req.user_id
    if current_user.get("role") != "admin":
        target_user_id = current_user.get("id")
    svc = get_system_config_service()
    ok = await svc.set_config(
        key,
        req.value,
        user_id=target_user_id,
        config_type=req.config_type,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="配置写入失败")
    return {"message": "配置已保存", "key": key}


@router.delete("/{key}")
async def delete_config(
    key: str,
    user_id: Optional[int] = Query(None, description="用户 ID,空=全局配置"),
    current_user: dict = Depends(get_current_user),
):
    """删除配置"""
    # 非 admin 用户只能删自己的配置
    target_user_id = user_id
    if current_user.get("role") != "admin":
        target_user_id = current_user.get("id")
    svc = get_system_config_service()
    ok = await svc.delete_config(key, user_id=target_user_id)
    if not ok:
        return {"message": "配置不存在或已删除", "deleted": False}
    return {"message": "配置已删除", "deleted": True}


@router.get("")
async def list_configs(
    config_type: Optional[str] = Query(None, description="配置类型筛选"),
    user_id: Optional[int] = Query(None, description="用户 ID,空=全局配置"),
    current_user: dict = Depends(get_current_user),
):
    """列出配置(可按 config_type / user_id 筛选)"""
    svc = get_system_config_service()
    # 非 admin 用户只能查看自己的配置
    target_user_id = user_id
    if current_user.get("role") != "admin":
        target_user_id = current_user.get("id")
    items = await svc.list_configs(config_type=config_type, user_id=target_user_id)
    return {"items": items, "total": len(items)}
