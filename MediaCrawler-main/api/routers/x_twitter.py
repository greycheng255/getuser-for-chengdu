# -*- coding: utf-8 -*-
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_session import get_session
from database.models import XTwitterPost, XTwitterComment, XTwitterVideoBreakdown, XTwitterSentComment

router = APIRouter(prefix="/x-twitter", tags=["x-twitter"])


@router.get("/posts")
async def get_posts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(None),
    has_video: bool = Query(None)
):
    async with get_session() as session:
        stmt = select(XTwitterPost).order_by(XTwitterPost.add_ts.desc())
        
        if keyword:
            stmt = stmt.where(XTwitterPost.content.like(f"%{keyword}%") | XTwitterPost.source_keyword.like(f"%{keyword}%"))
        
        if has_video is not None:
            if has_video:
                stmt = stmt.where(XTwitterPost.video_url.isnot(None), XTwitterPost.video_url != "")
            else:
                stmt = stmt.where((XTwitterPost.video_url.is_(None)) | (XTwitterPost.video_url == ""))
        
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        
        result = await session.execute(stmt)
        posts = result.scalars().all()
        
        count_stmt = select(func.count(XTwitterPost.id))
        if keyword:
            count_stmt = count_stmt.where(XTwitterPost.content.like(f"%{keyword}%") | XTwitterPost.source_keyword.like(f"%{keyword}%"))
        if has_video is not None:
            if has_video:
                count_stmt = count_stmt.where(XTwitterPost.video_url.isnot(None), XTwitterPost.video_url != "")
            else:
                count_stmt = count_stmt.where((XTwitterPost.video_url.is_(None)) | (XTwitterPost.video_url == ""))
        
        count_result = await session.execute(count_stmt)
        total = count_result.scalar()
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": post.id,
                "post_id": post.post_id,
                "username": post.username,
                "nickname": post.nickname,
                "content": post.content,
                "image_urls": post.image_urls,
                "video_url": post.video_url,
                "video_duration": post.video_duration,
                "likes_count": post.likes_count,
                "retweets_count": post.retweets_count,
                "replies_count": post.replies_count,
                "quotes_count": post.quotes_count,
                "bookmarks_count": post.bookmarks_count,
                "views_count": post.views_count,
                "post_url": post.post_url,
                "source_keyword": post.source_keyword,
                "hashtags": post.hashtags,
                "created_at": post.created_at,
                "add_ts": post.add_ts,
            }
            for post in posts
        ]
    }


@router.get("/posts/{post_id}")
async def get_post(post_id: str):
    async with get_session() as session:
        stmt = select(XTwitterPost).where(XTwitterPost.post_id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()
        
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        
        comment_count_stmt = select(func.count(XTwitterComment.id)).where(XTwitterComment.post_id == post_id)
        comment_count_result = await session.execute(comment_count_stmt)
        comment_count = comment_count_result.scalar()
    
    return {
        "id": post.id,
        "post_id": post.post_id,
        "username": post.username,
        "nickname": post.nickname,
        "content": post.content,
        "image_urls": post.image_urls,
        "video_url": post.video_url,
        "video_duration": post.video_duration,
        "likes_count": post.likes_count,
        "retweets_count": post.retweets_count,
        "replies_count": post.replies_count,
        "quotes_count": post.quotes_count,
        "bookmarks_count": post.bookmarks_count,
        "views_count": post.views_count,
        "post_url": post.post_url,
        "source_keyword": post.source_keyword,
        "hashtags": post.hashtags,
        "created_at": post.created_at,
        "add_ts": post.add_ts,
        "comment_count": comment_count,
    }


@router.get("/posts/{post_id}/comments")
async def get_post_comments(
    post_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    async with get_session() as session:
        stmt = select(XTwitterComment).where(XTwitterComment.post_id == post_id).order_by(XTwitterComment.add_ts.desc())
        
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        
        result = await session.execute(stmt)
        comments = result.scalars().all()
        
        count_stmt = select(func.count(XTwitterComment.id)).where(XTwitterComment.post_id == post_id)
        count_result = await session.execute(count_stmt)
        total = count_result.scalar()
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": comment.id,
                "comment_id": comment.comment_id,
                "post_id": comment.post_id,
                "username": comment.username,
                "nickname": comment.nickname,
                "content": comment.content,
                "likes_count": comment.likes_count,
                "replies_count": comment.replies_count,
                "created_at": comment.created_at,
                "add_ts": comment.add_ts,
            }
            for comment in comments
        ]
    }


