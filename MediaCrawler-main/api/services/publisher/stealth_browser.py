# -*- coding: utf-8 -*-
"""
共享的 Playwright 反检测浏览器工具

迁移自 GEO-main/geo_system/backend/stealth_browser.py，调整：
1. storage_state 默认目录改为 MediaCrawler 的 browser_data/publisher_state/
2. 兼容 ENABLE_CDP_MODE 环境变量（与项目主架构对齐）

为 douyin/xiaohongshu/bilibili/weibo/zhihu 等平台提供统一的反检测策略：
- Chrome 131 UA + sec-ch-ua headers
- 隐藏 webdriver 标志，伪造 plugins/platform/chrome runtime
- 完整启动参数（--disable-extensions / --lang=zh-CN 等）
- 支持 storage_state 持久化登录
"""

import logging
import os
import shutil
from typing import Optional

logger = logging.getLogger(__name__)


# storage_state 持久化目录（对齐 MediaCrawler 的 browser_data/ 约定）
_DEFAULT_STATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "browser_data",
    "publisher_state",
)


def _get_state_dir() -> str:
    """获取 storage_state 持久化目录

    优先用环境变量 PLATFORM_STATE_DIR，否则用 MediaCrawler 默认目录。
    """
    return os.environ.get("PLATFORM_STATE_DIR") or _DEFAULT_STATE_DIR


# 反检测启动参数（统一）
STEALTH_ARGS = [
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

# Chrome 131 UA（统一）
STEALTH_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

# 反检测 HTTP headers
STEALTH_HEADERS = {
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
}

# 反检测 init_script（隐藏 webdriver / 伪造 plugins / 伪装 chrome runtime）
STEALTH_INIT_SCRIPT = """
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
"""


async def launch_stealth_browser(playwright, headless: bool = True, proxy: Optional[str] = None):
    """启动反检测 Chromium 浏览器

    优先使用系统 Chrome（更不易被风控识别），否则使用 Playwright 内置 Chromium。
    若环境变量 ENABLE_CDP_MODE=1，会尝试通过 CDP 连接已存在的 Chrome 实例。

    Args:
        playwright: Playwright 实例
        headless: 是否无头模式
        proxy: 代理 URL（如 "http://user:pass@host:port"），用于地域适配
    """
    enable_cdp = os.environ.get("ENABLE_CDP_MODE", "0") == "1"
    cdp_endpoint = os.environ.get("CDP_ENDPOINT", "").strip()

    # 构造 proxy 字典（地域适配）
    proxy_dict = None
    if proxy:
        proxy_dict = _parse_proxy_url(proxy)
        logger.info(f"[StealthBrowser] 使用代理: {proxy}")

    # CDP 模式不支持代理（连接的是已存在的浏览器）
    if enable_cdp and cdp_endpoint and not proxy_dict:
        try:
            logger.info(f"[StealthBrowser] 通过 CDP 连接: {cdp_endpoint}")
            browser = await playwright.chromium.connect_over_cdp(cdp_endpoint)
            return browser
        except Exception as e:
            logger.warning(f"[StealthBrowser] CDP 连接失败，回退到独立启动: {e}")

    chrome_path = (
        shutil.which('google-chrome')
        or shutil.which('chromium')
        or shutil.which('chromium-browser')
    )

    if chrome_path:
        logger.info(f"[StealthBrowser] 使用系统 Chrome: {chrome_path}")
        browser = await playwright.chromium.launch(
            executable_path=chrome_path,
            headless=headless,
            args=STEALTH_ARGS,
            proxy=proxy_dict,
        )
    else:
        logger.info("[StealthBrowser] 使用 Playwright 内置 Chromium")
        browser = await playwright.chromium.launch(
            headless=headless,
            args=STEALTH_ARGS,
            proxy=proxy_dict,
        )
    return browser


def _parse_proxy_url(proxy_url: str) -> Optional[dict]:
    """解析代理 URL 为 Playwright proxy 字典

    支持：
    - http://user:pass@host:port
    - http://host:port
    - socks5://host:port
    """
    if not proxy_url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(proxy_url)
        result = {
            "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
        }
        if parsed.username:
            result["username"] = parsed.username
        if parsed.password:
            result["password"] = parsed.password
        return result
    except Exception as e:
        logger.warning(f"[StealthBrowser] 代理 URL 解析失败: {proxy_url} - {e}")
        return None


async def create_stealth_context(browser, storage_state: Optional[dict] = None):
    """创建反检测浏览器上下文

    Args:
        browser: Playwright Browser 实例
        storage_state: 可选的 storage_state（持久化登录状态）

    Returns:
        BrowserContext（已注入反检测脚本，可直接 new_page）
    """
    context_kwargs = dict(
        viewport={'width': 1920, 'height': 1080},
        user_agent=STEALTH_UA,
        locale='zh-CN',
        timezone_id='Asia/Shanghai',
        geolocation={'latitude': 31.2304, 'longitude': 121.4737},  # 上海
        permissions=['geolocation'],
        color_scheme='light',
        is_mobile=False,
        has_touch=False,
        device_scale_factor=1,
        extra_http_headers=STEALTH_HEADERS,
    )
    if storage_state:
        context_kwargs['storage_state'] = storage_state
        logger.info("[StealthBrowser] 使用 storage_state 创建上下文（持久化登录）")

    context = await browser.new_context(**context_kwargs)

    # 注入反检测脚本（在每个页面加载前执行）
    await context.add_init_script(STEALTH_INIT_SCRIPT)
    logger.info("[StealthBrowser] 反检测脚本已注入")

    return context


def get_storage_state_path(platform: str, user_id: int) -> str:
    """获取平台 storage_state 文件路径

    Args:
        platform: 平台标识（douyin / xiaohongshu / bilibili / weibo / zhihu）
        user_id: 用户 ID
    """
    return os.path.join(_get_state_dir(), f'{platform}_user_{user_id}.json')


def ensure_state_dir() -> str:
    """确保 storage_state 目录存在，返回目录路径"""
    state_dir = _get_state_dir()
    os.makedirs(state_dir, exist_ok=True)
    return state_dir
