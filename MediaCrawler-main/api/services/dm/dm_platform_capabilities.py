# -*- coding: utf-8 -*-
"""
多平台私信能力注册表（阶段四任务 4.1）

对应 PRD 5.4 / 8.6 私信自动回复：
- 国内：抖音、小红书、B站、微博、知乎、X(原已支持)
- 海外：TikTok、Instagram、YouTube、Facebook

提供：
1. 各平台 DM 能力描述（支持监控/回复/语言）
2. 默认监控平台集合
3. 平台优先级（高价值客户优先路由到 X/抖音等高转化平台）
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DMPlatformCapability:
    """平台 DM 能力描述"""

    platform: str
    name_cn: str
    region: str  # domestic / overseas
    supports_fetch: bool = False  # 是否支持拉取私信
    supports_reply: bool = False  # 是否支持回复私信
    default_language: str = "zh"
    priority: int = 50  # 高价值客户路由优先级（越大越优先）
    fetch_method: str = "playwright"  # playwright / api
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "name_cn": self.name_cn,
            "region": self.region,
            "supports_fetch": self.supports_fetch,
            "supports_reply": self.supports_reply,
            "default_language": self.default_language,
            "priority": self.priority,
            "fetch_method": self.fetch_method,
            "notes": self.notes,
        }


# 平台能力表（supports_*标记当前是否已实现该能力）
PLATFORM_CAPABILITIES: Dict[str, DMPlatformCapability] = {
    # 国内平台
    "douyin": DMPlatformCapability(
        platform="douyin",
        name_cn="抖音",
        region="domestic",
        supports_fetch=True,
        supports_reply=True,
        default_language="zh",
        priority=80,
        fetch_method="playwright",
        notes="通过抖音创作者后台私信页面抓取/回复",
    ),
    "xiaohongshu": DMPlatformCapability(
        platform="xiaohongshu",
        name_cn="小红书",
        region="domestic",
        supports_fetch=True,
        supports_reply=True,
        default_language="zh",
        priority=85,
        fetch_method="playwright",
        notes="小红书蒲公英私信",
    ),
    "bilibili": DMPlatformCapability(
        platform="bilibili",
        name_cn="哔哩哔哩",
        region="domestic",
        supports_fetch=True,
        supports_reply=True,
        default_language="zh",
        priority=60,
        fetch_method="playwright",
    ),
    "weibo": DMPlatformCapability(
        platform="weibo",
        name_cn="微博",
        region="domestic",
        supports_fetch=True,
        supports_reply=True,
        default_language="zh",
        priority=70,
        fetch_method="playwright",
    ),
    "zhihu": DMPlatformCapability(
        platform="zhihu",
        name_cn="知乎",
        region="domestic",
        supports_fetch=True,
        supports_reply=True,
        default_language="zh",
        priority=55,
        fetch_method="playwright",
        notes="知乎私信页面",
    ),
    # 海外平台
    "x_twitter": DMPlatformCapability(
        platform="x_twitter",
        name_cn="X(Twitter)",
        region="overseas",
        supports_fetch=True,
        supports_reply=True,
        default_language="en",
        priority=90,
        fetch_method="api",
        notes="X GraphQL DM API",
    ),
    "tiktok": DMPlatformCapability(
        platform="tiktok",
        name_cn="TikTok",
        region="overseas",
        supports_fetch=True,
        supports_reply=True,
        default_language="en",
        priority=75,
        fetch_method="playwright",
    ),
    "instagram": DMPlatformCapability(
        platform="instagram",
        name_cn="Instagram",
        region="overseas",
        supports_fetch=True,
        supports_reply=True,
        default_language="en",
        priority=78,
        fetch_method="api",
        notes="Meta Graph API",
    ),
    "youtube": DMPlatformCapability(
        platform="youtube",
        name_cn="YouTube",
        region="overseas",
        supports_fetch=False,  # YouTube 无传统私信，仅评论 DM
        supports_reply=False,
        default_language="en",
        priority=40,
        fetch_method="api",
        notes="YouTube 私信已下线，仅评论回复",
    ),
    "facebook": DMPlatformCapability(
        platform="facebook",
        name_cn="Facebook",
        region="overseas",
        supports_fetch=True,
        supports_reply=True,
        default_language="en",
        priority=72,
        fetch_method="api",
        notes="Meta Graph API Messenger",
    ),
}


class DMPlatformRegistry:
    """多平台 DM 能力注册"""

    def list_platforms(self, region: Optional[str] = None) -> List[DMPlatformCapability]:
        if region:
            return [c for c in PLATFORM_CAPABILITIES.values() if c.region == region]
        return list(PLATFORM_CAPABILITIES.values())

    def list_supported(self, capability: str = "fetch") -> List[str]:
        """列出支持某能力的平台 ID"""
        if capability == "fetch":
            return [p for p, c in PLATFORM_CAPABILITIES.items() if c.supports_fetch]
        if capability == "reply":
            return [p for p, c in PLATFORM_CAPABILITIES.items() if c.supports_reply]
        return list(PLATFORM_CAPABILITIES.keys())

    def get(self, platform: str) -> Optional[DMPlatformCapability]:
        return PLATFORM_CAPABILITIES.get(platform)

    def default_monitor_platforms(self) -> List[str]:
        """默认监控平台集合（仅启用 supports_fetch=True 的）"""
        return [p for p, c in PLATFORM_CAPABILITIES.items() if c.supports_fetch]

    def route_priority(self, platform: str) -> int:
        """高价值客户跨平台路由优先级"""
        cap = PLATFORM_CAPABILITIES.get(platform)
        return cap.priority if cap else 50

    def best_platform_for_high_value(self, owned_platforms: List[str]) -> str:
        """从用户已配置的账号池中选出最适合高价值客户对话的平台"""
        if not owned_platforms:
            return ""
        ranked = sorted(
            owned_platforms,
            key=lambda p: PLATFORM_CAPABILITIES.get(p, DMPlatformCapability(platform=p, name_cn=p, region="domestic")).priority,
            reverse=True,
        )
        return ranked[0]


_registry: Optional[DMPlatformRegistry] = None


def get_dm_platform_registry() -> DMPlatformRegistry:
    global _registry
    if _registry is None:
        _registry = DMPlatformRegistry()
    return _registry