@router.get("/comments")
async def get_comments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(None)
):
    async with get_session() as session:
        stmt = select(XTwitterComment).order_by(XTwitterComment.add_ts.desc())
        
        if keyword:
            stmt = stmt.where(XTwitterComment.content.like(f"%{keyword}%"))
        
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        
        result = await session.execute(stmt)
        comments = result.scalars().all()
        
        count_stmt = select(func.count(XTwitterComment.id))
        if keyword:
            count_stmt = count_stmt.where(XTwitterComment.content.like(f"%{keyword}%"))
        
        count_result = await session.execute(count_stmt)
        total = count_result.scalar()
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": comment.id,
                "comment_id": comment.comment_id,
                "post_id": comment.post_id,
                "username": comment.username,
                "nickname": comment.nickname,
                "content": comment.content,
                "likes_count": comment.likes_count,
                "replies_count": comment.replies_count,
                "created_at": comment.created_at,
                "add_ts": comment.add_ts,
            }
            for comment in comments
        ]
    }


@router.get("/video-breakdowns")
async def get_video_breakdowns(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    post_id: str = Query(None)
):
    async with get_session() as session:
        stmt = select(XTwitterVideoBreakdown).order_by(XTwitterVideoBreakdown.add_ts.desc())
        
        if post_id:
            stmt = stmt.where(XTwitterVideoBreakdown.post_id == post_id)
        
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        
        result = await session.execute(stmt)
        breakdowns = result.scalars().all()
        
        count_stmt = select(func.count(XTwitterVideoBreakdown.id))
        if post_id:
            count_stmt = count_stmt.where(XTwitterVideoBreakdown.post_id == post_id)
        
        count_result = await session.execute(count_stmt)
        total = count_result.scalar()
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": breakdown.id,
                "post_id": breakdown.post_id,
                "video_url": breakdown.video_url,
                "script": breakdown.script,
                "storyboard": breakdown.storyboard,
                "analysis": breakdown.analysis,
                "add_ts": breakdown.add_ts,
            }
            for breakdown in breakdowns
        ]
    }


@router.get("/stats")
async def get_stats():
    async with get_session() as session:
        post_count = await session.execute(select(func.count(XTwitterPost.id)))
        comment_count = await session.execute(select(func.count(XTwitterComment.id)))
        breakdown_count = await session.execute(select(func.count(XTwitterVideoBreakdown.id)))
        
        video_post_count = await session.execute(
            select(func.count(XTwitterPost.id)).where(XTwitterPost.video_url.isnot(None), XTwitterPost.video_url != "")
        )
        
        recent_posts = await session.execute(
            select(XTwitterPost).order_by(XTwitterPost.add_ts.desc()).limit(5)
        )
        
        recent_comments = await session.execute(
            select(XTwitterComment).order_by(XTwitterComment.add_ts.desc()).limit(5)
        )
    
    return {
        "total_posts": post_count.scalar(),
        "total_comments": comment_count.scalar(),
        "total_video_breakdowns": breakdown_count.scalar(),
        "video_posts_count": video_post_count.scalar(),
        "recent_posts": [
            {"post_id": p.post_id, "content": p.content[:100], "add_ts": p.add_ts}
            for p in recent_posts.scalars().all()
        ],
        "recent_comments": [
            {"comment_id": c.comment_id, "content": c.content[:100], "add_ts": c.add_ts}
            for c in recent_comments.scalars().all()
        ],
    }


