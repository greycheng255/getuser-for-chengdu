"""
微博二维码登录模块
参考 xiaohongshu_qr_login.py 的架构
"""

import asyncio
import base64
import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Dict

from playwright.async_api import async_playwright

from stealth_browser import launch_stealth_browser, create_stealth_context

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

login_sessions: Dict[str, dict] = {}

_loop = None
_loop_lock = threading.Lock()


def _get_loop():
    global _loop
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        _loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(_loop)
            try:
                _loop.run_forever()
            except Exception as e:
                logger.error(f"[WeiboQR] 全局事件循环异常: {e}")

        t = threading.Thread(target=_run_loop, daemon=True, name="weibo-qr-loop")
        t.start()
        logger.info("[WeiboQR] 全局事件循环已启动")
        return _loop


def run_async(coro, timeout=60):
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def _state_path(user_id: int) -> str:
    state_dir = os.environ.get('PLATFORM_STATE_DIR', '/app/data/platform_state')
    os.makedirs(state_dir, exist_ok=True)
    return os.path.join(state_dir, f'weibo_user_{user_id}.json')


class WeiboQRLogin:
    """微博二维码登录管理器"""

    def __init__(self):
        self.playwright = None
        self.browser = None

    async def init_browser(self):
        try:
            self.playwright = await async_playwright().start()
            self.browser = await launch_stealth_browser(self.playwright)
            return True
        except Exception as e:
            logger.error(f"[WeiboQR] 初始化浏览器失败: {e}")
            return False

    async def start_qr_login(self, session_id: str) -> Dict:
        try:
            logger.info(f"[WeiboQR] 开始二维码登录，会话ID: {session_id}")

            if not await self.init_browser():
                return {'success': False, 'error': '浏览器初始化失败'}

            context = await create_stealth_context(self.browser)
            page = await context.new_page()

            # 访问微博登录页
            logger.info("[WeiboQR] 访问微博登录页面...")
            await page.goto('https://passport.weibo.com/sso/signin', timeout=30000, wait_until='domcontentloaded')
            await asyncio.sleep(2)

            # 切换到扫码登录 tab（微博默认可能是账号密码）
            for selector in [
                'a:has-text("扫码登录")',
                'li:has-text("扫码登录")',
                '.LoginFunc_qrcode',
                '[class*="qrcode"]:has-text("扫码")'
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        await el.click(timeout=3000)
                        logger.info(f"[WeiboQR] 点击扫码登录 tab: {selector}")
                        break
                except Exception:
                    continue

            await asyncio.sleep(2)

            # 获取二维码
            qr_src = None
            for selector in [
                'img[src*="qrcode"]',
                'img.QRCode_img',
                'img[alt*="二维码"]',
                'canvas.QRCode',
                '.qrcode img',
                'img[class*="qrcode" i]'
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        if 'canvas' in selector:
                            qr_src = await page.evaluate('''() => {
                                const canvas = document.querySelector('canvas.QRCode');
                                if (canvas) return canvas.toDataURL('image/png');
                                return null;
                            }''')
                        else:
                            qr_src = await el.get_attribute('src')
                        if qr_src:
                            logger.info(f"[WeiboQR] 获取到二维码，selector={selector}")
                            break
                except Exception:
                    continue

            if not qr_src:
                # 兜底：截图
                try:
                    qr_container = page.locator('.QRCode, .qrcode, .LoginFunc_qrcode').first
                    if await qr_container.count() > 0:
                        screenshot = await qr_container.screenshot()
                        qr_src = 'data:image/png;base64,' + base64.b64encode(screenshot).decode()
                        logger.info("[WeiboQR] 使用截图作为二维码")
                except Exception as e:
                    logger.error(f"[WeiboQR] 截图失败: {e}")

            if not qr_src:
                await self._cleanup_session(session_id)
                return {'success': False, 'error': '未找到二维码，请稍后重试'}

            login_sessions[session_id] = {
                'context': context,
                'page': page,
                'status': 'waiting',
                'created_at': datetime.now(),
                'qr_src': qr_src,
                'cookies': None,
                'state_path': None
            }

            loop = _get_loop()
            asyncio.run_coroutine_threadsafe(self._check_login_status(session_id), loop)
            logger.info(f"[WeiboQR] 后台任务已调度，session_id={session_id}")

            return {
                'success': True,
                'session_id': session_id,
                'qr_image': qr_src
            }

        except Exception as e:
            logger.error(f"[WeiboQR] 启动登录失败: {e}")
            return {'success': False, 'error': str(e)}

    async def _check_login_status(self, session_id: str):
        session = login_sessions.get(session_id)
        if not session:
            return

        page = session['page']
        context = session['context']
        waited = 0
        timeout = 300

        try:
            while waited < timeout:
                if session.get('status') in ['cancelled', 'need_verification']:
                    return

                try:
                    current_url = page.url or ''

                    if await self._detect_verification_page(page):
                        session['status'] = 'need_verification'
                        logger.info(f"[WeiboQR] 会话 {session_id} 进入验证码阶段")
                        return

                    # 登录成功：URL 跳转到 weibo.com
                    if 'passport.weibo' not in current_url and ('weibo.com' in current_url or 'd.weibo.com' in current_url):
                        logger.info(f"[WeiboQR] 会话 {session_id} 登录成功，URL: {current_url}")
                        break

                    await asyncio.sleep(2)
                    waited += 2

                except Exception as e:
                    logger.error(f"[WeiboQR] 检测状态出错: {e}")
                    await asyncio.sleep(2)
                    waited += 2

            current_url = page.url or ''
            if 'passport.weibo' not in current_url and 'weibo.com' in current_url:
                logger.info(f"[WeiboQR] 处理登录成功流程，URL: {current_url}")
                await asyncio.sleep(3)

                # 访问微博主页
                try:
                    await page.goto('https://weibo.com/', timeout=15000, wait_until='domcontentloaded')
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"[WeiboQR] 访问微博主页失败（继续）: {e}")

                # 访问发布页
                try:
                    await page.goto('https://weibo.com/', timeout=15000, wait_until='domcontentloaded')
                    await asyncio.sleep(2)
                except Exception:
                    pass

                cookies = await context.cookies()
                logger.info(f"[WeiboQR] 获取到 {len(cookies)} 个 Cookie")

                key_cookies = ['SUB', 'SUBP', 'SSOLoginState', 'ALF']
                found_keys = [c.get('name') for c in cookies if c.get('name') in key_cookies]
                logger.info(f"[WeiboQR] 关键 Cookie: {found_keys}")

                has_sub = any(c.get('name') == 'SUB' for c in cookies)
                logger.info(f"[WeiboQR] SUB 认证 Token: {'已获取' if has_sub else '未获取'}")

                state_path = None
                try:
                    state = await context.storage_state()
                    state_path = _state_path(session.get('user_id', 0)) if session.get('user_id') else None
                    if state_path:
                        with open(state_path, 'w', encoding='utf-8') as f:
                            json.dump(state, f, ensure_ascii=False)
                        session['state_path'] = state_path
                        logger.info(f"[WeiboQR] storage_state 已保存到 {state_path}")
                except Exception as e:
                    logger.error(f"[WeiboQR] 保存 storage_state 失败: {e}")

                session['cookies'] = cookies
                session['status'] = 'success'
                await self._close_session(session_id)
                return

            logger.info(f"[WeiboQR] 会话 {session_id} 扫码超时")
            session['status'] = 'timeout'
            await self._close_session(session_id)

        except Exception as e:
            logger.error(f"[WeiboQR] 检测登录状态失败: {e}")
            session['status'] = 'error'
            session['error'] = str(e)
            await self._close_session(session_id)

    async def _detect_verification_page(self, page) -> bool:
        try:
            for selector in [
                'input[placeholder*="验证码"]',
                'input[placeholder*="code" i]',
                'img.BanVcode',
                '.Vcode',
                'input[name*="vcode" i]',
                'input[name*="code" i]'
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0 and await el.is_visible():
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    async def submit_verification_code(self, session_id: str, code: str) -> Dict:
        session = login_sessions.get(session_id)
        if not session:
            return {'success': False, 'error': '会话不存在'}

        page = session['page']
        try:
            for selector in [
                'input[placeholder*="验证码"]',
                'input[placeholder*="code" i]',
                'input[name*="vcode" i]',
                'input[name*="code" i]'
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0 and await el.is_visible():
                        await el.fill(code)
                        logger.info(f"[WeiboQR] 已填入验证码到 {selector}")

                        for btn_selector in [
                            'a:has-text("确定")',
                            'button:has-text("确定")',
                            'a:has-text("验证")',
                            'a.WB_btn_login'
                        ]:
                            try:
                                btn = page.locator(btn_selector).first
                                if await btn.count() > 0:
                                    await btn.click(timeout=3000)
                                    break
                            except Exception:
                                continue

                        await page.keyboard.press('Enter')
                        session['status'] = 'waiting'
                        logger.info(f"[WeiboQR] 会话 {session_id} 验证码已提交")
                        return {'success': True}
                except Exception:
                    continue

            return {'success': False, 'error': '未找到验证码输入框'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _close_session(self, session_id: str):
        session = login_sessions.get(session_id)
        if not session:
            return
        try:
            if session.get('context'):
                await session['context'].close()
            if session.get('browser') and self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass
            if self.playwright:
                try:
                    await self.playwright.stop()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[WeiboQR] 关闭会话失败: {e}")
        finally:
            self.playwright = None
            self.browser = None

    async def _cleanup_session(self, session_id: str):
        await self._close_session(session_id)
        login_sessions.pop(session_id, None)

    def get_login_status(self, session_id: str) -> Dict:
        session = login_sessions.get(session_id)
        if not session:
            return {'success': False, 'error': '会话不存在或已过期'}

        status = session.get('status')
        result = {
            'success': True,
            'status': status,
            'session_id': session_id
        }

        if status == 'success':
            cookies = session.get('cookies', [])
            result['cookies'] = cookies
            result['cookie_count'] = len(cookies)
            result['state_path'] = session.get('state_path')
            has_sub = any(c.get('name') == 'SUB' for c in cookies)
            result['has_sub'] = has_sub
        elif status == 'need_verification':
            result['message'] = '请输入验证码'
        elif status == 'timeout':
            result['message'] = '扫码超时，请重新获取二维码'
        elif status == 'error':
            result['message'] = session.get('error', '登录失败')

        return result

    async def cancel_login(self, session_id: str) -> Dict:
        session = login_sessions.get(session_id)
        if session:
            session['status'] = 'cancelled'
            await self._close_session(session_id)
            login_sessions.pop(session_id, None)
        return {'success': True}


weibo_qr_login_manager = WeiboQRLogin()
