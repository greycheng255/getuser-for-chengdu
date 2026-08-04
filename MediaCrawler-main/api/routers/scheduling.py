# -*- coding: utf-8 -*-
"""
发布策略 API 路由（第四阶段）

提供：
1. POST /api/scheduling/tasks - 创建定时发布任务
2. GET /api/scheduling/tasks - 列出任务
3. DELETE /api/scheduling/tasks/{task_id} - 取消任务
4. POST /api/scheduling/recommend-time - 推荐错峰发布时间
5. POST /api/scheduling/scheduler/start - 启动调度器
6. POST /api/scheduling/scheduler/stop - 停止调度器
7. GET /api/scheduling/calendar - 内容日历视图
8. POST /api/scheduling/calendar/items - 创建内容项
9. GET /api/scheduling/calendar/items - 列出内容项
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.scheduling import (
    get_publish_scheduler,
    get_content_calendar,
    ContentItem,
    ContentStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduling", tags=["scheduling"])


# ==================== Pydantic 模型 ====================


class ScheduleTaskRequest(BaseModel):
    title: str
    content: str
    images: List[str] = Field(default_factory=list)
    video_path: str = ""
    target_platforms: List[str]
    user_id: int = 1
    source_post_id: str = ""
    scheduled_at: Optional[datetime] = None


class RecommendTimeRequest(BaseModel):
    platform: str
    base_time: Optional[datetime] = None


class CalendarItemRequest(BaseModel):
    title: str
    content: str = ""
    content_type: str = "article"
    priority: str = "medium"
    planned_date: Optional[datetime] = None
    target_platforms: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


# ==================== 定时发布任务 ====================


@router.post("/tasks")
async def create_schedule_task(req: ScheduleTaskRequest):
    scheduler = get_publish_scheduler()
    from ..services.scheduling.publish_scheduler import ScheduledTask
    import uuid

    task = ScheduledTask(
        task_id=str(uuid.uuid4())[:8],
        title=req.title,
        content=req.content,
        images=req.images,
        video_path=req.video_path,
        target_platforms=req.target_platforms,
        user_id=req.user_id,
        source_post_id=req.source_post_id,
        scheduled_at=req.scheduled_at,
        created_at=datetime.utcnow(),
    )
    task_id = await scheduler.schedule_task(task)
    if task_id is None:
        raise HTTPException(500, "创建定时任务失败")
    return {"success": True, "task_id": task_id, "scheduled_at": task.scheduled_at}


@router.get("/tasks")
async def list_schedule_tasks(limit: int = Query(100, ge=1, le=500)):
    scheduler = get_publish_scheduler()
    tasks = await scheduler.list_all_tasks(limit=limit)
    return {"tasks": tasks, "count": len(tasks)}


@router.delete("/tasks/{task_id}")
async def cancel_schedule_task(task_id: int):
    scheduler = get_publish_scheduler()
    ok = await scheduler.cancel_task(task_id)
    if not ok:
        raise HTTPException(400, "取消任务失败")
    return {"success": True, "message": "任务已取消"}


@router.post("/recommend-time")
async def recommend_time(req: RecommendTimeRequest):
    scheduler = get_publish_scheduler()
    recommended = scheduler.recommend_publish_time(req.platform, req.base_time)
    peak_hours = scheduler.get_peak_hours(req.platform)
    return {
        "platform": req.platform,
        "recommended_at": recommended.isoformat(),
        "peak_hours": peak_hours,
    }


# ==================== 平台活跃时段（任务 2.4） ====================


@router.get("/peak-hours/{platform}")
async def get_peak_hours(platform: str):
    """查询平台活跃时段"""
    from ..services.scheduling.peak_hours import get_peak_hours_service
    svc = get_peak_hours_service()
    ph = svc.get_peak_hours(platform)
    return {"code": 0, "data": ph.to_dict()}


@router.get("/peak-hours")
async def list_peak_hours():
    """列出所有已配置平台"""
    from ..services.scheduling.peak_hours import get_peak_hours_service
    svc = get_peak_hours_service()
    platforms = svc.list_platforms()
    data = [svc.get_peak_hours(p).to_dict() for p in platforms]
    return {"code": 0, "data": data}


@router.get("/peak-hours/{platform}/is-peak")
async def is_peak_now(platform: str):
    """判断当前是否处于活跃时段"""
    from ..services.scheduling.peak_hours import get_peak_hours_service
    svc = get_peak_hours_service()
    now = datetime.utcnow()
    return {
        "code": 0,
        "data": {
            "platform": platform,
            "is_peak": svc.is_peak_now(platform, now),
            "checked_at": now.isoformat(),
        },
    }


class SmartStaggerRequest(BaseModel):
    """智能错峰请求"""
    platforms: List[str] = Field(..., description="目标平台列表")
    base_time: Optional[datetime] = None
    min_gap_minutes: int = Field(30, description="各平台发布间隔分钟")


@router.post("/smart-stagger")
async def smart_stagger(req: SmartStaggerRequest):
    """多平台智能错峰推荐"""
    from ..services.scheduling.peak_hours import get_peak_hours_service
    svc = get_peak_hours_service()
    result = svc.recommend_multi_platform_times(
        req.platforms, req.base_time, req.min_gap_minutes,
    )
    return {
        "code": 0,
        "data": {
            p: t.isoformat() for p, t in result.items()
        },
    }


class FrequencyAdaptRequest(BaseModel):
    """发布频率自适应请求"""
    platform: str
    recent_success_rate: float = Field(..., ge=0, le=1, description="近期发布成功率")
    current_interval_minutes: int = Field(60, description="当前发布间隔分钟")


@router.post("/frequency-adapt")
async def frequency_adapt(req: FrequencyAdaptRequest):
    """发布频率自适应"""
    from ..services.scheduling.peak_hours import get_peak_hours_service
    svc = get_peak_hours_service()
    adjusted = svc.adapt_frequency_by_success_rate(
        req.platform, req.recent_success_rate, req.current_interval_minutes,
    )
    return {
        "code": 0,
        "data": {
            "platform": req.platform,
            "current_interval_minutes": req.current_interval_minutes,
            "adjusted_interval_minutes": adjusted,
            "recent_success_rate": req.recent_success_rate,
        },
    }


@router.post("/scheduler/start")
async def start_scheduler():
    scheduler = get_publish_scheduler()
    if scheduler.is_running():
        return {"success": True, "message": "调度器已在运行"}
    await scheduler.start()
    return {"success": True, "message": "调度器已启动"}


@router.post("/scheduler/stop")
async def stop_scheduler():
    scheduler = get_publish_scheduler()
    await scheduler.stop()
    return {"success": True, "message": "调度器已停止"}


# ==================== 内容日历 ====================


@router.get("/calendar")
async def calendar_view(year: int = Query(...), month: int = Query(..., ge=1, le=12)):
    cal = get_content_calendar()
    view = await cal.get_calendar_view(year, month)
    return view


@router.post("/calendar/items")
async def create_calendar_item(req: CalendarItemRequest):
    cal = get_content_calendar()
    item = ContentItem(
        title=req.title,
        content=req.content,
        content_type=req.content_type,
        priority=req.priority,
        planned_date=req.planned_date,
        target_platforms=req.target_platforms,
        tags=req.tags,
    )
    item_id = await cal.create_item(item)
    if item_id is None:
        raise HTTPException(500, "创建内容项失败")
    return {"success": True, "id": item_id}


@router.get("/calendar/items")
async def list_calendar_items(
    days: int = Query(7, ge=1, le=90),
):
    cal = get_content_calendar()
    items = await cal.get_upcoming(days=days)
    return {"items": items, "count": len(items)}


@router.post("/calendar/items/{item_id}/status")
async def update_item_status(item_id: int, status: str = Query(...)):
    cal = get_content_calendar()
    ok = await cal.update_status(item_id, status)
    if not ok:
        raise HTTPException(400, "更新状态失败")
    return {"success": True, "message": f"内容项已更新为 {status}"}
