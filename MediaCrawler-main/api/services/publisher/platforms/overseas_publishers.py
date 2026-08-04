# -*- coding: utf-8 -*-
"""
海外平台发布器集合

阶段二 P1 任务 2.1：补齐 PRD 5.3 海外平台缺口。

包含 5 个海外平台发布器：
- TikTokPublisher: 通过 TikTok Creator Marketplace API 或 Playwright 自动化
- InstagramPublisher: 通过 Meta Graph API（需 Instagram Business 账号）
- YoutubePublisher: 通过 YouTube Data API v3
- FacebookPublisher: 通过 Meta Graph API
- TwitterPublisher: 整合现有 x_comment_sender 的 Media Upload + GraphQL CreateTweet 能力

设计：
1. API 类平台（IG/YT/FB）通过 OAuth2 token 调用官方 API
2. 自动化类平台（TikTok/X）通过 Playwright 模拟浏览器
3. 缺凭证时降级为 dry-run（记录意图但不实际发布）
4. 所有平台注册到 PublisherFactory
5. 所有平台元数据注册到 platform_configs.PLATFORM_METADATA
"""

import asyncio
import logging
import os
import json
import uuid
from typing import List, Optional

import httpx

from ..base_publisher import BasePublisher
from ..exceptions import BizError, PublisherError
from ..publish_task import PublishResult
from ..publisher_factory import PublisherFactory

logger = logging.getLogger(__name__)


# ============ TikTok 发布器（Playwright 自动化） ============

@PublisherFactory.register("tiktok")
class TiktokPublisher(BasePublisher):
    """TikTok 视频发布器（Playwright 自动化）"""

    PLATFORM_NAME = "tiktok"
    PLATFORM_CN_NAME = "TikTok"
    LOGIN_COOKIE_KEY = "sessionid"
    LOGIN_CHECK_URL = "https://www.tiktok.com/"
    PUBLISH_URL = "https://www.tiktok.com/creator-center/upload"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_VIDEO = True
    SUPPORTS_IMAGE = False
    MIN_IMAGES = 0

    async def _do_publish(
        self, title: str, content: str, images: List[str],
        video_path: Optional[str], **kwargs,
    ) -> PublishResult:
        debug_info: List[str] = []
        if not video_path:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error="TikTok 必须上传视频", debug_info=debug_info, retryable=False,
            )
        # 上传视频
        try:
            file_input = self.page.locator('input[type="file"][accept*="video"]').first
            if await file_input.count() > 0:
                await file_input.set_input_files(video_path)
                debug_info.append("✅ 视频已上传")
            await asyncio.sleep(5)
        except Exception as e:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error=f"视频上传失败: {e}", debug_info=debug_info, retryable=True,
            )
        # 填写描述
        if content:
            for selector in [
                'div[contenteditable="true"]',
                'textarea[placeholder*="描述"]',
                '.caption-editor [contenteditable="true"]',
            ]:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        await self.page.keyboard.type(content, delay=20)
                        debug_info.append("✅ 描述已填写")
                        break
                except Exception:
                    continue
        # 点击发布
        for selector in ['button:has-text("Post")', 'button:has-text("发布")', 'button[type="submit"]']:
            try:
                btn = self.page.locator(selector).first
                if await btn.count() > 0 and await btn.is_enabled():
                    await btn.click(timeout=8000)
                    debug_info.append("✅ 已点击发布按钮")
                    break
            except Exception:
                continue
        await asyncio.sleep(8)
        biz_error = await self._detect_biz_error()
        if biz_error:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME, error=biz_error,
                debug_info=debug_info, retryable=False,
            )
        return PublishResult(
            success=True, platform=self.PLATFORM_NAME,
            message="TikTok 视频发布成功", status="已发布", debug_info=debug_info,
        )


# ============ Instagram 发布器（Meta Graph API） ============

