"""
知乎自动发布模块
参考 xiaohongshu_automation.py 的架构
支持知乎专栏文章发布（含封面图上传）
"""

import asyncio
import json
import logging
import os
from typing import Optional

from playwright.async_api import async_playwright

from stealth_browser import launch_stealth_browser, create_stealth_context

logger = logging.getLogger(__name__)


def _state_path(user_id: int) -> str:
    state_dir = os.environ.get('PLATFORM_STATE_DIR', '/app/data/platform_state')
    return os.path.join(state_dir, f'zhihu_user_{user_id}.json')


class ZhihuAutomation:
    """知乎自动发布器"""

    def __init__(self, cookies: str, user_id: int = None):
        self.cookies_raw = cookies
        self.user_id = user_id
        self.storage_state = None
        if user_id is not None:
            state_path = _state_path(user_id)
            if os.path.exists(state_path):
                try:
                    with open(state_path, 'r', encoding='utf-8') as f:
                        self.storage_state = json.load(f)
                    logger.info(f"[ZhihuAuto] 用户 {user_id} 已加载 storage_state")
                except Exception as e:
                    logger.warning(f"[ZhihuAuto] 加载 storage_state 失败: {e}")

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def _parse_cookies(self) -> list:
        """解析 cookies 字符串为 Playwright cookie 列表"""
        try:
            cl = json.loads(self.cookies_raw) if isinstance(self.cookies_raw, str) else self.cookies_raw
            if isinstance(cl, list):
                return cl
        except Exception:
            pass
        return []

    async def _init_browser(self) -> bool:
        try:
            self.playwright = await async_playwright().start()
            self.browser = await launch_stealth_browser(self.playwright)

            # 优先用 storage_state
            if self.storage_state:
                self.context = await create_stealth_context(
                    self.browser, storage_state=self.storage_state
                )
            else:
                self.context = await create_stealth_context(self.browser)
                cookie_list = self._parse_cookies()
                if cookie_list:
                    await self.context.add_cookies(cookie_list)

            self.page = await self.context.new_page()
            return True
        except Exception as e:
            logger.error(f"[ZhihuAuto] 初始化浏览器失败: {e}")
            return False

    async def _check_login(self) -> bool:
        """检查是否已登录知乎"""
        try:
            await self.page.goto('https://www.zhihu.com/', timeout=20000, wait_until='domcontentloaded')
            await asyncio.sleep(2)
            url = self.page.url
            if 'signin' in url.lower():
                return False

            # 检查页面是否有登录后的元素
            try:
                # 登录后会显示头像按钮
                avatar = await self.page.query_selector('img.Avatar, [class*="Avatar"]')
                if avatar:
                    return True
            except Exception:
                pass

            # 检查 cookie z_c0
            cookies = await self.context.cookies()
            has_z_c0 = any(c.get('name') == 'z_c0' for c in cookies)
            return has_z_c0
        except Exception as e:
            logger.error(f"[ZhihuAuto] 检查登录失败: {e}")
            return False

    async def publish_article(
        self,
        title: str,
        content: str,
        image_path: Optional[str] = None,
        topic: Optional[str] = None
    ) -> dict:
        """发布知乎专栏文章"""
        debug_info = []

        try:
            if not await self._init_browser():
                return {'success': False, 'error': '浏览器初始化失败', 'debug_info': debug_info}

            # 检查登录
            if not await self._check_login():
                debug_info.append('未登录或登录已失效')
                return {'success': False, 'error': '知乎登录已失效，请重新扫码登录', 'debug_info': debug_info}

            debug_info.append('✅ 登录状态正常')

            # 访问写作页
            logger.info("[ZhihuAuto] 访问知乎写作页...")
            await self.page.goto('https://zhuanlan.zhihu.com/write', timeout=20000, wait_until='domcontentloaded')
            await asyncio.sleep(3)

            # 检测是否真的进入了写作页
            current_url = self.page.url
            if 'signin' in current_url.lower() or 'write' not in current_url.lower():
                debug_info.append(f'写作页访问失败，URL: {current_url}')
                return {'success': False, 'error': '无法进入知乎写作页（可能登录已失效）', 'debug_info': debug_info}

            # 填写标题
            title_filled = False
            for selector in [
                'textarea.PostIndex-titleInput',
                'textarea[placeholder*="标题"]',
                'input.PostIndex-titleInput',
                '.WriteIndex-titleInput textarea',
                '.WriteIndex-titleInput input'
            ]:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        await el.fill(title)
                        title_filled = True
                        debug_info.append(f'✅ 标题已填写（{selector}）')
                        break
                except Exception:
                    continue

            if not title_filled:
                debug_info.append('❌ 未找到标题输入框')
                return {'success': False, 'error': '未找到标题输入框', 'debug_info': debug_info}

            # 填写正文
            content_filled = False
            for selector in [
                'div.PublicDraftEditor-content',
                'div[contenteditable="true"]',
                '.ProseMirror',
                'textarea.PostIndex-contentInput'
            ]:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        # 知乎编辑器是富文本，用 keyboard.type 输入
                        await self.page.keyboard.type(content, delay=10)
                        content_filled = True
                        debug_info.append(f'✅ 正文已填写（{selector}）')
                        break
                except Exception as e:
                    debug_info.append(f'填写正文失败 ({selector}): {e}')
                    continue

            if not content_filled:
                debug_info.append('❌ 未找到正文输入框')
                return {'success': False, 'error': '未找到正文输入框', 'debug_info': debug_info}

            await asyncio.sleep(2)

            # 上传封面图（如果有）
            if image_path and os.path.exists(image_path):
                try:
                    # 知乎专栏文章有"上传封面"按钮
                    upload_selectors = [
                        'button:has-text("上传封面")',
                        'input[type="file"][accept*="image"]',
                        '.ColumnWriteBundle-coverUploader',
                        '.UploadPicture button'
                    ]
                    for selector in upload_selectors:
                        try:
                            if 'input[type="file"]' in selector:
                                el = self.page.locator(selector).first
                                if await el.count() > 0:
                                    await el.set_input_files(image_path)
                                    debug_info.append('✅ 封面图已上传')
                                    await asyncio.sleep(3)
                                    break
                            else:
                                btn = self.page.locator(selector).first
                                if await btn.count() > 0:
                                    await btn.click(timeout=3000)
                                    await asyncio.sleep(1)
                                    # 然后找 file input
                                    file_input = self.page.locator('input[type="file"][accept*="image"]').first
                                    if await file_input.count() > 0:
                                        await file_input.set_input_files(image_path)
                                        debug_info.append('✅ 封面图已上传')
                                        await asyncio.sleep(3)
                                        break
                        except Exception:
                            continue
                except Exception as e:
                    debug_info.append(f'⚠️ 封面图上传失败: {e}')

            # 添加话题（可选）
            if topic:
                try:
                    topic_btn = self.page.locator('button:has-text("添加话题"), .TopicSelectButton').first
                    if await topic_btn.count() > 0:
                        await topic_btn.click(timeout=3000)
                        await asyncio.sleep(1)
                        topic_input = self.page.locator('input[placeholder*="话题"], input[placeholder*="搜索"]').first
                        if await topic_input.count() > 0:
                            await topic_input.fill(topic)
                            await asyncio.sleep(2)
                            # 选第一个搜索结果
                            first_topic = self.page.locator('.TopicSelectItem, .TopicMenuItem').first
                            if await first_topic.count() > 0:
                                await first_topic.click(timeout=3000)
                                debug_info.append(f'✅ 话题已添加: {topic}')
                except Exception as e:
                    debug_info.append(f'⚠️ 话题添加失败: {e}')

            # 发布文章
            publish_clicked = False
            for selector in [
                'button:has-text("发布")',
                'button.PublishIndex-publishButton',
                'button[type="submit"]:has-text("发布")'
            ]:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_enabled():
                        await btn.click(timeout=5000)
                        publish_clicked = True
                        debug_info.append(f'✅ 已点击发布按钮（{selector}）')
                        break
                except Exception:
                    continue

            if not publish_clicked:
                debug_info.append('❌ 未找到发布按钮')
                return {'success': False, 'error': '未找到发布按钮', 'debug_info': debug_info}

            # 等待发布结果
            await asyncio.sleep(5)

            # 检查发布结果
            current_url = self.page.url
            page_content = await self.page.content()
            page_text = await self.page.evaluate('() => document.body.innerText.slice(0, 1000)')

            # 知乎业务错误检测（参考小红书的修复）
            biz_error_indicators = [
                '频次过高', '验证码', '账号异常', '限制',
                '违规', '请稍后再试', '发布失败'
            ]
            has_biz_error = any(indicator in page_text for indicator in biz_error_indicators)

            if has_biz_error:
                error_msg = '知乎拒绝发布'
                for indicator in biz_error_indicators:
                    if indicator in page_text:
                        error_msg = f'知乎业务错误: {indicator}'
                        break
                logger.error(f"[ZhihuAuto] {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'debug_info': debug_info + [f'❌ {error_msg}']
                }

            # 成功标志：URL 跳转到 /p/{id}
            success_indicators = ['/p/', '专栏文章', '已发布']
            is_success = any(indicator in current_url for indicator in success_indicators) or \
                         '/write' not in current_url

            if is_success:
                # 提取文章 URL
                article_url = current_url if '/p/' in current_url else None
                debug_info.append(f'✅ 发布成功，URL: {current_url}')

                # 持久化新的 storage_state
                await self._persist_state()

                return {
                    'success': True,
                    'platform': 'zhihu',
                    'message': '知乎专栏文章发布成功',
                    'article_url': article_url,
                    'status': '已发布',
                    'debug_info': debug_info
                }

            debug_info.append(f'⚠️ 发布状态不确定，URL: {current_url}')
            return {
                'success': False,
                'error': '发布状态不确定',
                'debug_info': debug_info
            }

        except Exception as e:
            logger.error(f"[ZhihuAuto] 发布异常: {e}")
            return {'success': False, 'error': f'发布异常: {e}', 'debug_info': debug_info}
        finally:
            await self._close_browser()

    async def _persist_state(self):
        """持久化 storage_state"""
        if not self.user_id or not self.context:
            return
        try:
            state = await self.context.storage_state()
            state_path = _state_path(self.user_id)
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False)
            logger.info(f"[ZhihuAuto] storage_state 已更新到 {state_path}")
        except Exception as e:
            logger.warning(f"[ZhihuAuto] 更新 storage_state 失败: {e}")

    async def _close_browser(self):
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        finally:
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None
