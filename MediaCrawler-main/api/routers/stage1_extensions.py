# -*- coding: utf-8 -*-
"""
阶段一 P0 任务 1.2 / 1.3 / 1.6 / 1.7 扩展路由：
- /api/ai/video-config 视频参数配置 CRUD
- /api/ai/batch-generate 批量生成
- /api/ai/generate-from-hotspot P4 链路一键执行
- /api/moderation/review 人工复核
- /api/interact/bot-accounts 机器人账号管理
- /api/hotpoint/filter-config 筛选配置
- /api/hotpoint/{id}/quick-create 突发热点一键取材
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.services.ai.batch_video_generator import get_batch_video_generator
from api.services.ai.prompt_storyboard_pipeline import get_prompt_storyboard_pipeline
from api.services.ai.video_generation_config import (
    VideoGenConfig,
    get_video_gen_config_service,
)
from api.services.hotpoint.hotpoint_alert import get_hotpoint_alert_service
from api.services.hotpoint.hotpoint_classifier import get_hotpoint_classifier
from api.services.hotpoint.hotpoint_filter_config import (
    HotpointFilterConfig,
    get_hotpoint_filter_config_service,
)
from api.services.interactor.bot_account_pool import (
    BotAccountGroup,
    BotAccountStatus,
    get_bot_account_pool,
)
from api.services.moderation.review_workflow import (
    ReviewStatus,
    get_review_workflow_service,
)

logger = logging.getLogger(__name__)


# ============ 视频参数配置 ============
video_config_router = APIRouter(prefix="/ai/video-config", tags=["ai-video-config"])


class VideoConfigCreate(BaseModel):
    name: str
    duration_seconds: int = 30
    resolution: str = "720p"
    aspect_ratio: str = "9:16"
    visual_style: str = "modern"
    voice_timbre: str = "female_warm"
    subtitle_style: str = "white_bold_black_outline"
    bgm_mood: str = "upbeat"
    enable_subtitle: bool = True
    enable_voiceover: bool = True
    enable_bgm: bool = True
    owner_user_id: Optional[int] = None


@video_config_router.get("")
async def list_video_configs(
    user_id: Optional[int] = Query(None),
    include_presets: bool = Query(True),
):
    svc = get_video_gen_config_service()
    items = await svc.list_configs(user_id, include_presets)
    return {"code": 0, "data": {"items": items, "total": len(items)}}


@video_config_router.post("")
async def create_video_config(req: VideoConfigCreate):
    svc = get_video_gen_config_service()
    cfg = VideoGenConfig(
        name=req.name,
        duration_seconds=req.duration_seconds,
        resolution=req.resolution,
        aspect_ratio=req.aspect_ratio,
        visual_style=req.visual_style,
        voice_timbre=req.voice_timbre,
        subtitle_style=req.subtitle_style,
        bgm_mood=req.bgm_mood,
        enable_subtitle=req.enable_subtitle,
        enable_voiceover=req.enable_voiceover,
        enable_bgm=req.enable_bgm,
        owner_user_id=req.owner_user_id,
    )
    errors = cfg.validate()
    if errors:
        # 校验失败返回 HTTP 422（符合 REST 规范），而非 HTTP 200 + body code 4000
        return JSONResponse(
            status_code=422,
            content={"code": 4000, "message": "校验失败", "data": {"errors": errors}},
        )
    ok = await svc.save_config(cfg)
    return {"code": 0 if ok else 5000, "data": cfg.to_dict()}


@video_config_router.get("/{config_id}")
async def get_video_config(config_id: str):
    svc = get_video_gen_config_service()
    cfg = await svc.get_config(config_id)
    return {"code": 0 if cfg else 4040, "data": cfg}


@video_config_router.delete("/{config_id}")
async def delete_video_config(config_id: str):
    svc = get_video_gen_config_service()
    ok = await svc.delete_config(config_id)
    return {"code": 0 if ok else 5000, "data": {"success": ok}}


@video_config_router.get("/options/valid-values")
async def get_valid_values():
    """获取合法取值范围（前端表单用）"""
    from api.services.ai.video_generation_config import (
        VALID_ASPECT_RATIOS,
        VALID_BGM_MOODS,
        VALID_RESOLUTIONS,
        VALID_SUBTITLE_STYLES,
        VALID_VOICE_TIMBRES,
        VALID_VISUAL_STYLES,
    )
    return {
        "code": 0,
        "data": {
            "resolutions": list(VALID_RESOLUTIONS),
            "aspect_ratios": list(VALID_ASPECT_RATIOS),
            "visual_styles": list(VALID_VISUAL_STYLES),
            "voice_timbres": list(VALID_VOICE_TIMBRES),
            "subtitle_styles": list(VALID_SUBTITLE_STYLES),
            "bgm_moods": list(VALID_BGM_MOODS),
        },
    }


# ============ 批量视频生成 ============
batch_video_router = APIRouter(prefix="/ai/batch-generate", tags=["ai-batch-video"])


class BatchGenerateRequest(BaseModel):
    hotspot_ids: List[str]
    config_ids: Optional[List[str]] = None  # 视频参数配置 ID 列表
    user_id: Optional[int] = None


@batch_video_router.post("")
async def start_batch(req: BatchGenerateRequest):
    """启动批量生成任务"""
    gen = get_batch_video_generator()
    # 加载用户指定的配置
    variants = None
    if req.config_ids:
        svc = get_video_gen_config_service()
        variants = []
        for cid in req.config_ids:
            cfg_dict = await svc.get_config(cid)
            if cfg_dict:
                variants.append(VideoGenConfig(
                    config_id=cfg_dict["config_id"],
                    name=cfg_dict["name"],
                    duration_seconds=cfg_dict["duration_seconds"],
                    resolution=cfg_dict["resolution"],
                    aspect_ratio=cfg_dict["aspect_ratio"],
                    visual_style=cfg_dict["visual_style"],
                    voice_timbre=cfg_dict["voice_timbre"],
                    subtitle_style=cfg_dict["subtitle_style"],
                    bgm_mood=cfg_dict["bgm_mood"],
                ))
    task = await gen.start_batch(req.hotspot_ids, variants, req.user_id)
    return {
        "code": 0,
        "data": {
            "task_id": task.task_id,
            "total": task.total,
            "status": task.status,
            "created_at": task.created_at,
        },
    }


@batch_video_router.get("/{task_id}")
async def get_batch_task(task_id: str):
    gen = get_batch_video_generator()
    task = gen.get_task(task_id)
    if not task:
        return {"code": 4040, "message": "任务不存在"}
    return {
        "code": 0,
        "data": {
            "task_id": task.task_id,
            "status": task.status,
            "progress": task.progress,
            "total": task.total,
            "completed": task.completed,
            "failed": task.failed,
            "results": task.results,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        },
    }


@batch_video_router.get("")
async def list_batch_tasks():
    gen = get_batch_video_generator()
    return {"code": 0, "data": {"items": gen.list_tasks()}}


# ============ P4 提示词/分镜链路 ============
prompt_pipeline_router = APIRouter(prefix="/ai", tags=["ai-prompt-pipeline"])


class GenerateFromHotspotRequest(BaseModel):
    hotspot_video_url: str
    video_config_id: Optional[str] = None
    auto_moderate: bool = True


@prompt_pipeline_router.post("/generate-from-hotspot")
async def generate_from_hotspot(req: GenerateFromHotspotRequest):
    """P4 链路：热点视频 → 提示词/分镜 → 新视频生成 → 审核"""
    pipeline = get_prompt_storyboard_pipeline()
    # 加载视频参数配置
    video_config = None
    if req.video_config_id:
        svc = get_video_gen_config_service()
        cfg_dict = await svc.get_config(req.video_config_id)
        if cfg_dict:
            video_config = VideoGenConfig(
                duration_seconds=cfg_dict["duration_seconds"],
                resolution=cfg_dict["resolution"],
                aspect_ratio=cfg_dict["aspect_ratio"],
                visual_style=cfg_dict["visual_style"],
                voice_timbre=cfg_dict["voice_timbre"],
                subtitle_style=cfg_dict["subtitle_style"],
                bgm_mood=cfg_dict["bgm_mood"],
            )
    result = await pipeline.generate_video_from_hotspot(
        hotspot_video_url=req.hotspot_video_url,
        video_config=video_config,
        auto_moderate=req.auto_moderate,
    )
    return {"code": 0 if result.get("success") else 5000, "data": result}


@prompt_pipeline_router.post("/extract-prompt")
async def extract_prompt(req: GenerateFromHotspotRequest):
    """仅提取提示词/分镜（不生成视频）"""
    pipeline = get_prompt_storyboard_pipeline()
    result = await pipeline.extract_from_hotspot(req.hotspot_video_url)
    return {"code": 0 if result.get("success") else 5000, "data": result}


# ============ 阶段四任务 4.2：提示词库 + 一键完整链路 ============


class PromptSearchRequest(BaseModel):
    keyword: str = ""
    category: str = ""
    tags: Optional[List[str]] = None
    style_keyword: str = ""
    owner_user_id: Optional[int] = None
    limit: int = 20
    offset: int = 0


class PromptCreateRequest(BaseModel):
    title: str
    prompt_text: str
    category: str = ""
    style_keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    source_video_url: str = ""
    source_hotspot_id: str = ""
    storyboard_id: str = ""
    owner_user_id: Optional[int] = None


class FullPipelineRequest(BaseModel):
    hotspot_video_url: str
    hotspot_id: str = ""
    owner_user_id: Optional[int] = None
    video_config_id: Optional[str] = None
    publish_platforms: Optional[List[str]] = None


@prompt_pipeline_router.post("/prompt-library/search")
async def prompt_library_search(req: PromptSearchRequest):
    """检索提示词库"""
    from ..services.ai.prompt_library import get_prompt_library
    library = get_prompt_library()
    records = await library.search(
        keyword=req.keyword,
        category=req.category,
        tags=req.tags,
        style_keyword=req.style_keyword,
        owner_user_id=req.owner_user_id,
        limit=req.limit,
        offset=req.offset,
    )
    return {"code": 0, "data": [r.to_dict() for r in records]}


@prompt_pipeline_router.post("/prompt-library")
async def prompt_library_create(req: PromptCreateRequest):
    """手动新增提示词"""
    from ..services.ai.prompt_library import get_prompt_library
    library = get_prompt_library()
    prompt_id = await library.save_prompt(
        title=req.title,
        prompt_text=req.prompt_text,
        category=req.category,
        style_keywords=req.style_keywords,
        tags=req.tags,
        source_video_url=req.source_video_url,
        source_hotspot_id=req.source_hotspot_id,
        storyboard_id=req.storyboard_id,
        owner_user_id=req.owner_user_id,
    )
    if not prompt_id:
        return {"code": 5000, "message": "保存失败"}
    return {"code": 0, "data": {"prompt_id": prompt_id}}


@prompt_pipeline_router.get("/prompt-library/{prompt_id}")
async def prompt_library_get(prompt_id: str):
    """获取提示词详情"""
    from ..services.ai.prompt_library import get_prompt_library
    library = get_prompt_library()
    record = await library.get(prompt_id)
    if not record:
        return {"code": 404, "message": "提示词不存在"}
    return {"code": 0, "data": record.to_dict()}


@prompt_pipeline_router.post("/prompt-library/{prompt_id}/variant")
async def prompt_library_variant(prompt_id: str, variant_intent: str = ""):
    """基于已有提示词生成变体"""
    from ..services.ai.prompt_library import get_prompt_library
    library = get_prompt_library()
    variant = await library.generate_variant(prompt_id, variant_intent)
    if not variant:
        return {"code": 5000, "message": "生成失败"}
    return {"code": 0, "data": {"variant_prompt": variant}}


@prompt_pipeline_router.get("/storyboard/{storyboard_id}")
async def storyboard_get(storyboard_id: str):
    """查询分镜详情"""
    from ..services.ai.prompt_library import get_prompt_library
    library = get_prompt_library()
    sb = await library.get_storyboard(storyboard_id)
    if not sb:
        return {"code": 404, "message": "分镜不存在"}
    return {"code": 0, "data": sb}


@prompt_pipeline_router.post("/full-pipeline")
async def full_pipeline(req: FullPipelineRequest):
    """阶段四任务 4.2：一键执行完整链路
    热点视频 → 拆解 → 分镜 → 提示词库沉淀 → 视频生成 → 审核 → 多平台分发
    """
    pipeline = get_prompt_storyboard_pipeline()
    video_config = None
    if req.video_config_id:
        svc = get_video_gen_config_service()
        cfg_dict = await svc.get_config(req.video_config_id)
        if cfg_dict:
            video_config = VideoGenConfig(
                duration_seconds=cfg_dict["duration_seconds"],
                resolution=cfg_dict["resolution"],
                aspect_ratio=cfg_dict["aspect_ratio"],
                visual_style=cfg_dict["visual_style"],
                voice_timbre=cfg_dict["voice_timbre"],
                subtitle_style=cfg_dict["subtitle_style"],
                bgm_mood=cfg_dict["bgm_mood"],
            )
    result = await pipeline.run_full_pipeline(
        hotspot_video_url=req.hotspot_video_url,
        video_config=video_config,
        owner_user_id=req.owner_user_id,
        hotspot_id=req.hotspot_id,
        publish_platforms=req.publish_platforms,
    )
    return {"code": 0 if result.get("success") else 5000, "data": result}


# ============ 人工复核 ============
review_router = APIRouter(prefix="/moderation/review", tags=["moderation-review"])


class CreateReviewRequest(BaseModel):
    content_type: str = "video"
    content_id: str
    content_url: str = ""
    content_preview: str = ""
    auto_moderation_result: Optional[dict] = None
    owner_user_id: Optional[int] = None


class SubmitReviewRequest(BaseModel):
    reviewer_id: int
    decision: str  # approved / rejected
    notes: str = ""
    tags: Optional[List[str]] = None


@review_router.post("")
async def create_review(req: CreateReviewRequest):
    svc = get_review_workflow_service()
    task = await svc.create_review_task(
        content_type=req.content_type,
        content_id=req.content_id,
        content_url=req.content_url,
        content_preview=req.content_preview,
        auto_moderation_result=req.auto_moderation_result,
        owner_user_id=req.owner_user_id,
    )
    return {"code": 0, "data": task.to_dict()}


@review_router.get("/queue")
async def list_pending(
    user_id: Optional[int] = Query(None),
    content_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    svc = get_review_workflow_service()
    items = await svc.list_pending_reviews(user_id, content_type, limit, offset)
    return {"code": 0, "data": {"items": items, "total": len(items)}}


@review_router.post("/{review_id}/submit")
async def submit_review(review_id: str, req: SubmitReviewRequest):
    svc = get_review_workflow_service()
    ok = await svc.submit_review(
        review_id=review_id,
        reviewer_id=req.reviewer_id,
        decision=req.decision,
        notes=req.notes,
        tags=req.tags,
    )
    return {"code": 0 if ok else 4000, "data": {"success": ok}}


@review_router.get("/recent")
async def list_recent(
    user_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    svc = get_review_workflow_service()
    items = await svc.list_recent_reviews(user_id, limit)
    return {"code": 0, "data": {"items": items}}


@review_router.get("/{review_id}")
async def get_review(review_id: str):
    svc = get_review_workflow_service()
    item = await svc.get_review(review_id)
    return {"code": 0 if item else 4040, "data": item}


# ============ 机器人账号管理 ============
bot_account_router = APIRouter(prefix="/interact/bot-accounts", tags=["bot-accounts"])


class AddBotAccountRequest(BaseModel):
    platform: str
    cookie: str
    label: str = ""
    group: str = BotAccountGroup.DOMESTIC_NEW.value
    region: str = "cn"
    owner_user_id: Optional[int] = None


class BatchAddBotRequest(BaseModel):
    platform: str
    cookies: List[str]
    group: str = BotAccountGroup.DOMESTIC_NEW.value
    region: str = "cn"
    owner_user_id: Optional[int] = None


@bot_account_router.post("")
async def add_bot_account(req: AddBotAccountRequest):
    pool = get_bot_account_pool()
    acc = await pool.add_account(
        platform=req.platform,
        cookie=req.cookie,
        label=req.label,
        group=req.group,
        region=req.region,
        owner_user_id=req.owner_user_id,
    )
    return {"code": 0, "data": acc.to_dict()}


@bot_account_router.post("/batch")
async def batch_add(req: BatchAddBotRequest):
    pool = get_bot_account_pool()
    accounts = await pool.batch_add_from_cookies(
        platform=req.platform,
        cookies_list=req.cookies,
        group=req.group,
        region=req.region,
        owner_user_id=req.owner_user_id,
    )
    return {
        "code": 0,
        "data": {"added": len(accounts), "items": [a.to_dict() for a in accounts]},
    }


@bot_account_router.get("")
async def list_bot_accounts(
    platform: Optional[str] = Query(None),
    group: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    pool = get_bot_account_pool()
    items = await pool.list_accounts(
        platform=platform,
        group=group,
        region=region,
        status=status,
        owner_user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return {"code": 0, "data": {"items": items, "total": len(items)}}


@bot_account_router.delete("/{account_id}")
async def delete_bot_account(account_id: str):
    pool = get_bot_account_pool()
    ok = await pool.delete_account(account_id)
    return {"code": 0 if ok else 5000, "data": {"success": ok}}


@bot_account_router.get("/stats")
async def bot_stats(platform: Optional[str] = Query(None)):
    pool = get_bot_account_pool()
    return {"code": 0, "data": await pool.stats(platform)}


@bot_account_router.get("/groups")
async def list_groups():
    return {
        "code": 0,
        "data": {
            "groups": [g.value for g in BotAccountGroup],
            "statuses": [s.value for s in BotAccountStatus],
        },
    }


# ============ 热点筛选配置 ============
hotpoint_filter_router = APIRouter(prefix="/hotpoint/filter-config", tags=["hotpoint-filter"])


class SaveFilterConfigRequest(BaseModel):
    config_id: Optional[str] = None
    name: str
    min_heat_value: int = 0
    industry_categories: List[str] = []
    target_audience: List[str] = []
    regions: List[str] = []
    include_keywords: List[str] = []
    exclude_keywords: List[str] = []
    only_viral: bool = False
    categories: List[str] = []
    platforms: List[str] = []
    fetch_interval_seconds: int = 1800
    owner_user_id: Optional[int] = None
    is_active: bool = True


@hotpoint_filter_router.get("")
async def list_filter_configs(
    user_id: Optional[int] = Query(None),
    active_only: bool = Query(False),
):
    svc = get_hotpoint_filter_config_service()
    items = await svc.list_configs(user_id, active_only)
    return {"code": 0, "data": {"items": items, "total": len(items)}}


@hotpoint_filter_router.post("")
async def save_filter_config(req: SaveFilterConfigRequest):
    svc = get_hotpoint_filter_config_service()
    cfg = HotpointFilterConfig(
        config_id=req.config_id or "",
        name=req.name,
        min_heat_value=req.min_heat_value,
        industry_categories=req.industry_categories,
        target_audience=req.target_audience,
        regions=req.regions,
        include_keywords=req.include_keywords,
        exclude_keywords=req.exclude_keywords,
        only_viral=req.only_viral,
        categories=req.categories,
        platforms=req.platforms,
        fetch_interval_seconds=req.fetch_interval_seconds,
        owner_user_id=req.owner_user_id,
        is_active=req.is_active,
    )
    ok = await svc.save_config(cfg)
    return {"code": 0 if ok else 5000, "data": cfg.to_dict()}


@hotpoint_filter_router.delete("/{config_id}")
async def delete_filter_config(config_id: str):
    svc = get_hotpoint_filter_config_service()
    ok = await svc.delete_config(config_id)
    return {"code": 0 if ok else 5000, "data": {"success": ok}}


@hotpoint_filter_router.post("/preview")
async def preview_filter(req: SaveFilterConfigRequest):
    """预览筛选结果（不入库）"""
    svc = get_hotpoint_filter_config_service()
    cfg = HotpointFilterConfig(
        min_heat_value=req.min_heat_value,
        industry_categories=req.industry_categories,
        include_keywords=req.include_keywords,
        exclude_keywords=req.exclude_keywords,
        only_viral=req.only_viral,
        categories=req.categories,
        platforms=req.platforms,
    )
    result = await svc.preview(cfg)
    return {"code": 0, "data": result}


# ============ 热点分类 ============
hotpoint_category_router = APIRouter(prefix="/hotpoint/categories", tags=["hotpoint-category"])


@hotpoint_category_router.get("")
async def list_categories():
    """获取所有热点分类（含适配平台）"""
    clf = get_hotpoint_classifier()
    return {"code": 0, "data": {"items": clf.get_all_categories()}}


@hotpoint_category_router.post("/classify")
async def classify_hotpoint(payload: dict):
    """对单个热点进行分类"""
    title = payload.get("title", "")
    description = payload.get("description", "")
    clf = get_hotpoint_classifier()
    result = await clf.classify(title, description)
    return {
        "code": 0,
        "data": {
            "category": result.category,
            "confidence": result.confidence,
            "matched_keywords": result.matched_keywords,
            "recommended_platforms": result.recommended_platforms,
            "method": result.method,
        },
    }


# ============ 突发热点预警 ============
hotpoint_alert_router = APIRouter(prefix="/hotpoint/alerts", tags=["hotpoint-alert"])


@hotpoint_alert_router.get("/stats")
async def alert_stats():
    """获取预警监控统计"""
    svc = get_hotpoint_alert_service()
    return {"code": 0, "data": svc.get_stats()}


@hotpoint_alert_router.post("/start")
async def start_alert_service():
    """启动后台预警扫描"""
    svc = get_hotpoint_alert_service()
    if not svc.is_running():
        ok = await svc.start()
        return {"code": 0 if ok else 5000, "data": {"running": svc.is_running()}}
    return {"code": 0, "data": {"running": True, "message": "已在运行"}}


@hotpoint_alert_router.post("/stop")
async def stop_alert_service():
    svc = get_hotpoint_alert_service()
    await svc.stop()
    return {"code": 0, "data": {"running": svc.is_running()}}


@hotpoint_alert_router.get("/check/{hotspot_id}")
async def manual_check(hotspot_id: str):
    """手动检测单热点突发状态"""
    svc = get_hotpoint_alert_service()
    result = await svc.manual_check(hotspot_id)
    return {"code": 0 if result else 4040, "data": result}


# ============ 突发热点一键取材（P1-9） ============
# 独立子路由：路径 /api/hotpoint/{hotspot_id}/quick-create
# 注意：hotpoint_alert_router 的前缀是 /hotpoint/alerts，无法直接挂载该路径，
# 因此新建前缀为 /hotpoint 的子路由；与既有 hotpoint_router 的 GET /{platform}
# 路径段数不同、方法不同，不会冲突。
hotpoint_quick_router = APIRouter(prefix="/hotpoint", tags=["hotpoint-quick-create"])


@hotpoint_quick_router.post("/{hotspot_id}/quick-create")
async def quick_create_from_hotpoint(hotspot_id: str):
    """突发热点一键取材：基于单个热点启动视频生成草稿任务

    流程：
    1. 通过 get_hot_items_store().get_hot_item(hotspot_id) 读取热点详情
    2. 调用 batch_video_generator.start_batch 以单热点方式启动生成任务
    3. 返回 task_id 与跳转链接，前端可跳转 /video-gen-config?task_id=...
    """
    try:
        from api.services.hotpoint.hot_items_store import get_hot_items_store

        try:
            hot_id = int(hotspot_id)
        except (TypeError, ValueError):
            return {"success": False, "error": f"hotspot_id 必须为整数: {hotspot_id}"}

        store = get_hot_items_store()
        hotspot = await store.get_hot_item(hot_id)
        if not hotspot:
            return {"success": False, "error": f"热点 {hotspot_id} 不存在"}

        # 单热点方式启动批量生成（默认 4 个变体）
        gen = get_batch_video_generator()
        task = await gen.start_batch([str(hot_id)], variants=None, user_id=None)

        return {
            "success": True,
            "task_id": task.task_id,
            "hotspot_id": str(hot_id),
            "hotspot_title": hotspot.get("title") or "",
            "total": task.total,
            "redirect_url": f"/video-gen-config?task_id={task.task_id}",
        }
    except Exception as e:
        logger.warning(f"[quick-create] 一键取材失败: {e}")
        return {"success": False, "error": str(e)}


# ============ 五功能统一流水线 ============
# 提示词库 → 视频参数配置 → 数字人视频生成 → 人工复核 → 发布调度管理 → 话术库互动
unified_pipeline_router = APIRouter(prefix="/pipeline", tags=["unified-pipeline"])


class RunPipelineRequest(BaseModel):
    source_type: str = Field(..., description="输入源类型: hotspot_url/prompt_id/manual_text")
    source_value: str = Field(..., description="URL/prompt_id/文案内容")
    video_config_id: str = Field("", description="视频参数配置ID（空则用默认）")
    publish_platforms: Optional[List[str]] = Field(None, description="目标发布平台列表")
    owner_user_id: Optional[int] = None


@unified_pipeline_router.post("/run")
async def run_unified_pipeline(req: RunPipelineRequest):
    """启动五功能统一流水线

    执行至人工复核环节暂停，复核通过后自动推进发布调度与互动。
    """
    from api.services.ai.unified_pipeline import get_unified_pipeline
    pipeline = get_unified_pipeline()
    result = await pipeline.run_unified_pipeline(
        source_type=req.source_type,
        source_value=req.source_value,
        video_config_id=req.video_config_id,
        publish_platforms=req.publish_platforms,
        owner_user_id=req.owner_user_id,
    )
    return {"code": 0 if result.get("success") else 5000, "data": result}


@unified_pipeline_router.get("/{pipeline_id}")
async def get_pipeline_status(pipeline_id: str):
    """查询流水线状态（含6步进度）"""
    from api.services.ai.unified_pipeline import get_unified_pipeline
    pipeline = get_unified_pipeline()
    data = await pipeline.get_pipeline_status(pipeline_id)
    if not data:
        return {"code": 4040, "message": "流水线不存在"}
    return {"code": 0, "data": data}


@unified_pipeline_router.get("")
async def list_pipelines(limit: int = Query(20, ge=1, le=100)):
    """列出最近的流水线任务"""
    from api.services.ai.unified_pipeline import get_unified_pipeline
    pipeline = get_unified_pipeline()
    items = await pipeline.list_pipelines(limit)
    return {"code": 0, "data": {"items": items, "total": len(items)}}
