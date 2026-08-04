# -*- coding: utf-8 -*-
"""
BaseInteractor 抽象基类

第二阶段：多平台互动能力扩展。

设计要点（与 BasePublisher 对齐）：
1. 模板方法模式：like() / comment() / reply() / follow() 固化
   "初始化→登录检测→导航→执行→持久化→关闭"流程
2. 复用 publisher/stealth_browser.py 的反检测浏览器
3. 子类只需实现 _do_like / _do_comment / _do_reply / _do_follow
4. 模拟真人节奏：随机停留 / 随机滚动（项目 memory 风控规避要求）
5. 严格 try-finally 关闭 Playwright 实例（避免泄漏，项目 memory 教训）

GEO-main 没有互动代码，本模块为新建，但沿用 MediaCrawler 已确立的架构风格。
"""

import asyncio
import json
import logging
import os
import random
from abc import ABC, abstractmethod
from typing import List, Optional

from playwright.async_api import async_playwright

from api.services.publisher.exceptions import (
    BizError,
    ContentBlockedError,
    LoginExpiredError,
    PublisherError,
    RateLimitError,
)
from api.services.publisher.stealth_browser import (
    create_stealth_context,
    get_storage_state_path,
    launch_stealth_browser,
)

from .interaction_models import InteractionResult, InteractionType

logger = logging.getLogger(__name__)


# 互动业务错误关键词
INTERACTION_BIZ_ERRORS = [
    '频次过高', '验证码', '账号异常', '限制', '违规', '请稍后再试',
    '操作太频繁', '权限不足', '风控', '已被限制', '账号被限流',
    '请稍候再试', '操作过于频繁', '滑块验证',
]

# 不可重试关键词
NO_RETRY_INTERACTION_KEYWORDS = [
    '账号被限流', '已被封禁', '账号异常', '风控限制', '违反社区规范',
]


