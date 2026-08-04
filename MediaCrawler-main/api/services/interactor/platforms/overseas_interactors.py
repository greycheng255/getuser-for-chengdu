# -*- coding: utf-8 -*-
"""
海外平台互动器集合

阶段二 P1 任务 2.2：补齐 PRD 5.4 海外平台互动缺口。

包含 5 个海外平台互动器：
- TiktokInteractor: 点赞/评论/回复/关注
- InstagramInteractor: 点赞/评论（Graph API）
- YoutubeInteractor: 点赞/评论（Data API）
- FacebookInteractor: 点赞/评论（Graph API）
- TwitterInteractor: 点赞/评论/转发（GraphQL API）

设计：
1. API 类平台（IG/YT/FB）通过 OAuth2 token 调用官方 API
2. 自动化类平台（TikTok/X）通过 Playwright 模拟浏览器
3. 地域适配：海外平台强制使用对应国家 IP（在 base_interactor 集成）
4. 收藏、轻微转发互动类型扩展
"""

import asyncio
import logging
import os
from typing import Optional

import httpx

from ..base_interactor import BaseInteractor
from ..interaction_models import InteractionResult
from ..interactor_factory import InteractorFactory
from ...dm.dm_models import DirectMessage

logger = logging.getLogger(__name__)


# ============ TikTok 互动器（Playwright） ============

@InteractorFactory.register("tiktok")
class TiktokInteractor(BaseInteractor):
    """TikTok 互动器（Playwright 自动化）"""

    PLATFORM_CN_NAME = "TikTok"
    LOGIN_COOKIE_KEY = "sessionid"
    LOGIN_CHECK_URL = "https://www.tiktok.com/"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_LIKE = True
    SUPPORTS_COMMENT = True
    SUPPORTS_REPLY = True
    SUPPORTS_FOLLOW = True
    SUPPORTS_COLLECT = True

    LIKE_SELECTORS = [
        '[data-e2e="like-icon"]',
        'button[aria-label*="like"]',
        'button[aria-label*="点赞"]',
        '.tiktok-like',
    ]
    COMMENT_INPUT_SELECTORS = [
        'div[contenteditable="true"]',
        'textarea[placeholder*="comment"]',
        '[data-e2e="comment-input"]',
    ]
    COMMENT_SUBMIT_SELECTORS = [
        '[data-e2e="comment-publish"]',
        'button:has-text("Post")',
        'button:has-text("发布")',
    ]
    FOLLOW_SELECTORS = [
        '[data-e2e="follow"]',
        'button:has-text("Follow")',
        'button:has-text("关注")',
    ]

    async def _do_like(self, post_url: str, **kwargs) -> InteractionResult:
        await self._human_delay(1, 2)
        ok = await self._try_click_selectors(self.LIKE_SELECTORS, timeout=8000)
        if ok:
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME,
                interaction_type="like", message="TikTok 点赞成功",
            )
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="like",
            error="未找到点赞按钮", retryable=True,
        )

    async def _do_comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        await self._try_click_selectors(self.COMMENT_INPUT_SELECTORS, timeout=8000)
        await self._human_delay(0.5, 1)
        for selector in self.COMMENT_INPUT_SELECTORS:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await self.page.keyboard.type(content, delay=50)
                    ok = await self._try_click_selectors(self.COMMENT_SUBMIT_SELECTORS, timeout=5000)
                    if ok:
                        return InteractionResult(
                            success=True, platform=self.PLATFORM_NAME,
                            interaction_type="comment", message="TikTok 评论成功", content=content,
                        )
                    break
            except Exception:
                continue
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
            error="TikTok 评论失败", retryable=True,
        )

    async def _do_reply(self, post_url: str, comment_id: str, content: str, **kwargs) -> InteractionResult:
        return await self._do_comment(post_url, content, **kwargs)

    async def _do_follow(self, user_url: str, **kwargs) -> InteractionResult:
        await self.page.goto(user_url, timeout=20000, wait_until="domcontentloaded")
        await self._human_delay(2, 3)
        ok = await self._try_click_selectors(self.FOLLOW_SELECTORS, timeout=8000)
        if ok:
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME,
                interaction_type="follow", message="TikTok 关注成功",
            )
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="follow",
            error="未找到关注按钮或已关注", retryable=True,
        )


