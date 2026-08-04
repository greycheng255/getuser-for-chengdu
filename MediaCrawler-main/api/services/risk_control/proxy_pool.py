# -*- coding: utf-8 -*-
"""
IP 代理池

对应 PRD 5.6 风控优化 - IP 代理池：海外平台匹配对应国家 IP。

设计：
1. 从环境变量 PROXY_POOL 加载代理列表（格式：protocol://user:pass@host:port）
2. 按平台/国家匹配代理
3. 失败自动剔除 + 健康检查
"""

import logging
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 平台 → 推荐国家
PLATFORM_COUNTRY = {
    "x_twitter": "US",
    "douyin": "CN",
    "xiaohongshu": "CN",
    "bilibili": "CN",
    "weibo": "CN",
    "zhihu": "CN",
    "kuaishou": "CN",
    "wechat_public": "CN",
}


@dataclass
class ProxyInfo:
    url: str  # protocol://user:pass@host:port
    country: str = ""
    platform: str = ""  # 专属平台（空则通用）
    failures: int = 0
    successes: int = 0
    is_active: bool = True


class ProxyPool:
    """IP 代理池"""

    def __init__(self):
        self._proxies: List[ProxyInfo] = []
        self._load_from_env()

    def _load_from_env(self):
        """从环境变量加载代理

        格式：PROXY_POOL="http://user:pass@1.2.3.4:8080|||http://user:pass@5.6.7.8:8080"
        或   PROXY_POOL="US:http://...|||CN:http://..."
        """
        raw = os.environ.get("PROXY_POOL", "").strip()
        if not raw:
            return
        for item in raw.split("|||"):
            item = item.strip()
            if not item:
                continue
            country = ""
            if ":" in item and "://" not in item.split(":")[0]:
                # 带国家前缀：US:http://...
                parts = item.split(":", 1)
                country = parts[0].strip()
                url = parts[1].strip()
            else:
                url = item
            self._proxies.append(ProxyInfo(url=url, country=country))
        logger.info(f"[ProxyPool] 已加载 {len(self._proxies)} 个代理")

    def get_proxy(self, platform: str = "") -> Optional[str]:
        """获取一个代理（按平台匹配国家）

        Returns:
            代理 URL 字符串，无可用时返回 None
        """
        if not self._proxies:
            return None
        country = PLATFORM_COUNTRY.get(platform, "")
        # 优先匹配国家 + 活跃
        candidates = [
            p for p in self._proxies
            if p.is_active and (not country or not p.country or p.country == country)
        ]
        if not candidates:
            candidates = [p for p in self._proxies if p.is_active]
        if not candidates:
            return None
        # 按成功率排序
        chosen = max(candidates, key=lambda x: (x.successes, -x.failures))
        return chosen.url

    def get_proxy_by_country(
        self, platform: str = "", country: str = ""
    ) -> Optional[str]:
        """按国家精确匹配代理（地域适配专用）

        阶段二 P1 任务 2.2：海外机器人执行互动时强制使用对应国家 IP。
        优先级：
        1. country + platform 专属代理
        2. country 通用代理
        3. platform 推荐国家代理（PLATFORM_COUNTRY 兜底）
        4. 任意活跃代理

        Args:
            platform: 平台名
            country: 国家代码（CN/US/EU/SEA）

        Returns:
            代理 URL，无可用时返回 None
        """
        if not self._proxies:
            return None
        # 1. country + platform 专属
        if country and platform:
            candidates = [
                p for p in self._proxies
                if p.is_active and p.country == country and (
                    not p.platform or p.platform == platform
                )
            ]
            if candidates:
                chosen = max(candidates, key=lambda x: (x.successes, -x.failures))
                return chosen.url
        # 2. country 通用
        if country:
            candidates = [
                p for p in self._proxies
                if p.is_active and p.country == country
            ]
            if candidates:
                chosen = max(candidates, key=lambda x: (x.successes, -x.failures))
                return chosen.url
        # 3. platform 推荐国家
        recommended = PLATFORM_COUNTRY.get(platform, "")
        if recommended:
            candidates = [
                p for p in self._proxies
                if p.is_active and (not p.country or p.country == recommended)
            ]
            if candidates:
                chosen = max(candidates, key=lambda x: (x.successes, -x.failures))
                return chosen.url
        # 4. 任意活跃代理
        candidates = [p for p in self._proxies if p.is_active]
        if not candidates:
            return None
        chosen = max(candidates, key=lambda x: (x.successes, -x.failures))
        return chosen.url

    def mark_success(self, proxy_url: str):
        for p in self._proxies:
            if p.url == proxy_url:
                p.successes += 1
                p.failures = 0
                break

    def mark_failure(self, proxy_url: str):
        for p in self._proxies:
            if p.url == proxy_url:
                p.failures += 1
                if p.failures >= 5:
                    p.is_active = False
                    logger.warning(f"[ProxyPool] 代理 {proxy_url} 连续失败 5 次，已禁用")
                break

    def list_proxies(self) -> List[Dict]:
        return [
            {
                "url": p.url,
                "country": p.country,
                "is_active": p.is_active,
                "successes": p.successes,
                "failures": p.failures,
            }
            for p in self._proxies
        ]

    def add_proxy(self, url: str, country: str = "", platform: str = "") -> bool:
        for p in self._proxies:
            if p.url == url:
                p.is_active = True
                return True
        self._proxies.append(ProxyInfo(url=url, country=country, platform=platform))
        return True

    def remove_proxy(self, url: str) -> bool:
        before = len(self._proxies)
        self._proxies = [p for p in self._proxies if p.url != url]
        return len(self._proxies) < before


_pool: Optional[ProxyPool] = None


def get_proxy_pool() -> ProxyPool:
    global _pool
    if _pool is None:
        _pool = ProxyPool()
    return _pool