# ========== 回复模板管理 ==========

from pydantic import BaseModel
from typing import List as ListType, Optional as OptionalType
import config as app_config


class KeywordReplyRule(BaseModel):
    keywords: ListType[str]
    replies: ListType[str]
    priority: int = 99


@router.get("/reply-rules")
async def get_reply_rules():
    """获取关键词回复规则"""
    rules = getattr(app_config, "X_TWITTER_KEYWORD_REPLY_RULES", [])
    return {"rules": rules}


@router.put("/reply-rules")
async def update_reply_rules(rules: ListType[KeywordReplyRule]):
    """更新关键词回复规则"""
    import json
    rules_data = [r.model_dump() for r in rules]
    app_config.X_TWITTER_KEYWORD_REPLY_RULES = rules_data

    # 持久化到环境变量文件
    env_path = ".env"
    rules_json = json.dumps(rules_data, ensure_ascii=False)
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()
        found = False
        with open(env_path, "w") as f:
            for line in lines:
                if line.startswith("X_TWITTER_KEYWORD_REPLY_RULES="):
                    f.write('X_TWITTER_KEYWORD_REPLY_RULES=' + rules_json + chr(10))
                    found = True
                else:
                    f.write(line)
            if not found:
                f.write('X_TWITTER_KEYWORD_REPLY_RULES=' + rules_json + chr(10))
    except Exception:
        pass

    return {"success": True, "rules": rules_data}


@router.get("/reply-config")
async def get_reply_config():
    """获取回复策略配置"""
    return {
        "ai_reply_enabled": app_config.X_TWITTER_AI_REPLY_ENABLED,
        "keyword_match_first": getattr(app_config, "X_TWITTER_KEYWORD_MATCH_FIRST", True),
        "reply_daily_limit": getattr(app_config, "X_TWITTER_REPLY_DAILY_LIMIT", 10),
        "system_prompt": getattr(app_config, "X_TWITTER_AI_REPLY_SYSTEM_PROMPT", ""),
        "comment_templates": app_config.X_TWITTER_COMMENT_TEMPLATES,
        "scheduled_crawl_enabled": getattr(app_config, "X_TWITTER_SCHEDULED_CRAWL_ENABLED", False),
        "crawl_interval_minutes": getattr(app_config, "X_TWITTER_CRAWL_INTERVAL_MINUTES", 60),
        "batch_breakdown_size": getattr(app_config, "X_TWITTER_BATCH_BREAKDOWN_SIZE", 5),
        "batch_comment_size": getattr(app_config, "X_TWITTER_BATCH_COMMENT_SIZE", 3),
    }


# ========== 任务调度 ==========

_x_twitter_scheduler_task = None
_x_twitter_scheduler_running = False


@router.post("/crawl/start")
async def start_scheduled_crawl():
    """启动定时爬取任务"""
    global _x_twitter_scheduler_task, _x_twitter_scheduler_running

    if _x_twitter_scheduler_running:
        return {"success": False, "message": "定时爬取任务已在运行中"}

    async def scheduled_crawl_loop():
        global _x_twitter_scheduler_running
        while _x_twitter_scheduler_running:
            try:
                from media_platform.x_twitter.core import XTwitterCrawler
                crawler = XTwitterCrawler()
                utils_logger_msg = "定时爬取任务启动"
                print(f"[X-Twitter-Scheduler] {utils_logger_msg}")

                await crawler.start()
            except Exception as e:
                print(f"[X-Twitter-Scheduler] Error: {e}")

            # 等待下次执行
            interval = getattr(app_config, "X_TWITTER_CRAWL_INTERVAL_MINUTES", 60)
            await asyncio.sleep(interval * 60)

    _x_twitter_scheduler_running = True
    _x_twitter_scheduler_task = asyncio.create_task(scheduled_crawl_loop())

    return {"success": True, "message": f"定时爬取已启动，间隔{getattr(app_config, 'X_TWITTER_CRAWL_INTERVAL_MINUTES', 60)}分钟"}


