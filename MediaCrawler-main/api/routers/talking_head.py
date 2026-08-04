# -*- coding: utf-8 -*-
"""
数字人口播视频 API 路由

对标超级IP智能体核心能力，提供：
1. POST /api/talking-head/extract-script  — 对标文案提取
2. POST /api/talking-head/rewrite         — 文案仿写
3. POST /api/talking-head/voice-clone      — 创建声音克隆模型
4. GET  /api/talking-head/voice-models     — 声音模型列表
5. POST /api/talking-head/digital-human    — 创建数字人形象
6. GET  /api/talking-head/digital-humans   — 数字人列表
7. POST /api/talking-head/generate         — 一键生成口播视频（全链路）
8. POST /api/talking-head/post-production  — 后期制作（字幕/BGM/封面）
9. GET  /api/talking-head/tasks            — 生成任务列表
10. GET /api/talking-head/status           — 服务状态（降级/真实模式）
"""
import json
import logging
import os
import tempfile
import time

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/talking-head", tags=["talking-head"])


def _path_to_talking_head_url(path: str) -> str:
    """把 /tmp/talking_head/xxx.mp4 本地路径转换为前端可访问的 URL

    前端通过 /api/talking-head/files/xxx.mp4 访问（main.py 已挂载静态目录）。
    """
    if not path:
        return ""
    # 取 basename，避免路径遍历
    basename = os.path.basename(path)
    if not basename:
        return ""
    return f"/api/talking-head/files/{basename}"


# ============ 请求模型 ============

class ExtractScriptRequest(BaseModel):
    video_url: str = Field(..., description="对标视频链接")
    platform: str = Field("", description="平台标识（可选）")


class RewriteRequest(BaseModel):
    original_text: str = Field(..., description="原始口播文案")
    style: str = Field("", description="风格要求")
    industry: str = Field("", description="行业")
    tone: str = Field("", description="语气")


class VoiceCloneRequest(BaseModel):
    sample_audio_path: str = Field(..., description="录音样本文件路径")
    name: str = Field(..., description="声音名称")


class DigitalHumanRequest(BaseModel):
    portrait_path: str = Field(..., description="形象照文件路径")
    name: str = Field(..., description="数字人名称")


class GenerateRequest(BaseModel):
    video_url: str = Field("", description="对标视频链接（与text二选一）")
    text: str = Field("", description="直接提供文案（与video_url二选一）")
    style: str = Field("", description="仿写风格")
    industry: str = Field("", description="行业")
    voice_model_id: int = Field(0, description="声音模型ID（0=使用默认TTS）")
    digital_human_id: int = Field(0, description="数字人模型ID（0=黑底视频）")
    enable_subtitle: bool = Field(True, description="是否生成字幕")
    enable_bgm: bool = Field(True, description="是否添加BGM")
    enable_cover: bool = Field(True, description="是否生成封面")
    bgm_mood: str = Field("default", description="BGM情绪标签")
    skip_rewrite: bool = Field(False, description="是否跳过仿写")


class PostProductionRequest(BaseModel):
    video_path: str = Field(..., description="视频文件路径")
    enable_subtitle: bool = Field(True)
    enable_bgm: bool = Field(True)
    enable_cover: bool = Field(True)
    audio_path: str = Field("", description="音频路径（生成字幕用）")
    bgm_mood: str = Field("default")
    cover_title: str = Field("")


# ============ 文案提取 ============

@router.post("/extract-script")
async def extract_script(req: ExtractScriptRequest):
    """从对标视频链接提取口播文案"""
    from api.services.ai.script_extractor import extract_script as do_extract

    try:
        result = await do_extract(req.video_url, platform=req.platform)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"文案提取失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 文案仿写 ============

