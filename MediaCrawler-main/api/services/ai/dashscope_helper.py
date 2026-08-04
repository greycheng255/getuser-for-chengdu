# -*- coding: utf-8 -*-
"""
DashScope（阿里云百炼）数字人视频生成助手

基于 wan2.2-s2v 模型，实现真正的数字人口播视频生成（带唇形同步）。
流程：本地文件 → 上传获取 oss:// URL → 提交异步任务 → 轮询结果 → 下载视频

参考文档：
- https://help.aliyun.com/zh/model-studio/wan-s2v-api
- https://help.aliyun.com/zh/model-studio/get-temporary-file-url
"""
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("dashscope_helper")

# DashScope API 常量
DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/api/v1"
UPLOADS_URL = f"{DASHSCOPE_BASE}/uploads"
S2V_ENDPOINT = f"{DASHSCOPE_BASE}/services/aigc/image2video/video-synthesis"
TASKS_URL = f"{DASHSCOPE_BASE}/tasks"

# 轮询配置：PENDING 阶段 30s 间隔（减少无效请求），RUNNING 阶段 15s 间隔
# 最多 20 次：PENDING 约 5 分钟超时，RUNNING 约 5 分钟超时
POLL_INTERVAL_PENDING_S = 30
POLL_INTERVAL_RUNNING_S = 15
MAX_POLLS = 20  # 约 5-7 分钟，超时后降级到图片+音频模式

# 模型名称
MODEL_NAME = "wan2.2-s2v"


def _get_api_key() -> str:
    """获取 DashScope API Key"""
    key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置")
    return key


