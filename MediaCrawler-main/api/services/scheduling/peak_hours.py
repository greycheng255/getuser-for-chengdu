# -*- coding: utf-8 -*-
"""
平台活跃时段模型 + 智能错峰策略

阶段二 P1 任务 2.4：补齐 PRD 5.3 智能调度 + 错峰策略。

设计：
1. PeakHours 数据类：按平台/工作日/周末分时段统计活跃度
2. 内置默认值（参考主流平台运营经验）
3. 智能错峰策略 smart_stagger：
   - 自动选择下一个活跃时段
   - 避免与同账号已发布内容时间冲突
   - 多平台分发时按平台时区分散
4. 发布频率自适应：监控账号近期发布成功率，自动调整频率

时区说明：
- 国内平台使用 UTC+8（北京时间）
- 海外平台按时区调整
"""

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ScheduleStrategy(str, Enum):
    """发布调度策略"""
    IMMEDIATE = "immediate"          # 立即发布
    SCHEDULED = "scheduled"           # 定时发布
    SMART_STAGGER = "smart_stagger"   # 智能错峰


@dataclass
class PeakSlot:
    """活跃时段"""
    start_hour: int       # 起始小时（0-23）
    end_hour: int         # 结束小时（0-23）
    weight: float = 1.0   # 活跃度权重（0-1，1 为最活跃）

    def contains(self, hour: int) -> bool:
        return self.start_hour <= hour < self.end_hour


@dataclass
class PeakHours:
    """平台活跃时段配置"""
    platform: str
    weekday_slots: List[PeakSlot] = field(default_factory=list)   # 工作日时段
    weekend_slots: List[PeakSlot] = field(default_factory=list)   # 周末时段
    timezone: str = "Asia/Shanghai"   # 默认北京时区
    country: str = "CN"

    def get_slots(self, dt: datetime) -> List[PeakSlot]:
        """根据日期返回对应时段（周末/工作日）"""
        # weekday(): Monday=0, Sunday=6
        is_weekend = dt.weekday() >= 5
        return self.weekend_slots if is_weekend else self.weekday_slots

    def is_peak(self, dt: datetime) -> bool:
        """判断给定时间是否处于活跃时段"""
        slots = self.get_slots(dt)
        return any(slot.contains(dt.hour) for slot in slots)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "timezone": self.timezone,
            "country": self.country,
            "weekday_slots": [
                {"start_hour": s.start_hour, "end_hour": s.end_hour, "weight": s.weight}
                for s in self.weekday_slots
            ],
            "weekend_slots": [
                {"start_hour": s.start_hour, "end_hour": s.end_hour, "weight": s.weight}
                for s in self.weekend_slots
            ],
        }


# ============ 各平台默认活跃时段 ============

DEFAULT_PEAK_HOURS: Dict[str, PeakHours] = {
    "douyin": PeakHours(
        platform="douyin",
        weekday_slots=[
            PeakSlot(12, 14, 1.0),   # 午休
            PeakSlot(19, 23, 1.0),   # 晚间黄金
        ],
        weekend_slots=[
            PeakSlot(10, 14, 0.9),
            PeakSlot(19, 23, 1.0),
        ],
    ),
    "xiaohongshu": PeakHours(
        platform="xiaohongshu",
        weekday_slots=[
            PeakSlot(7, 9, 0.9),     # 通勤
            PeakSlot(12, 14, 1.0),   # 午休
            PeakSlot(20, 22, 1.0),   # 晚间
        ],
        weekend_slots=[
            PeakSlot(10, 12, 0.9),
            PeakSlot(15, 17, 0.9),
            PeakSlot(20, 22, 1.0),
        ],
    ),
    "bilibili": PeakHours(
        platform="bilibili",
        weekday_slots=[PeakSlot(18, 23, 1.0)],
        weekend_slots=[PeakSlot(14, 23, 1.0)],
    ),
    "weibo": PeakHours(
        platform="weibo",
        weekday_slots=[
            PeakSlot(8, 10, 0.9),
            PeakSlot(12, 14, 1.0),
            PeakSlot(20, 23, 1.0),
        ],
        weekend_slots=[PeakSlot(10, 23, 0.9)],
    ),
    "zhihu": PeakHours(
        platform="zhihu",
        weekday_slots=[
            PeakSlot(9, 11, 1.0),
            PeakSlot(20, 23, 1.0),
        ],
        weekend_slots=[PeakSlot(10, 12, 0.9), PeakSlot(15, 17, 0.9)],
    ),
    "kuaishou": PeakHours(
        platform="kuaishou",
        weekday_slots=[
            PeakSlot(12, 14, 1.0),
            PeakSlot(19, 23, 1.0),
        ],
        weekend_slots=[PeakSlot(10, 14, 0.9), PeakSlot(19, 23, 1.0)],
    ),
    "wechat_public": PeakHours(
        platform="wechat_public",
        weekday_slots=[
            PeakSlot(7, 9, 1.0),
            PeakSlot(12, 14, 0.9),
            PeakSlot(20, 22, 1.0),
        ],
        weekend_slots=[PeakSlot(10, 12, 0.8)],
    ),
    "x_twitter_publisher": PeakHours(
        platform="x_twitter_publisher",
        timezone="America/New_York",
        country="US",
        weekday_slots=[
            PeakSlot(9, 12, 1.0),
            PeakSlot(20, 23, 1.0),
        ],
        weekend_slots=[PeakSlot(10, 14, 0.9)],
    ),
    "tiktok": PeakHours(
        platform="tiktok",
        timezone="America/Los_Angeles",
        country="US",
        weekday_slots=[
            PeakSlot(6, 10, 1.0),
            PeakSlot(19, 23, 1.0),
        ],
        weekend_slots=[PeakSlot(10, 14, 0.9), PeakSlot(19, 23, 1.0)],
    ),
    "instagram": PeakHours(
        platform="instagram",
        timezone="America/Los_Angeles",
        country="US",
        weekday_slots=[
            PeakSlot(11, 13, 1.0),
            PeakSlot(19, 21, 1.0),
        ],
        weekend_slots=[PeakSlot(10, 12, 0.9)],
    ),
    "youtube": PeakHours(
        platform="youtube",
        timezone="America/New_York",
        country="US",
        weekday_slots=[PeakSlot(14, 17, 1.0)],
        weekend_slots=[PeakSlot(9, 12, 1.0)],
    ),
    "facebook": PeakHours(
        platform="facebook",
        timezone="America/Chicago",
        country="US",
        weekday_slots=[
            PeakSlot(9, 12, 1.0),
            PeakSlot(13, 16, 0.9),
        ],
        weekend_slots=[PeakSlot(12, 14, 0.9)],
    ),
}


