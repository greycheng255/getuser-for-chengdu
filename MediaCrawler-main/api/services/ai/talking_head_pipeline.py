# -*- coding: utf-8 -*-
"""
数字人口播视频全链路流水线

串联所有子服务，一键生成口播视频：
1. 文案提取（如有对标视频链接）
2. 文案仿写
3. 声音克隆合成音频
4. 数字人口播视频生成
5. 自动字幕
6. BGM 混音
7. 封面生成

对标超级IP智能体的"一键生成口播视频"全流程。
"""
import logging
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("talking_head_pipeline")

# 临时文件目录（与 digital_human_service / post_production_service 共用）
TMP_DIR = os.path.join(tempfile.gettempdir(), "talking_head")
FFMPEG_BIN = "/usr/bin/ffmpeg"


async def _download_thumbnail_to_local(url: str) -> str:
    """下载对标视频封面图到本地临时文件（用于无形象照时作为视频背景）"""
    if not url:
        return ""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.douyin.com/",
            })
            if resp.status_code == 200 and resp.content:
                local_path = os.path.join(TMP_DIR, f"thumb_{int(time.time())}.jpg")
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                logger.info(f"[Pipeline] 封面图下载成功: {local_path} ({len(resp.content)} bytes)")
                return local_path
    except Exception as e:
        logger.warning(f"[Pipeline] 封面图下载失败: {e}")
    return ""


async def _extract_frame_from_video(video_url: str) -> str:
    """从对标视频 URL 下载并抽取第一帧作为背景图"""
    if not video_url:
        return ""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(video_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.douyin.com/",
            })
            if resp.status_code != 200 or not resp.content:
                return ""
            tmp_video = os.path.join(TMP_DIR, f"ref_{int(time.time())}.mp4")
            with open(tmp_video, "wb") as f:
                f.write(resp.content)
        # 用 ffmpeg 抽取第一帧
        frame_path = os.path.join(TMP_DIR, f"frame_{int(time.time())}.jpg")
        cmd = [FFMPEG_BIN, "-i", tmp_video, "-vframes", "1", "-q:v", "2",
               "-y", "-hide_banner", "-loglevel", "error", frame_path]
        subprocess.run(cmd, capture_output=True, timeout=30)
        try:
            os.remove(tmp_video)
        except OSError:
            pass
        if os.path.exists(frame_path):
            logger.info(f"[Pipeline] 视频抽帧成功: {frame_path}")
            return frame_path
    except Exception as e:
        logger.warning(f"[Pipeline] 视频抽帧失败: {e}")
    return ""


