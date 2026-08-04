# -*- coding: utf-8 -*-
"""
私信自动回复 API 路由（第七阶段 + 阶段四任务 4.1 多平台扩展）

提供：
1. GET /api/dm/messages - 私信列表
2. GET /api/dm/messages/needs-human - 需转人工的私信
3. POST /api/dm/messages/{msg_id}/resolve - 标记已解决
4. POST /api/dm/platforms - 添加监控平台
5. DELETE /api/dm/platforms - 移除监控平台
6. GET /api/dm/platforms - 监控平台列表
7. POST /api/dm/monitor/start - 启动私信监控
8. POST /api/dm/monitor/stop - 停止监控
9. GET /api/dm/monitor/status - 监控状态
10. POST /api/dm/reply/preview - 预览 AI 回复（不实际发送）
11. GET /api/dm/platforms/supported - 列出 DM 能力平台（任务 4.1）
12. POST /api/dm/{platform}/reply - 跨平台主动回复（任务 4.1）
13. POST /api/dm/messages/{msg_id}/reply - 基于已存私信 ID 主动回复（任务 4.1）
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.dm import (
    get_dm_monitor,
    get_dm_replier,
    get_dm_platform_registry,
)
from ..services.dm.dm_models import DirectMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dm", tags=["dm"])


class PlatformRequest(BaseModel):
    platform: str


class ReplyPreviewRequest(BaseModel):
    platform: str
    message_text: str
    sender_name: str = ""


class CrossPlatformReplyRequest(BaseModel):
    """跨平台主动回复请求"""
    conversation_id: str
    reply_text: str
    sender_name: str = ""
    message_text: str = ""  # 原私信内容（用于上下文）


class ReplyByIdRequest(BaseModel):
    """基于已存私信 ID 的回复请求"""
    reply_text: str = ""  # 留空则使用 AI 生成的 reply_text
    force: bool = False  # 是否强制发送（即使 needs_human=True）


@router.get("/messages")
async def list_messages(
    platform: str = Query(""),
    state: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
):
    monitor = get_dm_monitor()
    msgs = await monitor.list_messages(platform=platform, state=state, limit=limit)
    return {"messages": msgs, "count": len(msgs)}


@router.get("/messages/needs-human")
async def list_needs_human():
    monitor = get_dm_monitor()
    msgs = await monitor.list_needs_human()
    return {"messages": msgs, "count": len(msgs)}


@router.post("/messages/{msg_id}/resolve")
async def resolve_message(msg_id: int):
    monitor = get_dm_monitor()
    ok = await monitor.resolve_message(msg_id)
    if not ok:
        raise HTTPException(400, "标记失败")
    return {"success": True, "message": "私信已标记为解决"}


@router.post("/platforms")
async def add_platform(req: PlatformRequest):
    monitor = get_dm_monitor()
    await monitor.add_platform(req.platform)
    return {"success": True, "platforms": monitor.list_platforms()}


@router.delete("/platforms")
async def remove_platform(req: PlatformRequest):
    monitor = get_dm_monitor()
    await monitor.remove_platform(req.platform)
    return {"success": True, "platforms": monitor.list_platforms()}


@router.get("/platforms")
async def list_platforms():
    monitor = get_dm_monitor()
    return {"platforms": monitor.list_platforms()}


@router.get("/platforms/supported")
async def list_supported_platforms(region: str = Query("")):
    """列出所有支持 DM 的平台（任务 4.1）

    Args:
        region: domestic/overseas，留空返回全部
    """
    registry = get_dm_platform_registry()
    caps = registry.list_platforms(region=region or None)
    return {
        "platforms": [c.to_dict() for c in caps],
        "count": len(caps),
    }


@router.post("/monitor/start")
async def start_monitor():
    monitor = get_dm_monitor()
    if monitor.is_running():
        return {"success": True, "message": "监控已在运行"}
    await monitor.start()
    return {"success": True, "message": "私信监控已启动"}


@router.post("/monitor/stop")
async def stop_monitor():
    monitor = get_dm_monitor()
    await monitor.stop()
    return {"success": True, "message": "私信监控已停止"}


@router.get("/monitor/status")
async def monitor_status():
    monitor = get_dm_monitor()
    return {
        "running": monitor.is_running(),
        "check_interval": monitor.check_interval,
        "platforms": monitor.list_platforms(),
    }


@router.post("/reply/preview")
async def preview_reply(req: ReplyPreviewRequest):
    """预览 AI 回复（不实际发送）"""
    replier = get_dm_replier()
    dm = DirectMessage(
        platform=req.platform,
        message_text=req.message_text,
        sender_name=req.sender_name,
    )
    result = await replier.classify_and_reply(dm)
    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "reply_text": result.reply_text,
        "needs_human": result.needs_human,
        "state": result.state,
    }


# ==================== 跨平台回复（任务 4.1） ====================


@router.post("/{platform}/reply")
async def cross_platform_reply(platform: str, req: CrossPlatformReplyRequest):
    """跨平台主动回复私信

    内部流程：构造 DirectMessage → AI 分类 → 实际发送
    """
    registry = get_dm_platform_registry()
    cap = registry.get(platform)
    if cap is None:
        raise HTTPException(404, f"平台 {platform} 不在 DM 能力注册表中")
    if not cap.supports_reply:
        raise HTTPException(400, f"平台 {platform} 暂不支持回复私信")

    replier = get_dm_replier()
    dm = DirectMessage(
        platform=platform,
        conversation_id=req.conversation_id,
        message_text=req.message_text,
        sender_name=req.sender_name,
        reply_text=req.reply_text,  # 直接使用调用方提供的回复
    )
    # 直接发送（绕过 AI 生成）
    dm = await replier.reply_cross_platform(dm, force=True)
    return {
        "success": dm.is_replied,
        "platform": platform,
        "conversation_id": req.conversation_id,
        "state": dm.state,
        "message": "回复已发送" if dm.is_replied else "回复失败",
    }


@router.post("/messages/{msg_id}/reply")
async def reply_by_message_id(msg_id: int, req: ReplyByIdRequest):
    """基于已存私信 ID 主动回复

    - 若 reply_text 为空，使用 AI 已生成的 reply_text
    - 若 force=True，即使 needs_human=True 也强制发送
    """
    monitor = get_dm_monitor()
    msgs = await monitor.list_messages(limit=500)
    target = next((m for m in msgs if m.get("id") == msg_id), None)
    if not target:
        raise HTTPException(404, f"私信 #{msg_id} 不存在")

    dm = DirectMessage(
        id=msg_id,
        platform=target.get("platform", ""),
        conversation_id=target.get("conversation_id", ""),
        message_text=target.get("message_text", ""),
        sender_name=target.get("sender_name", ""),
        reply_text=req.reply_text or target.get("reply_text") or "",
        needs_human=target.get("needs_human", False),
    )
    if not dm.reply_text:
        # 没有 reply_text，先调 AI 生成
        replier = get_dm_replier()
        dm = await replier.classify_and_reply(dm)

    replier = get_dm_replier()
    dm = await replier.reply_cross_platform(dm, force=req.force)

    # 更新数据库
    await monitor._update_reply(dm)
    return {
        "success": dm.is_replied,
        "msg_id": msg_id,
        "state": dm.state,
        "reply_text": dm.reply_text,
    }
