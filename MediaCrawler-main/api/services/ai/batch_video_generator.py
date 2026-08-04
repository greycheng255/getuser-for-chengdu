# -*- coding: utf-8 -*-
"""
批量视频生成器

阶段一 P0 任务 1.2：补齐 PRD 5.2 批量生成多差异化视频缺口。

策略：
1. 输入多个热点 ID + 多个视频参数变体
2. 通过参数组合（不同画面风格 / 音色 / BGM）+ 随机扰动避免同质化
3. 并发控制：默认 max_concurrency=2（避免 AI 服务压力过大）
4. 输出：差异化视频列表 + 生成任务进度

复用：
- explainer_video_client.ExplainerVideoClient：视频生成
- video_generation_config.VideoGenConfig：参数配置
- hotpoint_fetcher：热点详情获取
"""

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .video_generation_config import VideoGenConfig, get_video_gen_config_service

logger = logging.getLogger(__name__)


@dataclass
class BatchVideoTask:
    """批量视频生成任务"""
    task_id: str
    hotspot_ids: List[str]
    variants: List[VideoGenConfig] = field(default_factory=list)
    status: str = "pending"  # pending / running / completed / failed
    progress: float = 0.0
    total: int = 0
    completed: int = 0
    failed: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    error: Optional[str] = None


