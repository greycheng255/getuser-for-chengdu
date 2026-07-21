# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/x_twitter/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1


import asyncio
import json
import os
import random
from asyncio import Task
from typing import Dict, List, Optional

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

import config
from base.base_crawler import AbstractCrawler
from tools import utils
from tools.cdp_browser import CDPBrowserManager

from .client import XTwitterClient
from .field import SearchType
from .login import XTwitterLogin

from store import x_twitter as x_twitter_store


class XTwitterCrawler(AbstractCrawler):
    context_page: Page
    x_twitter_client: XTwitterClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://x.com"
        self.cookie_urls = ["https://x.com", "https://www.x.com"]
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        self.cdp_manager = None
        self._posted_comments = []
        self._replied_to = set()
        self._reply_monitor_task: Optional[Task] = None

    async def start(self) -> None:
        async with async_playwright() as playwright:
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[XTwitterCrawler] Launching browser using CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    None,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
                await self.cdp_manager.add_stealth_script()
            else:
                utils.logger.info("[XTwitterCrawler] Launching browser using standard mode")
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    None,
                    self.user_agent,
                    headless=config.HEADLESS,
                )
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            utils.logger.info(f"[XTwitterCrawler] Navigating to {self.index_url}...")
            try:
                await self.context_page.goto(
                    self.index_url,
                    wait_until="networkidle",
                    timeout=60000,
                )
            except Exception as e:
                utils.logger.warning(f"[XTwitterCrawler] Initial navigation failed: {e}, retrying...")
                await self.context_page.goto(
                    self.index_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            await asyncio.sleep(random.uniform(3, 5))
            
            try:
                await self.context_page.evaluate("window.scrollBy(0, 300)")
                await asyncio.sleep(random.uniform(1, 2))
                await self.context_page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(random.uniform(1, 2))
            except Exception as e:
                utils.logger.warning(f"[XTwitterCrawler.start] Scroll simulation error: {e}")

            self.x_twitter_client = await self.create_x_twitter_client()
            
            if config.COOKIES:
                login_obj = XTwitterLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
            
            await self.x_twitter_client.update_cookies(
                browser_context=self.browser_context,
            )

            startup_delay = random.uniform(5, 10)
            utils.logger.info(f"[XTwitterCrawler.start] Waiting {startup_delay:.1f}s before starting crawl...")
            await asyncio.sleep(startup_delay)

            if config.CRAWLER_TYPE == "search":
                await self.search()
            elif config.CRAWLER_TYPE == "trending":
                await self.crawl_trending()
            elif config.CRAWLER_TYPE == "auto_comment":
                await self.auto_comment_flow()
            elif config.CRAWLER_TYPE == "detail":
                await self.get_specified_posts()
            else:
                await self.crawl_trending()

            utils.logger.info("[XTwitterCrawler.start] X Twitter Crawler finished ...")

    async def launch_browser(self, chromium: BrowserType, playwright_proxy: Optional[Dict], user_agent: Optional[str], headless: bool = True) -> BrowserContext:
        return await chromium.launch_persistent_context(
            user_data_dir=os.path.join(os.getcwd(), "browser_data", "x_twitter_user_data_dir"),
            headless=headless,
            viewport={"width": 1920, "height": 1080},
            user_agent=user_agent,
        )

    async def launch_browser_with_cdp(self, playwright: Playwright, playwright_proxy: Optional[Dict], user_agent: Optional[str], headless: bool = True) -> BrowserContext:
        self.cdp_manager = CDPBrowserManager()
        user_data_dir = os.path.join(os.getcwd(), "browser_data", "cdp_x_twitter_user_data_dir")
        self.cdp_manager.user_data_dir_override = user_data_dir
        browser_context = await self.cdp_manager.launch_and_connect(
            playwright=playwright,
            playwright_proxy=playwright_proxy,
            user_agent=user_agent,
            headless=headless,
        )
        return browser_context

    async def create_x_twitter_client(self) -> XTwitterClient:
        cookies = await self.browser_context.cookies()
        cookie_dict = {}
        for cookie in cookies:
            cookie_dict[cookie["name"]] = cookie["value"]

        cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        headers = {
            "Cookie": cookie_str,
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Referer": "https://x.com/",
            "Sec-Ch-Ua": '"Chromium";v="126", "Not;A=Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Twitter-Active-User": "yes",
            "X-Twitter-Client-Language": "en",
        }

        return XTwitterClient(
            headers=headers,
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
        )

    async def search(self) -> None:
        utils.logger.info("[XTwitterCrawler.search] Begin search X Twitter keywords")

        for keyword in config.KEYWORDS.split(","):
            keyword = keyword.strip()
            if not keyword:
                continue
            utils.logger.info(f"[XTwitterCrawler.search] Current search keyword: {keyword}")

            posts = await self.x_twitter_client.search_posts(
                keyword=keyword,
                max_count=config.X_TWITTER_MAX_POSTS,
            )

            for post in posts:
                await self._process_post(post)

    async def crawl_trending(self) -> None:
        utils.logger.info("[XTwitterCrawler.crawl_trending] Crawling trending topics")

        trending_topics = await self.x_twitter_client.get_trending_topics()
        utils.logger.info(f"[XTwitterCrawler.crawl_trending] Found {len(trending_topics)} trending topics")

        total_topics = min(len(trending_topics), 5)
        for idx, topic in enumerate(trending_topics[:5]):
            utils.logger.info(f"[XTwitterCrawler.crawl_trending] Processing topic: {topic['topic']}")

            # WebSocket 推送: 爬取进度
            try:
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'api'))
                from routers.websocket import notify_x_twitter_crawl_progress
                await notify_x_twitter_crawl_progress(idx + 1, total_topics, topic["topic"])
            except Exception:
                pass
            
            posts = await self.x_twitter_client.search_posts(
                keyword=topic["topic"],
                max_count=config.X_TWITTER_MAX_POSTS,
            )

            for post in posts:
                await self._process_post(post)

    async def auto_comment_flow(self) -> None:
        """全自动评论 + 自动回复流程

        流程:
        1. 获取 trending topics(失败时用 fallback 关键词)
        2. 每个 topic 搜索帖子
        3. 对前 N 条帖子(默认 5,可配置 X_TWITTER_AUTO_COMMENT_MAX_POSTS)发送 AI 评论
        4. 评论全部发送后,启动 comment_reply_monitor 持续监控回复(替代旧的 _check_replies)
        5. monitor 持续运行直到程序被 Ctrl+C 终止(不再 sleep 300 退出)

        P1-3 改造:废弃 core.py 自带的 _check_replies(基于 notifications API,可能漏回复),
        统一委托给 api/services/comment_reply_monitor.py(基于评论页面爬取,更可靠)。
        """
        utils.logger.info("[XTwitterCrawler.auto_comment_flow] Starting auto-comment flow")

        trending_topics = await self.x_twitter_client.get_trending_topics()

        if not trending_topics:
            utils.logger.warning("[XTwitterCrawler.auto_comment_flow] No trending topics found, using fallback keywords")
            trending_topics = [
                {"topic": "AI"},
                {"topic": "technology"},
                {"topic": "programming"},
                {"topic": "coding"},
                {"topic": "software"},
            ]

        selected_posts = []
        for topic in trending_topics[:3]:
            posts = await self.x_twitter_client.search_posts(
                keyword=topic["topic"],
                max_count=5,
            )
            selected_posts.extend(posts)

        # P2-2: 处理条数可配置(默认 5)
        max_posts = int(getattr(config, "X_TWITTER_AUTO_COMMENT_MAX_POSTS", 5))
        if max_posts < 1:
            max_posts = 5

        for post in selected_posts[:max_posts]:
            utils.logger.info(f"[XTwitterCrawler.auto_comment_flow] Processing post: {post['post_url']}")

            await self._process_post(post)

            if config.X_TWITTER_AUTO_COMMENT_ENABLED:
                await self._post_comment_to_post(post)

            await asyncio.sleep(random.uniform(30, 60))

        utils.logger.info(
            f"[XTwitterCrawler.auto_comment_flow] 所有 {min(len(selected_posts), max_posts)} 条帖子评论已发送,"
            f"启动持续回复监控..."
        )

        # P0-3 + P1-3:统一委托 comment_reply_monitor 持续运行
        # 旧的 _start_reply_monitor + _check_replies(基于 notifications API)已废弃,
        # 因为 comment_reply_monitor 基于评论页面爬取,更可靠且支持幂等性。
        if config.X_TWITTER_AUTO_REPLY_ENABLED:
            monitor_started = await self._start_persistent_reply_monitor()
            if monitor_started:
                # monitor 在后台 task 持续运行,主流程进入等待循环(直到 Ctrl+C)
                utils.logger.info("[XTwitterCrawler.auto_comment_flow] 进入持续运行状态,等待回复监控(Ctrl+C 退出)")
                try:
                    while True:
                        await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    utils.logger.info("[XTwitterCrawler.auto_comment_flow] 收到取消信号,退出")
            else:
                # comment_reply_monitor 启动失败,fall back 到旧的 _start_reply_monitor(避免完全无监控)
                utils.logger.warning("[XTwitterCrawler.auto_comment_flow] comment_reply_monitor 启动失败,回退到内置监控")
                self._start_reply_monitor()
                try:
                    while True:
                        await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    utils.logger.info("[XTwitterCrawler.auto_comment_flow] 内置监控被取消,退出")

    async def _start_persistent_reply_monitor(self) -> bool:
        """启动 comment_reply_monitor 服务作为持久后台任务

        委托给 api/services/comment_reply_monitor.py,而非使用 core.py 自带的 _check_replies。
        Returns:
            bool: True 启动成功;False 启动失败(调用方回退到 _start_reply_monitor)
        """
        try:
            import sys
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            from api.services.comment_reply_monitor import start_monitor, is_monitor_running
            if is_monitor_running():
                utils.logger.info("[XTwitterCrawler._start_persistent_reply_monitor] comment_reply_monitor 已在运行")
                return True
            ok = await start_monitor()
            if ok:
                utils.logger.info("[XTwitterCrawler._start_persistent_reply_monitor] comment_reply_monitor 已启动,持续运行")
                return True
            utils.logger.warning("[XTwitterCrawler._start_persistent_reply_monitor] start_monitor 返回 False")
            return False
        except Exception as e:
            utils.logger.error(f"[XTwitterCrawler._start_persistent_reply_monitor] 启动失败: {e}")
            return False

    async def get_specified_posts(self) -> None:
        utils.logger.info("[XTwitterCrawler.get_specified_posts] Getting specified posts")
        pass

    async def _process_post(self, post: Dict) -> None:
        utils.logger.info(f"[XTwitterCrawler._process_post] Processing post: {post.get('post_id', '')}")

        await x_twitter_store.update_x_twitter_post(post)

        if config.X_TWITTER_VIDEO_BREAKDOWN_ENABLED and post.get("video_url"):
            await self._breakdown_video(post)

        if config.ENABLE_GET_COMMENTS:
            comments = await self.x_twitter_client.get_post_comments(
                post_url=post["post_url"],
                max_count=config.X_TWITTER_MAX_COMMENTS,
            )
            utils.logger.info(f"[XTwitterCrawler._process_post] Found {len(comments)} comments for post {post['post_id']}")
            
            for comment in comments:
                await x_twitter_store.update_x_twitter_comment(post["post_id"], comment)

        await asyncio.sleep(random.uniform(2, 5))

    async def _post_comment_to_post(self, post: Dict) -> None:
        """给指定帖子发送评论

        评论内容来源(优先级):
        1. AI 生成评论(调用 api.services.ai_agent_client.generate_comments)—— 默认
           - P2-1: 视频帖子优先调用 generate_video_breakdown 获取分镜,
             再用 breakdown 作为上下文生成更针对性的评论
        2. 兜底:从 X_TWITTER_COMMENT_TEMPLATES 随机选模板

        同时持久化到 XTwitterSentComment 表,使 comment_reply_monitor 能监控该评论的回复。
        """
        try:
            comment_content = ""

            # 1. 优先 AI 生成评论
            if getattr(config, "X_TWITTER_AI_COMMENT_ENABLED", True):
                try:
                    # sys.path 注入:core.py 在 media_platform/x_twitter/,需要回到项目根
                    import sys
                    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                    if project_root not in sys.path:
                        sys.path.insert(0, project_root)
                    from api.services.ai_agent_client import generate_comments, generate_video_breakdown

                    # P2-1: 视频帖子优先调用 generate_video_breakdown 获取分镜,
                    # 再用 breakdown 作为上下文调用 generate_comments 生成更针对性的评论
                    breakdown = ""
                    if post.get("video_url"):
                        try:
                            breakdown = await generate_video_breakdown(post)
                            utils.logger.info(
                                f"[XTwitterCrawler._post_comment_to_post] 视频帖子 {post.get('post_id', '')} "
                                f"已生成分镜({len(breakdown)} 字符),用于增强评论上下文"
                            )
                        except Exception as bd_err:
                            utils.logger.warning(f"[XTwitterCrawler._post_comment_to_post] 生成视频分镜失败,继续无分镜: {bd_err}")

                    ai_comments = await generate_comments(post, breakdown=breakdown, count=1)
                    if ai_comments:
                        comment_content = ai_comments[0]
                        utils.logger.info(f"[XTwitterCrawler._post_comment_to_post] AI 生成评论: {comment_content[:50]}...")
                except Exception as ai_err:
                    utils.logger.warning(f"[XTwitterCrawler._post_comment_to_post] AI 生成评论失败,回退到模板: {ai_err}")

            # 2. 兜底:模板
            if not comment_content:
                templates = getattr(config, "X_TWITTER_COMMENT_TEMPLATES", []) or ["Interesting post!"]
                comment_content = random.choice(templates)

            utils.logger.info(f"[XTwitterCrawler._post_comment_to_post] Posting comment: {comment_content}")

            success = await self.x_twitter_client.post_comment(
                post_url=post["post_url"],
                content=comment_content,
            )

            if success:
                self._posted_comments.append({
                    "post_id": post["post_id"],
                    "post_url": post["post_url"],
                    "content": comment_content,
                    "timestamp": asyncio.get_event_loop().time(),
                })
                utils.logger.info(f"[XTwitterCrawler._post_comment_to_post] Comment posted successfully to {post['post_url']}")

                # 持久化到 XTwitterSentComment 表,使 comment_reply_monitor 能监控该评论的回复
                try:
                    import sys
                    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                    if project_root not in sys.path:
                        sys.path.insert(0, project_root)
                    from database.db_session import get_session
                    from database.models import XTwitterSentComment
                    import time as _time
                    now = int(_time.time())
                    async with get_session() as session:
                        sc = XTwitterSentComment(
                            post_id=post.get("post_id", ""),
                            post_url=post.get("post_url", ""),
                            post_content=(post.get("content") or "")[:500],
                            post_username=post.get("username", ""),
                            video_url=post.get("video_url", ""),
                            comment_content=comment_content,
                            comment_url="",
                            sent_status="success",
                            sent_error="",
                            sent_at=now,
                            source="auto_comment_flow",
                            monitoring=1,  # 默认开启监控,让 comment_reply_monitor 接管
                            last_check_ts=0,
                            reply_count=0,
                            auto_replied_count=0,
                            add_ts=now,
                            last_modify_ts=now,
                        )
                        session.add(sc)
                        await session.commit()
                        utils.logger.info(f"[XTwitterCrawler._post_comment_to_post] 已持久化到 XTwitterSentComment id={sc.id}")
                except Exception as db_err:
                    utils.logger.warning(f"[XTwitterCrawler._post_comment_to_post] 持久化评论失败(不影响主流程): {db_err}")
            else:
                utils.logger.warning(f"[XTwitterCrawler._post_comment_to_post] Failed to post comment to {post['post_url']}")

        except Exception as e:
            utils.logger.error(f"[XTwitterCrawler._post_comment_to_post] Error: {e}")

    def _start_reply_monitor(self) -> None:
        async def monitor_replies():
            while True:
                try:
                    utils.logger.info("[XTwitterCrawler.monitor_replies] Checking for new replies...")
                    await self._check_replies()
                except Exception as e:
                    utils.logger.error(f"[XTwitterCrawler.monitor_replies] Error: {e}")
                
                await asyncio.sleep(config.X_TWITTER_REPLY_CHECK_INTERVAL)

        self._reply_monitor_task = asyncio.create_task(monitor_replies())

    async def _check_replies(self) -> None:
        try:
            notifications = await self.x_twitter_client.get_notifications(max_count=20)

            for notification in notifications:
                text = notification.get("text", "")
                
                if "replied to your Tweet" in text or "回复了你的推文" in text:
                    comment_url = self._extract_comment_url(text)
                    if comment_url and comment_url not in self._replied_to:
                        # WebSocket 推送: 收到新回复
                        try:
                            import sys
                            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'api'))
                            from routers.websocket import notify_x_twitter_reply, notify_x_twitter_reply_sent
                            await notify_x_twitter_reply(
                                post_id=comment_url.split('/status/')[-1] if '/status/' in comment_url else '',
                                comment_url=comment_url,
                                reply_content=text[:200],
                                replied_by=notification.get("user", {}).get("screen_name", ""),
                            )
                        except Exception as ws_err:
                            utils.logger.warning(f"[XTwitterCrawler._check_replies] WS notify error: {ws_err}")

                        await self._auto_reply_to_comment(comment_url, text)
                        self._replied_to.add(comment_url)

                        # WebSocket 推送: AI 回复已发送
                        try:
                            await notify_x_twitter_reply_sent(
                                post_id=comment_url.split('/status/')[-1] if '/status/' in comment_url else '',
                                comment_url=comment_url,
                                reply_content="AI auto-reply sent",
                            )
                        except Exception:
                            pass

        except Exception as e:
            utils.logger.error(f"[XTwitterCrawler._check_replies] Error: {e}")

    def _extract_comment_url(self, notification_text: str) -> str:
        try:
            import re
            url_match = re.search(r"https?://x\.com/[^/\s]+/status/\d+", notification_text)
            if url_match:
                return url_match.group(0)
            return ""
        except:
            return ""

    def _match_keyword_reply(self, text: str) -> Optional[str]:
        """关键词匹配回复: 根据评论内容匹配预设关键词模板

        按优先级匹配,命中后随机返回一条模板回复。
        """
        rules = getattr(config, "X_TWITTER_KEYWORD_REPLY_RULES", [])
        if not rules:
            return None

        text_lower = text.lower()
        # 按 priority 排序
        sorted_rules = sorted(rules, key=lambda r: r.get("priority", 99))

        for rule in sorted_rules:
            keywords = rule.get("keywords", [])
            if any(kw.lower() in text_lower for kw in keywords):
                replies = rule.get("replies", [])
                if replies:
                    return random.choice(replies)
        return None

    async def _auto_reply_to_comment(self, comment_url: str, notification_text: str) -> None:
        try:
            reply_content = None

            # 1. 关键词匹配优先
            if getattr(config, "X_TWITTER_KEYWORD_MATCH_FIRST", True):
                reply_content = self._match_keyword_reply(notification_text)
                if reply_content:
                    utils.logger.info(f"[XTwitterCrawler._auto_reply_to_comment] Matched keyword reply: {reply_content}")

            # 2. AI 回复
            if not reply_content and config.X_TWITTER_AI_REPLY_ENABLED:
                reply_content = await self._generate_ai_reply(notification_text)

            # 3. 默认兜底回复
            if not reply_content:
                reply_content = random.choice([
                    "Thanks for your reply! 😊",
                    "Great point! Let me think about that.",
                    "Appreciate your feedback! 🙏",
                    "Interesting perspective! 💯",
                ])

            utils.logger.info(f"[XTwitterCrawler._auto_reply_to_comment] Replying with: {reply_content}")

            success = await self.x_twitter_client.reply_to_comment(
                comment_url=comment_url,
                content=reply_content,
            )

            if success:
                utils.logger.info(f"[XTwitterCrawler._auto_reply_to_comment] Reply sent successfully to {comment_url}")
            else:
                utils.logger.warning(f"[XTwitterCrawler._auto_reply_to_comment] Failed to send reply to {comment_url}")

        except Exception as e:
            utils.logger.error(f"[XTwitterCrawler._auto_reply_to_comment] Error: {e}")

    async def _generate_ai_reply(self, context_text: str) -> str:
        try:
            system_prompt = getattr(config, "X_TWITTER_AI_REPLY_SYSTEM_PROMPT",
                "你是一个活跃的社交媒体用户，擅长用轻松友好的语气回复评论。")
            user_prompt = f"请回复以下评论内容:\n\n{context_text}\n\n请直接给出回复内容，不要解释。"

            api_key = config.X_TWITTER_AI_API_KEY
            base_url = config.X_TWITTER_AI_BASE_URL
            model = config.X_TWITTER_AI_MODEL

            if not api_key:
                utils.logger.warning("[XTwitterCrawler._generate_ai_reply] AI API key not configured, using fallback reply")
                return "Thanks for your reply! 😊"

            import httpx
            response = await httpx.post(
                f"{base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 100,
                },
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                reply = result["choices"][0]["message"]["content"].strip()
                return reply
            else:
                utils.logger.warning(f"[XTwitterCrawler._generate_ai_reply] AI API failed: {response.status_code}")
                return "Thanks for your reply! 😊"

        except Exception as e:
            utils.logger.error(f"[XTwitterCrawler._generate_ai_reply] Error: {e}")
            return "Thanks for your reply! 😊"

    async def _breakdown_video(self, post: Dict) -> None:
        utils.logger.info(f"[XTwitterCrawler._breakdown_video] Breaking down video: {post['post_url']}")

        try:
            content = post.get("content", "")
            video_url = post.get("video_url", "")

            prompt = f"""
请分析以下X平台热门视频，进行脚本和分镜拆解：

视频内容/描述: {content}
视频链接: {video_url}

请输出以下内容：
1. 【脚本分析】- 视频的核心脚本内容，包括开场白、主体内容、结尾呼吁
2. 【分镜拆解】- 视频的镜头结构，列出主要镜头及其画面内容
3. 【关键要点】- 视频传达的核心信息点
4. 【推荐评论】- 针对该视频的3条高互动评论建议

请用中文输出，格式清晰。
            """.strip()

            api_key = config.X_TWITTER_AI_API_KEY
            base_url = config.X_TWITTER_AI_BASE_URL
            model = config.X_TWITTER_AI_MODEL

            if not api_key:
                utils.logger.warning("[XTwitterCrawler._breakdown_video] AI API key not configured, skipping video breakdown")
                return

            import httpx
            response = await httpx.post(
                f"{base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 500,
                },
                timeout=60,
            )

            if response.status_code == 200:
                result = response.json()
                breakdown = result["choices"][0]["message"]["content"].strip()
                
                breakdown_dir = os.path.join(os.getcwd(), "data", "video_breakdown")
                os.makedirs(breakdown_dir, exist_ok=True)
                
                filename = f"{post['post_id']}_breakdown.txt"
                filepath = os.path.join(breakdown_dir, filename)
                
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"视频链接: {post['post_url']}\n")
                    f.write(f"发布者: {post.get('username', '')}\n")
                    f.write(f"发布时间: {post.get('created_at', '')}\n")
                    f.write("=" * 50 + "\n")
                    f.write(breakdown)
                
                utils.logger.info(f"[XTwitterCrawler._breakdown_video] Video breakdown saved to: {filepath}")

                # WebSocket 推送: 视频拆解完成
                try:
                    import sys
                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'api'))
                    from routers.websocket import notify_x_twitter_breakdown
                    await notify_x_twitter_breakdown(
                        post_id=post["post_id"],
                        post_url=post["post_url"],
                    )
                except Exception as ws_err:
                    utils.logger.warning(f"[XTwitterCrawler._breakdown_video] WS notify error: {ws_err}")
            else:
                utils.logger.warning(f"[XTwitterCrawler._breakdown_video] AI API failed: {response.status_code}")

        except Exception as e:
            utils.logger.error(f"[XTwitterCrawler._breakdown_video] Error: {e}")