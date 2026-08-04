# -*- coding: utf-8 -*-
"""
风控优化 API 路由（第六阶段）

提供：
1. GET /api/risk-control/health - 账号健康度列表
2. GET /api/risk-control/health/{account_id} - 单账号健康度
3. POST /api/risk-control/check-anomalies - 扫描异常并生成预警
4. GET /api/risk-control/alerts - 异常预警列表
5. POST /api/risk-control/alerts/{alert_id}/resolve - 解决预警
6. GET /api/risk-control/proxies - 代理列表
7. POST /api/risk-control/proxies - 添加代理
8. DELETE /api/risk-control/proxies - 删除代理
9. GET /api/risk-control/proxies/match/{platform} - 按平台匹配代理
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.risk_control import (
    get_account_health_service,
    get_proxy_pool,
)
from ..services.risk_control.account_weight import get_account_weight_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risk-control", tags=["risk-control"])


class ProxyAddRequest(BaseModel):
    url: str
    country: str = ""
    platform: str = ""


class ProxyDeleteRequest(BaseModel):
    url: str


# ==================== 账号健康度 ====================


@router.get("/health")
async def list_health(platform: str = Query("", description="按平台过滤")):
    svc = get_account_health_service()
    result = await svc.list_health_by_platform(platform=platform)
    return {"accounts": result, "count": len(result)}


@router.get("/health/{account_id}")
async def get_health(account_id: int):
    svc = get_account_health_service()
    h = await svc.get_health(account_id)
    if h is None:
        raise HTTPException(404, "账号不存在")
    return {
        "account_id": h.account_id,
        "platform": h.platform,
        "account_name": h.account_name,
        "health_score": h.health_score,
        "health_level": h.health_level,
        "successes": h.successes,
        "failures": h.failures,
        "in_cooldown": h.in_cooldown,
        "cooldown_until": h.cooldown_until,
        "today_count": h.today_count,
        "daily_limit": h.daily_limit,
        "anomalies": h.anomalies,
    }


@router.post("/check-anomalies")
async def check_anomalies():
    """扫描所有账号，生成异常预警"""
    svc = get_account_health_service()
    alerts = await svc.check_anomalies()
    return {"alerts_created": alerts, "count": len(alerts)}


@router.get("/alerts")
async def list_alerts(only_unresolved: bool = Query(True)):
    svc = get_account_health_service()
    alerts = await svc.list_alerts(only_unresolved=only_unresolved)
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    svc = get_account_health_service()
    ok = await svc.resolve_alert(alert_id)
    if not ok:
        raise HTTPException(400, "解决预警失败")
    return {"success": True, "message": "预警已解决"}


# ==================== IP 代理池 ====================


@router.get("/proxies")
async def list_proxies():
    pool = get_proxy_pool()
    proxies = pool.list_proxies()
    return {"proxies": proxies, "count": len(proxies)}


@router.post("/proxies")
async def add_proxy(req: ProxyAddRequest):
    pool = get_proxy_pool()
    pool.add_proxy(req.url, req.country, req.platform)
    return {"success": True, "message": "代理已添加"}


@router.delete("/proxies")
async def remove_proxy(req: ProxyDeleteRequest):
    pool = get_proxy_pool()
    ok = pool.remove_proxy(req.url)
    if not ok:
        raise HTTPException(404, "代理不存在")
    return {"success": True, "message": "代理已删除"}


@router.get("/proxies/match/{platform}")
async def match_proxy(platform: str):
    pool = get_proxy_pool()
    proxy = pool.get_proxy(platform)
    return {"platform": platform, "proxy": proxy, "found": proxy is not None}


@router.get("/proxies/match-by-country")
async def match_proxy_by_country(platform: str, country: str):
    """按国家匹配代理（地域适配）"""
    pool = get_proxy_pool()
    proxy = pool.get_proxy_by_country(platform, country)
    return {
        "platform": platform, "country": country,
        "proxy": proxy, "found": proxy is not None,
    }


# ==================== 频次硬限制配置（任务 2.3） ====================


class QuotaConfigSaveRequest(BaseModel):
    platform: str = Field(..., description="平台名")
    max_publishes_per_day: int = Field(5, description="单账号单日最大发布数")
    max_interactions_per_day: int = Field(80, description="单账号单日最大互动数")
    max_comments_per_post: int = Field(10, description="单条内容最大评论数")
    like_comment_ratio: float = Field(5.0, description="点赞评论比例")
    owner_user_id: Optional[int] = Field(None, description="用户 ID")


@router.get("/quota")
async def get_quota_config(platform: str, owner_user_id: Optional[int] = None):
    """查询频次配置"""
    from ..services.risk_control.quota_config import get_quota_config_service
    svc = get_quota_config_service()
    cfg = await svc.get_config(platform, owner_user_id)
    return {"code": 0, "data": cfg.to_dict()}


@router.post("/quota")
async def save_quota_config(req: QuotaConfigSaveRequest):
    """保存频次配置"""
    from ..services.risk_control.quota_config import (
        get_quota_config_service, QuotaConfig,
    )
    svc = get_quota_config_service()
    cfg = QuotaConfig(
        platform=req.platform,
        max_publishes_per_day=req.max_publishes_per_day,
        max_interactions_per_day=req.max_interactions_per_day,
        max_comments_per_post=req.max_comments_per_post,
        like_comment_ratio=req.like_comment_ratio,
        owner_user_id=req.owner_user_id,
    )
    errors = cfg.validate()
    if errors:
        return {"code": 4000, "message": "参数校验失败", "errors": errors}
    ok = await svc.save_config(cfg)
    return {"code": 0 if ok else 5000, "data": cfg.to_dict()}


@router.get("/quota/list")
async def list_quota_configs(
    platform: Optional[str] = None, owner_user_id: Optional[int] = None,
):
    """查询全部频次配置"""
    from ..services.risk_control.quota_config import get_quota_config_service
    svc = get_quota_config_service()
    cfgs = await svc.list_configs(platform=platform, owner_user_id=owner_user_id)
    return {"code": 0, "data": [c.to_dict() for c in cfgs]}


@router.post("/quota/check-publish")
async def check_publish_quota(
    platform: str, account_id: str, owner_user_id: Optional[int] = None,
):
    """校验发布配额"""
    from ..services.risk_control.quota_config import get_quota_config_service
    svc = get_quota_config_service()
    result = await svc.check_publish_quota(platform, account_id, owner_user_id)
    return {"code": 0, "data": result.to_dict()}


@router.post("/quota/check-interaction")
async def check_interaction_quota(
    platform: str, account_id: str,
    interaction_type: str = "like",
    owner_user_id: Optional[int] = None,
):
    """校验互动配额"""
    from ..services.risk_control.quota_config import get_quota_config_service
    svc = get_quota_config_service()
    result = await svc.check_interaction_quota(
        platform, account_id, interaction_type, owner_user_id
    )
    return {"code": 0, "data": result.to_dict()}


# ==================== 账号权重（阶段三 P2-6 F3 接入主流程）====================


@router.get("/weights")
async def list_account_weights(platform: str = Query("", description="按平台过滤")):
    """列出账号权重"""
    svc = get_account_weight_service()
    if platform:
        result = await svc.list_by_platform(platform)
    else:
        result = []
    return {"weights": [w.to_dict() for w in result], "count": len(result)}


@router.get("/weights/{account_id}")
async def get_account_weight(account_id: int, platform: str = Query(..., description="平台")):
    """获取单账号权重"""
    svc = get_account_weight_service()
    weight = await svc.get_weight(account_id, platform)
    if not weight:
        # 即时计算一次
        weight = await svc.update_weight(account_id, platform)
    if not weight:
        raise HTTPException(status_code=404, detail="账号不存在或无法计算权重")
    return weight.to_dict()


@router.post("/weights/refresh")
async def refresh_account_weights(platform: str = Query("", description="指定平台，留空刷新全部")):
    """批量刷新账号权重"""
    svc = get_account_weight_service()
    count = await svc.refresh_all(platform=platform or None)
    return {"code": 0, "data": {"refreshed": count}}
