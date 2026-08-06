# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/client.py
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
import copy
import json
import os
import urllib.parse
from typing import TYPE_CHECKING, Any, Callable, Dict, Union, Optional

import httpx
from playwright.async_api import BrowserContext

from base.base_crawler import AbstractApiClient
from proxy.proxy_mixin import ProxyRefreshMixin
from tools import utils
from tools.httpx_util import make_async_client
from var import request_keyword_var

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool

from .exception import *
from .field import *
from .help import *


class DouYinClient(AbstractApiClient, ProxyRefreshMixin):

    def __init__(
        self,
        timeout=60,  # If the crawl media option is turned on, Douyin’s short videos will require a longer timeout.
        proxy=None,
        *,
        headers: Dict,
        playwright_page: Optional[Page],
        cookie_dict: Dict,
        proxy_ip_pool: Optional["ProxyIpPool"] = None,
        account_pool=None,  # 多账号池（可选）
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://www.douyin.com"
        self.cookie_urls = [
            "https://douyin.com",
            self._host,
            "https://creator.douyin.com",
            "https://douhot.douyin.com",
            "https://live.douyin.com",
        ]
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self._account_pool = account_pool  # 多账号池
        # Initialize proxy pool (from ProxyRefreshMixin)
        self.init_proxy_pool(proxy_ip_pool)

    async def __process_req_params(
        self,
        uri: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        request_method="GET",
    ):

        if not params:
            return
        headers = headers or self.headers
        local_storage: Dict = await self.playwright_page.evaluate("() => window.localStorage")  # type: ignore
        xmst = local_storage.get("xmst", "")
        if not xmst:
            # 尝试从 cookie 中获取 msToken
            try:
                cookies = await self.playwright_page.context.cookies()
                msToken_cookie = next((c for c in cookies if c["name"] == "msToken"), None)
                if msToken_cookie:
                    xmst = msToken_cookie["value"]
            except Exception:
                pass
        
        if not xmst:
            # getuser-canrun 经验 4: 假 msToken 比没有更糟 — 随机生成的 msToken 会被抖音立即识别无效
            # 触发 verify_check / 2483 / 验证码风控。宁可不带 msToken（或空）让其重新生成，也绝不造假
            if "search" in uri:
                utils.logger.warning(
                    "[DouYinClient.__process_req_params] msToken missing from localStorage/cookie, "
                    "will continue WITHOUT fake msToken (per getuser-canrun: fake token > no token). "
                    "Expect occasional 2483/verify_check; caller should trigger page reload to refresh token."
                )
            xmst = ""
        
        common_params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "version_code": "190600",
            "version_name": "19.6.0",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "cookie_enabled": "true",
            "browser_language": "zh-CN",
            "browser_platform": "MacIntel",
            "browser_name": "Chrome",
            "browser_version": "125.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "os_name": "Mac OS",
            "os_version": "10.15.7",
            "cpu_core_num": "8",
            "device_memory": "8",
            "engine_version": "109.0",
            "platform": "PC",
            "screen_width": "2560",
            "screen_height": "1440",
            'effective_type': '4g',
            "round_trip_time": "50",
            "webid": get_web_id(),
            "msToken": xmst or local_storage.get("xmst", ""),
        }
        params.update(common_params)
        query_string = urllib.parse.urlencode(params)

        # 20240927 a-bogus update (JS version)
        post_data = {}
        if request_method == "POST":
            post_data = params

        # 为所有 API 请求生成 a_bogus 签名（包括搜索 API）
        a_bogus = await get_a_bogus(uri, query_string, post_data, headers["User-Agent"], self.playwright_page)
        params["a_bogus"] = a_bogus
        if "search" in uri:
            utils.logger.info(f"[DouYinClient.__process_req_params] Search request a_bogus generated, length={len(a_bogus)}")

    async def request(self, method, url, **kwargs):
        """带自动切换的请求方法：检测到风控/验证码时自动切换Cookie+IP"""
        max_retries = 3
        last_error = None
        response_text = ""

        for attempt in range(max_retries):
            # 如果有账号池，使用当前账号的Cookie
            if self._account_pool:
                account = await self._account_pool.get_healthy_account()
                if account and account.cookie:
                    # 更新Cookie头
                    self.headers["Cookie"] = account.cookie
                    current_account_id = account.account_id
                    current_interface = account.network_interface
                    current_alias = account.cookie_alias
                    current_public_ip = account.public_ip
                    cookie_preview = account.cookie[:30] + "..." if len(account.cookie) > 30 else account.cookie
                    utils.logger.info(
                        f"[DouYinClient.request] >>> {current_alias} | "
                        f"IP: {current_interface} ({current_public_ip}) | "
                        f"Cookie: {cookie_preview} | "
                        f"URL: {url} | "
                        f"attempt {attempt+1}/{max_retries}"
                    )
                else:
                    current_account_id = None
                    current_interface = None
                    current_alias = "默认"
                    current_public_ip = ""
                    utils.logger.warning("[DouYinClient.request] No healthy account available, using default cookie")
            else:
                current_account_id = None
                current_interface = None
                current_alias = "无账号池"
                current_public_ip = ""

            # Check whether the proxy has expired before each request
            await self._refresh_proxy_if_expired()

            try:
                async with make_async_client(
                    proxy=self.proxy,
                    network_interface=current_interface
                ) as client:
                    response = await client.request(method, url, timeout=self.timeout, **kwargs)

                response_text = response.text
                if response_text == "" or response_text == "blocked":
                    utils.logger.error(f"[DouYinClient.request] Blocked response: {response_text}")
                    raise Exception("account blocked")

                result = response.json()

                # 检测风控信号
                fail_type = self._detect_risk(result, response_text)
                if fail_type:
                    if self._account_pool and current_account_id:
                        should_switch = await self._account_pool.report_failure(current_account_id, fail_type)
                        if should_switch and attempt < max_retries - 1:
                            utils.logger.warning(
                                f"[DouYinClient.request] Risk detected ({fail_type}), switching account..."
                            )
                            await self._account_pool.switch_account(fail_type)
                            continue  # 重试
                    raise DataFetchError(f"Risk detected: {fail_type}, response: {response_text[:200]}")

                # 请求成功，报告成功
                if self._account_pool and current_account_id:
                    await self._account_pool.report_success(current_account_id)
                    utils.logger.info(
                        f"[DouYinClient.request] ✓ 成功 | {current_alias} | "
                        f"IP: {current_interface} ({current_public_ip})"
                    )

                return result

            except DataFetchError:
                raise
            except Exception as e:
                last_error = e
                # 分类错误
                from api.services.account_pool import classify_error
                fail_type = classify_error(e, response_text)

                if self._account_pool and current_account_id:
                    should_switch = await self._account_pool.report_failure(current_account_id, fail_type)
                    if should_switch and attempt < max_retries - 1:
                        utils.logger.warning(
                            f"[DouYinClient.request] Error ({fail_type}), switching account..."
                        )
                        await self._account_pool.switch_account(fail_type)
                        continue

                if attempt == max_retries - 1:
                    raise DataFetchError(f"{e}, {response_text}")

    def _detect_risk(self, result: dict, response_text: str) -> Optional[str]:
        """检测响应中的风控信号

        Returns:
            fail_type 如果检测到风控，否则 None
        """
        if not isinstance(result, dict):
            return None

        # status_code 2483 = 被封禁或临时限流
        # 注意: "请先登录，再继续搜索吧" 是搜索接口的临时限流提示，不是真正的 Cookie 失效
        # (后续会自动降级到浏览器搜索，且通常能成功)
        status_code = result.get("status_code")
        if status_code == 2483:
            return "blocked"

        # 搜索结果被拦截
        if "search_nil_info" in result:
            nil_info = result.get("search_nil_info", {})
            nil_type = nil_info.get("search_nil_type", "") if isinstance(nil_info, dict) else ""
            if nil_type == "verify_check":
                data = result.get("data", [])
                if not data:
                    return "verify_check"

        # 频率限制
        status_msg = result.get("status_msg", "") or ""
        if any(kw in str(status_msg) for kw in ["频繁", "频率", "限制", "rate limit"]):
            return "rate_limit"

        # 验证码相关
        if any(kw in response_text.lower() for kw in ["captcha", "verifycenter", "验证码"]):
            return "captcha"

        return None

    async def get(self, uri: str, params: Optional[Dict] = None, headers: Optional[Dict] = None):
        """
        GET请求
        """
        await self.__process_req_params(uri, params, headers)
        headers = headers or self.headers
        # 调试：检查 Cookie 头是否包含 sessionid
        cookie_header = headers.get("Cookie", "")
        has_sessionid = "sessionid" in cookie_header
        if "search" in uri:
            utils.logger.info(f"[DouYinClient.get] Search request - Cookie has sessionid: {has_sessionid}, Cookie length: {len(cookie_header)}")
            # 打印所有 headers 用于调试
            safe_headers = {k: (v[:30] + '...' if len(str(v)) > 30 else v) for k, v in headers.items()}
            utils.logger.info(f"[DouYinClient.get] Search request headers: {safe_headers}")
        return await self.request(method="GET", url=f"{self._host}{uri}", params=params, headers=headers)

    async def post(self, uri: str, data: dict, headers: Optional[Dict] = None):
        await self.__process_req_params(uri, data, headers)
        headers = headers or self.headers
        return await self.request(method="POST", url=f"{self._host}{uri}", data=data, headers=headers)

    async def pong(self, browser_context: BrowserContext) -> bool:
        utils.logger.info("[DouYinClient.pong] Checking login status...")
        try:
            # 获取 localStorage
            utils.logger.info("[DouYinClient.pong] Getting localStorage...")
            try:
                local_storage = await self.playwright_page.evaluate("() => window.localStorage")
                utils.logger.info(f"[DouYinClient.pong] localStorage HasUserLogin: {local_storage.get('HasUserLogin', 'NOT_FOUND')}")
                
                if local_storage.get("HasUserLogin", "") == "1":
                    utils.logger.info("[DouYinClient.pong] Login status confirmed via localStorage")
                    return True
            except Exception as e:
                utils.logger.warning(f"[DouYinClient.pong] Failed to get localStorage: {e}")

            # 检查 Cookie
            utils.logger.info("[DouYinClient.pong] Checking cookies...")
            # 使用不带 urls 参数的 cookies() 获取所有 Cookie，避免某些 Cookie 被过滤
            all_cookies = await browser_context.cookies()
            _, cookie_dict = utils.convert_cookies(all_cookies)
            
            # 检查 LOGIN_STATUS
            login_status = cookie_dict.get("LOGIN_STATUS")
            utils.logger.info(f"[DouYinClient.pong] Cookie LOGIN_STATUS: {login_status}")
            
            if login_status == "1":
                utils.logger.info("[DouYinClient.pong] Login status confirmed via LOGIN_STATUS cookie")
                return True
            
            # 检查是否有 sessionid（抖音登录的关键 cookie）
            sessionid = cookie_dict.get("sessionid")
            utils.logger.info(f"[DouYinClient.pong] Cookie sessionid: {sessionid[:20] if sessionid else 'NOT_FOUND'}...")
            
            if sessionid:
                utils.logger.info("[DouYinClient.pong] Login status confirmed via sessionid cookie")
                return True
            
            # 检查是否有其他登录相关的 cookie
            has_sid = bool(cookie_dict.get("sid_guard") or cookie_dict.get("sid_tt"))
            utils.logger.info(f"[DouYinClient.pong] Has sid cookies: {has_sid}")
            
            if has_sid:
                utils.logger.info("[DouYinClient.pong] Login status confirmed via sid cookies")
                return True
            
            utils.logger.warning("[DouYinClient.pong] Login status check failed - no valid login cookies found")
            return False
        except Exception as e:
            utils.logger.error(f"[DouYinClient.pong] Error checking login: {e}")
            # 如果检查失败，假设未登录，让登录流程继续
            return False

    async def update_cookies(self, browser_context: BrowserContext, urls: Optional[list[str]] = None):
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            browser_context,
            urls=urls or self.cookie_urls,
        )
        self.headers["Cookie"] = cookie_str
        self.cookie_dict = cookie_dict
        # 日志：检查关键 cookie 字段
        has_sessionid = "sessionid" in cookie_dict
        has_sid_guard = "sid_guard" in cookie_dict
        has_sid_tt = "sid_tt" in cookie_dict
        utils.logger.info(f"[DouYinClient.update_cookies] Cookie sync: {len(cookie_dict)} cookies, sessionid={has_sessionid}, sid_guard={has_sid_guard}, sid_tt={has_sid_tt}, cookie_str_len={len(cookie_str)}")
        
        # 从 __druidClientInfo 提取原始 User-Agent，保持与 cookie 生成环境一致
        try:
            druid_info = cookie_dict.get("__druidClientInfo", "")
            if druid_info:
                import base64, urllib.parse
                decoded = urllib.parse.unquote(druid_info)
                # 有些是先 base64 再 urlencode，有些是直接 urlencode
                try:
                    decoded = base64.b64decode(decoded).decode('utf-8', errors='ignore')
                except Exception:
                    pass
                decoded = urllib.parse.unquote(decoded)
                info_json = json.loads(decoded)
                original_ua = info_json.get("userAgent", "")
                if original_ua:
                    self.headers["User-Agent"] = original_ua
                    utils.logger.info(f"[DouYinClient.update_cookies] Updated User-Agent from cookie: {original_ua[:60]}...")
        except Exception as e:
            utils.logger.warning(f"[DouYinClient.update_cookies] Failed to extract UA from cookie: {e}")

    async def search_info_by_keyword_via_browser(
        self,
        keyword: str,
        offset: int = 0,
        page: "Page" = None,
    ):
        """
        通过浏览器页面搜索，拦截网络请求获取搜索结果
        当 HTTP API 返回 2483（请先登录）时使用此方法
        """
        if not page:
            page = self.playwright_page

        result_data = None

        async def handle_response(response):
            nonlocal result_data
            url = response.url
            # 匹配搜索 API 的 URL
            if "search" in url and "aweme" in url and response.status == 200:
                try:
                    data = await response.json()
                    if isinstance(data, dict) and (data.get("data") or data.get("status_code") == 0):
                        result_data = data
                        utils.logger.info(f"[DouYinClient.search_via_browser] Intercepted search response from {url[:100]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            search_url = f"https://www.douyin.com/search/{keyword}?type=general"
            utils.logger.info(f"[DouYinClient.search_via_browser] Navigating to {search_url}")
            await page.goto(search_url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)

            # 检查是否遇到验证码页面
            page_title = await page.title()
            if "验证码" in page_title:
                utils.logger.warning("[DouYinClient.search_via_browser] Captcha page detected, attempting to solve...")
                try:
                    from media_platform.douyin.login import DouYinLogin
                    login_obj = DouYinLogin(
                        login_type="cookie",
                        login_phone="",
                        browser_context=page.context,
                        context_page=page,
                        cookie_str="",
                    )
                    await login_obj.check_page_display_slider(move_step=3, slider_level="hard")
                    # 验证码通过后重新导航
                    await page.goto(search_url, wait_until="networkidle", timeout=60000)
                    await asyncio.sleep(3)
                except Exception as e:
                    utils.logger.error(f"[DouYinClient.search_via_browser] Captcha solve failed: {e}")

            # 滚动页面触发加载
            for i in range(3):
                await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/4})")
                await asyncio.sleep(2)
                if result_data:
                    break

            if result_data:
                utils.logger.info(f"[DouYinClient.search_via_browser] Got search results, data count: {len(result_data.get('data', []))}")
            else:
                # 诊断：检查页面状态
                try:
                    page_state = await page.evaluate("""
                        () => ({
                            url: window.location.href,
                            title: document.title,
                            bodyLen: document.body.innerText.length,
                            bodyPreview: document.body.innerText.substring(0, 300),
                        })
                    """)
                    utils.logger.warning(f"[DouYinClient.search_via_browser] Page state: url={page_state.get('url')}, title={page_state.get('title')}, bodyLen={page_state.get('bodyLen')}")
                    utils.logger.info(f"[DouYinClient.search_via_browser] Body preview: {page_state.get('bodyPreview', '')[:200]}")
                except Exception:
                    pass
        finally:
            page.remove_listener("response", handle_response)

        return result_data or {"data": []}

    async def search_info_by_keyword(
        self,
        keyword: str,
        offset: int = 0,
        search_channel: SearchChannelType = SearchChannelType.GENERAL,
        sort_type: SearchSortType = SearchSortType.GENERAL,
        publish_time: PublishTimeType = PublishTimeType.UNLIMITED,
        search_id: str = "",
    ):
        """
        DouYin Web Search API
        :param keyword:
        :param offset:
        :param search_channel:
        :param sort_type:
        :param publish_time: ·
        :param search_id: ·
        :return:
        """
        query_params = {
            'search_channel': search_channel.value,
            'enable_history': '1',
            'keyword': keyword,
            'search_source': 'tab_search',
            'query_correct_type': '1',
            'is_filter_search': '0',
            'from_group_id': '7378810571505847586',
            'offset': offset,
            'count': '15',
            'need_filter_settings': '1',
            'list_type': 'multi',
            'search_id': search_id,
        }
        if sort_type.value != SearchSortType.GENERAL.value or publish_time.value != PublishTimeType.UNLIMITED.value:
            query_params["filter_selected"] = json.dumps({"sort_type": str(sort_type.value), "publish_time": str(publish_time.value)})
            query_params["is_filter_search"] = 1
            query_params["search_source"] = "tab_search"
        referer_url = f"https://www.douyin.com/search/{keyword}?aid=f594bbd9-a0e2-4651-9319-ebe3cb6298c1&type=general"
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=':/')
        return await self.get("/aweme/v1/web/general/search/single/", query_params, headers=headers)

    async def get_video_by_id(self, aweme_id: str) -> Any:
        """
        DouYin Video Detail API
        :param aweme_id:
        :return:
        """
        params = {"aweme_id": aweme_id}
        headers = copy.copy(self.headers)
        del headers["Origin"]
        res = await self.get("/aweme/v1/web/aweme/detail/", params, headers)
        return res.get("aweme_detail", {})

    async def get_aweme_comments(self, aweme_id: str, cursor: int = 0):
        """get note comments

        """
        uri = "/aweme/v1/web/comment/list/"
        params = {"aweme_id": aweme_id, "cursor": cursor, "count": 20, "item_type": 0}
        keywords = request_keyword_var.get()
        referer_url = "https://www.douyin.com/search/" + keywords + '?aid=3a3cec5a-9e27-4040-b6aa-ef548c2c1138&publish_time=0&sort_type=0&source=search_history&type=general'
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=':/')
        return await self.get(uri, params)

    async def get_sub_comments(self, aweme_id: str, comment_id: str, cursor: int = 0):
        """
            获取子评论
        """
        uri = "/aweme/v1/web/comment/list/reply/"
        params = {
            'comment_id': comment_id,
            "cursor": cursor,
            "count": 20,
            "item_type": 0,
            "item_id": aweme_id,
        }
        keywords = request_keyword_var.get()
        referer_url = "https://www.douyin.com/search/" + keywords + '?aid=3a3cec5a-9e27-4040-b6aa-ef548c2c1138&publish_time=0&sort_type=0&source=search_history&type=general'
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=':/')
        return await self.get(uri, params)

    async def get_aweme_all_comments(
        self,
        aweme_id: str,
        crawl_interval: float = 1.0,
        is_fetch_sub_comments=False,
        callback: Optional[Callable] = None,
        max_count: int = 10,
    ):
        """
        获取帖子的所有评论，包括子评论
        :param aweme_id: 帖子ID
        :param crawl_interval: 抓取间隔
        :param is_fetch_sub_comments: 是否抓取子评论
        :param callback: 回调函数，用于处理抓取到的评论
        :param max_count: 一次帖子爬取的最大评论数量
        :return: 评论列表
        """
        result = []
        comments_has_more = 1
        comments_cursor = 0
        while comments_has_more and len(result) < max_count:
            comments_res = await self.get_aweme_comments(aweme_id, comments_cursor)
            comments_has_more = comments_res.get("has_more", 0)
            comments_cursor = comments_res.get("cursor", 0)
            comments = comments_res.get("comments", [])
            if not comments:
                continue
            if len(result) + len(comments) > max_count:
                comments = comments[:max_count - len(result)]
            result.extend(comments)
            if callback:  # If there is a callback function, execute the callback function
                await callback(aweme_id, comments)

            await asyncio.sleep(crawl_interval)
            if not is_fetch_sub_comments:
                continue
            # Get secondary reviews
            for comment in comments:
                reply_comment_total = comment.get("reply_comment_total")

                if reply_comment_total > 0:
                    comment_id = comment.get("cid")
                    sub_comments_has_more = 1
                    sub_comments_cursor = 0

                    while sub_comments_has_more:
                        sub_comments_res = await self.get_sub_comments(aweme_id, comment_id, sub_comments_cursor)
                        sub_comments_has_more = sub_comments_res.get("has_more", 0)
                        sub_comments_cursor = sub_comments_res.get("cursor", 0)
                        sub_comments = sub_comments_res.get("comments", [])

                        if not sub_comments:
                            continue
                        result.extend(sub_comments)
                        if callback:  # If there is a callback function, execute the callback function
                            await callback(aweme_id, sub_comments)
                        await asyncio.sleep(crawl_interval)
        return result

    async def get_user_info(self, sec_user_id: str):
        uri = "/aweme/v1/web/user/profile/other/"
        params = {
            "sec_user_id": sec_user_id,
            "publish_video_strategy_type": 2,
            "personal_center_strategy": 1,
        }
        return await self.get(uri, params)

    async def get_user_aweme_posts(self, sec_user_id: str, max_cursor: str = "") -> Dict:
        uri = "/aweme/v1/web/aweme/post/"
        params = {
            "sec_user_id": sec_user_id,
            "count": 18,
            "max_cursor": max_cursor,
            "locate_query": "false",
            "publish_video_strategy_type": 2,
        }
        return await self.get(uri, params)

    async def get_all_user_aweme_posts(self, sec_user_id: str, callback: Optional[Callable] = None):
        posts_has_more = 1
        max_cursor = ""
        result = []
        while posts_has_more == 1:
            aweme_post_res = await self.get_user_aweme_posts(sec_user_id, max_cursor)
            posts_has_more = aweme_post_res.get("has_more", 0)
            max_cursor = aweme_post_res.get("max_cursor")
            aweme_list = aweme_post_res.get("aweme_list") if aweme_post_res.get("aweme_list") else []
            utils.logger.info(f"[DouYinClient.get_all_user_aweme_posts] get sec_user_id:{sec_user_id} video len : {len(aweme_list)}")
            if callback:
                await callback(aweme_list)
            result.extend(aweme_list)
        return result

    async def get_aweme_media(self, url: str) -> Union[bytes, None]:
        async with make_async_client(proxy=self.proxy) as client:
            try:
                response = await client.request("GET", url, timeout=self.timeout, follow_redirects=True)
                response.raise_for_status()
                if not response.reason_phrase == "OK":
                    utils.logger.error(f"[DouYinClient.get_aweme_media] request {url} err, res:{response.text}")
                    return None
                else:
                    return response.content
            except httpx.HTTPError as exc:  # some wrong when call httpx.request method, such as connection error, client error, server error or response status code is not 2xx
                utils.logger.error(f"[DouYinClient.get_aweme_media] {exc.__class__.__name__} for {exc.request.url} - {exc}")  # Keep the original exception type name for developers to debug
                return None

    async def resolve_short_url(self, short_url: str) -> str:
        """
        解析抖音短链接,获取重定向后的真实URL
        Args:
            short_url: 短链接,如 https://v.douyin.com/iF12345ABC/
        Returns:
            重定向后的完整URL
        """
        async with make_async_client(proxy=self.proxy, follow_redirects=False) as client:
            try:
                utils.logger.info(f"[DouYinClient.resolve_short_url] Resolving short URL: {short_url}")
                response = await client.get(short_url, timeout=10)

                # Short links usually return a 302 redirect
                if response.status_code in [301, 302, 303, 307, 308]:
                    redirect_url = response.headers.get("Location", "")
                    utils.logger.info(f"[DouYinClient.resolve_short_url] Resolved to: {redirect_url}")
                    return redirect_url
                else:
                    utils.logger.warning(f"[DouYinClient.resolve_short_url] Unexpected status code: {response.status_code}")
                    return ""
            except Exception as e:
                utils.logger.error(f"[DouYinClient.resolve_short_url] Failed to resolve short URL: {e}")
                return ""

    async def send_private_message_via_browser(
        self,
        sec_uid: str,
        message: str,
        browser_context: "BrowserContext",
        page: Optional["Page"] = None,
    ) -> dict:
        """
        通过浏览器自动化发送抖音私信

        利用已有的浏览器上下文和 Cookie，访问用户主页 -> 点击私信按钮 -> 输入消息 -> 发送

        Args:
            sec_uid: 目标用户的 sec_uid
            message: 要发送的私信内容
            browser_context: Playwright 浏览器上下文
            page: 可选的 Playwright 页面，如果不传则新建

        Returns:
            dict: {"success": bool, "error": str, "screenshot": str}
        """
        import random
        result = {"success": False, "error": "", "screenshot": ""}

        try:
            # 创建或使用现有页面
            if page is None:
                page = await browser_context.new_page()

            # Step 1: 访问用户主页
            user_url = f"https://www.douyin.com/user/{sec_uid}"
            utils.logger.info(f"[DouYinClient.send_private_message] Navigating to {user_url}")
            await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(random.uniform(3, 5))

            # 诊断：检查页面是否正确加载
            try:
                page_state = await page.evaluate("""
                    () => {
                        return {
                            url: window.location.href,
                            title: document.title,
                            bodyTextLength: document.body.innerText.length,
                            bodyTextPreview: document.body.innerText.substring(0, 500),
                            hasUserCard: !!document.querySelector('[class*="user"], [class*="author"], [class*="profile"]'),
                        };
                    }
                """)
                utils.logger.info(f"[DouYinClient.send_private_message] Page state: url={page_state.get('url')}, title={page_state.get('title')}, bodyLen={page_state.get('bodyTextLength')}")
                # 如果页面内容太少，可能没有正确加载
                if page_state.get('bodyTextLength', 0) < 100:
                    utils.logger.warning(f"[DouYinClient.send_private_message] Page content too short, may not have loaded correctly. Preview: {page_state.get('bodyTextPreview', '')[:200]}")
                    # 尝试等待更长时间
                    await asyncio.sleep(5)
            except Exception as e:
                utils.logger.warning(f"[DouYinClient.send_private_message] Page state check failed: {e}")

            # Step 2: 查找并点击私信按钮
            pm_clicked = False

            # 先尝试关注（有些用户需要互关才能私信）
            try:
                follow_btn = page.locator('button:has-text("关注")').last
                if await follow_btn.count() > 0 and await follow_btn.is_visible():
                    await follow_btn.click()
                    utils.logger.info(f"[DouYinClient.send_private_message] Clicked follow button")
                    await asyncio.sleep(2)
            except Exception:
                pass

            # 多策略查找私信按钮
            # 策略1: Playwright 文本匹配
            for selector in [
                'button:has-text("私信")',
                'a:has-text("私信")',
                'div:has-text("私信")',
                'span:has-text("私信")',
                '[aria-label*="私信"]',
                '[aria-label*="发消息"]',
                'button:has-text("发消息")',
            ]:
                try:
                    loc = page.locator(selector)
                    count = await loc.count()
                    if count > 0:
                        # 找最后一个（导航栏可能有干扰，用户主页的按钮通常在后面）
                        for i in range(count - 1, -1, -1):
                            el = loc.nth(i)
                            if await el.is_visible():
                                box = await el.bounding_box()
                                # 排除导航栏（y < 80 的通常是顶部导航）
                                if box and box['y'] > 80:
                                    await el.click()
                                    pm_clicked = True
                                    utils.logger.info(f"[DouYinClient.send_private_message] Clicked PM via {selector} (index {i})")
                                    break
                    if pm_clicked:
                        break
                except Exception:
                    continue

            # 策略2: 从关注按钮的兄弟元素中查找私信按钮
            if not pm_clicked:
                try:
                    sibling_result = await page.evaluate("""
                        () => {
                            // 找所有包含"关注"文本的按钮
                            const allBtns = Array.from(document.querySelectorAll('button'));
                            const followBtns = allBtns.filter(b => {
                                const text = b.textContent?.trim();
                                return text === '关注' || text === '已关注';
                            });

                            for (const fb of followBtns) {
                                // 检查兄弟元素
                                const parent = fb.parentElement;
                                if (!parent) continue;
                                const siblings = Array.from(parent.children);
                                for (const sib of siblings) {
                                    const text = (sib.textContent || '').trim();
                                    if (text.includes('私信') || text.includes('发消息')) {
                                        sib.click();
                                        return { success: true, method: 'sibling', text: text };
                                    }
                                }
                                // 检查父元素的父元素
                                const grandparent = parent.parentElement;
                                if (!grandparent) continue;
                                const cousins = Array.from(grandparent.querySelectorAll('button, a, div[role="button"]'));
                                for (const cousin of cousins) {
                                    const text = (cousin.textContent || '').trim();
                                    if ((text.includes('私信') || text.includes('发消息')) && !cousin.contains(fb)) {
                                        cousin.click();
                                        return { success: true, method: 'cousin', text: text };
                                    }
                                }
                            }
                            return { success: false };
                        }
                    """)
                    if sibling_result.get("success"):
                        pm_clicked = True
                        utils.logger.info(f"[DouYinClient.send_private_message] Clicked PM via {sibling_result.get('method')}")
                except Exception as e:
                    utils.logger.warning(f"[DouYinClient.send_private_message] Sibling search failed: {e}")

            # 策略3: 用 JS 遍历所有元素，收集调试信息
            if not pm_clicked:
                try:
                    debug_result = await page.evaluate("""
                        () => {
                            const allElements = Array.from(document.querySelectorAll('*')).filter(el => {
                                return el.offsetParent !== null && el.offsetWidth > 20 && el.offsetHeight > 10;
                            });
                            // 收集所有可见按钮/可点击元素
                            const clickableElements = allElements.filter(el => {
                                const tag = el.tagName.toLowerCase();
                                return tag === 'button' || tag === 'a' || el.getAttribute('role') === 'button';
                            }).map(el => ({
                                tag: el.tagName,
                                text: (el.innerText || el.textContent || '').trim().substring(0, 50),
                                ariaLabel: el.getAttribute('aria-label'),
                                title: el.getAttribute('title'),
                                cls: (typeof el.className === 'string' ? el.className : '').substring(0, 80),
                                rect: {
                                    x: Math.round(el.getBoundingClientRect().x),
                                    y: Math.round(el.getBoundingClientRect().y),
                                    w: Math.round(el.getBoundingClientRect().width),
                                    h: Math.round(el.getBoundingClientRect().height)
                                }
                            }));
                            return { clickableCount: clickableElements.length, clickables: clickableElements.slice(0, 30) };
                        }
                    """)
                    utils.logger.info(f"[DouYinClient.send_private_message] Page has {debug_result.get('clickableCount')} clickable elements")
                    utils.logger.info(f"[DouYinClient.send_private_message] Clickables: {debug_result.get('clickables')}")
                except Exception:
                    pass

            if not pm_clicked:
                result["error"] = "未找到私信按钮"
                return result

            # Step 3: 等待私信对话框加载（等待输入框出现）
            input_locator = None
            input_frame = None

            for wait_round in range(6):
                await asyncio.sleep(2)

                # 每轮先做页面诊断，了解当前状态
                if wait_round == 0:
                    try:
                        diag = await page.evaluate("""
                            () => {
                                const textareas = document.querySelectorAll('textarea');
                                const editables = document.querySelectorAll('[contenteditable="true"]');
                                const inputs = document.querySelectorAll('input[type="text"]');
                                return {
                                    textareaCount: textareas.length,
                                    textareaPlaceholders: Array.from(textareas).map(t => t.placeholder || ''),
                                    editableCount: editables.length,
                                    editableClasses: Array.from(editables).slice(0, 5).map(e => (e.className || '').substring(0, 80)),
                                    inputCount: inputs.length,
                                    inputPlaceholders: Array.from(inputs).map(i => i.placeholder || ''),
                                    hasChatPanel: !!document.querySelector('[class*="chat"], [class*="im-"], [class*="message-panel"]'),
                                    url: window.location.href
                                };
                            }
                        """)
                        utils.logger.info(f"[DouYinClient.send_private_message] Page diagnostic: {diag}")
                    except Exception:
                        pass

                # 跨 frame 查找输入框
                try:
                    frames = page.frames
                except AttributeError:
                    frames = [page]

                for frame in frames:
                    if not hasattr(frame, 'locator'):
                        continue
                    # 按优先级尝试各种选择器
                    for selector in [
                        'textarea[placeholder*="发消息"]',
                        'textarea[placeholder*="私信"]',
                        '[class*="chat-input"] textarea',
                        '[class*="im-input"] textarea',
                        '[class*="chat"] [contenteditable="true"]',
                        '[class*="im-"] [contenteditable="true"]',
                        '[class*="chat-input"]',
                        '[class*="im-input"]',
                        '[class*="editor"][contenteditable]',
                        'textarea',
                        '[contenteditable="true"]',
                        '[contenteditable]:not([contenteditable="false"])',
                        'div[role="textbox"]',
                        'input[placeholder*="发消息"]',
                        'input[placeholder*="私信"]',
                    ]:
                        try:
                            loc = frame.locator(selector).first
                            if await loc.count() > 0 and await loc.is_visible():
                                # 排除搜索框：检查 placeholder 和位置
                                try:
                                    ph = await loc.get_attribute("placeholder") or ""
                                    if "搜索" in ph:
                                        continue
                                    # 排除页面顶部的搜索框（y坐标小于100的通常是导航栏）
                                    box = await loc.bounding_box()
                                    if box and box['y'] < 100:
                                        continue
                                except Exception:
                                    pass

                                input_locator = loc
                                input_frame = frame
                                utils.logger.info(f"[DouYinClient.send_private_message] Found input via {selector} in frame (round {wait_round})")
                                break
                        except Exception:
                            continue
                    if input_locator:
                        break
                if input_locator:
                    break

            if not input_locator:
                # 最后尝试：用 JS 在所有元素中搜索（排除搜索框和导航栏元素）
                try:
                    js_result = await page.evaluate("""
                        () => {
                            const all = Array.from(document.querySelectorAll('div, input, textarea'));
                            // 优先找在聊天面板内的
                            for (const el of all) {
                                const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
                                const isEditable = el.contentEditable === 'true' || el.getAttribute('contenteditable') === 'true';
                                if (isEditable && (cls.includes('chat') || cls.includes('im-') || cls.includes('message'))) {
                                    if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                                        el.setAttribute('data-dm-input', 'true');
                                        return true;
                                    }
                                }
                            }
                            // 回退：找任何可见可编辑区域（排除搜索框）
                            for (const el of all) {
                                const ph = (el.placeholder || '').toLowerCase();
                                const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
                                const isEditable = el.contentEditable === 'true' || el.getAttribute('contenteditable') === 'true';
                                const rect = el.getBoundingClientRect();
                                if (ph.includes('搜索')) continue;
                                if (rect.y < 100) continue;
                                if (isEditable || ph.includes('发消息') || ph.includes('私信') || cls.includes('chat-input') || cls.includes('im-input')) {
                                    if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                                        el.setAttribute('data-dm-input', 'true');
                                        return true;
                                    }
                                }
                            }
                            return false;
                        }
                    """)
                    if js_result:
                        input_locator = page.locator('[data-dm-input="true"]').first
                        utils.logger.info("[DouYinClient.send_private_message] Found input via JS fallback")
                except Exception:
                    pass

            if not input_locator:
                result["error"] = "未找到私信输入框"
                return result

            # Step 4: 输入消息
            try:
                await input_locator.click()
                await asyncio.sleep(0.5)
                tag = await input_locator.evaluate("el => el.tagName.toLowerCase()")
                is_contenteditable = await input_locator.evaluate("el => el.contentEditable === 'true'")
                if tag == 'div' or is_contenteditable:
                    await input_locator.type(message, delay=random.randint(30, 80))
                else:
                    await input_locator.fill(message)
                # 触发事件确保框架捕获
                await input_locator.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles: true})); }")
                utils.logger.info(f"[DouYinClient.send_private_message] Message typed (tag={tag}, contenteditable={is_contenteditable})")
            except Exception as e:
                result["error"] = f"输入消息失败: {e}"
                return result

            await asyncio.sleep(random.uniform(0.5, 1.5))

            # Step 5: 发送消息
            send_success = False

            # 尝试点击发送按钮
            for selector in [
                'button:has-text("发送")',
                '[class*="send"]',
                'button:has-text("Send")',
                '[class*="btn-send"]',
                '[class*="submit"]',
            ]:
                try:
                    btn = page.locator(selector).first
                    if await btn.count() > 0:
                        await btn.click()
                        send_success = True
                        utils.logger.info(f"[DouYinClient.send_private_message] Clicked send button: {selector}")
                        break
                except Exception:
                    continue

            # 回退：按 Enter 键发送
            if not send_success:
                try:
                    # 对 contenteditable div 按 Enter
                    await input_locator.press("Enter")
                    send_success = True
                    utils.logger.info("[DouYinClient.send_private_message] Sent via Enter key")
                except Exception:
                    pass

            if not send_success:
                result["error"] = "未找到发送按钮"
                return result

            await asyncio.sleep(random.uniform(2, 4))

            # Step 6: 风控检测
            risk_check = await page.evaluate("""
                () => {
                    const keywords = ['发送失败', '系统繁忙', '操作频繁', '暂时无法', '请稍后再试', '账号异常'];
                    const body = document.body.innerText;
                    for (const kw of keywords) {
                        if (body.includes(kw)) return { hasRisk: true, keyword: kw };
                    }
                    return { hasRisk: false };
                }
            """)

            if risk_check.get("hasRisk"):
                result["error"] = f"风控拦截: {risk_check.get('keyword')}"
                return result

            result["success"] = True
            utils.logger.info(f"[DouYinClient.send_private_message] Message sent successfully to {sec_uid}")

        except Exception as e:
            result["error"] = str(e)
            utils.logger.error(f"[DouYinClient.send_private_message] Error: {e}")

        return result
