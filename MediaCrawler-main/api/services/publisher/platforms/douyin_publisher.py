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
from ..publish_feature_flags import douyin_video_publish_enabled
from ..publish_task import PublishErrorCode, PublishResult
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
    VIDEO_PUBLISH_URL = "https://creator.douyin.com/creator-metrics/content-upload?default_type=video"
    MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_IMAGE = True
    SUPPORTS_VIDEO = True
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

        keywords: List[str] = kwargs.get("keywords", [])

        # 1. 上传视频或图片
        if video_path:
            if not douyin_video_publish_enabled():
                return PublishResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error="抖音视频发布能力未开启",
                    error_code=PublishErrorCode.INVALID_MEDIA.value,
                    debug_info=debug_info,
                    retryable=False,
                )
            if not await self._upload_video(video_path, debug_info):
                return PublishResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error="抖音视频上传失败",
                    error_code=PublishErrorCode.UPLOAD_FAILED.value,
                    debug_info=debug_info,
                    retryable=True,
                )
            cover_path = kwargs.get("cover_path")
            if cover_path:
                await self._apply_cover(cover_path, debug_info)
        elif images:
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

        # 3. 填写正文和标签
        formatted_content = content
        if keywords:
            formatted_content = f"{content}\n\n" + " ".join(
                f"#{keyword}" for keyword in keywords[:5]
            )
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
                    await self.page.keyboard.type(formatted_content, delay=10)
                    content_filled = True
                    debug_info.append("✅ 正文已填写")
                    break
            except Exception:
                continue

        if not content_filled:
            debug_info.append("⚠️ 未找到正文输入框（继续尝试发布）")

        await asyncio.sleep(2)

        # 可见范围、评论权限等发布设置（未传入时沿用平台默认值）
        await self._apply_publish_settings(kwargs, debug_info)

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

        confirmed, post_url, post_id = await self._confirm_publish_success(
            url_markers=["/video/", "/note/"],
            success_markers=["发布成功", "作品已发布", "提交成功", "审核中"],
        )
        if not post_url:
            compensated, compensated_url, compensated_id = await self._query_recent_published_post(
                manage_url=self.MANAGE_URL,
                link_selector='a[href*="/video/"], a[href*="/note/"]',
                title=title,
            )
            if compensated:
                confirmed, post_url, post_id = True, compensated_url, compensated_id
                debug_info.append("✅ 已通过作品管理页补偿查询确认发布")
        if not confirmed:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error="抖音发布结果未通过二次确认",
                error_code=PublishErrorCode.UNKNOWN.value,
                debug_info=debug_info,
                retryable=False,
            )

        media_name = "视频" if video_path else "图文"
        debug_info.append(f"✅ 抖音{media_name}发布已二次确认")
        return PublishResult(
            success=True,
            platform=self.PLATFORM_NAME,
            message=f"抖音{media_name}发布成功",
            post_url=post_url,
            post_id=post_id,
            status="已发布",
            debug_info=debug_info,
        )

    def _get_publish_url(self, video_path: Optional[str]) -> str:
        return self.VIDEO_PUBLISH_URL if video_path else self.PUBLISH_URL

    async def _upload_video(self, video_path: str, debug_info: List[str]) -> bool:
        for selector in [
            'input[type="file"][accept*="video"]',
            'input[type="file"]',
        ]:
            try:
                file_input = self.page.locator(selector).first
                if await file_input.count() > 0:
                    await file_input.set_input_files(video_path)
                    debug_info.append(f"✅ 视频已提交上传: {os.path.basename(video_path)}")
                    for _ in range(15):
                        page_text = str(await self.page.evaluate(
                            '() => document.body.innerText.slice(0, 2000)'
                        ) or "")
                        if any(marker in page_text for marker in ["上传成功", "重新上传", "视频封面"]):
                            debug_info.append("✅ 视频上传处理完成")
                            return True
                        if any(marker in page_text for marker in ["上传失败", "格式不支持", "视频损坏"]):
                            debug_info.append(f"❌ 视频上传失败: {page_text[:200]}")
                            return False
                        await asyncio.sleep(2)
                    debug_info.append("⚠️ 未获取上传完成提示，继续检查发布表单")
                    return True
            except Exception as exc:
                debug_info.append(f"⚠️ 视频上传入口失败 ({selector}): {exc}")
        return False

    async def _apply_cover(self, cover_path: str, debug_info: List[str]) -> bool:
        if not os.path.isfile(cover_path):
            debug_info.append(f"⚠️ 封面文件不存在: {cover_path}")
            return False
        for selector in ['input[type="file"][accept*="image"]', '.cover-upload input[type="file"]']:
            try:
                cover_input = self.page.locator(selector).last
                if await cover_input.count() > 0:
                    await cover_input.set_input_files(cover_path)
                    debug_info.append("✅ 视频封面已设置")
                    return True
            except Exception:
                continue
        debug_info.append("⚠️ 未找到视频封面入口，沿用平台自动封面")
        return False

    async def _apply_publish_settings(self, kwargs: dict, debug_info: List[str]) -> None:
        visibility = kwargs.get("visibility")
        if visibility:
            try:
                option = self.page.get_by_text(str(visibility), exact=True).last
                if await option.count() > 0:
                    await option.click()
                    debug_info.append(f"✅ 可见范围已设置为 {visibility}")
            except Exception as exc:
                debug_info.append(f"⚠️ 可见范围设置未生效: {exc}")

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
