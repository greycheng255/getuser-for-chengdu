# -*- coding: utf-8 -*-
"""
X Twitter 工作台 - 全自动模式路由

提供 Web UI 一键启动/停止/查询全自动模式:
- POST /x-workbench/auto-mode/start   启动全自动模式
- POST /x-workbench/auto-mode/stop    停止全自动模式
- GET  /x-workbench/auto-mode/status  查询状态

全自动模式 = 爬热点 → AI 生成评论 → 真实发送 → 监控回复 → AI 自动回复
"""
from fastapi import APIRouter, Depends

from api.services.auth import require_admin, get_current_user
from api.services.auto_mode_service import (
    start_auto_mode,
    stop_auto_mode,
    get_status,
)


router = APIRouter(
    prefix="/x-workbench/auto-mode",
    tags=["x-twitter-workbench"],
)


@router.post("/start", dependencies=[Depends(require_admin)])
async def start():
    """启动全自动模式(仅管理员,幂等,已在运行则直接返回)"""
    ok = await start_auto_mode()
    if not ok:
        return {"success": False, "message": "启动失败,请检查后端日志"}
    return {"success": True, "message": "全自动模式已启动"}


@router.post("/stop", dependencies=[Depends(require_admin)])
async def stop():
    """停止全自动模式(仅管理员)"""
    await stop_auto_mode()
    return {"success": True, "message": "全自动模式已停止"}


@router.get("/status", dependencies=[Depends(get_current_user)])
async def status():
    """查询全自动模式状态(所有登录用户可查)"""
    return get_status()
