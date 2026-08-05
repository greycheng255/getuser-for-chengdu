# -*- coding: utf-8 -*-
"""获客采集专用浏览器启动器(从 getuser-canrun outreach_automation 剥离)

设计目标:
1. 完全脱离 outreach_automation,仅供 contact_collector / lead_comment_monitor 使用
2. 复用 MediaCrawler-main 已有的 CDPBrowserManager + tools/anti_detect.py
3. 实现浏览器实例缓存(TTL 10 分钟),避免每次采集都重启 Chrome
4. 注入 anti_detect 反检测脚本(WebRTC/AudioContext/WebGL2/cdc_ 清除)

迁移对应: getuser-canrun 迁移方案 v2.0 A12(反检测浏览器启动器)
源函数: outreach_automation._launch_browser_for_outreach + _inject_anti_detection

注意: 不迁移 outreach 的"扫描已有 Chrome 端口复用"逻辑(那是 outreach 特有优化),
     本模块用 CDPBrowserManager 启动独立 Chrome + 缓存复用,足够获客采集场景。
"""
import asyncio
import os
import shutil
import time
from typing import Dict, Optional, Tuple

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

import config
from tools import utils
from tools.anti_detect import get_anti_detect_script
from tools.cdp_browser import CDPBrowserManager


# ==================== 浏览器实例缓存 ====================
_BROWSER_CACHE_TTL = 600  # 缓存 10 分钟(获客采集低频,无需频繁重启)
_cached_browser: Optional[Dict] = None
_browser_last_used: float = 0.0


async def _close_cached_browser():
    """关闭缓存的浏览器实例。"""
    global _cached_browser, _browser_last_used
    if _cached_browser is None:
        return
    try:
        playwright = _cached_browser.get("playwright")
        if playwright:
            await playwright.stop()
        utils.logger.info("[lead_browser] Cached browser closed")
    except Exception as e:
        utils.logger.warning(f"[lead_browser] Error closing cached browser: {e}")
    finally:
        _cached_browser = None
        _browser_last_used = 0


