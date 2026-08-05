# -*- coding: utf-8 -*-
"""
小红书图文笔记发布器

迁移自 GEO-main/geo_system/backend/xiaohongshu_automation.py（65KB），精简为 ~250 行。

关键策略：
1. 强制 MIN_IMAGES = 1（小红书必须至少 1 张图片）
2. 三路图片上传兜底：filechooser → set_input_files → JavaScript 触发
3. JavaScript + 传统 selector 双路填表（小红书 Vue 富文本编辑器较难定位）
4. 完整业务错误检测（-9136 / -10000 / 风控限制 / HTTPBizError）
"""

import asyncio
import logging
import os
from typing import List, Optional

from ..base_publisher import BasePublisher
from ..publish_feature_flags import xiaohongshu_video_publish_enabled
from ..publish_task import PublishErrorCode, PublishResult
from ..publisher_factory import PublisherFactory

logger = logging.getLogger(__name__)


@PublisherFactory.register("xiaohongshu")
class XiaohongshuPublisher(BasePublisher):
    """小红书图文笔记发布器"""

    PLATFORM_NAME = "xiaohongshu"
    PLATFORM_CN_NAME = "小红书"
    LOGIN_COOKIE_KEY = "web_session"
    LOGIN_CHECK_URL = "https://creator.xiaohongshu.com/"
    PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=image"
    VIDEO_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=video"
    MANAGE_URL = "https://creator.xiaohongshu.com/publish/manage"
    LOGIN_REDIRECT_KEYWORD = "login"

    SUPPORTS_IMAGE = True
    SUPPORTS_VIDEO = True
    MIN_IMAGES = 1  # 小红书必须至少 1 张图片

    async def _check_login(self) -> bool:
        """覆盖默认登录检测：URL + 页面内容双重检查

        小红书登录失效时 URL 会包含 login，且页面内容较短并包含登录表单。
        """
        if not self.page:
            return False
        try:
            await self.page.goto(
                self.LOGIN_CHECK_URL,
                timeout=30000,
                wait_until="domcontentloaded",
            )
            await asyncio.sleep(5)

            current_url = self.page.url
            page_content = await self.page.content()

            is_login_url = "login" in current_url.lower()
            is_short_page = len(page_content) < 10000
            has_login_form = any(
                kw in page_content
                for kw in ["密码登录", "手机号登录", "验证码登录"]
            )

            if is_login_url or (is_short_page and has_login_form):
                logger.warning(
                    f"[XhsAuto] 检测到登录页: URL={current_url}, "
                    f"short_page={is_short_page}, login_form={has_login_form}"
                )
                return False

            # cookie 兜底
            cookies = await self.context.cookies()
            has_web_session = any(c.get("name") == "web_session" for c in cookies)
            return has_web_session
        except Exception as e:
            logger.error(f"[XhsAuto] 检查登录失败: {e}")
            return False

    async def _do_publish(
        self,
        title: str,
        content: str,
        images: List[str],
        video_path: Optional[str],
        **kwargs,
    ) -> PublishResult:
        """发布小红书笔记

        小红书的 Vue 富文本编辑器较难直接定位，采用 JavaScript + 传统 selector 双路策略。
        """
        debug_info: List[str] = []
        keywords: List[str] = kwargs.get("keywords", [])

        # 1. 等待 Vue 组件初始化
        debug_info.append("⏱️ 等待 Vue 组件初始化...")
        await asyncio.sleep(5)

        # 2. 视频或三路图片上传
        if video_path:
            if not xiaohongshu_video_publish_enabled():
                return PublishResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error="小红书视频发布能力未开启",
                    error_code=PublishErrorCode.INVALID_MEDIA.value,
                    debug_info=debug_info,
                    retryable=False,
                )
            upload_success = await self._upload_video(video_path, debug_info)
        else:
            upload_success = await self._upload_images(images, debug_info)
        if not upload_success:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=f"小红书{'视频' if video_path else '图片'}上传失败",
                error_code=PublishErrorCode.UPLOAD_FAILED.value,
                debug_info=debug_info,
                retryable=True,
            )
        debug_info.append(f"✅ {'视频' if video_path else '图片'}上传完成")

        cover_path = kwargs.get("cover_path")
        if video_path and cover_path:
            await self._apply_cover(cover_path, debug_info)

        # 3. 等待表单元素加载（小红书新版：上传图片后才显示表单）
        await self._wait_form_loaded(debug_info)

        # 4. 格式化内容（追加话题标签）
        formatted_content = content
        if keywords:
            tags = " ".join([f"#{kw}#" for kw in keywords[:5]])
            formatted_content = f"{content}\n\n{tags}"

        # 5. 填写标题（JavaScript + 传统 selector 双路）
        title_filled = await self._fill_title(title[:20], debug_info)
        if not title_filled:
            debug_info.append("⚠️ 标题未填写成功（继续尝试）")

        await asyncio.sleep(1)

        # 6. 填写正文
        content_filled = await self._fill_content(formatted_content[:1000], debug_info)
        if not content_filled:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error="未找到正文输入框",
                debug_info=debug_info,
            )

        await asyncio.sleep(2)

        await self._apply_publish_settings(kwargs, debug_info)

        # 7. 点击发布按钮
        publish_clicked = await self._click_publish(debug_info)
        if not publish_clicked:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error="未找到发布按钮",
                debug_info=debug_info,
            )

        await asyncio.sleep(5)

        # 8. 业务错误检测
        biz_error = await self._detect_biz_error()
        if biz_error:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=biz_error,
                debug_info=debug_info + [f"❌ {biz_error}"],
                retryable=False,
            )

        # 9. 二次确认：成功提示或作品/管理页跳转至少命中一项
        confirmed, note_url, note_id = await self._confirm_publish_success(
            url_markers=["/explore/", "/discovery/item/"],
            success_markers=["发布成功", "提交成功", "审核中", "发布完成"],
        )
        if not note_url:
            compensated, compensated_url, compensated_id = await self._query_recent_published_post(
                manage_url=self.MANAGE_URL,
                link_selector='a[href*="/explore/"], a[href*="/discovery/item/"]',
                title=title,
            )
            if compensated:
                confirmed, note_url, note_id = True, compensated_url, compensated_id
                debug_info.append("✅ 已通过作品管理页补偿查询确认发布")
        if not confirmed:
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error="小红书发布结果未通过二次确认",
                error_code=PublishErrorCode.UNKNOWN.value,
                debug_info=debug_info,
                retryable=False,
            )

        media_name = "视频" if video_path else "图文"
        debug_info.append(f"✅ 小红书{media_name}发布已二次确认")
        return PublishResult(
            success=True,
            platform=self.PLATFORM_NAME,
            message=f"小红书{media_name}笔记发布成功",
            post_url=note_url,
            post_id=note_id,
            status="已发布",
            debug_info=debug_info,
        )

    # ==================== 内部辅助方法 ====================

    def _get_publish_url(self, video_path: Optional[str]) -> str:
        return self.VIDEO_PUBLISH_URL if video_path else self.PUBLISH_URL

    async def _upload_video(self, video_path: str, debug_info: List[str]) -> bool:
        for selector in ['input[type="file"][accept*="video"]', 'input[type="file"]']:
            try:
                upload_input = self.page.locator(selector).first
                if await upload_input.count() > 0:
                    await upload_input.set_input_files(video_path)
                    debug_info.append(f"✅ 视频已提交上传: {os.path.basename(video_path)}")
                    for _ in range(15):
                        page_text = str(await self.page.evaluate(
                            '() => document.body.innerText.slice(0, 2000)'
                        ) or "")
                        if any(marker in page_text for marker in ["上传成功", "重新上传", "视频封面"]):
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

    async def _upload_images(self, images: List[str], debug_info: List[str]) -> bool:
        """三路图片上传：filechooser → set_input_files → JavaScript"""
        valid_images = [img for img in images if img and os.path.exists(img)]
        if not valid_images:
            debug_info.append("⚠️ 没有有效的图片文件")
            return False

        # 方式 1: filechooser 事件
        try:
            async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                await self.page.click('button:has-text("上传图片")', timeout=5000)
            file_chooser = await fc_info.value
            await file_chooser.set_files(valid_images)
            debug_info.append("✅ filechooser 方式上传成功")
            await asyncio.sleep(5)
            return True
        except Exception as e:
            debug_info.append(f"⚠️ filechooser 方式失败: {e}")

        # 方式 2: 直接找 file input
        try:
            upload_input = await self.page.wait_for_selector(
                'input[type="file"]', state="attached", timeout=10000
            )
            if upload_input:
                await upload_input.set_input_files(valid_images)
                debug_info.append("✅ set_input_files 方式上传成功")
                await asyncio.sleep(5)
                return True
        except Exception as e:
            debug_info.append(f"⚠️ set_input_files 方式失败: {e}")

        # 方式 3: JavaScript 触发
        try:
            import base64

            with open(valid_images[0], "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")

            result = await self.page.evaluate(
                """async (imgData) => {
                    let input = document.querySelector('input[type="file"]');
                    if (!input) return { success: false, message: 'No file input found' };
                    input.click();
                    const byteCharacters = atob(imgData);
                    const byteArrays = [];
                    for (let i = 0; i < byteCharacters.length; i++) {
                        byteArrays.push(byteCharacters.charCodeAt(i));
                    }
                    const blob = new Blob([new Uint8Array(byteArrays)], { type: 'image/jpeg' });
                    const file = new File([blob], 'image.jpg', { type: 'image/jpeg' });
                    const dataTransfer = new DataTransfer();
                    dataTransfer.items.add(file);
                    input.files = dataTransfer.files;
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    return { success: true, message: 'JavaScript upload triggered' };
                }""",
                img_data,
            )
            if result and result.get("success"):
                debug_info.append("✅ JavaScript 方式上传成功")
                await asyncio.sleep(5)
                return True
            debug_info.append(f"⚠️ JavaScript 方式失败: {result}")
        except Exception as e:
            debug_info.append(f"⚠️ JavaScript 方式失败: {e}")

        return False

    async def _wait_form_loaded(self, debug_info: List[str]):
        """等待表单元素加载（小红书上传图片后才显示表单）"""
        max_wait = 15
        for attempt in range(max_wait):
            try:
                form_check = await self.page.evaluate(
                    """() => {
                        const inputs = document.querySelectorAll('input, textarea, [contenteditable]');
                        const bodyText = document.body.innerText;
                        return {
                            inputCount: inputs.length,
                            hasImageEditor: bodyText.includes('图片编辑'),
                            hasForm: bodyText.includes('填写标题'),
                        };
                    }"""
                )
                if form_check.get("hasImageEditor") and form_check.get("inputCount", 0) > 0:
                    debug_info.append("✅ 表单元素已加载")
                    return
                await asyncio.sleep(2)
            except Exception:
                await asyncio.sleep(2)
        debug_info.append("⚠️ 表单元素加载超时（继续尝试填写）")

    async def _fill_title(self, title: str, debug_info: List[str]) -> bool:
        """JavaScript + 传统 selector 双路填写标题"""
        # 方式 1: JavaScript
        try:
            result = await self.page.evaluate(
                """(titleText) => {
                    let titleInput = document.querySelector('input[placeholder*="标题"]:not([type="file"])')
                        || document.querySelector('textarea[placeholder*="标题"]')
                        || document.querySelector('.title-input')
                        || document.querySelector('.publish-title input:not([type="file"])')
                        || document.querySelector('input[maxlength]:not([type="file"])');
                    if (titleInput) {
                        titleInput.focus();
                        titleInput.click();
                        titleInput.value = titleText;
                        titleInput.dispatchEvent(new Event('input', { bubbles: true }));
                        titleInput.dispatchEvent(new Event('change', { bubbles: true }));
                        titleInput.blur();
                        return { success: true };
                    }
                    return { success: false };
                }""",
                title,
            )
            if result and result.get("success"):
                debug_info.append("✅ JavaScript 填写标题成功")
                return True
        except Exception as e:
            debug_info.append(f"⚠️ JavaScript 填写标题失败: {e}")

        # 方式 2: 传统 selector
        for selector in [
            'input[placeholder*="标题"]',
            'textarea[placeholder*="标题"]',
            ".title-input",
            ".publish-title input",
            "input[maxlength]",
        ]:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.fill(title)
                    debug_info.append(f"✅ 传统方式填写标题成功（{selector}）")
                    return True
            except Exception:
                continue
        return False

    async def _fill_content(self, content: str, debug_info: List[str]) -> bool:
        """JavaScript + 传统 selector 双路填写正文"""
        # 方式 1: JavaScript
        try:
            result = await self.page.evaluate(
                """(contentText) => {
                    let contentInput = document.querySelector('div[contenteditable="true"]')
                        || document.querySelector('textarea[placeholder*="正文"]')
                        || document.querySelector('textarea[placeholder*="描述"]')
                        || document.querySelector('textarea');
                    if (contentInput) {
                        contentInput.focus();
                        contentInput.click();
                        if (contentInput.tagName === 'DIV' || contentInput.isContentEditable) {
                            contentInput.innerText = contentText;
                            contentInput.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: contentText }));
                        } else {
                            contentInput.value = contentText;
                            contentInput.dispatchEvent(new Event('input', { bubbles: true }));
                            contentInput.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        return { success: true };
                    }
                    return { success: false };
                }""",
                content,
            )
            if result and result.get("success"):
                debug_info.append("✅ JavaScript 填写正文成功")
                return True
        except Exception as e:
            debug_info.append(f"⚠️ JavaScript 填写正文失败: {e}")

        # 方式 2: 传统 selector
        for selector in [
            'div[contenteditable="true"]',
            'textarea[placeholder*="正文"]',
            'textarea[placeholder*="描述"]',
            "textarea",
        ]:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click()
                    await self.page.keyboard.type(content, delay=10)
                    debug_info.append(f"✅ 传统方式填写正文成功（{selector}）")
                    return True
            except Exception:
                continue
        return False

    async def _click_publish(self, debug_info: List[str]) -> bool:
        """点击发布按钮"""
        for selector in [
            'button:has-text("发布")',
            'button.publish-btn',
            'button[type="submit"]:has-text("发布")',
            ".submit-btn",
        ]:
            try:
                btn = self.page.locator(selector).first
                if await btn.count() > 0 and await btn.is_enabled():
                    await btn.click(timeout=5000)
                    debug_info.append("✅ 已点击发布按钮")
                    return True
            except Exception:
                continue
        return False

    async def _extract_note_url(self) -> Optional[str]:
        """提取发布后的笔记链接（如果跳转）"""
        try:
            current_url = self.page.url
            if "/explore/" in current_url or "/discovery/item/" in current_url:
                return current_url
        except Exception:
            pass
        return None

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        """小红书单 cookie 值（web_session）转 Playwright cookie 列表"""
        return [
            {
                "name": "web_session",
                "value": cookie_value,
                "domain": ".xiaohongshu.com",
                "path": "/",
                "secure": True,
                "sameSite": "None",
            }
        ]
