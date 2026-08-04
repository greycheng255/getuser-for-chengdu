# -*- coding: utf-8 -*-
"""
后期制作服务

视频生成后的后期处理：
1. 自动字幕生成（faster-whisper → SRT）
2. 字幕烧录到视频（FFmpeg subtitles 滤镜）
3. 自动 BGM 混音（FFmpeg amix 滤镜）
4. 视频封面自动生成（FFmpeg 抽帧 + AI 生成）

对标超级IP智能体的"自动添加字幕/BGM/封面"功能。
"""
import asyncio
import logging
import os
import random
import re
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("post_production")

FFMPEG_BIN = "/usr/bin/ffmpeg"
FFPROBE_BIN = "/usr/bin/ffprobe"
TMP_DIR = os.path.join(tempfile.gettempdir(), "talking_head")
os.makedirs(TMP_DIR, exist_ok=True)

# BGM 素材库目录（预置一些免版权 BGM）
BGM_LIBRARY_DIR = os.path.join(os.getcwd(), "data", "bgm_library")
os.makedirs(BGM_LIBRARY_DIR, exist_ok=True)

# 情绪标签 → BGM 文件名前缀映射
MOOD_BGM_MAP = {
    "energetic": ["energetic_01", "energetic_02"],
    "calm": ["calm_01", "calm_02"],
    "uplifting": ["uplifting_01"],
    "serious": ["serious_01"],
    "playful": ["playful_01"],
    "default": ["default_01", "default_02"],
}


