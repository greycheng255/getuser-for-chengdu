# -*- coding: utf-8 -*-
"""用 OpenNotebook Agent API 生成 X 工作台解说视频。"""
from __future__ import annotations

import json
import os
from typing import Any, Iterable

import httpx

from api.services.opennotebook_oauth import (
    OpenNotebookCredentials,
    OpenNotebookOAuthError,
    oauth_provider_config,
    validate_service_url,
)


TEXT_VIDEO_MODEL = "kwvideo-v2"
REFERENCE_VIDEO_MODEL = "kwvideo-v2-ref"


class AgentVideoError(RuntimeError):
    """Agent API 请求失败。"""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


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
    """有参考媒体使用参考生，否则使用首尾帧模型的文生视频模式。"""
    return REFERENCE_VIDEO_MODEL if image_urls or video_urls else TEXT_VIDEO_MODEL


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

    return f"""请生成一段 4 秒、16:9、带中文解说的社交媒体短视频预览。

目标：把下面的视频拆解内容压缩成一个清晰、有吸引力的解说片段。画面主体稳定，镜头运动自然，字幕简洁清楚；生成同步的自然中文旁白和轻量环境音。不要展示平台水印、UI 或无关文字。

原帖内容：
{post_content.strip() or '无'}

脚本分析：
{script.strip() or '无'}

分镜参考：
{storyboard_text}

关键要点：
{key_point_text}

请优先呈现最核心的一个画面和一句中文解说，保证 4 秒内信息完整。"""


async def _agent_api_url() -> str:
    """显式旧配置优先；新配置从 OpenNotebook Discovery 获取。"""
    api_url = os.getenv("AGENT_API_URL", "").strip().rstrip("/")
    try:
        if api_url:
            return validate_service_url("AGENT_API_URL", api_url, base_url=True)
        return (await oauth_provider_config())["agent_endpoint"]
    except OpenNotebookOAuthError as exc:
        raise AgentVideoError(str(exc), 503) from exc


def _headers(
    credentials: OpenNotebookCredentials,
    *,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"{credentials.token_type} {credentials.access_token}",
        "Content-Type": "application/json",
    }
    if credentials.tenant_id:
        headers["X-Tenant-ID"] = credentials.tenant_id
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500] or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("code") or detail)
        if detail:
            return str(detail)
    return str(payload)[:500]


async def submit_explainer_video(
    *,
    credentials: OpenNotebookCredentials,
    prompt: str,
    image_urls: list[str],
    video_urls: list[str],
    idempotency_key: str,
) -> dict[str, Any]:
    """提交低成本 Seedance 视频任务，返回 Agent task_id。"""
    api_url = await _agent_api_url()
    model = choose_seedance_model(image_urls, video_urls)
    model_name = (
        "Seedance 2.0 参考生"
        if model == REFERENCE_VIDEO_MODEL
        else "Seedance 2.0 首尾帧"
    )
    params: dict[str, Any] = {
        "prompt": prompt,
        "model_id": model,
        "model_name": model_name,
        "version": "Mini",
        "duration": "4",
        "aspect_ratio": "16:9",
        "resolution": "480p",
    }
    if image_urls:
        params["images"] = image_urls[:9]
    if video_urls:
        params["videos"] = video_urls[:3]

    body = {
        "type": "videogen",
        "model": model,
        "prompt": prompt,
        "params": params,
        "workspace_id": credentials.workspace_id,
    }
    try:
        # 视频创建是计费、非幂等操作。明确关闭 transport 连接重试，
        # 且不跟随可能重复 POST 的 307/308 重定向。
        async with httpx.AsyncClient(
            timeout=60.0,
            transport=httpx.AsyncHTTPTransport(retries=0),
            follow_redirects=False,
        ) as client:
            response = await client.post(
                f"{api_url}/generate",
                headers=_headers(
                    credentials,
                    idempotency_key=idempotency_key,
                ),
                json=body,
            )
    except httpx.HTTPError as exc:
        raise AgentVideoError(f"Agent 视频任务提交失败: {exc}") from exc

    if response.status_code >= 400:
        raise AgentVideoError(
            f"Agent 视频任务提交失败: {_error_message(response)}",
            response.status_code,
        )

    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    task_id = data.get("task_id") if isinstance(data, dict) else None
    task_id = task_id or (payload.get("task_id") if isinstance(payload, dict) else None)
    if not task_id:
        raise AgentVideoError("Agent 返回结果中缺少 task_id")

    return {
        "task_id": str(task_id),
        "status": "running",
        "model": model,
        "model_name": model_name,
        "reference_count": len(image_urls) + len(video_urls),
    }


async def get_explainer_video_status(
    task_id: str,
    *,
    credentials: OpenNotebookCredentials,
) -> dict[str, Any]:
    """查询 Agent 异步视频任务并返回前端需要的统一字段。"""
    api_url = await _agent_api_url()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{api_url}/status",
                headers=_headers(credentials),
                params={"task_id": task_id},
            )
    except httpx.HTTPError as exc:
        raise AgentVideoError(f"Agent 视频状态查询失败: {exc}") from exc

    if response.status_code >= 400:
        raise AgentVideoError(
            f"Agent 视频状态查询失败: {_error_message(response)}",
            response.status_code,
        )

    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise AgentVideoError("Agent 视频状态响应格式异常")
    progress_text = str(data.get("progress") or "0")
    try:
        progress = int(progress_text.rstrip("%"))
    except ValueError:
        progress = 0

    return {
        "task_id": str(data.get("task_id") or task_id),
        "status": str(data.get("status") or "running"),
        "is_final": bool(data.get("is_final")),
        "progress": max(0, min(100, progress)),
        "current_step": str(data.get("current_step") or ""),
        "result_url": str(data.get("result_url") or ""),
        "error": str(data.get("error") or ""),
        "cost": data.get("cost") or 0,
    }