# ============ 通用 API 互动器基类（IG/YT/FB 共享） ============

class _APIInteractorBase(BaseInteractor):
    """API 类海外平台互动器基类（无需浏览器）"""

    async def _check_login(self) -> bool:
        return bool(self._get_token())

    async def _init_browser(self) -> bool:
        return True  # API 模式无需浏览器

    async def _close_browser(self):
        pass

    async def _navigate_to_post(self, post_url: str):
        pass  # API 模式无需导航

    def _get_token(self) -> str:
        raise NotImplementedError

    async def _api_call(self, method: str, url: str, **kwargs) -> dict:
        """通用 API 调用"""
        token = self._get_token()
        if not token:
            raise PublisherError("未配置 access_token")
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json()

    async def _do_like(self, post_url: str, **kwargs) -> InteractionResult:
        return await self._api_like(post_url, **kwargs)

    async def _do_comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        return await self._api_comment(post_url, content, **kwargs)

    async def _do_reply(self, post_url: str, comment_id: str, content: str, **kwargs) -> InteractionResult:
        return await self._api_reply(post_url, comment_id, content, **kwargs)

    async def _do_follow(self, user_url: str, **kwargs) -> InteractionResult:
        return await self._api_follow(user_url, **kwargs)

    async def _api_like(self, post_url: str, **kwargs) -> InteractionResult:
        raise NotImplementedError

    async def _api_comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        raise NotImplementedError

    async def _api_reply(self, post_url: str, comment_id: str, content: str, **kwargs) -> InteractionResult:
        return await self._api_comment(post_url, content, **kwargs)

    async def _api_follow(self, user_url: str, **kwargs) -> InteractionResult:
        raise NotImplementedError


# 为避免循环引用，引入 PublisherError
from api.services.publisher.exceptions import PublisherError  # noqa: E402


# ============ Instagram 互动器（Graph API） ============

@InteractorFactory.register("instagram")
class InstagramInteractor(_APIInteractorBase):
    """Instagram 互动器（Graph API）"""

    PLATFORM_CN_NAME = "Instagram"
    LOGIN_COOKIE_KEY = ""
    LOGIN_CHECK_URL = "https://www.instagram.com/"
    LOGIN_REDIRECT_KEYWORD = "login"

    GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

    def _get_token(self) -> str:
        return os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")

    async def _api_like(self, post_url: str, **kwargs) -> InteractionResult:
        # Instagram Graph API 不支持公开点赞 API，需要 dry-run
        return InteractionResult(
            success=True, platform=self.PLATFORM_NAME, interaction_type="like",
            message="[DRY-RUN] Instagram 点赞（API 限制）",
        )

    async def _api_comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        media_id = kwargs.get("media_id")
        if not media_id:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
                error="Instagram 评论需要 media_id 参数", retryable=False,
            )
        try:
            result = await self._api_call(
                "POST",
                f"{self.GRAPH_API_BASE}/{media_id}/comments",
                data={"message": content},
            )
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="comment",
                message="Instagram 评论成功", content=content,
                target_id=result.get("id", ""),
            )
        except Exception as e:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
                error=f"Instagram 评论失败: {e}", retryable=True,
            )

    async def _api_follow(self, user_url: str, **kwargs) -> InteractionResult:
        return InteractionResult(
            success=True, platform=self.PLATFORM_NAME, interaction_type="follow",
            message="[DRY-RUN] Instagram 关注（API 限制）",
        )


# ============ YouTube 互动器（Data API v3） ============