def _format_timestamp(seconds: float) -> str:
    """秒 → SRT 时间戳格式 HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _segments_to_srt(segments: List[Dict[str, Any]]) -> str:
    """faster-whisper segments → SRT 字幕格式"""
    srt_lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_timestamp(seg["start"])
        end = _format_timestamp(seg["end"])
        text = seg["text"].strip()
        srt_lines.append(f"{i}")
        srt_lines.append(f"{start} --> {end}")
        srt_lines.append(text)
        srt_lines.append("")  # 空行分隔
    return "\n".join(srt_lines)


def _get_audio_duration(audio_path: str) -> float:
    """用 ffprobe 获取音频时长（秒）"""
    try:
        result = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip()) if result.stdout.strip() else 0.0
    except Exception as e:
        logger.warning(f"[PostProduction] 获取音频时长失败: {e}")
        return 0.0


def _split_text_to_segments(text: str, total_duration: float) -> List[Dict[str, Any]]:
    """把文案按句切分，按字数比例分配时间轴

    TTS 合成的音频无明显静音，faster-whisper 的 VAD 无法切分，
    会把整段音频识别为 1 条 segment，导致字幕一次性显示全部文案。
    此函数按句号/问号/感叹号切分，长句再按逗号切，每句按字数比例分配时间。

    Args:
        text: 仿写后的文案
        total_duration: 音频总时长（秒）

    Returns:
        [{start, end, text}, ...]
    """
    if not text or total_duration <= 0:
        return []

    # 1. 按句末标点（。！？!?）切分，保留标点
    sentences = re.split(r"(?<=[。！？!?])", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    # 2. 长句（>18字）按逗号再切，避免单条字幕过长
    final_sentences: List[str] = []
    for sent in sentences:
        if len(sent) > 18:
            sub_parts = re.split(r"(?<=[，,；;])", sent)
            final_sentences.extend([p.strip() for p in sub_parts if p.strip()])
        else:
            final_sentences.append(sent)

    # 3. 合并过短的句子（<4字）到前一句，避免字幕闪现
    merged: List[str] = []
    for s in final_sentences:
        if merged and len(s) < 4:
            merged[-1] += s
        else:
            merged.append(s)

    if not merged:
        return []

    # 4. 按字数比例分配时间轴
    total_chars = sum(len(s) for s in merged)
    if total_chars == 0:
        return []

    segments: List[Dict[str, Any]] = []
    current_time = 0.0
    for s in merged:
        char_ratio = len(s) / total_chars
        duration = total_duration * char_ratio
        end_time = min(current_time + duration, total_duration)
        segments.append({
            "start": round(current_time, 2),
            "end": round(end_time, 2),
            "text": s,
        })
        current_time = end_time

    return segments


async def generate_subtitle(audio_path: str, text: str = "") -> Dict[str, Any]:
    """从音频生成 SRT 字幕文件

    优先用传入的文案按句切分（适用于 TTS 合成音频，无明显静音），
    无文案时用 faster-whisper 识别（适用于真实人声录音）。

    Args:
        audio_path: 音频文件路径
        text: 仿写后的文案（推荐传入，字幕质量更高）

    Returns:
        {srt_path, segments, duration}
    """
    logger.info(f"[PostProduction] 生成字幕: {audio_path} (text={'有' if text else '无'})")

    # 优先用文案切分（TTS 音频无明显静音，whisper VAD 会把整段识别为 1 条）
    if text:
        duration = _get_audio_duration(audio_path)
        if duration > 0:
            segments = _split_text_to_segments(text, duration)
            if segments:
                srt_content = _segments_to_srt(segments)
                srt_path = os.path.join(TMP_DIR, f"subtitle_{int(time.time())}.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
                logger.info(
                    f"[PostProduction] 字幕(文案切分)生成成功: {srt_path} "
                    f"({len(segments)} 段, duration={duration:.1f}s)"
                )
                return {"srt_path": srt_path, "segments": segments, "duration": duration}

    # 兜底：faster-whisper 识别
    from api.services.ai.script_extractor import _get_whisper_model, _transcribe

    result = await asyncio.to_thread(_transcribe, audio_path)

    if not result["segments"]:
        logger.warning("[PostProduction] 未识别到语音内容，字幕为空")
        return {"srt_path": "", "segments": [], "duration": result["duration"]}

    srt_content = _segments_to_srt(result["segments"])
    srt_path = os.path.join(TMP_DIR, f"subtitle_{int(time.time())}.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    logger.info(f"[PostProduction] 字幕(whisper识别)生成成功: {srt_path} ({len(result['segments'])} 段)")
    return {
        "srt_path": srt_path,
        "segments": result["segments"],
        "duration": result["duration"],
    }


async def burn_subtitle(video_path: str, srt_path: str, output_path: Optional[str] = None) -> str:
    """将字幕烧录到视频（硬编码）

    使用 FFmpeg subtitles 滤镜，指定中文字体（WenQuanYi Zen Hei）和样式：
    白字 + 黑色描边 + 底部居中，确保中文正常显示。
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"视频不存在: {video_path}")
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"字幕文件不存在: {srt_path}")

    if not output_path:
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_subbed{ext}"

    # subtitles 滤镜需要转义路径中的特殊字符
    escaped_srt = srt_path.replace("\\", "\\\\").replace(":", "\\:")
    # force_style 指定中文字体和样式（避免中文显示为方框/乱码）
    # PrimaryColour=&H00FFFFFF 白字, OutlineColour=&H00000000 黑描边
    # Outline=2 描边宽度, Alignment=2 底部居中, MarginV=50 底部边距
    # FontSize=22 字号（适合 720p 竖屏）
    force_style = (
        "FontName=WenQuanYi Zen Hei,"
        "FontSize=22,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BackColour=&H80000000,"
        "Bold=1,"
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=50"
    )
    vf = f"subtitles='{escaped_srt}':force_style='{force_style}'"

    cmd = [
        FFMPEG_BIN,
        "-i", video_path,
        "-vf", vf,
        "-c:a", "copy",
        "-y", "-hide_banner", "-loglevel", "error",
        output_path,
    ]
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 字幕烧录失败: {result.stderr[:300]}")
    except Exception as e:
        raise RuntimeError(f"FFmpeg 字幕烧录异常: {e}")

    logger.info(f"[PostProduction] 字幕烧录成功: {output_path}")
    return output_path


