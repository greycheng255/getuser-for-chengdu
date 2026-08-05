# -*- coding: utf-8 -*-
"""反检测脚本与浏览器指纹读取工具。

职责:
1. get_anti_detect_script() 返回完整反检测 JS 字符串,
   覆盖 stealth.min.js 缺失的项(WebRTC 防护/deviceMemory/platform/AudioContext/
   languages/permissions.query/iframe contentWindow.webdriver)。
2. read_browser_fingerprint() 启动后读取一次浏览器真实指纹,缓存复用。
3. infer_os_params() 从 UA 反推 os_name/browser_platform,保证参数与 UA 一致。

设计原则:CDP 模式与标准模式都注入本脚本,避免原 CDP 模式只注入 stealth.min.js
导致反检测不完整的漏洞。
"""
import re
from typing import Dict

from playwright.async_api import Page


def get_anti_detect_script() -> str:
    """返回完整的反检测 JS 字符串。

    覆盖 stealth.min.js 缺失的项:
    - navigator.languages / permissions.query(原 anti_detect_js 已有,CDP 模式缺失)
    - WebRTC IP 泄漏防护(代理时关键)
    - navigator.deviceMemory(stealth 未覆盖)
    - AudioContext 指纹随机化
    - WebGL2RenderingContext(原只伪装 v1)
    - iframe contentWindow.webdriver 跨域清除
    """
    return r"""
    // === 原有项(从 core.py:1639-1666 迁移,保持标准模式行为一致)===
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    if (!window.chrome) { window.chrome = {}; }
    if (!window.chrome.runtime) { window.chrome.runtime = { connect: () => {}, sendMessage: () => {} }; }
    if (!window.chrome.app) { window.chrome.app = { isInstalled: false }; }
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
    delete window.__playwright__evaluation_script;
    // permissions API 伪装(notifications 返回当前权限状态)
    const _oq = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : _oq(parameters);
    // WebGL v1 渲染器伪装
    const _gp = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';          // UNMASKED_VENDOR_WEBGL
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
        return _gp.call(this, parameter);
    };

    // === 新增项(stealth.min.js 未覆盖)===
    // 1. WebGL2 也伪装(stealth 只覆盖 v1)
    if (typeof WebGL2RenderingContext !== 'undefined') {
        const _gp2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return _gp2.call(this, parameter);
        };
    }
    // 2. WebRTC IP 泄漏防护(代理时关键,屏蔽 srflx/host 候选,只保留 relay)
    const _RTCPeerConnection = window.RTCPeerConnection || window.webkitRTCPeerConnection;
    if (_RTCPeerConnection) {
        const _origAddIceCandidate = _RTCPeerConnection.prototype.addIceCandidate;
        _RTCPeerConnection.prototype.addIceCandidate = function(candidate) {
            const c = (candidate && candidate.candidate) || '';
            // 过滤 server-reflexive 和 host 候选,避免泄漏真实 IP
            if (c.indexOf('srflx') !== -1 || c.indexOf('host') !== -1) {
                return Promise.resolve();
            }
            return _origAddIceCandidate.call(this, candidate);
        };
    }
    // 3. deviceMemory 伪装(stealth 未覆盖)
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    // 4. AudioContext 指纹随机化(常被用于设备指纹)
    const _AudioContext = window.AudioContext || window.webkitAudioContext;
    if (_AudioContext) {
        const _origCreateOscillator = _AudioContext.prototype.createOscillator;
        _AudioContext.prototype.createOscillator = function() {
            const osc = _origCreateOscillator.call(this);
            // 微小随机扰动破坏指纹稳定性(不影响可听性)
            const _origFreq = osc.frequency.value;
            osc.frequency.value = _origFreq + (Math.random() * 0.0001);
            return osc;
        };
    }
    // 5. iframe contentWindow.webdriver 跨域清除(检测脚本会跨 iframe 读取)
    try {
        const _iframeDesc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
        if (_iframeDesc && _iframeDesc.get) {
            const _origContentWindow = _iframeDesc.get;
            Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
                get: function() {
                    const w = _origContentWindow.call(this);
                    try {
                        if (w && w.navigator) {
                            Object.defineProperty(w.navigator, 'webdriver', { get: () => undefined });
                        }
                    } catch (e) {
                        // 跨域 iframe 访问 navigator 会抛异常,忽略
                    }
                    return w;
                }
            });
        }
    } catch (e) {}
    """


async def read_browser_fingerprint(page: Page) -> Dict:
    """启动后读取一次浏览器真实指纹,缓存复用。

    读取项:navigator.platform/hardwareConcurrency/deviceMemory、
           screen.width/height、navigator.connection.effectiveType、UA。

    失败时返回空 dict,调用方回退到 infer_os_params 推断值。

    Args:
        page: 已导航到抖音首页的 Playwright Page

    Returns:
        Dict: {platform, hardwareConcurrency, deviceMemory, screenWidth,
               screenHeight, effectiveType, userAgent}
    """
    try:
        return await page.evaluate("""
            () => ({
                platform: navigator.platform,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemory: navigator.deviceMemory || 8,
                screenWidth: window.screen.width,
                screenHeight: window.screen.height,
                effectiveType: (navigator.connection && navigator.connection.effectiveType) || '4g',
                userAgent: navigator.userAgent,
            })
        """)
    except Exception:
        return {}


def infer_os_params(user_agent: str) -> Dict:
    """从 UA 反推 os_name / browser_platform,保证参数与 UA 一致。

    消除原 client.py 写死 Mac 但浏览器跑在 Linux 的不一致问题。
    UA 优先级:cookie 提取的 UA > 浏览器 navigator UA > 默认 UA。

    Args:
        user_agent: User-Agent 字符串

    Returns:
        Dict: {os_name, os_version, browser_platform, browser_name, engine_name}
    """
    ua = user_agent or ""
    if "Windows" in ua:
        m = re.search(r"Windows NT ([\d.]+)", ua)
        win_ver = m.group(1) if m else "10.0"
        return {
            "os_name": "Windows",
            "os_version": win_ver,
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "engine_name": "Blink",
        }
    elif "Macintosh" in ua or "Mac OS" in ua:
        m = re.search(r"Mac OS X ([\d_]+)", ua)
        mac_ver = m.group(1).replace("_", ".") if m else "10.15.7"
        return {
            "os_name": "Mac OS",
            "os_version": mac_ver,
            "browser_platform": "MacIntel",
            "browser_name": "Chrome",
            "engine_name": "Blink",
        }
    elif "Linux" in ua:
        return {
            "os_name": "Linux",
            "os_version": "x86_64",
            "browser_platform": "Linux x86_64",
            "browser_name": "Chrome",
            "engine_name": "Blink",
        }
    # 默认回退 Mac(保持与旧版兼容,避免空值)
    return {
        "os_name": "Mac OS",
        "os_version": "10.15.7",
        "browser_platform": "MacIntel",
        "browser_name": "Chrome",
        "engine_name": "Blink",
    }


def infer_sec_ch_ua_platform(user_agent: str) -> str:
    """根据 UA 返回 sec-ch-ua-platform 请求头的值(带引号)。

    Args:
        user_agent: User-Agent 字符串

    Returns:
        str: '"Windows"' / '"macOS"' / '"Linux"'
    """
    os_name = infer_os_params(user_agent)["os_name"]
    if os_name == "Windows":
        return '"Windows"'
    elif os_name == "Mac OS":
        return '"macOS"'
    elif os_name == "Linux":
        return '"Linux"'
    return '"Windows"'
