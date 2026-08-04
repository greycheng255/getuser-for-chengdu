# -*- coding: utf-8 -*-
"""
BasePublisher 抽象基类

迁移自 GEO-main 的 5 个 XxxAutomation 类的公共结构，提炼为模板方法模式：
- __init__ / _parse_cookies / _init_browser / _check_login / _persist_state / _close_browser
  全部上移到基类（5 个子类原本 >80% 相同）
- 子类只需实现 _do_publish() 和必要的常量（PLATFORM_NAME / LOGIN_COOKIE_KEY 等）

设计要点：
1. publish() 是模板方法，固化"初始化→登录检测→业务参数校验→发布→持久化→关闭"流程
2. _check_login() 默认基于 cookie 关键字段，子类可覆盖为 DOM 检测
3. _detect_biz_error() 统一业务错误检测，错误码集中管理
4. _close_browser() 严格 try-finally，避免 Playwright 实例泄漏（项目 memory 中的教训）
"""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import List, Optional

from playwright.async_api import async_playwright

from .exceptions import BizError, ContentBlockedError, LoginExpiredError, PublisherError, RateLimitError
from .publish_task import PublishResult
from .stealth_browser import create_stealth_context, get_storage_state_path, launch_stealth_browser

logger = logging.getLogger(__name__)


# 业务错误关键词（统一管理，避免 5 个子类各自维护一份）
BIZ_ERROR_INDICATORS = [
    '频次过高', '验证码', '账号异常', '限制', '违规', '请稍后再试',
    '发布失败', '内容过长', '权限不足', '禁止发布', '风控', '内容违规',
    '发布受限', '账号被限流', 'HTTPBizError', '禁止发笔记', '违反社区规范',
    '-9136', '-10000',
]

# 不可重试错误关键词（命中后不再重试，直接返回）
NO_RETRY_KEYWORDS = [
    '必须包含至少1张图片', '无权访问', '禁止发笔记',
    '违反社区规范', 'HTTPBizError', '账号被限流', '风控限制',
    '小红书拒绝发布', '抖音拒绝发布', 'B站拒绝发布', '微博拒绝发布', '知乎拒绝发布',
]


