# -*- coding: utf-8 -*-
"""
发布任务 / 结果数据类

迁移自 GEO-main 的 publish_service.py，调整为：
1. 全 async 友好（不依赖同步 requests）
2. 字段对齐 MediaCrawler 开发计划的 PublishTask 表设计
3. 增加 account_id 字段支持 Cookie 池
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class PublishStatus(str, Enum):
    """发布状态"""

    PENDING = "pending"
    PUBLISHING = "publishing"
    SUCCESS = "success"
    PARTIAL = "partial"  # 多平台发布时部分成功
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"  # 风控拦截 / 配额耗尽


class PublishErrorCode(str, Enum):
    """跨平台发布错误码。"""

    AUTH_EXPIRED = "AUTH_EXPIRED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_MEDIA = "INVALID_MEDIA"
    CONTENT_REJECTED = "CONTENT_REJECTED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    SELECTOR_CHANGED = "SELECTOR_CHANGED"
    TIMEOUT = "TIMEOUT"
    NO_AVAILABLE_ACCOUNT = "NO_AVAILABLE_ACCOUNT"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    UNKNOWN = "UNKNOWN"


@dataclass
class PublishResult:
    """单平台发布结果，统一字段与历史字段双向兼容。"""

    success: bool
    platform: str
    url: Optional[str] = None  # 发布后的链接
    platform_id: Optional[str] = None  # 平台内容 ID（tweet_id / note_id 等）
    message: str = ""
    status: str = ""  # 已发布 / 审核中 / 失败原因
    debug_info: List[str] = field(default_factory=list)
    error: Optional[str] = None
    account_id: Optional[int] = None  # 用的哪个账号
    retryable: bool = True  # 是否可重试

    task_id: Optional[str] = None
    post_id: Optional[str] = None
    post_url: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def __post_init__(self) -> None:
        self.post_url = self.post_url or self.url
        self.url = self.url or self.post_url
        self.post_id = self.post_id or self.platform_id
        self.platform_id = self.platform_id or self.post_id
        self.error_message = self.error_message or self.error
        self.error = self.error or self.error_message
        if isinstance(self.error_code, PublishErrorCode):
            self.error_code = self.error_code.value

    def finalize(self, *, task_id: Optional[str] = None) -> "PublishResult":
        """补齐统一协议字段，并返回自身。"""
        if task_id and not self.task_id:
            self.task_id = task_id
        self.__post_init__()
        if not self.started_at:
            self.started_at = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        if not self.finished_at:
            self.finished_at = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        if self.success:
            self.error_code = None
            self.error_message = None
            self.error = None
            self.retryable = False
        elif not self.error_code:
            self.error_code = PublishErrorCode.UNKNOWN.value
        return self

    def to_dict(self) -> Dict[str, Any]:
        self.__post_init__()
        return {
            "success": self.success,
            "platform": self.platform,
            "account_id": self.account_id,
            "task_id": self.task_id,
            "post_id": self.post_id,
            "post_url": self.post_url,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retryable": self.retryable,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            # 兼容旧版字段
            "url": self.url,
            "platform_id": self.platform_id,
            "message": self.message,
            "status": self.status,
            "debug_info": self.debug_info,
            "error": self.error,
        }


@dataclass
class PublishTask:
    """统一发布任务

    一次任务可包含多个目标平台，结果聚合到 platform_results。
    """

    source_post_id: str = ""  # 来源热点帖子 ID（可空）
    title: str = ""
    content: str = ""
    keywords: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)  # 本地图片路径
    video_path: Optional[str] = None  # 视频文件路径
    target_platforms: List[str] = field(default_factory=list)  # ["douyin", "xhs", ...]
    user_id: Optional[int] = None  # 关联的用户 ID（取该用户的 cookie）
    task_id: Optional[str] = None  # UUID
    status: PublishStatus = PublishStatus.PENDING
    platform_results: Dict[str, PublishResult] = field(default_factory=dict)
    scheduled_at: Optional[int] = None  # 定时发布时间戳
    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source_post_id": self.source_post_id,
            "title": self.title,
            "content": self.content,
            "keywords": self.keywords,
            "images": self.images,
            "video_path": self.video_path,
            "target_platforms": self.target_platforms,
            "user_id": self.user_id,
            "status": self.status.value,
            "platform_results": {k: v.to_dict() for k, v in self.platform_results.items()},
            "scheduled_at": self.scheduled_at,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "error_message": self.error_message,
        }
