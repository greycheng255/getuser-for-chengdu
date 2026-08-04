# -*- coding: utf-8 -*-
"""
多平台互动 API 路由（第二阶段）

提供：
1. POST /api/interact/multi-platform - 多平台并行互动（点赞/评论/回复/关注）
2. POST /api/interact/single/{platform} - 单平台互动
3. GET /api/interact/platforms - 列出支持互动的平台
4. POST /api/interact/monitor/posts - 添加监控帖子
5. DELETE /api/interact/monitor/posts - 移除监控
6. GET /api/interact/monitor/posts - 列出监控帖子
7. POST /api/interact/monitor/start - 启动评论监控
8. POST /api/interact/monitor/stop - 停止监控
9. GET /api/interact/monitor/status - 监控状态
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.interactor import (
    InteractorFactory,
    InteractionType,
    InteractionTask,
    get_multi_interactor,
)
from ..services.interactor.interaction_monitor import get_interaction_monitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interact", tags=["interact"])


# ==================== Pydantic 模型 ====================


class MultiInteractRequest(BaseModel):
    """多平台互动请求"""

    interaction_type: str = Field(..., description="互动类型: like/comment/reply/follow")
    target_url: str = Field(..., description="目标帖子/用户 URL")
    content: str = Field("", description="评论/回复内容（点赞/关注为空）")
    target_id: str = Field("", description="目标评论 ID（reply 时用）")
    target_platforms: List[str] = Field(..., description="目标平台列表")
    user_id: int = Field(1, description="用户 ID")


class SingleInteractRequest(BaseModel):
    """单平台互动请求"""

    interaction_type: str
    target_url: str
    content: str = ""
    target_id: str = ""
    user_id: int = 1
    cookies: str = Field("", description="可选：直接指定 cookie（不传则用账号池）")


class MonitorPostRequest(BaseModel):
    """添加监控帖子"""

    platform: str
    post_url: str
    my_comment_id: str = ""
    my_username: str = ""
    auto_reply: bool = True


class MonitorPostDeleteRequest(BaseModel):
    platform: str
    post_url: str


# ==================== 互动接口 ====================


@router.post("/multi-platform")
async def multi_platform_interact(req: MultiInteractRequest):
    """多平台并行互动"""
    valid_types = {"like", "comment", "reply", "follow"}
    if req.interaction_type not in valid_types:
        raise HTTPException(400, f"互动类型必须是 {valid_types} 之一")

    unsupported = [p for p in req.target_platforms if not InteractorFactory.is_supported(p)]
    if unsupported:
        raise HTTPException(400, f"不支持的平台: {unsupported}，已注册: {InteractorFactory.list_platforms()}")

    if req.interaction_type in ("comment", "reply") and not req.content.strip():
        raise HTTPException(400, "评论/回复内容不能为空")

    task = InteractionTask(
        interaction_type=req.interaction_type,
        target_url=req.target_url,
        target_id=req.target_id,
        content=req.content,
        target_platforms=req.target_platforms,
        user_id=req.user_id,
        created_at=datetime.utcnow(),
    )
    result = await get_multi_interactor().interact_across_platforms(task)
    successes = sum(1 for r in result.platform_results.values() if r.success)
    return {
        "success": result.status.value == "success",
        "status": result.status.value,
        "task_id": result.task_id,
        "summary": f"{successes}/{len(result.platform_results)} 平台成功",
        "platform_results": {k: v.to_dict() for k, v in result.platform_results.items()},
    }


@router.post("/single/{platform}")
async def single_platform_interact(platform: str, req: SingleInteractRequest):
    """单平台互动"""
    if not InteractorFactory.is_supported(platform):
        raise HTTPException(400, f"不支持的平台: {platform}")

    cookies = req.cookies
    if not cookies:
        from ..services.publisher.account_service import get_account_service

        account = await get_account_service().acquire_cookie(platform, user_id=req.user_id)
        if not account:
            raise HTTPException(400, f"{platform} 无可用账号")
        cookies = account.cookies

    interactor = InteractorFactory.create(platform, cookies=cookies, user_id=req.user_id)
    try:
        if req.interaction_type == "like":
            r = await interactor.like(req.target_url)
        elif req.interaction_type == "comment":
            r = await interactor.comment(req.target_url, req.content)
        elif req.interaction_type == "reply":
            r = await interactor.reply(req.target_url, req.target_id, req.content)
        elif req.interaction_type == "follow":
            r = await interactor.follow(req.target_url)
        else:
            raise HTTPException(400, f"不支持的互动类型: {req.interaction_type}")
        return r.to_dict()
    finally:
        pass


@router.get("/platforms")
async def list_interaction_platforms():
    """列出支持互动的平台"""
    platforms = InteractorFactory.list_platforms()
    return {
        "supported": platforms,
        "count": len(platforms),
        "interaction_types": ["like", "comment", "reply", "follow"],
    }


# ==================== 监控接口 ====================


@router.post("/monitor/posts")
async def add_monitor_post(req: MonitorPostRequest):
    """添加监控帖子"""
    if not InteractorFactory.is_supported(req.platform):
        raise HTTPException(400, f"不支持的平台: {req.platform}")
    monitor = get_interaction_monitor()
    await monitor.add_post(
        req.platform, req.post_url, req.my_comment_id, req.my_username, req.auto_reply
    )
    return {"success": True, "message": "监控帖子已添加"}


@router.delete("/monitor/posts")
async def remove_monitor_post(req: MonitorPostDeleteRequest):
    """移除监控帖子"""
    monitor = get_interaction_monitor()
    ok = await monitor.remove_post(req.platform, req.post_url)
    return {"success": ok}


@router.get("/monitor/posts")
async def list_monitor_posts():
    """列出所有监控帖子"""
    monitor = get_interaction_monitor()
    posts = await monitor.list_monitored()
    return {"posts": posts, "count": len(posts)}


@router.post("/monitor/start")
async def start_monitor():
    """启动评论监控"""
    monitor = get_interaction_monitor()
    if monitor.is_running():
        return {"success": True, "message": "监控已在运行"}
    await monitor.start()
    return {"success": True, "message": "评论监控已启动"}


@router.post("/monitor/stop")
async def stop_monitor():
    """停止评论监控"""
    monitor = get_interaction_monitor()
    await monitor.stop()
    return {"success": True, "message": "评论监控已停止"}


@router.get("/monitor/status")
async def monitor_status():
    """监控状态"""
    monitor = get_interaction_monitor()
    posts = await monitor.list_monitored()
    return {
        "running": monitor.is_running(),
        "check_interval": monitor.check_interval,
        "monitored_count": len(posts),
    }


# ==================== 互动调度器（任务 2.2） ====================


class ScheduleInteractionRequest(BaseModel):
    """调度互动任务请求"""
    post_url: str = Field(..., description="目标帖子 URL")
    platform: str = Field(..., description="平台名")
    user_id: Optional[int] = Field(None, description="发布用户 ID")
    min_likes: int = Field(3, description="最少点赞数")
    max_likes: int = Field(10, description="最多点赞数")
    min_comments: int = Field(1, description="最少评论数")
    max_comments: int = Field(3, description="最多评论数")
    follows: int = Field(0, description="关注数")
    collects: int = Field(0, description="收藏数")
    retweets: int = Field(0, description="转发数")
    like_comment_ratio: float = Field(5.0, description="点赞评论比例")
    delay_min_seconds: int = Field(300, description="启动延迟下限（秒）")
    delay_max_seconds: int = Field(1800, description="启动延迟上限（秒）")
    interval_min_seconds: int = Field(30, description="互动间隔下限（秒）")
    interval_max_seconds: int = Field(180, description="互动间隔上限（秒）")
    delay_seconds: Optional[int] = Field(None, description="显式指定启动延迟，覆盖随机区间")
    auto_start: bool = Field(True, description="是否自动启动后台任务")


@router.post("/schedule")
async def schedule_interaction(req: ScheduleInteractionRequest):
    """调度一次互动任务（PRD 5.4 时效控制）

    发布后延迟 5-30 分钟启动互动，避免机器化特征。
    """
    from ..services.interactor.interaction_scheduler import (
        get_interaction_scheduler, InteractionQuotaConfig,
    )
    quota = InteractionQuotaConfig(
        min_likes=req.min_likes, max_likes=req.max_likes,
        min_comments=req.min_comments, max_comments=req.max_comments,
        follows=req.follows, collects=req.collects, retweets=req.retweets,
        like_comment_ratio=req.like_comment_ratio,
        delay_min_seconds=req.delay_min_seconds,
        delay_max_seconds=req.delay_max_seconds,
        interval_min_seconds=req.interval_min_seconds,
        interval_max_seconds=req.interval_max_seconds,
    )
    errors = quota.validate()
    if errors:
        return {"code": 4000, "message": "参数校验失败", "errors": errors}
    scheduler = get_interaction_scheduler()
    await scheduler.ensure_table()
    task_id = await scheduler.schedule_interaction(
        post_url=req.post_url,
        platform=req.platform,
        user_id=req.user_id,
        quota=quota,
        delay_seconds=req.delay_seconds,
        auto_start=req.auto_start,
    )
    return {"code": 0, "data": {"task_id": task_id}}


@router.get("/schedule/{task_id}")
async def get_schedule_task(task_id: str):
    """查询调度任务详情"""
    from ..services.interactor.interaction_scheduler import get_interaction_scheduler
    scheduler = get_interaction_scheduler()
    task = await scheduler.get_task(task_id)
    if not task:
        return {"code": 4040, "message": "任务不存在"}
    return {"code": 0, "data": task.to_dict()}


@router.get("/schedule")
async def list_schedule_tasks(
    status: Optional[str] = None,
    platform: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
):
    """查询调度任务列表"""
    from ..services.interactor.interaction_scheduler import get_interaction_scheduler
    scheduler = get_interaction_scheduler()
    tasks = await scheduler.list_tasks(
        status=status, platform=platform, user_id=user_id,
        limit=limit, offset=offset,
    )
    pending_count = await scheduler.get_pending_count()
    return {
        "code": 0,
        "data": {"tasks": tasks, "pending_count": pending_count},
    }


@router.post("/schedule/{task_id}/cancel")
async def cancel_schedule_task(task_id: str):
    """取消调度任务"""
    from ..services.interactor.interaction_scheduler import get_interaction_scheduler
    scheduler = get_interaction_scheduler()
    ok = await scheduler.cancel_task(task_id)
    return {"code": 0 if ok else 4040, "message": "OK" if ok else "任务不存在或无法取消"}


@router.post("/schedule/{task_id}/start")
async def start_schedule_task(task_id: str):
    """手动启动调度任务"""
    from ..services.interactor.interaction_scheduler import get_interaction_scheduler
    scheduler = get_interaction_scheduler()
    ok = await scheduler.start_task(task_id)
    return {"code": 0 if ok else 4040, "message": "OK" if ok else "任务不存在或已在运行"}


# ==================== 话术库（任务 2.5 骨架） ====================


class ScriptCreateRequest(BaseModel):
    platform: str = Field("", description="平台名（空表示通用）")
    scene: str = Field("comment_reply", description="场景")
    content: str = Field(..., description="话术内容")
    tags: List[str] = Field(default_factory=list, description="标签")


@router.get("/scripts")
async def list_scripts(
    platform: Optional[str] = None,
    scene: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
):
    """查询话术列表"""
    from ..services.interactor.script_library import get_script_library
    library = get_script_library()
    scripts = await library.list_scripts(
        platform=platform, scene=scene, owner_user_id=user_id,
        limit=limit, offset=offset,
    )
    return {"code": 0, "data": scripts}


@router.post("/scripts")
async def create_script(req: ScriptCreateRequest):
    """新增话术"""
    from ..services.interactor.script_library import get_script_library
    library = get_script_library()
    script = await library.add_script(
        platform=req.platform, scene=req.scene, content=req.content, tags=req.tags,
    )
    return {"code": 0, "data": script.to_dict()}


@router.delete("/scripts/{script_id}")
async def delete_script(script_id: str):
    """删除话术"""
    from ..services.interactor.script_library import get_script_library
    library = get_script_library()
    ok = await library.delete_script(script_id)
    return {"code": 0 if ok else 4040, "message": "OK" if ok else "话术不存在"}


class ScriptBatchImportRequest(BaseModel):
    items: List[dict] = Field(..., description="话术列表")


@router.post("/scripts/batch-import")
async def batch_import_scripts(req: ScriptBatchImportRequest):
    """批量导入话术"""
    from ..services.interactor.script_library import get_script_library
    library = get_script_library()
    count = await library.batch_import(req.items)
    return {"code": 0, "data": {"imported": count}}


class ScriptGenerateRequest(BaseModel):
    """AI 话术生成请求"""
    script_type: str = Field("comment_reply", description="场景类型")
    context: str = Field("", description="上下文（如帖子标题）")
    platform: str = Field("", description="平台名")
    count: int = Field(5, ge=1, le=20, description="生成数量")
    use_ai: bool = Field(True, description="是否使用 AI")
    auto_save: bool = Field(False, description="是否自动入库")


@router.post("/scripts/generate")
async def generate_scripts(req: ScriptGenerateRequest):
    """AI 生成差异化话术变体（任务 2.5）"""
    from ..services.interactor.script_generator import get_script_generator
    from ..services.interactor.script_library import get_script_library
    generator = get_script_generator()
    variants = await generator.generate(
        script_type=req.script_type,
        context=req.context,
        platform=req.platform,
        count=req.count,
        use_ai=req.use_ai,
    )
    result = []
    library = get_script_library()
    for v in variants:
        item = {"content": v.content, "variant_type": v.variant_type}
        if req.auto_save:
            saved = await library.add_script(
                platform=req.platform,
                scene=req.script_type,
                content=v.content,
            )
            item["script_id"] = saved.script_id
        result.append(item)
    return {"code": 0, "data": {"variants": result, "count": len(result)}}


@router.get("/scripts/generator/status")
async def script_generator_status():
    """查询话术生成器状态"""
    from ..services.interactor.script_generator import get_script_generator
    generator = get_script_generator()
    return {"code": 0, "data": generator.get_status()}


# ==================== 互动量配置（阶段四任务 4.3） ====================


class InteractionConfigRequest(BaseModel):
    """互动量配置请求"""
    name: str = ""
    platform: str = "all"
    scene: str = "default"
    min_likes: int = Field(5, ge=0)
    max_likes: int = Field(20, ge=0)
    min_comments: int = Field(1, ge=0)
    max_comments: int = Field(5, ge=0)
    min_shares: int = Field(0, ge=0)
    max_shares: int = Field(3, ge=0)
    min_favorites: int = Field(0, ge=0)
    max_favorites: int = Field(5, ge=0)
    like_comment_ratio: float = Field(5.0, ge=0)
    interaction_target_total: int = Field(30, ge=0)
    delay_start_min_minutes: int = Field(5, ge=0)
    delay_start_max_minutes: int = Field(30, ge=0)
    interval_min_seconds: int = Field(30, ge=0)
    interval_max_seconds: int = Field(180, ge=0)
    weight_like: float = Field(0.6, ge=0, le=1)
    weight_comment: float = Field(0.15, ge=0, le=1)
    weight_share: float = Field(0.1, ge=0, le=1)
    weight_favorite: float = Field(0.15, ge=0, le=1)
    is_active: bool = True


@router.post("/configs")
async def save_interaction_config(req: InteractionConfigRequest):
    """保存互动量配置"""
    from ..services.interactor.interaction_config import (
        InteractionConfig,
        get_interaction_config_service,
    )
    svc = get_interaction_config_service()
    cfg = InteractionConfig(
        name=req.name,
        platform=req.platform,
        scene=req.scene,
        min_likes=req.min_likes, max_likes=req.max_likes,
        min_comments=req.min_comments, max_comments=req.max_comments,
        min_shares=req.min_shares, max_shares=req.max_shares,
        min_favorites=req.min_favorites, max_favorites=req.max_favorites,
        like_comment_ratio=req.like_comment_ratio,
        interaction_target_total=req.interaction_target_total,
        delay_start_min_minutes=req.delay_start_min_minutes,
        delay_start_max_minutes=req.delay_start_max_minutes,
        interval_min_seconds=req.interval_min_seconds,
        interval_max_seconds=req.interval_max_seconds,
        weight_like=req.weight_like,
        weight_comment=req.weight_comment,
        weight_share=req.weight_share,
        weight_favorite=req.weight_favorite,
        is_active=req.is_active,
    )
    cfg_id = await svc.save(cfg)
    if not cfg_id:
        raise HTTPException(500, "保存失败")
    return {"code": 0, "data": {"config_id": cfg_id}}


@router.get("/configs")
async def list_interaction_configs(
    platform: str = "",
    owner_user_id: Optional[int] = None,
):
    """列出互动量配置"""
    from ..services.interactor.interaction_config import get_interaction_config_service
    svc = get_interaction_config_service()
    configs = await svc.list(platform=platform, owner_user_id=owner_user_id)
    return {"code": 0, "data": [c.to_dict() for c in configs]}


@router.get("/configs/find")
async def find_interaction_config(
    platform: str = "all",
    scene: str = "default",
    owner_user_id: Optional[int] = None,
):
    """查找匹配的互动量配置"""
    from ..services.interactor.interaction_config import get_interaction_config_service
    svc = get_interaction_config_service()
    cfg = await svc.find(platform=platform, scene=scene, owner_user_id=owner_user_id)
    if not cfg:
        return {"code": 0, "data": None}
    return {"code": 0, "data": cfg.to_dict()}


@router.get("/configs/{config_id}")
async def get_interaction_config(config_id: str):
    """获取单条互动量配置"""
    from ..services.interactor.interaction_config import get_interaction_config_service
    svc = get_interaction_config_service()
    cfg = await svc.get(config_id)
    if not cfg:
        raise HTTPException(404, "配置不存在")
    return {"code": 0, "data": cfg.to_dict()}


@router.delete("/configs/{config_id}")
async def deactivate_interaction_config(config_id: str):
    """停用互动量配置"""
    from ..services.interactor.interaction_config import get_interaction_config_service
    svc = get_interaction_config_service()
    ok = await svc.deactivate(config_id)
    if not ok:
        raise HTTPException(400, "停用失败")
    return {"code": 0, "message": "配置已停用"}


@router.post("/configs/{config_id}/split")
async def compute_split(config_id: str, total: int = Query(30, ge=0)):
    """按权重分配总互动量到各类型"""
    from ..services.interactor.interaction_config import get_interaction_config_service
    svc = get_interaction_config_service()
    cfg = await svc.get(config_id)
    if not cfg:
        raise HTTPException(404, "配置不存在")
    return {"code": 0, "data": cfg.compute_split(total)}
