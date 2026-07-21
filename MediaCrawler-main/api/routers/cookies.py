# -*- coding: utf-8 -*-
"""Cookie 管理路由"""
import os
import json
import asyncio
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..services.cookie_manager import (
    get_cookie, set_cookie, get_all_cookies as get_all_cookies_from_manager,
    get_user_cookie, get_user_cookie_pool, get_all_user_cookies,
    set_user_cookie, add_user_cookie_to_pool, remove_user_cookie, clear_user_cookie_pool,
)
from ..services.auth import get_current_user, require_admin

router = APIRouter(prefix="/cookies", tags=["cookies"])


# ============================================================
# Cookie 校验器：校验平台必需的登录态字段
# ============================================================
def validate_cookie_for_platform(platform: str, cookie: str) -> Tuple[bool, List[str]]:
    """校验Cookie是否包含平台必需的登录态字段

    Returns:
        (是否有效, 缺失字段列表)
    """
    missing: List[str] = []
    if platform == "dy":
        if "sessionid" not in cookie:
            missing.append("sessionid（抖音登录态核心字段）")
        if "sessionid_ss" not in cookie:
            missing.append("sessionid_ss")
        if "uid_tt" not in cookie:
            missing.append("uid_tt")
    elif platform == "xhs":
        if "web_session" not in cookie and "customer-session-id" not in cookie:
            missing.append("web_session（小红书登录态核心字段）")
    elif platform == "wb":
        if "SUB" not in cookie:
            missing.append("SUB（微博登录态核心字段）")
    elif platform == "ks":
        if "passToken" not in cookie and "userId" not in cookie:
            missing.append("passToken/userId（快手登录态核心字段）")
    elif platform == "bili":
        if "SESSDATA" not in cookie:
            missing.append("SESSDATA（B站登录态核心字段）")
    elif platform == "x_twitter":
        if "auth_token" not in cookie and "ct0" not in cookie:
            missing.append("auth_token/ct0（X平台登录态核心字段）")
    return (len(missing) == 0, missing)

# 平台 Cookie 配置
PLATFORM_COOKIES = {
    "xhs": {
        "name": "小红书",
        "env_key": "XHS_COOKIES",
        "check_field": "web_session",
        "required_fields": ["web_session", "a1"],
        "login_tip": "请从浏览器开发者工具 -> Application -> Cookies 中复制完整的登录态 Cookie，确保包含 web_session 字段"
    },
    "dy": {
        "name": "抖音",
        "env_key": "DY_COOKIES",
        "check_field": "sessionid",
        "required_fields": ["sessionid", "sid_guard", "sid_tt", "uid_tt"],
        "login_tip": "请从浏览器开发者工具 -> Application -> Cookies -> https://www.douyin.com 中复制完整的登录态 Cookie，确保包含 sessionid 字段（表示已登录）"
    },
    "ks": {
        "name": "快手",
        "env_key": "KS_COOKIES",
        "check_field": "kuaishou.web_st",
        "required_fields": ["kuaishou.web_st", "clientid", "client_key"],
        "login_tip": "请从浏览器开发者工具中复制完整的登录态 Cookie"
    },
    "bili": {
        "name": "B站",
        "env_key": "BILI_COOKIES",
        "check_field": "SESSDATA",
        "required_fields": ["SESSDATA", "bili_jct", "DedeUserID"],
        "login_tip": "请从浏览器开发者工具中复制完整的登录态 Cookie，确保包含 SESSDATA 字段"
    },
    "wb": {
        "name": "微博",
        "env_key": "WB_COOKIES",
        "check_field": "SUB",
        "required_fields": ["SUB", "SUBP"],
        "login_tip": "请从浏览器开发者工具中复制完整的登录态 Cookie，确保包含 SUB 字段"
    },
    "x_twitter": {
        "name": "X",
        "env_key": "X_TWITTER_COOKIES",
        "check_field": "auth_token",
        "required_fields": ["auth_token", "ct0", "guest_id"],
        "login_tip": "请从浏览器开发者工具 -> Application -> Cookies -> https://x.com 中复制完整的登录态 Cookie，确保包含 auth_token 或 ct0 字段"
    },
}


