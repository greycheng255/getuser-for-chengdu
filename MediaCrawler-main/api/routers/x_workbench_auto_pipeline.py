# -*- coding: utf-8 -*-
"""
X Twitter 自动化流水线路由

一键完成: 视频拆解 → 解说视频 → 发布文案 → AI选文案 → 发布到X
"""
import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from api.services.auth import get_current_user
from api.utils.rate_limit import rate_limit

logger = logging.getLogger("auto_pipeline_router")

router = APIRouter(
    prefix="/x-workbench/auto-pipeline",
    tags=["auto-pipeline"],
    dependencies=[
        Depends(get_current_user),
        Depends(rate_limit()),
    ],
)


class StartPipelineRequest(BaseModel):
    post_id: str = Field(..., description="原推文ID")
    skip_video: bool = Field(False, description="是否跳过视频生成步骤")


@router.post("")
async def start_pipeline(req: StartPipelineRequest, request: Request, current_user: dict = Depends(get_current_user)):
    """启动自动化流水线 (异步执行,立即返回任务ID)"""
    from api.services.auto_pipeline import start_pipeline as _start_pipeline

    server_base_url = "http://localhost:8000"
    if request:
        server_base_url = f"{request.url.scheme}://{request.url.hostname}"
        if request.url.port and request.url.port not in (80, 443):
            server_base_url += f":{request.url.port}"

    task = await _start_pipeline(req.post_id, req.skip_video, server_base_url)
    return {
        "success": True,
        "task_id": task["task_id"],
        "message": "流水线已启动,可通过 GET /auto-pipeline/{task_id} 查询进度",
    }


@router.get("/{task_id}")
async def get_pipeline_status(task_id: str):
    """查询流水线任务状态"""
    from api.services.auto_pipeline import get_task
    task = await get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return {"success": True, "task": task}


@router.get("")
async def list_pipelines(limit: int = Query(20, ge=1, le=100)):
    """查询最近的流水线任务列表"""
    from api.services.auto_pipeline import list_pipelines
    tasks = await list_pipelines(limit)
    return {"success": True, "total": len(tasks), "tasks": tasks}


@router.post("/{task_id}/cancel")
async def cancel_pipeline(task_id: str):
    """取消正在执行的流水线"""
    from api.services.auto_pipeline import cancel_pipeline
    ok = await cancel_pipeline(task_id)
    if not ok:
        raise HTTPException(400, "无法取消(任务已完成或不存在)")
    return {"success": True, "message": "任务已取消"}


@router.websocket("/ws/{task_id}")
async def pipeline_websocket(websocket: WebSocket, task_id: str, token: str = Query(default="")):
    """流水线实时进度 WebSocket

    每 3 秒推送一次任务状态,直到任务完成或失败。
    客户端发送 "ping" 会收到 "pong" 响应。
    """
    from api.services.auth import decode_token
    from api.services.auto_pipeline import get_task

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

            if task["status"] in ("completed", "failed"):
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
