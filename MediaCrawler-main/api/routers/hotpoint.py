# -*- coding: utf-8 -*-
"""热点内容聚合 REST API"""
import asyncio
import time
from fastapi import APIRouter, Query
from typing import Optional

from ..services.hotpoint_fetcher import (
    fetch_platform,
    fetch_all,
    get_platform_list,
    PLATFORMS,
    normalize_platform_id,
)

router = APIRouter(prefix="/hotpoint", tags=["hotpoint"])

# 后台刷新任务状态（避免重复启动 + 提供状态查询）
# fetch_all 内部已用 asyncio.gather 并行抓取所有平台，但单平台 Playwright
# 爬取耗时较长，同步等待会导致 HTTP 超时（90s+）。改为后台异步执行。
_refresh_task: Optional[asyncio.Task] = None
_refresh_status: dict = {
    "running": False,
    "started_at": 0,
    "completed_at": 0,
    "result": None,
    "error": None,
}


@router.get("/platforms")
async def list_platforms():
    """获取支持的热点平台列表"""
    return {"platforms": get_platform_list()}


@router.get("/list")
async def get_hotpoint_list(
    region: Optional[str] = Query(default=None, description="按区域筛选: china / global"),
    force_refresh: bool = Query(default=False, description="强制刷新缓存"),
):
    """获取所有平台热点内容（按平台分组）

    返回结构:
      {
        "china":   { "douyin": [...], "weibo": [...], ... },
        "global":  { "x": [...], "hackernews": [...], ... }
      }
    """
    all_data = await fetch_all(force_refresh=force_refresh)
    result: dict = {"china": {}, "global": {}}
    for pid, items in all_data.items():
        meta = PLATFORMS.get(pid, {})
        region_key = meta.get("region", "global")
        result.setdefault(region_key, {})[pid] = {
            "name": meta.get("name", pid),
            "color": meta.get("color", "#666"),
            "home": meta.get("home", ""),
            "items": items,
        }
    if region:
        return {"region": region, "data": result.get(region, {})}
    return result


@router.get("/{platform}")
async def get_platform_hotpoint(
    platform: str,
    force_refresh: bool = Query(default=False, description="强制刷新缓存"),
):
    """获取指定平台的热点内容"""
    normalized = normalize_platform_id(platform)
    if normalized not in PLATFORMS:
        return {"success": False, "message": f"不支持的平台: {platform}", "supported": list(PLATFORMS.keys())}
    items = await fetch_platform(normalized, force_refresh=force_refresh)
    meta = PLATFORMS[normalized]
    return {
        "success": True,
        "platform": platform,
        "normalized_platform": normalized,
        "name": meta.get("name", normalized),
        "color": meta.get("color", "#666"),
        "home": meta.get("home", ""),
        "region": meta.get("region", "global"),
        "count": len(items),
        "items": items,
    }


@router.post("/refresh")
async def refresh_all():
    """强制刷新所有平台缓存（后台异步执行，立即返回）

    fetch_all 内部已用 asyncio.gather 并行抓取所有平台，但单平台 Playwright
    爬取耗时较长，同步等待会导致 HTTP 超时（90s+）。改为后台异步：
    立即返回"已启动"，前端轮询 GET /api/hotpoint/refresh/status 获取结果。
    """
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return {
            "success": False,
            "message": "刷新任务正在进行中，请稍后通过 /api/hotpoint/refresh/status 查询状态",
            "status": _refresh_status,
        }
    _refresh_task = asyncio.create_task(_run_refresh_background())
    return {
        "success": True,
        "message": "刷新任务已启动，请通过 GET /api/hotpoint/refresh/status 查询进度",
        "status": {"running": True, "started_at": _refresh_status["started_at"]},
    }


@router.get("/refresh/status")
async def refresh_status():
    """查询后台刷新任务状态"""
    return _refresh_status


async def _run_refresh_background():
    """后台执行热点刷新（并行抓取所有平台，结果存入 _refresh_status）"""
    _refresh_status["running"] = True
    _refresh_status["started_at"] = time.time()
    _refresh_status["error"] = None
    _refresh_status["result"] = None
    try:
        all_data = await fetch_all(force_refresh=True, return_stats=True)

        china_platforms = []
        global_platforms = []
        total_added = 0
        total_count = 0

        for pid, stats in all_data.items():
            meta = PLATFORMS.get(pid, {})
            region_key = meta.get("region", "global")
            count = stats.get("total", 0)
            added = stats.get("added", 0)
            total_count += count
            total_added += added

            if region_key == "china":
                china_platforms.append({"id": pid, "name": meta.get("name", pid), "count": count, "added": added})
            else:
                global_platforms.append({"id": pid, "name": meta.get("name", pid), "count": count, "added": added})

        result = {
            "success": True,
            "message": f"刷新完成，新增 {total_added} 条热点，热点总数 {total_count} 条",
            "counts": {p: stats.get("total", 0) for p, stats in all_data.items()},
            "added": {p: stats.get("added", 0) for p, stats in all_data.items()},
            "summary": {
                "china": {
                    "platforms": china_platforms,
                    "count": len(china_platforms),
                    "total_items": sum(p["count"] for p in china_platforms),
                    "total_added": sum(p["added"] for p in china_platforms),
                },
                "global": {
                    "platforms": global_platforms,
                    "count": len(global_platforms),
                    "total_items": sum(p["count"] for p in global_platforms),
                    "total_added": sum(p["added"] for p in global_platforms),
                },
                "total": {
                    "platforms": len(china_platforms) + len(global_platforms),
                    "total_items": total_count,
                    "total_added": total_added,
                },
            },
        }
        _refresh_status["result"] = result
        _refresh_status["completed_at"] = time.time()
    except Exception as e:
        _refresh_status["error"] = str(e)
    finally:
        _refresh_status["running"] = False
        global _refresh_task
        _refresh_task = None
