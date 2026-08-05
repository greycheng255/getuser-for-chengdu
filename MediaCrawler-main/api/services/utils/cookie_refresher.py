# -*- coding: utf-8 -*-
"""
Cookie 自动刷新服务

迁移自 GEO-main 项目 (geo_system/backend/cookie_refresher.py)
对应 PRD 模块: 通用工具 - Cookie 定时刷新

职责:
- 定期访问各平台保持登录状态,避免 Cookie 因长期不使用而过期
- 与 MediaCrawler 现有 cookie_manager.py 协同工作
- 优先使用浏览器自动化刷新(真实访问),失败时仅做轻量保活(更新校验时间戳)

适配点(相对 GEO-main 原版):
1. 数据库: sqlite3 同步连接 -> PostgreSQL 异步
   (database.db_session.get_async_engine + sqlalchemy text)
2. 配置: 硬编码 -> os.environ.get(...),敏感信息一律走环境变量
3. 日志: print/直接 logger -> logging.getLogger(__name__)
4. 用户/Cookie 来源: platform_accounts 表 -> sys_user_cookie 表(通过 cookie_manager.py)
5. 调度: 保留原 threading + asyncio.run 模式,便于在 FastAPI startup 事件中调用 start()
6. auth_manager 注入: GEO-main 的 XhsAuthManager 在 MediaCrawler 不存在,改为直接调用
   cookie_manager 的 get_user_cookie_pool / set_user_cookie
7. 平台范围: 由仅 xhs 扩展为可通过 COOKIE_REFRESH_PLATFORMS 环境变量配置的多平台
8. 单例: 提供 get_cookie_refresher_service() 全局访问
"""

import asyncio
import json
import logging
import os
import threading
import time
from typing import List, Optional, Tuple

from sqlalchemy import text as sql_text

import config
from ..cookie_manager import set_user_cookie, get_user_cookie_pool

logger = logging.getLogger(__name__)


def _get_engine():
    """获取异步数据库引擎（公共方法，消除重复导入）"""
    from database.db_session import get_async_engine
    return get_async_engine(config.SAVE_DATA_OPTION)


# ============== 配置(从环境变量读取,避免硬编码) ==============

# 刷新周期(秒),默认 2 小时
REFRESH_INTERVAL_SECONDS = int(os.environ.get("COOKIE_REFRESH_INTERVAL_SECONDS", "7200"))

# 启动后首次刷新延迟(秒),默认 5 分钟(避开服务启动/扫码登录高峰)
FIRST_REFRESH_DELAY_SECONDS = int(os.environ.get("COOKIE_REFRESH_FIRST_REFRESH_DELAY_SECONDS", "300"))

# 调度循环检查间隔(秒),默认 60 秒(便于快速响应 stop)
SCHEDULE_TICK_SECONDS = int(os.environ.get("COOKIE_REFRESH_TICK_SECONDS", "60"))

# 参与自动刷新的平台列表(逗号分隔),默认仅 xhs
# 可选值: xhs, dy, ks, bili, wb, x_twitter
REFRESH_PLATFORMS: List[str] = [
    p.strip() for p in os.environ.get("COOKIE_REFRESH_PLATFORMS", "xhs").split(",") if p.strip()
]

# 各平台保活访问的目标 URL
PLATFORM_KEEPALIVE_URL = {
    "xhs": os.environ.get("COOKIE_REFRESH_XHS_URL", "https://creator.xiaohongshu.com/"),
    "dy": os.environ.get("COOKIE_REFRESH_DY_URL", "https://creator.douyin.com/"),
    "ks": os.environ.get("COOKIE_REFRESH_KS_URL", "https://cp.kuaishou.com/"),
    "bili": os.environ.get("COOKIE_REFRESH_BILI_URL", "https://member.bilibili.com/"),
    "wb": os.environ.get("COOKIE_REFRESH_WB_URL", "https://weibo.com/"),
    "x_twitter": os.environ.get("COOKIE_REFRESH_X_URL", "https://x.com/"),
}

# 各平台默认 Cookie domain(用于将 k=v 字符串解析为浏览器 Cookie)
_PLATFORM_DEFAULT_DOMAIN = {
    "xhs": ".xiaohongshu.com",
    "dy": ".douyin.com",
    "ks": ".kuaishou.com",
    "bili": ".bilibili.com",
    "wb": ".weibo.com",
    "x_twitter": ".x.com",
}

