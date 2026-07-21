# -*- coding: utf-8 -*-
"""通知路由 - 站内消息查看/标记已读 + 通知 webhook 接收"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, update, func

from database.models import Notification
from database.db_session import get_session
from .auth import get_current_user
from ..services.notification_service import (
    list_notifications, mark_notification_read, NotificationChannel,
    send_notification,
)

router = APIRouter(
    prefix="/notifications",
    tags=["通知管理"],
    responses={404: {"description": "Not found"}},
)


@router.get("")
async def list_user_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False, description="仅未读"),
    current_user: dict = Depends(get_current_user),
):
    """拉取站内消息列表"""
    result = await list_notifications(str(current_user["id"]), limit, offset, unread_only)
    # 同时返回未读总数
    async with get_session() as session:
        unread_count = await session.execute(
            select(func.count(Notification.id)).where(
                Notification.owner_user_id == str(current_user["id"]),
                Notification.is_read == 0,
            )
        )
        result["unread_count"] = unread_count.scalar() or 0
    return result


@router.post("/{notif_id}/read")
async def mark_read(
    notif_id: int,
    current_user: dict = Depends(get_current_user),
):
    """标记单条消息为已读"""
    ok = await mark_notification_read(notif_id, str(current_user["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"success": True}


@router.post("/read-all")
async def mark_all_read(current_user: dict = Depends(get_current_user)):
    """全部标记已读"""
    async with get_session() as session:
        await session.execute(
            update(Notification)
            .where(Notification.owner_user_id == str(current_user["id"]), Notification.is_read == 0)
            .values(is_read=1)
        )
        await session.commit()
    return {"success": True}


@router.post("/webhook")
async def notification_webhook(request: Request):
    """接收 Alertmanager / 外部系统的 webhook 通知,转存为站内消息

    Alertmanager 推送格式见: https://prometheus.io/docs/alerting/latest/alertmanager/
    """
    try:
        body = await request.body()
        payload = json.loads(body)
        alerts = payload.get("alerts", [])
        async with get_session() as session:
            for alert in alerts:
                status = alert.get("status", "firing")
                labels = alert.get("labels", {})
                annotations = alert.get("annotations", {})
                severity = labels.get("severity", "warning")
                title = annotations.get("summary", alert.get("alertname", "系统告警"))
                content = annotations.get("description", "")
                if status == "resolved":
                    title = f"[已恢复] {title}"
                    content = f"告警已恢复\n{content}"

                # owner_user_id 为空(系统级告警,所有用户可见)
                await send_notification(
                    channel=NotificationChannel.IN_APP,
                    owner_user_id="",  # 系统级
                    title=title,
                    content=content,
                    extra={"severity": severity, "alertname": labels.get("alertname"), "labels": labels},
                    session=session,
                )
        return {"success": True, "received": len(alerts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理 webhook 失败: {e}")
