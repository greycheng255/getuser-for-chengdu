# -*- coding: utf-8 -*-
"""
微信视频号发布器

阶段二 P1 任务 2.6：补齐国内 P0 平台剩余 2 个（视频号）。

设计要点：
1. 通过微信视频号助手 Playwright 自动化（https://channels.weixin.qq.com）
2. 视频上传 + 描述 + 话题标签
3. 继承 BasePublisher，复用 init/login/persist/close 模板方法
4. 多 selector 兜底，适配视频号平台 DOM 变化
5. 注册到 PublisherFactory，通过 @PublisherFactory.register("wechat_channels")
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


@PublisherFactory.register("wechat_channels")
class WechatChannelsPublisher(BasePublisher):
    """微信视频号发布器

    支持：
    - 短视频（video_path + content + hashtags）
    - 图片轮播（images + content）
    """

    PLATFORM_NAME = "wechat_channels"
    PLATFORM_CN_NAME = "微信视频号"
    LOGIN_COOKIE_KEY = "sess_data"  # 视频号 cookie 关键字段
    LOGIN_CHECK_URL = "https://channels.weixin.qq.com/platform/post/create"
    PUBLISH_URL = "https://channels.weixin.qq.com/platform/post/create"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_IMAGE = True
    SUPPORTS_VIDEO = True
    SUPPORTS_ARTICLE = False
    MIN_IMAGES = 0

    # 视频/图片上传 input selector
    UPLOAD_INPUT_SELECTORS = [
        'input[type="file"][accept*="video"]',
        'input[type="file"][accept*="image"]',
        'input[type="file"]',
        '.upload input[type="file"]',
        '.weui-input-file',
    ]
    # 描述输入框
    CONTENT_SELECTORS = [
        'div[contenteditable="true"]',
        'textarea[placeholder*="描述"]',
        'textarea[placeholder*="说点什么"]',
        '.editor-container [contenteditable="true"]',
        '.desc-textarea textarea',
        'textarea.input-desc',
    ]
    # 话题标签输入（视频号需要点击"#"按钮）
    HASHTAG_INPUT_SELECTORS = [
        'input[placeholder*="话题"]',
        'input[placeholder*="标签"]',
        '.hashtag-input input',
    ]
    # 发布按钮
    PUBLISH_BTN_SELECTORS = [
        'button:has-text("发表")',
        'button:has-text("发布")',
        'button.weui-btn_primary',
        '.publish-btn button',
        'button[type="submit"]:has-text("发表")',
    ]

    async def _do_publish(
        self, title: str, content: str, images: List[str],
        video_path: Optional[str], **kwargs,
    ) -> PublishResult:
        debug_info: List[str] = []

        # 1. 上传素材
        if video_path and os.path.exists(video_path):
            upload_ok = await self._upload_file(video_path, "video", debug_info)
            if not upload_ok:
                return PublishResult(
                    success=False, platform=self.PLATFORM_NAME,
                    error="视频号视频上传失败", debug_info=debug_info, retryable=True,
                )
        elif images:
            for img in images[:9]:  # 视频号最多 9 张图
                if os.path.exists(img):
                    await self._upload_file(img, "image", debug_info)
                    await asyncio.sleep(1)
        else:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error="视频号必须上传视频或图片",
                debug_info=debug_info, retryable=False,
            )

        # 2. 填写描述
        if content:
            await self._fill_content(content, debug_info)

        # 3. 添加话题标签
        hashtags = kwargs.get("hashtags", [])
        if hashtags:
            await self._add_hashtags(hashtags, debug_info)

        # 4. 点击发布
        publish_clicked = False
        for selector in self.PUBLISH_BTN_SELECTORS:
            try:
                btn = self.page.locator(selector).first
                if await btn.count() > 0 and await btn.is_enabled():
                    await btn.click(timeout=8000)
                    publish_clicked = True
                    debug_info.append(f"✅ 已点击发布按钮 ({selector})")
                    break
            except Exception:
                continue

        if not publish_clicked:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error="未找到视频号发布按钮", debug_info=debug_info, retryable=True,
            )

        await asyncio.sleep(8)
        # 检测业务错误
        biz_error = await self._detect_biz_error()
        if biz_error:
            return PublishResult(
                success=False, platform=self.PLATFORM_NAME,
                error=biz_error, debug_info=debug_info, retryable=False,
            )
        return PublishResult(
            success=True, platform=self.PLATFORM_NAME,
            message="微信视频号发布成功", status="已发布",
            debug_info=debug_info,
        )

    async def _upload_file(
        self, file_path: str, file_type: str, debug_info: List[str]
    ) -> bool:
        """上传视频或图片"""
        for selector in self.UPLOAD_INPUT_SELECTORS:
            try:
                file_input = self.page.locator(selector).first
                if await file_input.count() > 0:
                    await file_input.set_input_files(file_path)
                    debug_info.append(f"✅ {file_type} 已上传 ({selector})")
                    # 等待上传完成（视频需要更久）
                    await asyncio.sleep(10 if file_type == "video" else 3)
                    return True
            except Exception as e:
                debug_info.append(f"⚠️ {selector} 上传失败: {e}")
                continue
        return False

    async def _fill_content(self, content: str, debug_info: List[str]) -> None:
        """填写描述"""
        for selector in self.CONTENT_SELECTORS:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await asyncio.sleep(0.5)
                    await self.page.keyboard.type(content, delay=30)
                    debug_info.append(f"✅ 描述已填写 ({selector})")
                    return
            except Exception:
                continue
        debug_info.append("⚠️ 未找到描述输入框")

    async def _add_hashtags(
        self, hashtags: List[str], debug_info: List[str]
    ) -> None:
        """添加话题标签"""
        for tag in hashtags[:5]:  # 最多 5 个
            for selector in self.HASHTAG_INPUT_SELECTORS:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        await self.page.keyboard.type(f"#{tag}", delay=20)
                        await asyncio.sleep(0.3)
                        await self.page.keyboard.press("Space")
                        debug_info.append(f"✅ 话题标签已添加: #{tag}")
                        break
                except Exception:
                    continue