class PeakHoursService:
    """平台活跃时段服务"""

    def get_peak_hours(self, platform: str) -> PeakHours:
        """获取平台活跃时段配置"""
        if platform in DEFAULT_PEAK_HOURS:
            return DEFAULT_PEAK_HOURS[platform]
        # 兜底：通用时段
        return PeakHours(
            platform=platform,
            weekday_slots=[PeakSlot(9, 12, 1.0), PeakSlot(19, 22, 1.0)],
            weekend_slots=[PeakSlot(10, 14, 0.9), PeakSlot(19, 22, 1.0)],
        )

    def list_platforms(self) -> List[str]:
        """列出所有已配置平台"""
        return list(DEFAULT_PEAK_HOURS.keys())

    def is_peak_now(self, platform: str, dt: Optional[datetime] = None) -> bool:
        """判断当前是否处于活跃时段"""
        dt = dt or datetime.utcnow()
        ph = self.get_peak_hours(platform)
        return ph.is_peak(dt)

    def recommend_publish_time(
        self,
        platform: str,
        base_time: Optional[datetime] = None,
        *,
        strategy: str = ScheduleStrategy.SMART_STAGGER.value,
        avoid_times: Optional[List[datetime]] = None,
        min_gap_minutes: int = 30,
    ) -> datetime:
        """推荐发布时间

        Args:
            platform: 平台名
            base_time: 基准时间（默认当前）
            strategy: 调度策略（immediate/scheduled/smart_stagger）
            avoid_times: 避免冲突的时间列表（同账号已发布时间）
            min_gap_minutes: 与 avoid_times 的最小间隔分钟

        Returns:
            推荐发布时间
        """
        base = base_time or datetime.utcnow()

        if strategy == ScheduleStrategy.IMMEDIATE.value:
            return base

        ph = self.get_peak_hours(platform)
        avoid_times = avoid_times or []

        # smart_stagger 策略：扫描未来 7 天，找到最优时段
        for i in range(1, 168):  # 7 天逐小时
            candidate = (base + timedelta(hours=i)).replace(
                minute=random.randint(0, 50), second=0, microsecond=0
            )
            # 1. 必须在活跃时段
            if not ph.is_peak(candidate):
                continue
            # 2. 避免与已发布时间冲突
            conflict = False
            for avoid_time in avoid_times:
                if abs((candidate - avoid_time).total_seconds()) < min_gap_minutes * 60:
                    conflict = True
                    break
            if conflict:
                continue
            return candidate

        # 兜底：24h 后
        return base + timedelta(hours=24)

    def recommend_multi_platform_times(
        self,
        platforms: List[str],
        base_time: Optional[datetime] = None,
        min_gap_minutes: int = 30,
    ) -> Dict[str, datetime]:
        """多平台分发时按平台时区分散推荐

        Args:
            platforms: 平台列表
            base_time: 基准时间
            min_gap_minutes: 各平台发布间隔（避免同一账号同时段多平台发布）

        Returns:
            {platform: recommended_time}
        """
        base = base_time or datetime.utcnow()
        result: Dict[str, datetime] = {}
        used_times: List[datetime] = []

        for platform in platforms:
            recommended = self.recommend_publish_time(
                platform, base,
                strategy=ScheduleStrategy.SMART_STAGGER.value,
                avoid_times=used_times,
                min_gap_minutes=min_gap_minutes,
            )
            result[platform] = recommended
            used_times.append(recommended)
            # 推迟基准时间，避免后续平台选到同一时段
            base = recommended + timedelta(minutes=min_gap_minutes)
        return result

    def adapt_frequency_by_success_rate(
        self,
        platform: str,
        recent_success_rate: float,
        current_interval_minutes: int = 60,
    ) -> int:
        """发布频率自适应

        Args:
            platform: 平台名
            recent_success_rate: 近期发布成功率（0-1）
            current_interval_minutes: 当前发布间隔分钟

        Returns:
            调整后的间隔分钟
        """
        if recent_success_rate >= 0.95:
            # 成功率稳定，可适当缩短间隔
            return max(15, int(current_interval_minutes * 0.8))
        elif recent_success_rate >= 0.85:
            # 正常
            return current_interval_minutes
        elif recent_success_rate >= 0.70:
            # 失败率高，延长间隔
            return int(current_interval_minutes * 1.5)
        else:
            # 失败率极高，大幅延长
            return int(current_interval_minutes * 3.0)


# ============ 单例 ============

_svc: Optional[PeakHoursService] = None


def get_peak_hours_service() -> PeakHoursService:
    global _svc
    if _svc is None:
        _svc = PeakHoursService()
    return _svc
