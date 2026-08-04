# -*- coding: utf-8 -*-
"""
抖音图文发布器

迁移自 GEO-main/geo_system/backend/douyin_automation.py
重构为继承 BasePublisher，消除 80% 重复代码（init/login/persist/close 已上移）。
"""

import asyncio
import logging
import os
from typing import List, Optional

from ..base_publisher import BasePublisher
from ..exceptions import BizError
from ..publish_task import PublishResult
from ..publisher_factory import PublisherFactory

logger = logging.getLogger(__name__)


@PublisherFactory.register("douyin")
class DouyinPublisher(BasePublisher):
    """抖音图文笔记发布器"""

    PLATFORM_NAME = "douyin"
    PLATFORM_CN_NAME = "抖音"
    LOGIN_COOKIE_KEY = "sessionid"
    LOGIN_CHECK_URL = "https://creator.douyin.com/"
    PUBLISH_URL = "https://creator.douyin.com/creator-metrics/content-upload?default_type=image"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_IMAGE = True
    SUPPORTS_VIDEO = False
    MIN_IMAGES = 0  # 抖音图文建议至少 1 张，但不强制

    async def _do_publish(
        self,
        title: str,
        content: str,
        images: List[str],
        video_path: Optional[str],
        **kwargs,
    ) -> PublishResult:
        """发布抖音图文笔记

        注意：self.page 已打开 PUBLISH_URL，可直接操作。
        """
        debug_info: List[str] = []

        # 1. 上传图片
        if images:
            uploaded_count = 0
            for img_path in images:
                if not os.path.exists(img_path):
                    debug_info.append(f"⚠️ 图片不存在: {img_path}")
                    continue
                try:
                    file_input = self.page.locator(
                        'input[type="file"][accept*="image"]'
                    ).first
                    if await file_input.count() > 0:
                        await file_input.set_input_files(img_path)
                        uploaded_count += 1
                        debug_info.append(f"✅ 图片已上传: {os.path.basename(img_path)}")
                        await asyncio.sleep(3)
                except Exception as e:
                    debug_info.append(f"⚠️ 图片上传失败: {e}")

            if uploaded_count == 0 and images:
                return PublishResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error="抖音图文必须上传至少 1 张图片",
                    debug_info=debug_info,
                    retryable=False,
                )

        await asyncio.sleep(2)

        # 2. 填写标题（可选）
        if title:
            for selector in [
                'input[placeholder*="标题"]',
                "input.title",
                ".title-input input",
            ]:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        await el.fill(title)
                        debug_info.append(f"✅ 标题已填写")
                        break
                except Exception:
                    continue

        # 3. 填写正文
        content_filled = False
        for selector in [
            'div[contenteditable="true"]',
            'textarea[placeholder*="描述"]',
            ".editor-container [contenteditable='true']",
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
            debug_info.append("⚠️ 未找到正文输入框（继续尝试发布）")

        await asyncio.sleep(2)

        # 4. 点击发布按钮
        publish_clicked = False
        for selector in [
            'button:has-text("发布")',
            "button.publish-btn",
            'button[type="submit"]:has-text("发布")',
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

        debug_info.append("✅ 抖音图文发布成功")
        return PublishResult(
            success=True,
            platform=self.PLATFORM_NAME,
            message="抖音图文笔记发布成功",
            status="已发布",
            debug_info=debug_info,
        )

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        """抖音单 cookie 值（sessionid）转 Playwright cookie 列表"""
        return [
            {
                "name": "sessionid",
                "value": cookie_value,
                "domain": ".douyin.com",
                "path": "/",
            }
        ]