# Playwright 浏览器超时(毫秒)
BROWSER_TIMEOUT_MS = int(os.environ.get("COOKIE_REFRESH_BROWSER_TIMEOUT_MS", "30000"))

# 页面加载后等待时间(秒),让前端 JS 刷新 Cookie
PAGE_WAIT_SECONDS = int(os.environ.get("COOKIE_REFRESH_PAGE_WAIT_SECONDS", "5"))

# 是否启用 Playwright 浏览器刷新(需要安装 playwright)
ENABLE_BROWSER_REFRESH = os.environ.get("COOKIE_REFRESH_ENABLE_BROWSER", "true").lower() == "true"


class CookieRefresher:
    """Cookie 自动刷新器

    与 cookie_manager.py 协同:
    - 读取: 通过 cookie_manager.get_user_cookie_pool 获取用户某平台的 Cookie 池
    - 写入: 通过 cookie_manager.set_user_cookie 持久化刷新后的 Cookie
    - 用户列表: 通过 sys_user_cookie 表查询所有配置了 Cookie 的用户
    """

    def __init__(self):
        self.running: bool = False
        self.thread: Optional[threading.Thread] = None
        self._first_refresh_thread: Optional[threading.Thread] = None

    # ============== 数据库查询 ==============

    async def _get_users_by_platform(self, platform: str) -> List[int]:
        """获取所有配置了指定平台 Cookie 的 user_id 列表

        适配点: 使用 PostgreSQL 异步查询 sys_user_cookie 表
        (GEO-main 原版查询 platform_accounts 表,此处适配为 MediaCrawler 的用户 Cookie 表)
        """
        try:
            engine = _get_engine()
            if engine is None:
                # JSON/CSV 模式下没有数据库引擎,退回空列表
                logger.debug("[CookieRefresher] 当前存储模式无数据库引擎,跳过用户查询")
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT DISTINCT user_id FROM sys_user_cookie "
                        "WHERE platform = :platform AND status = 'active'"
                    ),
                    {"platform": platform},
                )
                return [int(row[0]) for row in rows.fetchall()]
        except Exception as e:
            logger.error(f"[CookieRefresher] 获取平台 {platform} 用户列表失败: {e}")
            return []

    async def _update_last_check_ts(self, user_id: int, platform: str) -> None:
        """更新指定用户某平台 Cookie 的最后校验时间戳"""
        try:
            engine = _get_engine()
            if engine is None:
                return
            now_ms = int(time.time() * 1000)
            async with engine.connect() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE sys_user_cookie SET last_check_ts = :ts "
                        "WHERE user_id = :uid AND platform = :platform AND status = 'active'"
                    ),
                    {"ts": now_ms, "uid": user_id, "platform": platform},
                )
                await conn.commit()
        except Exception as e:
            logger.error(
                f"[CookieRefresher] 更新 last_check_ts 失败 "
                f"(user={user_id}, platform={platform}): {e}"
            )

    # ============== 刷新主流程 ==============

    async def refresh_all_cookies(self) -> None:
        """刷新所有平台所有用户的 Cookie

        保留原 GEO-main refresh_all_cookies 逻辑骨架:
        - 遍历用户列表
        - 调用单用户刷新
        - 异常隔离,单个失败不影响其他用户

        扩展点: 由仅 xhs 扩展为 REFRESH_PLATFORMS 配置的所有平台
        """
        for platform in REFRESH_PLATFORMS:
            user_ids = await self._get_users_by_platform(platform)
            if not user_ids:
                continue
            logger.info(
                f"[CookieRefresher] 开始刷新平台 {platform} 的 "
                f"{len(user_ids)} 个用户 Cookie: {user_ids}"
            )
            for user_id in user_ids:
                try:
                    success, msg = await self.refresh_user_platform(user_id, platform)
                    status = "成功" if success else "失效"
                    logger.info(
                        f"[CookieRefresher] 用户 {user_id} 平台 {platform} "
                        f"Cookie 刷新{status}: {msg}"
                    )
                except Exception as e:
                    logger.error(
                        f"[CookieRefresher] 用户 {user_id} 平台 {platform} 刷新失败: {e}"
                    )

    async def refresh_user_platform(
        self, user_id: int, platform: str
    ) -> Tuple[bool, str]:
        """刷新单个用户单个平台的 Cookie

        策略:
        1. 取出该用户该平台的最新一条 Cookie
        2. 更新 last_check_ts(标记已校验)
        3. 若启用浏览器刷新,使用 Playwright 真实访问目标平台保活
        4. 否则仅更新 last_check_ts(轻量保活,不实际访问平台)

        Returns:
            (success, message)
        """
        # 取出该用户该平台的最新一条 Cookie
        pool = await get_user_cookie_pool(user_id, platform)
        if not pool:
            return False, "无可用 Cookie"
        latest_cookie = pool[0].get("cookie", "") if isinstance(pool[0], dict) else ""
        if not latest_cookie:
            return False, "Cookie 为空"

        # 更新校验时间戳(无论是否浏览器刷新都更新)
        await self._update_last_check_ts(user_id, platform)

        if not ENABLE_BROWSER_REFRESH:
            return True, "仅更新校验时间戳(浏览器刷新未启用)"

        # 浏览器保活刷新
        try:
            return await self._browser_refresh(user_id, platform, latest_cookie)
        except Exception as e:
            logger.error(
                f"[CookieRefresher] 浏览器刷新异常 "
                f"(user={user_id}, platform={platform}): {e}"
            )
            return False, f"浏览器刷新异常: {e}"

    async def _browser_refresh(
        self, user_id: int, platform: str, cookies: str
    ) -> Tuple[bool, str]:
        """浏览器保活刷新

        保留 GEO-main 原 refresh_xiaohongshu_cookie 的 playwright 逻辑骨架:
        - 启动 chromium headless
        - 注入 Cookie
        - 访问目标平台
        - 若未跳转到登录页,则提取新 Cookie 并持久化

        扩展点: 由仅 xhs 扩展为根据 platform 选择目标 URL 和默认 domain
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("[CookieRefresher] playwright 未安装,跳过浏览器刷新")
            return False, "playwright 未安装"

        target_url = PLATFORM_KEEPALIVE_URL.get(platform)
        if not target_url:
            return False, f"平台 {platform} 未配置保活 URL"

        # 解析 Cookie 字符串为 playwright 所需格式
        formatted_cookies = self._parse_cookies_for_browser(cookies, platform)
        if not formatted_cookies:
            return False, "Cookie 解析失败"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            try:
                await context.add_cookies(formatted_cookies)
                page = await context.new_page()
                await page.goto(target_url, timeout=BROWSER_TIMEOUT_MS)
                await asyncio.sleep(PAGE_WAIT_SECONDS)

                # 简单判定: 若 URL 仍包含 login 关键字,认为已失效
                current_url = page.url or ""
                if "login" in current_url:
                    logger.warning(
                        f"[CookieRefresher] 用户 {user_id} 平台 {platform} "
                        f"Cookie 已过期(跳转到登录页)"
                    )
                    return False, "Cookie 已过期(跳转到登录页)"

                # 提取刷新后的 Cookie 并持久化
                new_cookies = await context.cookies()
                new_cookie_str = self._serialize_cookies(new_cookies)
                if new_cookie_str:
                    ok = await set_user_cookie(
                        user_id, platform, new_cookie_str, alias="auto_refreshed"
                    )
                    if ok:
                        return True, f"已更新 Cookie({len(new_cookies)} 条)"
                return True, "访问成功但未取得新 Cookie"
            finally:
                await browser.close()

    @staticmethod
    def _parse_cookies_for_browser(cookies: str, platform: str) -> list:
        """将 Cookie 字符串解析为 playwright add_cookies 所需的列表格式

        兼容两种输入:
        1. JSON 数组格式(GEO-main 原版):
           [{"name": ..., "value": ..., "domain": ..., "path": ...}, ...]
        2. 浏览器 Cookie 字符串格式: "k1=v1; k2=v2"
        """
        domain = _PLATFORM_DEFAULT_DOMAIN.get(platform, "")

        # 1. 尝试 JSON 解析
        try:
            parsed = json.loads(cookies)
            if isinstance(parsed, list):
                result = []
                for cookie in parsed:
                    if not isinstance(cookie, dict):
                        continue
                    name = cookie.get("name")
                    value = cookie.get("value")
                    if not name or value is None:
                        continue
                    result.append({
                        "name": name,
                        "value": value,
                        "domain": cookie.get("domain") or domain,
                        "path": cookie.get("path", "/"),
                    })
                if result:
                    return result
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # 2. 退回 k=v; k=v 格式解析
        if not domain:
            return []
        result = []
        for pair in cookies.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            name = name.strip()
            value = value.strip()
            if name:
                result.append({
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": "/",
                })
        return result

    @staticmethod
    def _serialize_cookies(cookies: list) -> str:
        """将 playwright context.cookies() 返回值序列化为可持久化的字符串

        策略: 保留 JSON 数组格式(信息更完整),便于下次刷新时解析回浏览器 Cookie
        """
        try:
            simplified = []
            for c in cookies:
                simplified.append({
                    "name": c.get("name"),
                    "value": c.get("value"),
                    "domain": c.get("domain"),
                    "path": c.get("path", "/"),
                    "expires": c.get("expires"),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                })
            return json.dumps(simplified, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[CookieRefresher] 序列化 Cookie 失败,退回简单格式: {e}")
            return "; ".join(
                f"{c.get('name', '')}={c.get('value', '')}" for c in cookies
            )

    # ============== 调度器 ==============

    def start(self) -> None:
        """启动定时刷新(保留 GEO-main 原版 threading 调度模式)

        - 每 REFRESH_INTERVAL_SECONDS 秒刷新一次
        - 启动后延迟 FIRST_REFRESH_DELAY_SECONDS 秒首次刷新,避开服务启动高峰
        - 调度循环每 SCHEDULE_TICK_SECONDS 秒检查一次运行状态,便于快速响应 stop()
        """
        if self.running:
            return
        self.running = True

        def run_schedule():
            while self.running:
                # 等待间隔,每 SCHEDULE_TICK_SECONDS 秒检查一次运行状态
                waited = 0
                while self.running and waited < REFRESH_INTERVAL_SECONDS:
                    time.sleep(SCHEDULE_TICK_SECONDS)
                    waited += SCHEDULE_TICK_SECONDS
                if not self.running:
                    break
                try:
                    asyncio.run(self.refresh_all_cookies())
                except Exception as e:
                    logger.error(f"[CookieRefresher] 定时刷新出错: {e}")

        self.thread = threading.Thread(
            target=run_schedule, name="cookie-refresher", daemon=True
        )
        self.thread.start()
        logger.info(
            f"[CookieRefresher] 定时刷新已启动(每 {REFRESH_INTERVAL_SECONDS}s 刷新一次,"
            f"平台: {REFRESH_PLATFORMS})"
        )

        # 启动后延迟首次刷新(避开服务启动/扫码登录高峰)
        def delayed_first_refresh():
            time.sleep(FIRST_REFRESH_DELAY_SECONDS)
            try:
                asyncio.run(self.refresh_all_cookies())
            except Exception as e:
                logger.error(f"[CookieRefresher] 启动后首次刷新失败: {e}")

        try:
            self._first_refresh_thread = threading.Thread(
                target=delayed_first_refresh,
                name="cookie-refresher-first",
                daemon=True,
            )
            self._first_refresh_thread.start()
        except Exception as e:
            logger.error(f"[CookieRefresher] 启动首次刷新线程失败: {e}")

    def stop(self) -> None:
        """停止定时刷新"""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=SCHEDULE_TICK_SECONDS * 2)
        logger.info("[CookieRefresher] 定时刷新已停止")


# ============== 单例 ==============

_cookie_refresher_service: Optional[CookieRefresher] = None


def get_cookie_refresher_service() -> CookieRefresher:
    """获取全局 CookieRefresher 单例(懒初始化,不自动启动调度)

    使用方式:
        from api.services.utils.cookie_refresher import get_cookie_refresher_service
        service = get_cookie_refresher_service()
        service.start()  # 在 FastAPI startup 事件中调用
        # 单次刷新(测试用):
        await service.refresh_all_cookies()
        # 停止(在 FastAPI shutdown 事件中调用):
        service.stop()
    """
    global _cookie_refresher_service
    if _cookie_refresher_service is None:
        _cookie_refresher_service = CookieRefresher()
    return _cookie_refresher_service