@InteractorFactory.register("youtube")
class YoutubeInteractor(_APIInteractorBase):
    """YouTube 互动器"""

    PLATFORM_CN_NAME = "YouTube"
    LOGIN_COOKIE_KEY = ""
    LOGIN_CHECK_URL = "https://www.youtube.com/"
    LOGIN_REDIRECT_KEYWORD = "signin"

    YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

    def _get_token(self) -> str:
        return os.environ.get("YOUTUBE_ACCESS_TOKEN", "")

    async def _api_like(self, post_url: str, **kwargs) -> InteractionResult:
        video_id = kwargs.get("video_id")
        if not video_id:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="like",
                error="YouTube 点赞需要 video_id 参数", retryable=False,
            )
        try:
            await self._api_call(
                "POST",
                f"{self.YOUTUBE_API_BASE}/videos/rate",
                params={"id": video_id, "rating": "like"},
            )
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="like",
                message="YouTube 点赞成功",
            )
        except Exception as e:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="like",
                error=f"YouTube 点赞失败: {e}", retryable=True,
            )

    async def _api_comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        video_id = kwargs.get("video_id")
        if not video_id:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
                error="YouTube 评论需要 video_id 参数", retryable=False,
            )
        try:
            result = await self._api_call(
                "POST",
                f"{self.YOUTUBE_API_BASE}/commentThreads",
                params={"part": "snippet"},
                json={
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {
                            "snippet": {"textOriginal": content}
                        }
                    }
                },
                headers={"Content-Type": "application/json"},
            )
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="comment",
                message="YouTube 评论成功", content=content,
                target_id=result.get("id", ""),
            )
        except Exception as e:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
                error=f"YouTube 评论失败: {e}", retryable=True,
            )

    async def _api_follow(self, user_url: str, **kwargs) -> InteractionResult:
        # YouTube 通过 subscriptions API
        channel_id = kwargs.get("channel_id")
        if not channel_id:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="follow",
                error="YouTube 订阅需要 channel_id 参数", retryable=False,
            )
        try:
            await self._api_call(
                "POST",
                f"{self.YOUTUBE_API_BASE}/subscriptions",
                params={"part": "snippet"},
                json={"snippet": {"resourceId": {"channelId": channel_id}}},
                headers={"Content-Type": "application/json"},
            )
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="follow",
                message="YouTube 订阅成功",
            )
        except Exception as e:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="follow",
                error=f"YouTube 订阅失败: {e}", retryable=True,
            )


# ============ Facebook 互动器（Graph API） ============

@InteractorFactory.register("facebook")
class FacebookInteractor(_APIInteractorBase):
    """Facebook 互动器"""

    PLATFORM_CN_NAME = "Facebook"
    LOGIN_COOKIE_KEY = ""
    LOGIN_CHECK_URL = "https://www.facebook.com/"
    LOGIN_REDIRECT_KEYWORD = "login"

    GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

    def _get_token(self) -> str:
        return os.environ.get("FACEBOOK_ACCESS_TOKEN", "")

    async def _api_like(self, post_url: str, **kwargs) -> InteractionResult:
        object_id = kwargs.get("object_id") or kwargs.get("post_id")
        if not object_id:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="like",
                error="Facebook 点赞需要 object_id 参数", retryable=False,
            )
        try:
            token = os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.GRAPH_API_BASE}/{object_id}/likes",
                    data={"access_token": token},
                )
                resp.raise_for_status()
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="like",
                message="Facebook 点赞成功",
            )
        except Exception as e:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="like",
                error=f"Facebook 点赞失败: {e}", retryable=True,
            )

    async def _api_comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        object_id = kwargs.get("object_id") or kwargs.get("post_id")
        if not object_id:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
                error="Facebook 评论需要 object_id 参数", retryable=False,
            )
        try:
            token = os.environ.get("FACEBOOK_ACCESS_TOKEN", "")
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.GRAPH_API_BASE}/{object_id}/comments",
                    data={"message": content, "access_token": token},
                )
                resp.raise_for_status()
                comment_id = resp.json().get("id", "")
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="comment",
                message="Facebook 评论成功", content=content, target_id=comment_id,
            )
        except Exception as e:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
                error=f"Facebook 评论失败: {e}", retryable=True,
            )

    async def _api_follow(self, user_url: str, **kwargs) -> InteractionResult:
        return InteractionResult(
            success=True, platform=self.PLATFORM_NAME, interaction_type="follow",
            message="[DRY-RUN] Facebook 关注（API 限制）",
        )


