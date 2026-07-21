# -*- coding: utf-8 -*-
"""
X Twitter 工作台 - 多渠道通知推送服务

支持渠道:
- email: 邮件(复用 notification_service.send_email,SMTP 配置)
- dingtalk: 钉钉群机器人 webhook
- wechat_work: 企业微信群机器人 webhook
- custom_webhook: 自定义 webhook(POST JSON)

支持事件:
- new_reply:        收到新回复
- reply_sent:       AI 自动回复已发送
- reply_failed:     AI 自动回复失败
- comment_sent:     评论发送成功
- comment_failed:   评论发送失败
- cookie_pool_empty: Cookie 池为空/全部失效

设计要点:
1. 通知失败不影响主流程(异常吞掉,仅记日志)
2. 限频:每个渠道有 min_interval_seconds,避免短时间内重复通知
3. 异步并发:同时触发多个渠道用 asyncio.gather
4. 推送结果回写 DB(success_count/fail_count/last_trigger_ts)
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select, update

from database.db_session import get_session
from database.models import XTwitterNotificationChannel


logger = logging.getLogger("x_workbench_notifier")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# ==================== 事件类型 ====================

EVENT_NEW_REPLY = "new_reply"
EVENT_REPLY_SENT = "reply_sent"
EVENT_REPLY_FAILED = "reply_failed"
EVENT_COMMENT_SENT = "comment_sent"
EVENT_COMMENT_FAILED = "comment_failed"
EVENT_COOKIE_POOL_EMPTY = "cookie_pool_empty"

ALL_EVENTS = [
    (EVENT_NEW_REPLY, "收到新回复"),
    (EVENT_REPLY_SENT, "AI 自动回复已发送"),
    (EVENT_REPLY_FAILED, "AI 自动回复失败"),
    (EVENT_COMMENT_SENT, "评论发送成功"),
    (EVENT_COMMENT_FAILED, "评论发送失败"),
    (EVENT_COOKIE_POOL_EMPTY, "Cookie 池为空"),
]

CHANNEL_EMAIL = "email"
CHANNEL_DINGTALK = "dingtalk"
CHANNEL_WECHAT_WORK = "wechat_work"
CHANNEL_CUSTOM_WEBHOOK = "custom_webhook"

ALL_CHANNELS = [
    (CHANNEL_EMAIL, "邮件"),
    (CHANNEL_DINGTALK, "钉钉群机器人"),
    (CHANNEL_WECHAT_WORK, "企业微信群机器人"),
    (CHANNEL_CUSTOM_WEBHOOK, "自定义 Webhook"),
]


# ==================== 公共入口 ====================

async def notify_event(event: str, title: str, content: str, extra: Optional[Dict[str, Any]] = None) -> int:
    """触发一个事件的通知

    Args:
        event: 事件类型(见 ALL_EVENTS)
        title: 通知标题
        content: 通知正文(纯文本)
        extra: 附加数据(用于邮件 HTML / webhook payload)

    Returns:
        成功推送的渠道数
    """
    if not event:
        return 0

    now = int(time.time())

    # 查询订阅了该事件且启用的渠道
    async with get_session() as session:
        stmt = select(XTwitterNotificationChannel).where(
            XTwitterNotificationChannel.is_active == 1,
        )
        result = await session.execute(stmt)
        channels = result.scalars().all()

        # 在 Python 端过滤订阅事件(JSON 字段跨数据库查询兼容性差)
        target_channels: List[XTwitterNotificationChannel] = []
        for ch in channels:
            try:
                events = json.loads(ch.events or "[]")
                if event in events:
                    # 限频检查
                    if ch.last_trigger_ts and (now - ch.last_trigger_ts) < (ch.min_interval_seconds or 0):
                        logger.debug(f"渠道 {ch.name}({ch.id}) 限频跳过(距离上次 {now - ch.last_trigger_ts}s)")
                        continue
                    target_channels.append(ch)
            except Exception:
                continue

    if not target_channels:
        return 0

    logger.info(f"事件 {event} 触发 {len(target_channels)} 个渠道通知: {title}")

    # 并发推送(每个渠道独立失败,互不影响)
    async def _push_one(ch: XTwitterNotificationChannel):
        ok = False
        try:
            ok = await _dispatch_channel(ch, event, title, content, extra or {})
        except Exception as e:
            logger.error(f"渠道 {ch.name}({ch.id}) 推送异常: {e}")
            ok = False
        # 回写推送结果
        try:
            async with get_session() as session:
                if ok:
                    await session.execute(
                        update(XTwitterNotificationChannel)
                        .where(XTwitterNotificationChannel.id == ch.id)
                        .values(
                            success_count=XTwitterNotificationChannel.success_count + 1,
                            last_trigger_ts=now,
                            updated_ts=now,
                        )
                    )
                else:
                    await session.execute(
                        update(XTwitterNotificationChannel)
                        .where(XTwitterNotificationChannel.id == ch.id)
                        .values(
                            fail_count=XTwitterNotificationChannel.fail_count + 1,
                            last_trigger_ts=now,
                            updated_ts=now,
                        )
                    )
                await session.commit()
        except Exception as e:
            logger.error(f"回写渠道状态失败: {e}")
        return ok

    results = await asyncio.gather(*[_push_one(ch) for ch in target_channels])
    return sum(1 for r in results if r)


# ==================== 渠道分发 ====================

async def _dispatch_channel(ch: XTwitterNotificationChannel, event: str, title: str, content: str, extra: Dict[str, Any]) -> bool:
    """根据渠道类型分发推送"""
    try:
        cfg = json.loads(ch.config or "{}")
    except Exception:
        cfg = {}

    if ch.channel_type == CHANNEL_EMAIL:
        return await _push_email(cfg, title, content, extra)
    elif ch.channel_type == CHANNEL_DINGTALK:
        return await _push_dingtalk(cfg, title, content, extra)
    elif ch.channel_type == CHANNEL_WECHAT_WORK:
        return await _push_wechat_work(cfg, title, content, extra)
    elif ch.channel_type == CHANNEL_CUSTOM_WEBHOOK:
        return await _push_custom_webhook(cfg, event, title, content, extra)
    else:
        logger.warning(f"未知渠道类型: {ch.channel_type}")
        return False


# ==================== 邮件 ====================

async def _push_email(cfg: Dict[str, Any], title: str, content: str, extra: Dict[str, Any]) -> bool:
    """邮件渠道(复用 notification_service.send_email)"""
    to_addr = cfg.get("email_to", "").strip()
    if not to_addr:
        logger.warning("邮件渠道缺少 email_to 配置")
        return False

    from api.services.notification_service import send_email
    html = _build_email_html(title, content, extra)
    return await send_email(to_addr, f"[X工作台] {title}", content, html=html)


def _build_email_html(title: str, content: str, extra: Dict[str, Any]) -> str:
    """构建简单的 HTML 邮件内容"""
    rows = ""
    for k, v in (extra or {}).items():
        rows += f"<tr><td style='padding:4px 12px;color:#888;'>{k}</td><td style='padding:4px 12px;'>{v}</td></tr>"
    return f"""
    <div style='font-family:-apple-system,system-ui,sans-serif;max-width:560px;margin:0 auto;border:1px solid #eee;border-radius:8px;overflow:hidden'>
      <div style='background:#1DA1F2;color:#fff;padding:16px 24px;font-size:16px;font-weight:bold'>X Twitter 工作台通知</div>
      <div style='padding:16px 24px'>
        <h3 style='margin:0 0 12px 0;color:#333'>{title}</h3>
        <p style='color:#555;line-height:1.6;white-space:pre-wrap'>{content}</p>
        {f"<table style='margin-top:16px;border-collapse:collapse;font-size:13px;border-top:1px solid #eee'>{rows}</table>" if rows else ""}
      </div>
      <div style='background:#fafafa;color:#999;padding:8px 24px;font-size:12px'>本邮件由系统自动发送,请勿回复</div>
    </div>
    """


# ==================== 钉钉群机器人 ====================

async def _push_dingtalk(cfg: Dict[str, Any], title: str, content: str, extra: Dict[str, Any]) -> bool:
    """钉钉群机器人 webhook

    cfg 字段:
    - webhook_url: 钉钉机器人 webhook 地址
    - secret: (可选)加签密钥
    - at_mobiles: (可选)@指定手机号,逗号分隔
    """
    import urllib.parse
    import hashlib
    import hmac

    url = cfg.get("webhook_url", "").strip()
    if not url:
        logger.warning("钉钉渠道缺少 webhook_url")
        return False

    # 加签(如果配置了 secret)
    secret = cfg.get("secret", "").strip()
    if secret:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64_encode(hmac_code))
        url = f"{url}&timestamp={timestamp}&sign={sign}"

    # @ 手机号
    at_mobiles_str = cfg.get("at_mobiles", "").strip()
    at_mobiles = [m.strip() for m in at_mobiles_str.split(",") if m.strip()] if at_mobiles_str else []
    is_at_all = bool(cfg.get("is_at_all", False))

    text = f"【{title}】\n\n{content}"
    if extra:
        text += "\n\n"
        for k, v in extra.items():
            text += f"• {k}: {v}\n"
    if at_mobiles:
        text += "\n" + " ".join(f"@{m}" for m in at_mobiles)

    payload = {
        "msgtype": "text",
        "text": {"content": text},
        "at": {"atMobiles": at_mobiles, "isAtAll": is_at_all},
    }

    return await _post_webhook(url, payload, "钉钉")


def base64_encode(data: bytes) -> str:
    """Base64 编码(避免在文件顶部引入 base64)"""
    import base64
    return base64.b64encode(data).decode("utf-8")


# ==================== 企业微信群机器人 ====================

async def _push_wechat_work(cfg: Dict[str, Any], title: str, content: str, extra: Dict[str, Any]) -> bool:
    """企业微信群机器人 webhook

    cfg 字段:
    - webhook_url: 企业微信群机器人 webhook 地址
    - mentioned_list: (可选)@的用户ID 或手机号,逗号分隔(@all 表示所有人)
    """
    url = cfg.get("webhook_url", "").strip()
    if not url:
        logger.warning("企业微信渠道缺少 webhook_url")
        return False

    mentioned_str = cfg.get("mentioned_list", "").strip()
    mentioned = [m.strip() for m in mentioned_str.split(",") if m.strip()] if mentioned_str else []

    text = f"【{title}】\n{content}"
    if extra:
        text += "\n"
        for k, v in extra.items():
            text += f"\n{k}: {v}"
    if mentioned:
        text += "\n" + " ".join(f"@{m}" for m in mentioned)

    payload = {
        "msgtype": "text",
        "text": {"content": text, "mentioned_list": mentioned, "mentioned_mobile_list": []},
    }

    return await _post_webhook(url, payload, "企业微信")


# ==================== 自定义 Webhook ====================

async def _push_custom_webhook(cfg: Dict[str, Any], event: str, title: str, content: str, extra: Dict[str, Any]) -> bool:
    """自定义 webhook(POST JSON)

    cfg 字段:
    - webhook_url: 目标 URL
    - headers: (可选)自定义请求头 JSON
    - secret: (可选)签名密钥,放在 X-Webhook-Secret 头中
    """
    url = cfg.get("webhook_url", "").strip()
    if not url:
        logger.warning("自定义 webhook 缺少 webhook_url")
        return False

    try:
        custom_headers = json.loads(cfg.get("headers", "{}")) if cfg.get("headers") else {}
    except Exception:
        custom_headers = {}

    secret = cfg.get("secret", "").strip()
    if secret:
        custom_headers["X-Webhook-Secret"] = secret

    payload = {
        "event": event,
        "title": title,
        "content": content,
        "extra": extra,
        "timestamp": int(time.time()),
    }

    return await _post_webhook(url, payload, "自定义webhook", extra_headers=custom_headers)


# ==================== HTTP 推送公共函数 ====================

async def _post_webhook(url: str, payload: Dict[str, Any], channel_name: str, extra_headers: Optional[Dict[str, str]] = None) -> bool:
    """发送 webhook POST 请求,5s 超时,失败返回 False"""
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if extra_headers:
        headers.update(extra_headers)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code < 400:
            logger.info(f"{channel_name} webhook 推送成功 status={resp.status_code}")
            return True
        logger.error(f"{channel_name} webhook 推送失败 status={resp.status_code} body={resp.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"{channel_name} webhook 请求异常: {e}")
        return False