class BasePublisher(ABC):
    """发布器抽象基类

    子类需设置以下类属性：
        PLATFORM_NAME: str           # "douyin" / "xiaohongshu" / "bilibili" / "weibo" / "zhihu"
        PLATFORM_CN_NAME: str        # "抖音" / "小红书" / "B站" / "微博" / "知乎"
        LOGIN_COOKIE_KEY: str        # "sessionid" / "web_session" / "SESSDATA" / "SUB" / "z_c0"
        LOGIN_CHECK_URL: str         # 登录检测访问的 URL
        PUBLISH_URL: str             # 发布页 URL
        LOGIN_REDIRECT_KEYWORD: str  # 登录失效时 URL 中会出现的关键词，如 "login" / "signin" / "passport"
        SUPPORTS_VIDEO: bool = False
        SUPPORTS_IMAGE: bool = True
        SUPPORTS_ARTICLE: bool = False
        MIN_IMAGES: int = 0          # 最少图片数（小红书 = 1）
    """

    # 子类必须覆盖的类属性
    PLATFORM_NAME: str = ""
    PLATFORM_CN_NAME: str = ""
    LOGIN_COOKIE_KEY: str = ""
    LOGIN_CHECK_URL: str = ""
    PUBLISH_URL: str = ""
    LOGIN_REDIRECT_KEYWORD: str = "login"

    # 默认能力声明（子类按需覆盖）
    SUPPORTS_VIDEO: bool = False
    SUPPORTS_IMAGE: bool = True
    SUPPORTS_ARTICLE: bool = False
    MIN_IMAGES: int = 0

    def __init__(self, cookies: str, user_id: Optional[int] = None, *, headless: bool = True):
        """
        Args:
            cookies: cookie 字符串。支持两种格式：
                     1. JSON 字符串（Playwright cookie 列表）
                     2. 单个 cookie 值（如 web_session）—— 子类应实现 _build_cookies_from_simple()
            user_id: 用户 ID，用于加载/保存 storage_state（持久化登录态）
            headless: 是否无头模式
        """
        self.cookies_raw = cookies or ""
        self.user_id = user_id
        self.headless = headless
        self.storage_state = self._load_storage_state()

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    # ==================== 模板方法：发布主流程 ====================

    async def publish(
        self,
        title: str,
        content: str,
        images: Optional[List[str]] = None,
        video_path: Optional[str] = None,
        **kwargs,
    ) -> PublishResult:
        """模板方法：发布流程骨架

        流程：初始化浏览器 → 登录检测 → 业务参数校验 → 子类发布 → 持久化 → 关闭
        """
        debug_info: List[str] = []

        try:
            # 1. 参数校验
            if self.MIN_IMAGES > 0 and (not images or len(images) < self.MIN_IMAGES):
                return PublishResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error=f"{self.PLATFORM_CN_NAME}至少需要 {self.MIN_IMAGES} 张图片",
                    debug_info=debug_info,
                    retryable=False,
                )

            # 2. 初始化浏览器
            if not await self._init_browser():
                return PublishResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error="浏览器初始化失败",
                    debug_info=debug_info,
                )
            debug_info.append("✅ 浏览器初始化成功")

            # 3. 登录检测
            if not await self._check_login():
                debug_info.append("❌ 登录已失效")
                return PublishResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error=f"{self.PLATFORM_CN_NAME}登录已失效，请重新扫码登录",
                    debug_info=debug_info,
                    retryable=False,  # 登录失效不应重试同 cookie
                )
            debug_info.append("✅ 登录状态正常")

            # 4. 业务错误预检测（访问发布页后看是否被重定向到登录页）
            try:
                await self.page.goto(
                    self.PUBLISH_URL,
                    timeout=20000,
                    wait_until="domcontentloaded",
                )
                await asyncio.sleep(3)
                current_url = self.page.url
                if self.LOGIN_REDIRECT_KEYWORD in current_url.lower():
                    debug_info.append(f"发布页跳回登录页: {current_url}")
                    return PublishResult(
                        success=False,
                        platform=self.PLATFORM_NAME,
                        error=f"{self.PLATFORM_CN_NAME}登录已失效",
                        debug_info=debug_info,
                        retryable=False,
                    )
            except Exception as e:
                debug_info.append(f"⚠️ 访问发布页失败: {e}")

            # 5. 子类实现具体发布逻辑
            result = await self._do_publish(title, content, images or [], video_path, **kwargs)
            result.debug_info = debug_info + result.debug_info
            result.platform = self.PLATFORM_NAME

            # 6. 成功后持久化 storage_state
            if result.success:
                await self._persist_state()

            return result

        except LoginExpiredError as e:
            e.platform = self.PLATFORM_NAME
            logger.warning(f"[{self.PLATFORM_NAME}] 登录失效: {e.message}")
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=e.message,
                debug_info=debug_info,
                retryable=False,
            )
        except RateLimitError as e:
            e.platform = self.PLATFORM_NAME
            logger.warning(f"[{self.PLATFORM_NAME}] 被限流: {e.message}")
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=e.message,
                debug_info=debug_info,
                retryable=True,  # 限流可换账号重试
            )
        except (BizError, ContentBlockedError) as e:
            e.platform = self.PLATFORM_NAME
            logger.warning(f"[{self.PLATFORM_NAME}] 业务错误: {e.message}")
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=e.message,
                debug_info=debug_info,
                retryable=False,  # 业务错误不可重试
            )
        except PublisherError as e:
            e.platform = self.PLATFORM_NAME
            logger.error(f"[{self.PLATFORM_NAME}] 发布失败: {e.message}")
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=e.message,
                debug_info=debug_info,
            )
        except Exception as e:
            logger.exception(f"[{self.PLATFORM_NAME}] 发布异常")
            return PublishResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error=f"发布异常: {e}",
                debug_info=debug_info,
            )
        finally:
            await self._close_browser()

    # ==================== 抽象方法：子类实现 ====================

    @abstractmethod
    async def _do_publish(
        self,
        title: str,
        content: str,
        images: List[str],
        video_path: Optional[str],
        **kwargs,
    ) -> PublishResult:
        """子类实现具体发布逻辑（填写标题、上传图片/视频、点击发布按钮、检测成功）

        注意：
        - 此时 self.page 已打开 PUBLISH_URL，可直接操作
        - 不需要处理浏览器初始化/关闭（已在模板方法中处理）
        - 成功时返回 PublishResult(success=True, url=..., platform_id=...)
        """
        raise NotImplementedError

    # ==================== 钩子方法：子类可覆盖 ====================

    async def _check_login(self) -> bool:
        """默认登录检测：访问 LOGIN_CHECK_URL，检查 URL 重定向 + 关键 cookie

        子类可覆盖为更精确的 DOM 检测（如检测头像元素）。
        """
        if not self.page:
            return False
        try:
            await self.page.goto(
                self.LOGIN_CHECK_URL,
                timeout=20000,
                wait_until="domcontentloaded",
            )
            await asyncio.sleep(2)

            url = self.page.url
            if self.LOGIN_REDIRECT_KEYWORD in url.lower():
                return False

            # 检查关键 cookie
            if self.LOGIN_COOKIE_KEY:
                cookies = await self.context.cookies()
                return any(c.get("name") == self.LOGIN_COOKIE_KEY for c in cookies)
            return True
        except Exception as e:
            logger.error(f"[{self.PLATFORM_NAME}] 检查登录失败: {e}")
            return False

    # ==================== 公共方法：直接复用 ====================

    def _load_storage_state(self) -> Optional[dict]:
        """加载 storage_state（如果存在）"""
        if self.user_id is None:
            return None
        state_path = get_storage_state_path(self.PLATFORM_NAME, self.user_id)
        if not os.path.exists(state_path):
            return None
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.info(f"[{self.PLATFORM_NAME}] 用户 {self.user_id} 已加载 storage_state")
            return state
        except Exception as e:
            logger.warning(f"[{self.PLATFORM_NAME}] 加载 storage_state 失败: {e}")
            return None

    def _parse_cookies(self) -> list:
        """解析 cookies 字符串为 Playwright cookie 列表

        支持：
        1. JSON 字符串（[{"name": ..., "value": ..., "domain": ...}, ...]）
        2. Python list 对象
        3. 单个 cookie 值（子类可覆盖 _build_cookies_from_simple 处理）
        """
        if not self.cookies_raw:
            return []
        if isinstance(self.cookies_raw, list):
            return self.cookies_raw
        try:
            cl = json.loads(self.cookies_raw)
            if isinstance(cl, list):
                return cl
        except Exception:
            pass
        # 单值模式：交给子类处理
        return self._build_cookies_from_simple(self.cookies_raw)

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        """单值 cookie 转 Playwright cookie 列表

        子类按需覆盖，例如：
            小红书 web_session -> [{"name": "web_session", "value": ..., "domain": ".xiaohongshu.com"}]
        """
        return []

    async def _init_browser(self) -> bool:
        """初始化浏览器（共享反检测层）"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await launch_stealth_browser(self.playwright, headless=self.headless)

            if self.storage_state:
                self.context = await create_stealth_context(
                    self.browser, storage_state=self.storage_state
                )
            else:
                self.context = await create_stealth_context(self.browser)
                cookie_list = self._parse_cookies()
                if cookie_list:
                    await self.context.add_cookies(cookie_list)
                    logger.info(f"[{self.PLATFORM_NAME}] 已注入 {len(cookie_list)} 个 cookie")

            self.page = await self.context.new_page()
            return True
        except Exception as e:
            logger.error(f"[{self.PLATFORM_NAME}] 初始化浏览器失败: {e}")
            return False

    async def _persist_state(self):
        """持久化 storage_state（登录态延续）"""
        if not self.user_id or not self.context:
            return
        try:
            state = await self.context.storage_state()
            state_path = get_storage_state_path(self.PLATFORM_NAME, self.user_id)
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
            logger.info(f"[{self.PLATFORM_NAME}] storage_state 已更新到 {state_path}")
        except Exception as e:
            logger.warning(f"[{self.PLATFORM_NAME}] 更新 storage_state 失败: {e}")

    async def _close_browser(self):
        """关闭浏览器（严格 try-finally，避免实例泄漏）"""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        finally:
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None

    async def _detect_biz_error(self) -> Optional[str]:
        """业务错误检测：扫描页面文本，返回错误描述（无错误返回 None）"""
        try:
            page_text = await self.page.evaluate(
                '() => document.body.innerText.slice(0, 1000)'
            )
            for indicator in BIZ_ERROR_INDICATORS:
                if indicator in page_text:
                    return f"{self.PLATFORM_CN_NAME}业务错误: {indicator}"
            return None
        except Exception:
            return None

    @staticmethod
    def is_retryable_error(error: str) -> bool:
        """判断错误是否可重试"""
        if not error:
            return True
        for kw in NO_RETRY_KEYWORDS:
            if kw in error:
                return False
        return True

    async def _try_multiple_selectors(self, selectors: List[str], action: str = "click"):
        """尝试多个 selector，返回第一个成功的元素

        Args:
            selectors: selector 列表（按优先级）
            action: "click" / "fill" / "set_input_files"

        Returns:
            (selector, element) 或 (None, None)
        """
        for selector in selectors:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    return selector, el
            except Exception:
                continue
        return None, None
