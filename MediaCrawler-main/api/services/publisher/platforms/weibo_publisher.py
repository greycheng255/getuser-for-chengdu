# -*- coding: utf-8 -*-
"""
微博图文发布器

迁移自 GEO-main/geo_system/backend/weibo_automation.py
"""

import asyncio
import logging
import os
from typing import List, Optional

from ..base_publisher import BasePublisher
from ..publish_task import PublishResult
from ..publisher_factory import PublisherFactory

logger = logging.getLogger(__name__)


@PublisherFactory.register("weibo")
class WeiboPublisher(BasePublisher):
    """微博图文发布器"""

    PLATFORM_NAME = "weibo"
    PLATFORM_CN_NAME = "微博"
    LOGIN_COOKIE_KEY = "SUB"
    LOGIN_CHECK_URL = "https://weibo.com/"
    # 微博在首页直接发布，无独立发布页
    PUBLISH_URL = "https://weibo.com/"
    LOGIN_REDIRECT_KEYWORD = "passport.weibo"

    SUPPORTS_IMAGE = True
    SUPPORTS_ARTICLE = True
    MIN_IMAGES = 0

    async def _do_publish(
        self,
        title: str,
        content: str,
        images: List[str],
        video_path: Optional[str],
        **kwargs,
    ) -> PublishResult:
        """发布微博"""
        debug_info: List[str] = []

        # 微博首页就有发布框；title 会被合并到 content 头部
        full_content = f"【{title}】{content}" if title else content

        # 1. 找到微博正文输入框
        content_filled = False
        for selector in [
            "textarea.WB_textarea",
            'textarea[placeholder*="有什么新鲜事"]',
            'div[contenteditable="true"]',
            ".Form_input textarea",
            "textarea.Boxs_textarea",
        ]:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await asyncio.sleep(1)
                    await self.page.keyboard.type(full_content, delay=10)
                    content_filled = True
                    debug_info.append("✅ 正文已填写")
                    break
            except Exception:
                continue

        if not content_filled:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error="未找到微博正文输入框",
                debug_info=debug_info,
            )

        await asyncio.sleep(1)

        # 2. 上传图片
        if images:
            for img_path in images:
                if not os.path.exists(img_path):
                    continue
                try:
                    file_input = self.page.locator(
                        'input[type="file"][accept*="image"]'
                    ).first
                    if await file_input.count() > 0:
                        await file_input.set_input_files(img_path)
                        debug_info.append(f"✅ 图片已上传: {os.path.basename(img_path)}")
                        await asyncio.sleep(3)
                except Exception as e:
                    debug_info.append(f"⚠️ 图片上传失败: {e}")

        await asyncio.sleep(2)

        # 3. 点击发布按钮
        publish_clicked = False
        for selector in [
            'a:has-text("发布")',
            'button:has-text("发布")',
            "a.WB_btn_release",
            ".Form_btn a",
        ]:
            try:
                btn = self.page.locator(selector).first
                if await btn.count() > 0:
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

        # 4. 业务错误检测
        biz_error = await self._detect_biz_error()
        if biz_error:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=biz_error,
                debug_info=debug_info + [f"❌ {biz_error}"],
                retryable=False,
            )

        debug_info.append("✅ 微博发布成功")
        return PublishResult(
            success=True,
            platform=self.PLATFORM_NAME,
            message="微博发布成功",
            status="已发布",
            debug_info=debug_info,
        )

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        """微博单 cookie 值（SUB）转 Playwright cookie 列表"""
        return [
            {
                "name": "SUB",
                "value": cookie_value,
                "domain": ".weibo.com",
                "path": "/",
            }
        ]
