# -*- coding: utf-8 -*-
"""
X Twitter 工作台 - 通知渠道管理路由

CRUD 接口:
- GET    /x-workbench/notifications/channels       渠道列表
- GET    /x-workbench/notifications/channels/{id}  渠道详情
- POST   /x-workbench/notifications/channels       创建渠道
- PUT    /x-workbench/notifications/channels/{id}  更新渠道
- DELETE /x-workbench/notifications/channels/{id}  删除渠道(软删除:is_active=0)
- POST   /x-workbench/notifications/channels/{id}/test  测试推送

元数据接口:
- GET    /x-workbench/notifications/meta           渠道类型/事件类型枚举
- GET    /x-workbench/notifications/events         最近事件触发日志(可选)
"""
import json
import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc

from database.db_session import get_session
from database.models import XTwitterNotificationChannel
from api.services.auth import get_current_user, require_admin
from api.services.x_workbench_notifier import (
    notify_event,
    ALL_EVENTS,
    ALL_CHANNELS,
    CHANNEL_EMAIL,
    CHANNEL_DINGTALK,
    CHANNEL_WECHAT_WORK,
    CHANNEL_CUSTOM_WEBHOOK,
)
from api.utils.exceptions import NotFoundError, BusinessError
from api.utils.rate_limit import rate_limit


router = APIRouter(
    prefix="/x-workbench/notifications",
    tags=["x-twitter-workbench"],
    dependencies=[Depends(get_current_user), Depends(rate_limit())],
)

logger = logging.getLogger("x_workbench_notifications_router")


# ==================== 元数据 ====================

@router.get("/meta")
async def get_meta():
    """获取渠道类型和事件类型枚举(供前端构建表单选项)"""
    return {
        "channels": [{"value": v, "label": label} for v, label in ALL_CHANNELS],
        "events": [{"value": v, "label": label} for v, label in ALL_EVENTS],
    }


# ==================== 列表/详情 ====================

@router.get("/channels")
async def list_channels(
    active_only: bool = Query(False, description="只返回启用的"),
    channel_type: str = Query("", description="按渠道类型筛选"),
):
    """渠道列表"""
    async with get_session() as session:
        stmt = select(XTwitterNotificationChannel).order_by(desc(XTwitterNotificationChannel.id))
        if active_only:
            stmt = stmt.where(XTwitterNotificationChannel.is_active == 1)
        if channel_type:
            stmt = stmt.where(XTwitterNotificationChannel.channel_type == channel_type)
        result = await session.execute(stmt)
        items = result.scalars().all()

    return {
        "total": len(items),
        "items": [_channel_to_dict(c) for c in items],
    }


@router.get("/channels/{channel_id}")
async def get_channel(channel_id: int):
    """渠道详情"""
    async with get_session() as session:
        c = await session.get(XTwitterNotificationChannel, channel_id)
        if not c:
            raise NotFoundError("通知渠道不存在")
        return _channel_to_dict(c)


# ==================== 创建/更新/删除 ====================

@router.post("/channels")
async def create_channel(data: Dict[str, Any]):
    """创建通知渠道

    Body 字段:
    - name: 渠道名称
    - channel_type: 渠道类型(email/dingtalk/wechat_work/custom_webhook)
    - config: 配置 JSON(email_to/webhook_url/secret/at_mobiles 等)
    - events: 订阅事件数组
    - min_interval_seconds: 最小触发间隔(秒)
    - note: 备注
    """
    _validate_channel_payload(data)

    now = int(time.time())
    ch = XTwitterNotificationChannel(
        name=data["name"].strip(),
        channel_type=data["channel_type"],
        config=json.dumps(data.get("config", {}), ensure_ascii=False),
        events=json.dumps(data.get("events", []), ensure_ascii=False),
        is_active=1 if data.get("is_active", True) else 0,
        min_interval_seconds=int(data.get("min_interval_seconds", 60)),
        note=data.get("note", ""),
        success_count=0,
        fail_count=0,
        last_trigger_ts=0,
        created_ts=now,
        updated_ts=now,
    )
    async with get_session() as session:
        session.add(ch)
        await session.commit()
        await session.refresh(ch)

    logger.info(f"创建通知渠道: id={ch.id} name={ch.name} type={ch.channel_type}")
    return _channel_to_dict(ch)