@router.post("/rewrite")
async def rewrite_script(req: RewriteRequest):
    """对口播文案进行仿写改写"""
    from api.services.ai.script_rewriter import rewrite_script as do_rewrite

    try:
        result = await do_rewrite(
            req.original_text, style=req.style, industry=req.industry, tone=req.tone
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"文案仿写失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 声音克隆 ============

@router.post("/voice-clone")
async def create_voice_model(req: VoiceCloneRequest):
    """创建声音克隆模型"""
    from api.services.ai.voice_clone_service import (
        create_voice_model as do_create, is_cosyvoice_available,
    )

    try:
        result = await do_create(req.sample_audio_path, req.name)
        # 存入数据库
        from database.db_session import get_session
        from database.models import VoiceModel
        import asyncio

        async with get_session() as session:
            from sqlalchemy import select
            now = int(time.time())
            voice_model = VoiceModel(
                owner_user_id="1",
                name=req.name,
                provider=result.get("provider", "edge_tts"),
                provider_model_id=result.get("provider_model_id", ""),
                sample_audio_path=req.sample_audio_path,
                voice_config=json.dumps(result, ensure_ascii=False),
                status=result.get("status", "ready"),
                created_ts=now,
            )
            session.add(voice_model)
            await session.commit()
            await session.refresh(voice_model)
            db_id = voice_model.id

        return {
            "success": True,
            "data": {**result, "db_id": db_id},
            "mode": "cosyvoice" if is_cosyvoice_available() else "edge_tts_degraded",
        }
    except Exception as e:
        logger.error(f"声音克隆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/voice-models")
async def list_voice_models():
    """获取声音模型列表"""
    from database.db_session import get_session
    from database.models import VoiceModel
    from sqlalchemy import select

    try:
        async with get_session() as session:
            result = await session.execute(
                select(VoiceModel).order_by(VoiceModel.created_ts.desc()).limit(50)
            )
            models = result.scalars().all()
            return {
                "success": True,
                "data": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "provider": m.provider,
                        "status": m.status,
                        "created_ts": m.created_ts,
                    }
                    for m in models
                ],
            }
    except Exception as e:
        logger.error(f"声音模型列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 数字人 ============

@router.post("/digital-human/upload")
async def upload_digital_human(
    name: str = Query(..., description="数字人名称"),
    file: UploadFile = File(..., description="形象照图片"),
):
    """上传图片创建数字人形象"""
    from api.services.ai.digital_human_service import (
        create_digital_human as do_create, is_heygem_available,
    )
    import os

    try:
        # 保存上传的图片
        tmp_dir = os.path.join(tempfile.gettempdir(), "talking_head")
        os.makedirs(tmp_dir, exist_ok=True)
        ext = os.path.splitext(file.filename or "image.jpg")[1] or ".jpg"
        portrait_path = os.path.join(tmp_dir, f"portrait_{int(time.time())}{ext}")
        content = await file.read()
        with open(portrait_path, "wb") as f:
            f.write(content)
        logger.info(f"[TalkingHead] 数字人形象照上传: {portrait_path} ({len(content)} bytes)")

        result = await do_create(portrait_path, name)
        # 存入数据库
        from database.db_session import get_session
        from database.models import DigitalHumanModel

        async with get_session() as session:
            now = int(time.time())
            dh_model = DigitalHumanModel(
                owner_user_id="1",
                name=name,
                provider=result.get("provider", "image_video"),
                provider_model_id=result.get("provider_model_id", ""),
                portrait_path=portrait_path,
                status=result.get("status", "ready"),
                created_ts=now,
            )
            session.add(dh_model)
            await session.commit()
            await session.refresh(dh_model)
            db_id = dh_model.id

        return {
            "success": True,
            "data": {**result, "db_id": db_id, "id": db_id, "portrait_path": portrait_path},
            "mode": "heygem" if is_heygem_available() else "image_video_degraded",
        }
    except Exception as e:
        logger.error(f"数字人上传创建失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/digital-human")
async def create_digital_human(req: DigitalHumanRequest):
    """创建数字人形象"""
    from api.services.ai.digital_human_service import (
        create_digital_human as do_create, is_heygem_available,
    )

    try:
        result = await do_create(req.portrait_path, req.name)
        # 存入数据库
        from database.db_session import get_session
        from database.models import DigitalHumanModel
        from sqlalchemy import select

        async with get_session() as session:
            now = int(time.time())
            dh_model = DigitalHumanModel(
                owner_user_id="1",
                name=req.name,
                provider=result.get("provider", "image_video"),
                provider_model_id=result.get("provider_model_id", ""),
                portrait_path=req.portrait_path,
                status=result.get("status", "ready"),
                created_ts=now,
            )
            session.add(dh_model)
            await session.commit()
            await session.refresh(dh_model)
            db_id = dh_model.id

        return {
            "success": True,
            "data": {**result, "db_id": db_id},
            "mode": "heygem" if is_heygem_available() else "image_video_degraded",
        }
    except Exception as e:
        logger.error(f"数字人创建失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/digital-humans")
async def list_digital_humans():
    """获取数字人列表"""
    from database.db_session import get_session
    from database.models import DigitalHumanModel
    from sqlalchemy import select

    try:
        async with get_session() as session:
            result = await session.execute(
                select(DigitalHumanModel).order_by(DigitalHumanModel.created_ts.desc()).limit(50)
            )
            models = result.scalars().all()
            return {
                "success": True,
                "data": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "provider": m.provider,
                        "status": m.status,
                        "created_ts": m.created_ts,
                        "portrait_path": m.portrait_path or "",
                        "portrait_url": _path_to_talking_head_url(m.portrait_path or ""),
                    }
                    for m in models
                ],
            }
    except Exception as e:
        logger.error(f"数字人列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/digital-humans/{dh_id}")
