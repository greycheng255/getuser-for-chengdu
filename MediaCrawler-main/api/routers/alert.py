# -*- coding: utf-8 -*-
"""
统一预警中心路由

阶段一 P0 任务 1.4：暴露 GET /api/alerts、POST /api/alerts/{id}/read、WS /ws/alerts。
"""

import logging
import asyncio
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from api.services.alert.alert_center import (
    AlertSeverity,
    AlertType,
    get_alert_center,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])


class MarkReadRequest(BaseModel):
    user_id: Optional[int] = None


@router.get("")
async def list_alerts(
    user_id: Optional[int] = Query(None, alias="user_id"),
    alert_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """查询预警列表"""
    center = get_alert_center()
    items = await center.list_alerts(
        owner_user_id=user_id,
        alert_type=alert_type,
        severity=severity,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"code": 0, "data": {"items": items, "total": len(items)}}


@router.get("/unread-count")
async def unread_count(user_id: Optional[int] = Query(None)):
    """未读预警数"""
    center = get_alert_center()
    count = await center.count_unread(user_id)
    return {"code": 0, "data": {"count": count}}


@router.post("/{alert_id}/read")
async def mark_read(alert_id: str, req: MarkReadRequest):
    """标记单条已读"""
    center = get_alert_center()
    ok = await center.mark_read(alert_id, req.user_id)
    return {"code": 0 if ok else 4000, "data": {"success": ok}}


@router.post("/read-all")
async def mark_all_read(req: MarkReadRequest):
    """全部标记已读"""
    center = get_alert_center()
    n = await center.mark_all_read(req.user_id)
    return {"code": 0, "data": {"updated": n}}


@router.get("/types")
async def list_types():
    """预警类型枚举"""
    return {
        "code": 0,
        "data": {
            "types": [t.value for t in AlertType],
            "severities": [s.value for s in AlertSeverity],
        },
    }


@router.websocket("/ws")
async def alerts_ws(websocket: WebSocket):
    """WebSocket 实时推送预警"""
    await websocket.accept()
    center = get_alert_center()
    queue = center.subscribe()
    try:
        while True:
            try:
                alert = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(alert)
            except asyncio.TimeoutError:
                # 心跳
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[alerts_ws] 异常: {e}")
    finally:
        center.unsubscribe(queue)
