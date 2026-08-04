# -*- coding: utf-8 -*-
"""
内容风控 API 路由（第三阶段）

提供：
1. POST /api/moderation/check - 发布前内容审核（违规词 + 查重）
2. GET /api/moderation/logs - 审核日志查询
3. GET /api/moderation/sentiment/stats - 舆情统计
4. GET /api/moderation/sentiment/alerts - 舆情预警列表
5. POST /api/moderation/sentiment/alerts/{alert_id}/resolve - 解决预警
6. POST /api/moderation/sentiment/items - 记录舆情条目
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.moderation import (
    get_moderation_service,
    get_sentiment_monitor,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/moderation", tags=["moderation"])


# ==================== Pydantic 模型 ====================


class ModerationCheckRequest(BaseModel):
    content: str = Field(..., description="待审核内容")
    platform: str = Field("", description="目标平台")
    enable_dedup: bool = Field(True, description="是否启用查重")
    strict: bool = Field(False, description="严格模式")


class SentimentItemRequest(BaseModel):
    platform: str
    brand_name: str
    content: str
    url: str = ""
    author: str = ""


# ==================== 内容审核 ====================


@router.post("/check")
async def check_content(req: ModerationCheckRequest):
    """发布前内容审核"""
    svc = get_moderation_service()
    result = await svc.moderate(
        req.content, req.platform, enable_dedup=req.enable_dedup, strict=req.strict
    )
    return result.to_dict()


@router.get("/logs")
async def list_moderation_logs(
    platform: str = Query("", description="按平台过滤"),
    limit: int = Query(50, ge=1, le=200),
):
    """审核日志查询"""
    svc = get_moderation_service()
    logs = await svc.list_logs(platform=platform, limit=limit)
    return {"logs": logs, "count": len(logs)}


# ==================== 舆情监控 ====================


@router.get("/sentiment/stats")
async def sentiment_stats(
    brand_name: str = Query(..., description="品牌名"),
    days: int = Query(7, ge=1, le=90),
):
    """舆情统计"""
    svc = get_sentiment_monitor()
    stats = await svc.get_stats(brand_name, days=days)
    return stats


@router.get("/sentiment/alerts")
async def sentiment_alerts(
    brand_name: str = Query("", description="品牌名（空则全部）"),
    only_unresolved: bool = Query(True),
):
    """舆情预警列表"""
    svc = get_sentiment_monitor()
    alerts = await svc.list_alerts(brand_name=brand_name, only_unresolved=only_unresolved)
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/sentiment/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    """解决预警"""
    svc = get_sentiment_monitor()
    ok = await svc.resolve_alert(alert_id)
    if not ok:
        raise HTTPException(400, "解决预警失败")
    return {"success": True, "message": "预警已标记为解决"}


@router.post("/sentiment/items")
async def record_sentiment_item(req: SentimentItemRequest):
    """记录舆情条目"""
    svc = get_sentiment_monitor()
    sentiment, score, keywords = svc.classify_sentiment(req.content)
    from ..services.moderation.sentiment_monitor import SentimentItem

    item = SentimentItem(
        platform=req.platform,
        brand_name=req.brand_name,
        content=req.content,
        url=req.url,
        sentiment=sentiment,
        sentiment_score=score,
        keywords=keywords,
        author=req.author,
    )
    item_id = await svc.record_item(item)
    return {
        "success": item_id is not None,
        "id": item_id,
        "sentiment": sentiment,
        "score": score,
        "keywords": keywords,
    }


# ==================== 涉政检测（任务 2.3） ====================


class PoliticalCheckRequest(BaseModel):
    content: str = Field(..., description="待检测内容")


@router.post("/political/check")
async def check_political(req: PoliticalCheckRequest):
    """涉政内容检测"""
    from ..services.moderation.political_detector import get_political_detector
    detector = get_political_detector()
    result = await detector.detect_async(req.content)
    return result.to_dict()


# ==================== 侵权检测（任务 2.3） ====================


class CopyrightCheckRequest(BaseModel):
    media_path: str = Field(..., description="媒体文件路径")
    media_type: str = Field("image", description="媒体类型: image/video/audio")
    owner_user_id: Optional[int] = Field(None, description="用户 ID")


@router.post("/copyright/check")
async def check_copyright(req: CopyrightCheckRequest):
    """侵权内容检测"""
    from ..services.moderation.copyright_detector import get_copyright_detector
    detector = get_copyright_detector()
    if req.media_type == "image":
        result = await detector.detect_image(req.media_path, req.owner_user_id)
    elif req.media_type == "video":
        result = await detector.detect_video(req.media_path, req.owner_user_id)
    elif req.media_type == "audio":
        result = await detector.detect_audio(req.media_path, req.owner_user_id)
    else:
        return {"code": 4000, "message": "media_type 必须为 image/video/audio"}
    return result.to_dict()


class CopyrightLibraryAddRequest(BaseModel):
    media_type: str = Field(..., description="image/video/audio")
    source: str = Field(..., description="版权来源")
    phash: str = Field(..., description="媒体 pHash")
    metadata: dict = Field(default_factory=dict)


@router.post("/copyright/library")
async def add_to_copyright_library(req: CopyrightLibraryAddRequest):
    """添加到版权库"""
    from ..services.moderation.copyright_detector import get_copyright_detector
    detector = get_copyright_detector()
    ok = await detector.add_to_library(
        media_type=req.media_type, source=req.source,
        phash=req.phash, metadata=req.metadata,
    )
    return {"code": 0 if ok else 5000, "message": "OK" if ok else "添加失败"}


# ==================== 合规归档（任务 2.3） ====================


@router.get("/archive")
async def list_archive(
    archive_type: Optional[str] = None,
    platform: Optional[str] = None,
    owner_user_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """查询合规归档记录"""
    from ..services.moderation.compliance_archive import (
        get_compliance_archive_service,
    )
    svc = get_compliance_archive_service()
    records = await svc.list_records(
        archive_type=archive_type, platform=platform,
        owner_user_id=owner_user_id, start_date=start_date, end_date=end_date,
        limit=limit, offset=offset,
    )
    return {"code": 0, "data": records}


@router.get("/archive/{archive_id}")
async def get_archive(archive_id: str):
    """查询单条归档记录"""
    from ..services.moderation.compliance_archive import (
        get_compliance_archive_service,
    )
    svc = get_compliance_archive_service()
    record = await svc.get_record(archive_id)
    if not record:
        return {"code": 4040, "message": "记录不存在"}
    return {"code": 0, "data": record}


@router.post("/archive/migrate-cold")
async def migrate_cold_storage():
    """手动触发冷存储迁移"""
    from ..services.moderation.compliance_archive import (
        get_compliance_archive_service,
    )
    svc = get_compliance_archive_service()
    count = await svc.migrate_cold_storage()
    return {"code": 0, "data": {"migrated_count": count}}


@router.post("/archive/purge-expired")
async def purge_expired_archive():
    """清理超过 1 年的归档"""
    from ..services.moderation.compliance_archive import (
        get_compliance_archive_service,
    )
    svc = get_compliance_archive_service()
    count = await svc.purge_expired()
    return {"code": 0, "data": {"purged_count": count}}