def is_dashscope_available() -> bool:
    """检查 DashScope 是否可用（API Key 是否配置 且 未被显式禁用）"""
    # 环境变量 DASHSCOPE_ENABLED=0 可显式关闭 DashScope（走降级模式）
    if os.getenv("DASHSCOPE_ENABLED", "1") == "0":
        return False
    return bool(os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY", ""))


async def upload_file(file_path: str, model: str = MODEL_NAME) -> str:
    """上传本地文件到 DashScope 临时存储，返回 oss:// URL

    两步流程：
    1. GET /api/v1/uploads?action=getPolicy&model=xxx → 获取 OSS 上传凭证
    2. POST 到 OSS upload_host → 上传文件，返回 oss://{upload_dir}/{filename}
    """
    api_key = _get_api_key()
    file_name = Path(file_path).name

    # Step 1: 获取上传凭证
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            UPLOADS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            params={"action": "getPolicy", "model": model},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"获取上传凭证失败: HTTP {resp.status_code} {resp.text[:200]}")
    policy = resp.json().get("data")
    if not policy:
        raise RuntimeError(f"上传凭证为空: {resp.text[:200]}")

    # Step 2: 上传文件到 OSS
    key = f"{policy['upload_dir']}/{file_name}"
    with open(file_path, "rb") as f:
        files = {
            "OSSAccessKeyId": (None, policy["oss_access_key_id"]),
            "Signature": (None, policy["signature"]),
            "policy": (None, policy["policy"]),
            "x-oss-object-acl": (None, policy["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, policy["x_oss_forbid_overwrite"]),
            "key": (None, key),
            "success_action_status": (None, "200"),
            "file": (file_name, f),
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(policy["upload_host"], files=files)

    if resp.status_code != 200:
        raise RuntimeError(f"文件上传OSS失败: HTTP {resp.status_code} {resp.text[:200]}")

    oss_url = f"oss://{key}"
    logger.info(f"[DashScope] 文件上传成功: {file_path} → {oss_url}")
    return oss_url


async def submit_s2v_task(
    image_url: str, audio_url: str, resolution: str = "480P"
) -> str:
    """提交 wan2.2-s2v 数字人视频生成任务，返回 task_id

    Args:
        image_url: oss:// 格式的图片 URL
        audio_url: oss:// 格式的音频 URL
        resolution: 480P 或 720P
    """
    api_key = _get_api_key()
    body = {
        "model": MODEL_NAME,
        "input": {
            "image_url": image_url,
            "audio_url": audio_url,
        },
        "parameters": {"resolution": resolution},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-DashScope-Async": "enable",
        # 使用 oss:// URL 时必须加此 header
        "X-DashScope-OssResourceResolve": "enable",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(S2V_ENDPOINT, headers=headers, json=body)

    data = resp.json() if resp.status_code < 500 else {}
    task_id = (data.get("output") or {}).get("task_id")
    if resp.status_code >= 400 or not task_id:
        msg = (
            data.get("message")
            or (data.get("output") or {}).get("message")
            or f"提交任务失败 (HTTP {resp.status_code})"
        )
        raise RuntimeError(msg)

    logger.info(f"[DashScope] 数字人任务已提交: task_id={task_id}")
    return str(task_id)


async def poll_task_result(
    task_id: str,
    on_progress: Optional[Any] = None,
) -> Dict[str, Any]:
    """轮询任务结果，直到 SUCCEEDED 或失败/超时

    Returns:
        {video_url, duration, resolution, fps}
    """
    api_key = _get_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    status = "PENDING"  # 初始状态

    for i in range(MAX_POLLS):
        # PENDING 阶段 30s 间隔，RUNNING 阶段 15s 间隔
        interval = POLL_INTERVAL_PENDING_S if status == "PENDING" else POLL_INTERVAL_RUNNING_S
        await asyncio.sleep(interval)
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(f"{TASKS_URL}/{task_id}", headers=headers)

        data = resp.json() if resp.status_code < 500 else {}
        status = (data.get("output") or {}).get("task_status") or "UNKNOWN"

        if on_progress:
            try:
                await on_progress(i, status)
            except Exception:
                pass

        logger.info(f"[DashScope] 轮询 {i+1}/{MAX_POLLS}: task_id={task_id} status={status}")

        if status == "SUCCEEDED":
            output = data.get("output") or {}
            usage = data.get("usage") or {}
            results = output.get("results") or {}
            video_url = results.get("video_url") or output.get("video_url")
            if not video_url:
                raise RuntimeError("任务完成但未返回视频地址")
            return {
                "video_url": video_url,
                "duration": usage.get("duration") or 0,
                "resolution": usage.get("size") or "",
                "fps": usage.get("fps") or 0,
            }

        if status in ("FAILED", "CANCELED"):
            msg = (output.get("message")) or (
                "任务失败" if status == "FAILED" else "任务已取消"
            )
            raise RuntimeError(msg)
        # PENDING / RUNNING / UNKNOWN → 继续轮询

    raise RuntimeError("视频生成超时（约 5 分钟），DashScope 排队中，已自动降级")


async def download_video(video_url: str, output_path: str) -> str:
    """下载生成的视频到本地"""
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        resp = await client.get(video_url)
    if resp.status_code != 200:
        raise RuntimeError(f"视频下载失败: HTTP {resp.status_code}")
    with open(output_path, "wb") as f:
        f.write(resp.content)
    logger.info(
        f"[DashScope] 视频下载完成: {output_path} ({len(resp.content)} bytes)"
    )
    return output_path


async def generate_digital_human_video(
    portrait_path: str,
    audio_path: str,
    output_path: str,
    resolution: str = "480P",
    on_progress: Optional[Any] = None,
) -> Dict[str, Any]:
    """完整的数字人视频生成流程（一站式调用）

    Args:
        portrait_path: 本地形象照图片路径
        audio_path: 本地音频文件路径
        output_path: 输出视频路径
        resolution: 480P 或 720P
        on_progress: 进度回调 async (poll_index, status) -> None

    Returns:
        {video_path, video_url, duration, resolution, fps, method}
    """
    start_ts = time.time()
    logger.info(f"[DashScope] 开始数字人视频生成: portrait={portrait_path} audio={audio_path}")

    # 1. 上传图片和音频（并发）
    image_url, audio_url = await asyncio.gather(
        upload_file(portrait_path),
        upload_file(audio_path),
    )
    logger.info(f"[DashScope] 文件上传完成 ({time.time()-start_ts:.1f}s)")

    # 2. 提交任务
    task_id = await submit_s2v_task(image_url, audio_url, resolution=resolution)

    # 3. 轮询结果
    result = await poll_task_result(task_id, on_progress=on_progress)
    logger.info(
        f"[DashScope] 视频生成完成 ({time.time()-start_ts:.1f}s): "
        f"duration={result['duration']}s resolution={result['resolution']}"
    )

    # 4. 下载视频
    await download_video(result["video_url"], output_path)

    return {
        "video_path": output_path,
        "video_url": result["video_url"],
        "duration": result["duration"],
        "resolution": result["resolution"],
        "fps": result["fps"],
        "method": "dashscope_wan2.2-s2v",
        "task_id": task_id,
    }
