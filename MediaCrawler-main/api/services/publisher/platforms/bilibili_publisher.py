# -*- coding: utf-8 -*-
"""
B站专栏发布器

迁移自 GEO-main/geo_system/backend/bilibili_automation.py
"""

import asyncio
import logging
import os
from typing import List, Optional

from ..base_publisher import BasePublisher
from ..publish_task import PublishResult
from ..publisher_factory import PublisherFactory

logger = logging.getLogger(__name__)


@PublisherFactory.register("bilibili")
class BilibiliPublisher(BasePublisher):
    """B站专栏文章发布器"""

    PLATFORM_NAME = "bilibili"
    PLATFORM_CN_NAME = "B站"
    LOGIN_COOKIE_KEY = "SESSDATA"
    LOGIN_CHECK_URL = "https://www.bilibili.com/"
    PUBLISH_URL = "https://member.bilibili.com/platform/upload-manager/article"
    LOGIN_REDIRECT_KEYWORD = "passport.bilibili.com/login"

    SUPPORTS_ARTICLE = True
    SUPPORTS_IMAGE = True
    MIN_IMAGES = 0

    async def _do_publish(
        self,
        title: str,
        content: str,
        images: List[str],
        video_path: Optional[str],
        **kwargs,
    ) -> PublishResult:
        """发布B站专栏文章"""
        debug_info: List[str] = []

        # 切换到专栏写作（如果显示选项卡）
        for selector in [
            'a:has-text("专栏")',
            'li:has-text("专栏")',
            '.upload-item:has-text("专栏")',
        ]:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click(timeout=3000)
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

        # 1. 填写标题
        title_filled = False
        for selector in [
            "input.article-title",
            'input[placeholder*="标题"]',
            ".article-title input",
            "input.title",
        ]:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await el.fill(title)
                    title_filled = True
                    debug_info.append("✅ 标题已填写")
                    break
            except Exception:
                continue

        if not title_filled:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error="未找到标题输入框",
                debug_info=debug_info,
            )

        # 2. 填写正文
        content_filled = False
        for selector in [
            'div[contenteditable="true"]',
            ".ql-editor",
            "textarea.article-content",
            "div.editor-content",
        ]:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await self.page.keyboard.type(content, delay=10)
                    content_filled = True
                    debug_info.append("✅ 正文已填写")
                    break
            except Exception:
                continue

        if not content_filled:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error="未找到正文输入框",
                debug_info=debug_info,
            )

        await asyncio.sleep(2)

        # 3. 上传封面图
        if images and os.path.exists(images[0]):
            try:
                file_input = self.page.locator(
                    'input[type="file"][accept*="image"]'
                ).first
                if await file_input.count() > 0:
                    await file_input.set_input_files(images[0])
                    debug_info.append("✅ 封面图已上传")
                    await asyncio.sleep(3)
            except Exception as e:
                debug_info.append(f"⚠️ 封面图上传失败: {e}")

        # 4. 点击发布按钮
        publish_clicked = False
        for selector in [
            'button:has-text("发布")',
            'a:has-text("发布")',
            ".submit-btn",
            "button.publish-btn",
        ]:
            try:
                btn = self.page.locator(selector).first
                if await btn.count() > 0 and await btn.is_enabled():
                    await btn.click(timeout=5000)
                    publish_clicked = True
                    debug_info.append("✅ 已点击发布按钮")
                    break
            except Exception:
                continue

        if not publish_clicked:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error="未找到发布按钮",
                debug_info=debug_info,
            )

        await asyncio.sleep(5)

        # 5. 业务错误检测
        biz_error = await self._detect_biz_error()
        if biz_error:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=biz_error,
                debug_info=debug_info + [f"❌ {biz_error}"],
                retryable=False,
            )

        debug_info.append("✅ B站专栏文章发布成功")
        return PublishResult(
            success=True,
            platform=self.PLATFORM_NAME,
            message="B站专栏文章发布成功",
            status="已发布",
            debug_info=debug_info,
        )

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        """B站单 cookie 值（SESSDATA）转 Playwright cookie 列表"""
        return [
            {
                "name": "SESSDATA",
                "value": cookie_value,
                "domain": ".bilibili.com",
                "path": "/",
            }
        ]