async def run_full_pipeline(params: Dict[str, Any]) -> Dict[str, Any]:
    """一键生成口播视频全链路

    Args:
        params: {
            video_url: 对标视频链接（可选，与 text 二选一）
            text: 直接提供文案（可选）
            style: 仿写风格
            industry: 行业
            voice_model: 声音模型信息（从 DB 查询或传入）
            digital_human: 数字人模型信息
            enable_subtitle: 是否生成字幕（默认 True）
            enable_bgm: 是否添加 BGM（默认 True）
            enable_cover: 是否生成封面（默认 True）
            bgm_mood: BGM 情绪标签
            skip_rewrite: 是否跳过仿写（直接用原文案）
        }

    Returns:
        {
            original_script, rewritten_script,
            audio_path, video_path, subtitle_path, cover_path,
            title_suggestions, tags, duration, status, steps
        }
    """
    from api.services.ai.script_extractor import extract_script
    from api.services.ai.script_rewriter import rewrite_script
    from api.services.ai.voice_clone_service import synthesize_speech
    from api.services.ai.digital_human_service import generate_talking_video
    from api.services.ai.post_production_service import (
        generate_subtitle, burn_subtitle, add_bgm, generate_cover,
    )

    steps: list[Dict[str, Any]] = []
    start_ts = time.time()

    video_url = params.get("video_url", "")
    text = params.get("text", "")
    style = params.get("style", "")
    industry = params.get("industry", "")
    voice_model = params.get("voice_model", {})
    digital_human = params.get("digital_human", {})
    enable_subtitle = params.get("enable_subtitle", True)
    enable_bgm = params.get("enable_bgm", True)
    enable_cover = params.get("enable_cover", True)
    bgm_mood = params.get("bgm_mood", "default")
    skip_rewrite = params.get("skip_rewrite", False)

    original_script = ""
    rewritten_script = ""
    audio_path = ""
    video_path = ""
    subtitle_path = ""
    cover_path = ""
    title_suggestions: list[str] = []
    tags: list[str] = []
    # 解析服务返回的额外信息（用于无形象照时准备视频背景）
    extract_result: Dict[str, Any] = {}

    try:
        # ===== Step 1: 文案提取 =====
        if video_url and not text:
            steps.append({"step": "extract_script", "status": "running"})
            try:
                extract_result = await extract_script(video_url)
                original_script = extract_result["cleaned_text"]
                if not original_script:
                    original_script = extract_result.get("raw_text", "")
                steps[-1].update({
                    "status": "done",
                    "text_length": len(original_script),
                    "duration": extract_result.get("duration", 0),
                })
                logger.info(f"[Pipeline] Step 1 文案提取完成: {len(original_script)}字")
            except Exception as e:
                steps[-1].update({"status": "failed", "error": str(e)})
                raise RuntimeError(f"文案提取失败: {e}")
        elif text:
            original_script = text
            steps.append({"step": "extract_script", "status": "skipped", "reason": "直接提供文案"})
        else:
            raise ValueError("必须提供 video_url 或 text")

        # ===== Step 2: 文案仿写 =====
        if not skip_rewrite and original_script:
            steps.append({"step": "rewrite", "status": "running"})
            try:
                rewrite_result = await rewrite_script(
                    original_script, style=style, industry=industry
                )
                rewritten_script = rewrite_result.get("rewritten_text", "")
                title_suggestions = rewrite_result.get("title_suggestions", [])
                tags = rewrite_result.get("tags", [])
                steps[-1].update({"status": "done", "text_length": len(rewritten_script)})
                logger.info(f"[Pipeline] Step 2 文案仿写完成: {len(rewritten_script)}字")
            except Exception as e:
                steps[-1].update({"status": "failed", "error": str(e)})
                # 仿写失败不阻断，用原文案
                rewritten_script = original_script
                logger.warning(f"[Pipeline] 仿写失败，使用原文案: {e}")
        else:
            rewritten_script = original_script
            steps.append({"step": "rewrite", "status": "skipped"})

        # ===== Step 3: 声音合成 =====
        if voice_model and rewritten_script:
            steps.append({"step": "synthesize_speech", "status": "running"})
            try:
                audio_path = await synthesize_speech(rewritten_script, voice_model)
                steps[-1].update({"status": "done", "audio_path": audio_path})
                logger.info(f"[Pipeline] Step 3 声音合成完成: {audio_path}")
            except Exception as e:
                steps[-1].update({"status": "failed", "error": str(e)})
                raise RuntimeError(f"声音合成失败: {e}")
        else:
            steps.append({"step": "synthesize_speech", "status": "skipped", "reason": "无声音模型或文案"})

        # ===== Step 4: 字幕生成（在视频生成前生成，便于烧录） =====
        if enable_subtitle and audio_path:
            steps.append({"step": "generate_subtitle", "status": "running"})
            try:
                # 传入仿写文案，按句切分生成字幕（TTS 音频无明显静音，
                # whisper VAD 会把整段识别为 1 条，导致字幕一次性显示全部文案）
                sub_result = await generate_subtitle(audio_path, text=rewritten_script or "")
                subtitle_path = sub_result.get("srt_path", "")
                steps[-1].update({
                    "status": "done" if subtitle_path else "skipped",
                    "subtitle_path": subtitle_path,
                })
                logger.info(f"[Pipeline] Step 4 字幕生成: {subtitle_path or '(空)'}")
            except Exception as e:
                steps[-1].update({"status": "failed", "error": str(e)})
                logger.warning(f"[Pipeline] 字幕生成失败: {e}")

        # ===== Step 5: 数字人视频生成 =====
        if digital_human and audio_path:
            steps.append({"step": "generate_video", "status": "running"})
            try:
                # 无形象照时，按优先级准备背景图（避免黑屏）
                if not digital_human.get("portrait_path"):
                    bg_image = ""
                    # ① 优先用解析服务返回的封面图
                    thumb_url = extract_result.get("thumbnail", "")
                    if thumb_url:
                        bg_image = await _download_thumbnail_to_local(thumb_url)
                    # ② 封面图失败，从对标视频抽帧
                    if not bg_image:
                        ref_video_url = extract_result.get("parsed_video_url", "")
                        if ref_video_url:
                            bg_image = await _extract_frame_from_video(ref_video_url)
                    # ③ 都失败，用默认数字人形象照
                    if not bg_image:
                        default_portrait = os.path.join(os.getcwd(), "data", "default_digital_human.jpg")
                        if os.path.exists(default_portrait):
                            bg_image = default_portrait
                            logger.info(f"[Pipeline] 使用默认数字人形象照: {bg_image}")
                    if bg_image:
                        # 复制字典避免修改原始传入参数
                        digital_human = {**digital_human, "portrait_path": bg_image}
                        logger.info(f"[Pipeline] 背景图准备完成: {bg_image}")
                    else:
                        logger.warning("[Pipeline] 无形象照且无法获取背景图，将生成黑底视频")

                # 降级模式下传入字幕路径，FFmpeg 直接烧录
                video_path = await generate_talking_video(
                    digital_human, audio_path,
                    subtitle_path=subtitle_path if subtitle_path else None,
                )
                steps[-1].update({"status": "done", "video_path": video_path})
                logger.info(f"[Pipeline] Step 5 视频生成完成: {video_path}")
            except Exception as e:
                steps[-1].update({"status": "failed", "error": str(e)})
                raise RuntimeError(f"视频生成失败: {e}")
        else:
            steps.append({"step": "generate_video", "status": "skipped", "reason": "无数字人模型或音频"})

        # ===== Step 6: BGM 混音 =====
        if enable_bgm and video_path:
            steps.append({"step": "add_bgm", "status": "running"})
            try:
                video_path = await add_bgm(video_path, mood=bgm_mood)
                steps[-1].update({"status": "done", "video_path": video_path})
                logger.info(f"[Pipeline] Step 6 BGM 混音完成")
            except Exception as e:
                steps[-1].update({"status": "failed", "error": str(e)})
                logger.warning(f"[Pipeline] BGM 添加失败: {e}")

        # ===== Step 7: 封面生成 =====
        if enable_cover and video_path:
            steps.append({"step": "generate_cover", "status": "running"})
            try:
                cover_title = title_suggestions[0] if title_suggestions else ""
                cover_path = await generate_cover(video_path, title=cover_title)
                steps[-1].update({"status": "done", "cover_path": cover_path})
                logger.info(f"[Pipeline] Step 7 封面生成完成: {cover_path}")
            except Exception as e:
                steps[-1].update({"status": "failed", "error": str(e)})
                logger.warning(f"[Pipeline] 封面生成失败: {e}")

        elapsed = round(time.time() - start_ts, 2)
        logger.info(f"[Pipeline] 全链路完成，耗时 {elapsed}s")

        return {
            "status": "done",
            "original_script": original_script,
            "rewritten_script": rewritten_script,
            "audio_path": audio_path,
            "video_path": video_path,
            "subtitle_path": subtitle_path,
            "cover_path": cover_path,
            "title_suggestions": title_suggestions,
            "tags": tags,
            "elapsed": elapsed,
            "steps": steps,
        }

    except Exception as e:
        logger.error(f"[Pipeline] 全链路失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "original_script": original_script,
            "rewritten_script": rewritten_script,
            "audio_path": audio_path,
            "video_path": video_path,
            "subtitle_path": subtitle_path,
            "cover_path": cover_path,
            "steps": steps,
            "elapsed": round(time.time() - start_ts, 2),
        }
