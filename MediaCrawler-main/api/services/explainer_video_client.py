# -*- coding: utf-8 -*-
"""Generate X workbench explainer videos through AI6700."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from typing import Any, Iterable, Optional

import httpx

from api.services.ai6700_client import (
    AI6700BalanceError,
    ai6700_error_message,
    ai6700_headers,
    ensure_ai6700_balance,
)
from config.onellm_config import load_onellm_config

logger = logging.getLogger("explainer_video_client")


class AI6700VideoError(RuntimeError):
    """AI6700 media API request failed."""

    def __init__(
        self,
        message: str,
        status_code: int = 502,
        *,
        submission_uncertain: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.submission_uncertain = submission_uncertain


def normalize_media_urls(value: Any) -> list[str]:
    """把数据库中的 JSON、列表或分隔字符串统一为公网 URL 列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values: Iterable[Any] = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, list):
            values = decoded
        elif isinstance(decoded, str):
            values = [decoded]
        else:
            values = text.replace("\n", ",").split(",")
    else:
        values = [value]

    result: list[str] = []
    for item in values:
        url = str(item or "").strip()
        if url.startswith(("http://", "https://")) and url not in result:
            result.append(url)
    return result


def choose_seedance_model(image_urls: list[str], video_urls: list[str]) -> str:
    """有图片时使用参考生模型；当前两个配置模型均不接收视频引用。"""
    del video_urls
    settings = load_onellm_config()
    return settings.reference_video_model if image_urls else settings.video_model


async def extract_video_frames(video_url: str, max_frames: int = 3) -> list[str]:
    """从视频URL中提取关键帧作为参考图片，上传到AI6700获取可访问URL。"""
    frames = []
    try:
        video_path = None
        
        if video_url.startswith("https://x.com/") or video_url.startswith("https://twitter.com/"):
            try:
                import yt_dlp
                ydl_opts = {
                    'format': 'mp4',
                    'outtmpl': '/tmp/trae_video_%(id)s.%(ext)s',
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=True)
                    video_path = ydl.prepare_filename(info)
            except Exception as e:
                logger.warning(f"yt-dlp failed: {e}")
                return frames
        else:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, verify=False) as client:
                response = await client.get(video_url, timeout=60.0)
                if response.status_code != 200:
                    logger.warning(f"Failed to download video: HTTP {response.status_code}")
                    return frames
                
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                    video_path = f.name
                    f.write(response.content)
        
        output_dir = os.path.join(os.getcwd(), "data", "video_frames")
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-i", video_path,
                    "-vf", "fps=1/3",
                    "-q:v", "2",
                    f"{output_dir}/frame_%03d.jpg",
                    "-hide_banner", "-loglevel", "error"
                ],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                settings = load_onellm_config()
                headers = ai6700_headers(settings)
                
                for i in range(1, max_frames + 1):
                    frame_path = f"{output_dir}/frame_{i:03d}.jpg"
                    if os.path.exists(frame_path):
                        with open(frame_path, "rb") as f:
                            frame_data = f.read()
                        
                        try:
                            async with httpx.AsyncClient(timeout=30.0) as upload_client:
                                upload_resp = await upload_client.post(
                                    settings.endpoint("media/upload"),
                                    headers={"Authorization": headers["Authorization"]},
                                    files={"file": ("frame.jpg", frame_data, "image/jpeg")},
                                )
                                if upload_resp.status_code == 200:
                                    upload_result = upload_resp.json()
                                    image_url = upload_result.get("url") or upload_result.get("data", {}).get("url")
                                    if image_url:
                                        frames.append(image_url)
                        except Exception as upload_e:
                            logger.warning(f"Failed to upload frame {i}: {upload_e}")
        except Exception as e:
            logger.warning(f"FFmpeg frame extraction failed: {e}")
        
        if video_path and os.path.exists(video_path):
            os.unlink(video_path)
        
    except Exception as e:
        logger.warning(f"Video frame extraction error: {e}")
    
    return frames


def build_explainer_prompt(
    *,
    post_content: str,
    script: str,
    storyboards: list[str],
    key_points: list[str],
) -> str:
    """把拆解结果整理成 Seedance 可直接消费的有声视频提示词。"""
    storyboard_text = "\n".join(
        f"{index}. {item}" for index, item in enumerate(storyboards, 1)
    ) or "无明确分镜，请根据脚本自动设计镜头。"
    key_point_text = "\n".join(
        f"- {item}" for item in key_points
    ) or "请提炼一个最重要的信息点。"

    return f"""请生成一段 10 秒、9:16 竖屏、带中文解说的社交媒体短视频。

目标：把下面的视频拆解内容压缩成一个清晰、有吸引力的解说片段。画面主体稳定，镜头运动自然，字幕简洁清楚；生成同步的自然中文旁白和轻量环境音。

严格禁止：
- 不要展示平台水印、UI 或无关文字
- 不要生成任何乱码、无意义文字或胡言乱语
- 不要在画面底部生成英文或其他语言的无意义段落
- 字幕只保留核心关键词，不要生成多余文本

原帖内容：
{post_content.strip() or '无'}

脚本分析：
{script.strip() or '无'}

分镜参考：
{storyboard_text}

关键要点：
{key_point_text}

请围绕核心信息设计适合手机观看的竖屏镜头和中文解说，保证 10 秒内内容完整。"""


