# -*- coding: utf-8 -*-
"""
多平台一键拆解流水线核心服务（platform-agnostic）

8 步流水线：热点 → 视频拆解 → 解说视频 → 文案 → AI选文案 → 填视频URL
          → 平台路由发布 → 触发互动 → 启动监控

与 X 专用的 `api/services/auto_pipeline.py` 平行存在。差异点：
1. 不依赖 `XTwitterPost` 表：源数据由调用方传入 hotspot_item
2. Step 6 按 PLATFORM_CAPABILITIES 路由分发：
   - X：从 env cookie 池取 cookie，调 `_do_publish_to_x`（GraphQL）
   - 其他：调 `MultiPlatformPublisher.publish_to_single_platform`（自带 account_service cookie 池 + 重试）
3. 持久化用新 `auto_pipeline_tasks` 表（不污染 X 专用表）
4. Step 7 触发互动：仅给同平台造势（点赞造势）
5. Step 8 启动监控：仅 X 平台原生支持（写入 `XTwitterMonitoredPost`）
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select

logger = logging.getLogger("auto_pipeline_service")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# ------------------------------------------------------------------------------
# 平台能力矩阵（决定每平台走哪条发布路径）
# ------------------------------------------------------------------------------

PLATFORM_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    # ===== 海外 =====
    "x": {
        "name": "X (Twitter)",
        "region": "global",
        "publisher": "x_graphql",       # 走 _do_publish_to_x（GraphQL + 媒体上传 API）
        "interactor": "x_twitter",
        "cookie_source": "env_pool",       # X 使用 .env 配置的 cookie 池
        "monitor": "x_native",            # 写入 XTwitterMonitoredPost 表
        "max_content": 280,
        "real_publish": True,             # 真实发布（非 DRY-RUN）
    },
    # ===== 国内 =====
    "douyin": {
        "name": "抖音",
        "region": "china",
        "publisher": "multi_publisher",   # 走 MultiPlatformPublisher
        "interactor": "douyin",
        "cookie_source": "account_service",
        "monitor": None,
        "max_content": 2000,
        "real_publish": True,             # 国内平台已有 Playwright 真实发布实现（需配置账号 cookie）
    },
    "xiaohongshu": {
        "name": "小红书",
        "region": "china",
        "publisher": "multi_publisher",
        "interactor": "xiaohongshu",
        "cookie_source": "account_service",
        "monitor": None,
        "max_content": 1000,
        "real_publish": True,             # 抖音已有 Playwright 真实发布实现
    },
    "bilibili": {
        "name": "哔哩哔哩",
        "region": "china",
        "publisher": "multi_publisher",
        "interactor": "bilibili",
        "cookie_source": "account_service",
        "monitor": None,
        "max_content": 2000,
        "real_publish": True,             # 小红书已有 Playwright 真实发布实现
    },
    "weibo": {
        "name": "微博",
        "region": "china",
        "publisher": "multi_publisher",
        "interactor": "weibo",
        "cookie_source": "account_service",
        "monitor": None,
        "max_content": 2000,
        "real_publish": True,             # 哔哩哔哩已有 Playwright 真实发布实现
    },
    "zhihu": {
        "name": "知乎",
        "region": "china",
        "publisher": "multi_publisher",
        "interactor": "zhihu",
        "cookie_source": "account_service",
        "monitor": None,
        "max_content": 10000,
        "real_publish": True,             # 微博已有 Playwright 真实发布实现
    },
    "kuaishou": {
        "name": "快手",
        "region": "china",
        "publisher": "multi_publisher",
        "interactor": "kuaishou",
        "cookie_source": "account_service",
        "monitor": None,
        "max_content": 2000,
        "real_publish": True,             # 快手已有 Playwright 真实发布实现（kuaishou_publisher.py）
    },
}

SUPPORTED_PLATFORMS = list(PLATFORM_CAPABILITIES.keys())


PIPELINE_TIMEOUT_TOTAL = 1800  # 30 分钟总超时


class PipelineCancelledError(Exception):
    """流水线被用户取消"""
    pass


# ------------------------------------------------------------------------------
# 启动入口
# ------------------------------------------------------------------------------

async def start_pipeline(
    *,
    platform: str,
    hotspot_item: Dict[str, Any],
    options: Optional[Dict[str, Any]] = None,
    server_base_url: str = "http://localhost:8000",
    owner_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """启动一条多平台流水线（创建任务 + 异步执行）

    Args:
        platform: 目标平台（x/douyin/xiaohongshu/bilibili/weibo/zhihu）
        hotspot_item: 源热点数据 {post_id, post_url, content, video_url, username}
        options: {skip_video, auto_monitor, trigger_interaction}
        server_base_url: 服务端 base URL（X 发布需要下载视频）
        owner_user_id: 任务所有者（用于账号选择）

    Returns:
        创建的任务 dict（含 task_id）
    """
    if platform not in PLATFORM_CAPABILITIES:
        raise ValueError(f"不支持的平台: {platform}，支持: {SUPPORTED_PLATFORMS}")

    from api.services.auto_pipeline_task_store import get_auto_pipeline_store
    store = get_auto_pipeline_store()
    await store.ensure_table()

    options = options or {}
    task_info = await store.create_task(
        platform=platform,
        source_post_id=str(hotspot_item.get("post_id", "") or ""),
        source_post_url=str(hotspot_item.get("post_url", "") or ""),
        source_post_content=str(hotspot_item.get("content", "") or ""),
        source_post_video=str(hotspot_item.get("video_url", "") or ""),
        source_post_author=str(hotspot_item.get("username", "") or ""),
        options=options,
        owner_user_id=owner_user_id,
    )
    task_id = task_info["task_id"]

    async def _run():
        try:
            await run_pipeline(task_id, server_base_url)
        except asyncio.CancelledError:
            await store.update_task(task_id, status="failed", error_msg="任务被取消")
        except Exception as e:
            logger.error(f"[pipeline] 后台任务异常: {e}", exc_info=True)
            await store.update_task(
                task_id, status="failed",
                error_msg=str(e)[:2000],
                step_detail=f"流水线失败: {str(e)[:200]}",
            )

    asyncio.create_task(_run())
    return task_info


# ------------------------------------------------------------------------------
# 流水线主流程
# ------------------------------------------------------------------------------

async def run_pipeline(task_id: str, server_base_url: str = "http://localhost:8000") -> Dict[str, Any]:
    """执行完整流水线（异步后台任务）

    8 步：拆解 → 解说视频 → 文案 → AI选文案 → 填视频URL
         → 平台路由发布 → 触发互动 → 启动监控
    """
    from api.services.auto_pipeline_task_store import get_auto_pipeline_store
    store = get_auto_pipeline_store()
    task_info = await store.get_task(task_id)
    if not task_info:
        return {"success": False, "error": "任务不存在"}

    platform = task_info["platform"]
    options = task_info.get("options", {}) or {}
    skip_video = bool(options.get("skip_video", False))
    auto_monitor = bool(options.get("auto_monitor", True))
    trigger_interaction = bool(options.get("trigger_interaction", False))
    # 复用已有结果：来自视频拆解 Modal 的拆解文本和已生成视频 URL
    pre_breakdown_text = (options.get("breakdown_text") or "").strip() or ""
    pre_video_url = (options.get("pre_video_url") or "").strip() or ""
    # 复用已编辑文案：来自重试/编辑，跳过 Step3-4
    pre_selected_content = (options.get("pre_selected_content") or "").strip() or ""
    # 是否为重试发布（来自发布中心重试按钮）
    is_retry = bool(options.get("is_retry", False))

    cap = PLATFORM_CAPABILITIES[platform]
    logger.info(
        f"[pipeline] 启动 task_id={task_id} platform={platform} "
        f"real_publish={cap['real_publish']} skip_video={skip_video}"
    )

    # 构造 post 字典（供 ai_agent_client 使用）
    post = {
        "post_id": task_info["source_post_id"],
        "post_url": task_info["source_post_url"],
        "content": task_info["source_post_content"],
        "video_url": task_info["source_post_video"],
        "username": task_info["source_post_author"],
    }

    try:
        await store.update_task(
            task_id, status="running", current_step=0,
            step_detail="流水线启动中...",
        )

        # ========== Step 1: 视频拆解 ==========
        await store.update_task(
            task_id, current_step=1, step_detail="正在进行视频拆解...",
        )
        logger.info(f"[pipeline] Step 1: 视频拆解 platform={platform}")

        from api.services import ai_agent_client

        if pre_breakdown_text:
            # 复用视频拆解 Modal 已生成的拆解文本，跳过 AI 调用（避免重复拆解）
            breakdown_text = pre_breakdown_text
            logger.info(
                f"[pipeline] Step 1: 复用已有拆解文本（长度={len(breakdown_text)}），跳过 AI 拆解"
            )
        else:
            breakdown_text = await ai_agent_client.generate_video_breakdown(post)
        parsed = ai_agent_client.parse_breakdown(breakdown_text)

        await store.update_task(
            task_id, breakdown_text=breakdown_text,
            step_detail=f"拆解完成（{len(parsed.get('storyboard_items', []))} 个分镜）"
                       + ("【复用已有结果】" if pre_breakdown_text else ""),
        )
        logger.info(f"[pipeline] Step 1 完成: 拆解文本长度={len(breakdown_text)}")

        # ========== Step 2: 生成解说视频 ==========
        video_url = ""
        if pre_video_url:
            # 复用视频拆解 Modal 已生成的解说视频 URL，跳过视频生成（避免重复等待）
            video_url = pre_video_url
            await store.update_task(
                task_id, current_step=2, video_url=video_url,
                step_detail=f"复用已有视频（跳过生成）: {video_url}",
            )
            logger.info(
                f"[pipeline] Step 2: 复用已有视频 URL={video_url}，跳过视频生成"
            )
        elif not skip_video:
            try:
                await store.update_task(
                    task_id, current_step=2, step_detail="正在提交解说视频任务...",
                )
                logger.info(f"[pipeline] Step 2: 生成解说视频")

                from api.services.explainer_video_client import (
                    build_explainer_prompt,
                    submit_explainer_video,
                    get_explainer_video_status,
                )

                prompt = build_explainer_prompt(
                    post_content=post.get("content", ""),
                    script=parsed["script"],
                    storyboards=parsed["storyboard_items"],
                    key_points=parsed["key_points"],
                )

                image_urls: List[str] = []
                video_urls: List[str] = []
                if post.get("video_url"):
                    video_urls.append(post["video_url"])
                if post.get("post_url"):
                    video_urls.append(post["post_url"])

                # 读取用户视频生成配置（duration/resolution/aspect_ratio 等）
                # 修复：之前硬编码 5s/480p，导致用户配置的 30s/1080p 被丢弃
                video_cfg_duration = 5
                video_cfg_resolution = "480p"
                video_cfg_aspect_ratio = "9:16"
                try:
                    from api.services.ai.video_generation_config import (
                        get_video_generation_config_service,
                    )
                    cfg_svc = get_video_generation_config_service()
                    # 优先取用户自定义配置（非预设），否则取第一个预设
                    all_cfgs = await cfg_svc.list_configs(
                        owner_user_id=task_info.get("owner_user_id"),
                        include_presets=True,
                    )
                    user_cfg = next(
                        (c for c in all_cfgs if not c.get("is_preset")),
                        all_cfgs[0] if all_cfgs else None,
                    )
                    if user_cfg:
                        video_cfg_duration = int(user_cfg.get("duration_seconds", 5) or 5)
                        video_cfg_resolution = user_cfg.get("resolution", "480p") or "480p"
                        video_cfg_aspect_ratio = user_cfg.get("aspect_ratio", "9:16") or "9:16"
                        logger.info(
                            f"[pipeline] Step 2 使用视频配置 [{user_cfg.get('name', 'N/A')}]: "
                            f"duration={video_cfg_duration}s resolution={video_cfg_resolution} "
                            f"aspect_ratio={video_cfg_aspect_ratio}"
                        )
                except Exception as ve:
                    logger.warning(f"[pipeline] 读取用户视频配置失败(用默认): {ve}")

                video_result = await submit_explainer_video(
                    prompt=prompt,
                    image_urls=image_urls,
                    video_urls=video_urls,
                    duration=video_cfg_duration,
                    resolution=video_cfg_resolution,
                    aspect_ratio=video_cfg_aspect_ratio,
                )
                video_task_id = video_result.get("task_id", "")

                # 轮询视频状态（最多 20 分钟）
                video_timeout = 1200
                video_start = time.time()
                poll_interval = 15

                while time.time() - video_start < video_timeout:
                    await asyncio.sleep(poll_interval)
                    try:
                        status = await get_explainer_video_status(video_task_id)
                        cur_state = status.get("status", "")
                        cur_progress = status.get("progress", 0)
                        result_url = status.get("result_url", "")

                        if cur_state in ("succeeded", "success"):
                            video_url = result_url
                            await store.update_task(
                                task_id, video_url=video_url,
                                step_detail=f"视频生成完成（进度 {cur_progress}%）",
                            )
                            logger.info(f"[pipeline] Step 2 完成: video_url={video_url}")
                            break
                        elif cur_state in ("failed",):
                            await store.update_task(
                                task_id, step_detail=f"视频生成失败: {status.get('error', '')}",
                            )
                            logger.warning(f"[pipeline] Step 2 视频生成失败,降级为纯文字发布")
                            break
                        else:
                            await store.update_task(
                                task_id,
                                step_detail=f"视频生成中... ({cur_progress}%)",
                            )
                    except Exception as e:
                        logger.warning(f"[pipeline] 视频状态查询异常: {e}")

                if not video_url:
                    logger.warning("[pipeline] Step 2 视频未生成,降级为纯文字发布")
            except Exception as e:
                logger.warning(f"[pipeline] Step 2 视频生成异常: {e},降级为纯文字发布")
        else:
            await store.update_task(
                task_id, current_step=2, step_detail="已跳过视频生成",
            )
            logger.info("[pipeline] Step 2: 已跳过(skip_video=True)")

        # ========== Step 3: 生成发布文案 ==========
        await store.update_task(
            task_id, current_step=3, step_detail="正在生成发布文案...",
        )
        logger.info(f"[pipeline] Step 3: 生成发布文案 platform={platform}")

        if pre_selected_content:
            # 复用重试/编辑的文案，跳过 Step3-4 AI 文案生成与选文案
            contents = [pre_selected_content]
            selected_content = pre_selected_content
            await store.update_task(
                task_id,
                candidate_contents=contents,
                selected_content=selected_content,
                step_detail="复用已编辑文案（跳过 AI 生成与选文案）",
            )
            logger.info(
                f"[pipeline] Step 3-4: 复用已编辑文案（长度={len(selected_content)}），跳过 AI 生成"
            )
        else:
            try:
                contents = await ai_agent_client.generate_platform_post_content(
                    post, breakdown_text, platform, count=5,
                )
                await store.update_task(
                    task_id, candidate_contents=contents,
                    step_detail=f"已生成 {len(contents)} 条候选文案",
                )
                logger.info(f"[pipeline] Step 3 完成: 生成 {len(contents)} 条候选文案")
            except Exception as e:
                logger.warning(f"[pipeline] Step 3 文案生成失败: {e}")
                contents = [post.get("content", "")]
                await store.update_task(
                    task_id, candidate_contents=contents,
                    step_detail="文案生成失败,使用原内容降级",
                )

            # ========== Step 4: AI 自动选择最佳文案 ==========
            await store.update_task(
                task_id, current_step=4, step_detail="AI 正在选择最佳文案...",
            )
            logger.info(f"[pipeline] Step 4: AI 自动选文案")

            try:
                selected_content = await _ai_select_best_content(contents, platform)
                await store.update_task(
                    task_id, selected_content=selected_content,
                    step_detail="已选择最佳文案",
                )
                logger.info(f"[pipeline] Step 4 完成: 选中文案长度={len(selected_content)}")
            except Exception as e:
                logger.warning(f"[pipeline] Step 4 AI 选文案失败: {e},使用第一条")
                selected_content = contents[0] if contents else post.get("content", "")
                await store.update_task(
                    task_id, selected_content=selected_content,
                    step_detail="AI选文案失败,使用第一条候选",
                )

        # ========== Step 5: 填入视频 URL ==========
        await store.update_task(
            task_id, current_step=5,
            step_detail=f"视频URL: {video_url or '(无,纯文字发布)'}",
        )
        logger.info(f"[pipeline] Step 5: video_url={video_url or 'None(纯文字)'}")

        # ========== Step 6: 平台路由发布 ==========
        await store.update_task(
            task_id, current_step=6,
            step_detail=f"正在发布到 {cap['name']}...",
        )
        logger.info(
            f"[pipeline] Step 6: 发布到 {platform} (via {cap['publisher']}) "
            f"has_video={bool(video_url)}"
        )

        # 用 try/except 包裹发布调用：即使 _publish_with_route 抛异常（如无可用账号），
        # 也要确保 publish_records 写入失败记录，保证发布中心能看到所有任务
        publish_result: Dict[str, Any] = {}
        publish_error: str = ""
        try:
            publish_result = await _publish_with_route(
                platform=platform,
                cap=cap,
                content=selected_content,
                video_url=video_url,
                post=post,
                server_base_url=server_base_url,
                owner_user_id=task_info.get("owner_user_id"),
                task_id=task_id,
                store=store,
            )
        except Exception as e:
            # 捕获发布异常（无可用账号 / Playwright 失败 / 上传失败等），
            # 不在此处 raise，先写 publish_records 再在下方统一 raise
            publish_error = str(e)
            logger.warning(f"[pipeline] Step 6 发布异常(已捕获，将写记录后抛出): {e}")

        published_post_id = publish_result.get("published_post_id", "")
        published_post_url = publish_result.get("published_post_url", "")
        account_id = publish_result.get("account_id")
        is_publish_success = bool(published_post_id) and not publish_error

        # ========== Step 6.1: 写入 publish_records 表（数据闭环） ==========
        # 注意：无论发布成功还是失败都必须写入，确保发布中心能看到所有记录
        try:
            from api.services.publisher.publish_records_store import get_publish_records_store
            rec_store = get_publish_records_store()
            fail_reason = (
                publish_error
                or publish_result.get("reason")
                or publish_result.get("error")
                or "未知原因"
            )
            await rec_store.save_record(
                task_id=task_id,
                platform=platform,
                account_id=account_id,
                title=post.get("content", "")[:100],
                content=selected_content or post.get("content", ""),
                video_path=video_url if video_url else None,
                post_url=published_post_url,
                platform_id=published_post_id,
                status="success" if is_publish_success else "failed",
                error_message=None if is_publish_success else fail_reason,
                owner_user_id=task_info.get("owner_user_id"),
                source_post_id=post.get("post_id") or post.get("post_url"),
                metadata={
                    "pipeline": True,
                    "is_retry": is_retry,
                    "publisher_type": cap.get("publisher"),
                    "source_platform": post.get("source_platform"),
                    "selected_content": selected_content[:500] if selected_content else "",
                },
            )
            logger.info(
                f"[pipeline] Step 6.1: 已写入 publish_records "
                f"(platform={platform} status={'success' if is_publish_success else 'failed'})"
            )
        except Exception as e:
            logger.warning(f"[pipeline] Step 6.1: 写 publish_records 失败(忽略): {e}")

        if not is_publish_success:
            # real_publish=True 但实际未拿到 post_id → 视为发布失败
            fail_reason = (
                publish_error
                or publish_result.get("reason")
                or publish_result.get("error")
                or "未知原因"
            )
            logger.warning(
                f"[pipeline] Step 6 发布失败: platform={platform} reason={fail_reason}"
            )
            raise RuntimeError(
                f"{cap['name']} 发布失败: {fail_reason}"
            )
        else:
            logger.info(
                f"[pipeline] Step 6 完成: platform={platform} "
                f"post_id={published_post_id} url={published_post_url}"
            )

        # ========== Step 7: 触发互动造势（可选） ==========
        if trigger_interaction:
            await store.update_task(
                task_id, current_step=7,
                step_detail=f"正在触发 {cap['name']} 互动...",
            )
            logger.info(f"[pipeline] Step 7: 触发互动造势")

            try:
                interaction_ok = await _trigger_interaction(
                    platform=platform,
                    cap=cap,
                    target_url=published_post_url or post.get("post_url", ""),
                    target_id=published_post_id,
                )
                await store.update_task(
                    task_id, interaction_triggered=1 if interaction_ok else 0,
                    step_detail="互动已触发" if interaction_ok else "互动触发失败(已跳过)",
                )
                logger.info(f"[pipeline] Step 7 完成: interaction_ok={interaction_ok}")
            except Exception as e:
                logger.warning(f"[pipeline] Step 7 触发互动异常: {e}")
                await store.update_task(
                    task_id, interaction_triggered=0,
                    step_detail=f"互动触发异常: {str(e)[:100]}",
                )
        else:
            await store.update_task(
                task_id, current_step=7, step_detail="已跳过互动触发",
            )
            logger.info("[pipeline] Step 7: 已跳过(trigger_interaction=False)")

        # ========== Step 8: 启动评论监控（仅 X） ==========
        if auto_monitor and cap.get("monitor") == "x_native" and published_post_id:
            await store.update_task(
                task_id, current_step=8,
                step_detail="正在启动评论监控...",
            )
            logger.info(f"[pipeline] Step 8: 启动 X 评论监控 post_id={published_post_id}")

            try:
                monitor_ok = await _start_x_monitor(
                    tweet_id=published_post_id,
                    tweet_url=published_post_url,
                    content=selected_content,
                )
                await store.update_task(
                    task_id, monitor_started=1 if monitor_ok else 0,
                    step_detail="监控已启动" if monitor_ok else "监控启动失败(不影响发布结果)",
                )
            except Exception as e:
                logger.warning(f"[pipeline] Step 8 启动监控异常: {e}")
                await store.update_task(
                    task_id, monitor_started=0,
                    step_detail=f"监控启动异常: {str(e)[:100]}",
                )
        else:
            monitor_reason = "无原生监控支持" if cap.get("monitor") is None else "未启用"
            await store.update_task(
                task_id, current_step=8,
                step_detail=f"已跳过监控({monitor_reason})",
            )
            logger.info(f"[pipeline] Step 8: 已跳过 ({monitor_reason})")

        # ========== 完成 ==========
        await store.update_task(
            task_id, status="completed",
            step_detail=(
                f"完成! 发布到 {cap['name']} "
                f"(post_id={published_post_id})"
            ),
        )
        logger.info(
            f"[pipeline] 完成: task_id={task_id} platform={platform} "
            f"published_post_id={published_post_id}"
        )

        return {
            "success": True,
            "task_id": task_id,
            "platform": platform,
            "published_post_id": published_post_id,
            "published_post_url": published_post_url,
            "account_id": account_id,
        }

    except Exception as e:
        logger.error(f"[pipeline] 流水线失败: {e}", exc_info=True)
        await store.update_task(
            task_id, status="failed",
            error_msg=str(e)[:2000],
            step_detail=f"流水线失败: {str(e)[:200]}",
        )
        # 流水线失败 → 发送发布失败预警到 alert_center
        try:
            from api.services.alert.alert_center import emit_publish_failure
            await emit_publish_failure(
                platform=platform,
                account_label=cap.get("name", platform),
                error_message=str(e),
                content_preview=selected_content[:200] if selected_content else "",
                post_id=post.get("post_id", "") if post else "",
                owner_user_id=task_info.get("owner_user_id") if task_info else None,
            )
        except Exception as ae:
            logger.warning(f"[pipeline] 发送发布失败预警异常(非致命): {ae}")
        return {
            "success": False,
            "task_id": task_id,
            "platform": platform,
            "error": str(e),
        }


# ------------------------------------------------------------------------------
# Step 6: 平台路由发布
# ------------------------------------------------------------------------------

async def _publish_with_route(
    *,
    platform: str,
    cap: Dict[str, Any],
    content: str,
    video_url: str,
    post: Dict[str, Any],
    server_base_url: str,
    owner_user_id: Optional[int],
    task_id: str,
    store,
) -> Dict[str, Any]:
    """根据平台能力矩阵路由到不同的发布实现"""

    publisher_type = cap.get("publisher")

    if publisher_type == "x_graphql":
        # ===== X 平台：GraphQL + 媒体上传 API =====
        return await _publish_to_x(
            content=content,
            video_url=video_url,
            server_base_url=server_base_url,
            task_id=task_id,
            store=store,
        )

    elif publisher_type == "multi_publisher":
        # ===== 其他平台：MultiPlatformPublisher（account_service cookie 池 + 重试） =====
        return await _publish_to_multi_platform(
            platform=platform,
            content=content,
            video_url=video_url,
            title=post.get("content", "")[:100],
            owner_user_id=owner_user_id or 1,
            cap=cap,
        )

    else:
        raise ValueError(f"未知的 publisher 类型: {publisher_type}")


async def _publish_to_x(
    *,
    content: str,
    video_url: str,
    server_base_url: str,
    task_id: str,
    store,
) -> Dict[str, Any]:
    """X 平台发布：从 cookie 池取 cookie + 调 _do_publish_to_x（GraphQL）

    与旧 auto_pipeline.py 行为对齐：收集所有 cookie 候选，逐个尝试。
    """
    from api.routers.x_twitter_workbench import _do_publish_to_x

    # 收集所有可用 cookie（cookie 池 + 单 cookie 兜底）
    cookie_candidates: List[str] = []
    try:
        from api.services.cookie_pool_manager import _parse_pool_from_env
        pool_cookies = _parse_pool_from_env()
        cookie_candidates.extend(pool_cookies)
    except Exception as e:
        logger.warning(f"[pipeline] 加载 cookie 池失败: {e}")

    single_cookie = os.getenv("X_TWITTER_COOKIES", "")
    if single_cookie and single_cookie not in cookie_candidates:
        cookie_candidates.append(single_cookie)

    # 过滤无效 cookie
    cookie_candidates = [c for c in cookie_candidates if "auth_token" in c]
    if not cookie_candidates:
        raise ValueError("无可用 X cookie（X_TWITTER_COOKIES 未配置且 cookie 池为空）")

    logger.info(
        f"[pipeline] X 发布: 共 {len(cookie_candidates)} 个 cookie 候选, 逐个尝试"
    )

    publish_result = None
    last_error = ""
    for idx, cookie_str in enumerate(cookie_candidates, 1):
        try:
            await store.update_task(
                task_id,
                step_detail=f"正在用第 {idx}/{len(cookie_candidates)} 个 X 账号发布...",
            )
            logger.info(f"[pipeline] 尝试用 cookie #{idx}/{len(cookie_candidates)} 发布")
            result = await _do_publish_to_x(
                cookie_str,
                content,
                video_url if video_url else None,
                server_base_url,
            )
            if result.get("success", False) and result.get("tweet_id"):
                publish_result = result
                logger.info(f"[pipeline] cookie #{idx} 发布成功!")
                break
            else:
                err = result.get("error", "返回无 tweet_id")
                last_error = err
                logger.warning(f"[pipeline] cookie #{idx} 发布失败: {err}")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[pipeline] cookie #{idx} 发布异常: {e}")
            # 限额错误继续尝试下一个 cookie
            if "daily limit" in last_error.lower() or "344" in last_error:
                continue

    if not publish_result or not publish_result.get("tweet_id"):
        raise RuntimeError(f"所有 X cookie 均发布失败，最后错误: {last_error}")

    return {
        "published_post_id": publish_result.get("tweet_id", ""),
        "published_post_url": publish_result.get("tweet_url", ""),
        "account_id": None,  # X cookie 池不绑定到 publisher_accounts 表
        "raw": publish_result,
    }


async def _publish_to_multi_platform(
    *,
    platform: str,
    content: str,
    video_url: str,
    title: str,
    owner_user_id: int,
    cap: Dict[str, Any],
) -> Dict[str, Any]:
    """通过 MultiPlatformPublisher 发布（其他平台）

    若平台无真实发布实现（real_publish=False），仍走一遍流程：
    - 无可用账号时抛出 RuntimeError（让流水线整体失败并发送预警）
    - 有账号时按平台业务逻辑执行（成功则返回真实 post_id）
    """
    from api.services.publisher.multi_publisher import MultiPlatformPublisher
    from api.services.publisher.publisher_factory import PublisherFactory

    publisher = MultiPlatformPublisher()

    # 检查平台是否有 publisher 注册
    if not PublisherFactory.is_supported(platform):
        logger.warning(
            f"[pipeline] 平台 {platform} 无 publisher 注册"
        )
        raise RuntimeError(f"{platform} 暂无发布实现（无 publisher 注册）")

    # 构造发布任务
    try:
        result = await publisher.publish_to_single_platform(
            platform=platform,
            title=title,
            content=content,
            video_path=video_url if video_url else None,
            user_id=owner_user_id,
            # 流水线场景由 Step 6.1 统一写 publish_records，跳过避免重复
            skip_publish_record=True,
        )
        if result.success:
            logger.info(
                f"[pipeline] {platform} 发布成功: post_id={result.platform_id} url={result.url}"
            )
            return {
                "published_post_id": result.platform_id or "",
                "published_post_url": result.url or "",
                "account_id": result.account_id,
                "raw": {
                    "success": result.success,
                    "message": result.message,
                    "status": result.status,
                },
            }
        else:
            logger.warning(
                f"[pipeline] {platform} 发布失败: {result.error}"
            )
            # 真实发布失败 → 发送发布失败预警到 alert_center
            if cap.get("real_publish"):
                try:
                    from api.services.alert.alert_center import emit_publish_failure
                    await emit_publish_failure(
                        platform=platform,
                        account_label=cap.get("name", platform),
                        error_message=result.error or f"{platform} 发布失败",
                        content_preview=content[:200] if content else "",
                        owner_user_id=owner_user_id,
                    )
                except Exception as ae:
                    logger.warning(f"[pipeline] 发送发布失败预警异常(非致命): {ae}")
            # 失败抛异常 → 流水线整体失败并发送预警（不再走 DRY-RUN 兜底）
            raise RuntimeError(f"{platform} 发布失败: {result.error or '未知原因'}")
    except RuntimeError:
        raise  # 透传发布失败异常
    except Exception as e:
        logger.exception(f"[pipeline] {platform} 发布异常")
        # 真实发布异常 → 发送发布失败预警到 alert_center
        if cap.get("real_publish"):
            try:
                from api.services.alert.alert_center import emit_publish_failure
                await emit_publish_failure(
                    platform=platform,
                    account_label=cap.get("name", platform),
                    error_message=str(e),
                    content_preview=content[:200] if content else "",
                    owner_user_id=owner_user_id,
                )
            except Exception as ae:
                logger.warning(f"[pipeline] 发送发布失败预警异常(非致命): {ae}")
        raise RuntimeError(f"{platform} 发布异常: {e}")


# ------------------------------------------------------------------------------
# Step 7: 触发互动
# ------------------------------------------------------------------------------

async def _trigger_interaction(
    *,
    platform: str,
    cap: Dict[str, Any],
    target_url: str,
    target_id: str,
) -> bool:
    """触发同平台点赞造势（给刚发布的帖子增加互动量）

    Returns:
        True 表示互动已触发（不保证全部成功）
    """
    if not target_url:
        logger.warning(f"[pipeline] 无 target_url,跳过互动触发")
        return False

    interactor_name = cap.get("interactor")
    if not interactor_name:
        logger.info(f"[pipeline] {platform} 无 interactor,跳过互动触发")
        return False

    try:
        from api.services.interactor.interactor_factory import InteractorFactory
        from api.services.interactor.interaction_models import (
            InteractionTask, InteractionType,
        )

        if not InteractorFactory.is_supported(interactor_name):
            logger.info(
                f"[pipeline] interactor {interactor_name} 未注册,跳过互动触发"
            )
            return False

        task = InteractionTask(
            task_id=str(uuid.uuid4())[:8],
            user_id=1,
            target_platforms=[interactor_name],
            interaction_type=InteractionType.LIKE.value,
            target_url=target_url,
            target_id=target_id,
            content="",
        )

        from api.services.interactor.multi_interactor import get_multi_interactor
        result_task = await get_multi_interactor().interact_across_platforms(
            task, use_account_pool=True
        )

        success_count = sum(
            1 for r in result_task.platform_results.values() if r.success
        )
        logger.info(
            f"[pipeline] 互动触发完成: {success_count}/1 平台成功点赞"
        )
        return success_count > 0
    except Exception as e:
        logger.warning(f"[pipeline] 触发互动异常: {e}")
        return False


# ------------------------------------------------------------------------------
# Step 8: 启动 X 评论监控
# ------------------------------------------------------------------------------

async def _start_x_monitor(
    *,
    tweet_id: str,
    tweet_url: str,
    content: str,
) -> bool:
    """将新推文加入 X 评论监控表，并确保监控服务运行

    与旧 auto_pipeline.py 行为对齐：写入 XTwitterMonitoredPost 表，
    然后确保 comment_reply_monitor 运行。
    """
    if not tweet_id:
        return False

    try:
        from database.db_session import get_session
        from database.models import XTwitterMonitoredPost

        now_ts = int(time.time())
        async with get_session() as session:
            existing = (await session.execute(
                select(XTwitterMonitoredPost).where(
                    XTwitterMonitoredPost.post_id == tweet_id
                )
            )).scalar_one_or_none()

            if existing:
                existing.monitoring = 1
                existing.post_content = content[:500]
                existing.last_modify_ts = now_ts
            else:
                new_post = XTwitterMonitoredPost(
                    post_id=tweet_id,
                    post_url=tweet_url,
                    post_content=content[:500],
                    post_username="",
                    monitoring=1,
                    add_ts=now_ts,
                    last_modify_ts=now_ts,
                )
                session.add(new_post)
            await session.commit()

        # 确保评论监控服务运行
        try:
            from api.services.comment_reply_monitor import ensure_monitor_running
            await ensure_monitor_running()
        except Exception as e:
            logger.warning(f"[pipeline] ensure_monitor_running 失败(不影响监控表写入): {e}")

        logger.info(f"[pipeline] 已将推文 {tweet_id} 加入评论监控表")
        return True
    except Exception as e:
        logger.warning(f"[pipeline] 启动 X 监控失败: {e}")
        return False


# ------------------------------------------------------------------------------
# 辅助：AI 选最佳文案
# ------------------------------------------------------------------------------

async def _ai_select_best_content(contents: List[str], platform: str = "x") -> str:
    """AI 自动选择最佳文案（按平台调性评分）"""
    from api.services import ai_agent_client

    platform_name = PLATFORM_CAPABILITIES.get(platform, {}).get("name", platform)
    prompt = f"""你是 {platform_name} 内容专家。请从以下 {len(contents)} 条候选文案中,
