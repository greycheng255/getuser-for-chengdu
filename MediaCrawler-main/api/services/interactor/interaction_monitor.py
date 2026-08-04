# -*- coding: utf-8 -*-
"""
统一评论监控服务（多平台并行）

对应 PRD 5.4 评论监控，将 X 专用监控扩展到多平台：
1. 维护监控列表（platform + post_url + my_comment_id）
2. 并行轮询各平台新评论
3. 识别"回复我的评论"的回复（needs_reply）
4. 调用 AI 生成差异化回复
5. 通过 MultiInteractor 发送回复
6. watchdog 自动重启（与现有 X monitor 一致）

复用 MediaCrawler 现有的 AI 服务（ai_agent_client）生成回复。
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from .interaction_models import InteractionStatus, InteractionTask, InteractionType, MonitoredComment
from .interactor_factory import InteractorFactory
from .multi_interactor import get_multi_interactor

logger = logging.getLogger(__name__)

# 监控配置
DEFAULT_CHECK_INTERVAL = 300  # 5 分钟轮询一次
MAX_REPLY_PER_CYCLE = 10  # 每轮最多回复数（频次控制）


class MonitoredPost:
    """被监控的帖子"""

    def __init__(
        self,
        platform: str,
        post_url: str,
        my_comment_id: str = "",
        my_username: str = "",
        auto_reply: bool = True,
    ):
        self.platform = platform
        self.post_url = post_url
        self.my_comment_id = my_comment_id
        self.my_username = my_username
        self.auto_reply = auto_reply
        self.replied_comment_ids: set = set()  # 已回复的评论 ID
        self.last_checked: Optional[datetime] = None


class InteractionMonitor:
    """统一评论监控服务"""

    def __init__(self, check_interval: int = DEFAULT_CHECK_INTERVAL):
        self.check_interval = check_interval
        self._monitored: List[MonitoredPost] = []
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()

    # ==================== 监控列表管理 ====================

    async def add_post(
        self,
        platform: str,
        post_url: str,
        my_comment_id: str = "",
        my_username: str = "",
        auto_reply: bool = True,
    ) -> bool:
        """添加监控帖子"""
        async with self._lock:
            # 去重
            for m in self._monitored:
                if m.platform == platform and m.post_url == post_url:
                    m.my_comment_id = my_comment_id or m.my_comment_id
                    m.my_username = my_username or m.my_username
                    return True
            self._monitored.append(
                MonitoredPost(platform, post_url, my_comment_id, my_username, auto_reply)
            )
            logger.info(f"[Monitor] 已添加监控: {platform} {post_url}")
            return True

    async def remove_post(self, platform: str, post_url: str) -> bool:
        async with self._lock:
            before = len(self._monitored)
            self._monitored = [
                m for m in self._monitored
                if not (m.platform == platform and m.post_url == post_url)
            ]
            return len(self._monitored) < before

    async def list_monitored(self) -> List[Dict]:
        async with self._lock:
            return [
                {
                    "platform": m.platform,
                    "post_url": m.post_url,
                    "my_comment_id": m.my_comment_id,
                    "my_username": m.my_username,
                    "auto_reply": m.auto_reply,
                    "replied_count": len(m.replied_comment_ids),
                    "last_checked": m.last_checked.isoformat() if m.last_checked else None,
                }
                for m in self._monitored
            ]

    # ==================== 监控主循环 ====================

    async def start(self):
        """启动监控（带 watchdog 自动重启）"""
        if self._running:
            logger.warning("[Monitor] 监控已在运行")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_with_watchdog())
        logger.info("[Monitor] 评论监控服务已启动")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Monitor] 评论监控服务已停止")

    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def _run_with_watchdog(self):
        """watchdog：异常自动重启"""
        while self._running:
            try:
                await self._monitor_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"[Monitor] 监控循环异常，5s 后重启: {e}")
                await asyncio.sleep(5)

    async def _monitor_loop(self):
        """监控主循环"""
        while self._running:
            try:
                async with self._lock:
                    monitored = list(self._monitored)
                if monitored:
                    await self._check_all_posts(monitored)
            except Exception as e:
                logger.error(f"[Monitor] 轮询异常: {e}")
            await asyncio.sleep(self.check_interval)

    async def _check_all_posts(self, monitored: List[MonitoredPost]):
        """并行检查所有监控帖子的新评论"""
        tasks = [self._check_one_post(m) for m in monitored]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_one_post(self, post: MonitoredPost):
        """检查单个帖子的新评论并自动回复"""
        if not InteractorFactory.is_supported(post.platform):
            return
        post.last_checked = datetime.utcnow()
        try:
            comments = await self._fetch_comments(post)
            if not comments:
                return
            # 过滤需要回复的
            to_reply = [
                c for c in comments
                if c.needs_reply and c.comment_id not in post.replied_comment_ids
            ][:MAX_REPLY_PER_CYCLE]
            if not to_reply:
                return
            logger.info(
                f"[Monitor][{post.platform}] {post.post_url} 发现 {len(to_reply)} 条待回复评论"
            )
            if not post.auto_reply:
                return
            await self._auto_reply(post, to_reply)
        except Exception as e:
            logger.error(f"[Monitor][{post.platform}] 检查帖子失败: {e}")

    async def _fetch_comments(self, post: MonitoredPost) -> List[MonitoredComment]:
        """获取帖子评论（子类/平台特定实现）

        默认实现：通过 Interactor 的 page 抓取评论 DOM。
        各平台可在 Interactor 中扩展 fetch_comments 方法。
        """
        try:
            # 尝试调用 interactor 的 fetch_comments（如果实现了）
            from api.services.publisher.account_service import get_account_service

            account = await get_account_service().acquire_cookie(
                post.platform, user_id=1
            )
            if not account:
                return []
            interactor = InteractorFactory.create(
                post.platform, cookies=account.cookies, user_id=1
            )
            # 初始化浏览器
            if not await interactor._init_browser():
                await interactor._close_browser()
                return []
            try:
                await interactor._navigate_to_post(post.post_url)
                await interactor._human_delay(2, 4)
                # 调用平台特定的评论抓取（钩子方法，默认空实现）
                fetcher = getattr(interactor, "fetch_comments", None)
                if fetcher:
                    comments = await fetcher(post.post_url, my_username=post.my_username)
                    return comments or []
                return []
            finally:
                await interactor._close_browser()
        except Exception as e:
            logger.error(f"[Monitor][{post.platform}] 抓取评论失败: {e}")
            return []

    async def _auto_reply(self, post: MonitoredPost, comments: List[MonitoredComment]):
        """AI 自动回复评论"""
        for comment in comments:
            try:
                reply_text = await self._generate_reply(post, comment)
                if not reply_text:
                    continue
                task = InteractionTask(
                    interaction_type=InteractionType.REPLY.value,
                    target_url=post.post_url,
                    target_id=comment.comment_id,
                    content=reply_text,
                    target_platforms=[post.platform],
                    user_id=1,
                )
                result = await get_multi_interactor().interact_across_platforms(task)
                r = result.platform_results.get(post.platform)
                if r and r.success:
                    post.replied_comment_ids.add(comment.comment_id)
                    logger.info(
                        f"[Monitor][{post.platform}] 已回复 {comment.comment_id}: {reply_text[:30]}"
                    )
                else:
                    logger.warning(
                        f"[Monitor][{post.platform}] 回复失败: {r.error if r else 'unknown'}"
                    )
                # 随机间隔（风控规避）
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"[Monitor] 自动回复异常: {e}")

    async def _generate_reply(self, post: MonitoredPost, comment: MonitoredComment) -> Optional[str]:
        """调用 AI 生成回复（复用 MediaCrawler ai_agent_client）"""
        try:
            from api.services.ai_agent_client import get_ai_agent_client, is_ai_in_cooldown, is_ai_expected_error

            if is_ai_in_cooldown():
                logger.debug("[Monitor] AI 服务冷却中，跳过回复生成")
                return None
            prompt = (
                f"有人在{post.platform}上回复了我的评论：\n"
                f"对方说：{comment.comment_text}\n"
                f"请生成一条简短、自然、有人情味的回复（不超过50字），"
                f"不要硬广，可以适当引导关注。直接输出回复内容，不要解释。"
            )
            client = get_ai_agent_client()
            reply = await client.generate_text(prompt)
            return reply.strip() if reply else None
        except Exception as e:
            if is_ai_expected_error(e):
                logger.debug(f"[Monitor] AI 预期内错误跳过回复生成: {e}")
            else:
                logger.error(f"[Monitor] AI 生成回复失败: {e}")
            return None


# 单例
_monitor: Optional[InteractionMonitor] = None


def get_interaction_monitor() -> InteractionMonitor:
    global _monitor
    if _monitor is None:
        _monitor = InteractionMonitor()
    return _monitor
