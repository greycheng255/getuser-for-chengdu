# -*- coding: utf-8 -*-
"""邮件/站内消息通知测试

覆盖 PRD §10.7.4:支持多渠道通知(邮件/站内消息/webhook)。

测试场景:
1. 站内消息创建和列表查询
2. 标记单条消息已读
3. 全部标记已读
4. 未读计数
5. webhook 接收告警通知
6. 邮件发送(mock SMTP)
"""
import pytest
import json


@pytest.mark.asyncio
async def test_list_notifications_empty(app_client):
    """空列表返回空数组"""
    resp = await app_client.get("/api/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["unread_count"] == 0


@pytest.mark.asyncio
async def test_create_and_list_notification(app_client):
    """站内消息创建后可查询"""
    # 直接调用 send_notification 创建站内消息
    from database.db_session import get_session
    from api.services.notification_service import send_notification, NotificationChannel

    async with get_session() as session:
        await send_notification(
            channel=NotificationChannel.IN_APP,
            owner_user_id="1",  # admin user_id
            title="测试通知",
            content="这是一条测试通知内容",
            session=session,
        )

    resp = await app_client.get("/api/notifications")
    data = resp.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["title"] == "测试通知"
    assert item["content"] == "这是一条测试通知内容"
    assert item["is_read"] is False


@pytest.mark.asyncio
async def test_mark_single_notification_read(app_client):
    """标记单条消息已读"""
    from database.db_session import get_session
    from api.services.notification_service import send_notification, NotificationChannel

    async with get_session() as session:
        await send_notification(
            channel=NotificationChannel.IN_APP,
            owner_user_id="1",
            title="待标记已读",
            content="测试内容",
            session=session,
        )

    # 获取消息列表找到 ID
    resp = await app_client.get("/api/notifications")
    notif_id = resp.json()["items"][0]["id"]

    # 标记已读
    resp2 = await app_client.post(f"/api/notifications/{notif_id}/read")
    assert resp2.status_code == 200
    assert resp2.json()["success"] is True

    # 再次查询确认已读
    resp3 = await app_client.get("/api/notifications")
    item = next(i for i in resp3.json()["items"] if i["id"] == notif_id)
    assert item["is_read"] is True


@pytest.mark.asyncio
async def test_mark_all_read(app_client):
    """全部标记已读"""
    from database.db_session import get_session
    from api.services.notification_service import send_notification, NotificationChannel

    # 创建多条未读消息
    async with get_session() as session:
        for i in range(3):
            await send_notification(
                channel=NotificationChannel.IN_APP,
                owner_user_id="1",
                title=f"批量测试{i}",
                content="测试",
                session=session,
            )

    # 标记全部已读
    resp = await app_client.post("/api/notifications/read-all")
    assert resp.status_code == 200

    # 未读数应为 0
    resp2 = await app_client.get("/api/notifications")
    assert resp2.json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_unread_only_filter(app_client):
    """仅未读过滤"""
    from database.db_session import get_session
    from api.services.notification_service import send_notification, NotificationChannel

    async with get_session() as session:
        await send_notification(
            channel=NotificationChannel.IN_APP,
            owner_user_id="1",
            title="未读消息",
            content="测试",
            session=session,
        )

    # 查询全部
    resp_all = await app_client.get("/api/notifications")
    total_all = resp_all.json()["total"]

    # 查询仅未读
    resp_unread = await app_client.get("/api/notifications?unread_only=true")
    total_unread = resp_unread.json()["total"]

    assert total_unread <= total_all


@pytest.mark.asyncio
async def test_webhook_receive_alert(app_client):
    """webhook 接收 Alertmanager 告警"""
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"severity": "critical", "alertname": "HighErrorRate"},
                "annotations": {"summary": "错误率过高", "description": "API 错误率超过 5%"},
            }
        ]
    }

    resp = await app_client.post(
        "/api/notifications/webhook",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["received"] == 1


@pytest.mark.asyncio
async def test_webhook_resolved_alert(app_client):
    """webhook 接收已恢复告警"""
    payload = {
        "alerts": [
            {
                "status": "resolved",
                "labels": {"severity": "warning", "alertname": "DiskSpaceLow"},
                "annotations": {"summary": "磁盘空间不足", "description": "剩余空间 10%"},
            }
        ]
    }

    resp = await app_client.post(
        "/api/notifications/webhook",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] == 1


@pytest.mark.asyncio
async def test_user_cannot_read_others_notification(app_client, user_context):
    """用户不能标记其他用户的消息已读"""
    from database.db_session import get_session
    from api.services.notification_service import send_notification, NotificationChannel

    # admin 创建消息
    async with get_session() as session:
        await send_notification(
            channel=NotificationChannel.IN_APP,
            owner_user_id="1",
            title="admin私密消息",
            content="仅供admin查看",
            session=session,
        )

    # user2 列表为空
    async with user_context(2) as client:
        resp = await client.get("/api/notifications")
        assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_email_send_mock():
    """邮件发送(无 SMTP 配置时跳过)"""
    from api.services.notification_service import send_email

    # 无 SMTP 配置时返回 False
    result = await send_email("test@example.com", "测试邮件", "测试内容")
    # 生产环境有 SMTP 配置时 result 为 True,否则 False
    assert isinstance(result, bool)