# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/x_twitter/client.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1


import asyncio
import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

import httpx
from playwright.async_api import BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_not_exception_type
from tools.httpx_util import make_async_client

import config
from base.base_crawler import AbstractApiClient
from tools import utils

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool


class XTwitterClient(AbstractApiClient):

    def __init__(
        self,
        timeout=60,
        proxy=None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
        proxy_ip_pool: Optional["ProxyIpPool"] = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://x.com"
        self._api_host = "https://api.x.com"
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self._session = make_async_client(proxy=proxy)
        self.logger = utils.logger

    async def request(self, method, url, **kwargs) -> Union[str, Any]:
        return_response = kwargs.pop("return_response", False)
        
        try:
            headers = kwargs.get("headers", {})
            headers.update(self.headers)
            
            if self.proxy:
                kwargs["proxy"] = self.proxy
            
            response = await self._session.request(
                method, url, timeout=self.timeout, headers=headers, **kwargs
            )
            
            if return_response:
                return response
            
            try:
                return response.json()
            except:
                return response.text
                
        except Exception as e:
            self.logger.error(f"[XTwitterClient.request] Request failed: {e}")
            raise

    async def update_cookies(self, browser_context: BrowserContext):
        cookies = await browser_context.cookies()
        cookie_dict = {}
        for cookie in cookies:
            cookie_dict[cookie["name"]] = cookie["value"]
        
        self.cookie_dict = cookie_dict
        
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        self.headers["Cookie"] = cookie_str
        
        self.logger.info(f"[XTwitterClient.update_cookies] Updated {len(cookie_dict)} cookies")

    async def pong(self) -> bool:
        try:
            await self.playwright_page.goto("https://x.com/home", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            return await self._is_logged_in()
        except:
            return False

    async def _is_logged_in(self) -> bool:
        try:
            await self.playwright_page.wait_for_selector('div[data-testid="SideNav_NewTweet_Button"]', timeout=5000)
            return True
        except:
            try:
                await self.playwright_page.wait_for_selector('a[href="/compose/tweet"]', timeout=3000)
                return True
            except:
                return False

    async def get_trending_topics(self) -> List[Dict]:
        self.logger.info("[XTwitterClient.get_trending_topics] Fetching trending topics")
        
        try:
            await self.playwright_page.goto("https://x.com/explore/tabs/trending", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
            
            trending_data = []
            topic_selectors = await self.playwright_page.query_selector_all('div[data-testid="trend"]')
            
            for idx, topic_selector in enumerate(topic_selectors[:10]):
                try:
                    topic_name = await topic_selector.inner_text()
                    topic_name = topic_name.split('\n')[0] if '\n' in topic_name else topic_name
                    trending_data.append({
                        "rank": idx + 1,
                        "topic": topic_name,
                        "url": f"https://x.com/hashtag/{topic_name.replace('#', '')}"
                    })
                except Exception as e:
                    self.logger.warning(f"[XTwitterClient.get_trending_topics] Failed to parse topic {idx}: {e}")
            
            self.logger.info(f"[XTwitterClient.get_trending_topics] Found {len(trending_data)} trending topics")
            return trending_data
            
        except Exception as e:
            self.logger.error(f"[XTwitterClient.get_trending_topics] Failed: {e}")
            return []

    async def search_posts(self, keyword: str, max_count: int = 20) -> List[Dict]:
        self.logger.info(f"[XTwitterClient.search_posts] Searching for: {keyword}")
        
        try:
            search_url = f"https://x.com/search?q={keyword}"
            await self.playwright_page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(5)
            
            page_title = await self.playwright_page.title()
            self.logger.info(f"[XTwitterClient.search_posts] Page title: {page_title}")
            
            posts_data = []
            scroll_count = 0
            max_scroll = 5
            
            while len(posts_data) < max_count and scroll_count < max_scroll:
                tweet_selectors = await self.playwright_page.query_selector_all('article[data-testid="tweet"]')
                self.logger.info(f"[XTwitterClient.search_posts] Found {len(tweet_selectors)} tweet selectors")
                
                if not tweet_selectors:
                    tweet_selectors = await self.playwright_page.query_selector_all('article')
                    self.logger.info(f"[XTwitterClient.search_posts] Fallback: Found {len(tweet_selectors)} article elements")
                
                for tweet_selector in tweet_selectors:
                    if len(posts_data) >= max_count:
                        break
                    
                    try:
                        post_data = await self._parse_tweet(tweet_selector)
                        if post_data:
                            posts_data.append(post_data)
                    except Exception as e:
                        self.logger.warning(f"[XTwitterClient.search_posts] Failed to parse tweet: {e}")
                
                if len(posts_data) < max_count:
                    await self.playwright_page.evaluate("window.scrollBy(0, 1000)")
                    await asyncio.sleep(3)
                    scroll_count += 1
            
            self.logger.info(f"[XTwitterClient.search_posts] Found {len(posts_data)} posts for keyword: {keyword}")
            return posts_data
            
        except Exception as e:
            self.logger.error(f"[XTwitterClient.search_posts] Failed: {e}")
            return []


    async def _parse_tweet(self, tweet_selector) -> Optional[Dict]:
        try:
            tweet_id = await tweet_selector.get_attribute("data-tweet-id")
            
            if not tweet_id:
                permalink = await tweet_selector.query_selector('a[href*="/status/"]')
                if permalink:
                    href = await permalink.get_attribute("href")
                    if href:
                        parts = href.split("/status/")
                        if len(parts) > 1:
                            tweet_id = parts[1].split("?")[0]
            
            if not tweet_id:
                return None
            
            user_info = await tweet_selector.query_selector('div[data-testid="User-Name"]')
            if not user_info:
                user_info = await tweet_selector.query_selector('span[data-testid="User-Name"]')
            
            username = ""
            nickname = ""
            if user_info:
                spans = await user_info.query_selector_all("span")
                if spans:
                    username = await spans[0].inner_text() if spans[0] else ""
                    if len(spans) > 1:
                        nickname = await spans[1].inner_text() if spans[1] else ""
            
            avatar_elem = await tweet_selector.query_selector('img[data-testid="UserAvatar-Container"]')
            if not avatar_elem:
                avatar_elem = await tweet_selector.query_selector('img[alt*="Avatar"]')
            avatar = await avatar_elem.get_attribute("src") if avatar_elem else ""
            
            content_elem = await tweet_selector.query_selector('div[data-testid="tweetText"]')
            if not content_elem:
                content_elem = await tweet_selector.query_selector('[data-testid="tweetText"]')
            content = await content_elem.inner_text() if content_elem else ""
            
            image_urls = []
            image_selectors = await tweet_selector.query_selector_all('img[data-testid="tweetImage"]')
            for img_selector in image_selectors:
                img_url = await img_selector.get_attribute("src")
                if img_url:
                    image_urls.append(img_url)
            
            video_url = ""
            video_selector = await tweet_selector.query_selector('video')
            if video_selector:
                video_url = await video_selector.get_attribute("src") or ""
            
            likes_count = await self._get_tweet_stat(tweet_selector, "like")
            retweets_count = await self._get_tweet_stat(tweet_selector, "retweet")
            replies_count = await self._get_tweet_stat(tweet_selector, "reply")
            bookmarks_count = await self._get_tweet_stat(tweet_selector, "bookmark")
            views_count = await self._get_tweet_stat(tweet_selector, "view")
            
            return {
                "post_id": tweet_id,
                "user_id": "",
                "username": username,
                "nickname": nickname,
                "avatar": avatar,
                "content": content,
                "image_urls": image_urls,
                "video_url": video_url,
                "video_duration": 0,
                "likes_count": likes_count,
                "retweets_count": retweets_count,
                "replies_count": replies_count,
                "bookmarks_count": bookmarks_count,
                "views_count": views_count,
                "created_at": 0,
                "post_url": f"https://x.com/i/web/status/{tweet_id}",
                "is_retweet": False,
                "original_post_id": "",
                "lang": "",
            }
            
        except Exception as e:
            self.logger.warning(f"[XTwitterClient._parse_tweet] Parse error: {e}")
            return None

    async def _get_tweet_stat(self, tweet_selector, stat_type: str) -> str:
        try:
            stat_selector = None
            if stat_type == "like":
                stat_selector = await tweet_selector.query_selector('div[data-testid="like"]')
            elif stat_type == "retweet":
                stat_selector = await tweet_selector.query_selector('div[data-testid="retweet"]')
            elif stat_type == "reply":
                stat_selector = await tweet_selector.query_selector('div[data-testid="reply"]')
            elif stat_type == "bookmark":
                stat_selector = await tweet_selector.query_selector('div[data-testid="bookmark"]')
            elif stat_type == "view":
                stat_selector = await tweet_selector.query_selector('div[data-testid="view"]')
            
            if stat_selector:
                text = await stat_selector.inner_text()
                return text
            return "0"
        except:
            return "0"

    async def get_post_comments(self, post_url: str, max_count: int = 100) -> List[Dict]:
        self.logger.info(f"[XTwitterClient.get_post_comments] Fetching comments for: {post_url}")
        
        try:
            await self.playwright_page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)
            
            comments_data = []
            scroll_count = 0
            max_scroll = 10
            
            while len(comments_data) < max_count and scroll_count < max_scroll:
                comment_selectors = await self.playwright_page.query_selector_all('article[data-testid="tweet"]')
                
                for idx, comment_selector in enumerate(comment_selectors):
                    if idx == 0:
                        continue
                        
                    if len(comments_data) >= max_count:
                        break
                    
                    try:
                        comment_data = await self._parse_tweet(comment_selector)
                        if comment_data:
                            comments_data.append(comment_data)
                    except Exception as e:
                        self.logger.warning(f"[XTwitterClient.get_post_comments] Failed to parse comment: {e}")
                
                if len(comments_data) < max_count:
                    await self.playwright_page.evaluate("window.scrollBy(0, 1500)")
                    await asyncio.sleep(2)
                    scroll_count += 1
            
            self.logger.info(f"[XTwitterClient.get_post_comments] Found {len(comments_data)} comments")
            return comments_data
            
        except Exception as e:
            self.logger.error(f"[XTwitterClient.get_post_comments] Failed: {e}")
            return []

    async def post_comment(self, post_url: str, content: str) -> bool:
        self.logger.info(f"[XTwitterClient.post_comment] Posting comment to: {post_url}")
        
        try:
            await self.playwright_page.goto(post_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(5)
            
            page_title = await self.playwright_page.title()
            self.logger.info(f"[XTwitterClient.post_comment] Page title: {page_title}")
            
            await self.playwright_page.screenshot(path='/tmp/comment_page.png')
            self.logger.info(f"[XTwitterClient.post_comment] Screenshot saved")
            
            reply_button = None
            selectors = ['div[data-testid="reply"]', 'button[data-testid="reply"]', '[data-testid="reply"]']
            for selector in selectors:
                try:
                    reply_button = await self.playwright_page.wait_for_selector(selector, timeout=5000)
                    if reply_button:
                        self.logger.info(f"[XTwitterClient.post_comment] Found reply button with selector: {selector}")
                        break
                except:
                    self.logger.info(f"[XTwitterClient.post_comment] Selector not found: {selector}")
                    continue
            
            if not reply_button:
                all_buttons = await self.playwright_page.query_selector_all('button, div')
                self.logger.info(f"[XTwitterClient.post_comment] Total elements found: {len(all_buttons)}")
                
                interesting_elements = []
                for i, elem in enumerate(all_buttons[:50]):
                    try:
                        testid = await elem.get_attribute('data-testid')
                        if testid:
                            interesting_elements.append(f"[{i}] data-testid={testid}")
                        text = await elem.inner_text()
                        if 'reply' in text.lower() or '回复' in text:
                            interesting_elements.append(f"[{i}] text={text[:50]}")
                    except:
                        pass
                
                self.logger.info(f"[XTwitterClient.post_comment] Interesting elements: {interesting_elements}")
                return False
            
            await reply_button.click()
            await asyncio.sleep(2)
            
            textarea = None
            textarea_selectors = [
                'textarea[data-testid="tweetTextarea_0"]',
                'textarea[data-testid="tweetTextarea"]',
                '[data-testid="tweetTextarea_0"]',
                '[data-testid="tweetTextarea"]',
                'textarea[placeholder*="Reply"]',
                'textarea[placeholder*="回复"]',
            ]
            for selector in textarea_selectors:
                try:
                    textarea = await self.playwright_page.wait_for_selector(selector, timeout=5000)
                    if textarea:
                        self.logger.info(f"[XTwitterClient.post_comment] Found textarea with selector: {selector}")
                        break
                except:
                    continue
            
            if not textarea:
                self.logger.warning("[XTwitterClient.post_comment] Textarea not found")
                return False
            
            await textarea.fill(content)
            await asyncio.sleep(2)
            
            send_button = None
            send_selectors = [
                'div[data-testid="tweetButton"]',
                'button[data-testid="tweetButton"]',
                '[data-testid="tweetButton"]',
                'div[data-testid="replyButton"]',
                'button[data-testid="replyButton"]',
            ]
            for selector in send_selectors:
                try:
                    send_button = await self.playwright_page.wait_for_selector(selector, timeout=5000)
                    if send_button:
                        self.logger.info(f"[XTwitterClient.post_comment] Found send button with selector: {selector}")
                        break
                except:
                    continue
            
            if not send_button:
                self.logger.warning("[XTwitterClient.post_comment] Send button not found")
                return False
            
            await send_button.click()
            await asyncio.sleep(3)
            
            self.logger.info("[XTwitterClient.post_comment] Comment posted successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"[XTwitterClient.post_comment] Failed: {e}")
            return False

    async def get_notifications(self, max_count: int = 50) -> List[Dict]:
        self.logger.info("[XTwitterClient.get_notifications] Fetching notifications")
        
        try:
            await self.playwright_page.goto("https://x.com/notifications", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
            
            notifications_data = []
            scroll_count = 0
            max_scroll = 5
            
            while len(notifications_data) < max_count and scroll_count < max_scroll:
                notification_selectors = await self.playwright_page.query_selector_all('article[data-testid="tweet"]')
                
                for notification_selector in notification_selectors:
                    if len(notifications_data) >= max_count:
                        break
                    
                    try:
                        notification_data = await self._parse_tweet(notification_selector)
                        if notification_data:
                            notifications_data.append(notification_data)
                    except Exception as e:
                        self.logger.warning(f"[XTwitterClient.get_notifications] Failed to parse notification: {e}")
                
                if len(notifications_data) < max_count:
                    await self.playwright_page.evaluate("window.scrollBy(0, 1500)")
                    await asyncio.sleep(2)
                    scroll_count += 1
            
            self.logger.info(f"[XTwitterClient.get_notifications] Found {len(notifications_data)} notifications")
            return notifications_data
            
        except Exception as e:
            self.logger.error(f"[XTwitterClient.get_notifications] Failed: {e}")
            return []

    async def reply_to_comment(self, comment_url: str, content: str) -> bool:
        self.logger.info(f"[XTwitterClient.reply_to_comment] Replying to comment: {comment_url}")
        
        return await self.post_comment(comment_url, content)


    async def get_notifications(self, max_count: int = 50) -> List[Dict]:
        self.logger.info("[XTwitterClient.get_notifications] Fetching notifications")
        
        try:
            await self.playwright_page.goto("https://x.com/notifications", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
            
            notifications_data = []
            scroll_count = 0
            max_scroll = 5
            
            while len(notifications_data) < max_count and scroll_count < max_scroll:
                notification_selectors = await self.playwright_page.query_selector_all('article[data-testid="tweet"]')
                
                for notification_selector in notification_selectors:
                    if len(notifications_data) >= max_count:
                        break
                    
                    try:
                        notification_data = await self._parse_tweet(notification_selector)
                        if notification_data:
                            notifications_data.append(notification_data)
                    except Exception as e:
                        self.logger.warning(f"[XTwitterClient.get_notifications] Failed to parse notification: {e}")
                
                if len(notifications_data) < max_count:
                    await self.playwright_page.evaluate("window.scrollBy(0, 1500)")
                    await asyncio.sleep(2)
                    scroll_count += 1
            
            self.logger.info(f"[XTwitterClient.get_notifications] Found {len(notifications_data)} notifications")
            return notifications_data
            
        except Exception as e:
            self.logger.error(f"[XTwitterClient.get_notifications] Failed: {e}")
            return []
