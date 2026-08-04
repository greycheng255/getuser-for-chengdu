# -*- coding: utf-8 -*-
"""
快手互动器

阶段一 P0 任务 1.1：补齐 PRD 5.4 国内 P0 平台缺口。

实现快手网页版的点赞 / 评论 / 回复 / 关注 / 收藏 / 转发。
基于 Playwright DOM 自动化，模拟真人操作节奏。
"""

import asyncio
import logging

from ..base_interactor import BaseInteractor
from ..interaction_models import InteractionResult
from ..interactor_factory import InteractorFactory

logger = logging.getLogger(__name__)


@InteractorFactory.register("kuaishou")
class KuaishouInteractor(BaseInteractor):
    """快手互动器"""

    PLATFORM_CN_NAME = "快手"
    LOGIN_COOKIE_KEY = "userId"
    LOGIN_CHECK_URL = "https://www.kuaishou.com/"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_LIKE = True
    SUPPORTS_COMMENT = True
    SUPPORTS_REPLY = True
    SUPPORTS_FOLLOW = True
    SUPPORTS_COLLECT = True  # 快手支持收藏

    # 点赞按钮 selector
    LIKE_SELECTORS = [
        '.like-button',
        'button[aria-label*="点赞"]',
        'button[aria-label*="Like"]',
        '.video-like',
        'span:has-text("赞"):not(:has-text("点赞"))',
        '[data-e2e="video-like"]',
    ]
    # 评论输入框
    COMMENT_INPUT_SELECTORS = [
        'textarea[placeholder*="评论"]',
        'textarea[placeholder*="说点什么"]',
        'div[contenteditable="true"][placeholder*="评论"]',
        '.comment-input textarea',
        '.comment-input [contenteditable="true"]',
    ]
    COMMENT_SUBMIT_SELECTORS = [
        'button:has-text("发送")',
        'button:has-text("评论")',
        '.comment-submit',
        '[data-e2e="comment-publish"]',
    ]
    # 关注按钮
    FOLLOW_SELECTORS = [
        'button:has-text("关注")',
        '.follow-btn:not(:has-text("已关注"))',
        '[data-e2e="user-follow"]',
    ]
    # 收藏按钮
    COLLECT_SELECTORS = [
        '.collect-button',
        'button[aria-label*="收藏"]',
        'button[aria-label*="Collect"]',
        '.video-collect',
        '[data-e2e="video-collect"]',
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
                message="快手点赞成功",
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
                message="快手评论成功", content=content,
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
            f'[data-comment-id="{comment_id}"] :text("回复")',
            f'[data-e2e="comment-item"][data-id="{comment_id}"] :text("回复")',
            f'div[data-e2e="comment-list"] :text("回复")',
        ]
        await self._try_click_selectors(reply_trigger_selectors, timeout=8000)
        await self._human_delay(0.5, 1)
        return await self._do_comment(post_url, content, **kwargs)

    async def _do_follow(self, user_url: str, **kwargs) -> InteractionResult:
        await self.page.goto(user_url, timeout=20000, wait_until="domcontentloaded")
        await self._human_delay(2, 3)
        ok = await self._try_click_selectors(self.FOLLOW_SELECTORS, timeout=8000)
        if ok:
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="follow",
                message="快手关注成功",
            )
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="follow",
            error="未找到关注按钮或已关注", retryable=True,
        )

    async def _do_collect(self, post_url: str, **kwargs) -> InteractionResult:
        """收藏（快手支持）"""
        await self._human_delay(1, 2)
        ok = await self._try_click_selectors(self.COLLECT_SELECTORS, timeout=8000)
        if ok:
            return InteractionResult(
                success=True, platform=self.PLATFORM_NAME, interaction_type="collect",
                message="快手收藏成功",
            )
        return InteractionResult(
            success=False, platform=self.PLATFORM_NAME, interaction_type="collect",
            error="未找到收藏按钮", retryable=True,
        )