@router.post("/crawl/stop")
async def stop_scheduled_crawl():
    """停止定时爬取任务"""
    global _x_twitter_scheduler_task, _x_twitter_scheduler_running

    if not _x_twitter_scheduler_running:
        return {"success": False, "message": "定时爬取任务未在运行"}

    _x_twitter_scheduler_running = False
    if _x_twitter_scheduler_task:
        _x_twitter_scheduler_task.cancel()
        _x_twitter_scheduler_task = None

    return {"success": True, "message": "定时爬取已停止"}


@router.get("/crawl/status")
async def get_crawl_status():
    """获取定时爬取状态"""
    return {
        "running": _x_twitter_scheduler_running,
        "interval_minutes": getattr(app_config, "X_TWITTER_CRAWL_INTERVAL_MINUTES", 60),
    }


# ========== 批量操作 ==========

class BatchBreakdownRequest(BaseModel):
    post_ids: ListType[str]


class BatchCommentRequest(BaseModel):
    post_ids: ListType[str]
    comments: OptionalType[ListType[str]] = None
    real_send: bool = True  # 是否真实发送到 X.com(False=草稿模式)
    use_ai: bool = False  # comments 为空时是否使用 AI 生成评论(True=AI生成,False=用模板)
    ai_count: int = 1  # AI 生成时每条帖子生成的评论数(取第 1 条)


@router.post("/batch/breakdown")
async def batch_video_breakdown(req: BatchBreakdownRequest):
    """批量视频拆解"""
    import asyncio as aio
    from database.db_session import get_session

    batch_size = getattr(app_config, "X_TWITTER_BATCH_BREAKDOWN_SIZE", 5)
    interval = getattr(app_config, "X_TWITTER_BATCH_INTERVAL_SECONDS", 10)

    total = len(req.post_ids)
    success_count = 0
    failed_count = 0
    results = []

    # WebSocket 进度推送
    try:
        from .websocket import notify_x_twitter_batch_progress
    except ImportError:
        notify_x_twitter_batch_progress = None

    for idx, post_id in enumerate(req.post_ids):
        async with get_session() as session:
            stmt = select(XTwitterPost).where(XTwitterPost.post_id == post_id)
            result = await session.execute(stmt)
            post = result.scalar_one_or_none()

            if not post:
                failed_count += 1
                results.append({"post_id": post_id, "success": False, "error": "Post not found"})
                continue

            post_dict = {
                "post_id": post.post_id,
                "post_url": post.post_url,
                "content": post.content,
                "video_url": post.video_url,
                "username": post.username,
                "created_at": post.created_at,
            }

            try:
                # 调用 AI 进行视频拆解
                breakdown_result = await _do_video_breakdown(post_dict)

                # 保存到数据库
                if breakdown_result:
                    success_count += 1
                    results.append({"post_id": post_id, "success": True, "breakdown": breakdown_result[:200]})
                else:
                    failed_count += 1
                    results.append({"post_id": post_id, "success": False, "error": "AI breakdown failed"})
            except Exception as e:
                failed_count += 1
                results.append({"post_id": post_id, "success": False, "error": str(e)})

        # 推送进度
        if notify_x_twitter_batch_progress:
            await notify_x_twitter_batch_progress("视频拆解", idx + 1, total, success_count, failed_count)

        # 批次间隔
        if (idx + 1) % batch_size == 0 and idx + 1 < total:
            await aio.sleep(interval)

    return {
        "success": True,
        "total": total,
        "success_count": success_count,
        "failed_count": failed_count,
        "results": results,
    }


