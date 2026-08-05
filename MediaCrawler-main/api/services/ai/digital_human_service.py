# -*- coding: utf-8 -*-
"""
数字人口播视频生成服务

真实模式：对接 HeyGem API，音频+形象照 → 唇形同步口播视频
降级模式：无 HEYGEM_API_URL 时，用 FFmpeg 将形象照+音频合成图片视频

对标超级IP智能体的"数字人口播生成"功能。
"""
import asyncio
import logging
import os
import subprocess
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("digital_human_service")

FFMPEG_BIN = "/usr/bin/ffmpeg"
TMP_DIR = "/tmp/talking_head"
os.makedirs(TMP_DIR, exist_ok=True)

# 环境变量
HEYGEM_API_URL = os.getenv("HEYGEM_API_URL", "")
HEYGEM_API_KEY = os.getenv("HEYGEM_API_KEY", "")


def is_heygem_available() -> bool:
    """检查 HeyGem API 是否可用"""
    return bool(HEYGEM_API_URL)


async def create_digital_human(portrait_path: str, name: str) -> Dict[str, Any]:
    """创建数字人形象

    真实模式：上传形象照到 HeyGem → 返回数字人模型 ID
    降级模式：记录图片路径，后续用 FFmpeg 生成图片视频
    """
    if not os.path.exists(portrait_path):
        raise FileNotFoundError(f"形象照不存在: {portrait_path}")

    if is_heygem_available():
        # ===== HeyGem 真实模式 =====
        logger.info(f"[DigitalHuman] HeyGem 模式: 上传形象照 {portrait_path}")
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(portrait_path, "rb") as f:
                    resp = await client.post(
                        f"{HEYGEM_API_URL}/api/digital-human/create",
                        headers={"Authorization": f"Bearer {HEYGEM_API_KEY}"} if HEYGEM_API_KEY else {},
                        files={"portrait": f},
                        data={"name": name},
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    model_id = data.get("model_id", data.get("id", ""))
                    logger.info(f"[DigitalHuman] HeyGem 创建成功: model_id={model_id}")
                    return {
                        "provider": "heygem",
                        "provider_model_id": model_id,
                        "status": "ready",
                        "name": name,
                    }
                else:
                    logger.warning(f"[DigitalHuman] HeyGem 创建失败: {resp.status_code}")
        except Exception as e:
            logger.warning(f"[DigitalHuman] HeyGem 异常，降级到图片视频: {e}")

    # ===== 降级模式 =====
    logger.info(f"[DigitalHuman] 降级模式(图片视频): 记录形象照路径")
    return {
        "provider": "image_video",
        "provider_model_id": "",
        "portrait_path": portrait_path,
        "status": "ready",
        "name": name,
        "note": "未配置 HEYGEM_API_URL，使用图片+音频合成视频(无唇形同步)",
    }


async def generate_talking_video(
    digital_human: Dict[str, Any],
    audio_path: str,
    output_path: Optional[str] = None,
    subtitle_path: Optional[str] = None,
) -> str:
    """生成口播视频

    真实模式：HeyGem API 音频+形象 → 唇形同步视频
    降级模式：FFmpeg 形象照+音频 → 图片视频（可加字幕）

    Args:
        digital_human: 数字人模型信息
        audio_path: 口播音频路径
        output_path: 输出视频路径
        subtitle_path: SRT 字幕文件路径（可选，降级模式会烧录到视频）

    Returns:
        视频文件路径
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    if not output_path:
        output_path = os.path.join(TMP_DIR, f"dh_video_{int(time.time())}.mp4")

    provider = digital_human.get("provider", "image_video")

    if provider == "heygem" and is_heygem_available():
        # ===== HeyGem 真实模式 =====
        model_id = digital_human.get("provider_model_id", "")
        if model_id:
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    with open(audio_path, "rb") as f:
                        resp = await client.post(
                            f"{HEYGEM_API_URL}/api/digital-human/generate",
                            headers={"Authorization": f"Bearer {HEYGEM_API_KEY}"} if HEYGEM_API_KEY else {},
                            files={"audio": f},
                            data={"model_id": model_id},
                        )
                    if resp.status_code == 200:
                        data = resp.json()
                        video_url = data.get("video_url", "")
                        if video_url:
                            # 下载视频
                            video_resp = await client.get(video_url)
                            with open(output_path, "wb") as f:
                                f.write(video_resp.content)
                            logger.info(f"[DigitalHuman] HeyGem 视频生成成功: {output_path}")
                            return output_path
            except Exception as e:
                logger.warning(f"[DigitalHuman] HeyGem 生成失败，降级到图片视频: {e}")

    # ===== DashScope wan2.2-s2v 真实数字人模式 =====
    portrait_path = digital_human.get("portrait_path", "")
    if portrait_path and os.path.exists(portrait_path):
        s2v_audio = None  # 临时截取的音频文件，用完需清理
        try:
            from api.services.ai.dashscope_helper import (
                is_dashscope_available, generate_digital_human_video,
            )
            if is_dashscope_available():
                logger.info(f"[DigitalHuman] DashScope wan2.2-s2v 真实数字人模式: portrait={portrait_path}")

                # wan2.2-s2v 要求音频 <20 秒，超长音频截取前 19 秒
                s2v_audio = audio_path
                audio_duration = await _get_audio_duration(audio_path)
                subtitle_truncated = False  # 标记字幕是否需要截取
                if audio_duration > 19.5:
                    s2v_audio = audio_path.replace(".mp3", "_s2v.mp3")
                    await asyncio.to_thread(
                        subprocess.run,
                        [FFMPEG_BIN, "-i", audio_path, "-t", "19", "-y",
                         "-hide_banner", "-loglevel", "error", s2v_audio],
                        capture_output=True, text=True, timeout=30,
                    )
                    logger.info(f"[DigitalHuman] 音频截取前19秒: {audio_duration:.1f}s → 19s ({s2v_audio})")
                    subtitle_truncated = True

                # 调用 DashScope 生成数字人视频
                result = await generate_digital_human_video(
                    portrait_path=portrait_path,
                    audio_path=s2v_audio,
                    output_path=output_path.replace(".mp4", "_raw.mp4"),
                    resolution="480P",
                )
                raw_video = result["video_path"]

                # 烧录字幕（如有）— DashScope 模式下字幕需要截取前 19 秒部分
                if subtitle_path and os.path.exists(subtitle_path):
                    from api.services.ai.post_production_service import burn_subtitle as _burn_sub
                    # 如果音频被截取了，字幕也要截取前 19 秒
                    if subtitle_truncated:
                        truncated_srt = subtitle_path.replace(".srt", "_19s.srt")
                        _truncate_srt(subtitle_path, truncated_srt, max_seconds=19.0)
                        subtitle_to_use = truncated_srt
                    else:
                        subtitle_to_use = subtitle_path
                    try:
                        await _burn_sub(raw_video, subtitle_to_use, output_path=output_path)
                        os.remove(raw_video)
                        # 清理截取的字幕临时文件
                        if subtitle_truncated and os.path.exists(truncated_srt):
                            os.remove(truncated_srt)
                    except Exception as e:
                        logger.warning(f"[DigitalHuman] 字幕烧录失败，用无字幕视频: {e}")
                        os.rename(raw_video, output_path)
                        if subtitle_truncated and os.path.exists(truncated_srt):
                            os.remove(truncated_srt)
                else:
                    os.rename(raw_video, output_path)

                # 清理截取的音频临时文件
                if s2v_audio and s2v_audio != audio_path and os.path.exists(s2v_audio):
                    os.remove(s2v_audio)

                logger.info(f"[DigitalHuman] DashScope 数字人视频生成成功: {output_path}")
                return output_path
        except Exception as e:
            logger.warning(f"[DigitalHuman] DashScope 生成失败，降级到图片视频: {e}")
            # 清理截取的音频临时文件
            if s2v_audio and s2v_audio != audio_path and os.path.exists(s2v_audio):
                try:
                    os.remove(s2v_audio)
                except Exception:
                    pass

    # ===== 降级模式：FFmpeg 图片+音频 → 视频 =====
    if not portrait_path or not os.path.exists(portrait_path):
        # 无形象照，生成纯黑背景视频
        portrait_path = None
        logger.warning("[DigitalHuman] 无形象照，生成纯音频视频(黑底)")

    logger.info(f"[DigitalHuman] 降级模式: 图片+音频→视频 audio={audio_path}")

    # 获取音频时长
    duration = await _get_audio_duration(audio_path)

    # 构建 FFmpeg 命令
    if portrait_path:
        # 图片+音频 → 竖屏视频（scale+crop 确保图片适配 720x1280）
        # force_original_aspect_ratio=increase: 按比例放大到完全覆盖目标尺寸
        # crop=720:1280: 裁剪中间部分，避免变形
        vf = (
            "scale=720:1280:force_original_aspect_ratio=increase,"
            "crop=720:1280,"
            "format=yuv420p"
        )
        cmd = [
            FFMPEG_BIN,
            "-loop", "1",
            "-i", portrait_path,
            "-i", audio_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(duration),
            "-y", "-hide_banner", "-loglevel", "error",
        ]
    else:
        # 纯音频 → 竖屏黑底视频
        cmd = [
            FFMPEG_BIN,
            "-f", "lavfi",
            "-i", f"color=c=black:s=720x1280:d={duration}",
            "-i", audio_path,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-y", "-hide_banner", "-loglevel", "error",
        ]

    # 如有字幕，烧录到视频
    if subtitle_path and os.path.exists(subtitle_path):
        # 先生成无字幕视频，再烧录字幕（用 post_production_service 的 burn_subtitle）
        temp_video = output_path.replace(".mp4", "_nosub.mp4")
        cmd.extend([temp_video])
        try:
            await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=120)
        except Exception as e:
            raise RuntimeError(f"FFmpeg 视频生成失败: {e}")

        # 烧录字幕（复用 post_production_service 的中文字体样式）
        from api.services.ai.post_production_service import burn_subtitle as _burn_sub
        try:
            burned = await _burn_sub(temp_video, subtitle_path, output_path=output_path)
            os.remove(temp_video)
        except Exception as e:
            # 字幕烧录失败，用无字幕视频兜底
            logger.warning(f"[DigitalHuman] 字幕烧录失败，用无字幕视频: {e}")
            os.rename(temp_video, output_path)
    else:
        cmd.extend([output_path])
        try:
            await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=120)
        except Exception as e:
            raise RuntimeError(f"FFmpeg 视频生成失败: {e}")

    if not os.path.exists(output_path):
        raise RuntimeError("视频生成失败: 输出文件不存在")

    logger.info(f"[DigitalHuman] 图片视频生成成功: {output_path}")
    return output_path


async def _get_audio_duration(audio_path: str) -> float:
    """获取音频时长（秒）"""
    cmd = [
        FFMPEG_BIN,
        "-i", audio_path,
        "-hide_banner",
    ]
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=10
        )
        # FFmpeg 输出在 stderr 中，解析 Duration: 00:01:23.45
        import re
        match = re.search(r"Duration:\s(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 30.0  # 默认 30 秒


def _truncate_srt(srt_path: str, output_path: str, max_seconds: float = 19.0) -> None:
    """截取 SRT 字幕文件的前 max_seconds 秒部分

    DashScope wan2.2-s2v 限制音频 <20 秒，生成的视频也只有 <20 秒。
    但字幕是基于完整音频生成的，需要截取匹配视频时长的部分。
    """
    import re

    def parse_ts(ts: str) -> float:
        """SRT 时间戳 HH:MM:SS,mmm → 秒"""
        m = re.match(r"(\d+):(\d+):(\d+),(\d+)", ts.strip())
        if not m:
            return 0.0
        h, mi, s, ms = m.groups()
        return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
        blocks = content.strip().split("\n\n")
        truncated_blocks = []
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue
            # 解析时间轴行: 00:00:01,234 --> 00:00:05,678
            ts_line = lines[1]
            ts_match = re.match(
                r"(\d+:\d+:\d+,\d+)\s*-->\s*(\d+:\d+:\d+,\d+)", ts_line
            )
            if not ts_match:
                continue
            start = parse_ts(ts_match.group(1))
            end = parse_ts(ts_match.group(2))
            if start >= max_seconds:
                break  # 超过截止时间，停止
            if end > max_seconds:
                end = max_seconds  # 截断结束时间
            # 格式化回 SRT 时间戳
            def fmt_ts(sec: float) -> str:
                h = int(sec // 3600)
                m = int((sec % 3600) // 60)
                s = int(sec % 60)
                ms = int((sec % 1) * 1000)
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
            lines[1] = f"{fmt_ts(start)} --> {fmt_ts(end)}"
            truncated_blocks.append("\n".join(lines))
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(truncated_blocks) + "\n")
        logger.info(f"[DigitalHuman] 字幕截取前 {max_seconds}s: {len(truncated_blocks)} 段")
    except Exception as e:
        logger.warning(f"[DigitalHuman] 字幕截取失败，用原字幕: {e}")
        import shutil
        shutil.copy2(srt_path, output_path)
