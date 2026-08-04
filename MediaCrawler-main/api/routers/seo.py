# -*- coding: utf-8 -*-
"""
SEO 品牌推广 API 路由

端点：
  POST   /brands              创建品牌
  GET    /brands              列出品牌
  POST   /brands/{brand_id}/articles/generate  AI 生成文章
  POST   /articles/{article_id}/publish/{platform}  发布文章
  GET    /articles            列出文章
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user
from ..services.seo.seo_service import get_seo_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/seo", tags=["seo"])


class CreateBrandRequest(BaseModel):
    brand_name: str = Field(..., description="品牌名称")
    company_name: str = Field("", description="公司名称")
    logo_url: str = Field("", description="Logo URL")
    industry: str = Field("", description="所属行业")
    brand_intro: str = Field("", description="品牌简介")
    advantages: Optional[List[str]] = Field(None, description="品牌优势列表")


class GenerateArticleRequest(BaseModel):
    topic: str = Field(..., description="文章主题")
    target_platforms: Optional[List[str]] = Field(None, description="目标投放平台")


@router.post("/brands")
async def create_brand(
    req: CreateBrandRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建品牌"""
    svc = get_seo_service()
    result = await svc.create_brand(
        brand_name=req.brand_name,
        company_name=req.company_name,
        logo_url=req.logo_url,
        industry=req.industry,
        brand_intro=req.brand_intro,
        advantages=req.advantages,
        owner_user_id=str(current_user["id"]),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "创建失败"))
    return result


@router.get("/brands")
async def list_brands(current_user: dict = Depends(get_current_user)):
    """列出品牌"""
    svc = get_seo_service()
    brands = await svc.list_brands(owner_user_id=str(current_user["id"]))
    return {"brands": brands, "total": len(brands)}


@router.post("/brands/{brand_id}/articles/generate")
async def generate_article(
    brand_id: str,
    req: GenerateArticleRequest,
    current_user: dict = Depends(get_current_user),
):
    """AI 生成 SEO 文章"""
    svc = get_seo_service()
    result = await svc.generate_article(
        brand_id=brand_id,
        topic=req.topic,
        target_platforms=req.target_platforms,
        owner_user_id=str(current_user["id"]),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "生成失败"))
    return result


@router.post("/articles/{article_id}/publish/{platform}")
async def publish_article(
    article_id: str,
    platform: str,
    current_user: dict = Depends(get_current_user),
):
    """发布文章到指定平台"""
    svc = get_seo_service()
    result = await svc.publish_article(article_id, platform)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "发布失败"))
    return result


@router.get("/articles")
async def list_articles(
    brand_id: Optional[str] = Query(None),
    status: str = Query("draft"),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """列出文章"""
    svc = get_seo_service()
    articles = await svc.list_articles(brand_id=brand_id, status=status, limit=limit)
    return {"articles": articles, "total": len(articles)}