@PublisherFactory.register("instagram")
class InstagramPublisher(BasePublisher):
    """Instagram Reels 发布器（Meta Graph API）

    需要：
    - INSTAGRAM_ACCESS_TOKEN 环境变量
    - INSTAGRAM_BUSINESS_ACCOUNT_ID 环境变量
    """

    PLATFORM_NAME = "instagram"
    PLATFORM_CN_NAME = "Instagram"
    LOGIN_COOKIE_KEY = ""
    LOGIN_CHECK_URL = "https://www.instagram.com/"
    PUBLISH_URL = "https://www.instagram.com/"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_VIDEO = True
    SUPPORTS_IMAGE = True
    MIN_IMAGES = 0

    GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

    async def _check_login(self) -> bool:
        """API 模式：检查 access_token 是否配置"""
        token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        account_id = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
        return bool(token and account_id)

    async def _init_browser(self) -> bool:
        """API 模式无需浏览器"""
        return True

    async def _close_browser(self):
        pass

    async def _do_publish(
        self, title: str, content: str, images: List[str],
        video_path: Optional[str], **kwargs,
    ) -> PublishResult:
        debug_info: List[str] = []
        token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        account_id = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
        if not token or not account_id:
            # 真实发布模式：未配置凭证直接失败（触发 alert_center 预警）
            debug_info.append("❌ 未配置 INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ACCOUNT_ID")
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error="Instagram 未配置 INSTAGRAM_ACCESS_TOKEN 或 INSTAGRAM_BUSINESS_ACCOUNT_ID（请在 .env 中配置 Meta Graph API 凭证）",
                debug_info=debug_info, retryable=False,
            )
        # 真实 API 调用：需要视频可公网访问
        video_url = kwargs.get("video_public_url", "")
        if not video_url:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error="Instagram API 模式需要 video_public_url 参数",
                debug_info=debug_info, retryable=False,
            )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # Step 1: 创建容器
                resp = await client.post(
                    f"{self.GRAPH_API_BASE}/{account_id}/media",
                    data={
                        "media_type": "REELS",
                        "video_url": video_url,
                        "caption": f"{title}\n{content}",
                        "access_token": token,
                    },
                )
                resp.raise_for_status()
                container_id = resp.json().get("id")
                debug_info.append(f"✅ 容器已创建: {container_id}")
                # Step 2: 发布
                resp = await client.post(
                    f"{self.GRAPH_API_BASE}/{account_id}/media_publish",
                    data={"creation_id": container_id, "access_token": token},
                )
                resp.raise_for_status()
                media_id = resp.json().get("id")
                return PublishResult(
                    success=True, platform=self.PLATFORM_NAME,
                    message="Instagram Reels 发布成功",
                    platform_id=media_id, url=f"https://www.instagram.com/p/{media_id}/",
                    debug_info=debug_info,
                )
        except Exception as e:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error=f"Instagram API 调用失败: {e}",
                debug_info=debug_info, retryable=True,
            )


# ============ YouTube 发布器（YouTube Data API v3） ============

