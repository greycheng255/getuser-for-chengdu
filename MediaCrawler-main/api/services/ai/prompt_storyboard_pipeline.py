# -*- coding: utf-8 -*-
"""
P4 提示词/分镜识别与视频生成链路

阶段一 P0 任务 1.2 + 阶段四任务 4.2 增强：
1. 热点视频 → ai_agent_client 拆解
2. 拆解结果 → StoryboardParser 结构化（scenes 列表）
3. 结构化分镜 → 提取 prompt
4. 优化提示词 → 检索相似案例 → PromptLibrary 沉淀
5. 优化提示词 → explainer_video_client 生成新视频
6. 生成视频 → moderation 审核链路
7. 审核通过 → 多平台分发（可选）

对应 PRD P4 + 8.5：提示词库可检索复用，串联到视频生成输入链路。
"""

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# 复用独立拆出的 StoryboardParser（保持向后兼容旧导入）
from .storyboard_parser import (
    Scene,
    Storyboard,
    StoryboardParser,
    get_storyboard_parser,
)

logger = logging.getLogger(__name__)


class PromptStoryboardPipeline:
    """P4 提示词/分镜串联管线（增强版）

    新增能力：
    - 沉淀：每次提取的提示词+分镜自动入库
    - 检索：生成前先从库中检索相似案例作为参考
    - 复用：可直接基于已沉淀的提示词生成视频
    - 闭环：审核通过后自动调用 publisher 分发
    """

    def __init__(self):
        self.parser = get_storyboard_parser()

    async def extract_from_hotspot(
        self,
        hotspot_video_url: str,
        hotspot_id: str = "",
        owner_user_id: Optional[int] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """从热点视频提取提示词+分镜

        Args:
            hotspot_video_url: 热点视频 URL
            hotspot_id: 关联热点 ID（用于沉淀）
            owner_user_id: 用户 ID（用于隔离）
            persist: 是否沉淀到提示词库

        Returns:
            {success, prompt, storyboard, prompt_id, similar_cases, error}
        """
        try:
            from api.services.ai_agent_client import get_ai_agent_client, is_ai_in_cooldown, is_ai_expected_error

            if is_ai_in_cooldown():
                return {"success": False, "error": "AI 服务冷却中，稍后重试"}
            client = get_ai_agent_client()
            raw_text = await client.breakdown_video(hotspot_video_url)
            if not raw_text:
                return {"success": False, "error": "视频拆解返回空"}

            storyboard = self.parser.parse(raw_text, source_video_url=hotspot_video_url)
            storyboard.owner_user_id = owner_user_id

            # 构建优化后的提示词
            optimized_prompt = self._optimize_prompt(storyboard)

            # 检索相似案例
            similar_cases: List[Dict[str, Any]] = []
            try:
                from .prompt_library import get_prompt_library
                library = get_prompt_library()
                similar = await library.find_similar(
                    category=storyboard.category,
                    tags=storyboard.tags,
                    style_keyword=storyboard.style_keywords[0] if storyboard.style_keywords else "",
                    limit=3,
                )
                similar_cases = [s.to_dict() for s in similar]
            except Exception as e:
                logger.debug(f"[PromptStoryboard] 检索相似案例失败: {e}")

            # 沉淀到提示词库
            prompt_id = ""
            if persist:
                try:
                    from .prompt_library import get_prompt_library
                    library = get_prompt_library()
                    # 先存分镜
                    sb_id = await library.save_storyboard(storyboard)
                    if sb_id:
                        storyboard.storyboard_id = sb_id
                    # 再存提示词
                    prompt_id = await library.save_prompt(
                        title=storyboard.title or f"hotspot_{hotspot_id}",
                        prompt_text=optimized_prompt,
                        category=storyboard.category,
                        style_keywords=storyboard.style_keywords,
                        tags=storyboard.tags,
                        source_video_url=hotspot_video_url,
                        source_hotspot_id=hotspot_id,
                        storyboard_id=storyboard.storyboard_id,
                        owner_user_id=owner_user_id,
                    ) or ""
                except Exception as e:
                    logger.warning(f"[PromptStoryboard] 沉淀失败: {e}")

            return {
                "success": True,
                "prompt": optimized_prompt,
                "storyboard": storyboard.to_dict(),
                "prompt_id": prompt_id,
                "similar_cases": similar_cases,
                "raw_text": raw_text,
            }
        except Exception as e:
            if is_ai_expected_error(e):
                logger.debug(f"[PromptStoryboard] AI 预期内错误跳过: {e}")
            else:
                logger.warning(f"[PromptStoryboard] 提取失败: {e}")
            return {"success": False, "error": str(e)}

    async def generate_from_existing_prompt(
        self,
        prompt_id: str,
        video_config: Optional[Any] = None,
        auto_moderate: bool = True,
    ) -> Dict[str, Any]:
        """基于已沉淀的提示词生成视频（复用）

        Args:
            prompt_id: 提示词库 ID
            video_config: 视频参数
            auto_moderate: 是否自动审核
        """
        try:
            from .prompt_library import get_prompt_library
            library = get_prompt_library()
            record = await library.get(prompt_id)
            if not record:
                return {"success": False, "error": f"提示词 {prompt_id} 不存在"}

            # 标记使用
            await library.mark_used(prompt_id, success=False)

            # 生成视频
            video_url = await self._generate_video(record.prompt_text, video_config)
            if not video_url:
                await library.mark_used(prompt_id, success=False)
                return {
                    "success": False,
                    "error": "视频生成失败",
                    "prompt": record.prompt_text,
                }

            # 标记成功
            await library.mark_used(prompt_id, success=True)

            # 持久化到视频资产库（失败不影响主流程）
            asset_id = None
            try:
                from .video_asset_library import get_video_asset_library
                asset_id = await get_video_asset_library().save_asset(
                    video_url=video_url,
                    title=(record.title or prompt_id)[:255],
                    prompt=record.prompt_text,
                    duration=getattr(video_config, "duration_seconds", None),
                    resolution=getattr(video_config, "resolution", None),
                    aspect_ratio=getattr(video_config, "aspect_ratio", None),
                    source_post_url=record.source_video_url,
                    config_id=getattr(video_config, "config_id", None),
                    status="ready",
                )
            except Exception as save_e:
                logger.warning(f"[PromptStoryboard] 资产入库失败(非致命): {save_e}")

            result: Dict[str, Any] = {
                "success": True,
                "video_url": video_url,
                "asset_id": asset_id,
                "prompt": record.prompt_text,
                "prompt_id": prompt_id,
                "video_config": video_config.to_dict() if hasattr(video_config, "to_dict") else {},
            }

            if auto_moderate:
                result["moderation_result"] = await self._moderate(record.prompt_text, video_url)

            return result
        except Exception as e:
            logger.warning(f"[PromptStoryboard] 复用生成失败: {e}")
            return {"success": False, "error": str(e)}

    async def generate_video_from_hotspot(
        self,
        hotspot_video_url: str,
        video_config: Optional[Any] = None,
        auto_moderate: bool = True,
        hotspot_id: str = "",
        owner_user_id: Optional[int] = None,
        auto_publish_platforms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """一键执行完整链路：热点视频 → 提示词/分镜 → 新视频生成 → 审核 → 多平台分发

        Args:
            hotspot_video_url: 热点视频 URL
            video_config: VideoGenConfig 视频参数（None 用默认）
            auto_moderate: 是否自动审核
            hotspot_id: 关联热点 ID
            owner_user_id: 用户 ID
            auto_publish_platforms: 审核通过后自动分发的平台列表

        Returns:
            {success, video_url, prompt, storyboard, moderation_result, publish_results}
        """
        # 1. 提取提示词+分镜 + 沉淀
        extract_result = await self.extract_from_hotspot(
            hotspot_video_url,
            hotspot_id=hotspot_id,
            owner_user_id=owner_user_id,
            persist=True,
        )
        if not extract_result.get("success"):
            return extract_result

        prompt = extract_result["prompt"]
        storyboard = extract_result["storyboard"]
        prompt_id = extract_result.get("prompt_id", "")

        # 2. 合并用户配置
        if video_config is None:
            from .video_generation_config import VideoGenConfig
            video_config = VideoGenConfig()

        # 3. 调用视频生成
        video_url = await self._generate_video(prompt, video_config)
        if not video_url:
            return {
                "success": False,
                "error": "视频生成失败",
                "prompt": prompt,
                "storyboard": storyboard,
                "prompt_id": prompt_id,
            }

        # 3.5 持久化到视频资产库（失败不影响主流程）
        asset_id = None
        try:
            from .video_asset_library import get_video_asset_library
            sb_title = (
                storyboard.get("title", "") if isinstance(storyboard, dict)
                else getattr(storyboard, "title", "")
            )
            try:
                hotspot_id_int = int(hotspot_id) if hotspot_id else None
            except (TypeError, ValueError):
                hotspot_id_int = None
            asset_id = await get_video_asset_library().save_asset(
                video_url=video_url,
                title=(sb_title or f"hotspot_{hotspot_id}")[:255],
                prompt=prompt,
                duration=getattr(video_config, "duration_seconds", None),
                resolution=getattr(video_config, "resolution", None),
                aspect_ratio=getattr(video_config, "aspect_ratio", None),
                source_hotspot_id=hotspot_id_int,
                source_post_url=hotspot_video_url,
                config_id=getattr(video_config, "config_id", None),
                owner_user_id=owner_user_id,
                status="ready",
            )
        except Exception as save_e:
            logger.warning(f"[PromptStoryboard] 资产入库失败(非致命): {save_e}")

        result: Dict[str, Any] = {
            "success": True,
            "video_url": video_url,
            "asset_id": asset_id,
            "prompt": prompt,
            "prompt_id": prompt_id,
            "storyboard": storyboard,
            "similar_cases": extract_result.get("similar_cases", []),
            "video_config": video_config.to_dict() if hasattr(video_config, "to_dict") else {},
        }

        # 4. 自动审核
        if auto_moderate:
            result["moderation_result"] = await self._moderate(prompt, video_url)

        # 5. 审核通过后自动分发
        if auto_publish_platforms and result.get("success"):
            mod_result = result.get("moderation_result", {})
            mod_passed = (
                mod_result.get("passed", True)
                if isinstance(mod_result, dict)
                else True
            )
            if mod_passed:
                result["publish_results"] = await self._auto_publish(
                    video_url=video_url,
                    title=storyboard.get("title", "") if isinstance(storyboard, dict) else storyboard.title,
                    prompt=prompt,
                    platforms=auto_publish_platforms,
                    owner_user_id=owner_user_id,
                )

        # 6. 更新提示词使用统计
        if prompt_id:
            try:
                from .prompt_library import get_prompt_library
                await get_prompt_library().mark_used(prompt_id, success=result.get("success", False))
            except Exception:
                pass

        return result

    # ==================== 完整一键链路 ====================

    async def run_full_pipeline(
        self,
        hotspot_video_url: str,
        video_config: Optional[Any] = None,
        owner_user_id: Optional[int] = None,
        hotspot_id: str = "",
        publish_platforms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """阶段四任务 4.2 完整一键链路（POST /api/ai/full-pipeline）

        流程：
        1. 热点视频 → ai_agent_client 拆解
        2. 拆解结果 → StoryboardParser 结构化
        3. 结构化分镜 → PromptLibrary 沉淀 + 检索相似
        4. 优化提示词 → explainer_video_client 生成视频
        5. 生成视频 → ModerationService 审核
        6. 审核通过 → publisher 多平台分发
        """
        return await self.generate_video_from_hotspot(
            hotspot_video_url=hotspot_video_url,
            video_config=video_config,
            auto_moderate=True,
            hotspot_id=hotspot_id,
            owner_user_id=owner_user_id,
            auto_publish_platforms=publish_platforms,
        )

    # ==================== 私有方法 ====================

    async def _generate_video(
        self, prompt: str, video_config: Optional[Any]
    ) -> Optional[str]:
        """调用视频生成服务"""
        try:
            from api.services.explainer_video_client import ExplainerVideoClient

            if video_config is None:
                from .video_generation_config import VideoGenConfig
                video_config = VideoGenConfig()

            client = ExplainerVideoClient()
            return await client.generate_video(
                prompt=prompt,
                duration=video_config.duration_seconds,
                resolution=video_config.resolution,
                aspect_ratio=video_config.aspect_ratio,
                voice_timbre=video_config.voice_timbre,
                visual_style=video_config.visual_style,
            )
        except Exception as e:
            logger.warning(f"[PromptStoryboard] 视频生成失败: {e}")
            return None

    async def _moderate(self, prompt: str, video_url: str) -> Dict[str, Any]:
        """调用审核服务"""
        try:
            from api.services.moderation.moderation_service import get_moderation_service
            mod_service = get_moderation_service()
            mod_result = await mod_service.moderate(
                content=prompt,
                platform="auto",
                metadata={"video_url": video_url},
            )
            return mod_result.to_dict() if hasattr(mod_result, "to_dict") else {"raw": str(mod_result)}
        except Exception as e:
            logger.warning(f"[PromptStoryboard] 审核失败: {e}")
            return {"error": str(e), "passed": True}

    async def _auto_publish(
        self,
        video_url: str,
        title: str,
        prompt: str,
        platforms: List[str],
        owner_user_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        """审核通过后自动分发"""
        results: List[Dict[str, Any]] = []
        try:
            from api.services.publisher.multi_publisher import get_multi_platform_publisher
            from api.services.publisher.publish_task import PublishTask

            publisher = get_multi_platform_publisher()
            task = PublishTask(
                title=title or "AI 生成视频",
                content=prompt[:500],
                video_path=video_url,
                target_platforms=platforms,
                user_id=owner_user_id or 1,
            )
            # MultiPlatformPublisher 提供 publish_to_multiple_platforms（非 publish）
            publish_result = await publisher.publish_to_multiple_platforms(task)
            for pr in publish_result:
                results.append(pr.to_dict() if hasattr(pr, "to_dict") else {"raw": str(pr)})
        except Exception as e:
            logger.warning(f"[PromptStoryboard] 自动分发失败: {e}")
            results.append({"success": False, "error": str(e)})
        return results

    def _optimize_prompt(self, storyboard: Storyboard) -> str:
        """基于分镜结构优化生成提示词"""
        parts = []
        if storyboard.title:
            parts.append(f"主题：{storyboard.title}")
        if storyboard.style_keywords:
            parts.append(f"风格：{', '.join(storyboard.style_keywords)}")
        if storyboard.overall_prompt:
            parts.append(f"整体提示词：{storyboard.overall_prompt}")
        if storyboard.scenes:
            scene_descs = []
            for s in storyboard.scenes[:8]:  # 最多 8 个场景
                desc = s.visual_prompt or s.voiceover
                if desc:
                    scene_descs.append(f"分镜{s.scene_index + 1}: {desc[:100]}")
            if scene_descs:
                parts.append("分镜结构：\n" + "\n".join(scene_descs))
        if not parts:
            return "基于热点视频生成新的差异化短视频"
        return "\n".join(parts)


# ============ 单例 ============
_pipeline: Optional[PromptStoryboardPipeline] = None


def get_prompt_storyboard_pipeline() -> PromptStoryboardPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = PromptStoryboardPipeline()
    return _pipeline
