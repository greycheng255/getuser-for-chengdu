"""
小红书自动化发布模块
使用Playwright模拟浏览器操作实现自动发布
"""

import asyncio
import json
import logging
import re
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class XiaohongshuAutoPublisher:
    """小红书自动化发布器 - 使用Playwright"""

    def __init__(self, cookies: str, user_id: int = None):
        """
        初始化发布器
        :param cookies: 可以是单个 web_session 字符串，也可以是 JSON 格式的完整 Cookie 列表
        :param user_id: 用户 ID，用于加载 storage_state（持久化登录状态）
        """
        self.cookies_raw = cookies
        self.user_id = user_id
        self.storage_state = None
        self.cookies_list = None
        self.web_session = None
        self.access_token = None
        self.x_user_id = None

        # 优先加载 storage_state（包含 localStorage 等完整状态）
        if user_id is not None:
            try:
                import os
                state_dir = os.environ.get('XHS_STATE_DIR', '/app/data/xhs_state')
                state_path = os.path.join(state_dir, f'user_{user_id}.json')
                if os.path.exists(state_path):
                    with open(state_path, 'r', encoding='utf-8') as f:
                        self.storage_state = json.load(f)
                    logger.info(f"[XhsAuto] 用户 {user_id} 已加载 storage_state")
            except Exception as e:
                logger.warning(f"[XhsAuto] 加载 storage_state 失败: {e}")
        
        # 尝试解析为 JSON 列表
        try:
            parsed = json.loads(cookies)
            if isinstance(parsed, list):
                self.cookies_list = parsed
                # 从中提取各种认证方式
                for cookie in parsed:
                    name = cookie.get('name', '')
                    if name == 'web_session':
                        self.web_session = cookie.get('value')
                    elif 'access-token' in name:
                        self.access_token = cookie.get('value')
                    elif 'x-user-id' in name:
                        self.x_user_id = cookie.get('value')
                logger.info(f"解析到 {len(parsed)} 个 Cookie, web_session: {bool(self.web_session)}, access_token: {bool(self.access_token)}, x_user_id: {bool(self.x_user_id)}")
            else:
                self.web_session = cookies
        except:
            # 不是 JSON，当作单个 web_session
            self.web_session = cookies
            
        self.browser = None
        self.context = None
        self.page = None

    async def init_browser(self):
        """初始化浏览器"""
        import traceback
        try:
            from playwright.async_api import async_playwright

            logger.info("启动 Playwright...")
            self.playwright = await async_playwright().start()
            logger.info("Playwright 启动成功")

            logger.info("启动 Chromium 浏览器（反检测模式）...")
            # 尝试使用系统Chrome
            import shutil
            chrome_path = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
            
            # 反检测启动参数
            stealth_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-extensions',
                '--disable-default-apps',
                '--disable-component-update',
                '--disable-popup-blocking',
                '--disable-notifications',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-infobars',
                '--disable-renderer-backgrounding',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-sync',
                '--metrics-recording-only',
                '--password-store=basic',
                '--use-mock-keychain',
                '--lang=zh-CN',
                '--accept-lang=zh-CN,zh;q=0.9,en;q=0.8',
            ]
            
            if chrome_path:
                logger.info(f"使用系统Chrome: {chrome_path}")
                self.browser = await self.playwright.chromium.launch(
                    executable_path=chrome_path,
                    headless=True,
                    args=stealth_args
                )
            else:
                self.browser = await self.playwright.chromium.launch(
                    headless=True,  # 无头模式
                    args=stealth_args
                )
            logger.info("Chromium 启动成功（反检测模式）")

            logger.info("创建浏览器上下文（反检测）...")
            # 优先使用 storage_state（包含 localStorage 等完整状态）
            context_kwargs = dict(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                locale='zh-CN',
                timezone_id='Asia/Shanghai',
                geolocation={'latitude': 31.2304, 'longitude': 121.4737},  # 上海
                permissions=['geolocation'],
                color_scheme='light',
                is_mobile=False,
                has_touch=False,
                device_scale_factor=1,
                extra_http_headers={
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'sec-ch-ua': '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"macOS"',
                    'sec-fetch-dest': 'document',
                    'sec-fetch-mode': 'navigate',
                    'sec-fetch-site': 'none',
                    'sec-fetch-user': '?1',
                    'upgrade-insecure-requests': '1',
                    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                },
            )
            # 如果有 storage_state，注入到上下文参数
            if self.storage_state:
                context_kwargs['storage_state'] = self.storage_state
                logger.info("使用 storage_state 创建上下文（持久化登录状态）")
            self.context = await self.browser.new_context(**context_kwargs)
            
            # 注入反检测脚本（在每个页面加载前执行）
            await self.context.add_init_script("""
                // 隐藏 webdriver 标志
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                // 伪装 plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                // 伪装 languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en']
                });
                // 伪装 platform
                Object.defineProperty(navigator, 'platform', {
                    get: () => 'MacIntel'
                });
                // 伪装 hardwareConcurrency
                Object.defineProperty(navigator, 'hardwareConcurrency', {
                    get: () => 8
                });
                // 伪装 deviceMemory
                Object.defineProperty(navigator, 'deviceMemory', {
                    get: () => 8
                });
                // 伪装 connection
                Object.defineProperty(navigator, 'connection', {
                    get: () => ({
                        effectiveType: '4g',
                        rtt: 50,
                        downlink: 10,
                        saveData: false
                    })
                });
                // 伪装 webdriver prototype
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
                );
                // 移除 Playwright/automation 痕迹
                delete window.__playwright__;
                delete window.__pw_manual;
                // 伪装 chrome runtime
                window.chrome = {
                    runtime: {},
                    loadTimes: () => ({ requestTime: Date.now() / 1000 }),
                    csi: () => ({ startE: Date.now(), onloadT: Date.now() }),
                    app: {},
                };
            """)
            logger.info("已注入反检测脚本")
            logger.info("上下文创建成功")

            # 设置Cookie - 使用完整的 Cookie 列表
            # 注意：如果已使用 storage_state，cookies 已包含在 state 中，无需重复设置
            if self.cookies_list and not self.storage_state:
                # 转换 Playwright cookie 格式
                formatted_cookies = []
                for cookie in self.cookies_list:
                    formatted_cookie = {
                        'name': cookie.get('name'),
                        'value': cookie.get('value'),
                        'domain': cookie.get('domain', '.xiaohongshu.com'),
                        'path': cookie.get('path', '/'),
                    }
                    # 添加可选字段
                    if cookie.get('expires'):
                        formatted_cookie['expires'] = cookie.get('expires')
                    if cookie.get('httpOnly'):
                        formatted_cookie['httpOnly'] = cookie.get('httpOnly')
                    
                    # 对于 xiaohongshu.com 域名的 Cookie，设置 secure 和 sameSite
                    if 'xiaohongshu.com' in cookie.get('domain', ''):
                        formatted_cookie['secure'] = True
                        # 根据原始Cookie的sameSite设置，如果没有则默认为'None'
                        if cookie.get('sameSite'):
                            formatted_cookie['sameSite'] = cookie.get('sameSite')
                        else:
                            formatted_cookie['sameSite'] = 'None'
                    elif cookie.get('secure'):
                        formatted_cookie['secure'] = cookie.get('secure')
                    if cookie.get('sameSite'):
                        formatted_cookie['sameSite'] = cookie.get('sameSite')
                    
                    formatted_cookies.append(formatted_cookie)
                
                logger.info(f"准备添加 {len(formatted_cookies)} 个 Cookie...")
                for c in formatted_cookies[:5]:  # 显示前5个
                    logger.info(f"  Cookie: {c['name']}, domain: {c['domain']}, secure: {c.get('secure')}, sameSite: {c.get('sameSite')}")
                
                # 先访问目标网站，然后再添加Cookie（某些浏览器需要）
                logger.info("先访问小红书主页以设置Cookie domain...")
                temp_page = await self.context.new_page()
                await temp_page.goto('https://creator.xiaohongshu.com', wait_until='domcontentloaded', timeout=10000)
                await asyncio.sleep(2)
                
                # 添加Cookie
                await self.context.add_cookies(formatted_cookies)
                logger.info("Cookie添加成功")
                
                # 关闭临时页面
                await temp_page.close()
                
                # 验证Cookie是否添加成功
                cookies_after = await self.context.cookies()
                logger.info(f"验证: 浏览器上下文中共有 {len(cookies_after)} 个 Cookie")
                
                # 检查关键Cookie是否存在
                has_access_token = any('access-token' in c.get('name', '') for c in cookies_after)
                has_web_session = any(c.get('name') == 'web_session' for c in cookies_after)
                logger.info(f"关键Cookie检查 - access-token: {has_access_token}, web_session: {has_web_session}")
            elif self.web_session:
                # 回退到单个 web_session
                cookies_list = [{
                    'name': 'web_session',
                    'value': self.web_session,
                    'domain': '.xiaohongshu.com',
                    'path': '/',
                }]
                logger.info("添加单个 web_session Cookie...")
                await self.context.add_cookies(cookies_list)
                logger.info("Cookie 添加成功")
            else:
                logger.error("没有可用的 Cookie")
                return False

            logger.info("创建新页面...")
            self.page = await self.context.new_page()
            logger.info("页面创建成功")
            
            # 监听页面控制台日志（只记录错误，减少日志量）
            self.page.on("console", lambda msg: logger.error(f"[浏览器控制台] {msg.text}") if msg.type == 'error' else None)
            self.page.on("pageerror", lambda err: logger.error(f"[浏览器错误] {err}"))
            logger.info("已设置控制台日志监听")
            
            # 验证 Cookie 是否添加成功
            cookies_after = await self.context.cookies()
            logger.info(f"浏览器上下文中共有 {len(cookies_after)} 个 Cookie")
            for c in cookies_after[:5]:  # 只显示前5个
                logger.info(f"  Cookie: {c.get('name')} = {c.get('value')[:20]}...")

            logger.info("浏览器初始化成功")
            return True

        except ImportError as ie:
            logger.error(f"Playwright 未安装: {str(ie)}")
            logger.error(traceback.format_exc())
            return False
        except Exception as e:
            logger.error(f"浏览器初始化失败: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    async def publish_note(self, title: str, content: str, images: list = None, keywords: list = None) -> Dict:
        """
        自动发布小红书笔记

        Args:
            title: 笔记标题
            content: 笔记内容
            images: 图片路径列表（可选）
            keywords: 话题关键词列表（可选）
        """
        debug_info = []
        
        try:
            # 初始化浏览器
            debug_info.append("1. 初始化浏览器...")
            if not await self.init_browser():
                return {
                    'success': False,
                    'error': '浏览器初始化失败',
                    'platform': 'xiaohongshu',
                    'debug_info': debug_info
                }

            # 访问创作者平台 - 带重试机制
            debug_info.append("2. 访问创作者平台...")
            logger.info("访问小红书创作者平台...")
            
            # 重试访问页面
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = await self.page.goto('https://creator.xiaohongshu.com/', wait_until='domcontentloaded', timeout=30000)
                    debug_info.append(f"   页面响应状态: {response.status if response else '无响应'}")
                    
                    # 等待JavaScript渲染
                    await asyncio.sleep(5)
                    
                    # 检查页面是否正常加载
                    current_url = self.page.url
                    page_title = await self.page.title()
                    debug_info.append(f"   当前URL: {current_url}, 页面标题: {page_title}")
                    
                    # 检查页面是否有内容
                    page_content = await self.page.content()
                    if len(page_content) > 1000 and 'xiaohongshu' in page_content.lower():
                        debug_info.append(f"   ✅ 页面加载成功，内容长度: {len(page_content)}")
                        break
                    else:
                        debug_info.append(f"   ⚠️ 页面内容异常，长度: {len(page_content)}")
                        if attempt < max_retries - 1:
                            debug_info.append(f"   🔄 第 {attempt + 1} 次重试...")
                            await asyncio.sleep(3)
                        else:
                            raise Exception("页面加载失败，内容异常")
                            
                except Exception as e:
                    debug_info.append(f"   ❌ 访问页面失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                    if attempt < max_retries - 1:
                        debug_info.append(f"   🔄 等待后重试...")
                        await asyncio.sleep(5)
                    else:
                        await self.page.screenshot(path='/tmp/xiaohongshu_error_goto.png')
                        debug_info.append("   📸 已保存截图: /tmp/xiaohongshu_error_goto.png")
                        raise

            # 检查页面内容，看是否有登录相关的元素
            try:
                page_content = await self.page.content()
                logger.info(f"页面内容长度: {len(page_content)}")
                
                # 检查是否有登录相关的文本（更精确的判断）
                # 登录页面通常URL包含login，或页面内容很短且包含登录表单
                current_url = self.page.url
                is_login_url = 'login' in current_url.lower()
                is_short_page = len(page_content) < 10000
                has_login_form = '密码登录' in page_content or '手机号登录' in page_content or '验证码登录' in page_content
                
                logger.info(f"登录检测: URL={current_url}, is_login_url={is_login_url}, is_short_page={is_short_page}, has_login_form={has_login_form}")
                
                if is_login_url or (is_short_page and has_login_form):
                    debug_info.append("   ❌ 检测到登录页面，Cookie已过期")
                    logger.error("检测到登录页面，Cookie可能已过期")
                    
                    # 保存页面截图用于调试
                    await self.page.screenshot(path='/tmp/xiaohongshu_login_page.png')
                    debug_info.append("   📸 已保存截图: /tmp/xiaohongshu_login_page.png")
                    
                    return {
                        'success': False,
                        'error': 'Cookie已过期，请重新登录获取',
                        'platform': 'xiaohongshu',
                        'debug_info': debug_info
                    }
            except Exception as e:
                logger.error(f"检查页面内容时出错: {str(e)}")
            
            debug_info.append("   ✅ 已登录")

            # 直接访问图文发布页面（避免从首页导航带来的状态问题）
            debug_info.append("3. 导航到图文发布页面...")
            logger.info("导航到图文发布页面...")

            try:
                await self.page.goto('https://creator.xiaohongshu.com/publish/publish?from=menu&target=image', wait_until='domcontentloaded', timeout=30000)
                debug_info.append("   ✅ 页面DOM加载完成")
            except Exception as e:
                debug_info.append(f"   ⚠️ 页面加载超时: {str(e)}")

            # 等待页面完全加载
            debug_info.append("4. 等待发布页面加载...")
            logger.info("等待发布页面加载...")

            # 检查当前页面URL
            current_publish_url = self.page.url
            logger.info(f"发布页面URL: {current_publish_url}")
            debug_info.append(f"   当前页面: {current_publish_url}")

            # 等待JavaScript渲染（Vue组件初始化）- 直接等待固定时间
            await asyncio.sleep(5)
            debug_info.append("   ⏱️ 等待JavaScript渲染...")

            # 保存当前页面截图
            await self.page.screenshot(path='/tmp/xiaohongshu_publish_page.png')
            debug_info.append("   📸 已保存页面截图")

            # 检查页面是否完全加载 - 通过检查关键元素
            debug_info.append("   检查页面加载状态...")
            max_wait_attempts = 5
            for attempt in range(max_wait_attempts):
                try:
                    # 检查页面上是否有上传按钮
                    form_check = await self.page.evaluate('''() => {
                        const buttons = Array.from(document.querySelectorAll('button'));
                        return {
                            buttonCount: buttons.length,
                            hasUploadButton: buttons.some(b => b.textContent.includes('上传图片')),
                            pageText: document.body.innerText.slice(0, 200)
                        };
                    }''')

                    debug_info.append(f"   检查 {attempt + 1}/{max_wait_attempts}: buttons={form_check.get('buttonCount')}, hasUpload={form_check.get('hasUploadButton')}")

                    # 如果找到上传按钮，认为页面加载完成
                    if form_check.get('hasUploadButton'):
                        debug_info.append("   ✅ 页面表单元素已加载")
                        break

                    # 如果页面显示错误，提前退出
                    if '遇到问题' in form_check.get('pageText', '') or '错误' in form_check.get('pageText', ''):
                        debug_info.append(f"   ❌ 页面显示错误: {form_check.get('pageText', '')[:100]}")
                        break

                    # 继续等待
                    if attempt < max_wait_attempts - 1:
                        await asyncio.sleep(2)

                except Exception as e:
                    debug_info.append(f"   ⚠️ 检查页面状态时出错: {str(e)}")
                    break
            
            # 上传图片（小红书必须上传图片）
            if not images or len(images) == 0:
                debug_info.append("   ⚠️ 没有提供图片")
                return {
                    'success': False,
                    'platform': 'xiaohongshu',
                    'error': '小红书发布必须包含至少1张图片',
                    'message': '请上传图片后再发布到小红书，或启用AI自动生成功能',
                    'debug_info': debug_info
                }

            logger.info(f"上传 {len(images)} 张图片...")
            debug_info.append(f"   准备上传 {len(images)} 张图片")

            # 等待页面完全加载（确保Vue组件已初始化）
            await asyncio.sleep(5)

            # 使用 Playwright 上传图片
            upload_success = False

            # 方式1: 使用 filechooser 事件（小红书推荐方式）
            try:
                debug_info.append("   使用 filechooser 方式上传...")

                # 设置 filechooser 监听并点击上传按钮
                async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                    await self.page.click('button:has-text("上传图片")', timeout=5000)
                    debug_info.append("   ✅ 已点击上传按钮")

                file_chooser = await fc_info.value
                await file_chooser.set_files(images)
                debug_info.append("   ✅ filechooser 上传图片成功")
                upload_success = True
            except Exception as e:
                debug_info.append(f"   ⚠️ 方式1失败: {str(e)}")

            # 方式2: 直接找 file input（备用方式）
            if not upload_success:
                try:
                    upload_input = await self.page.wait_for_selector('input[type="file"]', state='attached', timeout=10000)
                    if upload_input:
                        await upload_input.set_input_files(images)
                        debug_info.append("   ✅ 直接设置文件上传成功")
                        upload_success = True
                except Exception as e:
                    debug_info.append(f"   ⚠️ 方式2失败: {str(e)}")

            # 方式3: 使用 JavaScript 直接触发文件上传
            if not upload_success:
                try:
                    debug_info.append("   尝试使用 JavaScript 上传...")

                    # 读取图片文件为 base64
                    import base64
                    with open(images[0], 'rb') as f:
                        img_data = base64.b64encode(f.read()).decode('utf-8')

                    result = await self.page.evaluate(f'''
                        async () => {{
                            let input = document.querySelector('input[type="file"]');
                            if (!input) {{
                                return {{ success: false, message: 'No file input found' }};
                            }}
                            input.click();
                            const byteCharacters = atob('{img_data}');
                            const byteArrays = [];
                            for (let i = 0; i < byteCharacters.length; i++) {{
                                byteArrays.push(byteCharacters.charCodeAt(i));
                            }}
                            const blob = new Blob([new Uint8Array(byteArrays)], {{ type: 'image/jpeg' }});
                            const file = new File([blob], 'image.jpg', {{ type: 'image/jpeg' }});
                            const dataTransfer = new DataTransfer();
                            dataTransfer.items.add(file);
                            input.files = dataTransfer.files;
                            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            return {{ success: true, message: 'JavaScript upload triggered' }};
                        }}
                    ''')
                    debug_info.append(f"   ✅ JavaScript 上传结果: {result}")
                    if result and result.get('success'):
                        upload_success = True
                except Exception as e:
                    debug_info.append(f"   ⚠️ 方式3失败: {str(e)}")

            if not upload_success:
                return {
                    'success': False,
                    'platform': 'xiaohongshu',
                    'error': '无法找到图片上传入口',
                    'message': '页面加载异常，请重试',
                    'debug_info': debug_info
                }

            debug_info.append("   ✅ 图片上传完成")

            # 等待表单元素加载（小红书新版：上传图片后才显示表单）
            debug_info.append("   等待表单元素加载...")

            # 先等待一段时间，让图片上传处理完成
            debug_info.append("   ⏱️ 等待图片上传处理...")
            await asyncio.sleep(5)  # 增加等待时间
            
            # 额外等待：检查图片是否真正上传成功
            debug_info.append("   检查图片上传状态...")
            for check_attempt in range(10):
                try:
                    img_check = await self.page.evaluate('''() => {
                        const images = document.querySelectorAll('img');
                        const uploadedImages = Array.from(images).filter(img => 
                            img.src && (img.src.includes('xiaohongshu') || img.src.includes('xhscdn'))
                        );
                        return {
                            totalImages: images.length,
                            uploadedImages: uploadedImages.length,
                            sampleSrc: uploadedImages.length > 0 ? uploadedImages[0].src.substring(0, 50) : null
                        };
                    }''')
                    debug_info.append(f"   图片检查 {check_attempt+1}/10: 总图片={img_check.get('totalImages')}, 已上传={img_check.get('uploadedImages')}")
                    
                    if img_check.get('uploadedImages', 0) >= len(images):
                        debug_info.append("   ✅ 图片已上传到小红书服务器")
                        break
                    
                    await asyncio.sleep(2)
                except Exception as e:
                    debug_info.append(f"   图片检查出错: {str(e)}")
                    await asyncio.sleep(2)

            max_form_wait = 30
            form_loaded = False
            for attempt in range(max_form_wait):
                try:
                    form_check = await self.page.evaluate('''() => {
                        const imgs = document.querySelectorAll('img');
                        const inputs = document.querySelectorAll('input, textarea, [contenteditable]');
                        const bodyText = document.body.innerText;

                        return {
                            imageCount: imgs.length,
                            inputCount: inputs.length,
                            hasImageEditor: bodyText.includes('图片编辑'),
                            hasForm: bodyText.includes('填写标题'),
                            pageText: bodyText.slice(0, 200)
                        };
                    }''')

                    debug_info.append(f"   表单检查 {attempt + 1}/{max_form_wait}: images={form_check.get('imageCount')}, inputs={form_check.get('inputCount')}, hasImageEditor={form_check.get('hasImageEditor')}")

                    # 如果找到图片编辑区域和表单元素，认为表单已加载
                    if form_check.get('hasImageEditor') and form_check.get('inputCount', 0) > 0:
                        debug_info.append("   ✅ 表单元素已加载")
                        form_loaded = True
                        break

                    # 检查真正的错误：如果图片数量没有增加且没有图片编辑器，可能是上传失败
                    # 注意：'遇到问题'是页面底部固定元素，不能作为错误判断依据
                    if attempt > 5 and form_check.get('imageCount', 0) < 5 and not form_check.get('hasImageEditor'):
                        debug_info.append(f"   ❌ 图片上传可能失败，图片数量: {form_check.get('imageCount')}")
                        break

                    await asyncio.sleep(2)
                except Exception as e:
                    debug_info.append(f"   ⚠️ 表单检查出错: {str(e)}")
                    break

            if not form_loaded:
                debug_info.append("   ⚠️ 表单元素加载失败，尝试使用JavaScript直接操作")
                try:
                    await self.page.screenshot(path='/tmp/xiaohongshu_no_form_elements.png')
                    debug_info.append("   📸 已保存无表单元素截图")
                except:
                    pass

            # 填写标题
            debug_info.append("5. 填写标题...")
            logger.info("填写标题...")

            # 先保存页面源码用于调试
            page_html = await self.page.content()
            with open('/tmp/xiaohongshu_page.html', 'w', encoding='utf-8') as f:
                f.write(page_html[:50000])  # 只保存前50000字符
            debug_info.append("   📄 已保存页面源码")

            # 等待页面完全渲染
            await asyncio.sleep(3)

            # 使用 JavaScript 直接填写标题
            title_filled = False
            try:
                result = await self.page.evaluate(f'''
                    () => {{
                        // 尝试多种方式找到标题输入框（排除 file input）
                        let titleInput = document.querySelector('input[placeholder*="标题"]:not([type="file"])') ||
                                        document.querySelector('textarea[placeholder*="标题"]') ||
                                        document.querySelector('input[type="text"]') ||
                                        document.querySelector('[data-testid="title-input"]') ||
                                        document.querySelector('.title-input') ||
                                        document.querySelector('input[placeholder]:not([type="file"])') ||
                                        document.querySelector('.input-title') ||
                                        document.querySelector('[class*="title"] input:not([type="file"])') ||
                                        document.querySelector('[class*="title"] textarea') ||
                                        document.querySelector('input[maxlength]:not([type="file"])') ||
                                        document.querySelector('.publish-title input:not([type="file"])') ||
                                        document.querySelector('.note-title input:not([type="file"])') ||
                                        document.querySelector('.editor-title input:not([type="file"])') ||
                                        document.querySelector('[class*="publish"] input[type="text"]') ||
                                        document.querySelector('[class*="note"] input[type="text"]') ||
                                        document.querySelector('input:not([type="file"]):not([type="hidden"])');

                        if (titleInput) {{
                            titleInput.focus();
                            titleInput.click();
                            titleInput.value = '{title[:20]}';
                            titleInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            titleInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            titleInput.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'a', ctrlKey: true, bubbles: true }}));
                            titleInput.dispatchEvent(new KeyboardEvent('keydown', {{ key: '{title[:20]}', bubbles: true }}));
                            titleInput.blur();
                            return {{ success: true, message: 'Title filled: ' + titleInput.tagName + ', placeholder: ' + (titleInput.placeholder || 'none'), className: titleInput.className }};
                        }}
                        return {{ success: false, message: 'Title input not found', allInputs: document.querySelectorAll('input').length }};
                    }}
                ''')
                if result.get('success'):
                    debug_info.append(f"   ✅ 使用 JavaScript 填写标题: {result.get('message')}")
                    title_filled = True
                else:
                    debug_info.append(f"   ⚠️ JavaScript 未找到标题输入框: {result.get('message')}, 页面共有 {result.get('allInputs')} 个input元素")
                await asyncio.sleep(1)
            except Exception as e:
                debug_info.append(f"   ⚠️ JavaScript 填写标题失败: {str(e)}")

            # 如果JavaScript方式失败，尝试传统方式（增强选择器）
            if not title_filled:
                try:
                    title_selectors = [
                        'input[placeholder*="标题"]',
                        'textarea[placeholder*="标题"]',
                        'input[type="text"]',
                        '.title-input',
                        '.input-title',
                        '[class*="title"] input',
                        '.publish-title input',
                        '.note-title input',
                        '.editor-title input',
                        'input[maxlength]'
                    ]
                    for selector in title_selectors:
                        try:
                            title_input = await self.page.wait_for_selector(selector, timeout=2000)
                            if title_input:
                                await title_input.fill(title[:20])
                                debug_info.append(f"   ✅ 使用传统方式填写标题: {selector}")
                                title_filled = True
                                break
                        except:
                            continue
                except Exception as e:
                    debug_info.append(f"   ⚠️ 传统方式填写标题失败: {str(e)}")

            if not title_filled:
                # 保存截图用于调试
                try:
                    await self.page.screenshot(path='/tmp/xiaohongshu_no_title_input.png')
                    debug_info.append("   📸 已保存无标题输入框截图")
                except:
                    pass

            # 填写内容
            logger.info("填写内容...")

            # 格式化内容（添加话题标签）
            formatted_content = content
            if keywords:
                tags = ' '.join([f'#{kw}#' for kw in keywords[:5]])
                formatted_content = f"{content}\n\n{tags}"

            # 使用 JavaScript 直接填写内容
            # 先处理内容中的特殊字符
            safe_content = formatted_content[:1000].replace("'", "\\'").replace("\n", "\\n")
            content_filled = False
            try:
                result = await self.page.evaluate(f'''
                    () => {{
                        // 尝试多种方式找到内容编辑框（增强选择器）
                        let contentInput = document.querySelector('div[contenteditable="true"]') ||
                                          document.querySelector('textarea[placeholder*="正文"]') ||
                                          document.querySelector('textarea[placeholder*="内容"]') ||
                                          document.querySelector('textarea[placeholder*="描述"]') ||
                                          document.querySelector('textarea') ||
                                          document.querySelector('[data-testid="content-input"]') ||
                                          document.querySelector('.content-input') ||
                                          document.querySelector('.editor') ||
                                          document.querySelector('.post-content') ||
                                          document.querySelector('.publish-content') ||
                                          document.querySelector('.note-content') ||
                                          document.querySelector('.editor-content') ||
                                          document.querySelector('[class*="content"] div[contenteditable]') ||
                                          document.querySelector('[class*="editor"] div[contenteditable]') ||
                                          document.querySelector('[class*="publish"] div[contenteditable]') ||
                                          document.querySelector('[contenteditable]');

                        if (contentInput) {{
                            contentInput.focus();
                            contentInput.click();
                            if (contentInput.contentEditable === 'true' || contentInput.isContentEditable) {{
                                contentInput.innerText = '{safe_content}';
                            }} else {{
                                contentInput.value = '{safe_content}';
                            }}
                            contentInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            contentInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            contentInput.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'a', ctrlKey: true, bubbles: true }}));
                            contentInput.dispatchEvent(new KeyboardEvent('keydown', {{ key: '{safe_content}', bubbles: true }}));
                            contentInput.blur();
                            return {{ success: true, message: 'Content filled: ' + contentInput.tagName + ', contentEditable: ' + contentInput.contentEditable, className: contentInput.className }};
                        }}
                        return {{ success: false, message: 'Content input not found', allTextareas: document.querySelectorAll('textarea').length, allEditable: document.querySelectorAll('[contenteditable]').length }};
                    }}
                ''')
                if result.get('success'):
                    debug_info.append(f"   ✅ 使用 JavaScript 填写内容: {result.get('message')}")
                    content_filled = True
                else:
                    debug_info.append(f"   ⚠️ JavaScript 未找到内容输入框: {result.get('message')}, 页面共有 {result.get('allTextareas')} 个textarea, {result.get('allEditable')} 个contenteditable元素")
                await asyncio.sleep(1)
            except Exception as e:
                debug_info.append(f"   ⚠️ JavaScript 填写内容失败: {str(e)}")

            # 如果JavaScript方式失败，尝试传统方式（增强选择器）
            if not content_filled:
                try:
                    content_selectors = [
                        'div[contenteditable="true"]',
                        'textarea[placeholder*="正文"]',
                        'textarea[placeholder*="内容"]',
                        'textarea[placeholder*="描述"]',
                        '.content-input',
                        '.editor',
                        '.post-content',
                        '.publish-content',
                        '.note-content',
                        '.editor-content',
                        'textarea'
                    ]
                    for selector in content_selectors:
                        try:
                            content_input = await self.page.wait_for_selector(selector, timeout=2000)
                            if content_input:
                                await content_input.fill(formatted_content[:1000])
                                debug_info.append(f"   ✅ 使用传统方式填写内容: {selector}")
                                content_filled = True
                                break
                        except:
                            continue
                except Exception as e:
                    debug_info.append(f"   ⚠️ 传统方式填写内容失败: {str(e)}")

            if not content_filled:
                # 保存截图用于调试
                try:
                    await self.page.screenshot(path='/tmp/xiaohongshu_no_content_input.png')
                    debug_info.append("   📸 已保存无内容输入框截图")
                except:
                    pass

            # 点击发布按钮
            logger.info("点击发布按钮...")
            publish_clicked = False

            # 方式1: 滚动到页面底部并使用坐标点击发布按钮
            try:
                debug_info.append("   滚动到页面底部...")
                await self.page.evaluate('''() => { window.scrollTo(0, document.body.scrollHeight); }''')
                await asyncio.sleep(2)

                # 使用坐标点击发布按钮（根据截图，发布按钮在页面底部中央偏右）
                debug_info.append("   使用坐标点击发布按钮...")
                await self.page.mouse.click(960, 1020)
                debug_info.append("   ✅ 使用坐标点击发布按钮")
                publish_clicked = True
            except Exception as e:
                debug_info.append(f"   ⚠️ 坐标点击失败: {str(e)}")

            # 方式2: 使用 xhs-publish-btn 自定义组件（小红书新版界面）
            if not publish_clicked:
                try:
                    publish_btn = await self.page.wait_for_selector('xhs-publish-btn', timeout=5000)
                    if publish_btn:
                        await publish_btn.click()
                        debug_info.append("   ✅ 使用 xhs-publish-btn 点击发布按钮")
                        publish_clicked = True
                except Exception as e:
                    debug_info.append(f"   ⚠️ xhs-publish-btn 点击失败: {str(e)}")

            # 方式3: 使用 JavaScript 查找并点击发布按钮
            if not publish_clicked:
                try:
                    click_result = await self.page.evaluate('''
                        () => {
                            // 尝试多种方式找到发布按钮
                            const buttons = Array.from(document.querySelectorAll('button'));
                            let btn = buttons.find(b => {
                                const text = b.textContent.trim();
                                return (text === '发布' || text === '立即发布' || text === '确认发布') && !b.disabled;
                            }) ||
                                      document.querySelector('[data-testid="publish-btn"]') ||
                                      document.querySelector('.publish-btn') ||
                                      document.querySelector('button[type="submit"]') ||
                                      document.querySelector('.btn-publish') ||
                                      document.querySelector('button.primary') ||
                                      document.querySelector('.submit-btn') ||
                                      document.querySelector('[class*="publish"]') ||
                                      buttons.find(b => b.className.includes('publish') && !b.disabled) ||
                                      buttons.find(b => b.textContent.includes('发布') && !b.disabled);

                            if (btn) {
                                btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                btn.focus();
                                btn.click();
                                btn.dispatchEvent(new Event('click', { bubbles: true }));
                                btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                                return { success: true, text: btn.textContent.trim(), className: btn.className, disabled: btn.disabled };
                            }
                            return { success: false, text: 'Publish button not found', allButtons: buttons.length };
                        }
                    ''')
                    if click_result.get('success'):
                        debug_info.append(f"   ✅ 使用 JavaScript 点击发布按钮: {click_result.get('text', '')}")
                        publish_clicked = True
                    else:
                        debug_info.append(f"   ⚠️ JavaScript 未找到发布按钮: {click_result.get('text', '')}, 页面共有 {click_result.get('allButtons')} 个按钮")
                except Exception as e:
                    debug_info.append(f"   ⚠️ JavaScript 点击失败: {str(e)}")

            # 方式3: 使用 Playwright 的 locator
            if not publish_clicked:
                try:
                    selectors = [
                        'button:has-text("发布")',
                        'button:has-text("立即发布")',
                        'button:has-text("确认发布")',
                        '.publish-btn',
                        '.btn-publish',
                        'button[type="submit"]',
                        'button.primary'
                    ]
                    for selector in selectors:
                        try:
                            btn = await self.page.wait_for_selector(selector, timeout=2000)
                            if btn:
                                await btn.click()
                                debug_info.append(f"   ✅ 使用 Playwright selector 点击发布按钮: {selector}")
                                publish_clicked = True
                                break
                        except:
                            continue
                except Exception as e:
                    debug_info.append(f"   ⚠️ Playwright selector 点击失败: {str(e)}")

            # 方式4: 使用 get_by_text
            if not publish_clicked:
                try:
                    submit_btn = self.page.get_by_text("发布", exact=False).first
                    await submit_btn.click()
                    debug_info.append("   ✅ 使用 Playwright get_by_text 点击发布按钮")
                    publish_clicked = True
                except Exception as e:
                    debug_info.append(f"   ⚠️ get_by_text 点击失败: {str(e)}")

            if not publish_clicked:
                try:
                    await self.page.screenshot(path='/tmp/xiaohongshu_no_publish_btn.png')
                    debug_info.append("   📸 已保存无发布按钮截图")
                except:
                    pass

                return {
                    'success': False,
                    'platform': 'xiaohongshu',
                    'error': '无法找到发布按钮',
                    'debug_info': debug_info
                }

            await asyncio.sleep(3)

            # 等待发布完成
            logger.info("等待发布完成...")
            debug_info.append("   等待发布处理...")

            # 等待更长时间，让发布完成
            await asyncio.sleep(15)

            # 检查是否有弹窗或提示
            try:
                # 检查是否有确认弹窗
                dialog = await self.page.wait_for_selector('.ant-modal, .dialog, [role="dialog"]', timeout=3000)
                if dialog:
                    dialog_text = await dialog.text_content()
                    debug_info.append(f"   检测到弹窗: {dialog_text[:100]}")
                    # 点击确认按钮
                    confirm_btn = await dialog.query_selector('button:has-text("确认"), button:has-text("确定"), button:has-text("发布")')
                    if confirm_btn:
                        await confirm_btn.click()
                        debug_info.append("   ✅ 点击确认按钮")
                        await asyncio.sleep(5)
            except:
                pass

            # 检查发布结果
            page_content = await self.page.content()
            current_url = self.page.url
            debug_info.append(f"   当前URL: {current_url}")

            # 保存发布后的页面截图
            try:
                await self.page.screenshot(path='/tmp/xiaohongshu_after_publish.png')
                debug_info.append("   📸 已保存发布后截图")
            except Exception as e:
                debug_info.append(f"   ⚠️ 保存截图失败: {str(e)}")

            # 提取页面关键文本用于调试
            page_text = await self.page.evaluate('() => document.body.innerText.slice(0, 500)')
            debug_info.append(f"   页面文本片段: {page_text[:200]}...")

            # 关键：检测小红书业务错误（HTTPBizError 是小红书 API 的错误对象）
            # 这些错误即使 HTTP 200 也会返回，必须优先判断
            biz_error_indicators = [
                'HTTPBizError', '禁止发笔记', '违反社区规范', '请稍后再试',
                '内容违规', '风控限制', '账号异常', '发布受限',
                '-9136', '-10000',  # 小红书常见业务错误码
            ]
            has_biz_error = any(indicator in page_content for indicator in biz_error_indicators)

            # 严格匹配的小红书业务错误 JSON（success:false）
            if '"success":false' in page_content or '"success": false' in page_content:
                has_biz_error = True

            if has_biz_error:
                # 提取具体错误信息
                biz_error_msg = '小红书业务错误'
                for indicator in biz_error_indicators:
                    if indicator in page_content:
                        biz_error_msg = f'小红书拒绝发布: {indicator}'
                        break
                logger.error(f"[XhsAuto] {biz_error_msg}")
                return {
                    'success': False,
                    'platform': 'xiaohongshu',
                    'error': biz_error_msg,
                    'message': biz_error_msg + '（可能账号被限流或内容触发风控）',
                    'debug_info': debug_info + [f'   ⚠️ 检测到业务错误: {biz_error_msg}']
                }

            # 多种成功标志（去除 'success' 关键字，因为它在错误 JSON 中也会出现）
            success_indicators = ['发布成功', '审核中', '笔记详情', '发布完成', 'published', '提交成功', '已发布']
            is_success = any(indicator in page_content for indicator in success_indicators)

            # 检查URL变化（发布成功后通常会跳转到笔记详情或列表页）
            url_changed = '/publish/' not in current_url and current_url != 'about:blank'

            # 检查是否有错误提示（使用更精确的错误指示词，避免JavaScript代码中的error字样）
            error_indicators = ['发布失败', '请重试', '无法发布', '内容不符合', '违规', '敏感', '禁止发笔记', '违反社区规范']
            has_error = any(indicator in page_content for indicator in error_indicators)

            # 检查是否有提交成功的提示（toast、弹窗等）- 只匹配页面可见文本，不匹配 JSON
            toast_success = '成功' in page_text

            # 检查是否有加载状态或处理中状态
            loading_indicators = ['发布中', '处理中', '上传中', 'loading', '请稍候']
            is_loading = any(indicator in page_content for indicator in loading_indicators)

            debug_info.append(f"   成功标志: {is_success}, URL变化: {url_changed}, 错误标志: {has_error}, Toast成功: {toast_success}, 加载中: {is_loading}")

            # 如果URL变化了，或者页面显示成功标志，且没有错误标志，则认为发布成功
            if (is_success or url_changed or toast_success) and not has_error:
                # 获取笔记链接
                note_link = await self.get_note_link()

                return {
                    'success': True,
                    'platform': 'xiaohongshu',
                    'message': '笔记发布成功',
                    'note_url': note_link,
                    'status': '审核中' if '审核中' in page_content else '已发布',
                    'debug_info': debug_info
                }
            else:
                # 检查错误信息
                error_msg = await self.extract_error_message()
                debug_info.append(f"   错误信息: {error_msg or '未找到具体错误'}")

                # 如果页面还在发布页面且没有错误，可能是异步提交
                if '/publish/' in current_url and not has_error and not is_loading:
                    # 可能是异步提交，需要再等待一下
                    debug_info.append("   页面仍在发布页面，等待异步提交完成...")
                    await asyncio.sleep(10)

                    # 再次检查
                    page_content = await self.page.content()
                    current_url = self.page.url

                    success_indicators_2 = ['发布成功', '审核中', '笔记详情', '发布完成', 'success', 'published', '已发布']
                    is_success_2 = any(indicator in page_content for indicator in success_indicators_2)
                    url_changed_2 = '/publish/' not in current_url and current_url != 'about:blank'

                    debug_info.append(f"   二次检查 - 成功标志: {is_success_2}, URL变化: {url_changed_2}")

                    if is_success_2 or url_changed_2:
                        note_link = await self.get_note_link()
                        return {
                            'success': True,
                            'platform': 'xiaohongshu',
                            'message': '笔记发布成功（异步提交）',
                            'note_url': note_link,
                            'status': '审核中',
                            'debug_info': debug_info
                        }

                # 如果页面还在加载中，可能是提交正在进行
                if is_loading:
                    debug_info.append("   页面仍在加载中，等待更长时间...")
                    await asyncio.sleep(15)

                    page_content = await self.page.content()
                    current_url = self.page.url

                    success_indicators_3 = ['发布成功', '审核中', '笔记详情', '发布完成', 'success', 'published', '已发布']
                    is_success_3 = any(indicator in page_content for indicator in success_indicators_3)
                    url_changed_3 = '/publish/' not in current_url and current_url != 'about:blank'
                    has_error_3 = any(indicator in page_content for indicator in error_indicators)

                    debug_info.append(f"   三次检查 - 成功标志: {is_success_3}, URL变化: {url_changed_3}, 错误: {has_error_3}")

                    if (is_success_3 or url_changed_3) and not has_error_3:
                        note_link = await self.get_note_link()
                        return {
                            'success': True,
                            'platform': 'xiaohongshu',
                            'message': '笔记发布成功（延迟确认）',
                            'note_url': note_link,
                            'status': '审核中',
                            'debug_info': debug_info
                        }

                # 记录详细的调试信息到日志
                logger.warning("=" * 60)
                logger.warning("小红书发布失败 - 详细调试信息:")
                for info in debug_info:
                    logger.warning(f"  {info}")
                logger.warning("=" * 60)

                return {
                    'success': False,
                    'platform': 'xiaohongshu',
                    'error': error_msg or '发布失败，请检查内容是否符合规范',
                    'debug_info': debug_info
                }

        except Exception as e:
            logger.error(f"自动发布失败: {str(e)}")
            # 截图保存用于调试
            try:
                if self.page:
                    await self.page.screenshot(path=f'/tmp/xiaohongshu_error_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
            except:
                pass

            debug_info.append(f"❌ 异常: {str(e)}")
            
            # 尝试截图
            try:
                if self.page:
                    await self.page.screenshot(path='/tmp/xiaohongshu_error.png')
                    debug_info.append("📸 已保存错误截图: /tmp/xiaohongshu_error.png")
            except:
                pass
            
            return {
                'success': False,
                'platform': 'xiaohongshu',
                'error': f'发布异常: {str(e)}',
                'debug_info': debug_info
            }

        finally:
            await self.close()

    async def get_note_link(self) -> Optional[str]:
        """获取发布的笔记链接"""
        try:
            # 尝试从页面中提取笔记链接
            link_element = await self.page.query_selector('a[href*="/discovery/item/"]')
            if link_element:
                href = await link_element.get_attribute('href')
                return f'https://xiaohongshu.com{href}' if href.startswith('/') else href
            return None
        except:
            return None

    async def extract_error_message(self) -> Optional[str]:
        """提取错误信息"""
        try:
            # 常见的错误提示元素
            error_selectors = [
                '.error-message',
                '.toast-content',
                '[class*="error"]',
                '[class*="fail"]'
            ]

            for selector in error_selectors:
                element = await self.page.query_selector(selector)
                if element:
                    text = await element.text_content()
                    if text:
                        return text.strip()

            return None
        except:
            return None

    async def close(self):
        """关闭浏览器"""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
        except Exception as e:
            logger.error(f"关闭浏览器失败: {str(e)}")


# 同步包装函数
async def auto_publish_to_xiaohongshu_async(title: str, content: str, cookies: str, images: list = None, keywords: list = None, max_retries: int = 2, user_id: int = None) -> Dict:
    """
    异步方式自动发布到小红书，支持重试

    Args:
        title: 标题
        content: 内容
        cookies: Cookie字符串
        images: 图片路径列表
        keywords: 关键词列表
        max_retries: 最大重试次数
        user_id: 用户 ID，用于加载 storage_state（持久化登录状态）

    Returns:
        发布结果字典
    """
    last_error = None

    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.info(f"第 {attempt} 次重试发布到小红书...")
            await asyncio.sleep(5)  # 重试前等待

        try:
            publisher = XiaohongshuAutoPublisher(cookies, user_id=user_id)
            result = await publisher.publish_note(title, content, images, keywords)

            if result.get('success'):
                logger.info(f"小红书发布成功（尝试 {attempt + 1}/{max_retries + 1}）")
                return result
            else:
                last_error = result.get('error', '未知错误')
                logger.warning(f"小红书发布失败（尝试 {attempt + 1}/{max_retries + 1}）: {last_error}")

                # 账号被限流 / 业务错误 / 内容问题，不重试直接返回
                no_retry_keywords = [
                    '必须包含至少1张图片', '无权访问',
                    '禁止发笔记', '违反社区规范', 'HTTPBizError',
                    '小红书拒绝发布', '账号被限流', '风控限制',
                ]
                if any(kw in last_error for kw in no_retry_keywords):
                    logger.warning(f"[XhsAuto] 检测到不可重试错误，直接返回: {last_error}")
                    return result

        except Exception as e:
            last_error = str(e)
            logger.error(f"小红书发布异常（尝试 {attempt + 1}/{max_retries + 1}）: {last_error}")

    # 所有重试都失败了
    return {
        'success': False,
        'platform': 'xiaohongshu',
        'error': f'发布失败，已重试 {max_retries} 次: {last_error}',
        'message': '请检查网络连接和账号状态后重试'
    }


def auto_publish_to_xiaohongshu(title: str, content: str, cookies: str, images: list = None, keywords: list = None, max_retries: int = 2, user_id: int = None) -> Dict:
    """
    同步方式自动发布到小红书，支持重试

    Args:
        title: 标题
        content: 内容
        cookies: Cookie字符串
        images: 图片路径列表
        keywords: 关键词列表
        max_retries: 最大重试次数
        user_id: 用户 ID，用于加载 storage_state（持久化登录状态）

    Returns:
        发布结果字典
    """
    return asyncio.run(auto_publish_to_xiaohongshu_async(title, content, cookies, images, keywords, max_retries, user_id))


# 测试函数
if __name__ == '__main__':
    # 测试代码
    result = auto_publish_to_xiaohongshu(
        title="测试标题",
        content="这是测试内容",
        cookies="your_web_session_cookie_here",
        keywords=["测试", "自动化"]
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