class BatchVideoGenerator:
    """批量视频生成器"""

    def __init__(self, max_concurrency: int = 2):
        self.max_concurrency = max_concurrency
        self._tasks: Dict[str, BatchVideoTask] = {}

    async def start_batch(
        self,
        hotspot_ids: List[str],
        variants: Optional[List[VideoGenConfig]] = None,
        user_id: Optional[int] = None,
    ) -> BatchVideoTask:
        """启动批量生成任务

        Args:
            hotspot_ids: 热点 ID 列表
            variants: 视频参数变体列表（空则使用默认 4 个预设）
            user_id: 用户 ID

        Returns:
            BatchVideoTask
        """
        task_id = f"bvid_{uuid.uuid4().hex[:12]}"
        if not variants:
            variants = self._generate_default_variants()

        # 笛卡尔积：每个热点 × 每个变体（但限制最多 20 个组合，避免爆炸）
        combos = []
        for hid in hotspot_ids:
            for v in variants:
                combos.append((hid, v))
                if len(combos) >= 20:
                    break
            if len(combos) >= 20:
                break

        task = BatchVideoTask(
            task_id=task_id,
            hotspot_ids=hotspot_ids,
            variants=variants,
            status="running",
            total=len(combos),
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self._tasks[task_id] = task

        # 异步执行
        asyncio.create_task(self._run_batch(task_id, combos, user_id))
        return task

    async def _run_batch(
        self,
        task_id: str,
        combos: List[tuple],
        user_id: Optional[int],
    ) -> None:
        """执行批量生成"""
        task = self._tasks[task_id]
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _gen_one(hotspot_id: str, cfg: VideoGenConfig, idx: int):
            async with semaphore:
                try:
                    result = await self._generate_one(hotspot_id, cfg, user_id)
                    task.results.append(result)
                    if result.get("success"):
                        task.completed += 1
                    else:
                        task.failed += 1
                except Exception as e:
                    logger.warning(f"[BatchVideo] #{idx} 生成失败: {e}")
                    task.results.append({
                        "hotspot_id": hotspot_id,
                        "config_id": cfg.config_id,
                        "success": False,
                        "error": str(e),
                    })
                    task.failed += 1
                task.progress = (task.completed + task.failed) / max(task.total, 1)
                task.updated_at = datetime.now().isoformat()

        await asyncio.gather(*[_gen_one(h, c, i) for i, (h, c) in enumerate(combos)])
        task.status = "completed" if task.failed < task.total else "failed"
        task.updated_at = datetime.now().isoformat()

    async def _generate_one(
        self, hotspot_id: str, cfg: VideoGenConfig, user_id: Optional[int]
    ) -> Dict[str, Any]:
        """生成单个视频"""
        try:
            # 1. 获取热点详情
            hotspot = await self._fetch_hotspot(hotspot_id)
            if not hotspot:
                return {
                    "hotspot_id": hotspot_id,
                    "config_id": cfg.config_id,
                    "success": False,
                    "error": "热点不存在",
                }

            # 2. 构建 prompt
            prompt = self._build_prompt(hotspot, cfg)

            # 3. 调用视频生成服务
            from api.services.explainer_video_client import ExplainerVideoClient
            client = ExplainerVideoClient()
            video_url = await client.generate_video(
                prompt=prompt,
                duration=cfg.duration_seconds,
                resolution=cfg.resolution,
                aspect_ratio=cfg.aspect_ratio,
                voice_timbre=cfg.voice_timbre,
                visual_style=cfg.visual_style,
            )

            # 4. 持久化到视频资产库（失败不影响主流程）
            asset_id = None
            if video_url:
                try:
                    from api.services.ai.video_asset_library import get_video_asset_library
                    asset_id = await get_video_asset_library().save_asset(
                        video_url=video_url,
                        title=hotspot.get("title", "")[:255],
                        prompt=prompt,
                        duration=cfg.duration_seconds,
                        resolution=cfg.resolution,
                        aspect_ratio=cfg.aspect_ratio,
                        source_hotspot_id=hotspot.get("hot_id"),
                        source_post_url=hotspot.get("url") or hotspot.get("video_url"),
                        config_id=cfg.config_id,
                        owner_user_id=user_id,
                        status="ready",
                    )
                except Exception as save_e:
                    logger.warning(f"[BatchVideo] 资产入库失败(非致命): {save_e}")

            return {
                "hotspot_id": hotspot_id,
                "hotspot_title": hotspot.get("title", ""),
                "config_id": cfg.config_id,
                "config_name": cfg.name,
                "video_url": video_url,
                "asset_id": asset_id,
                "duration_seconds": cfg.duration_seconds,
                "resolution": cfg.resolution,
                "aspect_ratio": cfg.aspect_ratio,
                "visual_style": cfg.visual_style,
                "voice_timbre": cfg.voice_timbre,
                "success": True,
                "created_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.warning(f"[BatchVideo] 单视频生成失败: {e}")
            return {
                "hotspot_id": hotspot_id,
                "config_id": cfg.config_id,
                "success": False,
                "error": str(e),
            }

    async def _fetch_hotspot(self, hotspot_id: str) -> Optional[Dict[str, Any]]:
        """获取热点详情（通过 get_hot_items_store() 读取 hot_items 表）"""
        try:
            from api.services.hotpoint.hot_items_store import get_hot_items_store

            try:
                hot_id = int(hotspot_id)
            except (TypeError, ValueError):
                return None
            store = get_hot_items_store()
            item = await store.get_hot_item(hot_id)
            if not item:
                return None
            # 兼容旧字段名
            return {
                "id": item.get("hot_id") or item.get("id") or hotspot_id,
                "hot_id": item.get("hot_id"),
                "title": item.get("title") or "",
                "description": item.get("description") or item.get("content") or "",
                "content": item.get("content") or "",
                "platform": item.get("platform") or "",
                "heat_value": int(item.get("heat_value") or 0),
                "url": item.get("url") or "",
                "video_url": item.get("video_url") or "",
            }
        except Exception as e:
            logger.warning(f"[BatchVideo] 获取热点失败: {e}")
            return None

    def _build_prompt(self, hotspot: Dict[str, Any], cfg: VideoGenConfig) -> str:
        """根据热点 + 配置构建生成 prompt"""
        title = hotspot.get("title", "")
        desc = hotspot.get("description", "")
        return (
            f"基于以下热点生成 {cfg.duration_seconds} 秒短视频：\n"
            f"热点标题：{title}\n"
            f"热点描述：{desc}\n"
            f"画面风格：{cfg.visual_style}\n"
            f"配音音色：{cfg.voice_timbre}\n"
            f"BGM 情绪：{cfg.bgm_mood}\n"
            f"字幕样式：{cfg.subtitle_style}\n"
            f"宽高比：{cfg.aspect_ratio}\n"
            f"分辨率：{cfg.resolution}\n"
        )

    def _generate_default_variants(self) -> List[VideoGenConfig]:
        """生成默认 4 个变体（不同风格/音色组合）"""
        return [
            VideoGenConfig(
                config_id=f"variant_{uuid.uuid4().hex[:8]}",
                name="变体A-现代女声",
                duration_seconds=15,
                visual_style="modern",
                voice_timbre="female_warm",
                bgm_mood="upbeat",
            ),
            VideoGenConfig(
                config_id=f"variant_{uuid.uuid4().hex[:8]}",
                name="变体B-电影男声",
                duration_seconds=30,
                visual_style="cinematic",
                voice_timbre="male_deep",
                bgm_mood="inspiring",
            ),
            VideoGenConfig(
                config_id=f"variant_{uuid.uuid4().hex[:8]}",
                name="变体C-极简女声",
                duration_seconds=20,
                visual_style="minimal",
                voice_timbre="female_clear",
                bgm_mood="calm",
            ),
            VideoGenConfig(
                config_id=f"variant_{uuid.uuid4().hex[:8]}",
                name="变体D-Vlog 男声",
                duration_seconds=25,
                visual_style="vlog",
                voice_timbre="male_warm",
                bgm_mood="funny",
            ),
        ]

    def get_task(self, task_id: str) -> Optional[BatchVideoTask]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> List[Dict[str, Any]]:
        return [
            {
                "task_id": t.task_id,
                "status": t.status,
                "progress": t.progress,
                "total": t.total,
                "completed": t.completed,
                "failed": t.failed,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in self._tasks.values()
        ]


# ============ 单例 ============
_generator: Optional[BatchVideoGenerator] = None


def get_batch_video_generator() -> BatchVideoGenerator:
    global _generator
    if _generator is None:
        _generator = BatchVideoGenerator()
    return _generator
