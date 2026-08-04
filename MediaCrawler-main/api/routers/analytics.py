# -*- coding: utf-8 -*-
"""
数据统计 API 路由（第五阶段）

提供：
1. GET /api/analytics/dashboard - 仪表盘汇总
2. GET /api/analytics/platform-comparison - 平台对比
3. GET /api/analytics/content-performance - 内容表现
4. GET /api/analytics/export/dashboard - 导出仪表盘报表
5. GET /api/analytics/export/platform-comparison - 导出平台对比
6. GET /api/analytics/export/content-performance - 导出内容表现
7. GET /api/analytics/external-metrics - 外部平台数据采集
8. POST /api/analytics/external-metrics/collect - 触发外部数据采集
9. POST /api/analytics/funnel - 转化漏斗分析
10. POST /api/analytics/funnel/event - 记录漏斗事件
11. GET /api/analytics/viral-reviews - 爆款复盘报告列表
12. GET /api/analytics/viral-reviews/{report_id} - 爆款复盘报告详情
13. POST /api/analytics/viral-reviews - 生成爆款复盘报告
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.analytics import get_analytics_service, get_export_service
from ..services.analytics.external_metrics import (
    ExternalMetric,
    get_external_metrics_collector,
)
from ..services.analytics.viral_review import (
    ViralContent,
    ViralDetector,
    ViralReviewService,
    get_viral_detector,
    get_viral_review_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/dashboard")
async def dashboard(days: int = Query(7, ge=1, le=90)):
    """仪表盘汇总数据"""
    svc = get_analytics_service()
    return await svc.get_dashboard(days=days)


# ============ 阶段三 P2-8: 高级趋势分析 + 异常检测 ============


@router.get("/trends/advanced")
async def advanced_trends(days: int = Query(30, ge=1, le=90)):
    """高级趋势分析(含 7 日移动平均 / 环比 / 同比 / 异常点)

    返回字段:
    - trends: 每日数据点,含 moving_avg_7d / mom_ratio / yoy_ratio
    - summary: 最近 7 天 vs 上一个 7 天的汇总
    - anomalies: mom_ratio 异常点(下降>50% 或 上升>200%)
    """
    svc = get_analytics_service()
    return await svc.get_advanced_trends(days=days)


@router.get("/anomalies/check")
async def check_anomalies(days: int = Query(7, ge=1, le=30)):
    """触发一次数据异常检测

    对比最近 N 天与上一个 N 天的核心指标(publish_count / interaction_count /
    followers_delta),如果某指标环比下降超过 30%,触发 alert_center 预警。
    返回检测到的异常列表。
    """
    svc = get_analytics_service()
    anomalies = await svc.detect_data_anomaly(days=days)
    return {
        "code": 0,
        "data": {
            "anomalies": anomalies,
            "total": len(anomalies),
            "days": days,
            "checked_at": datetime.utcnow().isoformat(),
        },
    }


@router.get("/platform-comparison")
async def platform_comparison(days: int = Query(30, ge=1, le=365)):
    """平台对比分析"""
    svc = get_analytics_service()
    return await svc.get_platform_comparison(days=days)


@router.get("/content-performance")
async def content_performance(limit: int = Query(20, ge=1, le=200)):
    """内容表现排行"""
    svc = get_analytics_service()
    return await svc.get_content_performance(limit=limit)


@router.get("/export/dashboard")
async def export_dashboard(days: int = Query(7, ge=1, le=90)):
    """导出仪表盘报表（CSV）"""
    svc = get_export_service()
    content = await svc.export_dashboard_csv(days=days)
    filename = f"dashboard_{days}d.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export/platform-comparison")
async def export_platform_comparison(days: int = Query(30, ge=1, le=365)):
    """导出平台对比报表（CSV）"""
    svc = get_export_service()
    content = await svc.export_platform_comparison_csv(days=days)
    filename = f"platform_comparison_{days}d.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export/content-performance")
async def export_content_performance(limit: int = Query(100, ge=1, le=500)):
    """导出内容表现报表（CSV）"""
    svc = get_export_service()
    content = await svc.export_content_performance_csv(limit=limit)
    filename = f"content_performance.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ============ 阶段三 P2 任务 3.1：外部平台数据采集 ============


class CollectRequest(BaseModel):
    """外部数据采集请求"""
    accounts: List[Dict[str, str]] = Field(
        ..., description='[{"platform": "youtube", "account_id": "xxx"}, ...]'
    )


class FunnelEventRequest(BaseModel):
    """转化漏斗事件"""
    platform: str
    account_id: str
    event_type: str = Field(..., description="impression / click / visit / conversion")
    target_url: str = ""
    owner_user_id: Optional[int] = None


class FunnelAnalysisRequest(BaseModel):
    """转化漏斗分析请求"""
    platform: str
    days: int = 7


@router.get("/external-metrics")
async def list_external_metrics(
    platform: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
):
    """查询外部平台数据"""
    collector = get_external_metrics_collector()
    items = await collector.list_metrics(platform=platform, days=days, limit=limit)
    return {"code": 0, "data": {"items": items, "total": len(items)}}


@router.post("/external-metrics/collect")
async def collect_external_metrics(req: CollectRequest):
    """触发外部数据采集"""
    collector = get_external_metrics_collector()
    count = await collector.collect_all(req.accounts)
    return {"code": 0, "data": {"collected_count": count}}


@router.post("/external-metrics/utm-url")
async def build_utm_url(
    base_url: str = Query(...),
    source: str = Query(...),
    medium: str = Query("social"),
    campaign: str = Query(""),
    content: str = Query(""),
    term: str = Query(""),
):
    """构建 UTM 追踪 URL"""
    collector = get_external_metrics_collector()
    url = collector.build_utm_url(base_url, source, medium, campaign, content, term)
    return {"code": 0, "data": {"url": url}}


@router.post("/funnel/event")
async def record_funnel_event(req: FunnelEventRequest):
    """记录转化漏斗事件"""
    collector = get_external_metrics_collector()
    ok = await collector.record_funnel_event(
        platform=req.platform,
        account_id=req.account_id,
        event_type=req.event_type,
        target_url=req.target_url,
        owner_user_id=req.owner_user_id,
    )
    return {"code": 0 if ok else 5000, "data": {"success": ok}}


@router.post("/funnel")
async def funnel_analysis(req: FunnelAnalysisRequest):
    """转化漏斗分析"""
    collector = get_external_metrics_collector()
    data = await collector.get_funnel_analysis(req.platform, days=req.days)
    return {"code": 0, "data": data}


# ============ 阶段三 P2 任务 3.2：爆款内容复盘 ============


class ViralContentRequest(BaseModel):
    """爆款内容请求"""
    content_id: str = ""
    platform: str = ""
    post_url: str = ""
    title: str = ""
    published_at: Optional[str] = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    collects: int = 0
    interaction_rate: float = 0.0
    growth_velocity: float = 0.0
    hotspot_source: str = ""
    use_ai: bool = True


@router.get("/viral-reviews")
async def list_viral_reviews(
    platform: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
):
    """爆款复盘报告列表"""
    svc = get_viral_review_service()
    items = await svc.list_reports(platform=platform, days=days, limit=limit)
    return {"code": 0, "data": {"items": items, "total": len(items)}}


@router.get("/viral-reviews/{report_id}")
async def get_viral_review(report_id: str):
    """爆款复盘报告详情"""
    svc = get_viral_review_service()
    report = await svc.get_report(report_id)
    if not report:
        return {"code": 4040, "message": "报告不存在"}
    return {"code": 0, "data": report}


@router.post("/viral-reviews")
async def create_viral_review(req: ViralContentRequest):
    """生成爆款复盘报告"""
    content = ViralContent(
        content_id=req.content_id,
        platform=req.platform,
        post_url=req.post_url,
        title=req.title,
        published_at=req.published_at,
        views=req.views,
        likes=req.likes,
        comments=req.comments,
        shares=req.shares,
        collects=req.collects,
        interaction_rate=req.interaction_rate,
        growth_velocity=req.growth_velocity,
    )
    # 先识别是否为爆款
    detector = get_viral_detector()
    content = detector.detect(content)
    # 生成复盘报告
    svc = get_viral_review_service()
    report = await svc.generate_review(
        content, hotspot_source=req.hotspot_source, use_ai=req.use_ai,
    )
    return {"code": 0, "data": report.to_dict()}


@router.post("/viral-reviews/detect")
async def detect_viral(req: ViralContentRequest):
    """仅识别是否为爆款（不生成报告）"""
    content = ViralContent(
        content_id=req.content_id,
        platform=req.platform,
        post_url=req.post_url,
        title=req.title,
        views=req.views,
        likes=req.likes,
        comments=req.comments,
        shares=req.shares,
        collects=req.collects,
        interaction_rate=req.interaction_rate,
        growth_velocity=req.growth_velocity,
    )
    detector = get_viral_detector()
    content = detector.detect(content)
    return {"code": 0, "data": content.to_dict()}
