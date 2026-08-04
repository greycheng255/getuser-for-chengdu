# -*- coding: utf-8 -*-
"""
营销信息植入 API 路由（第四阶段）

提供：
1. POST /api/marketing/materials - 添加营销素材
2. GET /api/marketing/materials - 列出素材
3. DELETE /api/marketing/materials/{material_id} - 删除素材
4. POST /api/marketing/video/watermark - 视频添加图片水印
5. POST /api/marketing/video/text-watermark - 视频添加文字水印
6. POST /api/marketing/video/qr-code - 视频添加二维码贴片
7. POST /api/marketing/copy/insert - AI 文案植入
8. POST /api/marketing/copy/auto-insert - 从素材库自动植入
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.marketing import (
    get_material_library,
    get_copy_inserter,
    VideoProcessor,
    MaterialType,
)
from ..services.marketing.material_library import MarketingMaterial

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/marketing", tags=["marketing"])


# ==================== Pydantic 模型 ====================


class MaterialRequest(BaseModel):
    name: str
    material_type: str = Field("slogan", description="logo/qr_code/link/slogan/event/contact")
    content: str = ""
    file_path: str = ""
    link_url: str = ""
    position: str = "bottom-right"
    is_active: bool = True


class WatermarkRequest(BaseModel):
    video_path: str
    logo_path: str
    output_path: str
    position: str = "bottom-right"
    scale: str = "iw*0.15"


class TextWatermarkRequest(BaseModel):
    video_path: str
    text: str
    output_path: str
    position: str = "bottom-right"
    font_size: int = 24
    font_color: str = "white"


class QRCodeRequest(BaseModel):
    video_path: str
    qr_image_path: str
    output_path: str
    position: str = "bottom-right"
    duration: float = 5.0


class CopyInsertRequest(BaseModel):
    content: str
    platform: str = ""
    slogans: List[str] = Field(default_factory=list)
    link: Optional[str] = None
    event_info: Optional[str] = None


class AutoCopyInsertRequest(BaseModel):
    content: str
    platform: str = ""


# ==================== 素材库 ====================


@router.post("/materials")
async def add_material(req: MaterialRequest):
    library = get_material_library()
    material = MarketingMaterial(
        name=req.name,
        material_type=req.material_type,
        content=req.content,
        file_path=req.file_path,
        link_url=req.link_url,
        position=req.position,
        is_active=req.is_active,
    )
    mid = await library.add(material)
    if mid is None:
        raise HTTPException(500, "添加素材失败")
    return {"success": True, "id": mid}


@router.get("/materials")
async def list_materials(
    material_type: str = Query("", description="按类型过滤"),
    only_active: bool = Query(True),
):
    library = get_material_library()
    materials = await library.list_materials(
        material_type=material_type, only_active=only_active
    )
    return {"materials": materials, "count": len(materials)}


@router.delete("/materials/{material_id}")
async def delete_material(material_id: int):
    library = get_material_library()
    ok = await library.delete(material_id)
    if not ok:
        raise HTTPException(400, "删除失败")
    return {"success": True}


# ==================== 视频后处理 ====================


@router.post("/video/watermark")
async def add_video_watermark(req: WatermarkRequest):
    processor = VideoProcessor()
    try:
        out = await processor.add_watermark(
            req.video_path, req.logo_path, req.output_path, req.position, req.scale
        )
        return {"success": True, "output_path": out}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/video/text-watermark")
async def add_text_watermark(req: TextWatermarkRequest):
    processor = VideoProcessor()
    try:
        out = await processor.add_text_watermark(
            req.video_path, req.text, req.output_path, req.position,
            req.font_size, req.font_color,
        )
        return {"success": True, "output_path": out}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/video/qr-code")
async def add_qr_code(req: QRCodeRequest):
    processor = VideoProcessor()
    try:
        out = await processor.add_qr_code(
            req.video_path, req.qr_image_path, req.output_path,
            req.position, req.duration,
        )
        return {"success": True, "output_path": out}
    except Exception as e:
        raise HTTPException(500, str(e))


# ==================== 文案植入 ====================


@router.post("/copy/insert")
async def insert_marketing_copy(req: CopyInsertRequest):
    inserter = get_copy_inserter()
    result = await inserter.insert_marketing(
        req.content, req.platform, req.slogans, req.link, req.event_info
    )
    return {"success": True, "content": result, "original": req.content}


@router.post("/copy/auto-insert")
async def auto_insert_copy(req: AutoCopyInsertRequest):
    inserter = get_copy_inserter()
    result = await inserter.auto_insert_from_library(req.content, req.platform)
    return {"success": True, "content": result, "original": req.content}
