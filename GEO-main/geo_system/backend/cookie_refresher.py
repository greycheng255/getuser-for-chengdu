"""
Cookie 自动刷新模块
定期访问平台保持登录状态

改造后：使用 XhsAuthManager 统一管理
- 优先使用 storage_state 恢复浏览器
- 失效时自动标记 needs_relogin
- 保留对原有 publish_service 的兼容
"""

import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class CookieRefresher:
    """Cookie 自动刷新器"""

    def __init__(self, publish_service=None):
        self.publish_service = publish_service
        self.running = False
        self.thread = None
        self._xhs_auth_manager = None  # 延迟注入

    def set_auth_manager(self, auth_manager):
        """注入 XhsAuthManager"""
        self._xhs_auth_manager = auth_manager
        logger.info("[CookieRefresher] 已注入 XhsAuthManager")

    def _get_all_xhs_users(self):
        """获取所有配置了小红书账号的 user_id"""
        try:
            # 优先使用 auth_manager 的 db
            db = None
            if self._xhs_auth_manager:
                db = self._xhs_auth_manager.db
            elif self.publish_service and hasattr(self.publish_service, 'db'):
                db = self.publish_service.db
            if not db:
                return []
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT user_id FROM platform_accounts WHERE platform='xiaohongshu'"
                )
                return [row[0] for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"[CookieRefresher] 获取用户列表失败: {e}")
            return []

    def refresh_all_cookies(self):
        """刷新所有用户的小红书 Cookie"""
        user_ids = self._get_all_xhs_users()
        if not user_ids:
            return
        logger.info(f"[CookieRefresher] 开始刷新 {len(user_ids)} 个用户的 Cookie: {user_ids}")
        for user_id in user_ids:
            try:
                if self._xhs_auth_manager:
                    success, msg = asyncio.run(self._xhs_auth_manager.refresh_cookie(user_id))
                    status = '成功' if success else '失效'
                    logger.info(f"[CookieRefresher] 用户 {user_id} Cookie 刷新{status}: {msg}")
                elif self.publish_service:
                    # 降级：使用旧的刷新逻辑
                    asyncio.run(self._legacy_refresh(user_id))
            except Exception as e:
                logger.error(f"[CookieRefresher] 用户 {user_id} 刷新失败: {e}")

    async def _legacy_refresh(self, user_id: int):
        """降级方案：使用旧的 cookie 刷新逻辑"""
        try:
            if not self.publish_service:
                return
            account = None
            if hasattr(self.publish_service, 'get_platform_account'):
                account = self.publish_service.get_platform_account('xiaohongshu', user_id)
            if not account or not getattr(account, 'cookies', None):
                return
            await self.refresh_xiaohongshu_cookie(user_id, account.cookies)
        except Exception as e:
            logger.error(f"[CookieRefresher] 降级刷新失败: {e}")

    async def refresh_xiaohongshu_cookie(self, user_id: int, cookies: str) -> bool:
        """旧版刷新逻辑（保留兼容）"""
        if self._xhs_auth_manager:
            success, msg = await self._xhs_auth_manager.refresh_cookie(user_id)
            return success
        # 原始逻辑作为兜底
        try:
            import json
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()

                formatted_cookies = []
                try:
                    parsed = json.loads(cookies)
                    if isinstance(parsed, list):
                        for cookie in parsed:
                            formatted_cookies.append({
                                'name': cookie.get('name'),
                                'value': cookie.get('value'),
                                'domain': cookie.get('domain', '.xiaohongshu.com'),
                                'path': cookie.get('path', '/'),
                            })
                except Exception:
                    pass

                await context.add_cookies(formatted_cookies)
                page = await context.new_page()
                await page.goto('https://creator.xiaohongshu.com/', timeout=30000)
                await asyncio.sleep(5)

                if 'login' not in page.url:
                    new_cookies = await context.cookies()
                    if self.publish_service and hasattr(self.publish_service, 'update_platform_cookies'):
                        self.publish_service.update_platform_cookies(
                            'xiaohongshu', user_id, json.dumps(new_cookies)
                        )
                    await browser.close()
                    return True
                else:
                    logger.warning(f"用户 {user_id} 的小红书 Cookie 已过期")
                    await browser.close()
                    return False
        except Exception as e:
            logger.error(f"刷新 Cookie 失败: {str(e)}")
            return False

    def start(self):
        """启动定时刷新"""
        if self.running:
            return
        self.running = True

        # 每 2 小时刷新一次（使用标准库 threading.Timer，无需第三方依赖）
        REFRESH_INTERVAL = 2 * 3600  # 2小时，单位秒

        def run_schedule():
            while self.running:
                # 等待间隔，每 60 秒检查一次运行状态以便能快速响应 stop()
                waited = 0
                while self.running and waited < REFRESH_INTERVAL:
                    time.sleep(60)
                    waited += 60
                if not self.running:
                    break
                try:
                    self.refresh_all_cookies()
                except Exception as e:
                    logger.error(f"[CookieRefresher] 定时刷新出错: {e}")

        self.thread = threading.Thread(target=run_schedule)
        self.thread.daemon = True
        self.thread.start()
        logger.info("[CookieRefresher] 定时刷新已启动（每2小时）")

        # 启动后延迟 5 分钟再首次刷新，避免与服务启动/扫码登录冲突
        def delayed_first_refresh():
            time.sleep(300)
            try:
                self.refresh_all_cookies()
            except Exception as e:
                logger.error(f"[CookieRefresher] 启动后首次刷新失败: {e}")
        try:
            threading.Thread(target=delayed_first_refresh, daemon=True).start()
        except Exception as e:
            logger.error(f"[CookieRefresher] 启动首次刷新线程失败: {e}")

    def stop(self):
        """停止定时刷新"""
        self.running = False
        if self.thread:
            self.thread.join()
        logger.info("[CookieRefresher] 定时刷新已停止")


# 全局刷新器实例
cookie_refresher: Optional[CookieRefresher] = None


def init_cookie_refresher(publish_service=None):
    """初始化 Cookie 刷新器"""
    global cookie_refresher
    cookie_refresher = CookieRefresher(publish_service)
    cookie_refresher.start()
    return cookie_refresher
