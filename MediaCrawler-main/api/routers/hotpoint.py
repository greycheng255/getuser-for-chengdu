# -*- coding: utf-8 -*-
"""热点内容聚合 REST API"""
from fastapi import APIRouter, Query
from typing import Optional

from ..services.hotpoint_fetcher import (
    fetch_platform,
    fetch_all,
    get_platform_list,
    PLATFORMS,
)

router = APIRouter(prefix="/hotpoint", tags=["hotpoint"])


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
    if platform not in PLATFORMS:
        return {"success": False, "message": f"不支持的平台: {platform}", "supported": list(PLATFORMS.keys())}
    items = await fetch_platform(platform, force_refresh=force_refresh)
    meta = PLATFORMS[platform]
    return {
        "success": True,
        "platform": platform,
        "name": meta.get("name", platform),
        "color": meta.get("color", "#666"),
        "home": meta.get("home", ""),
        "region": meta.get("region", "global"),
        "count": len(items),
        "items": items,
    }


@router.post("/refresh")
async def refresh_all():
    """强制刷新所有平台缓存"""
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
    
    return {
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
