# -*- coding: utf-8 -*-
"""
多平台一键拆解流水线路由（platform-agnostic）

支持 X / 抖音 / 小红书 / 哔哩哔哩 / 微博 / 知乎 等平台的
"热点→拆解→文案→发布→互动→监控" 全流程编排。

与 X 专用的 `/x-workbench/auto-pipeline` 路由平行存在，不互相影响。
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from api.services.auth import get_current_user, decode_token
from api.utils.rate_limit import rate_limit

logger = logging.getLogger("auto_pipeline_router")

router = APIRouter(
    prefix="/auto_pipeline",
    tags=["auto-pipeline"],
    dependencies=[
        Depends(get_current_user),
        Depends(rate_limit()),
    ],
)


# ------------------------------------------------------------------------------
# 请求模型
# ------------------------------------------------------------------------------

class HotspotItem(BaseModel):
    """源热点数据（platform-agnostic）"""
    post_id: str = Field("", description="源热点 ID（平台原始 ID 或 URL hash）")
    post_url: str = Field("", description="源热点 URL")
    content: str = Field("", description="源热点文案")
    video_url: str = Field("", description="源热点视频 URL（可选）")
    username: str = Field("", description="源热点作者")


class RunPipelineRequest(BaseModel):
    """启动多平台流水线"""
    platform: str = Field(..., description="目标平台：x/douyin/xiaohongshu/bilibili/weibo/zhihu")
    hotspot_item: HotspotItem
    skip_video: bool = Field(False, description="是否跳过解说视频生成")
    auto_monitor: bool = Field(True, description="是否自动启动评论监控（仅 X 生效）")
    trigger_interaction: bool = Field(False, description="是否触发同平台点赞造势")
    breakdown_text: Optional[str] = Field(
        None, description="已有的拆解文本（来自视频拆解 Modal），提供则跳过 Step1 AI 拆解"
    )
    pre_video_url: Optional[str] = Field(
        None, description="已生成的解说视频 URL（来自视频拆解 Modal），提供则跳过 Step2 视频生成并复用"
    )
    pre_selected_content: Optional[str] = Field(
        None, description="已编辑的发布文案（来自重试/编辑），提供则跳过 Step3-4 文案生成与 AI 选文案"
    )
    is_retry: bool = Field(False, description="是否为重试发布（来自发布中心重试按钮），写入 publish_records.metadata.is_retry 供前端区分")


# ------------------------------------------------------------------------------
# REST 接口
# ------------------------------------------------------------------------------

@router.get("/platforms")
async def list_supported_platforms():
    """列出支持全流程的平台（含能力标注）"""
    from api.services.auto_pipeline_service import get_supported_platforms
    return {
        "success": True,
        "platforms": get_supported_platforms(),
        "total": len(get_supported_platforms()),
    }


@router.post("/run")
async def run_pipeline(req: RunPipelineRequest, request: Request, current_user: dict = Depends(get_current_user)):
    """启动多平台一键拆解流水线（异步执行，立即返回任务 ID）"""
    from api.services.auto_pipeline_service import start_pipeline

    server_base_url = "http://localhost:8000"
    if request:
        server_base_url = f"{request.url.scheme}://{request.url.hostname}"
        if request.url.port and request.url.port not in (80, 443):
            server_base_url += f":{request.url.port}"

    try:
        task = await start_pipeline(
            platform=req.platform,
            hotspot_item=req.hotspot_item.model_dump(),
            options={
                "skip_video": req.skip_video,
                "auto_monitor": req.auto_monitor,
                "trigger_interaction": req.trigger_interaction,
                "breakdown_text": req.breakdown_text,
                "pre_video_url": req.pre_video_url,
                "pre_selected_content": req.pre_selected_content,
                "is_retry": req.is_retry,
            },
            server_base_url=server_base_url,
            owner_user_id=current_user.get("uid") if isinstance(current_user, dict) else None,
        )
        return {
            "success": True,
            "task_id": task["task_id"],
            "platform": req.platform,
            "message": f"流水线已启动,可通过 GET /auto_pipeline/{task['task_id']} 查询进度",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("启动流水线失败")
        raise HTTPException(500, f"启动流水线失败: {e}")


@router.get("")
async def list_pipelines(
    platform: Optional[str] = Query(None, description="按平台过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """查询最近的流水线任务列表"""
    from api.services.auto_pipeline_service import list_tasks

    owner_user_id = current_user.get("uid") if isinstance(current_user, dict) else None
    tasks = await list_tasks(
        platform=platform,
        status=status,
        owner_user_id=owner_user_id,
        limit=limit,
    )
    return {"success": True, "total": len(tasks), "tasks": tasks}


@router.get("/{task_id}")
async def get_pipeline_status(task_id: str):
    """查询流水线任务状态"""
    from api.services.auto_pipeline_service import get_task

    task = await get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return {"success": True, "task": task}


@router.post("/{task_id}/cancel")
async def cancel_pipeline(task_id: str):
    """取消正在执行的流水线"""
    from api.services.auto_pipeline_service import cancel_task

    ok = await cancel_task(task_id)
    if not ok:
        raise HTTPException(400, "无法取消(任务已完成或不存在)")
    return {"success": True, "message": "任务已取消"}


# ------------------------------------------------------------------------------
# WebSocket 实时进度
# ------------------------------------------------------------------------------

@router.websocket("/ws/{task_id}")
async def pipeline_websocket(websocket: WebSocket, task_id: str, token: str = Query(default="")):
    """流水线实时进度 WebSocket

    每 3 秒推送一次任务状态，直到任务完成或失败。
    客户端发送 "ping" 会收到 "pong" 响应。
    """
    from api.services.auto_pipeline_service import get_task

    # 鉴权
    try:
        payload = decode_token(token)
        user_id = str(payload.get("sub", "unknown"))
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    logger.info(f"[pipeline WS] User {user_id} connected for task {task_id}")

    try:
        while True:
            task = await get_task(task_id)
            if not task:
                await websocket.send_text(json.dumps({"error": "任务不存在"}))
                break

            await websocket.send_text(json.dumps({
                "type": "pipeline_status",
                "task": task,
            }))

            if task["status"] in ("completed", "failed", "cancelled"):
                break

            await asyncio.sleep(3)

    except WebSocketDisconnect:
        logger.info(f"[pipeline WS] User {user_id} disconnected for task {task_id}")
    except Exception as e:
        logger.warning(f"[pipeline WS] Error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