@router.post("/batch/comment")
async def batch_post_comments(req: BatchCommentRequest):
    """批量发送评论

    真实调用 x_comment_sender.send_comment 发送评论到 X.com,
    并持久化到 XTwitterSentComment 表(与工作台单条发送保持一致)。

    评论内容来源(优先级):
    1. req.comments 显式指定(按索引对应 post_ids)
    2. req.use_ai=True 时,AI 生成评论(调用 ai_agent_client.generate_comments)
    3. 兜底:从 X_TWITTER_COMMENT_TEMPLATES 随机选模板

    单条失败不影响其他帖子;每批 batch_size 条之间间隔 interval 秒避免风控。
    """
    import asyncio as aio
    import random as rnd
    import time as _time

    batch_size = getattr(app_config, "X_TWITTER_BATCH_COMMENT_SIZE", 3)
    interval = getattr(app_config, "X_TWITTER_BATCH_INTERVAL_SECONDS", 10)
    templates = app_config.X_TWITTER_COMMENT_TEMPLATES

    total = len(req.post_ids)
    success_count = 0
    failed_count = 0
    results = []

    try:
        from .websocket import notify_x_twitter_batch_progress
    except ImportError:
        notify_x_twitter_batch_progress = None

    # 延迟导入发送服务和 AI 服务(避免循环依赖)
    from api.services.x_comment_sender import send_comment as _send_comment

    for idx, post_id in enumerate(req.post_ids):
        async with get_session() as session:
            stmt = select(XTwitterPost).where(XTwitterPost.post_id == post_id)
            result = await session.execute(stmt)
            post = result.scalar_one_or_none()

            if not post:
                failed_count += 1
                results.append({"post_id": post_id, "success": False, "error": "Post not found"})
                continue

            # ===== 选择评论内容 =====
            comment_content = ""
            if req.comments and idx < len(req.comments) and req.comments[idx]:
                # 1. 显式指定的评论
                comment_content = req.comments[idx]
            elif req.use_ai:
                # 2. AI 生成评论
                try:
                    from api.services.ai_agent_client import generate_comments
                    post_dict = {
                        "post_id": post.post_id,
                        "content": post.content or "",
                        "username": post.username or "",
                        "video_url": post.video_url or "",
                    }
                    ai_comments = await generate_comments(post_dict, breakdown="", count=max(1, req.ai_count))
                    if ai_comments:
                        comment_content = ai_comments[0]
                except Exception as e:
                    print(f"[Batch-Comment] AI 生成评论失败 post={post_id}: {e},回退到模板")

            if not comment_content:
                # 3. 兜底:模板
                comment_content = rnd.choice(templates) if templates else "Interesting post!"

            # ===== 真实发送 =====
            try:
                now = int(_time.time())
                # 幂等性检查:5 分钟内同 post_id + content 已成功发送过则跳过
                dup_stmt = (
                    select(XTwitterSentComment)
                    .where(
                        and_(
                            XTwitterSentComment.post_id == post_id,
                            XTwitterSentComment.comment_content == comment_content,
                            XTwitterSentComment.sent_status == "success",
                            XTwitterSentComment.sent_at >= now - 300,
                        )
                    )
                    .order_by(XTwitterSentComment.id.desc())
                    .limit(1)
                )
                dup_result = await session.execute(dup_stmt)
                existing_sc = dup_result.scalar_one_or_none()

                if existing_sc:
                    # 幂等命中,跳过
                    success_count += 1
                    results.append({
                        "post_id": post_id,
                        "success": True,
                        "mode": "idempotent",
                        "comment": comment_content,
                        "post_url": post.post_url,
                        "sent_comment_id": existing_sc.id,
                        "message": "5 分钟内已发送过相同评论,跳过",
                    })
                    continue

                # 调用真实发送服务
                send_result = await _send_comment(
                    post_url=post.post_url,
                    content=comment_content,
                    real_send=req.real_send,
                )

                sent_status = "success" if send_result.get("success") else ("draft" if send_result.get("mode") == "draft" else "failed")

                # 持久化到 XTwitterSentComment 表
                sc = XTwitterSentComment(
                    post_id=post_id,
                    post_url=post.post_url,
                    post_content=(post.content or "")[:500],
                    post_username=post.username or "",
                    video_url=post.video_url or "",
                    comment_content=comment_content,
                    comment_url=send_result.get("comment_url", ""),
                    sent_status=sent_status,
                    sent_error=send_result.get("error", ""),
                    sent_at=now,
                    source="batch_api",
                    monitoring=1 if sent_status == "success" else 0,
                    last_check_ts=0,
                    reply_count=0,
                    auto_replied_count=0,
                    add_ts=now,
                    last_modify_ts=now,
                )
                session.add(sc)
                await session.commit()
                await session.refresh(sc)
                sc_id = sc.id

                if send_result.get("success"):
                    success_count += 1
                    results.append({
                        "post_id": post_id,
                        "success": True,
                        "mode": send_result.get("mode", "real"),
                        "comment": comment_content,
                        "post_url": post.post_url,
                        "sent_comment_id": sc_id,
                        "comment_url": send_result.get("comment_url", ""),
                    })
                else:
                    failed_count += 1
                    results.append({
                        "post_id": post_id,
                        "success": False,
                        "mode": send_result.get("mode", "draft"),
                        "comment": comment_content,
                        "post_url": post.post_url,
                        "sent_comment_id": sc_id,
                        "error": send_result.get("error", "发送失败"),
                    })
            except Exception as e:
                failed_count += 1
                results.append({"post_id": post_id, "success": False, "error": str(e)})

        # 推送进度
        if notify_x_twitter_batch_progress:
            await notify_x_twitter_batch_progress("批量评论", idx + 1, total, success_count, failed_count)

        # 批次间隔(最后一条不等待)
        if (idx + 1) % batch_size == 0 and idx + 1 < total:
            await aio.sleep(interval)

    return {
        "success": True,
        "total": total,
        "success_count": success_count,
        "failed_count": failed_count,
        "results": results,
    }


