# -*- coding: utf-8 -*-
"""
操作日志 API 路由（阶段三 P2 任务 3.5）

提供：
1. GET  /api/audit-logs           - 查询操作日志
2. POST /api/audit-logs           - 手动记录操作日志
3. GET  /api/audit-logs/export    - 导出 CSV
4. GET  /api/audit-logs/reports   - 查询定时报表列表
5. POST /api/audit-logs/reports   - 立即生成报表
6. GET  /api/audit-logs/action-types - 支持的操作类型列表
"""
import csv
import io
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.utils.audit_log import (
    AuditActionType,
    get_audit_log_service,
    get_report_scheduler,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


class AuditLogCreateRequest(BaseModel):
    """操作日志创建请求"""
    action_type: str = Field(..., description="操作类型")
    user_id: Optional[int] = None
    platform: str = ""
    target: str = ""
    description: str = ""
    request_data: Optional[Dict[str, Any]] = None
    response_data: Optional[Dict[str, Any]] = None
    ip_address: str = ""
    user_agent: str = ""
    status: str = "success"
    error_message: str = ""


class ReportCreateRequest(BaseModel):
    """报表生成请求"""
    period: str = Field("daily", description="daily / weekly / monthly")
    days: int = Field(1, ge=1, le=365, description="报表覆盖天数")


@router.get("")
async def list_audit_logs(
    action_type: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """查询操作日志（支持多维度筛选）"""
    svc = get_audit_log_service()
    items = await svc.list_logs(
        action_type=action_type,
        user_id=user_id,
        platform=platform,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return {"code": 0, "data": {"items": items, "total": len(items), "offset": offset}}


@router.get("/export")
async def export_audit_logs(
    action_type: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    """导出操作日志为 CSV 文件（P1-6）"""
    svc = get_audit_log_service()
    # 最多导出 5000 条，避免内存爆炸
    items = await svc.list_logs(
        action_type=action_type,
        user_id=user_id,
        platform=platform,
        start_date=start_date,
        end_date=end_date,
        limit=5000,
        offset=0,
    )

    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM for Excel
    writer = csv.writer(output)
    writer.writerow([
        "log_id", "created_at", "action_type", "status", "user_id",
        "platform", "target", "description", "ip_address", "user_agent",
        "error_message", "request_data", "response_data",
    ])
    for it in items:
        writer.writerow([
            it.get("log_id", ""),
            it.get("created_at", ""),
            it.get("action_type", ""),
            it.get("status", ""),
            it.get("user_id", ""),
            it.get("platform", ""),
            it.get("target", ""),
            it.get("description", ""),
            it.get("ip_address", ""),
            it.get("user_agent", ""),
            it.get("error_message", ""),
            str(it.get("request_data", "")),
            str(it.get("response_data", "")),
        ])

    content = output.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                'attachment; filename="audit_logs.csv"'
            ),
        },
    )


@router.post("")
async def create_audit_log(req: AuditLogCreateRequest):
    """手动记录操作日志（供其他服务主动上报）"""
    svc = get_audit_log_service()
    log_id = await svc.log(
        action_type=req.action_type,
        user_id=req.user_id,
        platform=req.platform,
        target=req.target,
        description=req.description,
        request_data=req.request_data,
        response_data=req.response_data,
        ip_address=req.ip_address,
        user_agent=req.user_agent,
        status=req.status,
        error_message=req.error_message,
    )
    return {"code": 0, "data": {"log_id": log_id}}


@router.get("/action-types")
async def list_action_types():
    """支持的操作类型列表"""
    return {
        "code": 0,
        "data": {
            "items": [
                {"value": t.value, "label": t.name}
                for t in AuditActionType
            ],
        },
    }


@router.get("/reports")
async def list_reports(
    period: Optional[str] = Query(None, description="daily / weekly / monthly"),
    limit: int = Query(30, ge=1, le=200),
):
    """查询定时报表列表"""
    svc = get_report_scheduler()
    items = await svc.list_reports(period=period, limit=limit)
    return {"code": 0, "data": {"items": items, "total": len(items)}}


@router.post("/reports")
async def generate_report(req: ReportCreateRequest):
    """立即生成报表"""
    if req.period not in ("daily", "weekly", "monthly"):
        return {"code": 4000, "message": "period 必须是 daily/weekly/monthly"}
    svc = get_report_scheduler()
    report = await svc.generate_report(period=req.period, days=req.days)
    return {"code": 0, "data": report.to_dict()}
