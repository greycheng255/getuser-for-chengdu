# -*- coding: utf-8 -*-
"""
多平台发布 API 路由

提供：
1. POST /api/publish/multi-platform - 多平台并行发布
2. POST /api/publish/single/{platform} - 单平台发布
3. GET /api/publish/platforms - 列出所有支持的平台
4. GET /api/publish/accounts - 账号池状态
5. POST /api/publish/accounts - 添加账号
6. DELETE /api/publish/accounts/{account_id} - 删除账号
7. POST /api/publish/accounts/{account_id}/reset-cooldown - 重置冷却
8. POST /api/publish/moderate - 内容风控预检测
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from api.services.account_feature_flags import legacy_account_api_enabled
from pydantic import BaseModel, Field

from ..services.publisher import (
    BasePublisher,
    MultiPlatformPublisher,
    PlatformAccountService,
    PublisherFactory,
    PublishResult,
    PublishStatus,
    PublishTask,
    get_account_service,
    get_multi_publisher,
)
from ..services.publisher.content_adapter import adapt_for_platform, moderate_content
from ..services.publisher.platform_configs import (
    PLATFORM_METADATA,
    get_platform_meta,
    list_supported_platforms,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publish", tags=["publish"])


# ==================== Pydantic 请求/响应模型 ====================


class MultiPublishRequest(BaseModel):
    """多平台发布请求"""

    title: str = Field(..., description="标题")
    content: str = Field(..., description="正文")
    keywords: List[str] = Field(default_factory=list, description="话题关键词")
    images: List[str] = Field(default_factory=list, description="本地图片路径列表")
    video_path: Optional[str] = Field(None, description="视频文件路径")
    target_platforms: List[str] = Field(..., description="目标平台列表")
    user_id: int = Field(1, description="用户 ID")
    adapt_content: bool = Field(True, description="是否按平台适配内容")
    enforce_moderation: bool = Field(False, description="是否强制风控（命中敏感词时跳过发布）")
    source_post_id: str = Field("", description="来源热点帖子 ID（可空）")


class SinglePublishRequest(BaseModel):
    """单平台发布请求"""

    title: str
    content: str
    keywords: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    video_path: Optional[str] = None
    user_id: int = 1
    adapt_content: bool = True
    enforce_moderation: bool = False


class AccountCreateRequest(BaseModel):
    """账号创建请求"""

    user_id: int = 1
    platform: str
    cookies: str
    account_name: str = ""
    daily_limit: int = 5


class ModerateRequest(BaseModel):
    """内容风控检测请求"""

    content: str
    platform: str


class PlatformInfo(BaseModel):
    name: str
    name_cn: str
    icon: str
    category: str
    content_types: List[str]
    supports_video: bool
    supports_image: bool
    supports_article: bool
    min_images: int
    max_title_length: int
    max_content_length: int


# ==================== 路由：发布 ====================


@router.post("/multi-platform")
async def multi_platform_publish(req: MultiPublishRequest):
    """多平台并行发布

    返回每个平台的发布结果（成功/失败/原因）。
    """
    # 校验平台
    unsupported = [p for p in req.target_platforms if not PublisherFactory.is_supported(p)]
    if unsupported:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台: {unsupported}，已注册: {PublisherFactory.list_platforms()}",
        )

    task = PublishTask(
        title=req.title,
        content=req.content,
        keywords=req.keywords,
        images=req.images,
        video_path=req.video_path,
        target_platforms=req.target_platforms,
        user_id=req.user_id,
        source_post_id=req.source_post_id,
    )

    multi_publisher = get_multi_publisher()
    result = await multi_publisher.publish_to_multiple_platforms(
        task,
        adapt_content=req.adapt_content,
        enforce_moderation=req.enforce_moderation,
    )

    return {
        "success": result.status in (PublishStatus.SUCCESS, PublishStatus.PARTIAL),
        "status": result.status.value,
        "task_id": result.task_id,
        "platform_results": {k: v.to_dict() for k, v in result.platform_results.items()},
        "error_message": result.error_message,
        "published_at": result.published_at.isoformat() if result.published_at else None,
    }


@router.post("/single/{platform}")
async def single_platform_publish(platform: str, req: SinglePublishRequest):
    """单平台发布"""
    if not PublisherFactory.is_supported(platform):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台: {platform}，已注册: {PublisherFactory.list_platforms()}",
        )

    multi_publisher = get_multi_publisher()
    result = await multi_publisher.publish_to_single_platform(
        platform=platform,
        title=req.title,
        content=req.content,
        images=req.images,
        video_path=req.video_path,
        user_id=req.user_id,
        keywords=req.keywords,
    )

    return result.to_dict()


# ==================== 路由：平台元数据 ====================


@router.get("/platforms")
async def list_platforms(category: Optional[str] = Query(None)):
    """列出所有支持的平台"""
    platforms = list_supported_platforms(category=category)
    return {
        "total": len(platforms),
        "platforms": [
            PlatformInfo(
                name=p.name,
                name_cn=p.name_cn,
                icon=p.icon,
                category=p.category,
                content_types=p.content_types,
                supports_video=p.supports_video,
                supports_image=p.supports_image,
                supports_article=p.supports_article,
                min_images=p.min_images,
                max_title_length=p.max_title_length,
                max_content_length=p.max_content_length,
            ).dict()
            for p in platforms
        ],
    }


@router.get("/platforms/{platform}")
async def get_platform_detail(platform: str):
    """获取单个平台详情"""
    meta = get_platform_meta(platform)
    if not meta:
        raise HTTPException(status_code=404, detail=f"未知平台: {platform}")
    return {
        "name": meta.name,
        "name_cn": meta.name_cn,
        "icon": meta.icon,
        "category": meta.category,
        "content_types": meta.content_types,
        "supports_video": meta.supports_video,
        "supports_image": meta.supports_image,
        "supports_article": meta.supports_article,
        "min_images": meta.min_images,
        "max_title_length": meta.max_title_length,
        "max_content_length": meta.max_content_length,
        "max_images": meta.max_images,
        "setup_guide": meta.setup_guide,
        "doc_url": meta.doc_url,
    }


# ==================== 路由：账号管理 ====================


@router.get("/accounts")
async def list_accounts(
    platform: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
):
    """列出所有账号（可按平台/用户过滤）"""
    if not legacy_account_api_enabled():
        raise HTTPException(status_code=404, detail="旧发布账号接口已关闭，请使用 /api/accounts")
    service = get_account_service()
    accounts = await service.list_accounts(platform=platform, user_id=user_id)
    return {
        "total": len(accounts),
        "accounts": [a.to_dict() for a in accounts],
    }


@router.post("/accounts")
async def create_account(req: AccountCreateRequest):
    """添加账号"""
    if not legacy_account_api_enabled():
        raise HTTPException(status_code=404, detail="旧发布账号接口已关闭，请使用 /api/accounts")
    if not get_platform_meta(req.platform):
        raise HTTPException(status_code=400, detail=f"未知平台: {req.platform}")

    service = get_account_service()
    account = await service.save_account(
        user_id=req.user_id,
        platform=req.platform,
        cookies=req.cookies,
        account_name=req.account_name,
        daily_limit=req.daily_limit,
    )
    return {"success": True, "account": account.to_dict()}


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: int):
    """删除账号（标记 is_active=False）"""
    if not legacy_account_api_enabled():
        raise HTTPException(status_code=404, detail="旧发布账号接口已关闭，请使用 /api/accounts")
    if not await get_account_service().disable_account(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"success": True, "account_id": account_id}


@router.post("/accounts/{account_id}/reset-cooldown")
async def reset_cooldown(account_id: int):
    """重置账号冷却状态"""
    if not legacy_account_api_enabled():
        raise HTTPException(status_code=404, detail="旧发布账号接口已关闭，请使用 /api/accounts")
    if not await get_account_service().reset_cooldown(account_id):
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"success": True, "account_id": account_id}


# ==================== 路由：风控 ====================


@router.post("/moderate")
async def moderate(req: ModerateRequest):
    """内容风控预检测（不发布，仅检测）"""
    if not get_platform_meta(req.platform):
        raise HTTPException(status_code=400, detail=f"未知平台: {req.platform}")

    passed, hits = moderate_content(req.content, req.platform)
    adapted = adapt_for_platform("", req.content, req.platform, enforce_moderation=False)

    return {
        "platform": req.platform,
        "passed": passed,
        "hits": hits,
        "warnings": adapted["warnings"],
        "adapted_content": adapted["content"],
    }


# ==================== 路由：账号分组管理（阶段四任务 4.3） ====================


class SetGroupRequest(BaseModel):
    """设置账号分组请求"""
    group: str = Field(..., description="分组名（domestic_new/domestic_mature/overseas_us/overseas_eu 等）")
    region: str = Field("", description="地域（CN/US/EU/SEA 等）")


@router.get("/accounts/groups")
async def list_account_groups():
    """列出所有已使用的分组"""
    svc = get_account_service()
    groups = await svc.list_groups()
    return {"groups": groups, "count": len(groups)}


@router.get("/accounts/by-group")
async def list_accounts_by_group(
    group: str = Query(...),
    platform: str = Query(""),
):
    """按分组列出账号"""
    svc = get_account_service()
    accounts = await svc.list_by_group(group=group, platform=platform)
    return {
        "accounts": [a.to_dict() for a in accounts],
        "count": len(accounts),
    }


@router.post("/accounts/{account_id}/group")
async def set_account_group(account_id: int, req: SetGroupRequest):
    """设置账号分组与地域"""
    svc = get_account_service()
    ok = await svc.set_group(account_id, req.group, req.region)
    if not ok:
        raise HTTPException(400, "设置分组失败")
    return {"success": True, "account_id": account_id, "group": req.group, "region": req.region}


@router.post("/accounts/acquire-by-group")
async def acquire_by_group(
    platform: str = Query(...),
    group: str = Query(""),
    region: str = Query(""),
):
    """按分组+地域获取可用账号（不返回 cookie）"""
    svc = get_account_service()
    account = await svc.acquire_cookie_by_group(
        platform=platform, group=group, region=region
    )
    if not account:
        raise HTTPException(404, f"分组 {group} 内无可用账号")
    return {"account": account.to_dict()}


# ==================== 路由：发布记录（任务 P2-1） ====================


@router.get("/records")
async def list_publish_records(
    platform: Optional[str] = Query(None, description="平台过滤"),
    status: Optional[str] = Query(
        None, description="状态过滤: success / failed / skipped"
    ),
    start_date: Optional[str] = Query(
        None, description="起始日期 YYYY-MM-DD（或 ISO 字符串）"
    ),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    user_id: Optional[int] = Query(None, description="用户 ID 过滤"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """查询即时发布记录列表（任务 P2-1）"""
    from ..services.publisher.publish_records_store import get_publish_records_store
    store = get_publish_records_store()
    records = await store.list_records(
        platform=platform,
        status=status,
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return {"code": 0, "data": {"items": records, "total": len(records)}}


@router.get("/records/{record_id}")
async def get_publish_record(record_id: int):
    """查询单条发布记录详情（任务 P2-1）"""
    from ..services.publisher.publish_records_store import get_publish_records_store
    store = get_publish_records_store()
    record = await store.get_record(record_id)
    if not record:
        return {"code": 4040, "message": "记录不存在"}
    return {"code": 0, "data": record}