@router.put("/channels/{channel_id}")
async def update_channel(channel_id: int, data: Dict[str, Any]):
    """更新通知渠道(支持部分字段更新)"""
    _validate_channel_payload(data, partial=True)

    async with get_session() as session:
        c = await session.get(XTwitterNotificationChannel, channel_id)
        if not c:
            raise NotFoundError("通知渠道不存在")

        if "name" in data:
            c.name = data["name"].strip()
        if "channel_type" in data:
            c.channel_type = data["channel_type"]
        if "config" in data:
            c.config = json.dumps(data["config"], ensure_ascii=False)
        if "events" in data:
            c.events = json.dumps(data["events"], ensure_ascii=False)
        if "is_active" in data:
            c.is_active = 1 if data["is_active"] else 0
        if "min_interval_seconds" in data:
            c.min_interval_seconds = int(data["min_interval_seconds"])
        if "note" in data:
            c.note = data["note"]
        c.updated_ts = int(time.time())
        await session.commit()
        await session.refresh(c)

    return _channel_to_dict(c)


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: int):
    """删除通知渠道(软删除:标记为 inactive)"""
    async with get_session() as session:
        c = await session.get(XTwitterNotificationChannel, channel_id)
        if not c:
            raise NotFoundError("通知渠道不存在")
        c.is_active = 0
        c.updated_ts = int(time.time())
        await session.commit()
    return {"success": True, "message": "已禁用"}


# ==================== 测试推送 ====================

@router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: int):
    """测试推送一条通知到指定渠道(忽略限频)"""
    from api.services.x_workbench_notifier import _dispatch_channel

    async with get_session() as session:
        c = await session.get(XTwitterNotificationChannel, channel_id)
        if not c:
            raise NotFoundError("通知渠道不存在")

        # 临时把 last_trigger_ts 清零,绕过限频
        original_ts = c.last_trigger_ts
        c.last_trigger_ts = 0
        await session.commit()
        await session.refresh(c)

    try:
        ok = await _dispatch_channel(
            c,
            event="test",
            title="测试通知",
            content=f"这是一条来自 X Twitter 工作台的测试通知,渠道: {c.name}",
            extra={"测试时间": time.strftime("%Y-%m-%d %H:%M:%S"), "渠道ID": c.id},
        )
    finally:
        # 恢复 last_trigger_ts(测试不计入统计)
        async with get_session() as session:
            await session.execute(
                XTwitterNotificationChannel.__table__.update()
                .where(XTwitterNotificationChannel.id == channel_id)
                .values(last_trigger_ts=original_ts)
            )
            await session.commit()

    if not ok:
        raise BusinessError("推送失败,请检查渠道配置和后端日志")
    return {"success": True, "message": "推送成功,请检查目标是否收到"}


# ==================== 工具函数 ====================

def _channel_to_dict(c: XTwitterNotificationChannel) -> Dict[str, Any]:
    """渠道对象转 dict(同时解析 JSON 字段)"""
    try:
        config = json.loads(c.config or "{}")
    except Exception:
        config = {}
    try:
        events = json.loads(c.events or "[]")
    except Exception:
        events = []
    return {
        "id": c.id,
        "name": c.name,
        "channel_type": c.channel_type,
        "config": config,
        "events": events,
        "is_active": c.is_active,
        "min_interval_seconds": c.min_interval_seconds,
        "last_trigger_ts": c.last_trigger_ts,
        "success_count": c.success_count,
        "fail_count": c.fail_count,
        "note": c.note or "",
        "created_ts": c.created_ts,
        "updated_ts": c.updated_ts,
    }


def _validate_channel_payload(data: Dict[str, Any], partial: bool = False):
    """校验渠道创建/更新参数"""
    if not partial or "name" in data:
        if not data.get("name", "").strip():
            raise BusinessError("渠道名称不能为空")
    if not partial or "channel_type" in data:
        ct = data.get("channel_type", "")
        if ct not in (CHANNEL_EMAIL, CHANNEL_DINGTALK, CHANNEL_WECHAT_WORK, CHANNEL_CUSTOM_WEBHOOK):
            raise BusinessError(f"不支持的渠道类型: {ct}")

    # 渠道特定配置校验(只在 config 提供时校验)
    config = data.get("config") or {}
    if config:
        ct = data.get("channel_type")
        if ct == CHANNEL_EMAIL and not config.get("email_to"):
            raise BusinessError("邮件渠道需要配置 email_to")
        if ct in (CHANNEL_DINGTALK, CHANNEL_WECHAT_WORK, CHANNEL_CUSTOM_WEBHOOK) and not config.get("webhook_url"):
            raise BusinessError(f"{ct} 渠道需要配置 webhook_url")
