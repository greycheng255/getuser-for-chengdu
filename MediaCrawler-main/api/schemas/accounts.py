# -*- coding: utf-8 -*-
"""统一账号的业务枚举与 API 数据契约。"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AccountRole(str, Enum):
    PUBLISHER = "publisher"
    INTERACTOR = "interactor"
    BOTH = "both"


class AccountStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    INVALID = "invalid"
    NEEDS_RELOGIN = "needs_relogin"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"


class AccountCapability(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    ARTICLE = "article"
    COMMENT = "comment"
    DIRECT_MESSAGE = "dm"


CANONICAL_PLATFORMS = frozenset(
    {
        "douyin",
        "xiaohongshu",
        "bilibili",
        "weibo",
        "zhihu",
        "x_twitter",
        "x_twitter_publisher",
        "kuaishou",
        "wechat_public",
        "wechat_channels",
        "toutiao",
        "tiktok",
        "instagram",
        "youtube",
        "facebook",
    }
)

PLATFORM_ALIASES = {
    "dy": "douyin",
    "xhs": "xiaohongshu",
    "ks": "kuaishou",
    "bili": "bilibili",
    "x": "x_twitter",
    "twitter": "x_twitter",
    "wechat": "wechat_public",
    "channels": "wechat_channels",
}


def normalize_platform(value: str) -> str:
    """将 API 平台输入转换成数据库使用的规范平台编码。"""

    normalized = (value or "").strip().lower().replace("-", "_")
    normalized = PLATFORM_ALIASES.get(normalized, normalized)
    if normalized not in CANONICAL_PLATFORMS:
        supported = ", ".join(sorted(CANONICAL_PLATFORMS))
        raise ValueError(f"不支持的平台编码: {value!r}；支持: {supported}")
    return normalized


def _normalize_capabilities(values: List[str]) -> List[str]:
    result: List[str] = []
    valid = {item.value for item in AccountCapability}
    for value in values:
        item = str(value).strip().lower()
        if item not in valid:
            raise ValueError(f"不支持的账号能力: {value!r}")
        if item not in result:
            result.append(item)
    return result


class AccountCreateRequest(BaseModel):
    account_id: Optional[str] = Field(None, min_length=1, max_length=64)
    platform: str
    account_name: str = Field("", max_length=128)
    role: AccountRole = AccountRole.PUBLISHER
    status: AccountStatus = AccountStatus.ACTIVE
    auth_data: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)
    group_name: str = Field("", max_length=64)
    region: str = Field("", max_length=16)
    priority: int = Field(0, ge=0, le=10000)
    weight: int = Field(100, ge=0, le=10000)
    health_score: int = Field(100, ge=0, le=100)
    daily_limit: int = Field(0, ge=0)

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str) -> str:
        return normalize_platform(value)

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("account_id 不能为空")
        return normalized

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: List[str]) -> List[str]:
        return _normalize_capabilities(values)


class AccountUpdateRequest(BaseModel):
    platform: Optional[str] = None
    account_name: Optional[str] = Field(None, max_length=128)
    role: Optional[AccountRole] = None
    status: Optional[AccountStatus] = None
    auth_data: Optional[Dict[str, Any]] = None
    capabilities: Optional[List[str]] = None
    group_name: Optional[str] = Field(None, max_length=64)
    region: Optional[str] = Field(None, max_length=16)
    priority: Optional[int] = Field(None, ge=0, le=10000)
    weight: Optional[int] = Field(None, ge=0, le=10000)
    health_score: Optional[int] = Field(None, ge=0, le=100)
    daily_limit: Optional[int] = Field(None, ge=0)

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: Optional[str]) -> Optional[str]:
        return normalize_platform(value) if value is not None else None

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        return _normalize_capabilities(values) if values is not None else None


class AccountResponse(BaseModel):
    id: int
    account_id: str
    owner_user_id: str
    platform: str
    account_name: str
    role: AccountRole
    status: AccountStatus
    auth_configured: bool
    auth_preview: Dict[str, str] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)
    group_name: str
    region: str
    priority: int
    weight: int
    health_score: int
    daily_limit: int
    today_count: int
    success_count: int
    failure_count: int
    cooldown_until: int
    in_cooldown: bool
    last_used_ts: int
    created_ts: int
    updated_ts: int


class AccountListResponse(BaseModel):
    items: List[AccountResponse]
    total: int
    page: int
    page_size: int


class AccountStatsResponse(BaseModel):
    total: int
    by_platform: Dict[str, int]
    by_role: Dict[str, int]
    by_status: Dict[str, int]


class AccountBatchCreateRequest(BaseModel):
    items: List[AccountCreateRequest] = Field(..., min_length=1, max_length=500)


class AccountBatchCreateResponse(BaseModel):
    created: List[AccountResponse]
    failed: List[Dict[str, Any]]
