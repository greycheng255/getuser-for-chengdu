# -*- coding: utf-8 -*-
"""
关键词研究 API 路由（P1：关键词研究）

提供：
1. POST /api/keyword/research - 关键词研究（主入口）
2. GET /api/keyword/suggestions - 关键词建议
3. GET /api/keyword/geo - GEO 高相关词
4. POST /api/keyword/groups - 创建关键词分组
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.keyword import get_keyword_research_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/keyword", tags=["keyword"])


class ResearchRequest(BaseModel):
    """关键词研究请求"""
    seed_keyword: str = Field(..., description="种子关键词")
    industry: str = Field(default="", description="行业")
    depth: int = Field(default=2, ge=1, le=5, description="挖掘深度")


class CreateGroupRequest(BaseModel):
    """创建关键词分组请求"""
    name: str
    description: str = ""
    keywords: list = []


@router.post("/research")
async def research_keywords(req: ResearchRequest):
    """关键词研究（主入口：挖掘 → 分析 → 推荐）"""
    svc = get_keyword_research_service()
    try:
        return await svc.research_keywords(req.seed_keyword, req.industry, req.depth)
    except Exception as e:
        logger.exception("关键词研究失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suggestions")
async def keyword_suggestions(
    q: str = Query(..., description="查询字符串"),
    limit: int = Query(10, ge=1, le=100),
):
    """关键词模糊查询建议"""
    svc = get_keyword_research_service()
    return await svc.get_keyword_suggestions(q, limit)


@router.get("/geo")
async def geo_keywords(
    industry: str = Query("", description="行业"),
    limit: int = Query(20, ge=1, le=200),
):
    """获取 GEO 高相关关键词"""
    svc = get_keyword_research_service()
    return await svc.get_geo_keywords(industry, limit)


@router.post("/groups")
async def create_keyword_group(req: CreateGroupRequest):
    """创建关键词分组"""
    svc = get_keyword_research_service()
    try:
        return await svc.create_keyword_group(req.name, req.description, req.keywords)
    except Exception as e:
        logger.exception("创建关键词分组失败")
        raise HTTPException(status_code=500, detail=str(e))
