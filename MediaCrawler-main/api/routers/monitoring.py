# -*- coding: utf-8 -*-
"""
效果监控 API 路由（P1：效果监控）

提供：
1. GET /api/monitoring/search-rank - 搜索排名查询
2. POST /api/monitoring/search-rank/check - 检查搜索排名
3. GET /api/monitoring/ai-citation - AI 引用记录
4. POST /api/monitoring/ai-citation/check - 检查 AI 引用
5. POST /api/monitoring/ai-citation/batch - 批量检测 AI 引用
6. GET /api/monitoring/ai-citation/keywords - 引用关键词列表
7. GET /api/monitoring/traffic - 流量统计
8. POST /api/monitoring/traffic - 记录流量数据
9. GET /api/monitoring/report - 生成综合报告
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.monitoring import get_monitoring_service
from ..services.monitoring.monitoring_service import TrafficRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


class CheckRankRequest(BaseModel):
    keyword: str
    search_engine: str = "baidu"
    brand_name: str = ""


class CheckCitationRequest(BaseModel):
    platform: str = "chatgpt"
    query: str
    brand_name: str = ""


class BatchCheckRequest(BaseModel):
    platforms: list = ["chatgpt"]
    brand_name: str = ""


class AddKeywordRequest(BaseModel):
    keyword: str
    brand_name: str = ""
    category: str = ""


class RecordTrafficRequest(BaseModel):
    source: str = ""
    medium: str = ""
    campaign: str = ""
    visitors: int = 0
    pageviews: int = 0
    bounce_rate: float = 0.0
    avg_duration: float = 0.0
    conversions: int = 0


@router.get("/search-rank")
async def get_search_rank(
    keyword: str = Query(...),
    search_engine: str = Query("baidu"),
    limit: int = Query(20, ge=1, le=100),
):
    """获取搜索排名历史"""
    svc = get_monitoring_service()
    return await svc.get_rank_history(keyword, search_engine, limit)


@router.post("/search-rank/check")
async def check_search_rank(req: CheckRankRequest):
    """检查搜索排名"""
    svc = get_monitoring_service()
    try:
        return await svc.check_search_rank(req.keyword, req.search_engine, req.brand_name)
    except Exception as e:
        logger.exception("搜索排名检查失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-citation")
async def get_ai_citation(
    platform: str = Query("chatgpt"),
    limit: int = Query(20, ge=1, le=100),
):
    """获取 AI 引用记录"""
    svc = get_monitoring_service()
    return await svc.get_citation_records(platform, limit)


@router.post("/ai-citation/check")
async def check_ai_citation(req: CheckCitationRequest):
    """检查 AI 引用"""
    svc = get_monitoring_service()
    try:
        return await svc.check_ai_citation(req.platform, req.query, req.brand_name)
    except Exception as e:
        logger.exception("AI 引用检查失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-citation/batch")
async def batch_check_citation(req: BatchCheckRequest):
    """批量检测 AI 引用"""
    svc = get_monitoring_service()
    try:
        # 注意：用关键字参数传入，避免 req.platforms 被当作 keywords（首个位置参数）
        return await svc.batch_check_citation(
            platforms=req.platforms, brand_name=req.brand_name
        )
    except Exception as e:
        logger.exception("批量 AI 引用检测失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-citation/keywords")
async def list_citation_keywords():
    """获取引用关键词列表"""
    svc = get_monitoring_service()
    return await svc.list_citation_keywords()


@router.post("/ai-citation/keywords")
async def add_citation_keyword(req: AddKeywordRequest):
    """添加引用关键词"""
    svc = get_monitoring_service()
    return await svc.add_citation_keyword(req.keyword, req.brand_name, req.category)


@router.get("/ai-citation/stats")
async def citation_stats():
    """获取 AI 引用统计"""
    svc = get_monitoring_service()
    return await svc.get_citation_stats()


@router.get("/traffic")
async def get_traffic_summary(days: int = Query(7, ge=1, le=365)):
    """获取流量统计"""
    svc = get_monitoring_service()
    return await svc.get_traffic_summary(days)


@router.post("/traffic")
async def record_traffic(req: RecordTrafficRequest):
    """记录流量数据"""
    svc = get_monitoring_service()
    from datetime import datetime
    record = TrafficRecord(
        source=req.source,
        medium=req.medium,
        campaign=req.campaign,
        visitors=req.visitors,
        pageviews=req.pageviews,
        bounce_rate=req.bounce_rate,
        avg_duration=req.avg_duration,
        conversions=req.conversions,
        recorded_at=datetime.now(),
    )
    await svc.record_traffic(record)
    return {"success": True, "message": "流量数据已记录"}


@router.get("/report")
async def generate_report(brand_name: str = Query(""), days: int = Query(7, ge=1, le=90)):
    """生成综合监控报告"""
    svc = get_monitoring_service()
    try:
        return await svc.generate_report(brand_name, days)
    except Exception as e:
        logger.exception("监控报告生成失败")
        raise HTTPException(status_code=500, detail=str(e))
