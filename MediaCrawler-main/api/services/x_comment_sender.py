# -*- coding: utf-8 -*-
"""
X Twitter 工作台评论发送服务

功能：
1. 通过 Playwright headless 启动浏览器
2. 加载 X_TWITTER_COOKIES 完成登录
3. 在指定推文下发送评论
4. 回退到草稿模式（如果 cookies 未配置或浏览器启动失败）

使用方式：
    from api.services.x_comment_sender import send_comment
    result = await send_comment(post_url="https://x.com/user/status/123", content="评论内容")
    # result = {"success": True/False, "mode": "real"/"draft", "error": "...", "comment_url": "..."}
"""
import asyncio
import os
import time
from typing import Any, Dict, Optional

from tools import utils

# 是否尝试真实发送（默认 True，会自动降级为 draft）
SEND_REAL_DEFAULT = os.getenv("X_WORKBENCH_SEND_REAL", "true").lower() == "true"
# 浏览器启动超时（秒）
BROWSER_LAUNCH_TIMEOUT = 90
# 单次评论操作超时（秒）
COMMENT_OPERATION_TIMEOUT = 90
# 操作重试次数
MAX_RETRIES = 2


def _get_x_cookies() -> str:
    """从 cookie 池获取一个可用的 X Twitter cookie

    使用集中式 cookie_pool_manager：
    - 支持轮询选择 + 冷却机制
    - 失败次数跟踪
    - 当 X_TWITTER_COOKIES_POOL 为空时，自动回退到 X_TWITTER_COOKIES
    """
    try:
        from api.services.cookie_pool_manager import get_cookie_from_pool
        cookie = get_cookie_from_pool()
        if cookie:
            return cookie
    except Exception as e:
        print(f"[x_comment_sender] cookie_pool_manager 异常，回退到单 cookie: {e}")
    # 兜底：直接读环境变量
    return os.getenv("X_TWITTER_COOKIES", "")


def _mark_cookie_used(cookie_str: str, success: bool, reason: str = ""):
    """上报 cookie 使用结果到池管理器（用于健康状态跟踪）"""
    if not cookie_str:
        return
    try:
        from api.services.cookie_pool_manager import mark_cookie_success, mark_cookie_failure
        if success:
            mark_cookie_success(cookie_str)
        else:
            mark_cookie_failure(cookie_str, reason)
    except Exception:
        pass


def _parse_cookies(cookie_str: str) -> list:
    """把 cookie 字符串解析为 Playwright cookie 列表"""
    if not cookie_str:
        return []
    cookies = []
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        cookies.append({
            "name": k.strip(),
            "value": v.strip(),
            "domain": ".x.com",
            "path": "/",
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        })
    return cookies


