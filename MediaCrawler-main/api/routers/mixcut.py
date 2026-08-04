# -*- coding: utf-8 -*-
"""
AI 一键混剪 API 路由

端点：
  POST   /script              AI 生成混剪文案
  POST   /create              创建混剪任务
  POST   /batch               批量混剪
  GET    /tasks               列出混剪任务
  GET    /tasks/{task_id}     任务详情
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user
from ..services.mixcut.mixcut_service import get_mixcut_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mixcut", tags=["mixcut"])


class GenerateScriptRequest(BaseModel):
    industry: str = Field(..., description="行业名称")
    topic: str = Field(..., description="视频主题")
    style: str = Field("professional", description="风格: professional/casual/humorous")


class CreateMixcutRequest(BaseModel):
    video_files: List[str] = Field(..., min_items=1, description="视频素材文件路径列表")
    title: str = Field("", description="视频标题")
    banner_text: str = Field("", description="横幅文案")
    voiceover: str = Field("", description="口播文案")
    music_file: Optional[str] = Field(None, description="背景音乐文件路径")
    output_name: Optional[str] = Field(None, description="输出文件名")


class BatchMixcutRequest(BaseModel):
    groups: List[CreateMixcutRequest] = Field(..., min_items=1, description="混剪组列表")


@router.post("/script")
async def generate_script(
    req: GenerateScriptRequest,
    current_user: dict = Depends(get_current_user),
):
    """AI 生成混剪文案"""
    svc = get_mixcut_service()
    result = await svc.generate_script(
        industry=req.industry,
        topic=req.topic,
        style=req.style,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "生成失败"))
    return result


@router.post("/create")
async def create_mixcut(
    req: CreateMixcutRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建混剪任务"""
    svc = get_mixcut_service()
    script = {
        "title": req.title,
        "banner_text": req.banner_text,
        "voiceover": req.voiceover,
    }
    result = await svc.create_mixcut(
        video_files=req.video_files,
        script=script,
        music_file=req.music_file,
        output_name=req.output_name,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "混剪失败"))
    return result


@router.post("/batch")
async def batch_mixcut(
    req: BatchMixcutRequest,
    current_user: dict = Depends(get_current_user),
):
    """批量混剪"""
    svc = get_mixcut_service()
    material_groups = []
    for g in req.groups:
        material_groups.append({
            "video_files": g.video_files,
            "script": {"title": g.title, "banner_text": g.banner_text, "voiceover": g.voiceover},
            "music_file": g.music_file,
            "output_name": g.output_name,
        })
    result = await svc.batch_mixcut(material_groups)
    return result


@router.get("/tasks")
async def list_tasks(
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """列出混剪任务"""
    svc = get_mixcut_service()
    tasks = await svc.list_tasks(limit=limit)
    return {"tasks": tasks, "total": len(tasks)}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取混剪任务详情"""
    svc = get_mixcut_service()
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task
