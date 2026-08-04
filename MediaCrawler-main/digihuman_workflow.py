"""DigiHuman agent — 图片 + 音频 → 数字人口播视频 (LangGraph, DashScope wan2.2-s2v)。

迁移自历史前端 ``frontend/src/lib/agents/digihuman-workflow.ts``:

    submit (DashScope async) → poll (≤15min) → save

结果写入 ``agent_generation_records.result_data``,字段与前端一致(camelCase):
``{ video_url, duration, resolution, fps, image_url, audio_url }``。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, TypedDict

from langgraph.graph import StateGraph, START, END

from app.agents._common import abort, finish_record, settle, update_progress
from app.agents._dashscope import DASHSCOPE_AIGC_BASE, poll_task, submit_async_task

logger = logging.getLogger(__name__)

S2V_ENDPOINT = f"{DASHSCOPE_AIGC_BASE}/image2video/video-synthesis"


class DigiHumanState(TypedDict, total=False):
    image_url: str
    audio_url: str
    resolution: str
    record_id: str
    workspace_id: str
    tenant_id: str
    estimated_credits: float

    dashscope_task_id: str
    result: Dict[str, Any]
    status: str
    error: str


async def submit_node(state: DigiHumanState) -> Dict[str, Any]:
    await asyncio.to_thread(update_progress, state["record_id"], "submitting", 10)
    body = {
        "model": "wan2.2-s2v",
        "input": {
            "image_url": state.get("image_url"),
            "audio_url": state.get("audio_url"),
        },
        "parameters": {"resolution": state.get("resolution") or "480P"},
    }
    try:
        task_id = await submit_async_task(S2V_ENDPOINT, body)
    except Exception as e:
        return await abort(state, f"提交任务失败: {e}")
    await asyncio.to_thread(update_progress, state["record_id"], "queued", 20)
    return {"dashscope_task_id": task_id, "status": "polling"}


async def poll_node(state: DigiHumanState) -> Dict[str, Any]:
    record_id = state["record_id"]

    async def on_poll(i: int, _status: str) -> None:
        pct = min(20 + int(i / 60 * 70), 90)
        await asyncio.to_thread(update_progress, record_id, "generating", pct)

    try:
        data = await poll_task(state["dashscope_task_id"], on_poll=on_poll)
    except Exception as e:
        return await abort(state, f"视频生成失败: {e}")

    output = data.get("output") or {}
    usage = data.get("usage") or {}
    video_url = (output.get("results") or {}).get("video_url") or output.get("video_url")
    if not video_url:
        return await abort(state, "任务完成但未返回视频地址")
    return {
        "result": {
            "video_url": video_url,
            "duration": usage.get("duration") or 0,
            "resolution": usage.get("size") or "",
            "fps": usage.get("fps") or 0,
        },
        "status": "saving",
    }


async def save_node(state: DigiHumanState) -> Dict[str, Any]:
    result = state.get("result") or {}
    result_data = {
        "video_url": result.get("video_url"),
        "duration": result.get("duration"),
        "resolution": result.get("resolution"),
        "fps": result.get("fps"),
        "image_url": state.get("image_url"),
        "audio_url": state.get("audio_url"),
    }
    try:
        await settle(state)
        await asyncio.to_thread(finish_record, state["record_id"], result_data)
    except Exception as e:
        return await abort(state, f"结果保存失败: {e}")
    logger.info("[DigiHuman] done (record=%s)", state["record_id"])
    return {"status": "done"}


def _route_after_submit(state: DigiHumanState) -> str:
    return END if state.get("error") else "poll"


def _route_after_poll(state: DigiHumanState) -> str:
    return END if state.get("error") else "save"


_graph = StateGraph(DigiHumanState)
_graph.add_node("submit", submit_node)
_graph.add_node("poll", poll_node)
_graph.add_node("save", save_node)
_graph.add_edge(START, "submit")
_graph.add_conditional_edges("submit", _route_after_submit, {"poll": "poll", END: END})
_graph.add_conditional_edges("poll", _route_after_poll, {"save": "save", END: END})
_graph.add_edge("save", END)

digihuman_workflow_graph = _graph.compile()
