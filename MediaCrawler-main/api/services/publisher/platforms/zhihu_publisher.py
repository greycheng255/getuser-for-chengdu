# -*- coding: utf-8 -*-
"""
知乎专栏发布器

迁移自 GEO-main/geo_system/backend/zhihu_automation.py
知乎是 5 个 Playwright 平台中唯一会返回 article_url 的。
"""

import asyncio
import logging
import os
from typing import List, Optional

from ..base_publisher import BasePublisher
from ..publish_task import PublishResult
from ..publisher_factory import PublisherFactory

logger = logging.getLogger(__name__)


@PublisherFactory.register("zhihu")
class ZhihuPublisher(BasePublisher):
    """知乎专栏文章发布器"""

    PLATFORM_NAME = "zhihu"
    PLATFORM_CN_NAME = "知乎"
    LOGIN_COOKIE_KEY = "z_c0"
    LOGIN_CHECK_URL = "https://www.zhihu.com/"
    PUBLISH_URL = "https://zhuanlan.zhihu.com/write"
    LOGIN_REDIRECT_KEYWORD = "signin"

    SUPPORTS_ARTICLE = True
    SUPPORTS_IMAGE = True
    MIN_IMAGES = 0

    async def _check_login(self) -> bool:
        """覆盖默认登录检测：URL + DOM 头像元素 + cookie 三重检查"""
        if not self.page:
            return False
        try:
            await self.page.goto(
                self.LOGIN_CHECK_URL,
                timeout=20000,
                wait_until="domcontentloaded",
            )
            await asyncio.sleep(2)

            url = self.page.url
            if self.LOGIN_REDIRECT_KEYWORD in url.lower():
                return False

            # DOM 检测：登录后会显示头像按钮
            try:
                avatar = await self.page.query_selector(
                    'img.Avatar, [class*="Avatar"]'
                )
                if avatar:
                    return True
            except Exception:
                pass

            # cookie 兜底
            if self.LOGIN_COOKIE_KEY:
                cookies = await self.context.cookies()
                return any(c.get("name") == self.LOGIN_COOKIE_KEY for c in cookies)
            return True
        except Exception as e:
            logger.error(f"[{self.PLATFORM_NAME}] 检查登录失败: {e}")
            return False

    async def _do_publish(
        self,
        title: str,
        content: str,
        images: List[str],
        video_path: Optional[str],
        **kwargs,
    ) -> PublishResult:
        """发布知乎专栏文章"""
        debug_info: List[str] = []
        topic: Optional[str] = kwargs.get("topic")

        # 写作页校验
        current_url = self.page.url
        if (
            self.LOGIN_REDIRECT_KEYWORD in current_url.lower()
            or "write" not in current_url.lower()
        ):
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error="无法进入知乎写作页（可能登录已失效）",
                debug_info=debug_info + [f"URL: {current_url}"],
                retryable=False,
            )

        # 1. 填写标题
        title_filled = False
        for selector in [
            "textarea.PostIndex-titleInput",
            'textarea[placeholder*="标题"]',
            "input.PostIndex-titleInput",
            ".WriteIndex-titleInput textarea",
            ".WriteIndex-titleInput input",
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

        # 2. 填写正文（知乎是富文本编辑器）
        content_filled = False
        for selector in [
            "div.PublicDraftEditor-content",
            'div[contenteditable="true"]',
            ".ProseMirror",
            "textarea.PostIndex-contentInput",
        ]:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await self.page.keyboard.type(content, delay=10)
                    content_filled = True
                    debug_info.append("✅ 正文已填写")
                    break
            except Exception as e:
                debug_info.append(f"填写正文失败 ({selector}): {e}")
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
                upload_selectors = [
                    'button:has-text("上传封面")',
                    'input[type="file"][accept*="image"]',
                    ".ColumnWriteBundle-coverUploader",
                    ".UploadPicture button",
                ]
                for selector in upload_selectors:
                    try:
                        if 'input[type="file"]' in selector:
                            el = self.page.locator(selector).first
                            if await el.count() > 0:
                                await el.set_input_files(images[0])
                                debug_info.append("✅ 封面图已上传")
                                await asyncio.sleep(3)
                                break
                        else:
                            btn = self.page.locator(selector).first
                            if await btn.count() > 0:
                                await btn.click(timeout=3000)
                                await asyncio.sleep(1)
                                file_input = self.page.locator(
                                    'input[type="file"][accept*="image"]'
                                ).first
                                if await file_input.count() > 0:
                                    await file_input.set_input_files(images[0])
                                    debug_info.append("✅ 封面图已上传")
                                    await asyncio.sleep(3)
                                    break
                    except Exception:
                        continue
            except Exception as e:
                debug_info.append(f"⚠️ 封面图上传失败: {e}")

        # 4. 添加话题（可选）
        if topic:
            try:
                topic_btn = self.page.locator(
                    'button:has-text("添加话题"), .TopicSelectButton'
                ).first
                if await topic_btn.count() > 0:
                    await topic_btn.click(timeout=3000)
                    await asyncio.sleep(1)
                    topic_input = self.page.locator(
                        'input[placeholder*="话题"], input[placeholder*="搜索"]'
                    ).first
                    if await topic_input.count() > 0:
                        await topic_input.fill(topic)
                        await asyncio.sleep(2)
                        first_topic = self.page.locator(
                            ".TopicSelectItem, .TopicMenuItem"
                        ).first
                        if await first_topic.count() > 0:
                            await first_topic.click(timeout=3000)
                            debug_info.append(f"✅ 话题已添加: {topic}")
            except Exception as e:
                debug_info.append(f"⚠️ 话题添加失败: {e}")

        # 5. 点击发布按钮
        publish_clicked = False
        for selector in [
            'button:has-text("发布")',
            "button.PublishIndex-publishButton",
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

        # 6. 等待发布结果（知乎会跳转到 /p/{id}）
        await asyncio.sleep(5)

        # 7. 业务错误检测
        biz_error = await self._detect_biz_error()
        if biz_error:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=biz_error,
                debug_info=debug_info + [f"❌ {biz_error}"],
                retryable=False,
            )

        # 8. 检查跳转结果
        current_url = self.page.url
        success_indicators = ["/p/", "专栏文章", "已发布"]
        is_success = (
            any(ind in current_url for ind in success_indicators)
            or "/write" not in current_url
        )

        if is_success:
            article_url = current_url if "/p/" in current_url else None
            debug_info.append(f"✅ 发布成功，URL: {current_url}")
            return PublishResult(
                success=True,
                platform=self.PLATFORM_NAME,
                message="知乎专栏文章发布成功",
                url=article_url,
                status="已发布",
                debug_info=debug_info,
            )

        return PublishResult(
            success=False,
            platform=self.PLATFORM_NAME,
            error="发布状态不确定",
            debug_info=debug_info + [f"⚠️ URL: {current_url}"],
        )

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        """知乎单 cookie 值（z_c0）转 Playwright cookie 列表"""
        return [
            {
                "name": "z_c0",
                "value": cookie_value,
                "domain": ".zhihu.com",
                "path": "/",
            }
        ]
