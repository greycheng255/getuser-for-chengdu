# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/proxy/proxy_ip_pool.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/2 13:45
# @Desc    : IP proxy pool implementation
import random
import time
from typing import Dict, List
from urllib.parse import unquote, urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
from tools.httpx_util import make_async_client

import config
from proxy.providers import (
    new_kuai_daili_proxy,
    new_wandou_http_proxy,
)
from tools import utils

from .base_proxy import ProxyProvider
from .types import IpInfoModel, ProviderNameEnum


class ProxyIpPool:

    def __init__(
        self, ip_pool_count: int, enable_validate_ip: bool, ip_provider: ProxyProvider
    ) -> None:
        """

        Args:
            ip_pool_count:
            enable_validate_ip:
            ip_provider:
        """
        self.valid_ip_url = "https://echo.apifox.cn/"  # URL to validate if IP is valid
        self.ip_pool_count = ip_pool_count
        self.enable_validate_ip = enable_validate_ip
        self.proxy_list: List[IpInfoModel] = []
        self.ip_provider: ProxyProvider = ip_provider
        self.current_proxy: IpInfoModel | None = None  # Currently used proxy
        self._bad_ips: set = set()  # 被标记为坏的IP（被风控的IP）
        self._bad_ip_marked_at: Dict[str, float] = {}  # IP被标记的时间戳

    async def load_proxies(self) -> None:
        """
        Load IP proxies
        Returns:

        """
        self.proxy_list = await self.ip_provider.get_proxy(self.ip_pool_count)

    async def _is_valid_proxy(self, proxy: IpInfoModel) -> bool:
        """
        Validate if proxy IP is valid
        :param proxy:
        :return:
        """
        utils.logger.info(
            f"[ProxyIpPool._is_valid_proxy] testing {proxy.ip} is it valid "
        )
        try:
            # httpx 0.28.1 requires passing proxy URL string directly, not a dictionary
            if proxy.user and proxy.password:
                proxy_url = f"http://{proxy.user}:{proxy.password}@{proxy.ip}:{proxy.port}"
            else:
                proxy_url = f"http://{proxy.ip}:{proxy.port}"

            async with make_async_client(proxy=proxy_url) as client:
                response = await client.get(self.valid_ip_url)
            if response.status_code == 200:
                return True
            else:
                return False
        except Exception as e:
            utils.logger.info(
                f"[ProxyIpPool._is_valid_proxy] testing {proxy.ip} err: {e}"
            )
            raise e

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def get_proxy(self) -> IpInfoModel:
        """
        Randomly extract a proxy IP from the proxy pool (skip bad IPs)
        :return:
        """
        # 清理过期的坏IP标记（标记超过10分钟的IP恢复可用）
        self._cleanup_expired_bad_ips()

        if len(self.proxy_list) == 0:
            await self._reload_proxies()

        # 过滤掉坏IP
        available = [p for p in self.proxy_list if p.ip not in self._bad_ips]
        if not available:
            # 所有IP都是坏IP，清除标记重新使用
            if self._bad_ips:
                utils.logger.warning(
                    f"[ProxyIpPool.get_proxy] All {len(self.proxy_list)} IPs are marked bad, clearing marks and retrying"
                )
                self.clear_bad_ips()
                available = self.proxy_list
            else:
                # 没有可用IP，重新加载
                await self._reload_proxies()
                available = self.proxy_list

        proxy = random.choice(available)
        self.proxy_list.remove(proxy)  # Remove an IP once extracted
        if self.enable_validate_ip:
            if not await self._is_valid_proxy(proxy):
                raise Exception(
                    "[ProxyIpPool.get_proxy] current ip invalid and again get it"
                )
        self.current_proxy = proxy  # Save currently used proxy
        return proxy

    def mark_bad_ip(self, ip: str, reason: str = "") -> None:
        """标记IP为坏IP（被风控的IP）

        Args:
            ip: 被标记的IP地址
            reason: 标记原因
        """
        if ip:
            self._bad_ips.add(ip)
            self._bad_ip_marked_at[ip] = time.time()
            utils.logger.warning(
                f"[ProxyIpPool.mark_bad_ip] Marked IP {ip} as bad (reason: {reason or 'unknown'}). "
                f"Total bad IPs: {len(self._bad_ips)}"
            )

    def clear_bad_ips(self) -> None:
        """清除所有坏IP标记（给IP恢复机会）"""
        cleared = len(self._bad_ips)
        self._bad_ips.clear()
        self._bad_ip_marked_at.clear()
        if cleared:
            utils.logger.info(f"[ProxyIpPool.clear_bad_ips] Cleared {cleared} bad IP marks")

    def is_ip_bad(self, ip: str) -> bool:
        """检查IP是否被标记为坏IP"""
        return ip in self._bad_ips

    def _cleanup_expired_bad_ips(self, max_age_seconds: int = 600) -> None:
        """清理过期的坏IP标记（默认10分钟后恢复）

        Args:
            max_age_seconds: 坏IP标记的最大保留时间（秒）
        """
        if not self._bad_ip_marked_at:
            return
        now = time.time()
        expired = [ip for ip, ts in self._bad_ip_marked_at.items()
                   if now - ts > max_age_seconds]
        for ip in expired:
            self._bad_ips.discard(ip)
            del self._bad_ip_marked_at[ip]
        if expired:
            utils.logger.info(
                f"[ProxyIpPool._cleanup_expired_bad_ips] Restored {len(expired)} IPs from bad list: {expired}"
            )

    def is_current_proxy_expired(self, buffer_seconds: int = 30) -> bool:
        """
        Check if current proxy has expired
        Args:
            buffer_seconds: Buffer time (seconds), how many seconds ahead to consider expired
        Returns:
            bool: True means expired or no current proxy, False means still valid
        """
        if self.current_proxy is None:
            return True
        return self.current_proxy.is_expired(buffer_seconds)

    async def get_or_refresh_proxy(self, buffer_seconds: int = 30) -> IpInfoModel:
        """
        Get current proxy, automatically refresh if expired
        Call this method before each request to ensure proxy is valid
        Args:
            buffer_seconds: Buffer time (seconds), how many seconds ahead to consider expired
        Returns:
            IpInfoModel: Valid proxy IP information
        """
        if self.is_current_proxy_expired(buffer_seconds):
            utils.logger.info(
                f"[ProxyIpPool.get_or_refresh_proxy] Current proxy expired or not set, getting new proxy..."
            )
            return await self.get_proxy()
        return self.current_proxy

    async def _reload_proxies(self):
        """
        Reload proxy pool
        :return:
        """
        self.proxy_list = []
        await self.load_proxies()