def _ensure_xvfb():
    """在无头环境中自动启动 Xvfb 虚拟显示器(CDP headed 模式需要)。

    从 outreach_automation._ensure_xvfb 剥离的精简版:
    1. 清理无效 Xvfb 实例
    2. 复用已有可用 DISPLAY
    3. 启动新 Xvfb
    """
    current_display = os.environ.get("DISPLAY", "")
    if current_display:
        # 验证 DISPLAY 是否可用
        try:
            import subprocess
            result = subprocess.run(["xdpyinfo"], capture_output=True, timeout=3,
                                    env={**os.environ, "DISPLAY": current_display})
            if result.returncode == 0:
                return  # DISPLAY 有效
        except Exception:
            pass
        # DISPLAY 设置了但无效,清除它
        try:
            del os.environ["DISPLAY"]
        except Exception:
            pass

    if not shutil.which("Xvfb"):
        utils.logger.warning("[lead_browser] Xvfb not found, CDP headed mode may not work")
        return

    # 查找已有的可用 Xvfb 实例
    try:
        import subprocess
        result = subprocess.run(["pgrep", "-a", "Xvfb"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].startswith(":"):
                    display = parts[1]
                    try:
                        check = subprocess.run(["xdpyinfo"], capture_output=True, timeout=3,
                                               env={**os.environ, "DISPLAY": display})
                        if check.returncode == 0:
                            os.environ["DISPLAY"] = display
                            utils.logger.info(f"[lead_browser] Reusing existing Xvfb on {display}")
                            return
                    except Exception:
                        continue
    except Exception:
        pass

    # 启动新的 Xvfb 实例
    try:
        import subprocess
        display_num = 99
        while os.path.exists(f"/tmp/.X{display_num}-lock"):
            display_num += 1
        subprocess.Popen(
            ["Xvfb", f":{display_num}", "-screen", "0", "1920x1080x24",
             "-nolisten", "tcp", "-noreset"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = f":{display_num}"
        # 等待 Xvfb 启动(同步 sleep,本函数为同步实现)
        time.sleep(1)
        utils.logger.info(f"[lead_browser] Started Xvfb on :{display_num}")
    except Exception as e:
        utils.logger.warning(f"[lead_browser] Failed to start Xvfb: {e}")


def _is_headless_env() -> bool:
    """判断是否为无头环境(无 DISPLAY 或 HEADLESS=1)。"""
    return os.environ.get("DISPLAY") is None or os.environ.get("HEADLESS") == "1"


async def _load_platform_cookies(browser_context: BrowserContext, platform: str = "dy", user_id: int = 0):
    """根据平台加载 Cookie 到浏览器上下文(获客采集专用,优先 outreach Cookie)。

    从 outreach_automation._load_douyin_cookies / _load_xhs_cookies 剥离合并。
    优先使用 get_outreach_cookie(获客专用 Cookie),避免采集 Cookie 被风控影响。
    """
    if platform == "xhs":
        await _load_xhs_cookies(browser_context, user_id=user_id)
    else:
        await _load_douyin_cookies(browser_context, user_id=user_id)


async def _load_douyin_cookies(browser_context: BrowserContext, user_id: int = 0):
    """加载抖音 Cookie 到浏览器上下文。"""
    try:
        from .cookie_manager import get_cookie, get_outreach_cookie
        from tools.crawler_util import convert_str_cookie_to_dict
        import json
        import urllib.parse

        # 优先使用获客专用 Cookie
        cookie_str = ""
        if user_id:
            cookie_str = await get_outreach_cookie(user_id, "dy")
            if cookie_str:
                utils.logger.info(f"[lead_browser] Using outreach-specific cookie (user_id={user_id})")
        if not cookie_str:
            cookie_str = get_cookie("dy")
            if cookie_str:
                utils.logger.info("[lead_browser] Using global .env cookie")
        if not cookie_str:
            utils.logger.warning("[lead_browser] No Douyin cookie found")
            return

        # 清除浏览器中所有抖音相关的旧 cookie
        try:
            existing_cookies = await browser_context.cookies()
            dy_cookies = [c for c in existing_cookies if 'douyin.com' in c.get('domain', '')]
            if dy_cookies:
                for c in dy_cookies:
                    try:
                        await browser_context.clear_cookies(name=c['name'], domain=c['domain'])
                    except Exception:
                        pass
                utils.logger.info(f"[lead_browser] Cleared {len(dy_cookies)} old Douyin cookies")
        except Exception as clear_err:
            utils.logger.warning(f"[lead_browser] Failed to clear old cookies: {clear_err}")

        cookie_dict = convert_str_cookie_to_dict(cookie_str)
        cookies_to_add = [
            {"name": k, "value": v, "domain": ".douyin.com", "path": "/"}
            for k, v in cookie_dict.items()
        ]

        # 补充 uid(从 PhoneResumeUidCacheV1 提取)
        phone_uid_raw = cookie_dict.get('PhoneResumeUidCacheV1', '')
        if phone_uid_raw and not cookie_dict.get('uid'):
            try:
                uid_data = json.loads(urllib.parse.unquote(phone_uid_raw))
                uid_value = list(uid_data.keys())[0] if uid_data else ''
                if uid_value:
                    cookies_to_add.append({"name": "uid", "value": uid_value, "domain": ".douyin.com", "path": "/"})
            except Exception:
                pass

        await browser_context.add_cookies(cookies_to_add)
        utils.logger.info(f"[lead_browser] Loaded {len(cookies_to_add)} Douyin cookies")
    except Exception as e:
        utils.logger.warning(f"[lead_browser] Failed to load Douyin cookies: {e}")


async def _load_xhs_cookies(browser_context: BrowserContext, user_id: int = 0):
    """加载小红书 Cookie 到浏览器上下文。"""
    try:
        from .cookie_manager import get_cookie, get_outreach_cookie
        from tools.crawler_util import convert_str_cookie_to_dict

        cookie_str = ""
        if user_id:
            cookie_str = await get_outreach_cookie(user_id, "xhs")
        if not cookie_str:
            cookie_str = get_cookie("xhs")
        if not cookie_str:
            utils.logger.warning("[lead_browser] No XHS cookie found")
            return

        # 清除旧 cookie
        try:
            existing_cookies = await browser_context.cookies()
            xhs_cookies = [c for c in existing_cookies if 'xiaohongshu.com' in c.get('domain', '')]
            if xhs_cookies:
                for c in xhs_cookies:
                    try:
                        await browser_context.clear_cookies(name=c['name'], domain=c['domain'])
                    except Exception:
                        pass
                utils.logger.info(f"[lead_browser] Cleared {len(xhs_cookies)} old XHS cookies")
        except Exception as clear_err:
            utils.logger.warning(f"[lead_browser] Failed to clear old XHS cookies: {clear_err}")

        cookie_dict = convert_str_cookie_to_dict(cookie_str)
        cookies_to_add = [
            {"name": k, "value": v, "domain": ".xiaohongshu.com", "path": "/"}
            for k, v in cookie_dict.items()
        ]
        await browser_context.add_cookies(cookies_to_add)
        utils.logger.info(f"[lead_browser] Loaded {len(cookies_to_add)} XHS cookies")
    except Exception as e:
        utils.logger.warning(f"[lead_browser] Failed to load XHS cookies: {e}")


async def _verify_login(page: Page, platform: str = "dy") -> bool:
    """验证登录状态(通过页面元素/API 检测)。

    从 outreach_automation._verify_login 剥离精简版。
    """
    try:
        if platform == "xhs":
            # 小红书:检查是否有登录按钮
            result = await page.evaluate("""
                () => {
                    const loginBtn = document.querySelector('[class*="login-btn"], [class*="LoginButton"]');
                    if (loginBtn && loginBtn.offsetParent !== null) {
                        return { logged_in: false };
                    }
                    return { logged_in: true };
                }
            """)
            return bool(result.get('logged_in', False))
        else:
            # 抖音:通过 API 验证(检测页面是否有登录态标识)
            result = await page.evaluate("""
                async () => {
                    try {
                        // 检查页面是否有登录按钮(未登录时显示)
                        const loginBtn = document.querySelector('[class*="login"], [data-e2e*="login"]');
                        if (loginBtn && loginBtn.offsetParent !== null &&
                            (loginBtn.textContent || '').includes('登录')) {
                            return { logged_in: false };
                        }
                        // 检查是否有用户头像/昵称(登录后才显示)
                        const avatar = document.querySelector('[class*="avatar"], [data-e2e="user-avatar"]');
                        if (avatar) {
                            return { logged_in: true };
                        }
                        // 兜底:无登录按钮视为已登录
                        return { logged_in: true };
                    } catch(e) {
                        return { logged_in: false, error: String(e) };
                    }
                }
            """)
            return bool(result.get('logged_in', False))
    except Exception as e:
        utils.logger.warning(f"[lead_browser] Verify login failed: {e}")
        return False


async def _inject_anti_detection(browser_context: BrowserContext):
    """注入反自动化检测脚本(从 tools/anti_detect 加载完整脚本)。

    覆盖防护:
    1. navigator.webdriver = false
    2. chrome.runtime 属性
    3. Permissions API 行为
    4. Plugin/MimeType 数量
    5. WebGL/WebGL2 渲染器信息
    6. WebRTC IP 泄漏防护
    7. AudioContext 指纹随机化
    8. deviceMemory 伪装
    9. iframe contentWindow.webdriver 清除
    10. CDP cdc_* 特征变量清除
    """
    anti_detection_js = get_anti_detect_script()
    # 为浏览器上下文的所有新页面注入脚本
    await browser_context.add_init_script(anti_detection_js)
    # 对已有页面也注入
    for existing_page in browser_context.pages:
        try:
            await existing_page.evaluate(anti_detection_js)
        except Exception:
            pass
    utils.logger.info("[lead_browser] ✅ Anti-detection scripts injected")


async def launch_lead_browser(
    platform: str = "dy",
    user_id: int = 0,
    headless: bool = True,
) -> Tuple[BrowserContext, Page, Optional[CDPBrowserManager], object]:
    """启动获客采集专用浏览器(带缓存复用 + 反检测注入 + Cookie 加载)。

    Args:
        platform: 平台标识 dy/xhs
        user_id: 用户ID(用于读取用户专属 Cookie)
        headless: 是否无头模式(CDP 模式下建议 False,反检测效果更好)

    Returns:
        (browser_context, page, cdp_manager, playwright)
        - cdp_manager: CDPBrowserManager 实例(可能为 None,非 CDP 模式时)
        - playwright: Playwright 实例(调用方不应主动 stop,由缓存管理)

    调用方注意:
        返回的浏览器实例由本模块缓存管理,调用方不应主动关闭 browser_context 或 stop playwright。
        如需强制刷新浏览器,调用 close_cached_browser()。
    """
    global _cached_browser, _browser_last_used

    # 1. 检查是否有可复用的浏览器实例
    now = time.time()
    if _cached_browser is not None:
        if now - _browser_last_used > _BROWSER_CACHE_TTL:
            utils.logger.info("[lead_browser] Cached browser expired, closing...")
            await _close_cached_browser()
        else:
            # 验证浏览器是否仍然可用
            try:
                page = _cached_browser["page"]
                await page.evaluate("() => document.title")
                # 刷新 Cookie 确保登录状态
                await _load_platform_cookies(_cached_browser["browser_context"], platform, user_id=user_id)
                await page.reload(wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                login_ok = await _verify_login(page, platform)
                if login_ok:
                    utils.logger.info("[lead_browser] ✅ Reusing cached browser (login OK)")
                    _browser_last_used = now
                    return (_cached_browser["browser_context"], page,
                            _cached_browser["cdp_manager"], _cached_browser["playwright"])
                else:
                    utils.logger.warning("[lead_browser] Cached browser login expired, re-launching...")
                    await _close_cached_browser()
            except Exception as e:
                utils.logger.warning(f"[lead_browser] Cached browser unusable: {e}, re-launching...")
                await _close_cached_browser()

    # 2. 启动新浏览器
    cdp_manager: Optional[CDPBrowserManager] = None
    playwright = await async_playwright().start()

    # CDP 模式下启动 Xvfb,使 headed 模式可用(反检测效果更好)
    _ensure_xvfb()
    use_headless = headless if _is_headless_env() else False

    try:
        if getattr(config, 'ENABLE_CDP_MODE', False) or getattr(config, 'CDP_CONNECT_EXISTING', False):
            # CDP 模式:用独立 user_data_dir 避免与采集任务 Cookie 冲突
            if platform == "xhs":
                outreach_user_data = os.path.join(os.getcwd(), "browser_data", "cdp_xhs_lead_user_data_dir")
            else:
                outreach_user_data = os.path.join(os.getcwd(), "browser_data", "cdp_dy_lead_user_data_dir")
            os.makedirs(outreach_user_data, exist_ok=True)

            # 复制采集任务的 Cookies 到 lead 目录(确保登录状态)
            try:
                if platform == "xhs":
                    search_user_data = os.path.join(os.getcwd(), "browser_data", "cdp_xhs_user_data_dir")
                else:
                    search_user_data = os.path.join(os.getcwd(), "browser_data", "cdp_dy_user_data_dir")
                src_cookie = os.path.join(search_user_data, "Default", "Cookies")
                dst_cookie = os.path.join(outreach_user_data, "Default", "Cookies")
                dst_dir = os.path.dirname(dst_cookie)
                os.makedirs(dst_dir, exist_ok=True)
                if os.path.exists(src_cookie):
                    import shutil as _shutil
                    _shutil.copy2(src_cookie, dst_cookie)
                    # 也复制 Local Storage
                    src_ls = os.path.join(search_user_data, "Default", "Local Storage")
                    dst_ls = os.path.join(outreach_user_data, "Default", "Local Storage")
                    if os.path.exists(src_ls):
                        if os.path.exists(dst_ls):
                            _shutil.rmtree(dst_ls)
                        _shutil.copytree(src_ls, dst_ls)
                    utils.logger.info("[lead_browser] Copied login state from search browser")
            except Exception as e:
                utils.logger.warning(f"[lead_browser] Failed to copy login state: {e}")

            # 找一个可用端口(避免与采集任务 9222 冲突,用 9330-9429 区间)
            import socket
            import subprocess
            import httpx as _httpx
            available_port = None
            for port in range(9330, 9430):
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.bind(('localhost', port))
                        available_port = port
                        break
                except OSError:
                    # 端口被占用,检查 Chrome 是否存活;不存活则清理僵尸进程后重试
                    try:
                        _chk = _httpx.get(f"http://localhost:{port}/json/version", timeout=1)
                        if _chk.status_code == 200:
                            continue  # 存活 Chrome,跳过
                    except Exception:
                        pass
                    # Chrome 不响应,可能是僵尸进程,尝试 kill 后重试绑定
                    try:
                        _r = subprocess.run(['lsof', '-ti', f':{port}'], capture_output=True, text=True, timeout=3)
                        for _pid in _r.stdout.strip().split('\n'):
                            if _pid.strip().isdigit():
                                try:
                                    import os as _os, signal as _sig
                                    _os.kill(int(_pid.strip()), _sig.SIGKILL)
                                    utils.logger.info(f"[lead_browser] Killed stale Chrome PID {_pid} on port {port}")
                                except Exception:
                                    pass
                        time.sleep(0.5)
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.bind(('localhost', port))
                            available_port = port
                            break
                    except Exception:
                        continue
            if not available_port:
                raise RuntimeError("No available port for lead Chrome (ports 9330-9429 all occupied)")

            orig_debug_port = config.CDP_DEBUG_PORT
            config.CDP_DEBUG_PORT = available_port
            utils.logger.info(f"[lead_browser] Launching independent Chrome on port {available_port}")
            try:
                cdp_manager = CDPBrowserManager(user_data_dir_override=outreach_user_data)
                browser_context = await cdp_manager.launch_and_connect(playwright, headless=use_headless)
            except Exception as cdp_err:
                utils.logger.warning(
                    f"[lead_browser] CDP mode failed ({cdp_err}), "
                    f"falling back to Playwright Chromium persistent context"
                )
                # 降级:系统未安装 Chrome 时,使用 Playwright 内置 Chromium
                if platform == "xhs":
                    fb_user_data = os.path.join(os.getcwd(), "browser_data", "xhs_lead_user_data_dir")
                else:
                    fb_user_data = os.path.join(os.getcwd(), "browser_data", "dy_lead_user_data_dir")
                os.makedirs(fb_user_data, exist_ok=True)
                browser_context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=fb_user_data, headless=use_headless,
                    viewport={"width": 1920, "height": 1080},
                )
            finally:
                config.CDP_DEBUG_PORT = orig_debug_port
        else:
            # 非 CDP 模式:用 persistent context
            utils.logger.info("[lead_browser] Using persistent context mode")
            if platform == "xhs":
                user_data_dir = os.path.join(os.getcwd(), "browser_data", "xhs_lead_user_data_dir")
            else:
                user_data_dir = os.path.join(os.getcwd(), "browser_data", "dy_lead_user_data_dir")
            os.makedirs(user_data_dir, exist_ok=True)
            browser_context = await playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir, headless=use_headless,
                viewport={"width": 1920, "height": 1080},
            )

        page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})

        # 3. 导航并注入 Cookie
        if platform == "xhs":
            await page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=30000)
        else:
            await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        await _load_platform_cookies(browser_context, platform, user_id=user_id)
        await page.reload(wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # 4. 验证登录状态(带重试,避免网络抖动误判)
        login_ok = False
        for verify_attempt in range(3):
            login_ok = await _verify_login(page, platform)
            if login_ok:
                if verify_attempt > 0:
                    utils.logger.info(f"[lead_browser] ✅ Login recovered on retry {verify_attempt+1}")
                break
            utils.logger.warning(f"[lead_browser] Login verification failed (attempt {verify_attempt+1}/3)")
            if verify_attempt < 2:
                try:
                    home_url = "https://www.xiaohongshu.com" if platform == "xhs" else "https://www.douyin.com"
                    await page.goto(home_url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(3)
                    await page.reload(wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(2)
                except Exception as nav_err:
                    utils.logger.warning(f"[lead_browser] Re-nav before retry failed: {nav_err}")
        if not login_ok:
            await _close_cached_browser()
            raise Exception(f"{platform} 登录验证失败,请在 Cookie 管理中更新 Cookie 后重试")

        # 5. 注入反检测脚本
        await _inject_anti_detection(browser_context)

        # 6. 缓存浏览器实例
        _cached_browser = {
            "browser_context": browser_context,
            "page": page,
            "cdp_manager": cdp_manager,
            "playwright": playwright,
        }
        _browser_last_used = time.time()
        utils.logger.info("[lead_browser] ✅ Browser launched and cached for reuse")

        return browser_context, page, cdp_manager, playwright
    except Exception as e:
        # 启动失败时清理 playwright
        try:
            await playwright.stop()
        except Exception:
            pass
        raise e


async def close_cached_browser():
    """关闭缓存的浏览器实例(供外部强制刷新使用)。"""
    await _close_cached_browser()
