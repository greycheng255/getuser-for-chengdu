# -*- coding: utf-8 -*-
"""
互动任务 / 结果数据类

第二阶段：多平台互动能力扩展。
对应 PRD 5.4 智能机器人互动：点赞 / 评论 / 回复 / 关注。
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class InteractionType(str, Enum):
    """互动类型"""

    LIKE = "like"  # 点赞
    COMMENT = "comment"  # 评论
    REPLY = "reply"  # 回复评论
    FOLLOW = "follow"  # 关注
    COLLECT = "collect"  # 收藏
    RETWEET = "retweet"  # 转发/转推


class InteractionStatus(str, Enum):
    """互动状态"""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # 风控拦截 / 配额耗尽
    RETRYING = "retrying"


@dataclass
class InteractionResult:
    """单次互动结果"""

    success: bool
    platform: str
    interaction_type: str  # like / comment / reply / follow
    target_url: str = ""  # 目标帖子/评论 URL
    target_id: str = ""  # 平台内容 ID
    content: str = ""  # 评论内容（点赞为空）
    message: str = ""
    error: Optional[str] = None
    account_id: Optional[int] = None
    retryable: bool = True
    debug_info: List[str] = field(default_factory=list)
    timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "platform": self.platform,
            "interaction_type": self.interaction_type,
            "target_url": self.target_url,
            "target_id": self.target_id,
            "content": self.content,
            "message": self.message,
            "error": self.error,
            "account_id": self.account_id,
            "retryable": self.retryable,
            "debug_info": self.debug_info,
            "timestamp": self.timestamp,
        }


@dataclass
class InteractionTask:
    """互动任务（可批量聚合多平台）"""

    interaction_type: str  # like / comment / reply / follow
    target_url: str = ""  # 帖子 URL
    target_id: str = ""  # 评论 ID（reply 时用）
    content: str = ""  # 评论内容
    target_platforms: List[str] = field(default_factory=list)
    user_id: Optional[int] = None
    task_id: Optional[str] = None
    status: InteractionStatus = InteractionStatus.PENDING
    platform_results: Dict[str, InteractionResult] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "interaction_type": self.interaction_type,
            "target_url": self.target_url,
            "target_id": self.target_id,
            "content": self.content,
            "target_platforms": self.target_platforms,
            "user_id": self.user_id,
            "status": self.status.value,
            "platform_results": {k: v.to_dict() for k, v in self.platform_results.items()},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
        }


@dataclass
class MonitoredComment:
    """监控到的评论（多平台统一结构）"""

    platform: str
    post_url: str
    comment_id: str = ""
    comment_text: str = ""
    author_id: str = ""
    author_name: str = ""
    parent_comment_id: str = ""  # 回复的父评论 ID（如果是回复）
    is_reply_to_me: bool = False  # 是否是回复我的评论
    needs_reply: bool = False  # 是否需要回复
    replied: bool = False
    captured_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "post_url": self.post_url,
            "comment_id": self.comment_id,
            "comment_text": self.comment_text,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "parent_comment_id": self.parent_comment_id,
            "is_reply_to_me": self.is_reply_to_me,
            "needs_reply": self.needs_reply,
            "replied": self.replied,
            "captured_at": self.captured_at,
        }
