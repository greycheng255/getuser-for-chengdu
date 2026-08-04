# -*- coding: utf-8 -*-
"""
私信数据模型

对应 PRD 5.4 私信自动回复。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageIntent(str, Enum):
    """私信意图"""

    INQUIRY = "inquiry"  # 咨询（产品/价格/服务）
    COMPLAINT = "complaint"  # 投诉
    COOPERATION = "cooperation"  # 合作
    CHAT = "chat"  # 闲聊
    HIGH_VALUE = "high_value"  # 高价值客户（大单/代理）
    UNKNOWN = "unknown"


class ConversationState(str, Enum):
    """会话状态"""

    NEW = "new"  # 新私信，待处理
    REPLIED = "replied"  # 已自动回复
    NEEDS_HUMAN = "needs_human"  # 需转人工
    RESOLVED = "resolved"  # 已解决
    IGNORED = "ignored"  # 已忽略


@dataclass
class DirectMessage:
    """私信记录"""

    id: Optional[int] = None
    platform: str = ""
    conversation_id: str = ""  # 平台会话 ID
    sender_id: str = ""
    sender_name: str = ""
    message_text: str = ""
    intent: str = MessageIntent.UNKNOWN.value
    confidence: float = 0.0  # 意图识别置信度 0~1
    state: str = ConversationState.NEW.value
    reply_text: str = ""  # 自动回复内容
    is_replied: bool = False
    needs_human: bool = False
    received_at: Optional[datetime] = None
    replied_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "platform": self.platform,
            "conversation_id": self.conversation_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "message_text": self.message_text,
            "intent": self.intent,
            "confidence": self.confidence,
            "state": self.state,
            "reply_text": self.reply_text,
            "is_replied": self.is_replied,
            "needs_human": self.needs_human,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "replied_at": self.replied_at.isoformat() if self.replied_at else None,
        }