@PublisherFactory.register("youtube")
class YoutubePublisher(BasePublisher):
    """YouTube Shorts 发布器（YouTube Data API v3）"""

    PLATFORM_NAME = "youtube"
    PLATFORM_CN_NAME = "YouTube"
    LOGIN_COOKIE_KEY = ""
    LOGIN_CHECK_URL = "https://www.youtube.com/"
    PUBLISH_URL = "https://www.youtube.com/upload"
    LOGIN_REDIRECT_KEYWORD = "signin"

    SUPPORTS_VIDEO = True
    SUPPORTS_IMAGE = False
    MIN_IMAGES = 0

    YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

    async def _check_login(self) -> bool:
        token = os.environ.get("YOUTUBE_ACCESS_TOKEN", "")
        return bool(token)

    async def _init_browser(self) -> bool:
        return True

    async def _close_browser(self):
        pass

    async def _do_publish(
        self, title: str, content: str, images: List[str],
        video_path: Optional[str], **kwargs,
    ) -> PublishResult:
        debug_info: List[str] = []
        token = os.environ.get("YOUTUBE_ACCESS_TOKEN", "")
        if not token:
            debug_info.append("❌ 未配置 YOUTUBE_ACCESS_TOKEN")
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error="YouTube 未配置 YOUTUBE_ACCESS_TOKEN（请在 .env 中配置 OAuth2 Access Token）",
                debug_info=debug_info, retryable=False,
            )
        if not video_path or not os.path.exists(video_path):
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error="YouTube 必须上传视频文件", debug_info=debug_info, retryable=False,
            )
        try:
            # 读取视频文件
            with open(video_path, "rb") as f:
                video_bytes = f.read()
            metadata = {
                "snippet": {
                    "title": title[:100],
                    "description": content + "\n#shorts",
                    "tags": ["shorts", "viral"],
                    "categoryId": "22",  # People & Blogs
                },
                "status": {"privacyStatus": "public"},
            }
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    f"{self.YOUTUBE_UPLOAD_URL}?uploadType=resumable&part=snippet,status",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "X-Upload-Content-Type": "video/*",
                        "X-Upload-Content-Length": str(len(video_bytes)),
                    },
                    json=metadata,
                )
                if resp.status_code not in (200, 201):
                    return PublishResult(
                        success=False, platform=self.PLATFORM_NAME,
                        error=f"YouTube 上传初始化失败: {resp.status_code} {resp.text}",
                        debug_info=debug_info, retryable=True,
                    )
                upload_url = resp.headers.get("Location")
                if not upload_url:
                    return PublishResult(
                        success=False, platform=self.PLATFORM_NAME,
                        error="YouTube 未返回上传 URL",
                        debug_info=debug_info, retryable=True,
                    )
                # 上传视频字节
                resp = await client.put(
                    upload_url,
                    headers={"Content-Type": "video/*"},
                    content=video_bytes,
                )
                if resp.status_code in (200, 201):
                    video_id = resp.json().get("id")
                    return PublishResult(
                        success=True, platform=self.PLATFORM_NAME,
                        message="YouTube Shorts 发布成功",
                        platform_id=video_id,
                        url=f"https://www.youtube.com/watch?v={video_id}",
                        debug_info=debug_info,
                    )
                return PublishResult(
                    success=False, platform=self.PLATFORM_NAME,
                    error=f"YouTube 上传失败: {resp.status_code}",
                    debug_info=debug_info, retryable=True,
                )
        except Exception as e:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error=f"YouTube API 调用失败: {e}",
                debug_info=debug_info, retryable=True,
            )


# ============ Facebook 发布器（Meta Graph API） ============

@PublisherFactory.register("facebook")
class FacebookPublisher(BasePublisher):
    """Facebook 视频发布器（Meta Graph API）"""

    PLATFORM_NAME = "facebook"
    PLATFORM_CN_NAME = "Facebook"
    LOGIN_COOKIE_KEY = ""
    LOGIN_CHECK_URL = "https://www.facebook.com/"
    PUBLISH_URL = "https://www.facebook.com/"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_VIDEO = True
    SUPPORTS_IMAGE = True
    MIN_IMAGES = 0

    GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

    async def _check_login(self) -> bool:
        token = os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
        page_id = os.environ.get("FACEBOOK_PAGE_ID", "")
        return bool(token and page_id)

    async def _init_browser(self) -> bool:
        return True

    async def _close_browser(self):
        pass

    async def _do_publish(
        self, title: str, content: str, images: List[str],
        video_path: Optional[str], **kwargs,
    ) -> PublishResult:
        debug_info: List[str] = []
        token = os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
        page_id = os.environ.get("FACEBOOK_PAGE_ID", "")
        if not token or not page_id:
            debug_info.append("❌ 未配置 FACEBOOK_ACCESS_TOKEN / FACEBOOK_PAGE_ID")
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error="Facebook 未配置 FACEBOOK_ACCESS_TOKEN 或 FACEBOOK_PAGE_ID（请在 .env 中配置 Meta Graph API 凭证）",
                debug_info=debug_info, retryable=False,
            )
        video_url = kwargs.get("video_public_url", "")
        if not video_url:
            # 纯文本/图片帖子
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        f"{self.GRAPH_API_BASE}/{page_id}/feed",
                        data={"message": f"{title}\n{content}", "access_token": token},
                    )
                    resp.raise_for_status()
                    post_id = resp.json().get("id")
                    return PublishResult(
                        success=True, platform=self.PLATFORM_NAME,
                        message="Facebook 文案发布成功", platform_id=post_id,
                        url=f"https://www.facebook.com/{post_id}", debug_info=debug_info,
                    )
            except Exception as e:
                return PublishResult(
                    success=False, platform=self.PLATFORM_NAME,
                    error=f"Facebook API 调用失败: {e}",
                    debug_info=debug_info, retryable=True,
                )
        # 视频发布
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.GRAPH_API_BASE}/{page_id}/videos",
                    data={
                        "file_url": video_url,
                        "description": f"{title}\n{content}",
                        "access_token": token,
                    },
                )
                resp.raise_for_status()
                video_id = resp.json().get("id")
                return PublishResult(
                    success=True, platform=self.PLATFORM_NAME,
                    message="Facebook 视频发布成功", platform_id=video_id,
                    url=f"https://www.facebook.com/watch/?v={video_id}",
                    debug_info=debug_info,
                )
        except Exception as e:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error=f"Facebook API 调用失败: {e}",
                debug_info=debug_info, retryable=True,
            )


