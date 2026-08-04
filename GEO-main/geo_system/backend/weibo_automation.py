"""
微博自动发布模块
支持微博图文发布
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
    return os.path.join(state_dir, f'weibo_user_{user_id}.json')


class WeiboAutomation:
    """微博自动发布器"""

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
                    logger.info(f"[WeiboAuto] 用户 {user_id} 已加载 storage_state")
                except Exception as e:
                    logger.warning(f"[WeiboAuto] 加载 storage_state 失败: {e}")

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
            logger.error(f"[WeiboAuto] 初始化浏览器失败: {e}")
            return False

    async def _check_login(self) -> bool:
        try:
            await self.page.goto('https://weibo.com/', timeout=20000, wait_until='domcontentloaded')
            await asyncio.sleep(3)
            url = self.page.url
            if 'passport.weibo' in url or 'signin' in url.lower():
                return False

            # 检查 SUB cookie
            cookies = await self.context.cookies()
            has_sub = any(c.get('name') == 'SUB' for c in cookies)
            return has_sub
        except Exception as e:
            logger.error(f"[WeiboAuto] 检查登录失败: {e}")
            return False

    async def publish_post(
        self,
        content: str,
        image_paths: Optional[list] = None,
        title: Optional[str] = None
    ) -> dict:
        """发布微博（图文）"""
        debug_info = []

        try:
            if not await self._init_browser():
                return {'success': False, 'error': '浏览器初始化失败', 'debug_info': debug_info}

            if not await self._check_login():
                debug_info.append('未登录或登录已失效')
                return {'success': False, 'error': '微博登录已失效，请重新扫码登录', 'debug_info': debug_info}

            debug_info.append('✅ 登录状态正常')

            # 微博首页就有发布框
            logger.info("[WeiboAuto] 在微博首页发布...")
            current_url = self.page.url

            # 找到微博正文输入框
            content_filled = False
            for selector in [
                'textarea.WB_textarea',
                'textarea[placeholder*="有什么新鲜事"]',
                'div[contenteditable="true"]',
                '.Form_input textarea',
                'textarea.Boxs_textarea'
            ]:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        await el.click()
                        await asyncio.sleep(1)
                        await self.page.keyboard.type(content, delay=10)
                        content_filled = True
                        debug_info.append(f'✅ 正文已填写（{selector}）')
                        break
                except Exception:
                    continue

            if not content_filled:
                debug_info.append('❌ 未找到微博正文输入框')
                return {'success': False, 'error': '未找到微博正文输入框', 'debug_info': debug_info}

            await asyncio.sleep(1)

            # 上传图片
            if image_paths:
                for img_path in image_paths:
                    if not os.path.exists(img_path):
                        continue
                    try:
                        file_input = self.page.locator('input[type="file"][accept*="image"]').first
                        if await file_input.count() > 0:
                            await file_input.set_input_files(img_path)
                            debug_info.append(f'✅ 图片已上传: {os.path.basename(img_path)}')
                            await asyncio.sleep(3)
                    except Exception as e:
                        debug_info.append(f'⚠️ 图片上传失败: {e}')

            await asyncio.sleep(2)

            # 点击发布按钮
            publish_clicked = False
            for selector in [
                'a:has-text("发布")',
                'button:has-text("发布")',
                'a.WB_btn_release',
                '.Form_btn a'
            ]:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.count() > 0:
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

            # 检查发布结果
            page_text = await self.page.evaluate('() => document.body.innerText.slice(0, 1000)')

            biz_error_indicators = [
                '频次过高', '验证码', '账号异常', '限制',
                '违规', '请稍后再试', '发布失败', '内容过长'
            ]
            has_biz_error = any(indicator in page_text for indicator in biz_error_indicators)

            if has_biz_error:
                error_msg = '微博拒绝发布'
                for indicator in biz_error_indicators:
                    if indicator in page_text:
                        error_msg = f'微博业务错误: {indicator}'
                        break
                logger.error(f"[WeiboAuto] {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'debug_info': debug_info + [f'❌ {error_msg}']
                }

            await self._persist_state()

            debug_info.append('✅ 微博发布成功')
            return {
                'success': True,
                'platform': 'weibo',
                'message': '微博发布成功',
                'status': '已发布',
                'debug_info': debug_info
            }

        except Exception as e:
            logger.error(f"[WeiboAuto] 发布异常: {e}")
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
            logger.info(f"[WeiboAuto] storage_state 已更新到 {state_path}")
        except Exception as e:
            logger.warning(f"[WeiboAuto] 更新 storage_state 失败: {e}")

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
