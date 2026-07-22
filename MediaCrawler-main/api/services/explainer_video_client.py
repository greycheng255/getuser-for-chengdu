# -*- coding: utf-8 -*-
"""Generate X workbench explainer videos through AI6700."""
from __future__ import annotations

import json
from typing import Any, Iterable

import httpx

from api.services.ai6700_client import (
    AI6700BalanceError,
    ai6700_error_message,
    ai6700_headers,
    ensure_ai6700_balance,
)
from config.onellm_config import load_onellm_config


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

目标：把下面的视频拆解内容压缩成一个清晰、有吸引力的解说片段。画面主体稳定，镜头运动自然，字幕简洁清楚；生成同步的自然中文旁白和轻量环境音。不要展示平台水印、UI 或无关文字。

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
) -> dict[str, Any]:
    """Check balance, submit one AI6700 media task, and return its task id."""
    settings = load_onellm_config()
    model = choose_seedance_model(image_urls, video_urls)
    is_reference_model = model == settings.reference_video_model
    model_name = (
        "Seedance 2.0 参考生"
        if is_reference_model
        else "Seedance 2.0 首尾帧"
    )
    params: dict[str, Any] = {
        "version": "Mini",
        "duration": "10",
        "aspect_ratio": "9:16",
        "resolution": "720p",
    }
    reference_images = image_urls[:9] if is_reference_model else image_urls[:2]
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
