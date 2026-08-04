# -*- coding: utf-8 -*-
"""
AI 引用率定时检测调度器

迁移自 GEO-main geo_system/backend/ai_citation_scheduler.py，适配 MediaCrawler：
1. 调度层适配：原使用 threading.Thread + time.sleep，现改为 asyncio.create_task +
   asyncio.sleep，符合 MediaCrawler 异步架构。
2. 配置适配：调度时间、品牌名称、平台列表等通过环境变量读取，禁止硬编码。
3. 日志适配：保留 logging，与 MediaCrawler 风格一致。
4. 保留原业务逻辑：每日固定时间执行批量引用率检测，支持手动触发与配置更新。

对应 PRD：AI 引用率监控 - 定时检测调度模块。

适配点说明：
- monitoring_service 通过依赖注入传入（MediaCrawler 的 monitoring 服务尚未实现），
  调度器对 batch_check_citation 的调用兼容 sync/async 两种实现。
- 调度时间、品牌名称等参数从环境变量读取，见模块级常量。
"""

import asyncio
import inspect
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认每日凌晨 3 点执行（避开业务高峰），可通过环境变量覆盖
DEFAULT_CHECK_HOUR = int(os.environ.get("AI_CITATION_CHECK_HOUR", "3"))
# 每 24 小时一次，可通过环境变量覆盖
CHECK_INTERVAL_SECONDS = int(os.environ.get("AI_CITATION_CHECK_INTERVAL", str(24 * 3600)))
# 等待轮询粒度（秒），便于响应 stop()
POLL_GRANULARITY_SECONDS = int(os.environ.get("AI_CITATION_POLL_GRANULARITY", "60"))


class AICitationScheduler:
    """AI 引用率定时检测调度器（基于 asyncio）"""

    def __init__(self, monitoring_service: Any = None):
        self.monitoring_service = monitoring_service
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # 默认配置（可被 update_config 覆盖；环境变量优先于硬编码默认值）
        self.brand_name = os.environ.get("AI_CITATION_BRAND_NAME", "默认品牌")
        platforms_env = os.environ.get("AI_CITATION_PLATFORMS", "chatgpt")
        self.platforms: List[str] = [p.strip() for p in platforms_env.split(",") if p.strip()]
        self.enabled = True  # 总开关

    def set_monitoring_service(self, service: Any) -> None:
        """注入 monitoring_service（支持延迟注入）"""
        self.monitoring_service = service
        logger.info("[AICitationScheduler] 已注入 monitoring_service")

    def update_config(
        self,
        brand_name: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        """更新调度配置"""
        if brand_name is not None:
            self.brand_name = brand_name
        if platforms is not None:
            self.platforms = platforms
        if enabled is not None:
            self.enabled = enabled
        logger.info(
            "[AICitationScheduler] 配置已更新: enabled=%s, brand=%s, platforms=%s",
            self.enabled, self.brand_name, self.platforms,
        )

    async def start(self) -> None:
        """启动定时调度（asyncio.create_task）"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_schedule_loop())
        logger.info(
            "[AICitationScheduler] 定时检测已启动，每日 %d:00 执行，品牌=%s，平台=%s",
            DEFAULT_CHECK_HOUR, self.brand_name, self.platforms,
        )

    async def stop(self) -> None:
        """停止调度"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("[AICitationScheduler] 已停止")

    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running and self._task is not None and not self._task.done()

    async def _run_schedule_loop(self) -> None:
        """调度主循环"""
        while self._running:
            # 计算到下一个固定时刻的等待时间
            next_run = self._next_run_time()
            wait_seconds = (next_run - datetime.now()).total_seconds()
            if wait_seconds < 0:
                wait_seconds = CHECK_INTERVAL_SECONDS

            # 分段等待，便于响应 stop()
            waited = 0.0
            while self._running and waited < wait_seconds:
                await asyncio.sleep(POLL_GRANULARITY_SECONDS)
                waited += POLL_GRANULARITY_SECONDS

            if not self._running:
                break

            if not self.enabled:
                logger.info("[AICitationScheduler] 调度已禁用，跳过本次执行")
                continue

            try:
                await self._run_batch_check()
            except Exception as e:
                logger.error("[AICitationScheduler] 定时检测出错: %s", e)

    def _next_run_time(self) -> datetime:
        """计算下次运行时间"""
        now = datetime.now()
        next_run = now.replace(hour=DEFAULT_CHECK_HOUR, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

    async def _run_batch_check(self) -> Optional[Dict]:
        """执行一次批量检测（兼容 sync/async monitoring_service）"""
        if not self.monitoring_service:
            logger.warning("[AICitationScheduler] monitoring_service 未注入，跳过")
            return None

        batch_name = f"scheduled_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.info("[AICitationScheduler] 开始定时检测: %s", batch_name)

        result = self.monitoring_service.batch_check_citation(
            keywords=None,  # 使用数据库中所有 active 关键词
            platforms=self.platforms,
            brand_name=self.brand_name,
            batch_name=batch_name,
        )
        # 兼容 async monitoring_service
        if inspect.isawaitable(result):
            result = await result

        if result and result.get("success"):
            logger.info(
                "[AICitationScheduler] 定时检测完成: batch_id=%s, 总查询=%s, 被引用=%s, 引用率=%s%%",
                result.get("batch_id"), result.get("total_queries"),
                result.get("mentioned_count"), result.get("citation_rate"),
            )
        else:
            logger.error(
                "[AICitationScheduler] 定时检测失败: %s",
                result.get("error") if result else "无返回结果",
            )
        return result

    async def run_now(self) -> Dict:
        """立即执行一次（手动触发）"""
        if not self.monitoring_service:
            return {"success": False, "error": "monitoring_service 未注入"}

        batch_name = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        result = self.monitoring_service.batch_check_citation(
            keywords=None,
            platforms=self.platforms,
            brand_name=self.brand_name,
            batch_name=batch_name,
        )
        if inspect.isawaitable(result):
            result = await result
        return result or {"success": False, "error": "无返回结果"}


# 单例
_ai_citation_scheduler: Optional[AICitationScheduler] = None


def get_ai_citation_scheduler() -> AICitationScheduler:
    """获取 AI 引用率定时检测调度器单例"""
    global _ai_citation_scheduler
    if _ai_citation_scheduler is None:
        _ai_citation_scheduler = AICitationScheduler()
    return _ai_citation_scheduler