选出综合得分最高的一条。

评分维度(每项 1-10 分):
1. 吸引力:是否能在第一句话抓住眼球
2. 信息密度:是否涵盖了核心要点
3. 互动引导:是否鼓励评论、转发、点赞
4. 语言流畅:是否自然、有节奏感
5. 平台调性:是否符合 {platform_name} 的风格

候选文案:
"""
    for i, c in enumerate(contents, 1):
        prompt += f"\n{i}. {c}"

    prompt += f"""

请直接输出综合得分最高的那一条文案内容(只输出文案本身,不要编号、解释或其他内容)。"""

    messages = [
        {"role": "system", "content": f"你是资深 {platform_name} 内容专家。"},
        {"role": "user", "content": prompt},
    ]

    return await ai_agent_client._chat(messages, temperature=0.3, max_tokens=500)


# ------------------------------------------------------------------------------
# 查询 / 取消
# ------------------------------------------------------------------------------

async def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    from api.services.auto_pipeline_task_store import get_auto_pipeline_store
    return await get_auto_pipeline_store().get_task(task_id)


async def list_tasks(
    *,
    platform: Optional[str] = None,
    status: Optional[str] = None,
    owner_user_id: Optional[int] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    from api.services.auto_pipeline_task_store import get_auto_pipeline_store
    return await get_auto_pipeline_store().list_tasks(
        platform=platform,
        status=status,
        owner_user_id=owner_user_id,
        limit=limit,
    )


async def cancel_task(task_id: str) -> bool:
    from api.services.auto_pipeline_task_store import get_auto_pipeline_store
    return await get_auto_pipeline_store().cancel_task(task_id)


def get_supported_platforms() -> List[Dict[str, Any]]:
    """返回支持全流程的平台列表（含能力标注，供前端展示）"""
    return [
        {
            "platform": pid,
            "name": cap["name"],
            "region": cap["region"],
            "real_publish": cap.get("real_publish", False),
            "publisher": cap.get("publisher"),
            "interactor": cap.get("interactor"),
            "monitor": cap.get("monitor"),
            "max_content": cap.get("max_content", 2000),
        }
        for pid, cap in PLATFORM_CAPABILITIES.items()
    ]