class StaticProxyProvider(ProxyProvider):
    async def get_proxy(self, num: int) -> List[IpInfoModel]:
        proxy_url = getattr(config, "STATIC_PROXY_URL", "")
        if not proxy_url:
            utils.logger.warning("[StaticProxyProvider] STATIC_PROXY_URL is not configured!")
            return []

        try:
            parsed = urlparse(proxy_url)
            scheme = parsed.scheme or "http"
            if scheme not in {"http", "https"}:
                utils.logger.error(f"[StaticProxyProvider] Unsupported proxy scheme: {scheme}")
                return []

            ip = parsed.hostname or ""
            port = parsed.port or (443 if scheme == "https" else 80)
            if not ip:
                utils.logger.error("[StaticProxyProvider] STATIC_PROXY_URL host is empty!")
                return []

            return [
                IpInfoModel(
                    ip=ip,
                    port=port,
                    user=unquote(parsed.username or ""),
                    password=unquote(parsed.password or ""),
                    protocol=f"{scheme}://",
                    # Static proxy doesn't expire.
                    expired_time_ts=int(time.time()) + 99999999,
                )
            ]
        except Exception as e:
            utils.logger.error(f"[StaticProxyProvider] Parse static proxy url error: {e}")
            return []


IpProxyProvider: Dict[str, ProxyProvider] = {
    ProviderNameEnum.KUAI_DAILI_PROVIDER.value: new_kuai_daili_proxy(),
    ProviderNameEnum.WANDOU_HTTP_PROVIDER.value: new_wandou_http_proxy(),
    ProviderNameEnum.STATIC_PROVIDER.value: StaticProxyProvider(),
}


async def create_ip_pool(ip_pool_count: int, enable_validate_ip: bool) -> ProxyIpPool:
    """
    Create IP proxy pool
    :param ip_pool_count: Number of IPs in the pool
    :param enable_validate_ip: Whether to enable IP proxy validation
    :return:
    """
    is_static = config.IP_PROXY_PROVIDER_NAME == ProviderNameEnum.STATIC_PROVIDER.value
    pool = ProxyIpPool(
        ip_pool_count=ip_pool_count,
        enable_validate_ip=False if is_static else enable_validate_ip,
        ip_provider=IpProxyProvider.get(config.IP_PROXY_PROVIDER_NAME),
    )
    await pool.load_proxies()
    return pool


if __name__ == "__main__":
    pass