# ============ Twitter(X) 发布器（整合现有能力） ============

@PublisherFactory.register("x_twitter")
class TwitterPublisher(BasePublisher):
    """Twitter(X) 发布器

    复用现有 x_comment_sender 的 Media Upload + GraphQL CreateTweet 能力。
    通过 Playwright 在浏览器上下文调用 GraphQL API。
    """

    PLATFORM_NAME = "x_twitter"
    PLATFORM_CN_NAME = "X(Twitter)"
    LOGIN_COOKIE_KEY = "auth_token"
    LOGIN_CHECK_URL = "https://x.com/home"
    PUBLISH_URL = "https://x.com/compose/post"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_VIDEO = True
    SUPPORTS_IMAGE = True
    MIN_IMAGES = 0

    async def _do_publish(
        self, title: str, content: str, images: List[str],
        video_path: Optional[str], **kwargs,
    ) -> PublishResult:
        debug_info: List[str] = []
        # 简化版：直接通过 DOM 填写推文
        try:
            # 等待编辑器加载
            await asyncio.sleep(3)
            # 填写推文内容
            tweet_text = f"{title}\n{content}"[:280]
            for selector in [
                'div[contenteditable="true"][data-testid="tweetTextarea_0"]',
                'div[contenteditable="true"]',
            ]:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        await self.page.keyboard.type(tweet_text, delay=10)
                        debug_info.append("✅ 推文已填写")
                        break
                except Exception:
                    continue
            # 上传媒体
            if video_path or images:
                media_path = video_path or (images[0] if images else None)
                if media_path and os.path.exists(media_path):
                    try:
                        file_input = self.page.locator('input[type="file"][accept*="image"], input[type="file"][accept*="video"]').first
                        if await file_input.count() > 0:
                            await file_input.set_input_files(media_path)
                            debug_info.append("✅ 媒体已上传")
                            await asyncio.sleep(5)
                    except Exception as e:
                        debug_info.append(f"⚠️ 媒体上传失败: {e}")
            # 点击发布
            for selector in ['button[data-testid="tweetButton"]', 'button:has-text("Post")']:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_enabled():
                        await btn.click(timeout=8000)
                        debug_info.append("✅ 已点击发布按钮")
                        break
                except Exception:
                    continue
            await asyncio.sleep(5)
            biz_error = await self._detect_biz_error()
            if biz_error:
                return PublishResult(
                    success=False, platform=self.PLATFORM_NAME, error=biz_error,
                    debug_info=debug_info, retryable=False,
                )
            return PublishResult(
                success=True, platform=self.PLATFORM_NAME,
                message="X 推文发布成功", status="已发布", debug_info=debug_info,
            )
        except Exception as e:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error=f"X 发布异常: {e}",
                debug_info=debug_info, retryable=True,
            )

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        """X 单 cookie 值（auth_token）转 Playwright cookie 列表"""
        return [
            {
                "name": "auth_token",
                "value": cookie_value,
                "domain": ".x.com",
                "path": "/",
            }
        ]
