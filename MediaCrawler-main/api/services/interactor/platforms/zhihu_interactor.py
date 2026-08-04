# -*- coding: utf-8 -*-
"""
知乎互动器

实现知乎网页版的点赞 / 评论 / 回复 / 关注。
基于 Playwright DOM 自动化，模拟真人操作节奏。
"""

import asyncio
import logging

from ..base_interactor import BaseInteractor
from ..interaction_models import InteractionResult
from ..interactor_factory import InteractorFactory

logger = logging.getLogger(__name__)


@InteractorFactory.register("zhihu")
class ZhihuInteractor(BaseInteractor):
    PLATFORM_CN_NAME = "知乎"
    LOGIN_COOKIE_KEY = "z_c0"
    LOGIN_CHECK_URL = "https://www.zhihu.com/"
    LOGIN_REDIRECT_KEYWORD = "signin"

    # 能力声明
    SUPPORTS_LIKE: bool = True
    SUPPORTS_COMMENT: bool = True
    SUPPORTS_REPLY: bool = True
    SUPPORTS_FOLLOW: bool = True

    # 知乎点赞按钮 selector（多个兜底）
    LIKE_SELECTORS = [
        'button[aria-label*="赞同"]',
        '.VoteButton--up',
        'button:has-text("赞同")',
    ]
    COMMENT_INPUT_SELECTORS = [
        'div[contenteditable="true"]',
        'textarea[placeholder*="评论"]',
        '.CommentEditor textarea',
    ]
    COMMENT_SUBMIT_SELECTORS = [
        'button:has-text("发送")',
        'button:has-text("评论")',
    ]
    FOLLOW_SELECTORS = [
        'button:has-text("关注")',
        '.FollowButton',
        '[class*="follow"]',
    ]

    async def _do_like(self, post_url: str, **kwargs) -> InteractionResult:
        await self._human_delay(1, 2)
        ok = await self._try_click_selectors(self.LIKE_SELECTORS, timeout=8000)
        await self._human_delay(0.5, 1)
        if ok:
            return InteractionResult(
                success=True,
                platform=self.PLATFORM_NAME,
                interaction_type="like",
                message="知乎点赞成功",
            )
        return InteractionResult(
            success=False,
            platform=self.PLATFORM_NAME,
            interaction_type="like",
            error="未找到点赞按钮",
            retryable=True,
        )

    async def _do_comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        # 展开评论框
        await self._try_click_selectors(self.COMMENT_INPUT_SELECTORS, timeout=8000)
        await self._human_delay(0.5, 1)
        # 填入评论
        filled = False
        for selector in self.COMMENT_INPUT_SELECTORS:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await self.page.keyboard.type(content, delay=50)
                    filled = True
                    break
            except Exception:
                continue
        if not filled:
            return InteractionResult(
                success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
                error="未找到评论输入框", retryable=True,
            )
        await self._human_delay(0.5, 1)
        # 点击发送
        ok = await self._try_click_selectors(self.COMMENT_SUBMIT_SELECTORS, timeout=5000)
        if ok:
            await self._human_delay(1, 2)
            biz_err = await self._detect_biz_error()
            if biz_err:
                return InteractionResult(
                    success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
                    error=biz_err, retryable=False,
                )
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="comment",
                message="知乎评论成功", content=content,
            )
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="comment",
            error="评论发送失败", retryable=True,
        )

    async def _do_reply(
        self, post_url: str, comment_id: str, content: str, **kwargs
    ) -> InteractionResult:
        # 找到目标评论并点击"回复"
        reply_trigger_selectors = [
            f'[data-id="{comment_id}"] :text("回复")',
            f'div[id="{comment_id}"] :text("回复")',
            f'.CommentItem :text("回复")',
        ]
        await self._try_click_selectors(reply_trigger_selectors, timeout=8000)
        await self._human_delay(0.5, 1)
        # 复用评论输入逻辑
        return await self._do_comment(post_url, content, **kwargs)

    async def _do_follow(self, user_url: str, **kwargs) -> InteractionResult:
        await self.page.goto(user_url, timeout=20000, wait_until="domcontentloaded")
        await self._human_delay(2, 3)
        ok = await self._try_click_selectors(self.FOLLOW_SELECTORS, timeout=8000)
        if ok:
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="follow",
                message="知乎关注成功",
            )
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="follow",
            error="未找到关注按钮或已关注", retryable=True,
        )