def _parse_netscape_cookie(content: str) -> str:
    """
    解析 Netscape 格式的 Cookie 文件
    格式: domain	flag	path	secure	expiration	name	value
    或: name	value	domain	path	expires	size	httpOnly	secure	sameSite	priority
    """
    cookie_pairs = []
    lines = content.strip().split("\n")
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        parts = line.split("	")
        
        if len(parts) >= 7:
            if "." in parts[0] and (".com" in parts[0] or ".cn" in parts[0] or ".net" in parts[0]):
                if len(parts) >= 7:
                    name = parts[5].strip()
                    value = parts[6].strip()
                    if name and value:
                        cookie_pairs.append(f"{name}={value}")
            else:
                name = parts[0].strip()
                value = parts[1].strip()
                if len(parts) >= 3 and "." in parts[2]:
                    if name and value and name not in ["None", "", "✓"]:
                        cookie_pairs.append(f"{name}={value}")
        elif len(parts) == 2:
            name = parts[0].strip()
            value = parts[1].strip()
            if name and value:
                cookie_pairs.append(f"{name}={value}")
    
    return "; ".join(cookie_pairs)


def _parse_cookie_input(raw_input: str, platform: str) -> str:
    """
    智能解析用户粘贴的 Cookie 输入，支持多种格式
    返回标准化的 Cookie 字符串: key1=value1; key2=value2
    """
    raw_input = raw_input.strip()
    if not raw_input:
        return ""
    
    if "	" in raw_input:
        return _parse_netscape_cookie(raw_input)
    
    if raw_input.startswith("[") or raw_input.startswith("{"):
        try:
            data = json.loads(raw_input)
            if isinstance(data, list):
                cookie_pairs = []
                for item in data:
                    if isinstance(item, dict) and "name" in item and "value" in item:
                        cookie_pairs.append(f"{item['name']}={item['value']}")
                return "; ".join(cookie_pairs)
            elif isinstance(data, dict):
                cookie_pairs = [f"{k}={v}" for k, v in data.items()]
                return "; ".join(cookie_pairs)
        except json.JSONDecodeError:
            pass
    
    lines = raw_input.split("\n")
    if len(lines) > 1:
        cookie_pairs = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            
            if line.lower().startswith("cookie:"):
                line = line[7:].strip()
            
            if ":" in line and "=" not in line.split(":")[0]:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    if key and value:
                        cookie_pairs.append(f"{key}={value}")
            elif "=" in line:
                parts = line.split("=", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    value = value.rstrip(",;")
                    if key and value:
                        cookie_pairs.append(f"{key}={value}")
        
        if cookie_pairs:
            return "; ".join(cookie_pairs)
    
    if raw_input.lower().startswith("cookie:"):
        raw_input = raw_input[7:].strip()
    
    cookies = raw_input.split(";")
    cleaned = []
    for cookie in cookies:
        cookie = cookie.strip()
        if cookie and "=" in cookie:
            cleaned.append(cookie)
    
    return "; ".join(cleaned)


def _format_cookie_for_platform(cookie_str: str, platform: str) -> str:
    """根据平台需求格式化 Cookie 字符串"""
    if not cookie_str:
        return ""
    
    cookie_dict = {}
    for cookie in cookie_str.split(";"):
        cookie = cookie.strip()
        if not cookie:
            continue
        parts = cookie.split("=", 1)
        if len(parts) == 2:
            key = parts[0].strip()
            value = parts[1].strip()
            if key:
                cookie_dict[key] = value
    
    if platform == "dy":
        if "passport_csrf_token" in cookie_dict and "passport_csrf_token_default" not in cookie_dict:
            cookie_dict["passport_csrf_token_default"] = cookie_dict["passport_csrf_token"]
    elif platform == "xhs":
        pass
    
    cookie_pairs = [f"{k}={v}" for k, v in cookie_dict.items()]
    return "; ".join(cookie_pairs)


class CookieUpdateRequest(BaseModel):
    platform: str
    cookies: str


@router.get("")
async def get_all_cookies(current_user: dict = Depends(get_current_user)):
    """获取所有平台的 Cookie 状态(按用户隔离)"""
    user_id = current_user["id"]
    user_cookies = await get_all_user_cookies(user_id)
    result = {}
    for platform_id, config in PLATFORM_COOKIES.items():
        info = user_cookies.get(platform_id, {})
        cookies_len = info.get("cookie_length", 0)
        result[platform_id] = {
            "name": config["name"],
            "platform": platform_id,
            "has_cookie": info.get("has_cookie", False),
            "cookie_length": cookies_len,
            "pool_size": info.get("pool_size", 0),
            "status": "已配置" if cookies_len > 0 else "未配置",
            "check_field": config["check_field"]
        }
    return result


@router.post("/update")
async def update_cookie(request: CookieUpdateRequest, current_user: dict = Depends(get_current_user)):
    """更新指定平台的 Cookie(按用户隔离)"""
    platform = request.platform
    raw_cookies = request.cookies

    if platform not in PLATFORM_COOKIES:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    config = PLATFORM_COOKIES[platform]

    try:
        parsed_cookies = _parse_cookie_input(raw_cookies, platform)

        if not parsed_cookies:
            raise HTTPException(status_code=400, detail="Cookie 格式不正确，无法解析")

        formatted_cookies = _format_cookie_for_platform(parsed_cookies, platform)

        cookie_dict = {}
        for cookie in formatted_cookies.split(";"):
            cookie = cookie.strip()
            if not cookie:
                continue
            parts = cookie.split("=", 1)
            if len(parts) == 2:
                cookie_dict[parts[0].strip()] = parts[1].strip()

        check_field = config["check_field"]
        if check_field not in cookie_dict:
            required_fields = config.get("required_fields", [])
            missing = [f for f in required_fields if f not in cookie_dict]
            raise HTTPException(
                status_code=400,
                detail=f"Cookie 缺少关键登录字段 '{check_field}'，无法用于登录。缺少的字段: {', '.join(missing)}。{config.get('login_tip', '')}"
            )

        user_id = current_user["id"]
        success = await set_user_cookie(user_id, platform, formatted_cookies)
        if not success:
            raise HTTPException(status_code=500, detail="Cookie 保存失败")

        if current_user.get("role") == "admin":
            try:
                set_cookie(platform, formatted_cookies)
            except Exception:
                pass

        return {
            "success": True,
            "message": f"{config['name']} Cookie 更新成功",
            "platform": platform,
            "cookie_length": len(formatted_cookies),
            "parsed_length": len(parsed_cookies)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.post("/parse")
async def parse_cookie(request: CookieUpdateRequest, current_user: dict = Depends(get_current_user)):
    """预览 Cookie 解析结果，不保存"""
    platform = request.platform
    raw_cookies = request.cookies

    if platform not in PLATFORM_COOKIES:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    try:
        parsed = _parse_cookie_input(raw_cookies, platform)
        formatted = _format_cookie_for_platform(parsed, platform)
        
        cookie_dict = {}
        for cookie in formatted.split(";"):
            cookie = cookie.strip()
            if not cookie:
                continue
            parts = cookie.split("=", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                display_value = value[:15] + "..." if len(value) > 20 else value
                cookie_dict[key] = display_value
        
        config = PLATFORM_COOKIES[platform]
        required_fields = config.get("required_fields", [])
        missing_fields = [f for f in required_fields if f not in cookie_dict]
        has_login_field = config["check_field"] in cookie_dict
        
        return {
            "success": True,
            "platform": platform,
            "original_length": len(raw_cookies),
            "parsed_length": len(parsed),
            "formatted_length": len(formatted),
            "cookie_keys": list(cookie_dict.keys()),
            "cookie_preview": cookie_dict,
            "formatted_cookie": formatted,
            "has_login_field": has_login_field,
            "check_field": config["check_field"],
            "missing_fields": missing_fields,
            "required_fields": required_fields,
            "login_tip": config.get("login_tip", "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")


@router.get("/check/{platform}")
async def check_cookie(platform: str, current_user: dict = Depends(get_current_user)):
    """检测指定平台的 Cookie 是否有效(按用户隔离)"""
    if platform not in PLATFORM_COOKIES:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    config = PLATFORM_COOKIES[platform]
    user_id = current_user["id"]
    cookies = ""
    try:
        cookies = await get_user_cookie(user_id, platform)
    except Exception:
        pass
    if not cookies:
        cookies = os.getenv(config["env_key"], "")

    if not cookies:
        return {
            "valid": False,
            "message": f"{config['name']} Cookie 未配置",
            "platform": platform
        }

    check_field = config["check_field"]
    if check_field in cookies:
        return {
            "valid": True,
            "message": f"{config['name']} Cookie 格式正确",
            "platform": platform,
            "check_field": check_field,
            "has_key_field": True
        }
    else:
        return {
            "valid": False,
            "message": f"{config['name']} Cookie 缺少关键字段: {check_field}",
            "platform": platform,
            "check_field": check_field,
            "has_key_field": False
        }


@router.post("/test/{platform}")
async def test_cookie(platform: str, current_user: dict = Depends(get_current_user)):
    """使用 Playwright 实际测试 Cookie 是否能登录(按用户隔离)"""
    if platform not in PLATFORM_COOKIES:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    config = PLATFORM_COOKIES[platform]
    user_id = current_user["id"]
    cookies = ""
    try:
        cookies = await get_user_cookie(user_id, platform)
    except Exception:
        pass
    if not cookies:
        cookies = os.getenv(config["env_key"], "")

    if not cookies:
        return {
            "success": False,
            "message": f"{config['name']} Cookie 未配置",
            "platform": platform
        }

    try:
        from playwright.async_api import async_playwright
        from tools.crawler_util import convert_str_cookie_to_dict
    except ImportError as e:
        return {
            "success": False,
            "message": f"Playwright 未安装或导入失败: {str(e)}",
            "platform": platform
        }

    platform_urls = {
        "xhs": "https://www.xiaohongshu.com",
        "dy": "https://www.douyin.com",
        "bili": "https://www.bilibili.com",
        "x_twitter": "https://x.com"
    }

    url = platform_urls.get(platform, "https://www.xiaohongshu.com")

    try:
        result = await _test_cookie_with_playwright(platform, cookies, url, config["name"])
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"测试失败: {str(e)}",
            "platform": platform
        }


async def _test_cookie_with_playwright(platform: str, cookies: str, url: str, platform_name: str) -> dict:
    """使用 Playwright 实际测试 Cookie 登录状态"""
    from tools.crawler_util import convert_str_cookie_to_dict

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        cookie_dict = convert_str_cookie_to_dict(cookies)
        cookies_to_add = []

        if platform == "xhs":
            domain = ".xiaohongshu.com"
        elif platform == "dy":
            domain = ".douyin.com"
        elif platform == "bili":
            domain = ".bilibili.com"
        elif platform == "x_twitter":
            domain = ".x.com"
        else:
            domain = ".xiaohongshu.com"

        for key, value in cookie_dict.items():
            cookies_to_add.append({
                "name": key,
                "value": value,
                "domain": domain,
                "path": "/"
            })

        await context.add_cookies(cookies_to_add)

        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        is_logged_in = False
        login_indicators = []

        if platform == "xhs":
            try:
                user_info = await page.evaluate("""
                    () => {
                        const user = window.__INITIAL_SSR_STATE__?.user?.userInfo;
                        if (user && user.nickname) return { logged_in: true, nickname: user.nickname };
                        const avatar = document.querySelector('.user-avatar');
                        const nickname = document.querySelector('.user-nickname');
                        if (nickname) return { logged_in: true, nickname: nickname.textContent };
                        return { logged_in: false };
                    }
                """)
                is_logged_in = user_info.get("logged_in", False)
                if is_logged_in:
                    login_indicators.append(f"用户: {user_info.get('nickname', '未知')}")
            except Exception as e:
                login_indicators.append(f"检查失败: {str(e)}")

        elif platform == "dy":
            try:
                local_storage = await page.evaluate("() => window.localStorage")
                has_login = local_storage.get("HasUserLogin") == "1" or local_storage.get("has_login") == "1"
                page_cookies = await context.cookies()
                has_session = any(c["name"] in ["sessionid", "sid_guard", "sid_tt"] for c in page_cookies)
                is_logged_in = has_login or has_session
                if has_login:
                    login_indicators.append("localStorage 登录标记")
                if has_session:
                    login_indicators.append("Session Cookie")
            except Exception as e:
                login_indicators.append(f"检查失败: {str(e)}")

        elif platform == "bili":
            try:
                user_info = await page.evaluate("""
                    () => {
                        const avatar = document.querySelector('.header-entry-avatar');
                        const username = document.querySelector('.header-entry-username');
                        if (avatar || username) return { logged_in: true };
                        const face = document.querySelector('.face');
                        if (face) return { logged_in: true };
                        return { logged_in: false };
                    }
                """)
                is_logged_in = user_info.get("logged_in", False)
                if is_logged_in:
                    login_indicators.append("用户头像/用户名")
            except Exception as e:
                login_indicators.append(f"检查失败: {str(e)}")

        elif platform == "x_twitter":
            try:
                user_info = await page.evaluate("""
                    () => {
                        const profileButton = document.querySelector('[data-testid="AppTabBar_Profile_Link"]');
                        const loginButton = document.querySelector('[data-testid="login"]');
                        return { logged_in: false };
                    }
                """)
                is_logged_in = user_info.get("logged_in", False)
                if is_logged_in:
                    login_indicators.append("用户已登录")
            except Exception as e:
                login_indicators.append(f"检查失败: {str(e)}")

        await browser.close()

        if is_logged_in:
            return {
                "success": True,
                "logged_in": True,
                "message": f"{platform_name} 登录成功！{' | '.join(login_indicators)}",
                "platform": platform,
                "indicators": login_indicators
            }
        else:
            return {
                "success": True,
                "logged_in": False,
                "message": f"{platform_name} Cookie 已配置但未检测到登录状态，可能需要更新 Cookie",
                "platform": platform,
                "indicators": login_indicators
            }


# ============================================================
# Cookie 池管理 API（多Cookie支持）
# ============================================================
from ..services.cookie_manager import get_cookie_pool  # noqa: F401


@router.get("/pool")
async def get_pool(platform: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """获取Cookie池状态(按用户隔离)"""
    user_id = current_user["id"]
    if platform:
        pool = await get_user_cookie_pool(user_id, platform)
        return {
            "platform": platform,
            "pool_size": len(pool),
            "valid_count": sum(1 for c in pool if _cookie_has_session(platform, c["cookie"])),
            "invalid_count": sum(1 for c in pool if not _cookie_has_session(platform, c["cookie"])),
            "cookies": [
                {
                    "id": c["id"],
                    "index": i,
                    "cookie_length": len(c["cookie"]),
                    "cookie_preview": c["cookie"][:80] + "..." if len(c["cookie"]) > 80 else c["cookie"],
                    "has_session": _cookie_has_session(platform, c["cookie"]),
                    "is_valid": _cookie_has_session(platform, c["cookie"]),
                    "alias": c.get("alias", ""),
                    "created_ts": c.get("created_ts", 0),
                }
                for i, c in enumerate(pool)
            ],
        }
    else:
        result = {}
        for plat in PLATFORM_COOKIES.keys():
            pool = await get_user_cookie_pool(user_id, plat)
            result[plat] = {
                "pool_size": len(pool),
                "valid_count": sum(1 for c in pool if _cookie_has_session(plat, c["cookie"])),
                "invalid_count": sum(1 for c in pool if not _cookie_has_session(plat, c["cookie"])),
                "cookies": [
                    {
                        "id": c["id"],
                        "index": i,
                        "cookie_length": len(c["cookie"]),
                        "cookie_preview": c["cookie"][:80] + "..." if len(c["cookie"]) > 80 else c["cookie"],
                        "has_session": _cookie_has_session(plat, c["cookie"]),
                        "is_valid": _cookie_has_session(plat, c["cookie"]),
                        "alias": c.get("alias", ""),
                        "created_ts": c.get("created_ts", 0),
                    }
                    for i, c in enumerate(pool)
                ],
            }
        return result


def _cookie_has_session(platform: str, cookie: str) -> bool:
    """检查Cookie是否包含平台必需的登录态字段"""
    if platform == "dy":
        return "sessionid" in cookie
    elif platform == "xhs":
        return "web_session" in cookie or "customer-session-id" in cookie
    elif platform == "wb":
        return "SUB" in cookie
    elif platform == "ks":
        return "passToken" in cookie or "userId" in cookie
    elif platform == "bili":
        return "SESSDATA" in cookie
    elif platform == "x_twitter":
        return "auth_token" in cookie or "ct0" in cookie or "guest_id" in cookie
    return True


@router.post("/pool/add")
async def add_to_pool(
    platform: str,
    cookie: str,
    alias: str = "",
    current_user: dict = Depends(get_current_user)
):
    """添加Cookie到Cookie池(按用户隔离,自动解析非标准格式)"""
    if platform not in PLATFORM_COOKIES:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    if not cookie or len(cookie.strip()) < 20:
        raise HTTPException(status_code=400, detail="Cookie内容过短，请检查")

    raw_cookie = cookie.strip()
    try:
        parsed_cookie = _parse_cookie_input(raw_cookie, platform)
        parsed_cookie = _format_cookie_for_platform(parsed_cookie, platform)
    except Exception as e:
        return {
            "success": False,
            "message": f"Cookie解析失败：{str(e)}",
            "session_valid": False,
            "hint": "请确保Cookie格式为 key1=value1; key2=value2 或从浏览器复制的完整Cookie",
        }

    if not parsed_cookie or len(parsed_cookie) < 20:
        return {
            "success": False,
            "message": "Cookie解析失败：未解析到有效字段",
            "session_valid": False,
            "hint": "请确保Cookie格式为 key1=value1; key2=value2 或从浏览器复制的完整Cookie",
        }

    is_valid, missing_fields = validate_cookie_for_platform(platform, parsed_cookie)
    if not is_valid:
        return {
            "success": False,
            "message": f"Cookie无效：缺少 {'、'.join(missing_fields)}。请重新从浏览器获取完整Cookie",
            "session_valid": False,
            "missing_fields": missing_fields,
            "parsed_preview": parsed_cookie[:80] + "..." if len(parsed_cookie) > 80 else parsed_cookie,
            "parsed_field_count": parsed_cookie.count("="),
            "hint": "请按F12打开开发者工具 → Application/应用 → Cookies → 复制全部Cookie（包含sessionid等登录态字段）",
        }

    user_id = current_user["id"]
    success = await add_user_cookie_to_pool(user_id, platform, parsed_cookie)
    if success:
        pool = await get_user_cookie_pool(user_id, platform)
        return {
            "success": True,
            "message": f"Cookie已添加到{platform}池（解析为{parsed_cookie.count('=')}个字段）",
            "pool_size": len(pool),
            "session_valid": True,
            "parsed_field_count": parsed_cookie.count("="),
        }
    return {
        "success": False,
        "message": "添加失败（数据库写入失败）",
        "session_valid": False,
    }


@router.post("/pool/clear-invalid")
async def clear_invalid_cookies(platform: str, current_user: dict = Depends(get_current_user)):
    """清理Cookie池中无登录态的无效Cookie(按用户隔离)"""
    if platform not in PLATFORM_COOKIES:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    user_id = current_user["id"]
    pool = await get_user_cookie_pool(user_id, platform)
    invalid_ids = [c["id"] for c in pool if not _cookie_has_session(platform, c["cookie"])]
    removed_count = 0
    for cid in invalid_ids:
        if await remove_user_cookie(user_id, cid):
            removed_count += 1
    pool_after = await get_user_cookie_pool(user_id, platform)
    return {
        "success": True,
        "message": f"已清理 {removed_count} 个无效Cookie，剩余 {len(pool_after)} 个有效Cookie",
        "removed": removed_count,
        "remaining": len(pool_after),
    }


@router.post("/pool/remove")
async def remove_from_pool(
    platform: str,
    cookie_id: int = None,
    cookie: str = None,
    current_user: dict = Depends(get_current_user)
):
    """从Cookie池移除Cookie(按用户隔离,支持 by id 或 by cookie_str)"""
    user_id = current_user["id"]
    if cookie_id:
        success = await remove_user_cookie(user_id, cookie_id)
    elif cookie:
        pool = await get_user_cookie_pool(user_id, platform)
        target = next((c for c in pool if c["cookie"] == cookie), None)
        if target:
            success = await remove_user_cookie(user_id, target["id"])
        else:
            success = False
    else:
        return {"success": False, "message": "需要提供 cookie_id 或 cookie 参数"}
    pool_after = await get_user_cookie_pool(user_id, platform)
    if success:
        return {"success": True, "message": "Cookie已移除", "pool_size": len(pool_after)}
    return {"success": False, "message": "Cookie不存在于池中"}


@router.post("/pool/clear")
async def clear_pool(platform: str, current_user: dict = Depends(get_current_user)):
    """清空Cookie池(按用户隔离)"""
    if platform not in PLATFORM_COOKIES:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    user_id = current_user["id"]
    success = await clear_user_cookie_pool(user_id, platform)
    if success:
        return {"success": True, "message": f"已清空{platform}的Cookie池", "pool_size": 0}
    return {"success": False, "message": "清空失败"}


# ============================================================
# 账号池管理 API（多Cookie+多IP组合管理）
# ============================================================
from ..services.account_pool import get_account_pool

@router.get("/accounts")
async def get_accounts(
    platform: Optional[str] = None,
    current_user: dict = Depends(require_admin)
):
    """获取账号池状态（健康度、冷却状态等）"""
    from ..services.account_pool import _detect_network_interfaces, get_available_interfaces
    await _detect_network_interfaces()
    pool = get_account_pool(platform)
    status = pool.get_pool_status()
    status["network_interfaces"] = get_available_interfaces()
    return status


@router.post("/accounts/refresh")
async def refresh_accounts(
    platform: str = "dy",
    current_user: dict = Depends(require_admin)
):
    """手动刷新账号池：从Cookie池重新加载"""
    from ..services.account_pool import get_available_interfaces, _detect_network_interfaces
    from ..services.cookie_manager import get_cookie_pool
    pool = get_account_pool(platform)
    cookie_list = get_cookie_pool(platform)

    await _detect_network_interfaces()
    interfaces = get_available_interfaces()

    pool.accounts.clear()
    pool.current_account = None

    for i, cookie_str in enumerate(cookie_list):
        await pool.add_account(
            cookie=cookie_str,
            cookie_alias=f"账号{i+1}",
        )

    return {
        "success": True,
        "message": f"已刷新账号池，共{len(cookie_list)}个账号，{len(interfaces)}个IP动态随机组合",
        "total": len(pool.accounts),
        "network_interfaces": interfaces,
        "combination_count": len(cookie_list) * max(len(interfaces), 1),
    }


@router.post("/accounts/clear-bad-ips")
async def clear_bad_ips(
    platform: str = "dy",
    current_user: dict = Depends(require_admin)
):
    """清除坏IP标记"""
    pool = get_account_pool(platform)
    pool.clear_bad_ips()
    return {"success": True, "message": "已清除所有坏IP标记"}
