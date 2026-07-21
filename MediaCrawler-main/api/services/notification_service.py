# -*- coding: utf-8 -*-
"""
通知服务 - 支持多渠道通知(Webhook/邮件/站内消息)

设计要点:
1. 统一接口 send_notification(channel, recipient, title, content, extra)
2. 邮件渠道使用 smtplib + SMTP,配置项从环境变量读取
3. 站内消息存储到 notification 表,前端轮询/拉取
4. 失败不影响主流程,记录日志即可
"""
import os
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


# 邮件配置从环境变量读取
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "获客系统")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "true").lower() == "true"


class NotificationChannel:
    WEBHOOK = "webhook"
    EMAIL = "email"
    IN_APP = "in_app"  # 站内消息


async def send_email(to_addr: str, title: str, content: str, html: Optional[str] = None) -> bool:
    """发送邮件 - 同步 SMTP 包裹在 to_thread 中"""
    if not SMTP_HOST or not SMTP_USER:
        print("[Notification] 邮件渠道未配置 SMTP_HOST/SMTP_USER,跳过")
        return False

    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_USER))
            msg["To"] = to_addr
            msg["Subject"] = title
            msg.attach(MIMEText(content, "plain", "utf-8"))
            if html:
                msg.attach(MIMEText(html, "html", "utf-8"))

            if SMTP_USE_SSL:
                server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
            else:
                server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
                server.starttls()
            try:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, [to_addr], msg.as_string())
                return True
            finally:
                server.quit()
        except Exception as e:
            print(f"[Notification] 邮件发送失败 to={to_addr}: {e}")
            return False

    import asyncio
    return await asyncio.to_thread(_send)


async def send_in_app_message(session: AsyncSession, owner_user_id: str, title: str, content: str,
                                msg_type: str = "info", extra: str = "{}") -> bool:
    """站内消息 - 写入 notification 表"""
    try:
        from database.models import Notification
        now = int(time.time())
        notif = Notification(
            owner_user_id=owner_user_id,
            title=title,
            content=content,
            msg_type=msg_type,
            extra=extra,
            is_read=0,
            created_ts=now,
        )
        session.add(notif)
        await session.commit()
        return True
    except Exception as e:
        print(f"[Notification] 站内消息写入失败: {e}")
        await session.rollback()
        return False


async def send_notification(channel: str, owner_user_id: str, title: str, content: str,
                              recipient: str = "", extra: dict = None, session: AsyncSession = None) -> bool:
    """统一通知入口

    Args:
        channel: 通知渠道(webhook/email/in_app)
        owner_user_id: 归属用户ID
        title: 标题
        content: 内容
        recipient: 接收方(邮件地址/webhook URL,站内消息留空)
        extra: 附加数据
        session: 数据库 session(站内消息需要)
    """
    import json
    extra_str = json.dumps(extra or {}, ensure_ascii=False)

    if channel == NotificationChannel.EMAIL:
        return await send_email(recipient, title, content)
    elif channel == NotificationChannel.IN_APP:
        if not session:
            print("[Notification] 站内消息需要 session 参数")
            return False
        return await send_in_app_message(session, owner_user_id, title, content, extra=extra_str)
    elif channel == NotificationChannel.WEBHOOK:
        # webhook 通过现有 push_leads_to_webhook 实现
        print(f"[Notification] Webhook 渠道请调用 push_leads_to_webhook: {recipient}")
        return False
    else:
        print(f"[Notification] 未知渠道: {channel}")
        return False


async def list_notifications(owner_user_id: str, limit: int = 50, offset: int = 0,
                              unread_only: bool = False) -> dict:
    """拉取站内消息列表"""
    from database.db_session import get_session
    from database.models import Notification
    try:
        async with get_session() as session:
            q = select(Notification).where(Notification.owner_user_id == owner_user_id)
            if unread_only:
                q = q.where(Notification.is_read == 0)
            q = q.order_by(Notification.created_ts.desc()).limit(limit).offset(offset)
            result = await session.execute(q)
            items = result.scalars().all()
            return {
                "items": [
                    {
                        "id": n.id,
                        "title": n.title,
                        "content": n.content,
                        "msg_type": n.msg_type,
                        "extra": n.extra,
                        "is_read": bool(n.is_read),
                        "created_ts": n.created_ts,
                    }
                    for n in items
                ],
                "total": len(items),
            }
    except Exception as e:
        print(f"[Notification] 拉取站内消息失败: {e}")
        return {"items": [], "total": 0}


async def mark_notification_read(notif_id: int, owner_user_id: str) -> bool:
    """标记站内消息为已读"""
    from database.db_session import get_session
    from database.models import Notification
    try:
        async with get_session() as session:
            await session.execute(
                update(Notification)
                .where(Notification.id == notif_id, Notification.owner_user_id == owner_user_id)
                .values(is_read=1)
            )
            await session.commit()
            return True
    except Exception as e:
        print(f"[Notification] 标记已读失败: {e}")
        return False
