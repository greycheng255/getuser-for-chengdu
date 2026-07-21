# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/core.py
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

import asyncio
import json
import os
import random
import re
import urllib.parse
from asyncio import Task
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

import config
from base.base_crawler import AbstractCrawler
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import douyin as douyin_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import DouYinClient
from .exception import DataFetchError
from .field import PublishTimeType, SearchSortType
from .help import parse_video_info_from_url, parse_creator_info_from_url
from .login import DouYinLogin


class DouYinCrawler(AbstractCrawler):
    context_page: Page
    dy_client: DouYinClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://www.douyin.com"
        self.cookie_urls = [
            "https://douyin.com",
            "https://www.douyin.com",
            self.index_url,
            "https://creator.douyin.com",
            "https://douhot.douyin.com",
            "https://live.douyin.com",
        ]
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh
        self._account_pool = None  # 多账号池（Cookie+IP组合管理）

    async def start(self) -> None:
        # 启动时强制重新加载 .env 文件，确保用户更新的 cookie 能被使用
        try:
            from dotenv import load_dotenv
            from pathlib import Path
            env_file = Path(__file__).parent.parent.parent / ".env"
            if env_file.exists():
                load_dotenv(env_file, override=True)
                utils.logger.info(f"[DouYinCrawler.start] Reloaded .env file: {env_file}")
                # 清除 cookie_manager 的内存缓存，强制从 .env 重新读取
                import api.services.cookie_manager as cm
                cm.cookie_cache.clear()
                utils.logger.info("[DouYinCrawler.start] Cleared cookie_manager cache")
        except Exception as e:
            utils.logger.warning(f"[DouYinCrawler.start] Failed to reload .env: {e}")

        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        # 初始化多账号池：从Cookie池加载所有Cookie到账号池
        # 注意：网卡（IP）不再固定绑定到账号，而是每次请求时动态随机分配
        try:
            from api.services.account_pool import init_account_pool, get_available_interfaces
            from api.services.cookie_manager import get_cookie_pool
            # 从Cookie池获取所有Cookie
            cookie_pool = get_cookie_pool("dy")
            if cookie_pool:
                self._account_pool = await init_account_pool(platform="dy")
                # 清空数据库加载的旧账号,避免使用失效Cookie
                # cookie_manager 是唯一数据源,只用最新的有效Cookie
                if self._account_pool.accounts:
                    utils.logger.info(
                        f"[DouYinCrawler.start] Clearing {len(self._account_pool.accounts)} stale DB accounts, "
                        f"will use {len(cookie_pool)} fresh cookies from cookie_manager"
                    )
                    self._account_pool.accounts = []
                    self._account_pool.current_account = None
                # 探测多网卡（用于动态分配）
                interfaces = get_available_interfaces()
                for i, cookie_str in enumerate(cookie_pool):
                    await self._account_pool.add_account(
                        cookie=cookie_str,
                        cookie_alias=f"账号{i+1}",
                        proxy_ip=httpx_proxy_format or "",
                        # 不再传入network_interface，由get_healthy_account动态随机分配
                    )
                utils.logger.info(
                    f"[DouYinCrawler.start] Account pool initialized with {len(cookie_pool)} cookies, "
                    f"available interfaces (dynamic): {interfaces}"
                )
            else:
                utils.logger.info("[DouYinCrawler.start] No cookie pool found, using single cookie mode")
        except Exception as e:
            utils.logger.warning(f"[DouYinCrawler.start] Failed to init account pool: {e}, using single cookie mode")

        async with async_playwright() as playwright:
            # Select startup mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[DouYinCrawler] 使用CDP模式启动浏览器")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    None,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[DouYinCrawler] 使用标准模式启动浏览器")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    user_agent=None,
                    headless=config.HEADLESS,
                )
                # 反检测脚本已在 launch_browser 中通过 add_init_script 注入（首屏前生效）

            self.context_page = await self.browser_context.new_page()
            # 导航前模拟真人行为：先设置合理的 Referer，再访问
            try:
                await self.context_page.goto("https://www.baidu.com", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(random.uniform(1, 2))
            except Exception:
                pass
            await self.context_page.goto(self.index_url, wait_until="domcontentloaded", timeout=120000)
            await asyncio.sleep(random.uniform(3, 6))  # 随机等待，模拟真人浏览

            self.dy_client = await self.create_douyin_client(httpx_proxy_format)
            
            # 始终优先从 cookie_manager 获取最新 Cookie（单一数据源，避免浏览器持久化 Cookie 污染）
            # cookie_manager 会自动从 .env 加载，且 set_cookie 时会同步更新 .env 和内存
            browser_cookies = await self.browser_context.cookies()
            browser_cookie_dict = {c["name"]: c["value"] for c in browser_cookies}
            has_browser_sessionid = "sessionid" in browser_cookie_dict
            utils.logger.info(f"[DouYinCrawler.start] Browser persistent state: {len(browser_cookie_dict)} cookies, has sessionid={has_browser_sessionid}")
            
            # 始终从 cookie_manager 获取最新 Cookie 设置到 HTTP 客户端
            cm_cookie_str = ""
            try:
                from api.services.cookie_manager import get_cookie
                cm_cookie_str = get_cookie("dy") or ""
                if cm_cookie_str:
                    self.dy_client.headers["Cookie"] = cm_cookie_str
                    self.dy_client.cookie_dict = utils.convert_str_cookie_to_dict(cm_cookie_str)
                    utils.logger.info(f"[DouYinCrawler.start] Set HTTP client cookie from cookie_manager, length={len(cm_cookie_str)}, has sessionid={'sessionid' in self.dy_client.cookie_dict}")
                else:
                    utils.logger.warning("[DouYinCrawler.start] cookie_manager returned empty cookie, falling back to browser persistent cookies")
                    if has_browser_sessionid:
                        browser_cookie_str = "; ".join([f"{k}={v}" for k, v in browser_cookie_dict.items()])
                        self.dy_client.headers["Cookie"] = browser_cookie_str
                        self.dy_client.cookie_dict = browser_cookie_dict
            except ImportError:
                utils.logger.warning("[DouYinCrawler.start] cookie_manager not available, using browser persistent cookies")
                if has_browser_sessionid:
                    browser_cookie_str = "; ".join([f"{k}={v}" for k, v in browser_cookie_dict.items()])
                    self.dy_client.headers["Cookie"] = browser_cookie_str
                    self.dy_client.cookie_dict = browser_cookie_dict
            
            # 将 cookie_manager 的 Cookie 同步注入浏览器上下文（确保浏览器和 HTTP 客户端使用同一份 Cookie）
            if cm_cookie_str:
                try:
                    login_obj_for_sync = DouYinLogin(
                        login_type="cookie",
                        login_phone="",
                        browser_context=self.browser_context,
                        context_page=self.context_page,
                        cookie_str=cm_cookie_str,
                    )
                    await login_obj_for_sync.login_by_cookies()
                    utils.logger.info("[DouYinCrawler.start] Synced cookie_manager cookie to browser context")
                except Exception as e:
                    utils.logger.warning(f"[DouYinCrawler.start] Failed to sync cookie to browser context: {e}")
            
            # 从 cookie 提取原始 User-Agent
            try:
                import base64, urllib.parse, json
                druid_info = self.dy_client.cookie_dict.get("__druidClientInfo", "")
                if druid_info:
                    decoded = urllib.parse.unquote(druid_info)
                    try:
                        decoded = base64.b64decode(decoded).decode('utf-8', errors='ignore')
                    except Exception:
                        pass
                    decoded = urllib.parse.unquote(decoded)
                    info_json = json.loads(decoded)
                    original_ua = info_json.get("userAgent", "")
                    if original_ua:
                        self.dy_client.headers["User-Agent"] = original_ua
                        utils.logger.info(f"[DouYinCrawler.start] Updated User-Agent from cookie: {original_ua[:60]}...")
            except Exception as e:
                utils.logger.warning(f"[DouYinCrawler.start] Failed to extract UA: {e}")
            
            # 检查登录状态，重试机制
            utils.logger.info("[DouYinCrawler.start] Checking login state...")
            login_success = False
            for attempt in range(3):
                try:
                    login_success = await self.dy_client.pong(browser_context=self.browser_context)
                    utils.logger.info(f"[DouYinCrawler.start] Login check result (attempt {attempt+1}): {login_success}")
                    if login_success:
                        break
                except Exception as e:
                    utils.logger.warning(f"[DouYinCrawler.start] Login check attempt {attempt+1} failed: {e}")
                    await asyncio.sleep(2)
            
            # 如果浏览器持久化状态已登录但 pong 失败，尝试刷新页面再检查
            if not login_success and has_browser_sessionid:
                utils.logger.info("[DouYinCrawler.start] Browser has sessionid but pong failed, refreshing page...")
                await self.context_page.goto(self.index_url, wait_until="networkidle", timeout=60000)
                await asyncio.sleep(3)
                try:
                    login_success = await self.dy_client.pong(browser_context=self.browser_context)
                    utils.logger.info(f"[DouYinCrawler.start] Login check after refresh: {login_success}")
                except Exception as e:
                    utils.logger.warning(f"[DouYinCrawler.start] Login check after refresh failed: {e}")
            
            # 确保 msToken 已生成（搜索 API 必需）
            # 访问抖音首页触发 msToken 生成
            try:
                xmst = await self.context_page.evaluate("() => window.localStorage.getItem('xmst')")
                if not xmst:
                    utils.logger.info("[DouYinCrawler.start] msToken not found, triggering via login_by_cookies...")
                    # 使用 login_by_cookies 注入 cookie 并触发 msToken 生成
                    from api.services.cookie_manager import get_cookie
                    latest_cookie = get_cookie("dy")
                    login_obj = DouYinLogin(
                        login_type="cookie",
                        login_phone="",
                        browser_context=self.browser_context,
                        context_page=self.context_page,
                        cookie_str=latest_cookie or config.COOKIES,
                    )
                    await login_obj.login_by_cookies()
                    
                    # 再次检查 msToken
                    xmst = await self.context_page.evaluate("() => window.localStorage.getItem('xmst')")
                    if xmst:
                        utils.logger.info(f"[DouYinCrawler.start] msToken generated after login_by_cookies, length={len(xmst)}")
                    else:
                        utils.logger.warning("[DouYinCrawler.start] msToken still not found, trying page refresh...")
                        await self.context_page.goto("https://www.douyin.com", wait_until="domcontentloaded")
                        await asyncio.sleep(5)
                        xmst = await self.context_page.evaluate("() => window.localStorage.getItem('xmst')")
                        if xmst:
                            utils.logger.info(f"[DouYinCrawler.start] msToken generated after refresh, length={len(xmst)}")
                        else:
                            utils.logger.warning("[DouYinCrawler.start] msToken still not found after all attempts, search API may fail")
            except Exception as e:
                utils.logger.warning(f"[DouYinCrawler.start] msToken check failed: {e}")
            
            if not login_success:
                utils.logger.info("[DouYinCrawler.start] Login required, starting login process...")
                try:
                    login_obj = DouYinLogin(
                        login_type=config.LOGIN_TYPE,
                        login_phone="",  # you phone number
                        browser_context=self.browser_context,
                        context_page=self.context_page,
                        cookie_str=config.COOKIES,
                    )
                    await login_obj.begin()
                    utils.logger.info("[DouYinCrawler.start] Login finished, updating cookies...")
                    # login_by_cookies 后再次从 cookie_manager 设置 HTTP 客户端
                    try:
                        from api.services.cookie_manager import get_cookie
                        latest_cookie = get_cookie("dy")
                        if latest_cookie:
                            self.dy_client.headers["Cookie"] = latest_cookie
                            self.dy_client.cookie_dict = utils.convert_str_cookie_to_dict(latest_cookie)
                            utils.logger.info(f"[DouYinCrawler.start] Re-set HTTP client cookie after login, has sessionid={'sessionid' in self.dy_client.cookie_dict}")
                    except ImportError:
                        pass
                except Exception as e:
                    utils.logger.error(f"[DouYinCrawler.start] Login process error: {e}")
                    utils.logger.info("[DouYinCrawler.start] Continuing with available cookies anyway...")
            else:
                utils.logger.info("[DouYinCrawler.start] Already logged in")
                # 如果 HTTP 客户端 cookie 缺少 sessionid，尝试 login_by_cookies 注入浏览器上下文
                if "sessionid" not in self.dy_client.cookie_dict:
                    utils.logger.warning("[DouYinCrawler.start] HTTP client cookies missing sessionid, reloading from cookie_manager...")
                    try:
                        from api.services.cookie_manager import get_cookie
                        latest_cookie = get_cookie("dy")
                        
                        # 直接设置 HTTP 客户端的 Cookie 头
                        if latest_cookie:
                            self.dy_client.headers["Cookie"] = latest_cookie
                            self.dy_client.cookie_dict = utils.convert_str_cookie_to_dict(latest_cookie)
                            utils.logger.info(f"[DouYinCrawler.start] Set HTTP client cookie directly, has sessionid: {'sessionid' in self.dy_client.cookie_dict}")
                        
                        # 同时也更新浏览器上下文的 cookie
                        login_obj = DouYinLogin(
                            login_type="cookie",
                            login_phone="",
                            browser_context=self.browser_context,
                            context_page=self.context_page,
                            cookie_str=latest_cookie or config.COOKIES,
                        )
                        await login_obj.login_by_cookies()
                        utils.logger.info("[DouYinCrawler.start] Cookies reloaded from cookie_manager")
                    except Exception as e:
                        utils.logger.error(f"[DouYinCrawler.start] Cookie reload error: {e}")
            
            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for notes and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_awemes()
            elif config.CRAWLER_TYPE == "creator":
                # Get the information and comments of the specified creator
                await self.get_creators_and_videos()
            elif config.CRAWLER_TYPE == "send_dm":
                # Search -> crawl comments -> extract user info -> send private messages
                await self.search_and_send_dm()

            utils.logger.info("[DouYinCrawler.start] Douyin Crawler finished ...")

    async def search_by_browser(self, keyword: str, max_videos: int = 20) -> List[Dict]:
        """
        使用浏览器直接访问搜索页面，拦截 API 响应获取搜索结果
        作为 HTTP API 被风控时的 fallback
        """
        utils.logger.info(f"[DouYinCrawler.search_by_browser] Browser search for keyword: {keyword}")
        search_aweme_list: List[Dict] = []
        all_responses = []
        feed_data_list: List[Dict] = []
        search_data_list: List[Dict] = []  # 只记录真正的搜索API响应
        
        async def handle_route(route):
            url = route.request.url
            all_responses.append(url)
            if "/aweme/" in url:
                utils.logger.info(f"[DouYinCrawler.search_by_browser] Aweme API URL: {url[:150]}")
            
            # 继续请求，然后拦截响应 - 只匹配搜索API（避免feed推荐数据污染搜索结果）
            if "/aweme/" in url and "search" in url:
                try:
                    response = await route.fetch()
                    text = await response.text()
                    data = json.loads(text)
                    feed_data_list.append(data)
                    search_data_list.append(data)  # 记录搜索API数据
                    # 详细记录搜索API响应结构
                    if "search" in url:
                        utils.logger.info(f"[DouYinCrawler.search_by_browser] Search API response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}, status_code: {data.get('status_code') if isinstance(data, dict) else 'N/A'}")
                        if isinstance(data, dict) and data.get("data"):
                            search_data = data["data"]
                            utils.logger.info(f"[DouYinCrawler.search_by_browser] Search API data type: {type(search_data)}, len: {len(search_data) if isinstance(search_data, (list, dict)) else 'N/A'}")
                            if isinstance(search_data, dict):
                                utils.logger.info(f"[DouYinCrawler.search_by_browser] Search API data dict keys: {list(search_data.keys())}")
                                # 检查嵌套的列表
                                for dk, dv in search_data.items():
                                    if isinstance(dv, list) and len(dv) > 0:
                                        utils.logger.info(f"[DouYinCrawler.search_by_browser] data['{dk}'] is list, len={len(dv)}, first_item_type={type(dv[0])}")
                                        if isinstance(dv[0], dict):
                                            utils.logger.info(f"[DouYinCrawler.search_by_browser] data['{dk}'][0] keys: {list(dv[0].keys())[:15]}")
                            elif isinstance(search_data, list) and len(search_data) > 0:
                                utils.logger.info(f"[DouYinCrawler.search_by_browser] First item keys: {list(search_data[0].keys()) if isinstance(search_data[0], dict) else type(search_data[0])}")
                        if isinstance(data, dict) and data.get("aweme_list"):
                            utils.logger.info(f"[DouYinCrawler.search_by_browser] Search API aweme_list len: {len(data['aweme_list'])}")
                    else:
                        utils.logger.info(f"[DouYinCrawler.search_by_browser] Feed API data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                except Exception as e:
                    utils.logger.error(f"[DouYinCrawler.search_by_browser] Route fetch error: {e}")
            await route.continue_()
        
        await self.context_page.route("**/*", handle_route)
        
        try:
            # 先访问首页模拟真实用户行为，降低风控概率
            utils.logger.info("[DouYinCrawler.search_by_browser] Visiting homepage first to mimic real user...")
            await self.context_page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=60000)
            # 抖音 WAF 会返回 JS 挑战页(Please wait...)，浏览器执行 JS 后会自动 reload 到真正首页
            # 需要等待足够时间让 WAF 挑战完成(reload 后页面内容会变长)
            await asyncio.sleep(random.uniform(5, 8))
            # 检查 WAF 挑战是否完成（页面长度 > 5KB 说明已过挑战）
            try:
                page_len = len(await self.context_page.content())
                current_url = self.context_page.url
                # 检查 Cookie 是否有 _wafchallengeid（WAF 挑战通过的标志）
                cookies = await self.browser_context.cookies()
                cookie_names = [c['name'] for c in cookies]
                has_waf_cookie = any('waf' in n.lower() for n in cookie_names)
                utils.logger.info(f"[DouYinCrawler.search_by_browser] After homepage: url={current_url[:80]}, page_len={page_len}, has_waf_cookie={has_waf_cookie}, cookies={len(cookies)}")
                if page_len < 5000:
                    utils.logger.warning(f"[DouYinCrawler.search_by_browser] WAF challenge page detected (len={page_len}), waiting for reload...")
                    # 等待 WAF 挑战完成后的页面刷新
                    for waf_wait in range(10):
                        await asyncio.sleep(2)
                        page_len = len(await self.context_page.content())
                        if page_len > 5000:
                            utils.logger.info(f"[DouYinCrawler.search_by_browser] WAF challenge passed after {waf_wait*2+4}s (len={page_len})")
                            break
                    else:
                        utils.logger.warning(f"[DouYinCrawler.search_by_browser] WAF challenge may not have passed (len={page_len})")
            except Exception as e:
                utils.logger.warning(f"[DouYinCrawler.search_by_browser] WAF check failed: {e}")
            await asyncio.sleep(random.uniform(2, 4))
            # 在首页滚动一下（模拟真人浏览）
            for i in range(3):
                await self.context_page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/4})")
                await asyncio.sleep(random.uniform(1.5, 3))
            await asyncio.sleep(random.uniform(2, 4))
            
            # 访问搜索页面（综合排序，不指定sort_type避免风控）
            search_url = f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}?type=video"
            await self.context_page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(random.uniform(3, 6))
            
            # 检查是否有验证码
            page_title = await self.context_page.title()
            page_html = await self.context_page.content()
            has_captcha = "验证码" in page_title or "验证" in page_title or "captcha" in page_html.lower() or "verifycenter" in page_html.lower()
            if has_captcha:
                utils.logger.warning("[DouYinCrawler.search_by_browser] Captcha detected on search page, trying bypass first...")
                
                # 策略1: 重新导航搜索页（验证码常是临时触发）
                captcha_bypassed = False
                for attempt in range(3):
                    utils.logger.info(f"[DouYinCrawler.search_by_browser] Bypass attempt {attempt+1}/3...")
                    await asyncio.sleep(random.uniform(3, 6))
                    try:
                        await self.context_page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(4)
                        new_title = await self.context_page.title()
                        if "验证码" not in new_title and "验证" not in new_title:
                            new_html = await self.context_page.content()
                            if "verifycenter" not in new_html.lower():
                                captcha_bypassed = True
                                utils.logger.info(f"[DouYinCrawler.search_by_browser] Captcha bypassed on attempt {attempt+1}!")
                                break
                    except Exception as e:
                        utils.logger.warning(f"[DouYinCrawler.search_by_browser] Bypass attempt {attempt+1} failed: {e}")
                
                # 策略2: 换个子页面入口再搜索
                if not captcha_bypassed:
                    for entry_url in ["https://www.douyin.com/foryou", "https://www.douyin.com/hot"]:
                        utils.logger.info(f"[DouYinCrawler.search_by_browser] Trying entry: {entry_url}")
                        await asyncio.sleep(random.uniform(2, 4))
                        try:
                            await self.context_page.goto(entry_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(3)
                            # 在子页面通过搜索框搜索
                            search_input = await self.context_page.query_selector('input[data-e2e="searchbar-input"]')
                            if search_input:
                                await search_input.fill(keyword)
                                await asyncio.sleep(1)
                                await search_input.press("Enter")
                                await asyncio.sleep(5)
                                new_title = await self.context_page.title()
                                new_html = await self.context_page.content()
                                if "验证码" not in new_title and "verifycenter" not in new_html.lower():
                                    captcha_bypassed = True
                                    utils.logger.info(f"[DouYinCrawler.search_by_browser] Bypassed via {entry_url}!")
                                    break
                        except Exception as e:
                            utils.logger.warning(f"[DouYinCrawler.search_by_browser] Entry bypass failed: {e}")
                
                # 策略3: 实在绕不过，才解滑块
                if not captcha_bypassed:
                    utils.logger.warning("[DouYinCrawler.search_by_browser] All bypass failed, falling back to slider...")
                    try:
                        login_obj = DouYinLogin(
                            login_type="cookie",
                            login_phone="",
                            browser_context=self.browser_context,
                            context_page=self.context_page,
                            cookie_str="",
                        )
                        await login_obj.check_page_display_slider(move_step=3, slider_level="hard")
                        await asyncio.sleep(3)
                        utils.logger.info("[DouYinCrawler.search_by_browser] Captcha solved via slider, re-navigating to search page...")
                        # 清空之前拦截的数据（避免slider过程中热搜页等非搜索API数据污染结果）
                        feed_data_list.clear()
                        search_data_list.clear()
                        # 滑块验证后总是重新导航到搜索页（即使URL不在验证中心，也可能需要重新加载搜索结果）
                        try:
                            current_url = self.context_page.url
                            utils.logger.info(f"[DouYinCrawler.search_by_browser] Post-slider URL: {current_url[:100]}")
                            # 无论是否在验证中心，都重新导航到搜索页
                            await self.context_page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(5)
                            new_url = self.context_page.url
                            utils.logger.info(f"[DouYinCrawler.search_by_browser] Re-navigated, URL: {new_url[:100]}")
                        except Exception as nav_err:
                            utils.logger.warning(f"[DouYinCrawler.search_by_browser] Re-navigate failed: {nav_err}")
                    except Exception as e:
                        utils.logger.error(f"[DouYinCrawler.search_by_browser] Captcha solve failed: {e}")
                        # 滑块验证失败，尝试重新导航到搜索页
                        try:
                            utils.logger.info("[DouYinCrawler.search_by_browser] Retrying search page after slider failure...")
                            await self.context_page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(5)
                        except Exception:
                            pass

            # 重新导航后检查是否又遇到验证码（验证码未真正通过时会再次出现）
            await asyncio.sleep(3)
            try:
                page_url = self.context_page.url
                page_content = await self.context_page.content()
                page_len = len(page_content)
                has_captcha = ("verifycenter" in page_url or "captcha" in page_url.lower()
                               or "captcha" in page_content[:3000].lower() or page_len < 5000)
                utils.logger.info(f"[DouYinCrawler.search_by_browser] Post-navigation check: url={page_url[:80]}, len={page_len}, has_captcha={has_captcha}")
                if has_captcha:
                    utils.logger.warning(f"[DouYinCrawler.search_by_browser] Captcha reappeared after re-navigation, giving up this keyword to avoid endless loop")
                    return []
            except Exception as check_err:
                utils.logger.warning(f"[DouYinCrawler.search_by_browser] Post-navigation check failed: {check_err}")

            # 滚动页面加载更多
            for i in range(8):
                await self.context_page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/8})")
                await asyncio.sleep(2)
            
            # 只解析搜索API的数据（避免feed推荐数据污染搜索结果）
            utils.logger.info(f"[DouYinCrawler.search_by_browser] Parsing {len(search_data_list)} search API responses (filtered from {len(feed_data_list)} total)")
            for data in search_data_list:
                if not isinstance(data, dict):
                    continue
                # 处理 aweme_list 格式（推荐/搜索 feed）
                if "aweme_list" in data and isinstance(data["aweme_list"], list):
                    for aweme_info in data["aweme_list"]:
                        if isinstance(aweme_info, dict) and aweme_info.get("aweme_id"):
                            search_aweme_list.append(aweme_info)
                            utils.logger.info(f"[DouYinCrawler.search_by_browser] Found video from aweme_list: {aweme_info.get('aweme_id')}, desc: {str(aweme_info.get('desc', ''))[:30]}")
                # 处理 data 格式
                if "data" in data and isinstance(data["data"], list):
                    for item in data["data"]:
                        if isinstance(item, dict):
                            aweme_info = item.get("aweme_info")
                            if not aweme_info and "item" in item:
                                aweme_info = item.get("item")
                            if not aweme_info and "content" in item:
                                content = item.get("content")
                                if isinstance(content, dict):
                                    aweme_info = content.get("aweme_info") or content
                            if aweme_info and isinstance(aweme_info, dict) and aweme_info.get("aweme_id"):
                                search_aweme_list.append(aweme_info)
                                utils.logger.info(f"[DouYinCrawler.search_by_browser] Found video from data: {aweme_info.get('aweme_id')}, desc: {str(aweme_info.get('desc', ''))[:30]}")
                # 处理 data 是 dict 的格式（搜索API可能返回 data: {key: [items]}）
                if "data" in data and isinstance(data["data"], dict):
                    for dk, dv in data["data"].items():
                        if isinstance(dv, list):
                            for item in dv:
                                if isinstance(item, dict):
                                    aweme_info = item.get("aweme_info") or item.get("item")
                                    if not aweme_info and "content" in item:
                                        content = item.get("content")
                                        if isinstance(content, dict):
                                            aweme_info = content.get("aweme_info") or content
                                    if aweme_info and isinstance(aweme_info, dict) and aweme_info.get("aweme_id"):
                                        search_aweme_list.append(aweme_info)
                                        utils.logger.info(f"[DouYinCrawler.search_by_browser] Found video from data.{dk}: {aweme_info.get('aweme_id')}, desc: {str(aweme_info.get('desc', ''))[:30]}")
            
            # 打印前20个URL用于调试
            for i, url in enumerate(all_responses[:20]):
                utils.logger.info(f"[DouYinCrawler.search_by_browser] Response URL {i}: {url[:150]}")
            utils.logger.info(f"[DouYinCrawler.search_by_browser] Got {len(search_aweme_list)} videos from browser search, total API responses: {len(all_responses)}")
            
            # 如果 API 拦截没有获取到数据，尝试从页面 HTML 或 JS 变量中提取
            if not search_aweme_list:
                utils.logger.info("[DouYinCrawler.search_by_browser] No API data, trying to extract from page HTML/JS...")
                try:
                    page_html = await self.context_page.content()
                    # 尝试从 <script> 标签中提取 JSON 数据
                    script_pattern = re.compile(r'<script[^>]*>window\._SSR_HYDRATED_DATA\s*=\s*({.*?})</script>', re.DOTALL)
                    match = script_pattern.search(page_html)
                    if match:
                        ssr_text = match.group(1)
                        # 处理可能的 HTML 实体编码
                        ssr_text = ssr_text.replace('&quot;', '"').replace('&#x27;', "'")
                        data = json.loads(ssr_text)
                        utils.logger.info(f"[DouYinCrawler.search_by_browser] Found SSR in HTML, keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
                        if isinstance(data, dict):
                            for key in ['app', 'video', 'search', 'aweme', 'data']:
                                if key in data:
                                    sub_data = data[key]
                                    if isinstance(sub_data, dict):
                                        for sub_key, sub_val in sub_data.items():
                                            if isinstance(sub_val, list):
                                                for item in sub_val:
                                                    if isinstance(item, dict):
                                                        aweme_info = item.get('aweme_info') or item
                                                        if aweme_info and aweme_info.get('aweme_id'):
                                                            search_aweme_list.append(aweme_info)
                                            elif isinstance(sub_val, dict):
                                                for k, v in sub_val.items():
                                                    if isinstance(v, dict) and v.get('aweme_id'):
                                                        search_aweme_list.append(v)
                    else:
                        # 尝试从 window.__INITIAL_STATE__ 中提取
                        state_pattern = re.compile(r'<script[^>]*>window\.__INITIAL_STATE__\s*=\s*({.*?})</script>', re.DOTALL)
                        state_match = state_pattern.search(page_html)
                        if state_match:
                            state_text = state_match.group(1).replace('&quot;', '"').replace('&#x27;', "'")
                            data = json.loads(state_text)
                            utils.logger.info(f"[DouYinCrawler.search_by_browser] Found INITIAL_STATE in HTML, keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
                            if isinstance(data, dict):
                                for key in ['app', 'video', 'search', 'aweme', 'data']:
                                    if key in data:
                                        sub_data = data[key]
                                        if isinstance(sub_data, dict):
                                            for sub_key, sub_val in sub_data.items():
                                                if isinstance(sub_val, list):
                                                    for item in sub_val:
                                                        if isinstance(item, dict):
                                                            aweme_info = item.get('aweme_info') or item
                                                            if aweme_info and aweme_info.get('aweme_id'):
                                                                search_aweme_list.append(aweme_info)
                                                elif isinstance(sub_val, dict):
                                                    for k, v in sub_val.items():
                                                        if isinstance(v, dict) and v.get('aweme_id'):
                                                            search_aweme_list.append(v)
                        else:
                            # 尝试通用的 script 数据提取
                            scripts = re.findall(r'<script[^>]*>(.*?)</script>', page_html, re.DOTALL)
                            for script in scripts:
                                if '"aweme_id"' in script or '"aweme_info"' in script:
                                    # 尝试找到 JSON 对象
                                    json_matches = re.findall(r'({[^{}]*"aweme_id"[^{}]*})', script)
                                    for jm in json_matches:
                                        try:
                                            obj = json.loads(jm)
                                            if obj.get('aweme_id'):
                                                search_aweme_list.append(obj)
                                                utils.logger.info(f"[DouYinCrawler.search_by_browser] Found video from script: {obj.get('aweme_id')}")
                                        except:
                                            pass
                    utils.logger.info(f"[DouYinCrawler.search_by_browser] Extracted {len(search_aweme_list)} videos from HTML")
                except Exception as e:
                    utils.logger.error(f"[DouYinCrawler.search_by_browser] Extract from page failed: {e}")
        except Exception as e:
            utils.logger.error(f"[DouYinCrawler.search_by_browser] Failed: {e}")
        finally:
            await self.context_page.unroute("**/*", handle_route)
        
        # 去重并限制数量
        seen_ids = set()
        result = []
        for aweme_info in search_aweme_list:
            aweme_id = aweme_info.get("aweme_id")
            if aweme_id and aweme_id not in seen_ids:
                seen_ids.add(aweme_id)
                result.append(aweme_info)
                if len(result) >= max_videos:
                    break
        
        return result

    async def fetch_recommend_feed(self, max_videos: int = 20) -> List[Dict]:
        """
        从抖音推荐页获取视频列表（作为搜索被风控时的 fallback）
        通过浏览器拦截推荐 API 响应获取视频数据
        """
        utils.logger.info(f"[DouYinCrawler.fetch_recommend_feed] Fetching recommend feed, max_videos={max_videos}")
        aweme_list: List[Dict] = []
        try:
            # 导航到推荐页面（使用 /recommend 确保进入正常推荐流，而不是精选页）
            await self.context_page.goto("https://www.douyin.com/recommend", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            
            # 检查是否还在验证码页面
            page_title = await self.context_page.title()
            utils.logger.info(f"[DouYinCrawler.fetch_recommend_feed] Recommend page title: {page_title}")
            
            if "验证码" in page_title or "验证" in page_title:
                utils.logger.warning("[DouYinCrawler.fetch_recommend_feed] Recommend page has captcha, trying to solve...")
                try:
                    from media_platform.douyin.login import DouYinLogin
                    login_obj = DouYinLogin(
                        login_type="cookie",
                        login_phone="",
                        browser_context=self.browser_context,
                        context_page=self.context_page,
                        cookie_str="",
                    )
                    await login_obj.check_page_display_slider(move_step=3, slider_level="hard")
                    await self.context_page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                    page_title = await self.context_page.title()
                    utils.logger.info(f"[DouYinCrawler.fetch_recommend_feed] After captcha, page title: {page_title}")
                    
                    # 检查是否还需要二次验证
                    if "验证码" in page_title or "验证" in page_title:
                        utils.logger.error("[DouYinCrawler.fetch_recommend_feed] SECONDARY VERIFICATION REQUIRED!")
                        raise Exception("二次验证 Required: 请完成短信/邮箱验证后重试")
                except Exception as e:
                    if "二次验证" in str(e):
                        raise
                    utils.logger.error(f"[DouYinCrawler.fetch_recommend_feed] Captcha solve failed: {e}")
            
            # 拦截推荐 API 响应获取视频列表
            recommend_aweme_list: List[Dict] = []
            all_responses = []
            feed_data_list: List[Dict] = []
            
            async def handle_recommend_route(route):
                url = route.request.url
                all_responses.append(url)
                if "/aweme/" in url and ("feed" in url or "recommend" in url):
                    try:
                        response = await route.fetch()
                        text = await response.text()
                        data = json.loads(text)
                        feed_data_list.append(data)
                        utils.logger.info(f"[DouYinCrawler.fetch_recommend_feed] Feed API keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    except Exception as e:
                        utils.logger.error(f"[DouYinCrawler.fetch_recommend_feed] Route fetch error: {e}")
                await route.continue_()
            
            await self.context_page.route("**/*", handle_recommend_route)
            
            # 滚动页面触发推荐加载
            for i in range(8):
                await self.context_page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/8})")
                await asyncio.sleep(2)
            
            await self.context_page.unroute("**/*", handle_recommend_route)
            
            # 解析拦截到的数据
            for data in feed_data_list:
                if not isinstance(data, dict):
                    continue
                if "aweme_list" in data and isinstance(data["aweme_list"], list):
                    for aweme_info in data["aweme_list"]:
                        if isinstance(aweme_info, dict) and aweme_info.get("aweme_id"):
                            recommend_aweme_list.append(aweme_info)
                            utils.logger.info(f"[DouYinCrawler.fetch_recommend_feed] Found video from aweme_list: {aweme_info.get('aweme_id')}")
                if "data" in data and isinstance(data["data"], list):
                    for item in data["data"]:
                        if isinstance(item, dict):
                            aweme_info = item.get("aweme_info")
                            if aweme_info and aweme_info.get("aweme_id"):
                                recommend_aweme_list.append(aweme_info)
            
            utils.logger.info(f"[DouYinCrawler.fetch_recommend_feed] Got {len(recommend_aweme_list)} videos from recommend feed, total API responses: {len(all_responses)}")
            if all_responses:
                utils.logger.info(f"[DouYinCrawler.fetch_recommend_feed] Sample API URLs: {all_responses[:5]}")
            
            # 去重并限制数量
            seen_ids = set()
            for aweme_info in recommend_aweme_list:
                aweme_id = aweme_info.get("aweme_id")
                if aweme_id and aweme_id not in seen_ids:
                    seen_ids.add(aweme_id)
                    aweme_list.append(aweme_info)
                    if len(aweme_list) >= max_videos:
                        break
                        
        except Exception as e:
            utils.logger.error(f"[DouYinCrawler.fetch_recommend_feed] Failed: {e}")
        
        utils.logger.info(f"[DouYinCrawler.fetch_recommend_feed] Returning {len(aweme_list)} unique videos")
        return aweme_list

    async def search(self) -> None:
        utils.logger.info("[DouYinCrawler.search] Begin search douyin keywords")
        dy_limit_count = 10  # douyin limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < dy_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = dy_limit_count
        start_page = config.START_PAGE  # start page number
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[DouYinCrawler.search] Current keyword: {keyword}")
            aweme_list: List[str] = []
            page = 0
            dy_search_id = ""
            search_blocked = False
            while (page - start_page + 1) * dy_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[DouYinCrawler.search] Skip {page}")
                    page += 1
                    continue
                try:
                    utils.logger.info(f"[DouYinCrawler.search] search douyin keyword: {keyword}, page: {page}")
                    # 先用综合排序搜索（不容易被风控），如果无结果再用最新排序
                    sort_type = SearchSortType.GENERAL if page == 1 else SearchSortType.LATEST
                    posts_res = await self.dy_client.search_info_by_keyword(
                        keyword=keyword,
                        offset=page * dy_limit_count - dy_limit_count,
                        sort_type=sort_type,
                        publish_time=PublishTimeType(config.PUBLISH_TIME_TYPE),
                        search_id=dy_search_id,
                    )
                    utils.logger.info(f"[DouYinCrawler.search] search response keys: {list(posts_res.keys()) if isinstance(posts_res, dict) else type(posts_res)}")
                    utils.logger.info(f"[DouYinCrawler.search] search response status_code: {posts_res.get('status_code')}, status_msg: {posts_res.get('status_msg')}")

                    # 检测风控类型
                    nil_info = posts_res.get("search_nil_info", {})
                    nil_type = nil_info.get("search_nil_type", "") if isinstance(nil_info, dict) else ""
                    
                    utils.logger.info(f"[DouYinCrawler.search] search data len: {len(posts_res.get('data', []))}, has_more: {posts_res.get('has_more')}, cursor: {posts_res.get('cursor')}, nil_type: {nil_type}")
                    
                    # 如果返回 2483 "请先登录"，尝试重新登录解决验证码
                    if posts_res.get("status_code") == 2483:
                        utils.logger.warning(f"[DouYinCrawler.search] Search returned 2483, attempting re-login...")
                        try:
                            # 始终从 cookie_manager 获取最新 Cookie（单一数据源）
                            from api.services.cookie_manager import get_cookie
                            latest_cookie = get_cookie("dy")
                            login_obj = DouYinLogin(
                                login_type="cookie",
                                login_phone="",
                                browser_context=self.browser_context,
                                context_page=self.context_page,
                                cookie_str=latest_cookie or config.COOKIES,
                            )
                            await login_obj.login_by_cookies()
                            # 重新从 cookie_manager 获取 Cookie 设置到 HTTP 客户端（避免被浏览器持久化 Cookie 污染）
                            latest_cookie = get_cookie("dy") or ""
                            if latest_cookie:
                                self.dy_client.headers["Cookie"] = latest_cookie
                                self.dy_client.cookie_dict = utils.convert_str_cookie_to_dict(latest_cookie)
                                config.COOKIES = latest_cookie
                                utils.logger.info(f"[DouYinCrawler.search] Re-set HTTP client cookie from cookie_manager, length={len(latest_cookie)}")
                            else:
                                # cookie_manager 为空时才回退到浏览器持久化 Cookie
                                browser_cookies = await self.browser_context.cookies()
                                fresh_cookie_dict = {c["name"]: c["value"] for c in browser_cookies}
                                fresh_cookie_str = "; ".join([f"{k}={v}" for k, v in fresh_cookie_dict.items()])
                                utils.logger.info(f"[DouYinCrawler.search] cookie_manager empty, using browser cookies: {len(fresh_cookie_dict)} cookies, length: {len(fresh_cookie_str)}")
                                self.dy_client.headers["Cookie"] = fresh_cookie_str
                                self.dy_client.cookie_dict = fresh_cookie_dict
                                config.COOKIES = fresh_cookie_str
                            posts_res = await self.dy_client.search_info_by_keyword(
                                keyword=keyword,
                                offset=page * dy_limit_count - dy_limit_count,
                                sort_type=SearchSortType.LATEST,
                                publish_time=PublishTimeType(config.PUBLISH_TIME_TYPE),
                                search_id=dy_search_id,
                            )
                            utils.logger.info(f"[DouYinCrawler.search] Retry search response status_code: {posts_res.get('status_code')}")
                            # 重新检测风控
                            nil_info = posts_res.get("search_nil_info", {})
                            nil_type = nil_info.get("search_nil_type", "") if isinstance(nil_info, dict) else ""
                        except Exception as e:
                            if "二次验证" in str(e):
                                utils.logger.error(f"[DouYinCrawler.search] {e}")
                                raise
                            utils.logger.error(f"[DouYinCrawler.search] Re-login failed: {e}")

                    # 如果仍然 2483 或 verify_check 且无数据，标记搜索被拦截
                    has_data = posts_res.get("data") and len(posts_res.get("data", [])) > 0
                    # 检查 data 是否为热搜数据（dict 包含 trending_list/word_list 而非搜索结果）
                    is_trending_data = isinstance(posts_res.get("data"), dict) and (
                        "trending_list" in posts_res.get("data", {}) or "word_list" in posts_res.get("data", {})
                    )
                    if posts_res.get("status_code") == 2483 or (nil_type == "verify_check" and not has_data) or is_trending_data:
                        utils.logger.warning(f"[DouYinCrawler.search] Search blocked (2483 or verify_check with no data or trending_data), will fallback to recommend feed")
                        search_blocked = True
                        break

                    if posts_res.get("data") is None or posts_res.get("data") == []:
                        utils.logger.info(f"[DouYinCrawler.search] search douyin keyword: {keyword}, page: {page} is empty")
                        break
                except DataFetchError:
                    utils.logger.error(f"[DouYinCrawler.search] search douyin keyword: {keyword} failed")
                    search_blocked = True
                    break
                except Exception as e:
                    utils.logger.error(f"[DouYinCrawler.search] search unexpected error: {e}")
                    search_blocked = True
                    break

                page += 1
                if "data" not in posts_res and posts_res.get("status_code") != 0:
                    utils.logger.error(f"[DouYinCrawler.search] search douyin keyword: {keyword} failed，账号也许被风控了。")
                    search_blocked = True
                    break
                dy_search_id = posts_res.get("extra", {}).get("logid", "")
                page_aweme_list = []
                for post_item in posts_res.get("data"):
                    try:
                        aweme_info: Dict = (post_item.get("aweme_info") or post_item.get("aweme_mix_info", {}).get("mix_items")[0])
                    except TypeError:
                        continue
                    aweme_list.append(aweme_info.get("aweme_id", ""))
                    page_aweme_list.append(aweme_info.get("aweme_id", ""))
                    await douyin_store.update_douyin_aweme(aweme_item=aweme_info)
                    await self.get_aweme_media(aweme_item=aweme_info)
                
                await self.batch_get_note_comments(page_aweme_list)
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[DouYinCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")
            
            # 如果搜索被拦截，先等待冷却再重试 HTTP API，最后才降级到浏览器搜索
            if search_blocked:
                utils.logger.warning(f"[DouYinCrawler.search] Keyword '{keyword}' search blocked, waiting for cooldown before retry...")
                
                # 冷却重试：等待30秒后重试HTTP API（最多2次）
                retry_success = False
                for retry_idx in range(2):
                    cooldown_sec = 30 * (retry_idx + 1)
                    utils.logger.info(f"[DouYinCrawler.search] Cooldown retry {retry_idx+1}/2, waiting {cooldown_sec}s...")
                    await asyncio.sleep(cooldown_sec)
                    try:
                        posts_res = await self.dy_client.search_info_by_keyword(
                            keyword=keyword,
                            offset=0,
                            sort_type=SearchSortType.GENERAL,
                            publish_time=PublishTimeType(config.PUBLISH_TIME_TYPE),
                            search_id="",
                        )
                        retry_has_data = posts_res.get("data") and len(posts_res.get("data", [])) > 0
                        retry_nil = posts_res.get("search_nil_info", {})
                        retry_nil_type = retry_nil.get("search_nil_type", "") if isinstance(retry_nil, dict) else ""
                        utils.logger.info(f"[DouYinCrawler.search] Retry {retry_idx+1} status: {posts_res.get('status_code')}, data_len: {len(posts_res.get('data', []))}, nil_type: {retry_nil_type}")
                        
                        if retry_has_data and retry_nil_type != "verify_check":
                            utils.logger.info(f"[DouYinCrawler.search] Retry {retry_idx+1} succeeded! Processing results...")
                            page_aweme_list = []
                            for post_item in posts_res.get("data"):
                                try:
                                    aweme_info: Dict = (post_item.get("aweme_info") or post_item.get("aweme_mix_info", {}).get("mix_items")[0])
                                except TypeError:
                                    continue
                                aweme_id = aweme_info.get("aweme_id", "")
                                if aweme_id:
                                    aweme_list.append(aweme_id)
                                    page_aweme_list.append(aweme_id)
                                    await douyin_store.update_douyin_aweme(aweme_item=aweme_info)
                                    await self.get_aweme_media(aweme_item=aweme_info)
                            if page_aweme_list:
                                await self.batch_get_note_comments(page_aweme_list)
                            retry_success = True
                            break
                    except Exception as e:
                        utils.logger.warning(f"[DouYinCrawler.search] Retry {retry_idx+1} failed: {e}")
                
                # 冷却重试失败，才降级到浏览器搜索
                if not retry_success:
                    utils.logger.info(f"[DouYinCrawler.search] HTTP API retries exhausted, trying browser search...")
                    browser_search_videos = await self.search_by_browser(keyword, max_videos=config.CRAWLER_MAX_NOTES_COUNT)
                    if browser_search_videos:
                        utils.logger.info(f"[DouYinCrawler.search] Browser search succeeded, got {len(browser_search_videos)} videos")
                        page_aweme_list = []
                        for aweme_info in browser_search_videos:
                            aweme_id = aweme_info.get("aweme_id", "")
                            if aweme_id:
                                aweme_list.append(aweme_id)
                                page_aweme_list.append(aweme_id)
                                await douyin_store.update_douyin_aweme(aweme_item=aweme_info)
                                await self.get_aweme_media(aweme_item=aweme_info)
                        await self.batch_get_note_comments(page_aweme_list)
                    else:
                        utils.logger.warning(f"[DouYinCrawler.search] Browser search empty for keyword '{keyword}', skipping (not falling back to recommend feed to avoid irrelevant data)")
                        page_aweme_list = []
            
            utils.logger.info(f"[DouYinCrawler.search] keyword:{keyword}, aweme_list:{aweme_list}")

    async def get_specified_awemes(self):
        """Get the information and comments of the specified post from URLs or IDs"""
        utils.logger.info("[DouYinCrawler.get_specified_awemes] Parsing video URLs...")
        aweme_id_list = []
        for video_url in config.DY_SPECIFIED_ID_LIST:
            try:
                video_info = parse_video_info_from_url(video_url)

                # Handling short links
                if video_info.url_type == "short":
                    utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Resolving short link: {video_url}")
                    resolved_url = await self.dy_client.resolve_short_url(video_url)
                    if resolved_url:
                        # Extract video ID from parsed URL
                        video_info = parse_video_info_from_url(resolved_url)
                        utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Short link resolved to aweme ID: {video_info.aweme_id}")
                    else:
                        utils.logger.error(f"[DouYinCrawler.get_specified_awemes] Failed to resolve short link: {video_url}")
                        continue

                aweme_id_list.append(video_info.aweme_id)
                utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Parsed aweme ID: {video_info.aweme_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"[DouYinCrawler.get_specified_awemes] Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_aweme_detail(aweme_id=aweme_id, semaphore=semaphore) for aweme_id in aweme_id_list]
        aweme_details = await asyncio.gather(*task_list)
        for aweme_detail in aweme_details:
            if aweme_detail is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_detail)
                await self.get_aweme_media(aweme_item=aweme_detail)
        await self.batch_get_note_comments(aweme_id_list)

    async def get_aweme_detail(self, aweme_id: str, semaphore: asyncio.Semaphore) -> Any:
        """Get note detail"""
        async with semaphore:
            try:
                result = await self.dy_client.get_video_by_id(aweme_id)
                # Sleep after fetching aweme detail
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[DouYinCrawler.get_aweme_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching aweme {aweme_id}")
                return result
            except DataFetchError as ex:
                utils.logger.error(f"[DouYinCrawler.get_aweme_detail] Get aweme detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[DouYinCrawler.get_aweme_detail] have not fund note detail aweme_id:{aweme_id}, err: {ex}")
                return None

    async def batch_get_note_comments(self, aweme_list: List[str]) -> None:
        """
        Batch get note comments
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[DouYinCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        task_list: List[Task] = []
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        for aweme_id in aweme_list:
            task = asyncio.create_task(self.get_comments(aweme_id, semaphore), name=aweme_id)
            task_list.append(task)
        if len(task_list) > 0:
            await asyncio.wait(task_list)

    async def get_comments(self, aweme_id: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                # Pass the list of keywords to the get_aweme_all_comments method
                # Use fixed crawling interval
                crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
                await self.dy_client.get_aweme_all_comments(
                    aweme_id=aweme_id,
                    crawl_interval=crawl_interval,
                    is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                    callback=douyin_store.batch_update_dy_aweme_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
                # Sleep after fetching comments
                await asyncio.sleep(crawl_interval)
                utils.logger.info(f"[DouYinCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for aweme {aweme_id}")
                utils.logger.info(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} comments have all been obtained and filtered ...")
            except DataFetchError as e:
                error_msg = str(e).lower()
                if "account blocked" in error_msg or "请先登录" in error_msg or "2483" in error_msg or "login" in error_msg:
                    utils.logger.warning(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} HTTP API blocked, trying browser fallback...")
                    try:
                        comments = await self.get_comments_by_browser(aweme_id, max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES)
                        if comments:
                            await douyin_store.batch_update_dy_aweme_comments(aweme_id, comments)
                            utils.logger.info(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} got {len(comments)} comments from browser fallback")
                        else:
                            utils.logger.warning(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} no comments from browser fallback")
                    except Exception as browser_e:
                        utils.logger.error(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} browser fallback failed: {browser_e}")
                else:
                    utils.logger.error(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} get comments failed, error: {e}")

    async def get_comments_by_browser(self, aweme_id: str, max_count: int = 10) -> List[Dict]:
        """
        使用浏览器访问视频详情页，拦截评论 API 响应获取评论
        作为 HTTP API 被风控时的 fallback
        """
        utils.logger.info(f"[DouYinCrawler.get_comments_by_browser] Browser comments for aweme_id: {aweme_id}")
        all_comments: List[Dict] = []
        comment_data_list: List[Dict] = []
        
        async def handle_comment_route(route):
            url = route.request.url
            if "/aweme/v1/web/comment/list/" in url and "reply" not in url:
                try:
                    response = await route.fetch()
                    text = await response.text()
                    data = json.loads(text)
                    comment_data_list.append(data)
                    utils.logger.info(f"[DouYinCrawler.get_comments_by_browser] Comment API keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                except Exception as e:
                    utils.logger.error(f"[DouYinCrawler.get_comments_by_browser] Route fetch error: {e}")
            await route.continue_()
        
        await self.context_page.route("**/*", handle_comment_route)
        
        try:
            video_url = f"https://www.douyin.com/video/{aweme_id}"
            await self.context_page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(random.uniform(3, 6))
            
            # 检查是否有验证码 — 优先绕过
            page_title = await self.context_page.title()
            page_html = await self.context_page.content()
            has_captcha = "验证码" in page_title or "验证" in page_title or "captcha" in page_html.lower() or "verifycenter" in page_html.lower()
            if has_captcha:
                utils.logger.warning("[DouYinCrawler.get_comments_by_browser] Captcha detected on video page, trying bypass first...")
                captcha_bypassed = False
                # 策略1: 重新访问视频页
                for attempt in range(2):
                    await asyncio.sleep(random.uniform(3, 5))
                    try:
                        await self.context_page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(4)
                        new_title = await self.context_page.title()
                        new_html = await self.context_page.content()
                        if "验证码" not in new_title and "verifycenter" not in new_html.lower():
                            captcha_bypassed = True
                            utils.logger.info(f"[DouYinCrawler.get_comments_by_browser] Captcha bypassed on attempt {attempt+1}!")
                            break
                    except Exception as e:
                        utils.logger.warning(f"[DouYinCrawler.get_comments_by_browser] Bypass attempt {attempt+1} failed: {e}")
                
                # 策略2: 降级到滑块
                if not captcha_bypassed:
                    utils.logger.warning("[DouYinCrawler.get_comments_by_browser] Falling back to slider...")
                    try:
                        login_obj = DouYinLogin(
                            login_type="cookie",
                            login_phone="",
                            browser_context=self.browser_context,
                            context_page=self.context_page,
                            cookie_str="",
                        )
                        await login_obj.check_page_display_slider(move_step=3, slider_level="hard")
                        await asyncio.sleep(random.uniform(3, 5))
                    except Exception as e:
                        utils.logger.error(f"[DouYinCrawler.get_comments_by_browser] Captcha solve failed: {e}")
            
            # 滚动页面加载更多评论
            for i in range(5):
                await self.context_page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
                await asyncio.sleep(random.uniform(1.5, 3))
            
            # 解析拦截到的评论数据
            for data in comment_data_list:
                if isinstance(data, dict) and "comments" in data and isinstance(data["comments"], list):
                    for comment in data["comments"]:
                        if isinstance(comment, dict) and comment.get("cid"):
                            all_comments.append(comment)
                            utils.logger.info(f"[DouYinCrawler.get_comments_by_browser] Found comment: {comment.get('cid')}, text: {str(comment.get('text', ''))[:30]}")
            
            utils.logger.info(f"[DouYinCrawler.get_comments_by_browser] Got {len(all_comments)} comments from browser, total API responses: {len(comment_data_list)}")
            
            # 如果 API 拦截没有获取到数据，尝试从页面 HTML 中提取
            if not all_comments:
                utils.logger.info("[DouYinCrawler.get_comments_by_browser] No API data, trying to extract from page HTML...")
                try:
                    page_html = await self.context_page.content()
                    scripts = re.findall(r'<script[^>]*>(.*?)</script>', page_html, re.DOTALL)
                    for script in scripts:
                        if '"comments"' in script or '"cid"' in script:
                            json_matches = re.findall(r'({[^{}]*"cid"[^{}]*})', script)
                            for jm in json_matches:
                                try:
                                    obj = json.loads(jm)
                                    if obj.get("cid"):
                                        all_comments.append(obj)
                                except:
                                    pass
                except Exception as e:
                    utils.logger.error(f"[DouYinCrawler.get_comments_by_browser] Extract from page failed: {e}")
        except Exception as e:
            utils.logger.error(f"[DouYinCrawler.get_comments_by_browser] Failed: {e}")
        finally:
            await self.context_page.unroute("**/*", handle_comment_route)
        
        # 去重并限制数量
        seen_ids = set()
        result = []
        for comment in all_comments:
            cid = comment.get("cid")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                result.append(comment)
                if len(result) >= max_count:
                    break
        
        return result

    async def get_creators_and_videos(self) -> None:
        """
        Get the information and videos of the specified creator from URLs or IDs
        """
        utils.logger.info("[DouYinCrawler.get_creators_and_videos] Begin get douyin creators")
        utils.logger.info("[DouYinCrawler.get_creators_and_videos] Parsing creator URLs...")

        for creator_url in config.DY_CREATOR_ID_LIST:
            try:
                creator_info_parsed = parse_creator_info_from_url(creator_url)
                user_id = creator_info_parsed.sec_user_id
                utils.logger.info(f"[DouYinCrawler.get_creators_and_videos] Parsed sec_user_id: {user_id} from {creator_url}")
            except ValueError as e:
                utils.logger.error(f"[DouYinCrawler.get_creators_and_videos] Failed to parse creator URL: {e}")
                continue

            creator_info: Dict = await self.dy_client.get_user_info(user_id)
            if creator_info:
                await douyin_store.save_creator(user_id, creator=creator_info)

            # Get all video information of the creator
            all_video_list = await self.dy_client.get_all_user_aweme_posts(sec_user_id=user_id, callback=self.fetch_creator_video_detail)

            video_ids = [video_item.get("aweme_id") for video_item in all_video_list]
            await self.batch_get_note_comments(video_ids)

    async def fetch_creator_video_detail(self, video_list: List[Dict]):
        """
        Concurrently obtain the specified post list and save the data
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_aweme_detail(post_item.get("aweme_id"), semaphore) for post_item in video_list]

        note_details = await asyncio.gather(*task_list)
        for aweme_item in note_details:
            if aweme_item is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_item)
                await self.get_aweme_media(aweme_item=aweme_item)

    async def create_douyin_client(self, httpx_proxy: Optional[str]) -> DouYinClient:
        """Create douyin client"""
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=self.cookie_urls,
        )  # type: ignore
        
        # 优先使用 cookie 中记录的 User-Agent（确保与 cookie 生成环境一致）
        user_agent = None
        try:
            druid_info = cookie_dict.get("__druidClientInfo", "")
            if druid_info:
                import base64, urllib.parse
                # __druidClientInfo 是 base64(percent_encode(json_string))
                decoded_bytes = base64.b64decode(druid_info)
                url_decoded = urllib.parse.unquote(decoded_bytes.decode('utf-8'))
                druid_json = json.loads(url_decoded)
                user_agent = druid_json.get("userAgent")
                if user_agent:
                    utils.logger.info(f"[DouYinCrawler.create_douyin_client] Using User-Agent from cookie: {user_agent[:80]}...")
        except Exception as e:
            utils.logger.warning(f"[DouYinCrawler.create_douyin_client] Failed to parse __druidClientInfo: {e}")
        
        if not user_agent:
            # 回退：从浏览器页面获取
            try:
                user_agent = await self.context_page.evaluate("() => navigator.userAgent")
            except Exception as e:
                utils.logger.warning(f"[DouYinCrawler.create_douyin_client] Failed to get userAgent: {e}, using default")
                user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        
        douyin_client = DouYinClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": user_agent,
                "Cookie": cookie_str,
                "Host": "www.douyin.com",
                "Origin": "https://www.douyin.com/",
                "Referer": "https://www.douyin.com/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
            account_pool=self._account_pool,  # 多账号池（可选，自动切换Cookie+IP）
        )
        return douyin_client

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context with anti-detection"""
        # 真实浏览器 User-Agent（Chrome 126 Windows）
        if not user_agent:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )

        # 反自动化检测启动参数
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-component-extensions-with-background-pages",
            "--disable-dev-shm-usage",
            "--lang=zh-CN",
            "--disable-notifications",
        ]

        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM)  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                args=launch_args,
                ignore_default_args=["--enable-automation"],
            )  # type: ignore
        else:
            browser = await chromium.launch(
                headless=headless,
                proxy=playwright_proxy,
                args=launch_args,
                ignore_default_args=["--enable-automation"],
            )  # type: ignore
            browser_context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )

        # 注入反检测脚本（在页面创建前注入，确保首屏请求就不暴露）
        anti_detect_js = """
        // 隐藏 webdriver 标志
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // 添加 chrome.runtime（正常浏览器有此属性）
        if (!window.chrome) { window.chrome = {}; }
        if (!window.chrome.runtime) { window.chrome.runtime = { connect: () => {}, sendMessage: () => {} }; }
        // 修改 plugins 长度（正常浏览器有插件）
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        // 修改 languages
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
        // 隐藏 Playwright 特征
        delete window.__playwright__evaluation_script;
        // 修改 permissions API
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
        // WebGL 渲染器伪装
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';  // UNMASKED_VENDOR_WEBGL
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
            return getParameter.call(this, parameter);
        };
        """
        await browser_context.add_init_script(anti_detect_js)
        # 再叠加 stealth.min.js（如果存在）
        try:
            await browser_context.add_init_script(path="libs/stealth.min.js")
        except Exception:
            pass

        return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        使用CDP模式启动浏览器
        """
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Add anti-detection script
            await self.cdp_manager.add_stealth_script()

            # Show browser information
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[DouYinCrawler] CDP浏览器信息: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[DouYinCrawler] CDP模式启动失败，回退到标准模式: {e}")
            # Fall back to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def search_and_send_dm(self) -> None:
        """
        搜索关键词 -> 爬取评论 -> 提取评论用户信息 -> 发送私信

        复用已有的搜索和评论爬取机制，在获取到评论用户后自动发送私信
        """
        utils.logger.info("[DouYinCrawler.search_and_send_dm] Begin search and send DM flow")

        # 私信相关配置
        dm_message = getattr(config, 'DM_MESSAGE', '')
        dm_interval_min = getattr(config, 'DM_INTERVAL_MIN', 60)
        dm_interval_max = getattr(config, 'DM_INTERVAL_MAX', 180)
        dm_max_count = getattr(config, 'DM_MAX_COUNT', 10)
        dm_sent_count = 0  # 已发送计数

        if not dm_message:
            utils.logger.error("[DouYinCrawler.search_and_send_dm] DM_MESSAGE is empty, please set it in config")
            return

        # === 第一阶段：搜索 + 爬取评论，收集用户信息 ===
        dy_limit_count = 10
        if config.CRAWLER_MAX_NOTES_COUNT < dy_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = dy_limit_count
        start_page = config.START_PAGE

        # 收集所有评论用户: {sec_uid: {nickname, sec_uid, user_id, comment_content, aweme_id}}
        dm_targets: Dict[str, Dict] = {}

        # 先尝试搜索 API，如果被拦截则回退到推荐页面
        search_blocked = False

        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Current keyword: {keyword}")
            aweme_list: List[str] = []
            page = 0
            dy_search_id = ""

            while (page - start_page + 1) * dy_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    page += 1
                    continue
                try:
                    posts_res = await self.dy_client.search_info_by_keyword(
                        keyword=keyword,
                        offset=page * dy_limit_count - dy_limit_count,
                        sort_type=SearchSortType.LATEST,
                        publish_time=PublishTimeType(config.PUBLISH_TIME_TYPE),
                        search_id=dy_search_id,
                    )
                    utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Search API status_code: {posts_res.get('status_code')}, status_msg: {posts_res.get('status_msg')}")
                    
                    # 如果 HTTP API 返回 2483（请先登录），回退到浏览器搜索
                    if posts_res.get("status_code") == 2483:
                        utils.logger.info("[DouYinCrawler.search_and_send_dm] HTTP API blocked (2483), falling back to browser search...")
                        posts_res = await self.dy_client.search_info_by_keyword_via_browser(
                            keyword=keyword,
                            offset=page * dy_limit_count - dy_limit_count,
                            page=self.context_page,
                        )
                        if not posts_res.get("data"):
                            utils.logger.warning("[DouYinCrawler.search_and_send_dm] Browser search also returned empty")
                            search_blocked = True
                            break
                    
                    if posts_res.get("data") is None or posts_res.get("data") == []:
                        utils.logger.warning(f"[DouYinCrawler.search_and_send_dm] Search returned empty data")
                        break
                except DataFetchError as e:
                    utils.logger.error(f"[DouYinCrawler.search_and_send_dm] Search DataFetchError for keyword: {keyword}, error: {e}")
                    search_blocked = True
                    break
                except Exception as e:
                    utils.logger.error(f"[DouYinCrawler.search_and_send_dm] Search unexpected error for keyword: {keyword}, error: {type(e).__name__}: {e}")
                    search_blocked = True
                    break

                page += 1
                if "data" not in posts_res:
                    utils.logger.error(f"[DouYinCrawler.search_and_send_dm] Search failed, account may be risk-controlled")
                    break

                dy_search_id = posts_res.get("extra", {}).get("logid", "")
                page_aweme_list = []
                for post_item in posts_res.get("data"):
                    try:
                        aweme_info: Dict = (post_item.get("aweme_info") or post_item.get("aweme_mix_info", {}).get("mix_items")[0])
                    except TypeError:
                        continue
                    aweme_list.append(aweme_info.get("aweme_id", ""))
                    page_aweme_list.append(aweme_info.get("aweme_id", ""))
                    await douyin_store.update_douyin_aweme(aweme_item=aweme_info)
                    await self.get_aweme_media(aweme_item=aweme_info)

                # 爬取评论并收集用户信息
                for aweme_id in page_aweme_list:
                    comments = await self._collect_comment_users(aweme_id)
                    for sec_uid, user_info in comments.items():
                        if sec_uid not in dm_targets:
                            dm_targets[sec_uid] = user_info

                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)

            utils.logger.info(f"[DouYinCrawler.search_and_send_dm] keyword:{keyword}, aweme_list:{aweme_list}")

        # 如果搜索被拦截，回退到从推荐页面获取视频
        if search_blocked and not dm_targets:
            utils.logger.info("[DouYinCrawler.search_and_send_dm] Search blocked, falling back to recommend feed...")
            try:
                # 导航到推荐页面
                await self.context_page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                
                # 检查是否还在验证码页面
                page_title = await self.context_page.title()
                utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Recommend page title: {page_title}")
                
                if "验证码" in page_title:
                    utils.logger.warning("[DouYinCrawler.search_and_send_dm] Recommend page also has captcha, trying to solve...")
                    try:
                        from media_platform.douyin.login import DouYinLogin
                        login_obj = DouYinLogin(
                            login_type="cookie",
                            login_phone="",
                            browser_context=self.browser_context,
                            context_page=self.context_page,
                            cookie_str="",
                        )
                        await login_obj.check_page_display_slider(move_step=3, slider_level="hard")
                        # 验证码通过后重新导航
                        await self.context_page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(3)
                        page_title = await self.context_page.title()
                        utils.logger.info(f"[DouYinCrawler.search_and_send_dm] After captcha, page title: {page_title}")
                    except Exception as e:
                        utils.logger.error(f"[DouYinCrawler.search_and_send_dm] Captcha solve failed: {e}")
                
                # 拦截推荐 API 响应获取视频列表
                recommend_aweme_ids = []
                all_responses = []
                
                async def handle_recommend(response):
                    url = response.url
                    all_responses.append(url)
                    if ("feed" in url or "aweme" in url) and response.status == 200:
                        try:
                            data = await response.json()
                            if isinstance(data, dict):
                                for item in data.get("data", []):
                                    aweme_info = item.get("aweme_info")
                                    if aweme_info and aweme_info.get("aweme_id"):
                                        recommend_aweme_ids.append(aweme_info.get("aweme_id"))
                        except Exception:
                            pass
                
                self.context_page.on("response", handle_recommend)
                
                # 滚动页面触发推荐加载
                for i in range(5):
                    await self.context_page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
                    await asyncio.sleep(2)
                
                self.context_page.remove_listener("response", handle_recommend)
                
                utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Got {len(recommend_aweme_ids)} videos from recommend feed, total API responses: {len(all_responses)}")
                if all_responses:
                    utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Sample API URLs: {all_responses[:5]}")
                
                # 爬取评论收集用户
                for aweme_id in recommend_aweme_ids[:10]:  # 最多处理 10 个视频
                    comments = await self._collect_comment_users(aweme_id)
                    for sec_uid, user_info in comments.items():
                        if sec_uid not in dm_targets:
                            dm_targets[sec_uid] = user_info
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    
            except Exception as e:
                utils.logger.error(f"[DouYinCrawler.search_and_send_dm] Recommend feed fallback failed: {e}")

        utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Collected {len(dm_targets)} unique comment users")

        # === 第二阶段：给收集到的用户发送私信 ===
        if not dm_targets:
            utils.logger.warning("[DouYinCrawler.search_and_send_dm] No target users found")
            return

        for sec_uid, user_info in dm_targets.items():
            if dm_sent_count >= dm_max_count:
                utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Reached DM max count limit: {dm_max_count}")
                break

            nickname = user_info.get("nickname", "unknown")
            utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Sending DM to {nickname} ({sec_uid})")

            # 对消息内容进行个性化处理
            personalized_msg = self._personalize_dm(dm_message, nickname, user_info)

            try:
                result = await self.dy_client.send_private_message_via_browser(
                    sec_uid=sec_uid,
                    message=personalized_msg,
                    browser_context=self.browser_context,
                    page=self.context_page,
                )

                # 保存私信记录
                await douyin_store.save_dm_record(
                    sec_uid=sec_uid,
                    nickname=nickname,
                    user_id=user_info.get("user_id", ""),
                    message=personalized_msg,
                    success=result.get("success", False),
                    error=result.get("error", ""),
                    aweme_id=user_info.get("aweme_id", ""),
                )

                if result.get("success"):
                    dm_sent_count += 1
                    utils.logger.info(f"[DouYinCrawler.search_and_send_dm] DM sent to {nickname} ({dm_sent_count}/{dm_max_count})")
                else:
                    utils.logger.warning(f"[DouYinCrawler.search_and_send_dm] DM failed for {nickname}: {result.get('error')}")

            except Exception as e:
                utils.logger.error(f"[DouYinCrawler.search_and_send_dm] DM error for {nickname}: {e}")
                await douyin_store.save_dm_record(
                    sec_uid=sec_uid,
                    nickname=nickname,
                    user_id=user_info.get("user_id", ""),
                    message=personalized_msg,
                    success=False,
                    error=str(e),
                    aweme_id=user_info.get("aweme_id", ""),
                )

            # 私信间隔：随机等待，避免被风控
            interval = random.uniform(dm_interval_min, dm_interval_max)
            utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Waiting {interval:.0f}s before next DM...")
            await asyncio.sleep(interval)

        utils.logger.info(f"[DouYinCrawler.search_and_send_dm] Finished. Sent {dm_sent_count} DMs out of {len(dm_targets)} targets")

    async def _collect_comment_users(self, aweme_id: str) -> Dict[str, Dict]:
        """
        爬取指定视频的评论，提取评论用户信息用于私信

        Args:
            aweme_id: 视频ID

        Returns:
            Dict: {sec_uid: {nickname, sec_uid, user_id, comment_content, aweme_id}}
        """
        users: Dict[str, Dict] = {}
        try:
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            max_comments = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
            cursor = 0
            has_more = 1
            collected = 0

            while has_more and collected < max_comments:
                comments_res = await self.dy_client.get_aweme_comments(aweme_id, cursor)
                has_more = comments_res.get("has_more", 0)
                cursor = comments_res.get("cursor", 0)
                comments = comments_res.get("comments", [])

                if not comments:
                    break

                for comment in comments:
                    user_info = comment.get("user", {})
                    sec_uid = user_info.get("sec_uid", "")
                    if sec_uid and sec_uid not in users:
                        users[sec_uid] = {
                            "nickname": user_info.get("nickname", ""),
                            "sec_uid": sec_uid,
                            "user_id": user_info.get("uid", ""),
                            "comment_content": comment.get("text", ""),
                            "aweme_id": aweme_id,
                        }
                    collected += 1

                # 同时保存评论到 store（复用已有机制）
                await douyin_store.batch_update_dy_aweme_comments(aweme_id, comments)

                await asyncio.sleep(crawl_interval)

        except DataFetchError as e:
            utils.logger.error(f"[DouYinCrawler._collect_comment_users] Error for aweme {aweme_id}: {e}")

        return users

    @staticmethod
    def _personalize_dm(template: str, nickname: str, user_info: Dict) -> str:
        """
        对私信模板进行个性化处理，避免被识别为群发

        支持的占位符:
            {nickname} - 用户昵称
            {comment} - 用户评论内容（截取前20字）
        """
        msg = template.replace("{nickname}", nickname)
        comment = user_info.get("comment_content", "")[:20]
        msg = msg.replace("{comment}", comment)
        return msg

    async def close(self) -> None:
        """Close browser context"""
        # If you use CDP mode, special processing is required
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[DouYinCrawler.close] Browser context closed ...")

    async def get_aweme_media(self, aweme_item: Dict):
        """
        获取抖音媒体，自动判断媒体类型是短视频还是帖子图片并下载

        Args:
            aweme_item (Dict): 抖音作品详情
        """
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[DouYinCrawler.get_aweme_media] Crawling image mode is not enabled")
            return
        # List of note urls. If it is a short video type, an empty list will be returned.
        note_download_url: List[str] = douyin_store._extract_note_image_list(aweme_item)
        # The video URL will always exist, but when it is a short video type, the file is actually an audio file.
        video_download_url: str = douyin_store._extract_video_download_url(aweme_item)
        # TODO: Douyin does not adopt the audio and video separation strategy, so the audio can be separated from the original video and will not be extracted for the time being.
        if note_download_url:
            await self.get_aweme_images(aweme_item)
        else:
            await self.get_aweme_video(aweme_item)

    async def get_aweme_images(self, aweme_item: Dict):
        """
        get aweme images. please use get_aweme_media

        Args:
            aweme_item (Dict): 抖音作品详情
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        aweme_id = aweme_item.get("aweme_id")
        # List of note urls. If it is a short video type, an empty list will be returned.
        note_download_url: List[str] = douyin_store._extract_note_image_list(aweme_item)

        if not note_download_url:
            return
        picNum = 0
        for url in note_download_url:
            if not url:
                continue
            content = await self.dy_client.get_aweme_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{picNum:>03d}.jpeg"
            picNum += 1
            await douyin_store.update_dy_aweme_image(aweme_id, content, extension_file_name)

    async def get_aweme_video(self, aweme_item: Dict):
        """
        get aweme videos. please use get_aweme_media

        Args:
            aweme_item (Dict): 抖音作品详情
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        aweme_id = aweme_item.get("aweme_id")

        # The video URL will always exist, but when it is a short video type, the file is actually an audio file.
        video_download_url: str = douyin_store._extract_video_download_url(aweme_item)

        if not video_download_url:
            return
        content = await self.dy_client.get_aweme_media(video_download_url)
        await asyncio.sleep(random.random())
        if content is None:
            return
        extension_file_name = f"video.mp4"
        await douyin_store.update_dy_aweme_video(aweme_id, content, extension_file_name)