async def add_bgm(
    video_path: str,
    mood: str = "",
    bgm_volume_db: float = -15.0,
    voice_volume_db: float = -1.0,
    output_path: Optional[str] = None,
) -> str:
    """为视频添加背景音乐

    Args:
        video_path: 输入视频
        mood: 情绪标签（energetic/calm/uplifting/serious/playful）
        bgm_volume_db: BGM 音量（dB，默认 -15dB 低于人声）
        voice_volume_db: 人声音量（dB，默认 -1dB）
        output_path: 输出路径
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"视频不存在: {video_path}")

    if not output_path:
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_bgm{ext}"

    # 从 BGM 库中选择
    bgm_file = _select_bgm(mood)
    if not bgm_file:
        logger.warning("[PostProduction] BGM 库为空，跳过 BGM 添加")
        return video_path  # 返回原视频

    # 获取视频时长
    duration = await _get_video_duration(video_path)

    # FFmpeg 混音：人声 + BGM
    # BGM 循环到视频时长，然后混音
    cmd = [
        FFMPEG_BIN,
        "-i", video_path,
        "-stream_loop", "-1", "-i", bgm_file,  # BGM 循环
        "-filter_complex",
        f"[0:a]volume={voice_volume_db}dB[voice];"
        f"[1:a]volume={bgm_volume_db}dB,atrim=duration={duration}[bgm];"
        f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-y", "-hide_banner", "-loglevel", "error",
        output_path,
    ]
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            logger.warning(f"[PostProduction] BGM 混音失败: {result.stderr[:200]}")
            return video_path  # 返回原视频
    except Exception as e:
        logger.warning(f"[PostProduction] BGM 混音异常: {e}")
        return video_path

    logger.info(f"[PostProduction] BGM 添加成功: {output_path} (bgm={os.path.basename(bgm_file)})")
    return output_path


async def generate_cover(
    video_path: str,
    title: str = "",
    output_path: Optional[str] = None,
) -> str:
    """从视频生成封面图

    策略：从视频中抽取关键帧 → 选取最清晰的帧 → 叠加标题文字
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"视频不存在: {video_path}")

    if not output_path:
        output_path = os.path.join(TMP_DIR, f"cover_{int(time.time())}.jpg")

    # 从视频 1/4 处抽帧（开头通常是引入部分，1/4 处更有代表性）
    duration = await _get_video_duration(video_path)
    timestamp = duration / 4 if duration > 4 else 1.0

    cmd = [
        FFMPEG_BIN,
        "-ss", str(timestamp),
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        "-y", "-hide_banner", "-loglevel", "error",
        output_path,
    ]
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0 or not os.path.exists(output_path):
            raise RuntimeError(f"FFmpeg 抽帧失败: {result.stderr[:200]}")
    except Exception as e:
        raise RuntimeError(f"封面生成失败: {e}")

    # 如有标题，用 FFmpeg drawtext 叠加文字
    if title:
        title_escaped = title.replace("'", "\\'").replace(":", "\\:")
        # 限制标题长度
        if len(title) > 40:
            title_escaped = title[:40].replace("'", "\\'").replace(":", "\\:")

        text_video = output_path.replace(".jpg", "_text.jpg")
        cmd = [
            FFMPEG_BIN,
            "-i", output_path,
            "-vf",
            f"drawtext=text='{title_escaped}':"
            f"fontcolor=white:fontsize=36:"
            f"x=(w-text_w)/2:y=h-80:"
            f"box=1:boxcolor=black@0.5:boxborderw=10",
            "-q:v", "2",
            "-y", "-hide_banner", "-loglevel", "error",
            text_video,
        ]
        try:
            await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=30
            )
            if os.path.exists(text_video):
                os.replace(text_video, output_path)
        except Exception as e:
            logger.warning(f"[PostProduction] 封面文字叠加失败: {e}")

    logger.info(f"[PostProduction] 封面生成成功: {output_path}")
    return output_path


def _select_bgm(mood: str) -> Optional[str]:
    """从 BGM 库中按情绪标签选择 BGM"""
    # 查找匹配的 BGM 文件
    candidates = MOOD_BGM_MAP.get(mood, MOOD_BGM_MAP["default"])
    for name in candidates:
        for ext in (".mp3", ".m4a", ".aac", ".wav"):
            path = os.path.join(BGM_LIBRARY_DIR, name + ext)
            if os.path.exists(path):
                return path

    # 回退：BGM 库中任意文件
    all_bgm = []
    for ext in (".mp3", ".m4a", ".aac", ".wav"):
        all_bgm.extend(
            os.path.join(BGM_LIBRARY_DIR, f)
            for f in os.listdir(BGM_LIBRARY_DIR)
            if f.endswith(ext)
        )
    if all_bgm:
        return random.choice(all_bgm)
    return None


async def _get_video_duration(video_path: str) -> float:
    """获取视频时长"""
    cmd = [FFMPEG_BIN, "-i", video_path, "-hide_banner"]
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=10
        )
        import re
        match = re.search(r"Duration:\s(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 30.0