class BaseInteractor(ABC):
    """互动器抽象基类

    子类需设置：
        PLATFORM_NAME: str           # "douyin" / "xiaohongshu" / ...
        PLATFORM_CN_NAME: str
        LOGIN_COOKIE_KEY: str
        LOGIN_CHECK_URL: str
        LOGIN_REDIRECT_KEYWORD: str

    子类实现：
        _do_like() / _do_comment() / _do_reply() / _do_follow()
        可选：_navigate_to_post() 平台特定的帖子导航逻辑
    """

    PLATFORM_NAME: str = ""
    PLATFORM_CN_NAME: str = ""
    LOGIN_COOKIE_KEY: str = ""
    LOGIN_CHECK_URL: str = ""
    LOGIN_REDIRECT_KEYWORD: str = "login"

    # 能力声明（部分平台不支持收藏/转发）
    SUPPORTS_LIKE: bool = True
    SUPPORTS_COMMENT: bool = True
    SUPPORTS_REPLY: bool = True
    SUPPORTS_FOLLOW: bool = True
    SUPPORTS_COLLECT: bool = False

    def __init__(
        self,
        cookies: str,
        user_id: Optional[int] = None,
        *,
        headless: bool = True,
        region: Optional[str] = None,
        proxy_url: Optional[str] = None,
    ):
        """初始化互动器

        Args:
            cookies: cookie 字符串
            user_id: 用户 ID（用于 storage_state 持久化）
            headless: 是否无头模式
            region: 地域（cn/us/eu/sea），用于代理 IP 匹配
            proxy_url: 显式指定代理 URL（优先级高于 region 自动匹配）
        """
        self.cookies_raw = cookies or ""
        self.user_id = user_id
        self.headless = headless
        self.region = region or ""
        self.proxy_url = proxy_url or ""
        self.storage_state = self._load_storage_state()

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    # ==================== 模板方法：四种互动主流程 ====================

    async def like(self, post_url: str, **kwargs) -> InteractionResult:
        """点赞（模板方法）"""
        return await self._run_interaction(
            InteractionType.LIKE, post_url, content="", **kwargs
        )

    async def comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        """评论（模板方法）"""
        if not content or not content.strip():
            return InteractionResult(
                success=False,
                platform=self.PLATFORM_NAME,
                interaction_type=InteractionType.COMMENT.value,
                target_url=post_url,
                error="评论内容不能为空",
                retryable=False,
            )
        return await self._run_interaction(
            InteractionType.COMMENT, post_url, content=content, **kwargs
        )

    async def reply(
        self, post_url: str, comment_id: str, content: str, **kwargs
    ) -> InteractionResult:
        """回复评论（模板方法）"""
        if not content or not content.strip():
            return InteractionResult(
                success=False,
                platform=self.PLATFORM_NAME,
                interaction_type=InteractionType.REPLY.value,
                target_url=post_url,
                error="回复内容不能为空",
                retryable=False,
            )
        return await self._run_interaction(
            InteractionType.REPLY, post_url, content=content, target_id=comment_id, **kwargs
        )

    async def follow(self, user_url: str, **kwargs) -> InteractionResult:
        """关注（模板方法）"""
        return await self._run_interaction(
            InteractionType.FOLLOW, post_url=user_url, content="", **kwargs
        )

    # ==================== 互动执行骨架（核心模板方法）====================

    async def _run_interaction(
        self,
        interaction_type: InteractionType,
        post_url: str,
        content: str = "",
        target_id: str = "",
        **kwargs,
    ) -> InteractionResult:
        debug_info: List[str] = []
        try:
            # 1. 能力校验
            if interaction_type == InteractionType.LIKE and not self.SUPPORTS_LIKE:
                return self._unsupported(interaction_type, post_url, content)
            if interaction_type == InteractionType.COMMENT and not self.SUPPORTS_COMMENT:
                return self._unsupported(interaction_type, post_url, content)
            if interaction_type == InteractionType.REPLY and not self.SUPPORTS_REPLY:
                return self._unsupported(interaction_type, post_url, content)
            if interaction_type == InteractionType.FOLLOW and not self.SUPPORTS_FOLLOW:
                return self._unsupported(interaction_type, post_url, content)

            # 2. 初始化浏览器
            if not await self._init_browser():
                return InteractionResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    interaction_type=interaction_type.value,
                    target_url=post_url,
                    error="浏览器初始化失败",
                    debug_info=debug_info,
                )
            debug_info.append("✅ 浏览器初始化成功")

            # 3. 登录检测
            if not await self._check_login():
                debug_info.append("❌ 登录已失效")
                return InteractionResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    interaction_type=interaction_type.value,
                    target_url=post_url,
                    error=f"{self.PLATFORM_CN_NAME}登录已失效",
                    debug_info=debug_info,
                    retryable=False,
                )
            debug_info.append("✅ 登录状态正常")

            # 4. 导航到目标帖子
            await self._navigate_to_post(post_url)
            await self._human_delay(2, 4)  # 模拟真人阅读
            debug_info.append(f"✅ 已导航到 {post_url}")

            # 5. 执行具体互动
            if interaction_type == InteractionType.LIKE:
                result = await self._do_like(post_url, **kwargs)
            elif interaction_type == InteractionType.COMMENT:
                result = await self._do_comment(post_url, content, **kwargs)
            elif interaction_type == InteractionType.REPLY:
                result = await self._do_reply(post_url, target_id, content, **kwargs)
            elif interaction_type == InteractionType.FOLLOW:
                result = await self._do_follow(post_url, **kwargs)
            else:
                return InteractionResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    interaction_type=interaction_type.value,
                    target_url=post_url,
                    error=f"不支持的互动类型: {interaction_type}",
                    retryable=False,
                )

            result.debug_info = debug_info + result.debug_info
            result.platform = self.PLATFORM_NAME
            result.interaction_type = interaction_type.value
            result.target_url = post_url
            result.content = content
            result.target_id = target_id

            if result.success:
                await self._persist_state()

            return result

        except LoginExpiredError as e:
            return self._wrap_exception(interaction_type, post_url, content, e, retryable=False)
        except RateLimitError as e:
            return self._wrap_exception(interaction_type, post_url, content, e, retryable=True)
        except (BizError, ContentBlockedError) as e:
            return self._wrap_exception(interaction_type, post_url, content, e, retryable=False)
        except PublisherError as e:
            return self._wrap_exception(interaction_type, post_url, content, e, retryable=True)
        except Exception as e:
            logger.exception(f"[{self.PLATFORM_NAME}] 互动异常")
            return InteractionResult(
                success=False,
                platform=self.PLATFORM_NAME,
                interaction_type=interaction_type.value,
                target_url=post_url,
                content=content,
                error=f"互动异常: {e}",
                debug_info=debug_info,
            )
        finally:
            await self._close_browser()

    # ==================== 抽象方法：子类实现 ====================

    @abstractmethod
    async def _do_like(self, post_url: str, **kwargs) -> InteractionResult:
        """子类实现点赞逻辑"""
        raise NotImplementedError

    @abstractmethod
    async def _do_comment(self, post_url: str, content: str, **kwargs) -> InteractionResult:
        """子类实现评论逻辑"""
        raise NotImplementedError

    @abstractmethod
    async def _do_reply(
        self, post_url: str, comment_id: str, content: str, **kwargs
    ) -> InteractionResult:
        """子类实现回复评论逻辑"""
        raise NotImplementedError

    @abstractmethod
    async def _do_follow(self, user_url: str, **kwargs) -> InteractionResult:
        """子类实现关注逻辑"""
        raise NotImplementedError

    # ==================== 私信钩子（阶段四任务 4.1，默认未实现） ====================

    async def fetch_direct_messages(self, limit: int = 20) -> list:
        """拉取平台新私信（默认未实现，子类按需覆盖）

        Returns:
            List[DirectMessage] - 见 api/services/dm/dm_models.py
        """
        return []

    async def send_dm_reply(
        self, conversation_id: str, reply_text: str, **kwargs
    ) -> InteractionResult:
        """跨平台私信回复（默认未实现，子类按需覆盖）

        Returns:
            InteractionResult
        """
        return self._unsupported(
            InteractionType.COMMENT, conversation_id, reply_text
        )

    # ==================== 钩子方法 ====================

    async def _navigate_to_post(self, post_url: str):
        """导航到帖子页（默认实现，子类可覆盖为特殊导航）"""
        if not self.page:
            return
        await self.page.goto(post_url, timeout=20000, wait_until="domcontentloaded")
        # 模拟真人滚动浏览
        await self._human_scroll()

    async def _check_login(self) -> bool:
        """登录检测（与 BasePublisher 一致）"""
        if not self.page:
            return False
        try:
            await self.page.goto(
                self.LOGIN_CHECK_URL, timeout=20000, wait_until="domcontentloaded"
            )
            await asyncio.sleep(2)
            url = self.page.url
            if self.LOGIN_REDIRECT_KEYWORD in url.lower():
                return False
            if self.LOGIN_COOKIE_KEY:
                cookies = await self.context.cookies()
                return any(c.get("name") == self.LOGIN_COOKIE_KEY for c in cookies)
            return True
        except Exception as e:
            logger.error(f"[{self.PLATFORM_NAME}] 检查登录失败: {e}")
            return False

    # ==================== 公共工具方法 ====================

    async def _human_delay(self, min_s: float = 1.0, max_s: float = 3.0):
        """模拟真人停顿（风控规避）"""
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def _human_scroll(self, times: int = 3):
        """模拟真人滚动浏览（风控规避）"""
        if not self.page:
            return
        for _ in range(times):
            await self.page.mouse.wheel(0, random.randint(200, 600))
            await self._human_delay(0.5, 1.5)

    async def _try_click_selectors(self, selectors: List[str], timeout: int = 5000) -> bool:
        """尝试多个 selector 点击，返回是否成功"""
        if not self.page:
            return False
        for selector in selectors:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0:
                    await el.click(timeout=timeout)
                    return True
            except Exception:
                continue
        return False

    async def _detect_biz_error(self) -> Optional[str]:
        """检测业务错误（互动场景）"""
        try:
            page_text = await self.page.evaluate(
                '() => document.body.innerText.slice(0, 1000)'
            )
            for indicator in INTERACTION_BIZ_ERRORS:
                if indicator in page_text:
                    return f"{self.PLATFORM_CN_NAME}互动业务错误: {indicator}"
            return None
        except Exception:
            return None

    def _unsupported(
        self, interaction_type: InteractionType, post_url: str, content: str
    ) -> InteractionResult:
        return InteractionResult(
            success=False,
            platform=self.PLATFORM_NAME,
            interaction_type=interaction_type.value,
            target_url=post_url,
            content=content,
            error=f"{self.PLATFORM_CN_NAME}不支持{interaction_type.value}操作",
            retryable=False,
        )

    def _wrap_exception(
        self,
        interaction_type: InteractionType,
        post_url: str,
        content: str,
        e: Exception,
        retryable: bool,
    ) -> InteractionResult:
        e.platform = self.PLATFORM_NAME
        logger.warning(f"[{self.PLATFORM_NAME}] 互动失败: {e}")
        return InteractionResult(
            success=False,
            platform=self.PLATFORM_NAME,
            interaction_type=interaction_type.value,
            target_url=post_url,
            content=content,
            error=str(e.message if hasattr(e, "message") else e),
            retryable=retryable,
        )

    # ==================== 浏览器生命周期（复用 publisher 模式）====================

    def _load_storage_state(self) -> Optional[dict]:
        if self.user_id is None:
            return None
        state_path = get_storage_state_path(self.PLATFORM_NAME, self.user_id)
        if not os.path.exists(state_path):
            return None
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[{self.PLATFORM_NAME}] 加载 storage_state 失败: {e}")
            return None

    def _parse_cookies(self) -> list:
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
        return self._build_cookies_from_simple(self.cookies_raw)

    def _build_cookies_from_simple(self, cookie_value: str) -> list:
        return []

    async def _init_browser(self) -> bool:
        try:
            self.playwright = await async_playwright().start()
            # 地域适配：按 region 自动匹配代理（海外机器人强制使用对应国家 IP）
            proxy_url = self.proxy_url or self._resolve_proxy_by_region()
            self.browser = await launch_stealth_browser(
                self.playwright, headless=self.headless, proxy=proxy_url
            )
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
            if proxy_url:
                logger.info(
                    f"[{self.PLATFORM_NAME}] 使用代理: {proxy_url} (region={self.region or 'auto'})"
                )
            self.page = await self.context.new_page()
            return True
        except Exception as e:
            logger.error(f"[{self.PLATFORM_NAME}] 初始化浏览器失败: {e}")
            return False

    def _resolve_proxy_by_region(self) -> Optional[str]:
        """地域适配：按平台/region 匹配代理 IP

        PRD 5.4：海外机器人执行互动时强制使用对应国家 IP。
        """
        if not self.region:
            return None
        try:
            from api.services.risk_control.proxy_pool import get_proxy_pool
            pool = get_proxy_pool()
            # region → country 映射（cn→CN, us→US, eu→EU, sea→SEA）
            country_map = {"cn": "CN", "us": "US", "eu": "EU", "sea": "SEA"}
            country = country_map.get(self.region.lower(), self.region.upper())
            proxy = pool.get_proxy_by_country(self.PLATFORM_NAME, country)
            return proxy
        except Exception as e:
            logger.warning(f"[{self.PLATFORM_NAME}] 代理匹配失败: {e}")
            return None

    async def _persist_state(self):
        if not self.user_id or not self.context:
            return
        try:
            state = await self.context.storage_state()
            state_path = get_storage_state_path(self.PLATFORM_NAME, self.user_id)
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[{self.PLATFORM_NAME}] 更新 storage_state 失败: {e}")

    async def _close_browser(self):
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

    @staticmethod
    def is_retryable_error(error: str) -> bool:
        if not error:
            return True
        for kw in NO_RETRY_INTERACTION_KEYWORDS:
            if kw in error:
                return False
        return True
