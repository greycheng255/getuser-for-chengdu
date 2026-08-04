"""
小红书二维码登录模块
使用 Playwright 实现二维码登录流程
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 存储登录会话
login_sessions: Dict[str, dict] = {}

# ============== 全局事件循环管理 ==============
# 所有 QR 登录相关的异步操作（包括 start_qr_login、_check_login_status、
# get_login_status、submit_verification_code）都必须在同一个长期运行的事件循环中执行，
# 否则 playwright 对象会因为事件循环关闭而失效，后台任务也会被取消。

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
                logger.error(f"[QRLogin] 全局事件循环异常: {e}")

        t = threading.Thread(target=_run_loop, daemon=True, name="qr-login-loop")
        t.start()
        logger.info("[QRLogin] 全局事件循环已启动")
        return _loop


def run_async(coro, timeout=60):
    """在全局事件循环中运行协程，同步等待结果（供 Flask 同步路由调用）"""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


class XiaohongshuQRLogin:
    """小红书二维码登录管理器"""
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
    
    async def init_browser(self):
        """初始化浏览器"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 720}
            )
            self.page = await self.context.new_page()
            return True
        except Exception as e:
            logger.error(f"初始化浏览器失败: {e}")
            return False
    
    async def start_qr_login(self, session_id: str) -> Dict:
        """启动二维码登录流程"""
        try:
            logger.info(f"开始二维码登录，会话ID: {session_id}")
            
            # 初始化浏览器
            if not await self.init_browser():
                return {
                    'success': False,
                    'error': '浏览器初始化失败'
                }
            
            # 访问小红书登录页面
            logger.info("访问小红书登录页面...")
            await self.page.goto('https://creator.xiaohongshu.com/login', timeout=30000)
            await asyncio.sleep(3)
            
            # 截图查看页面状态
            await self.page.screenshot(path=f'/tmp/xiaohongshu_step1_{session_id}.png')
            
            # 尝试点击扫码登录按钮
            try:
                # 先截图查看当前页面状态
                await self.page.screenshot(path=f'/tmp/xiaohongshu_step1_{session_id}.png')
                
                # 查找二维码切换按钮（通常在右上角）
                qr_switch_selectors = [
                    '.login-switch-qrcode',
                    '.login-qrcode-switch',
                    '[class*="qrcode-switch"]',
                    '.login-box .qrcode',
                    'img[src*="qr"]',
                    '.login-tab-qrcode',
                    'text=扫码登录',
                ]
                
                qr_btn = None
                for selector in qr_switch_selectors:
                    try:
                        qr_btn = await self.page.query_selector(selector)
                        if qr_btn:
                            logger.info(f"找到扫码登录切换按钮: {selector}")
                            break
                    except:
                        continue
                
                if qr_btn:
                    await qr_btn.click()
                    logger.info("已点击切换到扫码登录")
                    await asyncio.sleep(3)
                    
                    # 截图查看切换后的页面
                    await self.page.screenshot(path=f'/tmp/xiaohongshu_step2_{session_id}.png')
                else:
                    logger.warning("未找到扫码登录切换按钮")
                    
            except Exception as e:
                logger.warning(f"切换到扫码登录失败: {e}")
            
            # 等待二维码加载
            await asyncio.sleep(3)
            
            # 获取二维码 - 优先获取原始 src
            logger.info("尝试获取二维码...")
            qr_image_data = None
            
            try:
                # 获取登录框
                login_box = await self.page.query_selector('.login-box, .login-content, [class*="login-container"]')
                if login_box:
                    # 获取登录框内的所有图片
                    images = await login_box.query_selector_all('img')
                    logger.info(f"登录框内找到 {len(images)} 个图片元素")
                    
                    # 找到最大的图片（通常是二维码）
                    largest_img = None
                    largest_size = 0
                    
                    for img in images:
                        try:
                            box = await img.bounding_box()
                            if box:
                                size = box['width'] * box['height']
                                if size > largest_size and size > 10000:
                                    largest_size = size
                                    largest_img = img
                        except:
                            continue
                    
                    if largest_img:
                        logger.info(f"找到最大的图片，尺寸: {largest_size} 像素")
                        
                        # 首先尝试获取图片的原始 src
                        qr_src = await largest_img.get_attribute('src')
                        if qr_src and len(qr_src) > 1000:
                            logger.info(f"获取到二维码原始 src，长度: {len(qr_src)}")
                            if qr_src.startswith('data:image'):
                                # 已经是 base64，直接使用
                                qr_image_data = qr_src
                            else:
                                # 是 URL，需要下载
                                import urllib.request
                                qr_path = f'/tmp/xiaohongshu_qr_{session_id}.png'
                                urllib.request.urlretrieve(qr_src, qr_path)
                                with open(qr_path, 'rb') as f:
                                    qr_base64 = base64.b64encode(f.read()).decode('utf-8')
                                qr_image_data = f'data:image/png;base64,{qr_base64}'
                        else:
                            # 无法获取 src，只能截图
                            logger.warning("无法获取二维码原始 src，使用截图方式")
                            await largest_img.screenshot(path=f'/tmp/xiaohongshu_qr_{session_id}.png')
                            with open(f'/tmp/xiaohongshu_qr_{session_id}.png', 'rb') as f:
                                qr_base64 = base64.b64encode(f.read()).decode('utf-8')
                            qr_image_data = f'data:image/png;base64,{qr_base64}'
            except Exception as e:
                logger.error(f"获取二维码失败: {e}")
            
            if not qr_image_data:
                return {
                    'success': False,
                    'error': '无法获取二维码'
                }
            
            # 保存会话
            login_sessions[session_id] = {
                'browser': self.browser,
                'context': self.context,
                'page': self.page,
                'playwright': self.playwright,
                'status': 'waiting',
                'created_at': datetime.now(),
                'cookies': None
            }
            
            # 启动后台任务检查登录状态（用全局事件循环调度，避免被 asyncio.run() 关闭）
            loop = _get_loop()
            asyncio.run_coroutine_threadsafe(self._check_login_status(session_id), loop)
            logger.info(f"[QRLogin] 后台任务已调度，会话 {session_id}")
            
            return {
                'success': True,
                'session_id': session_id,
                'qr_image': qr_image_data,
                'status': 'waiting',
                'message': '请使用小红书APP扫描二维码登录'
            }
            
        except Exception as e:
            logger.error(f"启动二维码登录失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': f'启动二维码登录失败: {str(e)}'
            }
    
    async def _check_login_status(self, session_id: str):
        """后台检查登录状态"""
        try:
            session = login_sessions.get(session_id)
            if not session:
                return

            page = session['page']
            max_wait = 300  # 延长到 300 秒（需要预留验证码输入时间）
            waited = 0

            while waited < max_wait:
                # 如果已经被外部切换到 need_verification 状态，则暂停轮询，等待验证码提交
                if session.get('status') == 'need_verification':
                    await asyncio.sleep(2)
                    waited += 2
                    continue

                # 如果已经被取消，直接退出
                if session.get('status') in ('cancelled', 'success', 'timeout'):
                    return

                try:
                    # 检查当前URL
                    current_url = page.url or ''

                    # 阶段1：检测验证码输入页面（扫码后弹出短信验证码）
                    if await self._detect_verification_page(page):
                        logger.info(f"会话 {session_id} 检测到验证码输入页面")
                        session['status'] = 'need_verification'
                        session['verification_detected_at'] = datetime.now()
                        # 不关闭浏览器，等待用户提交验证码
                        continue

                    # 阶段2：如果URL不再是登录页面，说明登录成功
                    if 'login' not in current_url and 'creator.xiaohongshu.com' in current_url:
                        logger.info(f"会话 {session_id} 登录成功，当前URL: {current_url}")
                        # 跳出循环，进入登录成功后的处理流程（避免重复处理）
                        break

                    # 还在等待扫码
                    await asyncio.sleep(2)
                    waited += 2

                except Exception as e:
                    logger.error(f"检查登录状态出错: {e}")
                    await asyncio.sleep(2)
                    waited += 2

            # 循环结束后判断是否登录成功
            current_url = page.url or ''
            if 'login' not in current_url and 'creator.xiaohongshu.com' in current_url:
                # === 登录成功后的处理（只执行一次）===
                logger.info(f"[QRLogin] 开始处理登录成功流程，URL: {current_url}")

                # 等待页面稳定
                await asyncio.sleep(3)

                # 访问创作者平台主页（用 domcontentloaded，避免 networkidle 永远等不到）
                try:
                    await page.goto('https://creator.xiaohongshu.com/', timeout=15000, wait_until='domcontentloaded')
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"[QRLogin] 访问创作者主页失败（继续执行）: {e}")

                # 访问发布管理页（触发 access-token-creator cookie 设置）
                try:
                    await page.goto('https://creator.xiaohongshu.com/publish/publish', timeout=15000, wait_until='domcontentloaded')
                    await asyncio.sleep(3)
                    logger.info("[QRLogin] 已访问发布页，触发 access-token 设置")
                except Exception as e:
                    logger.warning(f"[QRLogin] 访问发布页失败（继续执行）: {e}")

                # 访问 www.xiaohongshu.com 主页（触发 web_session cookie 设置）
                # web_session 是 www.xiaohongshu.com 域名的 cookie，必须访问主页才能拿到
                try:
                    await page.goto('https://www.xiaohongshu.com/', timeout=15000, wait_until='domcontentloaded')
                    await asyncio.sleep(3)
                    logger.info("[QRLogin] 已访问 www.xiaohongshu.com 主页，触发 web_session 设置")
                except Exception as e:
                    logger.warning(f"[QRLogin] 访问 www 主页失败（继续执行）: {e}")

                # 获取所有cookies（包括HttpOnly的）
                cookies = await session['context'].cookies()
                logger.info(f"获取到 {len(cookies)} 个Cookie")

                # 检查关键认证Cookie（支持新旧认证方式）
                auth_cookies = ['web_session', 'access-token', 'x-user-id', 'customer-sso-sid']
                found_auth_cookies = []
                for cookie in cookies:
                    cookie_name = cookie.get('name', '')
                    if cookie_name in auth_cookies or any(auth in cookie_name for auth in auth_cookies):
                        found_auth_cookies.append(cookie_name)
                        logger.info(f"找到认证Cookie {cookie_name}: {cookie.get('value')[:20]}...")

                if not found_auth_cookies:
                    logger.warning("未找到关键认证Cookie，可能登录未完全完成")
                else:
                    logger.info(f"找到 {len(found_auth_cookies)} 个认证Cookie: {found_auth_cookies}")

                # 检查是否拿到了创作者中心 access-token
                has_access_token_creator = any(
                    c.get('name', '').startswith('access-token') and 'creator' in c.get('domain', '')
                    for c in cookies
                )
                logger.info(f"[QRLogin] access-token-creator: {'已获取' if has_access_token_creator else '未获取'}")

                # === 保存 storage_state 到磁盘 ===
                try:
                    state = await session['context'].storage_state()
                    state_dir = os.environ.get('XHS_STATE_DIR', '/app/data/xhs_state')
                    os.makedirs(state_dir, exist_ok=True)
                    tmp_path = os.path.join(state_dir, f'_session_{session_id}.json')
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(state, f, ensure_ascii=False)
                    session['state_path'] = tmp_path
                    logger.info(f"[QRLogin] storage_state 已保存到 {tmp_path}")
                except Exception as e:
                    logger.error(f"[QRLogin] 保存 storage_state 失败: {e}")

                session['cookies'] = cookies
                session['status'] = 'success'

                # 关闭浏览器
                await self._close_session(session_id)
                return

            # 超时
            logger.info(f"会话 {session_id} 扫码超时")
            session['status'] = 'timeout'
            await self._close_session(session_id)

        except Exception as e:
            logger.error(f"检查登录状态失败: {e}")

    async def _detect_verification_page(self, page) -> bool:
        """检测当前页面是否为短信验证码输入页"""
        try:
            # 常见的验证码输入框选择器（覆盖小红书多种 UI 变体）
            verification_selectors = [
                'input[placeholder*="验证码"]',
                'input[placeholder*="短信"]',
                'input[placeholder*="code"]',
                'input[placeholder*="验证"]',
                'input[name*="code"]',
                'input[name*="verify"]',
                'input[type="tel"][maxlength]',
                'input[type="number"][maxlength]',
            ]
            for selector in verification_selectors:
                try:
                    elem = await page.query_selector(selector)
                    if elem and await elem.is_visible():
                        logger.info(f"[QRLogin] 检测到验证码输入框: {selector}")
                        return True
                except Exception:
                    continue

            # 检测页面文本是否包含"验证码"字样
            try:
                body_text = await page.evaluate("document.body.innerText")
                if body_text and ('验证码' in body_text or '短信验证' in body_text):
                    logger.info("[QRLogin] 页面文本包含'验证码'关键字")
                    return True
            except Exception:
                pass

            return False
        except Exception:
            return False

    async def submit_verification_code(self, session_id: str, code: str) -> Dict:
        """提交短信验证码"""
        try:
            session = login_sessions.get(session_id)
            if not session:
                return {'success': False, 'error': '会话不存在或已过期'}

            if session.get('status') != 'need_verification':
                return {'success': False, 'error': f'当前状态不是验证码输入阶段: {session.get("status")}'}

            page = session.get('page')
            if not page:
                return {'success': False, 'error': '浏览器页面已关闭'}

            logger.info(f"[QRLogin] 会话 {session_id} 提交验证码: {code}")

            # 1. 查找验证码输入框并填入
            verification_selectors = [
                'input[placeholder*="验证码"]',
                'input[placeholder*="短信"]',
                'input[placeholder*="code"]',
                'input[placeholder*="验证"]',
                'input[name*="code"]',
                'input[name*="verify"]',
                'input[type="tel"][maxlength]',
                'input[type="number"][maxlength]',
            ]
            input_filled = False
            for selector in verification_selectors:
                try:
                    elem = await page.query_selector(selector)
                    if elem and await elem.is_visible():
                        await elem.fill(code)
                        input_filled = True
                        logger.info(f"[QRLogin] 已填入验证码到: {selector}")
                        break
                except Exception:
                    continue

            if not input_filled:
                return {'success': False, 'error': '未找到验证码输入框'}

            # 2. 查找并点击"确定"/"提交"按钮
            btn_selectors = [
                'button:has-text("确定")',
                'button:has-text("确认")',
                'button:has-text("提交")',
                'button:has-text("验证")',
                'button[type="submit"]',
                '.btn:has-text("确定")',
                '.login-btn',
            ]
            btn_clicked = False
            for selector in btn_selectors:
                try:
                    btn = await page.query_selector(selector)
                    if btn and await btn.is_visible():
                        await btn.click()
                        btn_clicked = True
                        logger.info(f"[QRLogin] 已点击验证按钮: {selector}")
                        break
                except Exception:
                    continue

            if not btn_clicked:
                # 尝试按回车键提交
                try:
                    await page.keyboard.press('Enter')
                    btn_clicked = True
                    logger.info("[QRLogin] 已按回车提交验证码")
                except Exception:
                    pass

            if not btn_clicked:
                return {'success': False, 'error': '未找到验证按钮'}

            # 3. 把状态恢复为 waiting，让 _check_login_status 继续检测登录是否成功
            session['status'] = 'waiting'
            logger.info(f"[QRLogin] 会话 {session_id} 验证码已提交，状态恢复为 waiting")

            # 等待几秒，给页面跳转时间
            await asyncio.sleep(3)

            return {
                'success': True,
                'message': '验证码已提交，正在等待登录结果',
                'status': 'waiting'
            }

        except Exception as e:
            logger.error(f"[QRLogin] 提交验证码失败: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _close_session(self, session_id: str):
        """关闭会话"""
        try:
            session = login_sessions.get(session_id)
            if session:
                if session.get('page'):
                    await session['page'].close()
                if session.get('context'):
                    await session['context'].close()
                if session.get('browser'):
                    await session['browser'].close()
                if session.get('playwright'):
                    await session['playwright'].stop()
        except Exception as e:
            logger.error(f"关闭会话失败: {e}")
    
    async def get_login_status(self, session_id: str) -> Dict:
        """获取登录状态"""
        session = login_sessions.get(session_id)
        if not session:
            return {
                'success': False,
                'error': '会话不存在或已过期'
            }

        status = session.get('status', 'waiting')

        if status == 'success':
            # 返回cookies
            cookies = session.get('cookies', [])

            # 查找所有认证Cookie（支持新旧认证方式）
            auth_cookies = ['web_session', 'access-token', 'x-user-id', 'customer-sso-sid']
            found_auth = {}
            for cookie in cookies:
                cookie_name = cookie.get('name', '')
                if cookie_name in auth_cookies or any(auth in cookie_name for auth in auth_cookies):
                    found_auth[cookie_name] = cookie.get('value')

            return {
                'success': True,
                'status': 'success',
                'cookies': cookies,
                'auth_cookies': found_auth,
                'web_session': found_auth.get('web_session')  # 保持向后兼容
            }
        elif status == 'timeout':
            return {
                'success': False,
                'status': 'timeout',
                'error': '扫码超时，请重新获取二维码'
            }
        elif status == 'need_verification':
            # 需要输入短信验证码
            return {
                'success': True,
                'status': 'need_verification',
                'message': '请输入手机收到的短信验证码',
                'remaining_time': 300
            }
        else:
            # 计算剩余时间
            created_at = session.get('created_at')
            remaining_time = 300  # 默认300秒（预留验证码输入时间）
            if created_at:
                elapsed = (datetime.now() - created_at).total_seconds()
                remaining_time = max(0, int(300 - elapsed))

            return {
                'success': True,
                'status': 'waiting',
                'message': '等待扫码...',
                'remaining_time': remaining_time
            }
    
    async def cancel_login(self, session_id: str):
        """取消登录"""
        try:
            await self._close_session(session_id)
            if session_id in login_sessions:
                del login_sessions[session_id]
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}


# 全局实例
qr_login_manager = XiaohongshuQRLogin()
