"""
抖音自动发布模块
支持抖音图文笔记发布
"""

import asyncio
import json
import logging
import os
from typing import Optional, List

from playwright.async_api import async_playwright

from stealth_browser import launch_stealth_browser, create_stealth_context

logger = logging.getLogger(__name__)


def _state_path(user_id: int) -> str:
    state_dir = os.environ.get('PLATFORM_STATE_DIR', '/app/data/platform_state')
    return os.path.join(state_dir, f'douyin_user_{user_id}.json')


class DouyinAutomation:
    """抖音自动发布器"""

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
                    logger.info(f"[DouyinAuto] 用户 {user_id} 已加载 storage_state")
                except Exception as e:
                    logger.warning(f"[DouyinAuto] 加载 storage_state 失败: {e}")

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def _parse_cookies(self) -> list:
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
            logger.error(f"[DouyinAuto] 初始化浏览器失败: {e}")
            return False

    async def _check_login(self) -> bool:
        try:
            await self.page.goto('https://creator.douyin.com/', timeout=20000, wait_until='domcontentloaded')
            await asyncio.sleep(3)
            url = self.page.url
            if 'login' in url.lower():
                return False

            cookies = await self.context.cookies()
            has_sessionid = any(c.get('name') in ['sessionid', 'sessionid_ss'] for c in cookies)
            return has_sessionid
        except Exception as e:
            logger.error(f"[DouyinAuto] 检查登录失败: {e}")
            return False

    async def publish_post(
        self,
        content: str,
        image_paths: Optional[List[str]] = None,
        title: Optional[str] = None,
        video_path: Optional[str] = None
    ) -> dict:
        """发布抖音图文笔记"""
        debug_info = []

        try:
            if not await self._init_browser():
                return {'success': False, 'error': '浏览器初始化失败', 'debug_info': debug_info}

            if not await self._check_login():
                debug_info.append('未登录或登录已失效')
                return {'success': False, 'error': '抖音登录已失效，请重新扫码登录', 'debug_info': debug_info}

            debug_info.append('✅ 登录状态正常')

            # 访问抖音发布页（图文）
            logger.info("[DouyinAuto] 访问抖音图文发布页...")
            await self.page.goto('https://creator.douyin.com/creator-metrics/content-upload?default_type=image', timeout=20000, wait_until='domcontentloaded')
            await asyncio.sleep(3)

            current_url = self.page.url
            if 'login' in current_url.lower():
                debug_info.append('发布页跳回登录页，登录已失效')
                return {'success': False, 'error': '抖音登录已失效', 'debug_info': debug_info}

            # 上传图片（抖音图文必须先上传图片）
            if image_paths:
                uploaded_count = 0
                for img_path in image_paths:
                    if not os.path.exists(img_path):
                        continue
                    try:
                        file_input = self.page.locator('input[type="file"][accept*="image"]').first
                        if await file_input.count() > 0:
                            await file_input.set_input_files(img_path)
                            uploaded_count += 1
                            debug_info.append(f'✅ 图片已上传: {os.path.basename(img_path)}')
                            await asyncio.sleep(3)
                    except Exception as e:
                        debug_info.append(f'⚠️ 图片上传失败: {e}')

                if uploaded_count == 0:
                    debug_info.append('❌ 图片上传失败')
                    return {'success': False, 'error': '抖音图文必须上传至少1张图片', 'debug_info': debug_info}

            await asyncio.sleep(2)

            # 填写标题（可选）
            if title:
                for selector in [
                    'input[placeholder*="标题"]',
                    'input.title',
                    '.title-input input'
                ]:
                    try:
                        el = self.page.locator(selector).first
                        if await el.count() > 0:
                            await el.click()
                            await el.fill(title)
                            debug_info.append(f'✅ 标题已填写（{selector}）')
                            break
                    except Exception:
                        continue

            # 填写正文
            content_filled = False
            for selector in [
                'div[contenteditable="true"]',
                'textarea[placeholder*="描述"]',
                '.editor-container [contenteditable="true"]',
                'div.editor-content'
            ]:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        await self.page.keyboard.type(content, delay=10)
                        content_filled = True
                        debug_info.append(f'✅ 正文已填写（{selector}）')
                        break
                except Exception:
                    continue

            if not content_filled:
                debug_info.append('⚠️ 未找到正文输入框（继续尝试发布）')

            await asyncio.sleep(2)

            # 点击发布按钮
            publish_clicked = False
            for selector in [
                'button:has-text("发布")',
                'button.publish-btn',
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

            await asyncio.sleep(5)

            page_text = await self.page.evaluate('() => document.body.innerText.slice(0, 1000)')

            biz_error_indicators = [
                '频次过高', '验证码', '账号异常', '限制',
                '违规', '请稍后再试', '发布失败', '内容过长', '权限不足',
                '禁止发布', '风控'
            ]
            has_biz_error = any(indicator in page_text for indicator in biz_error_indicators)

            if has_biz_error:
                error_msg = '抖音拒绝发布'
                for indicator in biz_error_indicators:
                    if indicator in page_text:
                        error_msg = f'抖音业务错误: {indicator}'
                        break
                logger.error(f"[DouyinAuto] {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'debug_info': debug_info + [f'❌ {error_msg}']
                }

            await self._persist_state()

            debug_info.append('✅ 抖音图文发布成功')
            return {
                'success': True,
                'platform': 'douyin',
                'message': '抖音图文笔记发布成功',
                'status': '已发布',
                'debug_info': debug_info
            }

        except Exception as e:
            logger.error(f"[DouyinAuto] 发布异常: {e}")
            return {'success': False, 'error': f'发布异常: {e}', 'debug_info': debug_info}
        finally:
            await self._close_browser()

    async def _persist_state(self):
        if not self.user_id or not self.context:
            return
        try:
            state = await self.context.storage_state()
            state_path = _state_path(self.user_id)
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False)
            logger.info(f"[DouyinAuto] storage_state 已更新到 {state_path}")
        except Exception as e:
            logger.warning(f"[DouyinAuto] 更新 storage_state 失败: {e}")

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
