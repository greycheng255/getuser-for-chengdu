# -*- coding: utf-8 -*-
"""
本地生活 API 路由

端点：
  GET    /search                    高德POI搜索（keyword, city, page, page_size, types）
  GET    /search/detail             高德POI详情（source, poi_id）
  POST   /businesses/save           保存商家（platform, poi_id, extra?）
  POST   /businesses/batch-save     批量保存（items[], platform）
  GET    /businesses                列表（city/category/keyword/min_rating/page/page_size）
  GET    /businesses/{business_id}  详情
  PUT    /businesses/{business_id}  更新（手动补全电话/营业时间）
  DELETE /businesses/{business_id}  删除
  GET    /businesses/export         导出（fmt=xlsx）
  GET    /cities                    城市聚合
  GET    /categories                品类聚合
  GET    /config                    检查 AMAP_API_KEY 是否配置
"""
import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.auth import get_current_user, is_admin
from ..services.local_life.local_life_service import get_local_life_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-life", tags=["local-life"])


# ============ 请求模型 ============

class SaveBusinessRequest(BaseModel):
    platform: str = Field("amap", description="来源平台 amap/douyin/manual")
    poi_id: str = Field(..., description="高德POI ID")
    extra: Optional[dict] = Field(None, description="补充数据（手动改字段）")


class BatchSaveRequest(BaseModel):
    items: List[dict] = Field(..., description="search_from_amap 返回的 items")
    platform: str = Field("amap")


class UpdateBusinessRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    business_hours: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    photos: Optional[List[str]] = None
    price_avg: Optional[int] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None


# ============ 配置 / 元数据 ============

@router.get("/config")
async def get_config(current_user: dict = Depends(get_current_user)):
    """检查 AMAP_API_KEY 是否配置"""
    svc = get_local_life_service()
    return {"configured": svc.is_amap_configured()}


@router.get("/cities")
async def list_cities(current_user: dict = Depends(get_current_user)):
    """城市聚合（按商家数排序）"""
    svc = get_local_life_service()
    cities = await svc.list_cities(
        owner_user_id=str(current_user["id"]), is_admin=is_admin(current_user)
    )
    return cities


@router.get("/categories")
async def list_categories(current_user: dict = Depends(get_current_user)):
    """品类聚合"""
    svc = get_local_life_service()
    cats = await svc.list_categories(
        owner_user_id=str(current_user["id"]), is_admin=is_admin(current_user)
    )
    return cats


# ============ 搜索 ============

@router.get("/search")
async def search(
    keyword: str = Query(..., min_length=1, description="关键词，如 火锅"),
    city: Optional[str] = Query(None, description="城市名，如 成都"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=25),
    types: Optional[str] = Query(None, description="高德POI类型码，如 050000 餐饮服务"),
    current_user: dict = Depends(get_current_user),
):
    """高德 POI 搜索（不落库）"""
    svc = get_local_life_service()
    result = await svc.search_from_amap(
        keyword=keyword, city=city, page=page, page_size=page_size, types=types
    )
    return result


@router.get("/search/detail")
async def search_detail(
    poi_id: str = Query(..., description="高德 POI ID"),
    source: str = Query("amap"),
    current_user: dict = Depends(get_current_user),
):
    """高德 POI 详情"""
    svc = get_local_life_service()
    detail = await svc.get_business_detail(source=source, poi_id=poi_id)
    return detail


# ============ 商家 CRUD ============

@router.post("/businesses/save")
async def save_business(
    req: SaveBusinessRequest,
    current_user: dict = Depends(get_current_user),
):
    """保存单个商家（自动从高德拉详情后入库）"""
    svc = get_local_life_service()
    result = await svc.save_business(
        platform=req.platform, poi_id=req.poi_id,
        owner_user_id=str(current_user["id"]), extra=req.extra,
    )
    return result


@router.post("/businesses/batch-save")
async def batch_save(
    req: BatchSaveRequest,
    current_user: dict = Depends(get_current_user),
):
    """批量保存"""
    svc = get_local_life_service()
    result = await svc.batch_save_from_amap(
        items=req.items, owner_user_id=str(current_user["id"]), platform=req.platform
    )
    return result


@router.get("/businesses/export")
async def export_businesses(
    city: Optional[str] = None,
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    min_rating: Optional[float] = None,
    current_user: dict = Depends(get_current_user),
):
    """导出 Excel"""
    svc = get_local_life_service()
    filters = {}
    if city:
        filters["city"] = city
    if category:
        filters["category"] = category
    if keyword:
        filters["keyword"] = keyword
    if min_rating is not None:
        filters["min_rating"] = min_rating
    data = await svc.export_businesses(
        owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
        **filters,
    )
    if not data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="导出失败")
    filename = f"local_businesses_{int(time.time())}.xlsx"
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/businesses")
async def list_businesses(
    city: Optional[str] = None,
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    min_rating: Optional[float] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """商家列表（支持筛选）"""
    svc = get_local_life_service()
    result = await svc.list_businesses(
        owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
        city=city, category=category, keyword=keyword,
        min_rating=min_rating, page=page, page_size=page_size,
    )
    return result


@router.get("/businesses/{business_id}")
async def get_business(
    business_id: str,
    current_user: dict = Depends(get_current_user),
):
    """商家详情"""
    svc = get_local_life_service()
    biz = await svc.get_business(
        business_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not biz:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商家不存在")
    return biz


@router.put("/businesses/{business_id}")
async def update_business(
    business_id: str,
    req: UpdateBusinessRequest,
    current_user: dict = Depends(get_current_user),
):
    """更新商家（手动补全电话/营业时间等）"""
    svc = get_local_life_service()
    fields = req.dict(exclude_none=True)
    ok = await svc.update_business(
        business_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user), **fields,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商家不存在或无更新")
    return {"success": True, "message": "ok"}


@router.delete("/businesses/{business_id}")
async def delete_business(
    business_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除商家"""
    svc = get_local_life_service()
    ok = await svc.delete_business(
        business_id, owner_user_id=str(current_user["id"]),
        is_admin=is_admin(current_user),
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="商家不存在")
    return {"success": True, "message": "ok"}
