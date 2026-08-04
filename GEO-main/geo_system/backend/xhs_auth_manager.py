"""
小红书认证管理器
- 使用 storage_state 持久化浏览器登录状态
- Cookie 自动刷新（定期访问小红书续期）
- Cookie 失效检测（发布前自动检测+刷新）
- 失效通知机制（标记账号需要重新扫码）

设计原则：
1. 扫码登录成功后，保存 storage_state 到磁盘
2. 后续发布/刷新使用 storage_state 恢复，避免重复扫码
3. storage_state 失效时，标记账号状态为 needs_relogin，触发通知
4. 提供 check_and_refresh() 方法，发布前自动检测+刷新
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# storage_state 保存目录
STATE_DIR = os.environ.get('XHS_STATE_DIR', '/app/data/xhs_state')
os.makedirs(STATE_DIR, exist_ok=True)


def _state_path(user_id: int) -> str:
    """获取用户对应的 storage_state 文件路径"""
    return os.path.join(STATE_DIR, f'user_{user_id}.json')


class XhsAuthManager:
    """小红书认证管理器"""

    def __init__(self, postgres_db, platform_account_service):
        self.db = postgres_db
        self.account_service = platform_account_service

    # ============== storage_state 持久化 ==============

    async def save_storage_state(self, user_id: int, context) -> bool:
        """保存浏览器 context 的 storage_state 到磁盘"""
        try:
            state = await context.storage_state()
            path = _state_path(user_id)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False)
            logger.info(f"[XhsAuth] 用户 {user_id} storage_state 已保存到 {path}")
            return True
        except Exception as e:
            logger.error(f"[XhsAuth] 保存 storage_state 失败: {e}")
            return False

    def load_storage_state(self, user_id: int) -> Optional[Dict]:
        """从磁盘加载 storage_state"""
        path = _state_path(user_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[XhsAuth] 加载 storage_state 失败: {e}")
            return None

    def delete_storage_state(self, user_id: int):
        """删除 storage_state（账号失效时清理）"""
        path = _state_path(user_id)
        if os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"[XhsAuth] 已删除用户 {user_id} 的 storage_state")
            except Exception as e:
                logger.error(f"[XhsAuth] 删除 storage_state 失败: {e}")

    # ============== Cookie 有效性检测 ==============

    async def check_cookie_valid(self, user_id: int, cookies: str) -> Tuple[bool, str]:
        """
        检测 cookie 是否有效
        返回: (是否有效, 原因描述)
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )

                # 优先使用 storage_state（包含 localStorage 等完整状态）
                state = self.load_storage_state(user_id)
                if state:
                    context = await browser.new_context(storage_state=state)
                    logger.info(f"[XhsAuth] 用户 {user_id} 使用 storage_state 恢复浏览器上下文")
                else:
                    # 降级：使用 cookies
                    context = await browser.new_context()
                    cookie_list = self._parse_cookies(cookies)
                    if cookie_list:
                        await context.add_cookies(cookie_list)
                    logger.info(f"[XhsAuth] 用户 {user_id} 无 storage_state，使用 cookies")

                page = await context.new_page()
                try:
                    await page.goto('https://creator.xiaohongshu.com/', timeout=30000)
                    await asyncio.sleep(3)
                    url = page.url
                    if 'login' in url.lower():
                        # 失效：跳到登录页
                        await browser.close()
                        return False, 'cookie 已失效，被重定向到登录页'
                    # 有效：还在 creator 主页
                    # 顺便刷新 cookie 和 storage_state
                    new_cookies = await context.cookies()
                    new_state = await context.storage_state()
                    await self._persist_after_check(user_id, new_cookies, new_state)
                    await browser.close()
                    return True, f'cookie 有效，URL={url}'
                except Exception as e:
                    await browser.close()
                    return False, f'访问失败: {e}'
        except Exception as e:
            logger.error(f"[XhsAuth] 检测 cookie 失败: {e}")
            return False, f'检测异常: {e}'

    async def _persist_after_check(self, user_id: int, cookies: list, state: dict):
        """检测有效后，顺便刷新数据库 cookie 和 storage_state"""
        try:
            cookies_str = json.dumps(cookies, ensure_ascii=False)
            self.account_service.update_cookies(
                user_id, 'xiaohongshu', cookies_str,
                datetime.now() + timedelta(days=7)
            )
            path = _state_path(user_id)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False)
            logger.info(f"[XhsAuth] 用户 {user_id} cookie 和 storage_state 已刷新")
        except Exception as e:
            logger.error(f"[XhsAuth] 刷新 cookie 失败: {e}")

    # ============== 自动刷新 ==============

    async def refresh_cookie(self, user_id: int) -> Tuple[bool, str]:
        """
        刷新用户的小红书 cookie
        成功: 返回 (True, '刷新成功')
        失效: 返回 (False, 'cookie 已失效，需要重新扫码登录')
        """
        # 先从数据库取 cookie
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT cookies FROM platform_accounts WHERE platform='xiaohongshu' AND user_id=%s",
                (user_id,)
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return False, '未配置小红书账号'

        cookies = row[0]
        valid, msg = await self.check_cookie_valid(user_id, cookies)
        if valid:
            logger.info(f"[XhsAuth] 用户 {user_id} cookie 刷新成功: {msg}")
            # 标记账号为 active
            self._update_account_status(user_id, 'active')
            return True, 'cookie 刷新成功'
        else:
            logger.warning(f"[XhsAuth] 用户 {user_id} cookie 失效: {msg}")
            # 标记账号需要重新登录
            self._update_account_status(user_id, 'needs_relogin')
            # 清理失效的 storage_state
            self.delete_storage_state(user_id)
            return False, f'cookie 已失效，需要重新扫码登录'

    def _update_account_status(self, user_id: int, status: str):
        """更新账号状态"""
        try:
            with self.db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE platform_accounts SET status=%s, updated_at=CURRENT_TIMESTAMP WHERE platform='xiaohongshu' AND user_id=%s",
                    (status, user_id)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[XhsAuth] 更新账号状态失败: {e}")

    # ============== 发布前检测+刷新 ==============

    async def check_and_refresh(self, user_id: int) -> Tuple[bool, str]:
        """
        发布前自动检测+刷新
        1. 先检测 cookie 是否有效
        2. 失效则尝试自动刷新（访问小红书续期）
        3. 还是失效则返回 False，提示用户重新扫码
        """
        valid, msg = await self.check_cookie_valid(user_id, '')
        if valid:
            return True, msg
        # 失效，尝试刷新
        logger.info(f"[XhsAuth] 用户 {user_id} cookie 失效，尝试自动刷新...")
        return await self.refresh_cookie(user_id)

    # ============== 工具方法 ==============

    def _parse_cookies(self, cookies: str) -> list:
        """解析 cookie 字符串为 Playwright 格式"""
        if not cookies:
            return []
        try:
            parsed = json.loads(cookies) if isinstance(cookies, str) else cookies
            if isinstance(parsed, list):
                result = []
                for c in parsed:
                    name = c.get('name')
                    value = c.get('value')
                    if not name or not value:
                        continue
                    result.append({
                        'name': name,
                        'value': value,
                        'domain': c.get('domain', '.xiaohongshu.com'),
                        'path': c.get('path', '/'),
                    })
                return result
        except Exception as e:
            logger.error(f"[XhsAuth] 解析 cookie 失败: {e}")
        return []

    def get_account_status(self, user_id: int) -> Dict:
        """获取账号状态信息（供前端展示）"""
        try:
            with self.db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """SELECT id, account_name, status, cookies, last_login_time,
                              cookie_expires_at, updated_at
                       FROM platform_accounts
                       WHERE platform='xiaohongshu' AND user_id=%s""",
                    (user_id,)
                )
                row = cur.fetchone()
            if not row:
                return {'configured': False, 'status': 'not_configured'}

            cookies_str = row[3] or ''
            cookie_count = 0
            has_access_token = False
            has_web_session = False
            try:
                cl = json.loads(cookies_str) if isinstance(cookies_str, str) else cookies_str
                if isinstance(cl, list):
                    cookie_count = len(cl)
                    names = [c.get('name', '') for c in cl]
                    has_access_token = any('access-token' in n for n in names)
                    # 真实的 web_session（www 主站 cookie，发布时必需）
                    has_web_session = 'web_session' in names
                    # 创作者中心替代认证（QR 登录能拿到，但发布可能失败）
                    has_creator_auth = 'galaxy_creator_session_id' in names or 'customer-sso-sid' in names
            except Exception:
                pass

            state_path = _state_path(user_id)
            has_state = os.path.exists(state_path)

            # 计算剩余有效期
            expires_at = row[5]
            remaining_days = None
            if expires_at:
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                remaining = expires_at - datetime.now(expires_at.tzinfo) if expires_at.tzinfo else expires_at - datetime.now()
                remaining_days = max(0, remaining.days)

            return {
                'configured': True,
                'account_id': row[0],
                'account_name': row[1],
                'status': row[2],
                'cookie_count': cookie_count,
                'has_access_token': has_access_token,
                'has_web_session': has_web_session,
                'has_creator_auth': has_creator_auth,
                'has_storage_state': has_state,
                'last_login_time': str(row[4]) if row[4] else None,
                'cookie_expires_at': str(expires_at) if expires_at else None,
                'remaining_days': remaining_days,
                'updated_at': str(row[6]) if row[6] else None,
            }
        except Exception as e:
            logger.error(f"[XhsAuth] 获取账号状态失败: {e}")
            return {'configured': False, 'status': 'error', 'error': str(e)}


# 全局实例（在 app.py 中初始化）
xhs_auth_manager: Optional[XhsAuthManager] = None


def init_xhs_auth_manager(postgres_db, platform_account_service):
    """初始化全局认证管理器"""
    global xhs_auth_manager
    xhs_auth_manager = XhsAuthManager(postgres_db, platform_account_service)
    logger.info("[XhsAuth] 认证管理器已初始化")
    return xhs_auth_manager
