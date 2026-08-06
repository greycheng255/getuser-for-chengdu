# -*- coding: utf-8 -*-
"""
X Twitter 自动化流水线服务

一键完成: 视频拆解 → 生成解说视频 → 生成发布文案 → AI选最佳文案 → 发布到X
全流程编排器,每步都有容错降级策略。
"""
import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from database.db_session import get_session
from database.models import (
    XTwitterAutoPipelineTask,
    XTwitterVideoBreakdown,
    XTwitterPost,
    XTwitterTrendingPost,
)

logger = logging.getLogger("auto_pipeline")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False


STEP_NAMES = {
    0: "待启动",
    1: "视频拆解",
    2: "生成解说视频",
    3: "生成发布文案",
    4: "AI自动选文案",
    5: "自动填入视频URL",
    6: "发布到X",
}

PIPELINE_TIMEOUT_TOTAL = 1800  # 30min total timeout


class PipelineCancelledError(Exception):
    """流水线被用户取消"""
    pass


async def create_task(post_id: str, skip_video: bool = False) -> Dict[str, Any]:
    """创建流水线任务记录"""
    task_id = str(uuid.uuid4())
    now = int(time.time())
    async with get_session() as session:
        task = XTwitterAutoPipelineTask(
            task_id=task_id,
            post_id=post_id,
            status="pending",
            current_step=0,
            step_detail="任务已创建,等待执行",
            skip_video=1 if skip_video else 0,
            add_ts=now,
            update_ts=now,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

    logger.info(f"[pipeline] 创建任务 task_id={task_id} post_id={post_id}")
    return _task_to_dict(task)


def _task_to_dict(task: XTwitterAutoPipelineTask) -> Dict[str, Any]:
    return {
        "id": task.id,
        "task_id": task.task_id,
        "post_id": task.post_id,
        "status": task.status,
        "current_step": task.current_step,
        "step_name": STEP_NAMES.get(task.current_step, "未知"),
        "step_detail": task.step_detail or "",
        "breakdown_id": task.breakdown_id,
        "video_task_id": task.video_task_id or "",
        "video_url": task.video_url or "",
        "video_status": task.video_status or "",
        "candidate_contents": json.loads(task.candidate_contents or "[]"),
        "selected_content": task.selected_content or "",
        "tweet_id": task.tweet_id or "",
        "tweet_url": task.tweet_url or "",
        "error_msg": task.error_msg or "",
        "skip_video": task.skip_video,
        "add_ts": task.add_ts,
        "update_ts": task.update_ts,
    }


async def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """查询任务状态"""
    async with get_session() as session:
        result = await session.execute(
            select(XTwitterAutoPipelineTask).where(XTwitterAutoPipelineTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            return _task_to_dict(task)
    return None


async def _update_task(task_id: str, **kwargs) -> None:
    """更新任务字段"""
    async with get_session() as session:
        result = await session.execute(
            select(XTwitterAutoPipelineTask).where(XTwitterAutoPipelineTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            return
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        task.update_ts = int(time.time())
        await session.commit()


async def _get_post(post_id: str) -> Optional[Dict[str, Any]]:
    """获取原推文信息

    X 平台从数据库查；非 X 平台 post_id 是合成 ID（如 douyin_1），
    从 hotpoint_fetcher 缓存中按 platform + rank 查找。
    """
    from api.routers.x_twitter_workbench import _get_post_by_id
    async with get_session() as session:
        post = await _get_post_by_id(session, post_id)
        if post:
            return {
                "post_id": post.post_id,
                "post_url": post.post_url,
                "content": post.content,
                "video_url": post.video_url,
                "username": post.username,
            }

    # 非 X 平台 fallback：从 hotpoint_fetcher 缓存查找
    # post_id 格式: {platform}_{rank}，如 douyin_1、bili_3
    # _trending_from_hotpoint 中 enumerate 从 1 开始，rank 取 it.get('rank', idx)
    parts = post_id.rsplit("_", 1)
    if len(parts) == 2:
        platform, rank_str = parts
        try:
            rank = int(rank_str)
        except ValueError:
            return None
        try:
            from api.services.hotpoint_fetcher import _get_stale_cache
            items = _get_stale_cache(platform)
            if items:
                for idx, it in enumerate(items, 1):
                    if it.get("rank", idx) == rank:
                        url = it.get("url", "")
                        extra = it.get("extra", {}) or {}
                        video_url = extra.get("video_url", "")
                        if not video_url and url:
                            video_url = f"{url}/video/1"
                        return {
                            "post_id": post_id,
                            "post_url": url,
                            "content": it.get("title", "") or it.get("content", ""),
                            "video_url": video_url,
                            "username": it.get("author", "") or platform,
                        }
        except Exception as e:
            logger.warning(f"[pipeline] _get_post fallback hotpoint cache failed: {e}")

    return None


async def run_pipeline(task_id: str, server_base_url: str = "http://localhost:8000") -> Dict[str, Any]:
    """执行完整流水线 (异步后台任务)"""
    task_info = await get_task(task_id)
    if not task_info:
        return {"success": False, "error": "任务不存在"}

    post_id = task_info["post_id"]
    skip_video = task_info["skip_video"] == 1

    try:
        await _update_task(task_id, status="running", current_step=0, step_detail="流水线启动中...")

        # ========== Step 1: 视频拆解 ==========
        await _update_task(task_id, current_step=1, step_detail="正在进行视频拆解...")
        logger.info(f"[pipeline] Step 1: 视频拆解 post_id={post_id}")

        post = await _get_post(post_id)
        if not post:
            raise ValueError(f"推文 {post_id} 不存在")

        from api.services import ai_agent_client

        breakdown_text = await ai_agent_client.generate_video_breakdown(post)
        parsed = ai_agent_client.parse_breakdown(breakdown_text)

        # 保存拆解结果
        async with get_session() as session:
            existing = (await session.execute(
                select(XTwitterVideoBreakdown).where(XTwitterVideoBreakdown.post_id == post_id)
            )).scalars().first()

            if existing:
                existing.script = parsed["script"]
                existing.storyboards = json.dumps(parsed["storyboard_items"], ensure_ascii=False)
                existing.key_points = json.dumps(parsed["key_points"], ensure_ascii=False)
                existing.suggested_comments = json.dumps(parsed["suggested_comments"], ensure_ascii=False)
            else:
                new_bd = XTwitterVideoBreakdown(
                    post_id=post_id,
                    post_url=post.get("post_url", ""),
                    script=parsed["script"],
                    storyboards=json.dumps(parsed["storyboard_items"], ensure_ascii=False),
                    key_points=json.dumps(parsed["key_points"], ensure_ascii=False),
                    suggested_comments=json.dumps(parsed["suggested_comments"], ensure_ascii=False),
                    add_ts=int(time.time()),
                )
                session.add(new_bd)
                await session.flush()
                existing = new_bd
            await session.commit()
            breakdown_id = existing.id

        await _update_task(task_id, breakdown_id=breakdown_id)
        logger.info(f"[pipeline] Step 1 完成: 拆解 ID={breakdown_id}")

        # ========== Step 2: 生成解说视频 ==========
        video_url = ""
        video_task_id = ""
        video_status = ""

        if not skip_video:
            try:
                await _update_task(task_id, current_step=2, step_detail="正在提交解说视频任务...")
                logger.info(f"[pipeline] Step 2: 生成解说视频")

                from api.services.explainer_video_client import (
                    build_explainer_prompt,
                    submit_explainer_video,
                    get_explainer_video_status,
                    normalize_media_urls,
                    extract_video_frames,
                )

                prompt = build_explainer_prompt(
                    post_content=post.get("content", ""),
                    script=parsed["script"],
                    storyboards=parsed["storyboard_items"],
                    key_points=parsed["key_points"],
                )

                image_urls = []
                video_urls = []
                if post.get("video_url"):
                    video_urls.append(post["video_url"])
                if post.get("post_url"):
                    video_urls.append(post["post_url"])

                video_result = await submit_explainer_video(
                    prompt=prompt,
                    image_urls=image_urls,
                    video_urls=video_urls,
                )
                video_task_id = video_result.get("task_id", "")
                video_status = "submitting"

                await _update_task(task_id, video_task_id=video_task_id, video_status="submitting")

                # 轮询视频生成状态 (最多等待 20 分钟)
                video_timeout = 1200  # 20min
                video_start = time.time()
                poll_interval = 15  # 15s per poll

                while time.time() - video_start < video_timeout:
                    await asyncio.sleep(poll_interval)
                    try:
                        status = await get_explainer_video_status(video_task_id)
                        cur_state = status.get("status", "")
                        cur_progress = status.get("progress", 0)
                        result_url = status.get("result_url", "")

                        video_status = cur_state
                        if cur_state in ("succeeded", "success"):
                            video_url = result_url
                            await _update_task(
                                task_id,
                                video_status="succeeded",
                                video_url=video_url,
                                step_detail=f"视频生成完成",
                            )
                            logger.info(f"[pipeline] Step 2 完成: 视频URL={video_url}")
                            break
                        elif cur_state in ("failed",):
                            video_status = "failed"
                            await _update_task(
                                task_id,
                                video_status="failed",
                                step_detail=f"视频生成失败: {status.get('error', '')}",
                            )
                            logger.warning(f"[pipeline] Step 2 视频生成失败,降级为纯文字发布")
                            break
                        else:
                            await _update_task(
                                task_id,
                                video_status=cur_state,
                                step_detail=f"视频生成中... ({cur_progress}%)",
                            )
                    except Exception as e:
                        logger.warning(f"[pipeline] 视频状态查询异常: {e}")

                if not video_url and video_status != "failed":
                    video_status = "timeout"
                    await _update_task(task_id, video_status="timeout")
                    logger.warning("[pipeline] Step 2 视频生成超时,降级为纯文字发布")

            except Exception as e:
                video_status = "error"
                await _update_task(task_id, video_status="error", step_detail=f"视频生成异常: {e}")
                logger.warning(f"[pipeline] Step 2 视频生成异常: {e},降级为纯文字发布")
        else:
            await _update_task(task_id, current_step=2, step_detail="已跳过视频生成")
            logger.info("[pipeline] Step 2: 已跳过(skip_video=True)")

        # ========== Step 3: 生成发布文案 ==========
        await _update_task(task_id, current_step=3, step_detail="正在生成发布文案...")
        logger.info(f"[pipeline] Step 3: 生成发布文案")

        try:
            contents = await ai_agent_client.generate_x_post_content(
                post,
                f"""【脚本分析】\n{parsed['script']}\n\n【分镜拆解】\n{json.dumps(parsed['storyboard_items'], ensure_ascii=False)}\n\n【关键要点】\n{json.dumps(parsed['key_points'], ensure_ascii=False)}""",
                count=5,
            )
            await _update_task(
                task_id,
                candidate_contents=json.dumps(contents, ensure_ascii=False),
                step_detail=f"已生成 {len(contents)} 条候选文案",
            )
            logger.info(f"[pipeline] Step 3 完成: 生成 {len(contents)} 条候选文案")
        except Exception as e:
            logger.warning(f"[pipeline] Step 3 文案生成失败: {e}")
            contents = [post.get("content", "")]
            await _update_task(
                task_id,
                candidate_contents=json.dumps(contents, ensure_ascii=False),
                step_detail=f"文案生成失败,使用原推文内容降级",
            )

        # ========== Step 4: AI 自动选择最佳文案 ==========
        await _update_task(task_id, current_step=4, step_detail="AI 正在选择最佳文案...")
        logger.info(f"[pipeline] Step 4: AI 自动选文案")

        selected_content = ""
        try:
            selected_content = await _ai_select_best_content(contents)
            await _update_task(
                task_id,
                selected_content=selected_content,
                step_detail="已选择最佳文案",
            )
            logger.info(f"[pipeline] Step 4 完成: 选中文案={selected_content[:60]}")
        except Exception as e:
            logger.warning(f"[pipeline] Step 4 AI 选文案失败: {e},使用第一条")
            selected_content = contents[0] if contents else post.get("content", "")
            await _update_task(
                task_id,
                selected_content=selected_content,
                step_detail=f"AI选文案失败,使用第一条候选",
            )

        # ========== Step 5: 自动填入视频 URL ==========
        await _update_task(
            task_id,
            current_step=5,
            step_detail=f"视频URL: {video_url or '(无,纯文字发布)'}",
        )
        logger.info(f"[pipeline] Step 5: 视频URL={video_url or 'None(纯文字)'}")

        # ========== Step 6: 发布到 X ==========
        await _update_task(task_id, current_step=6, step_detail="正在发布到 X...")
        logger.info(f"[pipeline] Step 6: 发布到 X, 有视频={bool(video_url)}")

        from api.routers.x_twitter_workbench import _do_publish_to_x

        # 收集所有可用 cookie（cookie 池 + 单 cookie 兜底），轮换尝试
        cookie_candidates = []
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
            raise ValueError("无可用 cookie（X_TWITTER_COOKIES 未配置且 cookie 池为空）")

        logger.info(f"[pipeline] 共 {len(cookie_candidates)} 个 cookie 候选, 逐个尝试发布")

        publish_result = None
        last_error = ""
        for idx, cookie_str in enumerate(cookie_candidates, 1):
            try:
                await _update_task(
                    task_id,
                    step_detail=f"正在用第 {idx}/{len(cookie_candidates)} 个账号发布...",
                )
                logger.info(f"[pipeline] 尝试用 cookie #{idx}/{len(cookie_candidates)} 发布")
                result = await _do_publish_to_x(
                    cookie_str,
                    selected_content,
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
                # 如果是限额错误，继续尝试下一个 cookie
                if "daily limit" in last_error.lower() or "344" in last_error:
                    continue

        if not publish_result or not publish_result.get("tweet_id"):
            raise RuntimeError(f"所有 cookie 均发布失败，最后错误: {last_error}")

        tweet_id = publish_result.get("tweet_id", "")
        tweet_url = publish_result.get("tweet_url", "")

        # 发布成功后自动加入评论监控表（与 publish_to_x 接口逻辑一致）
        if tweet_id:
            try:
                from database.models import XTwitterMonitoredPost
                now_ts = int(time.time())
                async with get_session() as session:
                    existing = (await session.execute(
                        select(XTwitterMonitoredPost).where(XTwitterMonitoredPost.post_id == tweet_id)
                    )).scalar_one_or_none()

                    if existing:
                        existing.monitoring = 1
                        existing.post_content = selected_content[:500]
                        existing.last_modify_ts = now_ts
                    else:
                        new_post = XTwitterMonitoredPost(
                            post_id=tweet_id,
                            post_url=tweet_url,
                            post_content=selected_content[:500],
                            post_username="",
                            monitoring=1,
                            add_ts=now_ts,
                            last_modify_ts=now_ts,
                        )
                        session.add(new_post)
                    await session.commit()
                logger.info(f"[pipeline] 已将推文 {tweet_id} 加入评论监控表")
            except Exception as mon_err:
                logger.warning(f"[pipeline] 加入监控表失败(不影响发布结果): {mon_err}")

        await _update_task(
            task_id,
            tweet_id=tweet_id,
            tweet_url=tweet_url,
            status="completed",
            step_detail=f"发布成功! 推文ID={tweet_id}",
        )
        logger.info(f"[pipeline] 完成: tweet_id={tweet_id} url={tweet_url}")

        return {
            "success": True,
            "task_id": task_id,
            "tweet_id": tweet_id,
            "tweet_url": tweet_url,
        }

    except Exception as e:
        logger.error(f"[pipeline] 流水线失败: {e}", exc_info=True)
        await _update_task(
            task_id,
            status="failed",
            error_msg=str(e)[:2000],
            step_detail=f"流水线失败: {str(e)[:200]}",
        )
        return {
            "success": False,
            "task_id": task_id,
            "error": str(e),
        }


async def _ai_select_best_content(contents: List[str]) -> str:
    """AI 自动选择最佳文案"""
    from api.services import ai_agent_client

    prompt = f"""你是 X(Twitter) 内容专家。请从以下 {len(contents)} 条候选推文中,
选出综合得分最高的一条。

评分维度(每项 1-10 分):
1. 吸引力:是否能在第一句话抓住眼球
2. 信息密度:是否涵盖了核心要点
3. 互动引导:是否鼓励评论、转发、点赞
4. 语言流畅:是否自然、有节奏感
5. X 调性:是否符合 X 平台的风格(简洁、有力、话题性强)

候选文案:
"""
    for i, c in enumerate(contents, 1):
        prompt += f"\n{i}. {c}"

    prompt += """

请直接输出综合得分最高的那一条文案内容(只输出文案本身,不要编号、解释或其他内容)。"""

    messages = [
        {"role": "system", "content": "你是资深社交媒体内容专家,擅长创作战术性推文。"},
        {"role": "user", "content": prompt},
    ]

    return await ai_agent_client._chat(messages, temperature=0.3, max_tokens=500)


async def start_pipeline(post_id: str, skip_video: bool = False, server_base_url: str = "http://localhost:8000") -> Dict[str, Any]:
    """启动流水线(创建任务 + 异步执行)"""
    task_info = await create_task(post_id, skip_video)
    task_id = task_info["task_id"]

    async def _run():
        try:
            await run_pipeline(task_id, server_base_url)
        except asyncio.CancelledError:
            await _update_task(task_id, status="failed", error_msg="任务被取消")
        except Exception as e:
            logger.error(f"[pipeline] 后台任务异常: {e}", exc_info=True)
            await _update_task(task_id, status="failed", error_msg=str(e)[:2000])

    asyncio.create_task(_run())
    return task_info


async def cancel_pipeline(task_id: str) -> bool:
    """取消正在执行的流水线"""
    task = await get_task(task_id)
    if not task:
        return False
    if task["status"] in ("completed", "failed"):
        return False
    await _update_task(task_id, status="failed", error_msg="用户手动取消", step_detail="已取消")
    return True


async def list_pipelines(limit: int = 20) -> List[Dict[str, Any]]:
    """查询最近的流水线任务"""
    async with get_session() as session:
        result = await session.execute(
            select(XTwitterAutoPipelineTask)
            .order_by(XTwitterAutoPipelineTask.add_ts.desc())
            .limit(limit)
        )
        tasks = result.scalars().all()
    return [_task_to_dict(t) for t in tasks]