async def _launch_browser_and_send(post_url: str, content: str) -> Dict[str, Any]:
    """启动 Playwright 浏览器并发送评论（支持重试）"""
    from playwright.async_api import async_playwright

    cookies_str = _get_x_cookies()
    if not cookies_str:
        print(f"[x_comment_sender] ❌ 发送失败: X_TWITTER_COOKIES 未配置")
        return {"success": False, "error": "X_TWITTER_COOKIES 未配置", "mode": "draft"}

    if "auth_token" not in cookies_str and "ct0" not in cookies_str:
        _mark_cookie_used(cookies_str, False, "Cookie 缺少 auth_token 或 ct0")
        print(f"[x_comment_sender] ❌ 发送失败: Cookie 中缺少 auth_token 或 ct0，无法登录")
        return {"success": False, "error": "Cookie 中缺少 auth_token 或 ct0，无法登录", "mode": "draft"}

    cookie_list = _parse_cookies(cookies_str)
    if not cookie_list:
        _mark_cookie_used(cookies_str, False, "Cookie 解析失败")
        print(f"[x_comment_sender] ❌ 发送失败: Cookie 解析失败")
        return {"success": False, "error": "Cookie 解析失败", "mode": "draft"}

    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        browser = None
        context = None
        try:
            print(f"[x_comment_sender] ℹ️ 第 {attempt}/{MAX_RETRIES} 次尝试发送评论")
            
            p = await async_playwright().start()
            browser = await p.chromium.launch(headless=True, args=[
                "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ], timeout=BROWSER_LAUNCH_TIMEOUT * 1000)
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            await context.add_cookies(cookie_list)

            page = await context.new_page()
            page.set_default_timeout(COMMENT_OPERATION_TIMEOUT * 1000)
            
            await page.goto(post_url, wait_until="domcontentloaded", timeout=BROWSER_LAUNCH_TIMEOUT * 1000)
            await asyncio.sleep(5)

            try:
                await page.wait_for_selector('div[data-testid="tweetButtonInline"], div[data-testid="tweetButton"]', timeout=10000)
            except Exception:
                page_url = page.url
                if "login" in page_url or "flow" in page_url:
                    _mark_cookie_used(cookies_str, False, "Cookie 已失效（被重定向到登录页）")
                    print(f"[x_comment_sender] ❌ 发送失败: Cookie 已失效（被重定向到登录页）")
                    return {"success": False, "error": "Cookie 已失效，请重新获取 X_TWITTER_COOKIES", "mode": "draft"}

            # 使用 page.click 替代 ElementHandle.click，更稳定
            try:
                await page.click('article[data-testid="tweet"] [data-testid="reply"]', timeout=10000)
                print(f"[x_comment_sender] ℹ️ 点击回复按钮成功")
            except Exception:
                try:
                    await page.click('[data-testid="reply"]', timeout=10000)
                    print(f"[x_comment_sender] ℹ️ 使用全局选择器点击回复按钮成功")
                except Exception as e:
                    print(f"[x_comment_sender] ❌ 点击回复按钮失败: {e}")
                    raise

            await asyncio.sleep(2)

            textarea = None
            for sel in [
                'textarea[data-testid="tweetTextarea_0"]',
                'textarea[data-testid="tweetTextarea"]',
                '[data-testid="tweetTextarea_0"]',
            ]:
                try:
                    textarea = await page.wait_for_selector(sel, timeout=8000)
                    if textarea:
                        break
                except Exception:
                    continue
            if not textarea:
                print(f"[x_comment_sender] ❌ 发送失败: 未找到评论输入框")
                return {"success": False, "error": "未找到评论输入框", "mode": "real"}

            await textarea.click()
            await asyncio.sleep(0.5)
            await page.keyboard.type(content, delay=30)
            await asyncio.sleep(1)

            send_btn = None
            for sel in [
                'div[data-testid="tweetButton"]',
                'button[data-testid="tweetButton"]',
            ]:
                try:
                    send_btn = await page.wait_for_selector(sel, timeout=8000)
                    if send_btn:
                        break
                except Exception:
                    continue
            if not send_btn:
                print(f"[x_comment_sender] ❌ 发送失败: 未找到发送按钮")
                return {"success": False, "error": "未找到发送按钮", "mode": "real"}

            try:
                await send_btn.click(timeout=15000)
            except Exception:
                await page.click('div[data-testid="tweetButton"], button[data-testid="tweetButton"]', timeout=15000)
            
            await asyncio.sleep(5)
            print(f"[x_comment_sender] ℹ️ 发送按钮已点击，等待响应...")

            try:
                await page.wait_for_selector('div[data-testid="toast"]', timeout=8000)
                print(f"[x_comment_sender] ℹ️ 检测到 toast 提示，发送成功")
            except Exception:
                print(f"[x_comment_sender] ⚠️ 未检测到 toast 提示")

            await asyncio.sleep(3)
            await page.goto(post_url, wait_until="domcontentloaded", timeout=BROWSER_LAUNCH_TIMEOUT * 1000)
            await asyncio.sleep(6)
            
            print(f"[x_comment_sender] ℹ️ 重新加载页面完成，开始验证评论...")
            
            comment_elements = await page.query_selector_all('article[data-testid="tweet"]')
            print(f"[x_comment_sender] ℹ️ 找到 {len(comment_elements)} 个推文元素")
            
            found_comment = False
            comment_author = ""
            comment_url = ""
            for el in comment_elements:
                try:
                    content_el = await el.query_selector('[data-testid="tweetText"]')
                    if content_el:
                        text = await content_el.inner_text()
                        if content[:20] in text:
                            found_comment = True
                            author_el = await el.query_selector('[data-testid="User-Name"] a')
                            if author_el:
                                author_href = await author_el.get_attribute("href")
                                comment_author = author_href.strip("/") if author_href else ""
                            
                            permalink_el = await el.query_selector('a[href*="/status/"]')
                            if permalink_el:
                                permalink_href = await permalink_el.get_attribute("href")
                                if permalink_href and permalink_href.startswith("/"):
                                    parts = permalink_href.strip("/").split("/status/")
                                    if len(parts) == 2:
                                        status_id = parts[1].split("?")[0].split("#")[0].split("/")[0]
                                        if status_id.isdigit():
                                            comment_url = f"https://x.com/{parts[0]}/status/{status_id}"
                            
                            print(f"[x_comment_sender] ✅ 验证通过：评论已出现在原帖页面，作者: {comment_author}, URL: {comment_url}")
                            break
                except Exception as e:
                    print(f"[x_comment_sender] ⚠️ 检查评论元素失败: {e}")
                    continue
            
            if not found_comment:
                print(f"[x_comment_sender] ❌ 警告：未在原帖页面找到刚发送的评论")
                login_hint = await page.query_selector('text="Log in"')
                if login_hint:
                    print(f"[x_comment_sender] ❌ 页面提示需要登录，cookie 可能失效")

            if not comment_url:
                try:
                    links = await page.query_selector_all('a[href*="/status/"]')
                    if links:
                        for link in reversed(links):
                            href = await link.get_attribute("href")
                            if href and href.startswith("/"):
                                parts = href.strip("/").split("/status/")
                                if len(parts) == 2:
                                    status_id = parts[1].split("?")[0].split("#")[0].split("/")[0]
                                    if status_id.isdigit():
                                        comment_url = f"https://x.com/{parts[0]}/status/{status_id}"
                                        break
                        if not comment_url and links:
                            last_link = links[-1]
                            href = await last_link.get_attribute("href")
                            if href and href.startswith("/"):
                                comment_url = f"https://x.com{href}"
                            elif href:
                                comment_url = href
                except Exception:
                    pass

            _mark_cookie_used(cookies_str, found_comment)
            if found_comment:
                print(f"[x_comment_sender] ✅ 发送成功: post_url={post_url[:50]}..., comment_url={comment_url}, author={comment_author}")
                return {
                    "success": True,
                    "mode": "real",
                    "comment_url": comment_url,
                    "message": f"评论已发送（作者: {comment_author}）",
                }
            else:
                print(f"[x_comment_sender] ❌ 发送失败: 评论未出现在原帖页面")
                return {
                    "success": False,
                    "error": "评论未出现在原帖页面，可能未实际发送",
                    "mode": "real",
                    "comment_url": comment_url,
                }

        except Exception as e:
            error_msg = str(e)
            last_error = error_msg
            print(f"[x_comment_sender] ❌ 第 {attempt}/{MAX_RETRIES} 次发送失败: {error_msg[:200]}")
            
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            
            if attempt < MAX_RETRIES:
                print(f"[x_comment_sender] ℹ️ 等待 5 秒后重试...")
                await asyncio.sleep(5)
            else:
                break

    _mark_cookie_used(cookies_str, False, f"所有尝试失败: {last_error[:100]}")
    print(f"[x_comment_sender] ❌ 所有 {MAX_RETRIES} 次尝试均失败")
    return {"success": False, "error": f"所有 {MAX_RETRIES} 次尝试均失败: {last_error}", "mode": "real"}


async def send_comment(
    *,
    post_url: str,
    content: str,
    real_send: bool = True,
) -> Dict[str, Any]:
    """发送评论到 X.com

    Args:
        post_url: 推文 URL，例如 https://x.com/user/status/123
        content: 评论内容
        real_send: 是否真实发送。False 则直接进入草稿模式

    Returns:
        {
            "success": bool,
            "mode": "real" | "draft",
            "error": str,  # 失败原因
            "comment_url": str,  # 真实发送成功后的评论 URL
        }
    """
    print(f"[x_comment_sender] 开始发送评论: post_url={post_url[:50]}..., content={content[:30]}..., real_send={real_send}")

    if not real_send:
        print(f"[x_comment_sender] 跳过真实发送，保存为草稿")
        return {
            "success": True,
            "mode": "draft",
            "error": "",
            "comment_url": "",
            "message": "已保存为草稿（未真实发送）",
        }

    if not SEND_REAL_DEFAULT:
        print(f"[x_comment_sender] X_WORKBENCH_SEND_REAL=false，保存为草稿")
        return {
            "success": True,
            "mode": "draft",
            "error": "",
            "comment_url": "",
            "message": "X_WORKBENCH_SEND_REAL=false，已保存为草稿",
        }

    # 真实发送
    try:
        result = await asyncio.wait_for(
            _launch_browser_and_send(post_url, content),
            timeout=COMMENT_OPERATION_TIMEOUT + BROWSER_LAUNCH_TIMEOUT,
        )
        return result
    except asyncio.TimeoutError:
        print(f"[x_comment_sender] ❌ 发送失败: 评论发送超时")
        return {"success": False, "error": "评论发送超时", "mode": "real"}
    except Exception as e:
        error_msg = f"评论发送异常: {e}"
        print(f"[x_comment_sender] ❌ 发送失败: {error_msg}")
        return {"success": False, "error": error_msg, "mode": "real"}


async def reply_to_comment(
    *,
    comment_url: str,
    content: str,
    real_send: bool = True,
) -> Dict[str, Any]:
    """对某条评论进行回复（找到特定评论的回复按钮，而非底部回复框）"""
    print(f"[x_comment_sender] 开始回复评论: comment_url={comment_url[:50]}..., content={content[:30]}..., real_send={real_send}")

    if not real_send:
        print(f"[x_comment_sender] 跳过真实发送，保存为草稿")
        return {
            "success": True,
            "mode": "draft",
            "error": "",
            "comment_url": "",
            "message": "已保存为草稿（未真实发送）",
        }

    if not SEND_REAL_DEFAULT:
        print(f"[x_comment_sender] X_WORKBENCH_SEND_REAL=false，保存为草稿")
        return {
            "success": True,
            "mode": "draft",
            "error": "",
            "comment_url": "",
            "message": "X_WORKBENCH_SEND_REAL=false，已保存为草稿",
        }

    cookies_str = _get_x_cookies()
    if not cookies_str:
        print(f"[x_comment_sender] ❌ 回复失败: X_TWITTER_COOKIES 未配置")
        return {"success": False, "error": "X_TWITTER_COOKIES 未配置", "mode": "draft"}

    if "auth_token" not in cookies_str and "ct0" not in cookies_str:
        _mark_cookie_used(cookies_str, False, "Cookie 缺少 auth_token 或 ct0")
        print(f"[x_comment_sender] ❌ 回复失败: Cookie 中缺少 auth_token 或 ct0，无法登录")
        return {"success": False, "error": "Cookie 中缺少 auth_token 或 ct0，无法登录", "mode": "draft"}

    cookie_list = _parse_cookies(cookies_str)
    if not cookie_list:
        _mark_cookie_used(cookies_str, False, "Cookie 解析失败")
        print(f"[x_comment_sender] ❌ 回复失败: Cookie 解析失败")
        return {"success": False, "error": "Cookie 解析失败", "mode": "draft"}

    target_status_id = ""
    try:
        if "/status/" in comment_url:
            parts = comment_url.split("/status/")
            if len(parts) >= 2:
                target_status_id = parts[1].split("?")[0].split("#")[0].split("/")[0]
    except Exception:
        pass

    browser = None
    context = None
    try:
        from playwright.async_api import async_playwright

        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        await context.add_cookies(cookie_list)

        page = await context.new_page()
        await page.goto(comment_url, wait_until="domcontentloaded", timeout=BROWSER_LAUNCH_TIMEOUT * 1000)

        try:
            await page.wait_for_selector('div[data-testid="tweetButton"]', timeout=8000)
        except Exception:
            page_url = page.url
            if "login" in page_url or "flow" in page_url:
                _mark_cookie_used(cookies_str, False, "Cookie 已失效（被重定向到登录页）")
                print(f"[x_comment_sender] ❌ 回复失败: Cookie 已失效（被重定向到登录页）")
                return {"success": False, "error": "Cookie 已失效，请重新获取 X_TWITTER_COOKIES", "mode": "draft"}

        # 显式等待 article 元素出现(X.com 是 SPA,需要等 JS 渲染完成)
        # 带 2 次重试:第一次等 15s,失败后滚动+等 5s 再试一次
        articles = []
        for attempt in range(2):
            try:
                await page.wait_for_selector('article[data-testid="tweet"]', timeout=15000 if attempt == 0 else 8000)
                articles = await page.query_selector_all('article[data-testid="tweet"]')
                if articles:
                    break
                print(f"[x_comment_sender] ⚠️ 第 {attempt + 1} 次等待后仍未找到 article,继续重试...")
            except Exception as wait_err:
                print(f"[x_comment_sender] ⚠️ 等待 article 超时(第 {attempt + 1} 次): {wait_err}")
            if attempt == 0:
                await asyncio.sleep(3)
                try:
                    await page.evaluate("window.scrollBy(0, 300)")
                except Exception:
                    pass

        if not articles:
            try:
                final_url = page.url
                page_title = await page.title()
                print(f"[x_comment_sender] ❌ 回复失败: 未找到评论文章")
                print(f"[x_comment_sender]    诊断: url={final_url}, title={page_title}, target_id={target_status_id}")
                if "404" in page_title or "suspended" in final_url or "unavailable" in final_url:
                    return {"success": False, "error": f"评论不存在或已被删除(url={final_url})", "mode": "real"}
            except Exception:
                print(f"[x_comment_sender] ❌ 回复失败: 未找到评论文章(诊断信息获取失败)")
            return {"success": False, "error": "未找到评论文章(页面可能未加载完成或评论已被删除)", "mode": "real"}

        target_article = None
        if target_status_id:
            for article in articles:
                try:
                    permalink = await article.query_selector('a[href*="/status/"]')
                    if permalink:
                        href = await permalink.get_attribute("href")
                        if href and target_status_id in href:
                            target_article = article
                            break
                except Exception:
                    continue

        if not target_article:
            target_article = articles[0]

        reply_btn = None
        for sel in ['div[data-testid="reply"]', 'button[data-testid="reply"]', '[data-testid="reply"]']:
            try:
                reply_btn = await target_article.wait_for_selector(sel, timeout=5000)
                if reply_btn:
                    break
            except Exception:
                continue
        if not reply_btn:
            print(f"[x_comment_sender] ❌ 回复失败: 未找到目标评论的回复按钮")
            return {"success": False, "error": "未找到目标评论的回复按钮", "mode": "real"}

        await reply_btn.click()
        await asyncio.sleep(2)

        textarea = None
        for sel in [
            'textarea[data-testid="tweetTextarea_0"]',
            'textarea[data-testid="tweetTextarea"]',
            '[data-testid="tweetTextarea_0"]',
        ]:
            try:
                textarea = await page.wait_for_selector(sel, timeout=5000)
                if textarea:
                    break
            except Exception:
                continue
        if not textarea:
            print(f"[x_comment_sender] ❌ 回复失败: 未找到回复输入框")
            return {"success": False, "error": "未找到回复输入框", "mode": "real"}

        await textarea.click()
        await asyncio.sleep(0.5)
        await page.keyboard.type(content, delay=30)
        await asyncio.sleep(1)

        send_btn = None
        for sel in [
            'div[data-testid="tweetButton"]',
            'button[data-testid="tweetButton"]',
        ]:
            try:
                send_btn = await page.wait_for_selector(sel, timeout=5000)
                if send_btn:
                    break
            except Exception:
                continue
        if not send_btn:
            print(f"[x_comment_sender] ❌ 回复失败: 未找到发送按钮")
            return {"success": False, "error": "未找到发送按钮", "mode": "real"}

        await send_btn.click()
        await asyncio.sleep(4)

        try:
            await page.wait_for_selector('div[data-testid="toast"]', timeout=5000)
        except Exception:
            pass

        reply_url = ""
        try:
            links = await page.query_selector_all('a[href*="/status/"]')
            if links:
                for link in reversed(links):
                    href = await link.get_attribute("href")
                    if href and href.startswith("/"):
                        parts = href.strip("/").split("/status/")
                        if len(parts) == 2:
                            status_id = parts[1].split("?")[0].split("#")[0].split("/")[0]
                            if status_id.isdigit():
                                reply_url = f"https://x.com/{parts[0]}/status/{status_id}"
                                break
        except Exception:
            pass

        _mark_cookie_used(cookies_str, True)
        print(f"[x_comment_sender] ✅ 回复成功: comment_url={comment_url[:50]}..., reply_url={reply_url}")
        return {
            "success": True,
            "mode": "real",
            "comment_url": reply_url,
            "message": "回复已发送",
        }
    except Exception as e:
        error_msg = f"浏览器回复评论失败: {e}"
        print(f"[x_comment_sender] ❌ 回复失败: {error_msg}")
        return {"success": False, "error": error_msg, "mode": "real"}
    finally:
        try:
            if context:
                await context.close()
        except Exception:
            pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass


async def get_notifications_via_browser(max_count: int = 20) -> Dict[str, Any]:
    """通过浏览器获取通知（用于回复监控）

    Returns:
        {
            "success": bool,
            "notifications": [{"text": ..., "url": ..., "user": ...}, ...],
            "error": str,
        }
    """
    from playwright.async_api import async_playwright

    cookies_str = _get_x_cookies()
    if not cookies_str or "auth_token" not in cookies_str:
        if cookies_str:
            _mark_cookie_used(cookies_str, False, "Cookie 缺少 auth_token")
        return {"success": False, "notifications": [], "error": "Cookies 未配置"}

    cookie_list = _parse_cookies(cookies_str)
    browser = None
    context = None
    try:
        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox",
        ])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_cookies(cookie_list)
        page = await context.new_page()

        await page.goto("https://x.com/notifications", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        # 检查是否被重定向到登录页（Cookie 失效）
        page_url = page.url
        if "login" in page_url or "flow" in page_url:
            _mark_cookie_used(cookies_str, False, "Cookie 已失效（通知页被重定向到登录页）")
            return {"success": False, "notifications": [], "error": "Cookie 已失效"}

        notifications = []
        # 通知项通常以 article 形式存在
        articles = await page.query_selector_all('article[data-testid="tweet"], article')
        for article in articles[:max_count]:
            try:
                text = await article.inner_text()
                # 找到其中的 status 链接
                link = await article.query_selector('a[href*="/status/"]')
                url = ""
                if link:
                    href = await link.get_attribute("href")
                    if href:
                        url = href if href.startswith("http") else f"https://x.com{href}"
                notifications.append({"text": text[:300], "url": url})
            except Exception:
                continue

        _mark_cookie_used(cookies_str, True)
        return {"success": True, "notifications": notifications, "error": ""}
    except Exception as e:
        return {"success": False, "notifications": [], "error": str(e)}
    finally:
        try:
            if context:
                await context.close()
        except Exception:
            pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
