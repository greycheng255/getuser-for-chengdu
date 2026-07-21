# -*- coding: utf-8 -*-
"""
X 获客工作台 - 高级功能路由

包含从 X Twitter 模块迁移过来的独有功能:
1. 批量视频拆解
2. 关键词回复规则管理
3. WebSocket 实时事件推送

所有接口路径前缀: /api/x-workbench/
"""
import asyncio
import json
import logging
from typing import List as ListType, Optional as OptionalType

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from database.db_session import get_session
from database.models import XTwitterPost, XTwitterVideoBreakdown
from api.services.auth import get_current_user, require_admin
from api.utils.rate_limit import rate_limit


router = APIRouter(
    prefix="/x-workbench",
    tags=["x-workbench-advanced"],
    dependencies=[Depends(get_current_user), Depends(rate_limit())],
)

logger = logging.getLogger("x_workbench_advanced")


# ==================== 请求模型 ====================

class KeywordReplyRule(BaseModel):
    keywords: ListType[str] = Field(default_factory=list, description="触发关键词列表")
    replies: ListType[str] = Field(default_factory=list, description="回复内容列表(随机选一条)")
    priority: int = Field(99, description="优先级,数字越小越优先")


class BatchBreakdownRequest(BaseModel):
    post_ids: ListType[str] = Field(description="要拆解的推文 ID 列表")


class BatchCommentRequest(BaseModel):
    post_ids: ListType[str] = Field(description="要评论的推文 ID 列表")
    comments: OptionalType[ListType[str]] = Field(None, description="预定义评论内容(可选)")
    real_send: bool = Field(True, description="是否真实发送到 X.com")
    use_ai: bool = Field(False, description="comments 为空时是否使用 AI 生成评论")
    ai_count: int = Field(1, description="AI 生成时每条帖子生成的评论数")


# ==================== WebSocket 管理 ====================

class _WorkbenchWSManager:
    """工作台 WebSocket 连接管理器(按用户隔离)"""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id] = [
                ws for ws in self.active_connections[user_id] if ws != websocket
            ]
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_to_user(self, user_id: str, event_type: str, data: dict):
        """向指定用户的所有连接推送事件"""
        if user_id not in self.active_connections:
            return
        message = {"type": event_type, "event": event_type, "data": data, "ts": int(asyncio.get_event_loop().time())}
        dead = []
        for ws in self.active_connections[user_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, user_id)


_ws_manager = _WorkbenchWSManager()


async def notify_workbench_event(user_id: str, event_type: str, data: dict):
    """向工作台推送实时事件(外部调用入口)"""
    await _ws_manager.send_to_user(user_id, event_type, data)


# ==================== 1. 关键词回复规则 ====================

@router.get("/reply-rules")
async def get_reply_rules():
    """获取关键词回复规则"""
    import config as app_config
    rules = getattr(app_config, "X_TWITTER_KEYWORD_REPLY_RULES", [])
    return {"rules": rules}


@router.put("/reply-rules")
async def update_reply_rules(rules: ListType[KeywordReplyRule]):
    """更新关键词回复规则"""
    import config as app_config
    rules_data = [r.model_dump() for r in rules]
    app_config.X_TWITTER_KEYWORD_REPLY_RULES = rules_data

    env_path = ".env"
    rules_json = json.dumps(rules_data, ensure_ascii=False)
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()
        found = False
        with open(env_path, "w") as f:
            for line in lines:
                if line.startswith("X_TWITTER_KEYWORD_REPLY_RULES="):
                    f.write("X_TWITTER_KEYWORD_REPLY_RULES=" + rules_json + "\n")
                    found = True
                else:
                    f.write(line)
            if not found:
                f.write("X_TWITTER_KEYWORD_REPLY_RULES=" + rules_json + "\n")
    except Exception as e:
        logger.warning(f"Failed to persist reply rules to .env: {e}")

    return {"success": True, "rules": rules_data}


# ==================== 2. 批量视频拆解 ====================

@router.post("/batch/breakdown")
async def batch_video_breakdown(req: BatchBreakdownRequest, user=Depends(get_current_user)):
    """批量视频拆解(带 WebSocket 进度推送)"""
    import config as app_config
    from api.services.ai_agent_client import generate_video_breakdown

    batch_size = getattr(app_config, "X_TWITTER_BATCH_BREAKDOWN_SIZE", 5)
    interval = getattr(app_config, "X_TWITTER_BATCH_INTERVAL_SECONDS", 10)

    total = len(req.post_ids)
    success_count = 0
    failed_count = 0
    results = []

    user_id = str(getattr(user, "id", "unknown"))

    for idx, post_id in enumerate(req.post_ids):
        async with get_session() as session:
            stmt = select(XTwitterPost).where(XTwitterPost.post_id == post_id)
            result = await session.execute(stmt)
            post = result.scalar_one_or_none()

            if not post:
                failed_count += 1
                results.append({"post_id": post_id, "success": False, "error": "Post not found"})
                continue

            try:
                breakdown = await generate_video_breakdown(
                    post_id=post.post_id,
                    content=post.content or "",
                    video_url=post.video_url or "",
                )
                if breakdown and breakdown.get("script"):
                    success_count += 1
                    results.append({
                        "post_id": post_id,
                        "success": True,
                        "breakdown_preview": str(breakdown.get("script", ""))[:200],
                    })
                else:
                    failed_count += 1
                    results.append({"post_id": post_id, "success": False, "error": "AI breakdown failed"})
            except Exception as e:
                failed_count += 1
                results.append({"post_id": post_id, "success": False, "error": str(e)[:200]})

        # WebSocket 进度推送
        await _ws_manager.send_to_user(user_id, "batch_breakdown_progress", {
            "current": idx + 1,
            "total": total,
            "success": success_count,
            "failed": failed_count,
        })

        # 批次间隔
        if (idx + 1) % batch_size == 0 and idx + 1 < total:
            await asyncio.sleep(interval)

    return {
        "success": True,
        "total": total,
        "success_count": success_count,
        "failed_count": failed_count,
        "results": results,
    }


# ==================== 3. WebSocket 实时事件 ====================
#
# 注意: WebSocket 路由单独注册到一个不带认证依赖的 router,
# 因为 APIRouter 级别的 dependencies=[Depends(get_current_user)] 使用 Bearer Token,
# 在 WebSocket 握手阶段无法注入 HTTP 头,会导致连接被拒绝。
# WebSocket 通过 query 参数 token 自行认证。

_ws_router = APIRouter(prefix="/x-workbench", tags=["x-workbench-advanced"])


@_ws_router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket, token: str = Query(default="")):
    """
    工作台实时事件 WebSocket 通道

    支持的事件类型:
    - batch_breakdown_progress: 批量拆解进度
    - comment_sent: 评论发送完成
    - new_reply: 收到新回复
    - monitor_status: 监控状态变化
    """
    from api.services.auth import decode_token

    try:
        payload = decode_token(token)
        if payload is None:
            await websocket.close(code=4401)
            return
        user_id = str(payload.get("sub") or payload.get("uid") or "unknown")
    except Exception:
        await websocket.close(code=4401)
        return

    await _ws_manager.connect(websocket, user_id)
    logger.info(f"[Workbench WS] User {user_id} connected")

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        _ws_manager.disconnect(websocket, user_id)
        logger.info(f"[Workbench WS] User {user_id} disconnected")
    except Exception as e:
        _ws_manager.disconnect(websocket, user_id)
        logger.warning(f"[Workbench WS] User {user_id} error: {e}")
