"""
知乎二维码登录模块
使用 Playwright 实现扫码登录流程，参考 xiaohongshu_qr_login.py 的架构
"""

import asyncio
import base64
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

from playwright.async_api import async_playwright

from stealth_browser import launch_stealth_browser, create_stealth_context

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 存储登录会话
login_sessions: Dict[str, dict] = {}

# ============== 全局事件循环管理 ==============
_loop = None
_loop_lock = threading.Lock()


def _get_loop():
    """获取（或创建）全局事件循环"""
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
                logger.error(f"[ZhihuQR] 全局事件循环异常: {e}")

        t = threading.Thread(target=_run_loop, daemon=True, name="zhihu-qr-loop")
        t.start()
        logger.info("[ZhihuQR] 全局事件循环已启动")
        return _loop


def run_async(coro, timeout=60):
    """在全局事件循环中运行协程，同步等待结果"""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def _state_path(user_id: int) -> str:
    """获取用户对应的 storage_state 文件路径"""
    state_dir = os.environ.get('PLATFORM_STATE_DIR', '/app/data/platform_state')
    os.makedirs(state_dir, exist_ok=True)
    return os.path.join(state_dir, f'zhihu_user_{user_id}.json')


class ZhihuQRLogin:
    """知乎二维码登录管理器"""

    def __init__(self):
        self.playwright = None
        self.browser = None

    async def init_browser(self):
        try:
            self.playwright = await async_playwright().start()
            self.browser = await launch_stealth_browser(self.playwright)
            return True
        except Exception as e:
            logger.error(f"[ZhihuQR] 初始化浏览器失败: {e}")
            return False

    async def start_qr_login(self, session_id: str) -> Dict:
        """启动二维码登录流程"""
        try:
            logger.info(f"[ZhihuQR] 开始二维码登录，会话ID: {session_id}")

            if not await self.init_browser():
                return {'success': False, 'error': '浏览器初始化失败'}

            context = await create_stealth_context(self.browser)
            page = await context.new_page()

            # 访问知乎登录页
            logger.info("[ZhihuQR] 访问知乎登录页面...")
            await page.goto('https://www.zhihu.com/signin', timeout=30000, wait_until='domcontentloaded')
            await asyncio.sleep(2)

            # 切换到扫码登录（知乎默认显示密码登录，需要点击扫码 tab）
            qr_tab_clicked = False
            for selector in [
                'text=扫码登录',
                'button:has-text("扫码")',
                '.QrcodeLogin-tab',
                '[role="tab"]:has-text("扫码")',
                'div:has-text("扫码登录"):not(:has(*))'
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        await el.click(timeout=3000)
                        qr_tab_clicked = True
                        logger.info(f"[ZhihuQR] 点击扫码登录 tab: {selector}")
                        break
                except Exception:
                    continue

            if not qr_tab_clicked:
                # 知乎可能直接显示二维码
                logger.info("[ZhihuQR] 未找到扫码 tab，尝试直接获取二维码")

            await asyncio.sleep(3)

            # 先打印页面 DOM 结构用于调试
            page_html = await page.content()
            with open('/tmp/zhihu_login.html', 'w', encoding='utf-8') as f:
                f.write(page_html[:8000])
            logger.info(f"[ZhihuQR] 页面 HTML 已保存到 /tmp/zhihu_login.html")

            # 获取二维码图片
            qr_src = None
            
            # 方法1: 查找 img 标签
            for selector in [
                'img[src*="qrcode"]',
                'img[src*="qr"]',
                'img[alt*="二维码"]',
                'img[alt*="扫码"]',
                'img.QrcodeLogin-image',
                'img.SignInQrcode-image',
                '.QrcodeLogin img',
                '.SignInQrcode img',
                '.qrcode-img',
                '.qr-img',
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        qr_src = await el.get_attribute('src')
                        if qr_src and ('http' in qr_src or 'data:' in qr_src):
                            logger.info(f"[ZhihuQR] 获取到二维码，selector={selector}, src长度={len(qr_src)}")
                            break
                except Exception:
                    continue

            # 方法2: 查找 canvas
            if not qr_src:
                for selector in [
                    'canvas.QrcodeLogin-canvas',
                    'canvas[class*="qrcode"]',
                    'canvas[class*="qr"]',
                    '.QrcodeLogin canvas',
                ]:
                    try:
                        el = page.locator(selector).first
                        if await el.count() > 0:
                            qr_src = await page.evaluate(f'''() => {{
                                const canvas = document.querySelector('{selector}');
                                if (canvas) return canvas.toDataURL('image/png');
                                return null;
                            }}''')
                            if qr_src:
                                logger.info(f"[ZhihuQR] canvas 获取到二维码，selector={selector}")
                                break
                    except Exception:
                        continue

            # 方法3: 查找页面中的 data-url 二维码（有些页面直接用 img src=data:...）
            if not qr_src:
                try:
                    qr_src = await page.evaluate('''() => {
                        const imgs = document.querySelectorAll('img');
                        for (const img of imgs) {
                            const src = img.getAttribute('src');
                            if (src && src.startsWith('data:image') && src.length > 500) {
                                return src;
                            }
                        }
                        return null;
                    }''')
                    if qr_src:
                        logger.info(f"[ZhihuQR] 通过 JS 获取到 data-url 二维码")
                except Exception:
                    pass

            # 方法4: 截图兜底
            if not qr_src:
                try:
                    qr_container = page.locator('.QrcodeLogin, .SignInQrcode, .SignContainer, .SignFlow-qrcode').first
                    if await qr_container.count() > 0:
                        qr_src = await qr_container.screenshot()
                        qr_src = 'data:image/png;base64,' + base64.b64encode(qr_src).decode()
                        logger.info("[ZhihuQR] 使用截图作为二维码")
                except Exception as e:
                    logger.error(f"[ZhihuQR] 截图失败: {e}")

            # 方法5: 截取整个页面
            if not qr_src:
                try:
                    screenshot = await page.screenshot(full_page=False)
                    qr_src = 'data:image/png;base64,' + base64.b64encode(screenshot).decode()
                    logger.info("[ZhihuQR] 使用页面截图作为二维码")
                except Exception as e:
                    logger.error(f"[ZhihuQR] 页面截图失败: {e}")

            if not qr_src:
                await self._cleanup_session(session_id)
                return {'success': False, 'error': '未找到二维码，请稍后重试'}

            # 保存会话
            login_sessions[session_id] = {
                'context': context,
                'page': page,
                'status': 'waiting',
                'created_at': datetime.now(),
                'qr_src': qr_src,
                'cookies': None,
                'state_path': None
            }

            # 启动后台检测任务
            loop = _get_loop()
            asyncio.run_coroutine_threadsafe(self._check_login_status(session_id), loop)
            logger.info(f"[ZhihuQR] 后台任务已调度，session_id={session_id}")

            return {
                'success': True,
                'session_id': session_id,
                'qr_image': qr_src
            }

        except Exception as e:
            logger.error(f"[ZhihuQR] 启动登录失败: {e}")
            return {'success': False, 'error': str(e)}

    async def _check_login_status(self, session_id: str):
        """后台检测登录状态"""
        session = login_sessions.get(session_id)
        if not session:
            return

        page = session['page']
        context = session['context']
        waited = 0
        timeout = 300  # 5 分钟

        try:
            while waited < timeout:
                if session.get('status') in ['cancelled', 'need_verification']:
                    return

                try:
                    current_url = page.url or ''

                    # 检测验证码页面
                    if await self._detect_verification_page(page):
                        session['status'] = 'need_verification'
                        logger.info(f"[ZhihuQR] 会话 {session_id} 进入验证码阶段")
                        return

                    # 登录成功：URL 离开 signin 页面
                    if 'signin' not in current_url.lower() and 'zhihu.com' in current_url:
                        logger.info(f"[ZhihuQR] 会话 {session_id} 登录成功，URL: {current_url}")
                        break

                    await asyncio.sleep(2)
                    waited += 2

                except Exception as e:
                    logger.error(f"[ZhihuQR] 检测状态出错: {e}")
                    await asyncio.sleep(2)
                    waited += 2

            # 判断是否登录成功
            current_url = page.url or ''
            if 'signin' not in current_url.lower() and 'zhihu.com' in current_url:
                logger.info(f"[ZhihuQR] 开始处理登录成功流程，URL: {current_url}")
                await asyncio.sleep(3)

                # 访问知乎创作者中心，获取完整 cookie
                try:
                    await page.goto('https://www.zhihu.com/creator', timeout=15000, wait_until='domcontentloaded')
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"[ZhihuQR] 访问创作者中心失败（继续）: {e}")

                # 访问写作页触发更多 cookie
                try:
                    await page.goto('https://zhuanlan.zhihu.com/write', timeout=15000, wait_until='domcontentloaded')
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"[ZhihuQR] 访问写作页失败（继续）: {e}")

                # 获取 cookies
                cookies = await context.cookies()
                logger.info(f"[ZhihuQR] 获取到 {len(cookies)} 个 Cookie")

                # 检查关键 cookie
                key_cookies = ['z_c0', 'd_c0', '_xsrf', 'q_c1', 'tst']
                found_keys = [c.get('name') for c in cookies if c.get('name') in key_cookies]
                logger.info(f"[ZhihuQR] 关键 Cookie: {found_keys}")

                has_z_c0 = any(c.get('name') == 'z_c0' for c in cookies)
                logger.info(f"[ZhihuQR] z_c0 认证 Token: {'已获取' if has_z_c0 else '未获取'}")

                # 保存 storage_state
                state_path = None
                try:
                    state = await context.storage_state()
                    state_path = _state_path(session.get('user_id', 0)) if session.get('user_id') else None
                    if state_path:
                        with open(state_path, 'w', encoding='utf-8') as f:
                            json.dump(state, f, ensure_ascii=False)
                        session['state_path'] = state_path
                        logger.info(f"[ZhihuQR] storage_state 已保存到 {state_path}")
                except Exception as e:
                    logger.error(f"[ZhihuQR] 保存 storage_state 失败: {e}")

                session['cookies'] = cookies
                session['status'] = 'success'
                await self._close_session(session_id)
                return

            logger.info(f"[ZhihuQR] 会话 {session_id} 扫码超时")
            session['status'] = 'timeout'
            await self._close_session(session_id)

        except Exception as e:
            logger.error(f"[ZhihuQR] 检测登录状态失败: {e}")
            session['status'] = 'error'
            session['error'] = str(e)
            await self._close_session(session_id)

    async def _detect_verification_page(self, page) -> bool:
        """检测是否进入验证码页面"""
        try:
            # 知乎验证码通常是图形验证码或短信验证码
            for selector in [
                'input[placeholder*="验证码"]',
                'input[placeholder*="code" i]',
                'img.Captcha',
                '.Captcha',
                'input[name*="captcha" i]',
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
        """提交验证码"""
        session = login_sessions.get(session_id)
        if not session:
            return {'success': False, 'error': '会话不存在'}

        page = session['page']
        try:
            for selector in [
                'input[placeholder*="验证码"]',
                'input[placeholder*="code" i]',
                'input[name*="captcha" i]',
                'input[name*="code" i]'
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0 and await el.is_visible():
                        await el.fill(code)
                        logger.info(f"[ZhihuQR] 已填入验证码到 {selector}")

                        # 点击确定按钮
                        for btn_selector in [
                            'button:has-text("确定")',
                            'button:has-text("验证")',
                            'button[type="submit"]'
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
                        logger.info(f"[ZhihuQR] 会话 {session_id} 验证码已提交")
                        return {'success': True}
                except Exception:
                    continue

            return {'success': False, 'error': '未找到验证码输入框'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _close_session(self, session_id: str):
        """关闭会话浏览器"""
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
            logger.error(f"[ZhihuQR] 关闭会话失败: {e}")
        finally:
            self.playwright = None
            self.browser = None

    async def _cleanup_session(self, session_id: str):
        """清理失败的会话"""
        await self._close_session(session_id)
        if session_id in login_sessions:
            login_sessions.pop(session_id, None)

    def get_login_status(self, session_id: str) -> Dict:
        """获取登录状态（同步接口）"""
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

            has_z_c0 = any(c.get('name') == 'z_c0' for c in cookies)
            result['has_z_c0'] = has_z_c0

        elif status == 'need_verification':
            result['message'] = '请输入验证码'
        elif status == 'timeout':
            result['message'] = '扫码超时，请重新获取二维码'
        elif status == 'error':
            result['message'] = session.get('error', '登录失败')

        return result

    async def cancel_login(self, session_id: str) -> Dict:
        """取消登录"""
        session = login_sessions.get(session_id)
        if session:
            session['status'] = 'cancelled'
            await self._close_session(session_id)
            login_sessions.pop(session_id, None)
        return {'success': True}


# 全局单例
zhihu_qr_login_manager = ZhihuQRLogin()
