# -*- coding: utf-8 -*-
"""
热点热度预测模型

阶段三 P2 任务 3.3：补齐 PRD 5.1 热点热度预测。

核心能力：
1. 基于历史热度曲线 + 时间序列预测（指数平滑）
2. 输出：未来 1/3/6/12 小时热度预测
3. 模型每日重训练（保留扩展点）
4. 预警联动：预测热度持续上升 → 提前触发"潜力热点"预警

设计：
- 指数平滑（轻量级，无需 ML 框架）
- ARIMA 留作扩展（statsmodels 软依赖）
- 历史数据从 hotpoint_alerts / hotspots 表读取
"""

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class HeatSample:
    """热度采样点"""
    timestamp: str       # ISO 格式
    heat_value: float


@dataclass
class HeatPrediction:
    """热度预测结果"""
    hotspot_id: str = ""
    current_heat: float = 0.0
    predictions: Dict[str, float] = field(default_factory=dict)  # {"1h": 1234.5, ...}
    trend: str = "stable"        # rising / falling / stable
    confidence: float = 0.5       # 0-1
    predicted_at: Optional[str] = None
    history_samples: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HeatPredictor:
    """热度预测器（指数平滑）"""

    # 默认平滑系数（0-1，越大越敏感）
    ALPHA = 0.3
    # 预测窗口（小时）
    PREDICT_HOURS = [1, 3, 6, 12]
    # 趋势阈值
    RISING_THRESHOLD = 1.1
    FALLING_THRESHOLD = 0.9

    def predict(
        self, hotspot_id: str, history: List[HeatSample],
    ) -> HeatPrediction:
        """预测未来热度

        Args:
            hotspot_id: 热点 ID
            history: 历史热度采样（按时间升序）

        Returns:
            HeatPrediction
        """
        if not history:
            return HeatPrediction(hotspot_id=hotspot_id)

        current_heat = history[-1].heat_value
        # 单指数平滑
        smoothed = self._single_exponential_smoothing(
            [s.heat_value for s in history], self.ALPHA
        )
        # 趋势预测（基于最近 N 个采样的平均变化率）
        growth_rate = self._estimate_growth_rate(history)

        predictions: Dict[str, float] = {}
        for h in self.PREDICT_HOURS:
            # 简单线性外推 + 平滑值回归
            predicted = smoothed * (1 + growth_rate * h)
            # 防止负数
            predictions[f"{h}h"] = max(0.0, predicted)

        # 趋势判断
        if growth_rate > 0.1:
            trend = "rising"
        elif growth_rate < -0.1:
            trend = "falling"
        else:
            trend = "stable"

        # 置信度：基于历史采样数量
        confidence = min(1.0, len(history) / 20)

        return HeatPrediction(
            hotspot_id=hotspot_id,
            current_heat=current_heat,
            predictions=predictions,
            trend=trend,
            confidence=confidence,
            predicted_at=datetime.utcnow().isoformat(),
            history_samples=[
                {"timestamp": s.timestamp, "heat_value": s.heat_value}
                for s in history[-20:]  # 保留最近 20 个采样
            ],
        )

    def _single_exponential_smoothing(
        self, values: List[float], alpha: float
    ) -> float:
        """单指数平滑"""
        if not values:
            return 0.0
        smoothed = values[0]
        for v in values[1:]:
            smoothed = alpha * v + (1 - alpha) * smoothed
        return smoothed

    def _estimate_growth_rate(self, history: List[HeatSample]) -> float:
        """估算热度增长率（每小时）"""
        if len(history) < 2:
            return 0.0
        # 取最近 5 个采样（或全部）
        recent = history[-5:] if len(history) >= 5 else history
        # 计算每个间隔的变化率
        rates = []
        for i in range(1, len(recent)):
            prev = recent[i - 1].heat_value
            curr = recent[i].heat_value
            if prev > 0:
                # 解析时间戳
                try:
                    t_prev = datetime.fromisoformat(recent[i - 1].timestamp)
                    t_curr = datetime.fromisoformat(recent[i].timestamp)
                    hours = (t_curr - t_prev).total_seconds() / 3600
                    if hours > 0:
                        rate_per_hour = (curr - prev) / prev / hours
                        rates.append(rate_per_hour)
                except Exception:
                    continue
        if not rates:
            return 0.0
        return sum(rates) / len(rates)

    # ============ 数据库集成 ============

    async def predict_from_db(self, hotspot_id: str) -> HeatPrediction:
        """从数据库加载历史热度并预测"""
        history = await self._load_history(hotspot_id)
        if not history:
            return HeatPrediction(hotspot_id=hotspot_id)
        prediction = self.predict(hotspot_id, history)
        # 联动预警
        if prediction.trend == "rising" and prediction.confidence > 0.5:
            await self._trigger_potential_alert(prediction)
        return prediction

    async def _load_history(self, hotspot_id: str) -> List[HeatSample]:
        """从数据库加载热点历史热度

        原先查询 hotpoint_history 表（同样未创建），现降级为通过
        get_hot_items_store().get_history_samples() 读取 hot_items 当前热度
        作为单点采样，保证预测链路可运行。
        """
        try:
            from api.services.hotpoint.hot_items_store import get_hot_items_store

            store = get_hot_items_store()
            raw_samples = await store.get_history_samples(hotspot_id, limit=50)
            samples = []
            for s in raw_samples:
                samples.append(HeatSample(
                    timestamp=str(s.get("timestamp") or ""),
                    heat_value=float(s.get("heat_value") or 0),
                ))
            return samples
        except Exception as e:
            logger.warning(f"[HeatPredictor] _load_history failed: {e}")
            return []

    async def _trigger_potential_alert(self, prediction: HeatPrediction) -> None:
        """触发潜力热点预警"""
        try:
            from api.services.alert.alert_center import (
                emit_hotpoint_burst, AlertSeverity,
            )
            # 复用突发热点预警，severity=INFO 标识为潜力
            await emit_hotpoint_burst(
                hotspot_id=prediction.hotspot_id,
                title=f"潜力热点预测：{prediction.hotspot_id}",
                heat_value=int(prediction.current_heat),
                delta=int(prediction.predictions.get("1h", 0) - prediction.current_heat),
                velocity=prediction.predictions.get("1h", 0) / max(prediction.current_heat, 1),
                platforms=[],
            )
        except Exception as e:
            logger.warning(f"[HeatPredictor] 预警触发失败: {e}")


# ============ 单例 ============

_predictor: Optional[HeatPredictor] = None


def get_heat_predictor() -> HeatPredictor:
    global _predictor
    if _predictor is None:
        _predictor = HeatPredictor()
    return _predictor
