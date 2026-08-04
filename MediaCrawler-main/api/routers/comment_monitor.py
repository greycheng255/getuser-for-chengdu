# -*- coding: utf-8 -*-
"""
评论监控 API 路由

端点：
  POST   /tasks              创建监控任务
  GET    /tasks              列出任务（platform/status/monitor_type/page/page_size）
  GET    /tasks/{task_id}    任务详情
  PUT    /tasks/{task_id}    更新任务
  DELETE /tasks/{task_id}    删除任务
  POST   /tasks/{task_id}/start   启动监控
  POST   /tasks/{task_id}/stop    停止监控
  POST   /tasks/{task_id}/check-now  立即触发一次检查
  GET    /tasks/{task_id}/records  查看抓取记录（分页）
  GET    /tasks/{task_id}/stats    任务统计
  GET    /platforms               支持的平台列表
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..services.auth import get_current_user, is_admin
from ..services.comment_monitor.comment_monitor_service import get_comment_monitor_service
from ..services.comment_monitor.platform_comment_fetcher import CommentFetcherFactory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/comment-monitor", tags=["comment-monitor"])


# ============ 请求模型 ============

class CreateTaskRequest(BaseModel):
    platform: str = Field(..., description="平台: douyin/xhs/ks/bili/wb")
    monitor_type: str = Field("video", description="监控类型: account / video")
    target_id: str = Field(..., description="video: 视频URL或ID；account: 用户sec_uid")
    target_nickname: str = Field("", description="监控目标昵称（便于展示）")
    keywords: str = Field("", description="筛选关键词，逗号分隔")
    enable_auto_reply: bool = Field(False, description="AI自动回复")
    enable_lead_extract: bool = Field(True, description="意向客户识别")
    check_interval: int = Field(300, ge=60, le=86400, description="检查间隔(秒)")
    max_comments_per_check: int = Field(100, ge=10, le=500, description="单次抓取上限")


class UpdateTaskRequest(BaseModel):
    target_nickname: Optional[str] = None
    keywords: Optional[str] = None
    enable_auto_reply: Optional[bool] = None
    enable_lead_extract: Optional[bool] = None
    check_interval: Optional[int] = Field(None, ge=60, le=86400)
    max_comments_per_check: Optional[int] = Field(None, ge=10, le=500)
    status: Optional[str] = None  # 允许手动改 paused


# ============ 端点 ============

@router.get("/platforms")
async def list_supported_platforms(
    current_user: dict = Depends(get_current_user),
):
    """支持的监控平台列表"""
    return {
        "platforms": CommentFetcherFactory.supported_platforms(),
        "monitor_types": [
            {"value": "video", "label": "爆款视频评论"},
            {"value": "account", "label": "同行账号评论"},
        ],
    }


@router.post("/tasks")
async def create_task(
    req: CreateTaskRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建监控任务"""
    # 校验平台
    if req.platform not in CommentFetcherFactory.supported_platforms():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的平台: {req.platform}，当前支持: {CommentFetcherFactory.supported_platforms()}",
        )
    if req.monitor_type not in ("account", "video"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="monitor_type 必须为 account 或 video",
        )
    svc = get_comment_monitor_service()
    row = await svc.create_task(
        platform=req.platform,
        monitor_type=req.monitor_type,
        target_id=req.target_id.strip(),
        target_nickname=req.target_nickname,
        keywords=req.keywords,
        enable_auto_reply=req.enable_auto_reply,
        enable_lead_extract=req.enable_lead_extract,
        check_interval=req.check_interval,
        max_comments_per_check=req.max_comments_per_check,
        owner_user_id=str(current_user["id"]),
    )
    return row


@router.get("/tasks")
async def list_tasks(
    platform: Optional[str] = None,
    monitor_type: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """列出监控任务"""
    svc = get_comment_monitor_service()
    result = await svc.list_tasks(
        owner_user_id=str(current_user["id"]),
        platform=platform,
        status=status_filter,
        monitor_type=monitor_type,
        page=page,
        page_size=page_size,
        is_admin=is_admin(current_user),
    )
    # 补充运行状态
    for item in result.get("items", []):
        item["is_running"] = svc.is_task_running(item["task_id"])
    return result


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """任务详情"""
    svc = get_comment_monitor_service()
    task = await svc.get_task(
        task_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    task["is_running"] = svc.is_task_running(task_id)
    return task


@router.put("/tasks/{task_id}")
async def update_task(
    task_id: str,
    req: UpdateTaskRequest,
    current_user: dict = Depends(get_current_user),
):
    """更新任务（仅 owner / admin）"""
    svc = get_comment_monitor_service()
    fields = req.dict(exclude_none=True)
    ok = await svc.update_task(
        task_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user), **fields,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或无更新")
    return {"success": True, "message": "ok"}


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除任务（连带停掉协程 + 清理记录）"""
    svc = get_comment_monitor_service()
    ok = await svc.delete_task(
        task_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return {"success": True, "message": "ok"}


@router.post("/tasks/{task_id}/start")
async def start_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """启动监控"""
    svc = get_comment_monitor_service()
    ok = await svc.start_task(
        task_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或已在运行")
    return {"success": True, "message": "监控已启动"}


@router.post("/tasks/{task_id}/stop")
async def stop_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """停止监控"""
    svc = get_comment_monitor_service()
    ok = await svc.stop_task(
        task_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return {"success": True, "message": "监控已停止"}


@router.post("/tasks/{task_id}/check-now")
async def check_now(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """立即触发一次检查（异步，立即返回）"""
    svc = get_comment_monitor_service()
    ok = await svc.check_now(
        task_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return {"success": True, "message": "已触发检查，稍后查看抓取记录"}


@router.get("/tasks/{task_id}/records")
async def list_records(
    task_id: str,
    only_lead: bool = False,
    min_score: int = Query(0, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """查看抓取记录（分页）"""
    svc = get_comment_monitor_service()
    result = await svc.list_records(
        task_id, page=page, page_size=page_size,
        only_lead=only_lead, min_score=min_score,
        owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    return result


@router.get("/tasks/{task_id}/stats")
async def get_task_stats(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """任务统计"""
    svc = get_comment_monitor_service()
    stats = await svc.get_task_stats(
        task_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    return stats
