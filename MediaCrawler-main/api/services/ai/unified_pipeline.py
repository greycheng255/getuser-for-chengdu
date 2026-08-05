# -*- coding: utf-8 -*-
"""
五功能统一编排流水线

将"提示词库、视频参数配置、人工复核、发布调度管理、话术库"五个功能
串联为完整自动化流水线：

    输入源 → Step1 提示词库 → Step2 视频参数配置 → Step3 数字人视频生成
          → Step4 人工复核(强制) → Step5 发布调度管理(定时错峰)
          → Step6 话术库互动(自动触发)

设计要点：
- 流水线状态持久化到 pipeline_tasks 表，避免内存丢失
- Step4→Step5 由 review_workflow.submit_review() 回调 proceed_after_review()
- Step5→Step6 由 publish_scheduler._execute_one() 回调 proceed_after_publish()
- 不破坏现有 run_full_pipeline，独立编排
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# 流水线状态枚举
class PipelineStatus:
    PENDING = "pending"
    EXTRACTING = "extracting"        # Step1 提示词库
    GENERATING = "generating"        # Step3 视频生成
    REVIEWING = "reviewing"          # Step4 人工复核（暂停点）
    SCHEDULING = "scheduling"        # Step5 发布调度
    PUBLISHED = "published"          # 发布完成
    INTERACTING = "interacting"      # Step6 话术库互动
    COMPLETED = "completed"
    FAILED = "failed"


# 输入源类型
class SourceType:
    HOTSPOT_URL = "hotspot_url"      # 热点视频 URL
    PROMPT_ID = "prompt_id"          # 提示词库 ID
    MANUAL_TEXT = "manual_text"      # 手动文案


class UnifiedPipeline:
    """五功能统一编排流水线

    使用方式：
        pipeline = get_unified_pipeline()
        result = await pipeline.run_unified_pipeline(
            source_type="manual_text",
            source_value="文案内容",
            video_config_id="",
            publish_platforms=["douyin"],
        )
        # 返回 pipeline_id，后续由复核/发布回调自动推进
    """

    _ensured = False  # DDL 仅首次执行一次

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if UnifiedPipeline._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS pipeline_tasks ("
                        "  pipeline_id VARCHAR(64) PRIMARY KEY,"
                        "  status VARCHAR(32) DEFAULT 'pending',"
                        "  source_type VARCHAR(32),"
                        "  source_value TEXT,"
                        "  prompt_id VARCHAR(64),"
                        "  prompt_text TEXT,"
                        "  storyboard TEXT,"
                        "  video_config_id VARCHAR(64),"
                        "  video_url TEXT,"
                        "  asset_id VARCHAR(64),"
                        "  review_id VARCHAR(64),"
                        "  schedule_task_id VARCHAR(64),"
                        "  publish_results TEXT,"
                        "  interaction_task_id VARCHAR(64),"
                        "  publish_platforms TEXT,"
                        "  owner_user_id INTEGER,"
                        "  error_message TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  updated_at TIMESTAMP DEFAULT NOW())"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_pipeline_status "
                        "ON pipeline_tasks(status, created_at DESC)"
                    )
                )
                # scheduled_publish_tasks 增加来源列（兼容旧表，重复添加会被捕获）
                try:
                    await conn.execute(
                        sql_text(
                            "ALTER TABLE scheduled_publish_tasks "
                            "ADD COLUMN source_pipeline_id VARCHAR(64)"
                        )
                    )
                except Exception:
                    pass  # 列已存在
            UnifiedPipeline._ensured = True
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] ensure_table failed: {e}")

    # ==================== 主入口 ====================

    async def run_unified_pipeline(
        self,
        source_type: str,
        source_value: str,
        video_config_id: str = "",
        publish_platforms: Optional[List[str]] = None,
        owner_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """启动统一流水线

        执行 Step1→Step4，到 Step4（人工复核）暂停，返回 pipeline_id。
        后续由 proceed_after_review / proceed_after_publish 自动推进。

        Returns:
            {success, pipeline_id, status, review_id, prompt, video_url, error}
        """
        await self.ensure_table()
        publish_platforms = publish_platforms or ["douyin"]
        pipeline_id = f"pipe_{uuid.uuid4().hex[:12]}"

        # 创建流水线记录
        await self._create_pipeline_record(
            pipeline_id=pipeline_id,
            source_type=source_type,
            source_value=source_value,
            video_config_id=video_config_id,
            publish_platforms=publish_platforms,
            owner_user_id=owner_user_id,
        )

        try:
            # Step 1: 提示词库
            await self._update_status(pipeline_id, PipelineStatus.EXTRACTING)
            step1 = await self._step1_prompt(source_type, source_value, owner_user_id)
            if not step1.get("success"):
                await self._mark_failed(pipeline_id, f"Step1失败: {step1.get('error')}")
                return {"success": False, "pipeline_id": pipeline_id, "error": step1.get("error")}
            prompt_text = step1["prompt"]
            prompt_id = step1.get("prompt_id", "")
            storyboard = step1.get("storyboard")
            await self._update_pipeline(pipeline_id, {
                "prompt_id": prompt_id,
                "prompt_text": prompt_text,
                "storyboard": json.dumps(storyboard, ensure_ascii=False) if storyboard else "",
            })

            # Step 2: 视频参数配置
            video_config = await self._step2_config(video_config_id)

            # Step 3: 数字人视频生成
            await self._update_status(pipeline_id, PipelineStatus.GENERATING)
            video_url = await self._step3_generate(prompt_text, video_config)
            if not video_url:
                await self._mark_failed(pipeline_id, "Step3视频生成失败")
                return {"success": False, "pipeline_id": pipeline_id, "error": "视频生成失败"}
            await self._update_pipeline(pipeline_id, {"video_url": video_url})

            # 持久化到视频资产库（失败不影响主流程）
            asset_id = None
            try:
                from .video_asset_library import get_video_asset_library
                asset_id = await get_video_asset_library().save_asset(
                    video_url=video_url,
                    title=(prompt_text[:50] or pipeline_id),
                    prompt=prompt_text,
                    duration=getattr(video_config, "duration_seconds", None),
                    resolution=getattr(video_config, "resolution", None),
                    aspect_ratio=getattr(video_config, "aspect_ratio", None),
                    config_id=getattr(video_config, "config_id", None),
                    owner_user_id=owner_user_id,
                    status="ready",
                )
                if asset_id:
                    await self._update_pipeline(pipeline_id, {"asset_id": asset_id})
            except Exception as e:
                logger.warning(f"[UnifiedPipeline] 资产入库失败(非致命): {e}")

            # Step 4: 人工复核（强制）
            await self._update_status(pipeline_id, PipelineStatus.REVIEWING)
            review_id = await self._step4_create_review(
                pipeline_id=pipeline_id,
                video_url=video_url,
                prompt=prompt_text,
                owner_user_id=owner_user_id,
            )
            if not review_id:
                await self._mark_failed(pipeline_id, "Step4创建复核任务失败")
                return {"success": False, "pipeline_id": pipeline_id, "error": "创建复核任务失败"}
            await self._update_pipeline(pipeline_id, {"review_id": review_id})

            logger.info(
                f"[UnifiedPipeline] 流水线 {pipeline_id} 已暂停在人工复核环节 "
                f"review_id={review_id}"
            )
            return {
                "success": True,
                "pipeline_id": pipeline_id,
                "status": PipelineStatus.REVIEWING,
                "review_id": review_id,
                "prompt": prompt_text,
                "prompt_id": prompt_id,
                "video_url": video_url,
                "asset_id": asset_id,
                "message": "视频已生成，请前往人工复核队列审核",
            }
        except Exception as e:
            logger.exception(f"[UnifiedPipeline] 流水线 {pipeline_id} 异常")
            await self._mark_failed(pipeline_id, str(e))
            return {"success": False, "pipeline_id": pipeline_id, "error": str(e)}

    # ==================== 回调：复核通过 → Step5 ====================

    async def proceed_after_review(self, review_id: str) -> Dict[str, Any]:
        """人工复核通过后回调：执行 Step5 创建定时发布任务

        由 review_workflow.submit_review() 在 decision=approved 时调用。
        """
        try:
            # 通过 review_id 查找 pipeline（content_id 格式: pipeline_{pipeline_id}）
            pipeline = await self._get_pipeline_by_review(review_id)
            if not pipeline:
                logger.debug(f"[UnifiedPipeline] review_id={review_id} 不属于任何流水线")
                return {"success": False, "error": "不属于流水线任务"}
            pipeline_id = pipeline["pipeline_id"]

            if pipeline["status"] != PipelineStatus.REVIEWING:
                logger.warning(
                    f"[UnifiedPipeline] pipeline {pipeline_id} 状态非 reviewing，跳过"
                )
                return {"success": False, "error": f"状态非 reviewing: {pipeline['status']}"}

            await self._update_status(pipeline_id, PipelineStatus.SCHEDULING)

            # Step 5: 创建定时发布任务
            publish_platforms = json.loads(pipeline.get("publish_platforms") or "[]")
            video_url = pipeline.get("video_url") or ""
            title = (pipeline.get("prompt_text") or "")[:50] or pipeline_id

            schedule_task_id = await self._step5_schedule_publish(
                pipeline_id=pipeline_id,
                video_url=video_url,
                title=title,
                content=pipeline.get("prompt_text") or "",
                platforms=publish_platforms,
                owner_user_id=pipeline.get("owner_user_id"),
            )
            if not schedule_task_id:
                await self._mark_failed(pipeline_id, "Step5创建发布任务失败")
                return {"success": False, "pipeline_id": pipeline_id, "error": "创建发布任务失败"}

            await self._update_pipeline(pipeline_id, {
                "schedule_task_id": schedule_task_id,
            })
            logger.info(
                f"[UnifiedPipeline] pipeline {pipeline_id} 已创建发布任务 "
                f"schedule_task_id={schedule_task_id}"
            )
            return {
                "success": True,
                "pipeline_id": pipeline_id,
                "schedule_task_id": schedule_task_id,
                "message": "已自动创建定时发布任务，等待调度器执行",
            }
        except Exception as e:
            logger.exception(f"[UnifiedPipeline] proceed_after_review 异常")
            return {"success": False, "error": str(e)}

    # ==================== 回调：发布完成 → Step6 ====================

    async def proceed_after_publish(
        self, pipeline_id: str, publish_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """发布完成后回调：执行 Step6 话术库互动

        由 publish_scheduler._execute_one() 在发布成功后调用。
        """
        try:
            pipeline = await self.get_pipeline_status(pipeline_id)
            if not pipeline:
                return {"success": False, "error": f"流水线 {pipeline_id} 不存在"}

            await self._update_status(pipeline_id, PipelineStatus.PUBLISHED)
            await self._update_pipeline(pipeline_id, {
                "publish_results": json.dumps(publish_results, ensure_ascii=False),
            })

            # Step 6: 话术库互动
            await self._update_status(pipeline_id, PipelineStatus.INTERACTING)
            interaction_task_id = await self._step6_trigger_interaction(
                pipeline_id=pipeline_id,
                publish_results=publish_results,
                owner_user_id=pipeline.get("owner_user_id"),
            )
            await self._update_pipeline(pipeline_id, {
                "interaction_task_id": interaction_task_id or "",
            })

            # 流水线完成
            await self._update_status(pipeline_id, PipelineStatus.COMPLETED)
            logger.info(
                f"[UnifiedPipeline] pipeline {pipeline_id} 全流程完成 "
                f"interaction_task_id={interaction_task_id}"
            )
            return {
                "success": True,
                "pipeline_id": pipeline_id,
                "interaction_task_id": interaction_task_id,
                "status": PipelineStatus.COMPLETED,
            }
        except Exception as e:
            logger.exception(f"[UnifiedPipeline] proceed_after_publish 异常")
            await self._mark_failed(pipeline_id, f"Step6失败: {e}")
            return {"success": False, "error": str(e)}

    # ==================== 各步骤实现 ====================

    async def _step1_prompt(
        self, source_type: str, source_value: str, owner_user_id: Optional[int]
    ) -> Dict[str, Any]:
        """Step1: 提示词库 - 提取/复用/手动"""
        try:
            if source_type == SourceType.MANUAL_TEXT:
                # 手动文案直接作为 prompt
                return {
                    "success": True,
                    "prompt": source_value,
                    "prompt_id": "",
                    "storyboard": None,
                }

            if source_type == SourceType.PROMPT_ID:
                # 从提示词库复用
                from .prompt_library import get_prompt_library
                library = get_prompt_library()
                record = await library.get(source_value)
                if not record:
                    return {"success": False, "error": f"提示词 {source_value} 不存在"}
                # 标记使用
                await library.mark_used(source_value, success=False)
                return {
                    "success": True,
                    "prompt": record.prompt_text,
                    "prompt_id": source_value,
                    "storyboard": None,
                }

            if source_type == SourceType.HOTSPOT_URL:
                # 热点视频 URL → 拆解 + 沉淀
                from .prompt_storyboard_pipeline import get_prompt_storyboard_pipeline
                pipeline = get_prompt_storyboard_pipeline()
                extract_result = await pipeline.extract_from_hotspot(
                    hotspot_video_url=source_value,
                    owner_user_id=owner_user_id,
                    persist=True,
                )
                if not extract_result.get("success"):
                    return extract_result
                return {
                    "success": True,
                    "prompt": extract_result["prompt"],
                    "prompt_id": extract_result.get("prompt_id", ""),
                    "storyboard": extract_result.get("storyboard"),
                }

            return {"success": False, "error": f"未知 source_type: {source_type}"}
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] Step1 失败: {e}")
            return {"success": False, "error": str(e)}

    async def _step2_config(self, video_config_id: str):
        """Step2: 视频参数配置"""
        try:
            if video_config_id:
                from .video_generation_config import (
                    VideoGenConfig, get_video_gen_config_service,
                )
                svc = get_video_gen_config_service()
                cfg_dict = await svc.get_config(video_config_id)
                if cfg_dict:
                    return VideoGenConfig(
                        config_id=cfg_dict.get("config_id", ""),
                        name=cfg_dict.get("name", ""),
                        duration_seconds=cfg_dict.get("duration_seconds", 30),
                        resolution=cfg_dict.get("resolution", "720p"),
                        aspect_ratio=cfg_dict.get("aspect_ratio", "9:16"),
                        visual_style=cfg_dict.get("visual_style", "modern"),
                        voice_timbre=cfg_dict.get("voice_timbre", "female_warm"),
                        subtitle_style=cfg_dict.get("subtitle_style", "white_bold_black_outline"),
                        bgm_mood=cfg_dict.get("bgm_mood", "upbeat"),
                    )
            # 默认配置
            from .video_generation_config import VideoGenConfig
            return VideoGenConfig()
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] Step2 加载配置失败，用默认: {e}")
            from .video_generation_config import VideoGenConfig
            return VideoGenConfig()

    async def _step3_generate(self, prompt: str, video_config) -> Optional[str]:
        """Step3: 数字人口播视频生成"""
        try:
            from api.services.explainer_video_client import ExplainerVideoClient
            client = ExplainerVideoClient()
            return await client.generate_video(
                prompt=prompt,
                duration=getattr(video_config, "duration_seconds", 30),
                resolution=getattr(video_config, "resolution", "720p"),
                aspect_ratio=getattr(video_config, "aspect_ratio", "9:16"),
                voice_timbre=getattr(video_config, "voice_timbre", "female_warm"),
                visual_style=getattr(video_config, "visual_style", "modern"),
            )
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] Step3 视频生成失败: {e}")
            return None

    async def _step4_create_review(
        self,
        pipeline_id: str,
        video_url: str,
        prompt: str,
        owner_user_id: Optional[int],
    ) -> Optional[str]:
        """Step4: 创建人工复核任务（content_id 关联 pipeline_id）"""
        try:
            from api.services.moderation.review_workflow import (
                get_review_workflow_service, ContentType,
            )
            svc = get_review_workflow_service()
            task = await svc.create_review_task(
                content_type=ContentType.VIDEO.value,
                content_id=f"pipeline_{pipeline_id}",  # 关联流水线
                content_url=video_url,
                content_preview=prompt[:500],
                auto_moderation_result={"pipeline_source": True},
                owner_user_id=owner_user_id,
            )
            return task.review_id
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] Step4 创建复核失败: {e}")
            return None

    async def _step5_schedule_publish(
        self,
        pipeline_id: str,
        video_url: str,
        title: str,
        content: str,
        platforms: List[str],
        owner_user_id: Optional[int],
    ) -> Optional[str]:
        """Step5: 创建定时发布任务（错峰）"""
        try:
            from api.services.scheduling.publish_scheduler import (
                get_publish_scheduler, ScheduledTask,
            )
            scheduler = get_publish_scheduler()

            # 推荐第一个平台的错峰时间
            primary_platform = platforms[0] if platforms else "douyin"
            scheduled_at = scheduler.recommend_publish_time(primary_platform)

            task = ScheduledTask(
                task_id=str(uuid.uuid4())[:8],
                title=title,
                content=content[:500],
                video_path=video_url,
                target_platforms=platforms,
                user_id=owner_user_id or 1,
                source_post_id=f"pipeline_{pipeline_id}",
                scheduled_at=scheduled_at,
                created_at=datetime.utcnow(),
            )
            # 注入 source_pipeline_id（ScheduledTask 动态属性）
            task.source_pipeline_id = pipeline_id

            row_id = await scheduler.schedule_task(task)
            if row_id is None:
                return None
            # 更新 source_pipeline_id 列
            await self._set_schedule_source(row_id, pipeline_id)
            return str(row_id)
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] Step5 创建发布任务失败: {e}")
            return None

    async def _step6_trigger_interaction(
        self,
        pipeline_id: str,
        publish_results: List[Dict[str, Any]],
        owner_user_id: Optional[int],
    ) -> Optional[str]:
        """Step6: 话术库互动 - 选取话术 + 调度互动任务"""
        try:
            from api.services.interactor.script_library import (
                get_script_library, ScriptScene,
            )
            from api.services.interactor.interaction_scheduler import (
                get_interaction_scheduler,
            )

            script_lib = get_script_library()
            interaction_sched = get_interaction_scheduler()

            # 为每个平台的成功发布触发互动
            interaction_task_ids: List[str] = []
            for pr in publish_results:
                if not pr.get("success"):
                    continue
                platform = pr.get("platform", "")
                post_url = pr.get("post_url") or pr.get("url") or ""
                if not post_url:
                    logger.debug(
                        f"[UnifiedPipeline] Step6 平台 {platform} 无 post_url，跳过互动"
                    )
                    continue
                # 从话术库选取评论回复话术
                script = await script_lib.pick_random(
                    platform=platform,
                    script_type="comment",
                    scene=ScriptScene.COMMENT_REPLY,
                    owner_user_id=owner_user_id,
                )
                if not script:
                    logger.debug(f"[UnifiedPipeline] Step6 平台 {platform} 无可用话术")
                    continue
                # 调度互动任务
                task_id = await interaction_sched.schedule_interaction(
                    post_url=post_url,
                    platform=platform,
                    user_id=owner_user_id,
                    delay_seconds=300,  # 发布后 5 分钟开始互动
                    auto_start=True,
                )
                interaction_task_ids.append(task_id)
                logger.info(
                    f"[UnifiedPipeline] Step6 平台 {platform} 互动任务 {task_id} "
                    f"话术: {script.content[:30]}"
                )
            return interaction_task_ids[0] if interaction_task_ids else ""
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] Step6 互动触发失败: {e}")
            return None

    # ==================== 数据访问层 ====================

    async def _create_pipeline_record(
        self,
        pipeline_id: str,
        source_type: str,
        source_value: str,
        video_config_id: str,
        publish_platforms: List[str],
        owner_user_id: Optional[int],
    ) -> None:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO pipeline_tasks "
                        "(pipeline_id, status, source_type, source_value, "
                        " video_config_id, publish_platforms, owner_user_id, created_at, updated_at) "
                        "VALUES (:pid, :st, :syt, :syv, :vcid, :pp, :ouid, NOW(), NOW())"
                    ),
                    {
                        "pid": pipeline_id,
                        "st": PipelineStatus.PENDING,
                        "syt": source_type,
                        "syv": source_value,
                        "vcid": video_config_id,
                        "pp": json.dumps(publish_platforms, ensure_ascii=False),
                        "ouid": owner_user_id,
                    },
                )
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] 创建记录失败: {e}")

    async def _update_status(self, pipeline_id: str, status: str) -> None:
        await self._update_pipeline(pipeline_id, {"status": status})

    async def _update_pipeline(self, pipeline_id: str, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            # 字段映射：Python key → SQL 列
            set_clauses = []
            params: Dict[str, Any] = {"pid": pipeline_id}
            for k, v in fields.items():
                set_clauses.append(f"{k} = :{k}")
                params[k] = v
            set_clauses.append("updated_at = NOW()")
            sql = (
                f"UPDATE pipeline_tasks SET {', '.join(set_clauses)} "
                f"WHERE pipeline_id = :pid"
            )
            async with engine.begin() as conn:
                await conn.execute(sql_text(sql), params)
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] 更新状态失败: {e}")

    async def _mark_failed(self, pipeline_id: str, error: str) -> None:
        await self._update_pipeline(pipeline_id, {
            "status": PipelineStatus.FAILED,
            "error_message": error[:500],
        })

    async def _set_schedule_source(self, row_id: int, pipeline_id: str) -> None:
        """回写 scheduled_publish_tasks.source_pipeline_id"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE scheduled_publish_tasks SET source_pipeline_id = :pid "
                        "WHERE id = :rid"
                    ),
                    {"pid": pipeline_id, "rid": row_id},
                )
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] 回写 schedule source 失败: {e}")

    async def _get_pipeline_by_review(self, review_id: str) -> Optional[Dict[str, Any]]:
        """通过 review_id 反查 pipeline（借助 review 表的 content_id 字段）"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                # 1. 查 review 获取 content_id（格式 pipeline_xxx）
                rows = await conn.execute(
                    sql_text(
                        "SELECT content_id FROM video_review_tasks WHERE review_id = :rid"
                    ),
                    {"rid": review_id},
                )
                row = rows.fetchone()
                if not row or not row[0] or not row[0].startswith("pipeline_"):
                    return None
                pipeline_id = row[0][len("pipeline_"):]
                # 2. 查 pipeline 记录
                rows = await conn.execute(
                    sql_text("SELECT * FROM pipeline_tasks WHERE pipeline_id = :pid"),
                    {"pid": pipeline_id},
                )
                row = rows.fetchone()
                if not row:
                    return None
                return self._row_to_dict(row)
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] 反查 pipeline 失败: {e}")
            return None

    async def get_pipeline_status(self, pipeline_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM pipeline_tasks WHERE pipeline_id = :pid"),
                    {"pid": pipeline_id},
                )
                row = rows.fetchone()
                return self._row_to_dict(row) if row else None
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] 查询状态失败: {e}")
            return None

    async def list_pipelines(self, limit: int = 20) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT * FROM pipeline_tasks ORDER BY created_at DESC LIMIT :l"
                    ),
                    {"l": limit},
                )
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[UnifiedPipeline] 列表查询失败: {e}")
            return []

    def _row_to_dict(self, row) -> Dict[str, Any]:
        return {
            "pipeline_id": row[0],
            "status": row[1],
            "source_type": row[2],
            "source_value": row[3],
            "prompt_id": row[4],
            "prompt_text": row[5],
            "storyboard": row[6],
            "video_config_id": row[7],
            "video_url": row[8],
            "asset_id": row[9],
            "review_id": row[10],
            "schedule_task_id": row[11],
            "publish_results": row[12],
            "interaction_task_id": row[13],
            "publish_platforms": row[14],
            "owner_user_id": row[15],
            "error_message": row[16],
            "created_at": str(row[17]) if row[17] else None,
            "updated_at": str(row[18]) if row[18] else None,
        }


# ============ 单例 ============

_pipeline: Optional[UnifiedPipeline] = None


def get_unified_pipeline() -> UnifiedPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = UnifiedPipeline()
    return _pipeline