async def delete_digital_human(dh_id: int):
    """删除数字人形象"""
    from database.db_session import get_session
    from database.models import DigitalHumanModel

    try:
        async with get_session() as session:
            dh = await session.get(DigitalHumanModel, dh_id)
            if not dh:
                raise HTTPException(status_code=404, detail="数字人不存在")
            await session.delete(dh)
            await session.commit()
        return {"success": True, "data": {"id": dh_id}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"数字人删除失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 一键生成 ============

@router.post("/generate")
async def generate_talking_head(req: GenerateRequest):
    """一键生成口播视频（全链路）"""
    from api.services.ai.talking_head_pipeline import run_full_pipeline
    from api.services.ai.voice_clone_service import synthesize_speech
    from api.services.ai.digital_human_service import create_digital_human

    try:
        # 查询声音模型和数字人（如有ID）
        voice_model = {}
        digital_human = {}

        if req.voice_model_id:
            from database.db_session import get_session
            from database.models import VoiceModel
            from sqlalchemy import select

            async with get_session() as session:
                vm = await session.get(VoiceModel, req.voice_model_id)
                if vm:
                    voice_model = json.loads(vm.voice_config or "{}")
                    voice_model["provider"] = vm.provider

        if req.digital_human_id:
            from database.db_session import get_session
            from database.models import DigitalHumanModel
            from sqlalchemy import select

            async with get_session() as session:
                dh = await session.get(DigitalHumanModel, req.digital_human_id)
                if dh:
                    digital_human = {
                        "provider": dh.provider,
                        "provider_model_id": dh.provider_model_id,
                        "portrait_path": dh.portrait_path,
                    }

        # 如未指定，使用降级默认值
        if not voice_model:
            voice_model = {"provider": "edge_tts", "provider_model_id": ""}
        if not digital_human:
            digital_human = {"provider": "image_video", "portrait_path": ""}

        # 运行全链路
        result = await run_full_pipeline({
            "video_url": req.video_url,
            "text": req.text,
            "style": req.style,
            "industry": req.industry,
            "voice_model": voice_model,
            "digital_human": digital_human,
            "enable_subtitle": req.enable_subtitle,
            "enable_bgm": req.enable_bgm,
            "enable_cover": req.enable_cover,
            "bgm_mood": req.bgm_mood,
            "skip_rewrite": req.skip_rewrite,
        })

        # 存入数据库
        try:
            from database.db_session import get_session
            from database.models import TalkingHeadTask

            now = int(time.time())
            async with get_session() as session:
                task = TalkingHeadTask(
                    owner_user_id="1",
                    source_video_url=req.video_url,
                    original_script=result.get("original_script", ""),
                    rewritten_script=result.get("rewritten_script", ""),
                    voice_model_id=req.voice_model_id,
                    digital_human_id=req.digital_human_id,
                    audio_path=result.get("audio_path", ""),
                    video_path=result.get("video_path", ""),
                    cover_path=result.get("cover_path", ""),
                    subtitle_path=result.get("subtitle_path", ""),
                    title_suggestions=json.dumps(result.get("title_suggestions", []), ensure_ascii=False),
                    tags=json.dumps(result.get("tags", []), ensure_ascii=False),
                    pipeline_steps=json.dumps(result.get("steps", []), ensure_ascii=False),
                    status=result.get("status", "unknown"),
                    error=result.get("error", ""),
                    elapsed=int(result.get("elapsed", 0)),
                    created_ts=now,
                    updated_ts=now,
                )
                session.add(task)
                await session.commit()
                await session.refresh(task)
                result["task_id"] = task.id
        except Exception as db_err:
            logger.warning(f"任务存库失败(不影响结果): {db_err}")

        # 把本地文件路径转换为前端可访问的 URL（/api/talking-head/files/xxx.mp4）
        result["video_url"] = _path_to_talking_head_url(result.get("video_path", ""))
        result["cover_url"] = _path_to_talking_head_url(result.get("cover_path", ""))
        result["audio_url"] = _path_to_talking_head_url(result.get("audio_path", ""))
        result["subtitle_url"] = _path_to_talking_head_url(result.get("subtitle_path", ""))

        return {"success": result.get("status") == "done", "data": result}
    except Exception as e:
        logger.error(f"口播视频生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 后期制作 ============

@router.post("/post-production")
async def post_production(req: PostProductionRequest):
    """对已有视频进行后期制作（字幕/BGM/封面）"""
    from api.services.ai.post_production_service import (
        generate_subtitle, burn_subtitle, add_bgm, generate_cover,
    )

    result = {"video_path": req.video_path}
    try:
        # 字幕
        if req.enable_subtitle and req.audio_path:
            sub_result = await generate_subtitle(req.audio_path)
            if sub_result.get("srt_path"):
                result["subtitle_path"] = sub_result["srt_path"]
                result["video_path"] = await burn_subtitle(req.video_path, sub_result["srt_path"])

        # BGM
        if req.enable_bgm:
            result["video_path"] = await add_bgm(result["video_path"], mood=req.bgm_mood)

        # 封面
        if req.enable_cover:
            result["cover_path"] = await generate_cover(result["video_path"], title=req.cover_title)

        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"后期制作失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 任务列表 ============

@router.get("/tasks")
async def list_tasks(limit: int = Query(20, ge=1, le=100)):
    """获取口播视频生成任务列表"""
    from database.db_session import get_session
    from database.models import TalkingHeadTask
    from sqlalchemy import select

    try:
        async with get_session() as session:
            result = await session.execute(
                select(TalkingHeadTask)
                .order_by(TalkingHeadTask.created_ts.desc())
                .limit(limit)
            )
            tasks = result.scalars().all()
            return {
                "success": True,
                "data": [
                    {
                        "id": t.id,
                        "status": t.status,
                        "source_video_url": t.source_video_url,
                        "original_script": t.original_script[:100] if t.original_script else "",
                        "rewritten_script": t.rewritten_script[:100] if t.rewritten_script else "",
                        "video_path": t.video_path,
                        "cover_path": t.cover_path,
                        "elapsed": t.elapsed,
                        "error": t.error,
                        "created_ts": t.created_ts,
                    }
                    for t in tasks
                ],
            }
    except Exception as e:
        logger.error(f"任务列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ 服务状态 ============

@router.get("/status")
async def service_status():
    """获取口播视频服务状态（降级/真实模式）"""
    from api.services.ai.voice_clone_service import is_cosyvoice_available
    from api.services.ai.digital_human_service import is_heygem_available
    from api.services.ai.dashscope_helper import is_dashscope_available
    from api.services.ai.script_extractor import _whisper_model_size

    whisper_loaded = True  # 模块可导入即为 True
    try:
        from api.services.ai.script_extractor import _get_whisper_model
        _get_whisper_model()  # 触发加载
    except Exception:
        whisper_loaded = False

    # 数字人模式优先级：HeyGem > DashScope wan2.2-s2v > 图片视频降级
    dashscope_ok = is_dashscope_available()
    heygem_ok = is_heygem_available()
    if heygem_ok:
        dh_mode = "heygem"
    elif dashscope_ok:
        dh_mode = "dashscope_wan2.2-s2v"
    else:
        dh_mode = "image_video_degraded"

    return {
        "success": True,
        "data": {
            "whisper": {
                "available": whisper_loaded,
                "model_size": _whisper_model_size,
                "engine": "faster-whisper",
            },
            "voice_clone": {
                "mode": "cosyvoice" if is_cosyvoice_available() else "edge_tts_degraded",
                "cosyvoice_available": is_cosyvoice_available(),
            },
            "digital_human": {
                "mode": dh_mode,
                "heygem_available": heygem_ok,
                "dashscope_available": dashscope_ok,
            },
            "ffmpeg": os.path.exists("/usr/bin/ffmpeg"),
            "yt_dlp": os.path.exists("/home/ubuntu/.local/bin/yt-dlp"),
        },
    }


# ============ 视频拆解 ============

class AnalyzeVideoRequest(BaseModel):
    video_url: str = Field(..., description="视频链接（抖音/小红书/B站）")


@router.post("/analyze-video")
async def analyze_video(req: AnalyzeVideoRequest):
    """AI 视频拆解 — 输入视频链接，生成脚本分析、分镜拆解、关键要点、推荐评论"""
    from api.services.ai.video_analyzer import analyze_video as do_analyze

    try:
        result = await do_analyze(req.video_url)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"视频拆解失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
