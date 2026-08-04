# -*- coding: utf-8 -*-
"""
今日头条发布器

阶段二 P1 任务 2.6：补齐国内 P0 平台剩余 2 个（今日头条）。

设计要点：
1. 通过头条号后台 Playwright 自动化（https://mp.toutiao.com）
2. 视频上传 + 标题 + 描述
3. 继承 BasePublisher，复用 init/login/persist/close 模板方法
4. 多 selector 兜底，适配头条号后台 DOM 变化
5. 注册到 PublisherFactory，通过 @PublisherFactory.register("toutiao")
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


@PublisherFactory.register("toutiao")
class ToutiaoPublisher(BasePublisher):
    """今日头条发布器

    支持：
    - 视频发布（video_path + title + content）
    - 图文文章（title + content + images）
    """

    PLATFORM_NAME = "toutiao"
    PLATFORM_CN_NAME = "今日头条"
    LOGIN_COOKIE_KEY = "sessionid"  # 头条号 cookie 关键字段
    LOGIN_CHECK_URL = "https://mp.toutiao.com/profile_v4/index"
    PUBLISH_URL = "https://mp.toutiao.com/profile_v4/graphic/publish"
    VIDEO_PUBLISH_URL = "https://mp.toutiao.com/profile_v4/video/upload"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_IMAGE = True
    SUPPORTS_VIDEO = True
    SUPPORTS_ARTICLE = True
    MIN_IMAGES = 0

    # 视频/图片上传 input selector
    UPLOAD_INPUT_SELECTORS = [
        'input[type="file"][accept*="video"]',
        'input[type="file"][accept*="image"]',
        'input[type="file"]',
        '.upload-input input[type="file"]',
        'div[class*="upload"] input[type="file"]',
    ]
    # 标题输入框
    TITLE_SELECTORS = [
        'input[placeholder*="标题"]',
        'input[placeholder*="写标题"]',
        'textarea[placeholder*="标题"]',
        '.title-input input',
        'div[class*="title"] input',
        'input.input-title',
    ]
    # 正文/描述输入框
    CONTENT_SELECTORS = [
        'div[contenteditable="true"]',
        'textarea[placeholder*="描述"]',
        'textarea[placeholder*="正文"]',
        '.editor-container [contenteditable="true"]',
        'div.ProseMirror',
        'div[class*="ql-editor"]',
    ]
    # 发布按钮
    PUBLISH_BTN_SELECTORS = [
        'button:has-text("发布")',
        'button:has-text("发表")',
        'button:has-text("确认发布")',
        'button.publish-btn',
        'button[class*="publish"]',
        'button[type="submit"]:has-text("发布")',
    ]

    async def _do_publish(
        self, title: str, content: str, images: List[str],
        video_path: Optional[str], **kwargs,
    ) -> PublishResult:
        debug_info: List[str] = []

        # 1. 选择发布类型并导航
        if video_path and os.path.exists(video_path):
            # 视频发布
            try:
                await self.page.goto(
                    self.VIDEO_PUBLISH_URL,
                    timeout=20000, wait_until="domcontentloaded",
                )
                await asyncio.sleep(2)
            except Exception as e:
                debug_info.append(f"⚠️ 导航视频发布页失败: {e}")
        else:
            # 图文发布（默认 URL）
            pass

        # 2. 上传素材
        if video_path and os.path.exists(video_path):
            upload_ok = await self._upload_file(video_path, "video", debug_info)
            if not upload_ok:
                return PublishResult(
                    success=False, platform=self.PLATFORM_NAME,
                    error="头条视频上传失败", debug_info=debug_info, retryable=True,
                )
        elif images:
            for img in images[:9]:  # 头条最多 9 张图
                if os.path.exists(img):
                    await self._upload_file(img, "image", debug_info)
                    await asyncio.sleep(1)

        # 3. 填写标题
        if title:
            await self._fill_title(title, debug_info)

        # 4. 填写正文/描述
        if content:
            await self._fill_content(content, debug_info)

        # 5. 点击发布
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
                error="未找到头条发布按钮", debug_info=debug_info, retryable=True,
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
            message="今日头条发布成功", status="已发布",
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
                    # 等待上传完成
                    await asyncio.sleep(15 if file_type == "video" else 3)
                    return True
            except Exception as e:
                debug_info.append(f"⚠️ {selector} 上传失败: {e}")
                continue
        return False

    async def _fill_title(self, title: str, debug_info: List[str]) -> None:
        """填写标题"""
        for selector in self.TITLE_SELECTORS:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await asyncio.sleep(0.3)
                    await self.page.keyboard.type(title[:30], delay=20)  # 头条标题限 30 字
                    debug_info.append(f"✅ 标题已填写 ({selector})")
                    return
            except Exception:
                continue
        debug_info.append("⚠️ 未找到标题输入框")

    async def _fill_content(self, content: str, debug_info: List[str]) -> None:
        """填写正文/描述"""
        for selector in self.CONTENT_SELECTORS:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await asyncio.sleep(0.5)
                    await self.page.keyboard.type(content, delay=30)
                    debug_info.append(f"✅ 正文已填写 ({selector})")
                    return
            except Exception:
                continue
        debug_info.append("⚠️ 未找到正文输入框")
