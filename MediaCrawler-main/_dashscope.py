"""DashScope (阿里云百炼) async task helpers.

Shared by the DigiHuman (wan2.2-s2v) and Video Agent (wan2.x i2v/t2v/r2v)
workflows. Mirrors the ``X-DashScope-Async`` submit-then-poll pattern from the
historical frontend digihuman/video-agent workflows.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from config import settings

DASHSCOPE_AIGC_BASE = "https://dashscope.aliyuncs.com/api/v1/services/aigc"
DASHSCOPE_TASKS_URL = "https://dashscope.aliyuncs.com/api/v1/tasks"

# DashScope recommends polling at 15s; 60 polls ≈ 15 min, matching the frontend.
POLL_INTERVAL_S = 15
MAX_POLLS = 60


def api_key() -> str:
    """Resolve the DashScope key (falls back to OPENAI key, like services/vl.py)."""
    key = os.getenv("DASHSCOPE_API_KEY") or settings.openai_api_key
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置")
    return key


async def submit_async_task(endpoint: str, body: Dict[str, Any]) -> str:
    """POST an async generation task; return the DashScope task_id."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            endpoint,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key()}",
                "X-DashScope-Async": "enable",
            },
            json=body,
        )
    data = _safe_json(resp)
    task_id = (data.get("output") or {}).get("task_id")
    if resp.status_code >= 400 or not task_id:
        msg = (
            data.get("message")
            or (data.get("output") or {}).get("message")
            or f"提交任务失败 (HTTP {resp.status_code})"
        )
        raise RuntimeError(msg)
    return str(task_id)


async def poll_task(
    task_id: str,
    *,
    on_poll: Optional[Callable[[int, str], Awaitable[None]]] = None,
    interval_s: int = POLL_INTERVAL_S,
    max_polls: int = MAX_POLLS,
) -> Dict[str, Any]:
    """Poll until SUCCEEDED; raise on FAILED/CANCELED/timeout. Returns the full body."""
    for i in range(max_polls):
        await asyncio.sleep(interval_s)
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{DASHSCOPE_TASKS_URL}/{task_id}",
                headers={"Authorization": f"Bearer {api_key()}"},
            )
        data = _safe_json(resp)
        status = (data.get("output") or {}).get("task_status") or "UNKNOWN"
        if on_poll:
            await on_poll(i, status)
        if status == "SUCCEEDED":
            return data
        if status in ("FAILED", "CANCELED"):
            msg = (data.get("output") or {}).get("message") or (
                "任务失败" if status == "FAILED" else "任务已取消"
            )
            raise RuntimeError(msg)
        # PENDING / RUNNING / UNKNOWN → keep polling
    raise RuntimeError("视频生成超时（15 分钟），请重试。")


def _safe_json(resp: httpx.Response) -> Dict[str, Any]:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