async def _do_video_breakdown(post: dict) -> str:
    """执行视频拆解并保存到数据库"""
    import httpx

    api_key = app_config.X_TWITTER_AI_API_KEY
    base_url = app_config.X_TWITTER_AI_BASE_URL
    model = app_config.X_TWITTER_AI_MODEL

    if not api_key:
        return ""

    prompt = f"""
请分析以下X平台热门视频，进行脚本和分镜拆解：

视频内容/描述: {post.get("content", "")}
视频链接: {post.get("video_url", "")}

请输出以下内容：
1. 【脚本分析】- 视频的核心脚本内容
2. 【分镜拆解】- 视频的镜头结构
3. 【关键要点】- 视频传达的核心信息点

请用中文输出，格式清晰。
    """.strip()

    response = await httpx.post(
        f"{base_url}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 500,
        },
        timeout=60,
    )

    if response.status_code != 200:
        return ""

    result = response.json()
    breakdown_text = result["choices"][0]["message"]["content"].strip()

    # 解析并保存到数据库
    script = ""
    storyboard = ""
    analysis = breakdown_text

    if "【脚本分析】" in breakdown_text:
        parts = breakdown_text.split("【分镜拆解】")
        script = parts[0].replace("【脚本分析】", "").strip()
        if len(parts) > 1:
            rest = parts[1]
            if "【关键要点】" in rest:
                storyboard_parts = rest.split("【关键要点】")
                storyboard = storyboard_parts[0].strip()
                if len(storyboard_parts) > 1:
                    analysis = storyboard_parts[1].strip()
            else:
                storyboard = rest.strip()

    # 保存到数据库
    from store.x_twitter import update_x_twitter_video_breakdown
    await update_x_twitter_video_breakdown(
        post_id=post["post_id"],
        post_url=post.get("post_url", ""),
        breakdown_data={
            "script": script,
            "storyboard": storyboard,
            "analysis": analysis,
            "full_text": breakdown_text,
        }
    )

    return breakdown_text