def _headers() -> dict[str, str]:
    try:
        return ai6700_headers(load_onellm_config())
    except AI6700BalanceError as exc:
        raise AI6700VideoError(str(exc), exc.status_code) from exc


async def submit_explainer_video(
    *,
    prompt: str,
    image_urls: list[str],
    video_urls: list[str],
    duration: int = 10,
    resolution: str = "720p",
    aspect_ratio: str = "9:16",
) -> dict[str, Any]:
    """Check balance, submit one AI6700 media task, and return its task id.

    Args:
        prompt: 视频生成提示词
        image_urls: 参考图片 URL 列表
        video_urls: 原视频 URL 列表（用于抽帧作为参考图）
        duration: 时长(秒)，传给 AI6700 params.duration
        resolution: 分辨率 480p/720p/1080p
        aspect_ratio: 宽高比 9:16/16:9/1:1/4:3
    """
    settings = load_onellm_config()

    all_image_urls = list(image_urls)

    if video_urls:
        for video_url in video_urls[:3]:
            try:
                frames = await extract_video_frames(video_url, max_frames=3)
                all_image_urls.extend(frames)
            except Exception as e:
                logger.warning(f"Failed to extract frames from video: {e}")

    model = choose_seedance_model(all_image_urls, video_urls)
    is_reference_model = model == settings.reference_video_model
    model_name = (
        "Seedance 2.0 参考生"
        if is_reference_model
        else "Seedance 2.0 首尾帧"
    )

    # AI6700 params 接收用户配置的 duration/resolution/aspect_ratio
    # （历史 bug：硬编码 5/480p/9:16 导致用户配置的 30s/1080p 被丢弃）
    # duration 取整数秒；AI6700 要求字符串
    params: dict[str, Any] = {
        "version": "Mini",
        "duration": str(int(duration)) if duration else "10",
        "aspect_ratio": aspect_ratio or "9:16",
        "resolution": resolution or "720p",
    }
    reference_images = all_image_urls[:9] if is_reference_model else all_image_urls[:2]
    if reference_images:
        params["images"] = reference_images
    body = {
        "model": model,
        "prompt": prompt,
        "params": params,
    }

    try:
        await ensure_ai6700_balance(settings)
    except AI6700BalanceError as exc:
        raise AI6700VideoError(str(exc), exc.status_code) from exc

    try:
        # AI6700 does not document an upstream idempotency key. Never retry
        # this paid POST at transport level; an interrupted response is marked
        # as uncertain by the caller to avoid accidental duplicate billing.
        async with httpx.AsyncClient(
            timeout=60.0,
            transport=httpx.AsyncHTTPTransport(retries=0),
            follow_redirects=False,
        ) as client:
            response = await client.post(
                settings.endpoint("media/generate"),
                headers=_headers(),
                json=body,
            )
    except httpx.HTTPError as exc:
        raise AI6700VideoError(
            f"AI6700 视频任务提交结果未知: {exc}",
            submission_uncertain=True,
        ) from exc

    if response.status_code >= 400:
        status_code = 503 if response.status_code == 401 else response.status_code
        raise AI6700VideoError(
            f"AI6700 视频任务提交失败: {ai6700_error_message(response)}",
            status_code,
            submission_uncertain=response.status_code >= 500,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise AI6700VideoError(
            "AI6700 视频任务响应不是有效 JSON",
            submission_uncertain=True,
        ) from exc
    if not isinstance(payload, dict):
        raise AI6700VideoError(
            "AI6700 视频任务响应格式异常",
            submission_uncertain=True,
        )
    code = payload.get("code")
    if code not in (None, 200, "200"):
        try:
            status_code = int(code)
        except (TypeError, ValueError):
            status_code = 502
        if not 400 <= status_code <= 599:
            status_code = 502
        raise AI6700VideoError(
            f"AI6700 视频任务提交失败: {payload.get('msg') or payload}",
            503 if status_code == 401 else status_code,
            submission_uncertain=status_code >= 500,
        )

    data = payload.get("data")
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not task_id:
        raise AI6700VideoError(
            "AI6700 返回结果中缺少任务 ID",
            submission_uncertain=True,
        )
    return {
        "task_id": str(task_id),
        "status": "pending",
        "model": model,
        "model_name": model_name,
        "reference_count": len(reference_images),
    }


class ExplainerVideoClient:
    """视频生成客户端（封装 submit + poll 一体化流程）

    供 prompt_storyboard_pipeline / batch_video_generator 调用，
    统一暴露 ``generate_video()`` 同步接口（内部异步提交 + 轮询至完成）。
    """

    def __init__(self) -> None:
        self._last_task_id: Optional[str] = None
        self._last_status: dict[str, Any] = {}

    async def submit(
        self,
        *,
        prompt: str,
        image_urls: Optional[list[str]] = None,
        video_urls: Optional[list[str]] = None,
        duration: int = 10,
        resolution: str = "720p",
        aspect_ratio: str = "9:16",
    ) -> dict[str, Any]:
        """提交视频生成任务，返回包含 task_id 的提交结果"""
        result = await submit_explainer_video(
            prompt=prompt,
            image_urls=list(image_urls or []),
            video_urls=list(video_urls or []),
            duration=duration,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
        )
        self._last_task_id = result.get("task_id")
        return result

    async def poll(self, task_id: str, timeout: float = 600.0, interval: float = 5.0) -> dict[str, Any]:
        """轮询任务直至完成或超时"""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = await get_explainer_video_status(task_id)
            self._last_status = status
            if status.get("is_final") or status.get("status") in {"success", "failed"}:
                return status
            await asyncio.sleep(interval)
        return self._last_status or {"status": "timeout", "error": "轮询超时"}

    async def generate_video(
        self,
        *,
        prompt: str,
        duration: int = 10,
        resolution: str = "720p",
        aspect_ratio: str = "9:16",
        voice_timbre: Optional[str] = None,
        visual_style: Optional[str] = None,
        image_urls: Optional[list[str]] = None,
        video_urls: Optional[list[str]] = None,
        timeout: float = 600.0,
    ) -> Optional[str]:
        """提交并轮询视频生成，返回生成视频的 URL

        Args:
            prompt: 视频生成提示词
            duration: 时长(秒)，传给 AI6700 params.duration
            resolution: 分辨率 480p/720p/1080p
            aspect_ratio: 宽高比 9:16/16:9/1:1
            voice_timbre/visual_style: 由 prompt 承载（仅记录日志）
            image_urls/video_urls: 参考图片/原视频 URL
            timeout: 轮询超时秒数

        Returns:
            生成视频的 URL，失败返回 None
        """
        # voice_timbre / visual_style 由 prompt 承载（AI6700 不接收独立字段）
        # 但 duration / resolution / aspect_ratio 必须传给 AI6700 params
        if voice_timbre or visual_style:
            logger.info(
                f"[ExplainerVideoClient] voice_timbre={voice_timbre} "
                f"visual_style={visual_style} (由 prompt 承载)"
            )
        try:
            submit_result = await self.submit(
                prompt=prompt,
                image_urls=image_urls,
                video_urls=video_urls,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
            )
            task_id = submit_result.get("task_id")
            if not task_id:
                logger.warning(f"[ExplainerVideoClient] 提交失败: {submit_result}")
                return None

            final_status = await self.poll(task_id, timeout=timeout)
            if final_status.get("status") == "success":
                return final_status.get("result_url") or None
            logger.warning(
                f"[ExplainerVideoClient] 任务 {task_id} 未成功: {final_status.get('error') or final_status}"
            )
            return None
        except Exception as e:
            logger.warning(f"[ExplainerVideoClient] generate_video 异常: {e}")
            return None


async def get_explainer_video_status(task_id: str) -> dict[str, Any]:
    """Read AI6700 task-status and normalize it for the frontend."""
    settings = load_onellm_config()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                settings.endpoint("skills/task-status"),
                headers=_headers(),
                params={"task_id": task_id},
            )
    except httpx.HTTPError as exc:
        raise AI6700VideoError(f"AI6700 视频状态查询失败: {exc}") from exc

    if response.status_code >= 400:
        status_code = 503 if response.status_code == 401 else response.status_code
        raise AI6700VideoError(
            f"AI6700 视频状态查询失败: {ai6700_error_message(response)}",
            status_code,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AI6700VideoError("AI6700 视频状态响应不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise AI6700VideoError("AI6700 视频状态响应格式异常")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    state = str(data.get("state") or "").lower()
    status_text = str(data.get("status") or "")
    status_group = str(data.get("status_group") or "")
    if not state:
        state = {
            "等待中": "pending",
            "处理中": "running",
            "已完成": "success",
            "失败": "failed",
        }.get(status_group, "pending")
        if "失败" in status_text:
            state = "failed"
        elif "完成" in status_text:
            state = "success"
    is_final = bool(data.get("is_final")) or state in {"success", "failed"}

    progress_text = str(data.get("progress") or "0").strip().rstrip("%")
    try:
        progress = int(float(progress_text))
    except ValueError:
        progress = 100 if is_final else (50 if state == "running" else 0)

    error_value = data.get("error")
    if isinstance(error_value, dict):
        error = str(error_value.get("message") or error_value.get("code") or "")
    else:
        error = str(error_value or "")
    if state == "failed" and not error:
        error = status_text or "AI6700 视频生成失败"

    return {
        "task_id": str(data.get("task_id") or task_id),
        "status": state,
        "is_final": is_final,
        "progress": max(0, min(100, progress)),
        "current_step": status_text or state,
        "result_url": str(data.get("result_url") or ""),
        "result_reference": "",
        "error": error,
        "cost": data.get("cost", 0),
        "refunded": bool(data.get("refunded", False)),
        "refunded_amount": data.get("refunded_amount", 0),
        "channel_group": str(data.get("channel_group") or ""),
    }
