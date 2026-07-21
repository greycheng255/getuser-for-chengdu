# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/websocket.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import asyncio
from typing import Set, Optional, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from ..services import crawler_manager
from ..services.auth import decode_token

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """WebSocket connection manager"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        # 线索推送连接:按用户隔离 {websocket: owner_user_id}
        self.lead_connections: Dict[WebSocket, str] = {}
        # 通知推送连接:按用户隔离 {websocket: owner_user_id}
        self.notice_connections: Dict[WebSocket, str] = {}
        # X Twitter 评论回复推送连接
        self.x_twitter_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        self.lead_connections.pop(websocket, None)
        self.notice_connections.pop(websocket, None)

    async def broadcast(self, message: dict):
        """Broadcast message to all connections (日志广播)"""
        if not self.active_connections:
            return

        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected connections
        for conn in disconnected:
            self.disconnect(conn)

    async def connect_leads(self, websocket: WebSocket, user_id: str):
        """建立线索推送连接,绑定 user_id 用于按用户隔离推送"""
        await websocket.accept()
        self.lead_connections[websocket] = user_id

    async def broadcast_new_lead(self, owner_user_id: str, payload: dict):
        """向指定用户推送新线索事件(按 owner_user_id 隔离)"""
        if not self.lead_connections:
            return
        disconnected = []
        for conn, uid in list(self.lead_connections.items()):
            # 推送给该用户(以及管理员 uid 为空的系统级消息)
            if uid == owner_user_id or uid == "":
                try:
                    await conn.send_json(payload)
                except Exception:
                    disconnected.append(conn)
        for conn in disconnected:
            self.lead_connections.pop(conn, None)

    async def connect_notice(self, websocket: WebSocket, user_id: str):
        """建立通知推送连接,绑定 user_id 用于按用户隔离推送"""
        await websocket.accept()
        self.notice_connections[websocket] = user_id

    async def broadcast_notice(self, owner_user_id: str, payload: dict):
        """向指定用户推送通知事件(按 owner_user_id 隔离)

        owner_user_id 为空时视为系统级通知,推送给所有连接的用户。
        """
        if not self.notice_connections:
            return
        disconnected = []
        for conn, uid in list(self.notice_connections.items()):
            if uid == owner_user_id or owner_user_id == "":
                try:
                    await conn.send_json(payload)
                except Exception:
                    disconnected.append(conn)
        for conn in disconnected:
            self.notice_connections.pop(conn, None)


manager = ConnectionManager()


async def notify_new_leads(owner_user_id: str, task_id: str, platform: str, count: int, high_count: int, medium_count: int, low_count: int):
    """供采集流程调用:推送新线索事件到对应用户的 WebSocket

    在 tasks.py 批量写入线索后调用,前端收到后自动刷新列表。
    """
    if not owner_user_id:
        return
    await manager.broadcast_new_lead(owner_user_id, {
        "type": "new_lead",
        "task_id": task_id,
        "platform": platform,
        "count": count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "ts": int(asyncio.get_event_loop().time() * 1000),
    })


async def notify_user(owner_user_id: str, title: str, content: str, msg_type: str = "warning", extra: dict = None):
    """供业务流程调用:实时推送通知到对应用户的 WebSocket

    配合站内消息(notification 表)使用:先写库,再调用此函数推送实时事件。
    前端收到后弹出提醒并刷新通知中心。
    """
    if not owner_user_id:
        return
    payload = {
        "type": "notification",
        "title": title,
        "content": content,
        "msg_type": msg_type,  # info / warning / error / success
        "extra": extra or {},
        "ts": int(asyncio.get_event_loop().time() * 1000),
    }
    await manager.broadcast_notice(owner_user_id, payload)


async def log_broadcaster():
    """Background task: read logs from queue and broadcast"""
    queue = crawler_manager.get_log_queue()
    while True:
        try:
            # Get log entry from queue
            entry = await queue.get()
            # Broadcast to all WebSocket connections
            await manager.broadcast(entry.model_dump())
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Log broadcaster error: {e}")
            await asyncio.sleep(0.1)


# Global broadcast task
_broadcaster_task: Optional[asyncio.Task] = None


def start_broadcaster():
    """Start broadcast task"""
    global _broadcaster_task
    if _broadcaster_task is None or _broadcaster_task.done():
        _broadcaster_task = asyncio.create_task(log_broadcaster())


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket log stream"""
    print("[WS] New connection attempt")

    try:
        # Ensure broadcast task is running
        start_broadcaster()

        await manager.connect(websocket)
        print(f"[WS] Connected, active connections: {len(manager.active_connections)}")

        # Send existing logs
        for log in crawler_manager.logs():
            try:
                await websocket.send_json(log.model_dump())
            except Exception as e:
                print(f"[WS] Error sending existing log: {e}")
                break

        print(f"[WS] Sent {len(crawler_manager.logs())} existing logs, entering main loop")

        while True:
            # Keep connection alive, receive heartbeat or any message
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_text("ping")
                except Exception as e:
                    print(f"[WS] Error sending ping: {e}")
                    break

    except WebSocketDisconnect:
        print("[WS] Client disconnected")
    except Exception as e:
        print(f"[WS] Error: {type(e).__name__}: {e}")
    finally:
        manager.disconnect(websocket)
        print(f"[WS] Cleanup done, active connections: {len(manager.active_connections)}")


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket status stream"""
    await websocket.accept()

    try:
        while True:
            # Send status every second
            status = crawler_manager.get_status()
            await websocket.send_json(status)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@router.websocket("/ws/leads")
async def websocket_leads(websocket: WebSocket, token: str = Query(default="")):
    """新线索推送 WebSocket - 按用户隔离推送 new_lead 事件

    前端连接时通过 query 参数携带 token,服务端解析后绑定 user_id,
    采集流程写入线索后调用 notify_new_leads 推送给对应用户。
    """
    if not token:
        await websocket.close(code=4401)
        return
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4401)
        return
    user_id = str(payload.get("sub") or payload.get("user_id") or "")

    try:
        await manager.connect_leads(websocket, user_id)
        # 发送连接成功消息
        await websocket.send_json({"type": "connected", "user_id": user_id})

        while True:
            # 心跳保活
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS/leads] Error: {type(e).__name__}: {e}")
    finally:
        manager.disconnect(websocket)


@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket, token: str = Query(default="")):
    """通知推送 WebSocket - 按用户隔离推送 notification 事件

    前端连接时通过 query 参数携带 token,服务端解析后绑定 user_id,
    业务流程(如 cookie 失效告警)调用 notify_user 推送给对应用户。
    """
    if not token:
        await websocket.close(code=4401)
        return
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4401)
        return
    user_id = str(payload.get("sub") or payload.get("user_id") or "")

    try:
        await manager.connect_notice(websocket, user_id)
        await websocket.send_json({"type": "connected", "user_id": user_id})

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS/notifications] Error: {type(e).__name__}: {e}")
    finally:
        manager.disconnect(websocket)
