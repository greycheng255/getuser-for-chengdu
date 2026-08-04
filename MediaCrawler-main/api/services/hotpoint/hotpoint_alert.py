# -*- coding: utf-8 -*-
"""
突发热点预警检测服务

阶段一 P0 任务 1.3：补齐 PRD 5.1.3 第 6 条"高热度突发热点弹窗提醒 + 一键取材"。

检测算法：
1. 维护热点历史热度曲线
2. 每 5 分钟扫描最近 30 分钟热点
3. 检测两个条件（任一命中即触发）：
   - delta_threshold: 10 分钟内热度增量 ≥ 阈值（默认 1000）
   - velocity_threshold: 10 分钟内热度增速 ≥ 2x
4. 触发后调用 emit_hotpoint_burst() 推送预警
5. 同一热点 30 分钟内不重复预警（冷却机制）

复用：
- hotpoint_fetcher.HotpointFetcher：获取当前热点
- alert.alert_center.emit_hotpoint_burst：推送预警
- hotpoint_classifier.HotpointClassifier：获取适配平台
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from api.services.alert.alert_center import emit_hotpoint_burst

logger = logging.getLogger(__name__)


@dataclass
class HeatSample:
    """热度采样点"""
    hotspot_id: str
    title: str
    platform: str
    heat_value: int
    sampled_at: float  # timestamp
    url: str = ""  # 热点帖子原始 URL（供预警中心展示，让用户能跳转查看具体内容）


@dataclass
class BurstAlertConfig:
    """突发预警配置"""
    delta_threshold: int = 1000           # 10 分钟内热度增量阈值
    velocity_threshold: float = 2.0       # 10 分钟内增速阈值
    cooldown_seconds: int = 1800          # 同一热点冷却 30 分钟
    scan_interval_seconds: int = 300      # 扫描间隔 5 分钟
    history_window_seconds: int = 1800    # 历史窗口 30 分钟


class HotpointAlertService:
    """突发热点预警服务"""

    def __init__(self, config: Optional[BurstAlertConfig] = None):
        self.config = config or BurstAlertConfig()
        # 热点历史采样：hotspot_id -> List[HeatSample]
        self._history: Dict[str, List[HeatSample]] = {}
        # 预警冷却：hotspot_id -> last_alert_ts
        self._last_alert: Dict[str, float] = {}
        # 后台任务
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> bool:
        """启动后台扫描任务"""
        if self._running:
            return True
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        logger.info(
            f"[HotpointAlert] 后台扫描已启动，间隔 {self.config.scan_interval_seconds}s"
        )
        return True

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def _scan_loop(self) -> None:
        """后台扫描主循环"""
        while self._running:
            try:
                await self._scan_once()
            except Exception as e:
                logger.warning(f"[HotpointAlert] 扫描异常: {e}")
            await asyncio.sleep(self.config.scan_interval_seconds)

    async def _scan_once(self) -> int:
        """扫描一次，返回触发的预警数"""
        # 1. 采样当前热点
        current_samples = await self._fetch_current_hotspots()
        now = time.time()
        for s in current_samples:
            self._history.setdefault(s.hotspot_id, []).append(s)

        # 2. 清理过期历史
        cutoff = now - self.config.history_window_seconds
        for hid in list(self._history.keys()):
            self._history[hid] = [s for s in self._history[hid] if s.sampled_at >= cutoff]
            if not self._history[hid]:
                del self._history[hid]

        # 3. 检测突发
        alert_count = 0
        for hid, samples in self._history.items():
            if len(samples) < 2:
                continue
            # 冷却检查
            last_alert_ts = self._last_alert.get(hid, 0)
            if now - last_alert_ts < self.config.cooldown_seconds:
                continue
            # 取 10 分钟前的样本作为基线
            ten_min_ago = now - 600
            baseline_samples = [s for s in samples if s.sampled_at <= ten_min_ago]
            if not baseline_samples:
                continue
            baseline = max(baseline_samples, key=lambda s: s.heat_value)
            current = max(samples, key=lambda s: s.heat_value)
            delta = current.heat_value - baseline.heat_value
            velocity = current.heat_value / max(baseline.heat_value, 1)
            if delta >= self.config.delta_threshold or velocity >= self.config.velocity_threshold:
                # 触发预警
                platforms = await self._get_recommend_platforms(current.title)
                await emit_hotpoint_burst(
                    hotspot_id=hid,
                    title=current.title,
                    heat_value=current.heat_value,
                    delta=delta,
                    velocity=velocity,
                    platforms=platforms,
                    post_url=current.url,
                )
                self._last_alert[hid] = now
                alert_count += 1
                logger.info(
                    f"[HotpointAlert] 突发预警: {current.title[:30]} delta={delta} velocity={velocity:.2f}"
                )
        return alert_count

    async def _fetch_current_hotspots(self) -> List[HeatSample]:
        """获取当前热点（从数据库）

        优先通过 get_hot_items_store() 读取 hot_items 通用热点表；
        若表为空或读取失败则降级到 x_twitter_trending_post（X 平台热点）。
        两次读取使用独立连接，避免事务中止影响。
        """
        now = time.time()
        try:
            from api.services.hotpoint.hot_items_store import get_hot_items_store

            store = get_hot_items_store()
            items = await store.list_recent(hours=1, limit=50)

            if not items:
                # 降级：使用 X 平台 trending_post 表（独立连接）
                try:
                    from sqlalchemy import text as sql_text
                    from api.services.hotpoint.hot_items_store import HotItemsStore

                    engine = HotItemsStore._get_engine()
                    if engine is None:
                        return []
                    async with engine.connect() as conn:
                        rows = await conn.execute(
                            sql_text(
                                "SELECT id, COALESCE(topic, content), 'x_twitter', "
                                " COALESCE(CAST(likes_count AS INTEGER), 0) "
                                " FROM x_twitter_trending_post "
                                " WHERE crawl_ts >= EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour')::BIGINT "
                                " ORDER BY CAST(likes_count AS INTEGER) DESC LIMIT 50"
                            )
                        )
                        fetched = rows.fetchall()
                except Exception as e:
                    logger.warning(f"[HotpointAlert] 降级查询 trending_post 失败: {e}")
                    return []
                samples = []
                for r in fetched:
                    try:
                        samples.append(HeatSample(
                            hotspot_id=str(r[0]),
                            title=r[1] or "",
                            platform=r[2] or "",
                            heat_value=int(r[3] or 0),
                            sampled_at=now,
                        ))
                    except Exception:
                        continue
                return samples

            samples = []
            for it in items:
                try:
                    samples.append(HeatSample(
                        hotspot_id=str(it.get("hot_id") or it.get("id") or ""),
                        title=it.get("title") or "",
                        platform=it.get("platform") or "",
                        heat_value=int(it.get("heat_value") or 0),
                        sampled_at=now,
                        url=it.get("url") or it.get("post_url") or "",
                    ))
                except Exception:
                    continue
            return samples
        except Exception as e:
            logger.warning(f"[HotpointAlert] 采样失败: {e}")
            return []

    async def _get_recommend_platforms(self, title: str) -> List[str]:
        """获取热点适配平台"""
        try:
            from api.services.hotpoint.hotpoint_classifier import get_hotpoint_classifier
            classifier = get_hotpoint_classifier()
            return await classifier.recommend_platforms(title)
        except Exception:
            # 兜底：返回所有平台
            return ["douyin", "xiaohongshu", "weibo", "bilibili", "zhihu", "kuaishou"]

    async def manual_check(self, hotspot_id: str) -> Optional[Dict[str, Any]]:
        """手动触发单热点检测（用于调试 / API 调用）"""
        samples = self._history.get(hotspot_id, [])
        if len(samples) < 2:
            return None
        baseline = min(samples, key=lambda s: s.heat_value)
        current = max(samples, key=lambda s: s.heat_value)
        delta = current.heat_value - baseline.heat_value
        velocity = current.heat_value / max(baseline.heat_value, 1)
        return {
            "hotspot_id": hotspot_id,
            "title": current.title,
            "baseline_heat": baseline.heat_value,
            "current_heat": current.heat_value,
            "delta": delta,
            "velocity": velocity,
            "is_burst": delta >= self.config.delta_threshold or velocity >= self.config.velocity_threshold,
            "samples_count": len(samples),
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取监控统计"""
        return {
            "running": self.is_running(),
            "tracked_hotspots": len(self._history),
            "total_samples": sum(len(v) for v in self._history.values()),
            "alerts_today": sum(
                1 for ts in self._last_alert.values()
                if ts > time.time() - 86400
            ),
            "config": {
                "delta_threshold": self.config.delta_threshold,
                "velocity_threshold": self.config.velocity_threshold,
                "scan_interval_seconds": self.config.scan_interval_seconds,
                "cooldown_seconds": self.config.cooldown_seconds,
            },
        }


# ============ 单例 ============
_service: Optional[HotpointAlertService] = None


def get_hotpoint_alert_service() -> HotpointAlertService:
    global _service
    if _service is None:
        _service = HotpointAlertService()
    return _service
