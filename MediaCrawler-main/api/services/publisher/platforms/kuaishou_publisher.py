# -*- coding: utf-8 -*-
"""
快手图文/视频发布器

阶段一 P0 任务 1.1：补齐 PRD 5.3 国内 P0 平台缺口。

设计要点：
1. 继承 BasePublisher，复用 init/login/persist/close 模板方法
2. 支持 video_path 与 images 两种发布形态
3. 复用 stealth_browser 反检测层（Chrome 131 UA + 隐藏 webdriver）
4. 注册到 PublisherFactory，通过装饰器 @PublisherFactory.register("kuaishou")
5. 多 selector 兜底，适配快手创作者中心 DOM 变化
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


@PublisherFactory.register("kuaishou")
class KuaishouPublisher(BasePublisher):
    """快手创作者中心发布器

    支持：
    - 图文笔记（images + title + content）
    - 短视频（video_path + title + content）
    """

    PLATFORM_NAME = "kuaishou"
    PLATFORM_CN_NAME = "快手"
    LOGIN_COOKIE_KEY = "userId"  # 快手创作者中心关键 cookie
    LOGIN_CHECK_URL = "https://cp.kuaishou.com/article/publish/video"
    PUBLISH_URL = "https://cp.kuaishou.com/article/publish/video"
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
    ]
    # 标题输入框
    TITLE_SELECTORS = [
        'input[placeholder*="标题"]',
        'input[placeholder*="填个标题"]',
        'textarea[placeholder*="标题"]',
        '.title-input input',
        '.input-title input',
    ]
    # 正文/描述输入框
    CONTENT_SELECTORS = [
        'div[contenteditable="true"]',
        'textarea[placeholder*="描述"]',
        'textarea[placeholder*="添加描述"]',
        '.desc-input textarea',
        '.editor-container [contenteditable="true"]',
    ]
    # 发布按钮
    PUBLISH_BTN_SELECTORS = [
        'button:has-text("发布")',
        'button:has-text("立即发布")',
        'button.publish-btn',
        'button[type="submit"]:has-text("发布")',
        '.publish-button',
    ]

    async def _do_publish(
        self,
        title: str,
        content: str,
        images: List[str],
        video_path: Optional[str],
        **kwargs,
    ) -> PublishResult:
        """执行快手发布

        优先级：video_path > images
        """
        debug_info: List[str] = []

        # 1. 上传素材
        if video_path:
            upload_ok = await self._upload_file(video_path, "video", debug_info)
            if not upload_ok:
                return PublishResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error="快手视频上传失败",
                    debug_info=debug_info,
                    retryable=True,
                )
        elif images:
            uploaded = 0
            for img_path in images:
                if not os.path.exists(img_path):
                    debug_info.append(f"⚠️ 图片不存在: {img_path}")
                    continue
                if await self._upload_file(img_path, "image", debug_info):
                    uploaded += 1
                    await asyncio.sleep(2)
            if uploaded == 0:
                return PublishResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error="快手图文必须上传至少 1 张图片",
                    debug_info=debug_info,
                    retryable=False,
                )

        # 等待上传处理
        await asyncio.sleep(5)

        # 2. 填写标题
        if title:
            await self._fill_title(title, debug_info)

        # 3. 填写正文
        await self._fill_content(content, debug_info)

        # 4. 点击发布
        publish_clicked = False
        for selector in self.PUBLISH_BTN_SELECTORS:
            try:
                btn = self.page.locator(selector).first
                if await btn.count() > 0 and await btn.is_enabled():
                    await btn.click(timeout=8000)
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

        # 6. 尝试获取发布后的 URL
        try:
            current_url = self.page.url
            if "publish" not in current_url:
                debug_info.append(f"✅ 已跳转到: {current_url}")
        except Exception:
            pass

        debug_info.append("✅ 快手发布成功")
        return PublishResult(
            success=True,
            platform=self.PLATFORM_NAME,
            message="快手内容发布成功",
            status="已发布",
            debug_info=debug_info,
        )

    async def _upload_file(
        self, file_path: str, file_type: str, debug_info: List[str]
    ) -> bool:
        """上传单个文件"""
        if not os.path.exists(file_path):
            debug_info.append(f"⚠️ 文件不存在: {file_path}")
            return False
        for selector in self.UPLOAD_INPUT_SELECTORS:
            try:
                file_input = self.page.locator(selector).first
                if await file_input.count() > 0:
                    await file_input.set_input_files(file_path)
                    debug_info.append(f"✅ {file_type} 已上传: {os.path.basename(file_path)}")
                    return True
            except Exception as e:
                debug_info.append(f"⚠️ selector {selector} 上传失败: {e}")
                continue
        return False

    async def _fill_title(self, title: str, debug_info: List[str]):
        for selector in self.TITLE_SELECTORS:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await el.fill(title)
                    debug_info.append("✅ 标题已填写")
                    return
            except Exception:
                continue
        debug_info.append("⚠️ 未找到标题输入框（继续尝试发布）")

    async def _fill_content(self, content: str, debug_info: List[str]):
        if not content:
            return
        for selector in self.CONTENT_SELECTORS:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await self.page.keyboard.type(content, delay=20)
                    debug_info.append("✅ 正文已填写")
                    return
            except Exception:
                continue
        debug_info.append("⚠️ 未找到正文输入框（继续尝试发布）")

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        """快手单 cookie 值（userId）转 Playwright cookie 列表"""
        return [
            {
                "name": "userId",
                "value": cookie_value,
                "domain": ".kuaishou.com",
                "path": "/",
            }
        ]
