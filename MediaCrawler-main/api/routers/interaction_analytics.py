# -*- coding: utf-8 -*-
"""
互动数据精细化分析 API 路由（任务 P1-5）

暴露 InteractionAnalyticsService 的核心查询能力：
1. GET /api/interact/analytics/aggregate  - 互动统计聚合
2. GET /api/interact/analytics/trend      - 互动趋势（按天）
3. GET /api/interact/analytics/anomalies  - 异常互动识别

挂在 interact 路由组下，统一前缀 /api/interact/analytics。
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from ..services.analytics.interaction_analytics import (
    get_interaction_analytics,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interact/analytics", tags=["interact-analytics"])


@router.get("/aggregate")
async def aggregate(
    platform: Optional[str] = Query(None, description="平台过滤"),
    account_id: Optional[int] = Query(None, description="账号 ID 过滤"),
    target_id: Optional[str] = Query(None, description="目标内容 ID 过滤"),
    start_date: Optional[str] = Query(
        None, description="开始日期 YYYY-MM-DD（ISO 字符串也可）"
    ),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    dimension: str = Query(
        "platform", description="分组维度: platform / account / target / type"
    ),
):
    """互动统计聚合（按维度分组）"""
    svc = get_interaction_analytics()
    start_dt = _parse_dt(start_date)
    end_dt = _parse_dt(end_date)
    stats = await svc.aggregate(
        platform=platform,
        account_id=account_id,
        target_id=target_id,
        start=start_dt,
        end=end_dt,
        group_by=dimension,
    )
    return {"code": 0, "data": [s.to_dict() for s in stats]}


@router.get("/trend")
async def trend(
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
    platform: Optional[str] = Query(None, description="平台过滤"),
    account_id: Optional[int] = Query(None, description="账号 ID 过滤"),
):
    """按天返回互动数趋势"""
    svc = get_interaction_analytics()
    data = await svc.trend(
        platform=platform,
        account_id=account_id,
        days=days,
    )
    return {"code": 0, "data": data}


@router.get("/anomalies")
async def anomalies(
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    platform: Optional[str] = Query(None, description="平台过滤"),
    account_id: Optional[int] = Query(None, description="账号 ID 过滤"),
    max_interval_seconds: int = Query(5, ge=1, description="too_fast 阈值（秒）"),
):
    """识别异常互动（too_fast / off_hours / duplicate_content / abnormal_volume）

    detect_anomalies 当前以 since 为查询起点，这里把 start_date 转换为 since。
    end_date 暂作为返回元信息，方便前端展示。
    """
    svc = get_interaction_analytics()
    since_dt = _parse_dt(start_date)
    items = await svc.detect_anomalies(
        platform=platform,
        account_id=account_id,
        since=since_dt,
        max_interval_seconds=max_interval_seconds,
    )
    return {
        "code": 0,
        "data": [a.to_dict() for a in items],
        "query": {
            "start_date": start_date,
            "end_date": end_date,
            "platform": platform,
            "account_id": account_id,
        },
    }


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """宽松解析日期字符串：支持 YYYY-MM-DD 与 ISO datetime。"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # 最后尝试 ISO 解析
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None
