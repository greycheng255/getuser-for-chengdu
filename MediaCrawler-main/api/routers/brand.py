# -*- coding: utf-8 -*-
"""
品牌诊断 API 路由（P1：品牌诊断）

提供：
1. POST /api/brand/diagnosis - 执行品牌诊断
2. GET /api/brand/reports - 获取诊断报告历史
3. GET /api/brand/reports/{report_id} - 获取指定报告
4. GET /api/brand/score-trend - 获取品牌评分趋势
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.brand import get_brand_diagnosis_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/brand", tags=["brand"])


class DiagnosisRequest(BaseModel):
    """品牌诊断请求"""
    brand_name: str = Field(..., description="品牌名称")
    website: str = Field(default="", description="品牌官网")
    industry: str = Field(default="", description="行业")


@router.post("/diagnosis")
async def run_diagnosis(req: DiagnosisRequest):
    """执行品牌诊断（AI 可见度 + 搜索排名 + 内容质量 + 舆情 + 竞争）"""
    svc = get_brand_diagnosis_service()
    try:
        return await svc.run_full_diagnosis(req.brand_name, req.website, req.industry)
    except Exception as e:
        logger.exception("品牌诊断失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports")
async def list_reports(
    brand_name: str = Query("", description="品牌名称筛选"),
    limit: int = Query(20, ge=1, le=100),
):
    """获取诊断报告历史"""
    svc = get_brand_diagnosis_service()
    return await svc.get_report_history(brand_name=brand_name, limit=limit)


@router.get("/score-trend")
async def score_trend(
    brand_name: str = Query(..., description="品牌名称"),
    days: int = Query(30, ge=1, le=365),
):
    """获取品牌评分趋势"""
    svc = get_brand_diagnosis_service()
    return await svc.get_score_trend(brand_name=brand_name, days=days)