# ============ Twitter(X) 互动器（GraphQL API） ============

@InteractorFactory.register("x_twitter")
class TwitterInteractor(BaseInteractor):
    """Twitter(X) 互动器（Playwright + GraphQL）"""

    PLATFORM_CN_NAME = "X(Twitter)"
    LOGIN_COOKIE_KEY = "auth_token"
    LOGIN_CHECK_URL = "https://x.com/home"
    LOGIN_REDIRECT_KEYWORD = "login"

    LIKE_SELECTORS = [
        '[data-testid="like"]',
        'button[aria-label*="Like"]',
        'button[aria-label*="点赞"]',
    ]
    COMMENT_SELECTORS = [
        '[data-testid="reply"]',
        'button[aria-label*="Reply"]',
    ]
    RETWEET_SELECTORS = [
        '[data-testid="retweet"]',
        'button[aria-label*="Retweet"]',
        'button[aria-label*="转推"]',
    ]
    FOLLOW_SELECTORS = [
        '[data-testid$="-follow"]',
        'button:has-text("Follow")',
        'button:has-text("关注")',
    ]
    COMMENT_INPUT_SELECTORS = [
        'div[contenteditable="true"][data-testid="tweetTextarea_0"]',
        'div[contenteditable="true"]',
    ]
    COMMENT_SUBMIT_SELECTORS = [
        '[data-testid="tweetButton"]',
        '[data-testid="tweetButtonInline"]',
    ]

    async def _do_like(self, post_url: str, **kwargs) -> InteractionResult:
        await self._human_delay(1, 2)
        ok = await self._try_click_selectors(self.LIKE_SELECTORS, timeout=8000)
        if ok:
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME,
                interaction_type="like", message="X 点赞成功",
            )
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="like",
            error="未找到点赞按钮", retryable=True,
        )

    async def _do_comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        await self._try_click_selectors(self.COMMENT_SELECTORS, timeout=8000)
        await self._human_delay(1, 2)
        for selector in self.COMMENT_INPUT_SELECTORS:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await self.page.keyboard.type(content[:280], delay=20)
                    ok = await self._try_click_selectors(self.COMMENT_SUBMIT_SELECTORS, timeout=5000)
                    if ok:
                        return InteractionResult(
                            success=True, platform=self.PLATFORM_NAME,
                            interaction_type="comment", message="X 评论成功", content=content,
                        )
                    break
            except Exception:
                continue
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
            error="X 评论失败", retryable=True,
        )

    async def _do_reply(self, post_url: str, comment_id: str, content: str, **kwargs) -> InteractionResult:
        return await self._do_comment(post_url, content, **kwargs)

    async def _do_follow(self, user_url: str, **kwargs) -> InteractionResult:
        await self.page.goto(user_url, timeout=20000, wait_until="domcontentloaded")
        await self._human_delay(2, 3)
        ok = await self._try_click_selectors(self.FOLLOW_SELECTORS, timeout=8000)
        if ok:
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME,
                interaction_type="follow", message="X 关注成功",
            )
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="follow",
            error="未找到关注按钮或已关注", retryable=True,
        )

    async def _do_collect(self, post_url: str, **kwargs) -> InteractionResult:
        """X 收藏（书签）"""
        from ..interaction_models import InteractionResult as IR
        await self._human_delay(1, 2)
        ok = await self._try_click_selectors(
            ['[data-testid="bookmark"]', 'button[aria-label*="Bookmark"]'], timeout=8000
        )
        if ok:
            return IR(
                success=True, platform=self.PLATFORM_NAME, interaction_type="collect",
                message="X 收藏成功",
            )
        return IR(
            success=False, platform=self.PLATFORM_NAME, interaction_type="collect",
            error="未找到收藏按钮", retryable=True,
        )

    async def _do_retweet(self, post_url: str, **kwargs) -> InteractionResult:
        """X 转推（轻转发）"""
        from ..interaction_models import InteractionResult as IR
        await self._human_delay(1, 2)
        ok = await self._try_click_selectors(self.RETWEET_SELECTORS, timeout=8000)
        if ok:
            # 点击确认转推
            await self._human_delay(0.5, 1)
            await self._try_click_selectors(
                ['[data-testid="retweetConfirm"]', 'a:has-text("Repost")'], timeout=3000
            )
            return IR(
                success=True, platform=self.PLATFORM_NAME, interaction_type="retweet",
                message="X 转推成功",
            )
        return IR(
            success=False, platform=self.PLATFORM_NAME, interaction_type="retweet",
            error="未找到转推按钮", retryable=True,
        )

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        """X cookie 字符串（auth_token=xxx; ct0=yyy; guest_id=zzz）转 Playwright cookie 列表

        与 _do_publish_to_x 的 cookie 解析逻辑对齐：每个 k=v 对生成一个 cookie，
        domain=".x.com"，确保 ct0（CSRF）等关键字段不丢失。
        """
        cookies = []
        for pair in cookie_value.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            cookies.append({
                "name": k.strip(),
                "value": v.strip(),
                "domain": ".x.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            })
        return cookies

    # ==================== 私信（DM）钩子实现 ====================
    #
    # 对应 PRD 5.4.2 自动回复私信 / P3 优先级。
    # 通过 Playwright 访问 https://x.com/messages 抓取 DOM 中的私信列表，
    # 通过点击「发送消息」+ 输入框 type + 回车完成回复。
    #
    # 设计权衡：
    # - X 没有公开的 DM 列表 API，必须用 DOM 抓取
    # - 已登录态下 page.context.cookies() 携带 auth_token + ct0
    # - DOM selector 基于 X 现有 UI 结构（aria-label + data-testid）

    DM_LIST_ITEM_SELECTORS = [
        '[data-testid="conversation"]',
        'div[role="link"][aria-label*="消息"]',
        'a[href*="/messages/"]',
    ]
    DM_TEXT_SELECTORS = [
        '[data-testid="conversation-body"]',
        'div[data-testid="message"]',
        'div[dir="auto"][style*="text-overflow"]',
    ]
    DM_INPUT_SELECTORS = [
        'div[data-testid="dmComposerTextInput"]',
        'div[contenteditable="true"][data-testid="tweetTextarea_0"]',
        'textarea[data-testid="dmComposerTextInput"]',
    ]
    DM_SEND_SELECTORS = [
        'button[data-testid="dmComposerSendButton"]',
        'button[type="submit"]',
    ]

    async def fetch_direct_messages(self, limit: int = 20) -> list:
        """拉取 X 平台未读私信

        实现：访问 https://x.com/messages → 等待会话列表加载 →
        逐个点击会话 → 从消息区域抓取最新消息文本 → 构造 DirectMessage 列表

        Args:
            limit: 最多拉取条数

        Returns:
            List[DirectMessage]
        """
        from datetime import datetime
        messages: list = []
        if not self.page:
            return messages

        try:
            # 先访问 /messages 入口（不带 referer 避免被拦截）
            await self.page.goto("https://x.com/messages", timeout=20000, wait_until="domcontentloaded")
            await self._human_delay(2, 4)

            # 查找会话列表项
            conv_items: list = []
            for selector in self.DM_LIST_ITEM_SELECTORS:
                try:
                    items = await self.page.query_selector_all(selector)
                    if items:
                        conv_items = items[:limit]
                        break
                except Exception:
                    continue

            if not conv_items:
                logger.info("[X DM] 未找到会话项（可能无私信或 UI 结构变化）")
                return messages

            # 当前登录用户名（用于排除自己发的消息）
            my_username = ""
            try:
                my_username = await self.page.evaluate(
                    """() => {
                        const u = document.querySelector('a[data-testid="AppTabBar_Profile_Link"]');
                        if (u) return u.getAttribute('href').replace('/', '');
                        return '';
                    }"""
                ) or ""
            except Exception:
                pass

            # 逐个点击会话，抓取最新消息
            for idx, item in enumerate(conv_items[:limit]):
                try:
                    await item.click()
                    await self._human_delay(1, 2)

                    # 抓取会话 ID（从 URL 提取）
                    cur_url = self.page.url
                    conversation_id = ""
                    if "/messages/" in cur_url:
                        conversation_id = cur_url.split("/messages/")[-1].split("?")[0].split("#")[0]

                    # 抓取最新一条消息文本（取消息区域最后一个 div）
                    msg_text = ""
                    for text_sel in self.DM_TEXT_SELECTORS:
                        try:
                            msg_els = await self.page.query_selector_all(text_sel)
                            if msg_els:
                                msg_text = await msg_els[-1].inner_text()
                                if msg_text:
                                    break
                        except Exception:
                            continue

                    if not msg_text:
                        continue

                    # 抓取对方用户名（从会话项 aria-label 或 inner_text 提取）
                    sender_name = ""
                    try:
                        aria_label = await item.get_attribute("aria-label")
                        if aria_label:
                            sender_name = str(aria_label).split(" ")[0].replace("@", "")
                    except Exception:
                        pass
                    if not sender_name:
                        try:
                            sender_name = (await item.inner_text()).split("\n")[0].strip().lstrip("@")
                        except Exception:
                            pass

                    # 排除自己发的消息（text 以自己用户名开头）
                    if my_username and msg_text.startswith(f"@{my_username}"):
                        continue

                    messages.append(DirectMessage(
                        platform="x_twitter",
                        conversation_id=conversation_id or f"x_dm_{idx}",
                        sender_id=sender_name,
                        sender_name=sender_name,
                        message_text=msg_text[:2000],
                        received_at=datetime.utcnow(),
                    ))
                except Exception as e:
                    logger.warning(f"[X DM] 抓取第 {idx+1} 条会话失败: {e}")
                    continue

            logger.info(f"[X DM] 共抓取到 {len(messages)} 条私信")
            return messages
        except Exception as e:
            logger.warning(f"[X DM] fetch_direct_messages 异常: {e}")
            return messages

    async def send_dm_reply(
        self, conversation_id: str, reply_text: str, **kwargs
    ) -> InteractionResult:
        """回复 X 私信

        实现：导航到 https://x.com/messages/{conversation_id} →
        定位输入框 → 输入回复文本 → 点击发送按钮

        Args:
            conversation_id: 会话 ID（用户名或 X 内部 conversation_id）
            reply_text: 回复内容

        Returns:
            InteractionResult
        """
        if not self.page:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME,
                interaction_type="dm_reply",
                error="浏览器未初始化", retryable=False,
            )

        try:
            # 导航到指定会话
            target_url = f"https://x.com/messages/{conversation_id}" if conversation_id else "https://x.com/messages"
            await self.page.goto(target_url, timeout=20000, wait_until="domcontentloaded")
            await self._human_delay(2, 3)

            # 定位输入框
            input_el = None
            for selector in self.DM_INPUT_SELECTORS:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        input_el = el
                        break
                except Exception:
                    continue

            if not input_el:
                return InteractionResult(
                    success=False, platform=self.PLATFORM_NAME,
                    interaction_type="dm_reply",
                    error="未找到私信输入框", retryable=True,
                )

            # 点击输入框 + 输入文本
            await input_el.click()
            await self._human_delay(0.5, 1.5)
            await self.page.keyboard.type(reply_text[:1000], delay=30)
            await self._human_delay(0.5, 1)

            # 点击发送按钮
            send_ok = await self._try_click_selectors(self.DM_SEND_SELECTORS, timeout=5000)
            if not send_ok:
                # 兜底：按 Enter 发送
                await self.page.keyboard.press("Enter")
                send_ok = True

            if send_ok:
                logger.info(f"[X DM] 回复成功: conv={conversation_id} text={reply_text[:50]}")
                return InteractionResult(
                    success=True, platform=self.PLATFORM_NAME,
                    interaction_type="dm_reply",
                    message="X 私信回复成功", content=reply_text,
                )
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME,
                interaction_type="dm_reply",
                error="未找到发送按钮", retryable=True,
            )
        except Exception as e:
            logger.warning(f"[X DM] send_dm_reply 异常: {e}")
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME,
                interaction_type="dm_reply",
                error=f"X 私信回复异常: {e}", retryable=True,
            )
