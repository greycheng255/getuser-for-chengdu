# -*- coding: utf-8 -*-
"""
AI 服务 API 路由（P0：AI 能力扩展）

提供：
1. POST /api/ai/generate - AI 内容生成
2. POST /api/ai/geo-article - GEO 优化文章生成
3. POST /api/ai/geo-plan - GEO 优化方案生成
4. GET /api/ai/platforms - 获取可用 AI 平台列表
5. POST /api/ai/platforms/generate - 指定平台生成
6. POST /api/ai/platforms/fallback - 多平台故障转移生成
7. POST /api/ai/image/generate - 图像生成
8. POST /api/ai/image/xhs-cover - 小红书封面生成
9. POST /api/ai/image/xhs-images - 小红书配图批量生成
10. GET/POST/DELETE /api/ai/tasks - AI 任务管理
11. POST /api/ai/citation/run - 立即执行 AI 引用检测
12. GET /api/ai/citation/status - 引用调度器状态
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.ai import (
    get_ai_citation_scheduler,
    get_ai_platform_service,
    get_ai_service,
    get_ai_task_service,
    get_image_generation_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


# ============ AI 内容生成 ============

class GenerateRequest(BaseModel):
    prompt: str
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000
    model: str = ""


class GeoArticleRequest(BaseModel):
    topic: str
    brand_name: str = ""
    industry: str = ""
    keywords: list = []
    target_audience: str = ""
    word_count: int = 1500


class GeoPlanRequest(BaseModel):
    domain: str = ""
    brand_name: str
    industry: str
    keywords: list = []
    location: str = ""


@router.post("/generate")
async def generate_content(req: GenerateRequest):
    """AI 内容生成"""
    svc = get_ai_service()
    try:
        return await svc.generate_content(
            req.prompt, req.system_prompt, req.temperature, req.max_tokens, req.model
        )
    except Exception as e:
        logger.exception("AI 内容生成失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/geo-article")
async def generate_geo_article(req: GeoArticleRequest):
    """GEO 优化文章生成"""
    svc = get_ai_service()
    try:
        # service 签名为 generate_geo_article(title, brand_info: Dict, keywords, target_platform, word_count)
        # 将 brand_name/industry/target_audience 组装为 brand_info Dict，避免位置参数错位
        return await svc.generate_geo_article(
            title=req.topic,
            brand_info={
                "name": req.brand_name,
                "industry": req.industry,
                "audience": req.target_audience,
            },
            keywords=req.keywords,
            word_count=req.word_count,
        )
    except Exception as e:
        logger.exception("GEO 文章生成失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/geo-plan")
async def generate_geo_plan(req: GeoPlanRequest):
    """GEO 优化方案生成"""
    svc = get_ai_service()
    try:
        return await svc.generate_geo_plan(
            req.domain, req.brand_name, req.industry, req.keywords, req.location
        )
    except Exception as e:
        logger.exception("GEO 方案生成失败")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 多 AI 平台 ============

@router.get("/platforms")
async def list_platforms():
    """获取可用 AI 平台列表"""
    svc = get_ai_platform_service()
    return svc.get_available_platforms()


class PlatformGenerateRequest(BaseModel):
    platform: str
    prompt: str
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000


@router.post("/platforms/generate")
async def generate_with_platform(req: PlatformGenerateRequest):
    """指定平台生成"""
    svc = get_ai_platform_service()
    try:
        return await svc.generate_with_platform(
            req.platform, req.prompt, req.system_prompt, req.temperature, req.max_tokens
        )
    except Exception as e:
        logger.exception("平台生成失败")
        raise HTTPException(status_code=500, detail=str(e))


class FallbackGenerateRequest(BaseModel):
    prompt: str
    platforms: list = []
    system_prompt: str = ""


@router.post("/platforms/fallback")
async def generate_with_fallback(req: FallbackGenerateRequest):
    """多平台故障转移生成"""
    svc = get_ai_platform_service()
    try:
        return await svc.generate_with_fallback(req.prompt, req.platforms, req.system_prompt)
    except Exception as e:
        logger.exception("故障转移生成失败")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 图像生成 ============

class ImageGenerateRequest(BaseModel):
    prompt: str
    size: str = "1024x1024"
    quality: str = "standard"


class XhsCoverRequest(BaseModel):
    title: str
    content: str = ""
    keywords: list = []
    brand_name: str = ""


class XhsImagesRequest(BaseModel):
    title: str
    content: str = ""
    keywords: list = []
    count: int = 3
    brand_name: str = ""


@router.post("/image/generate")
async def generate_image(req: ImageGenerateRequest):
    """图像生成（多模型重试链）"""
    svc = get_image_generation_service()
    try:
        result = await svc.generate_image(req.prompt, req.size, req.quality)
        if not result:
            return {"success": False, "error": "所有图像生成模型均失败"}
        return {"success": True, "image": result}
    except Exception as e:
        logger.exception("图像生成失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/image/xhs-cover")
async def generate_xhs_cover(req: XhsCoverRequest):
    """小红书封面生成"""
    svc = get_image_generation_service()
    try:
        result = await svc.generate_xiaohongshu_cover(
            req.title, req.content, req.keywords, req.brand_name
        )
        return {"success": bool(result), "image": result}
    except Exception as e:
        logger.exception("小红书封面生成失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/image/xhs-images")
async def generate_xhs_images(req: XhsImagesRequest):
    """小红书配图批量生成"""
    svc = get_image_generation_service()
    try:
        result = await svc.generate_xiaohongshu_images(
            req.title, req.content, req.keywords, req.count, req.brand_name
        )
        return {"success": bool(result), "images": result or []}
    except Exception as e:
        logger.exception("小红书配图生成失败")
        raise HTTPException(status_code=500, detail=str(e))


# ============ AI 任务管理 ============

class CreateTaskRequest(BaseModel):
    task_type: str
    title: str
    description: str = ""
    input_data: dict = {}
    user_id: int = 1
    plan_id: int = None


@router.post("/tasks")
async def create_task(req: CreateTaskRequest):
    """创建 AI 任务"""
    svc = get_ai_task_service()
    try:
        return await svc.create_task(req.dict())
    except Exception as e:
        logger.exception("创建 AI 任务失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def list_tasks(
    user_id: int = Query(0, description="用户 ID（0 表示全部）"),
    status: str = Query("", description="状态筛选"),
    limit: int = Query(20, ge=1, le=100),
):
    """获取 AI 任务列表"""
    svc = get_ai_task_service()
    return await svc.get_tasks(user_id=user_id, status=status, limit=limit)


@router.get("/tasks/{task_id}")
async def get_task(task_id: int):
    """获取 AI 任务详情"""
    svc = get_ai_task_service()
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    """删除 AI 任务"""
    svc = get_ai_task_service()
    return await svc.delete_task(task_id)


# ============ AI 引用调度 ============

@router.post("/citation/run")
async def run_citation_check():
    """立即执行一次 AI 引用检测"""
    svc = get_ai_citation_scheduler()
    try:
        return await svc.run_now()
    except Exception as e:
        logger.exception("AI 引用检测失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/citation/status")
async def citation_status():
    """获取 AI 引用调度器状态"""
    svc = get_ai_citation_scheduler()
    return {
        "running": svc.is_running(),
    }
