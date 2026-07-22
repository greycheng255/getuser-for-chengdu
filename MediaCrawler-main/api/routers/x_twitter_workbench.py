# -*- coding: utf-8 -*-
"""
X Twitter 工作台路由

整合功能：
1. 从热点列表选择 X 推文（复用 hotpoint 和 x_twitter 表）
2. 视频拆解（脚本/分镜/关键要点/推荐评论）
3. 评论生成与发送（真实发送 / 草稿模式）
4. 已发评论列表 + 回复监控
5. AI 自动回复
"""
import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from weakref import WeakValueDictionary

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, UUID4
from sqlalchemy import select, update, func, and_, or_, desc, case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_session import get_session
from database.models import XTwitterPost, XTwitterVideoBreakdown, XTwitterExplainerVideoTask, XTwitterSentComment, XTwitterReply, XTwitterMonitoredPost, XTwitterPostReply, XTwitterTrendingPost
from api.utils.ttl_cache import ttl_cache
from api.utils.rate_limit import rate_limit, ai_rate_limit
from api.services.auth import get_current_user, require_admin


# 路由级依赖:所有 /x-workbench 接口都需要认证 + 全局限流
# (前端 request.ts 已自动携带 Bearer token,无需额外改造)
router = APIRouter(
    prefix="/x-workbench",
    tags=["x-twitter-workbench"],
    dependencies=[
        Depends(get_current_user),
        Depends(rate_limit()),
    ],
)

# 模块级 logger
logger = logging.getLogger("x_workbench_router")


# ==================== 请求模型 ====================

class BreakdownRequest(BaseModel):
    post_id: str = Field(..., description="推文ID")
    force_refresh: bool = Field(False, description="是否强制重新生成拆解")


class ExplainerVideoRequest(BaseModel):
    post_id: str = Field(..., description="推文ID")
    idempotency_key: UUID4 = Field(..., description="本次视频生成意图 UUID v4")


class GenerateCommentsRequest(BaseModel):
    post_id: str = Field(..., description="推文ID")
    count: int = Field(3, ge=1, le=10, description="生成评论数")


class SendCommentRequest(BaseModel):
    post_id: str = Field(..., description="推文ID")
    post_url: str = Field(..., description="推文URL")
    content: str = Field(..., min_length=1, max_length=280, description="评论内容")
    real_send: bool = Field(True, description="是否真实发送。False=草稿模式")


class ManualReplyRequest(BaseModel):
    reply_id: int = Field(..., description="XTwitterReply.id")
    content: str = Field(..., min_length=1, max_length=280, description="回复内容")
    real_send: bool = Field(True, description="是否真实发送")


class UpdateMonitoringRequest(BaseModel):
    sent_comment_id: int = Field(..., description="XTwitterSentComment.id")
    monitoring: int = Field(0, description="0=停止监控, 1=恢复监控")


# ==================== 工具函数 ====================

def _ts() -> int:
    return int(time.time())


def _stored_list(value: Any) -> List[str]:
    """兼容数据库 JSON 字符串、历史换行文本和原生列表。"""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    text = str(value).strip()
    try:
        import json
        decoded = json.loads(text)
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
    except (TypeError, ValueError):
        pass
    return [line.strip() for line in text.splitlines() if line.strip()]


_explainer_submission_locks: WeakValueDictionary[
    tuple[str, str], asyncio.Lock
] = WeakValueDictionary()
_EXPLAINER_SUBMISSION_LEASE_SECONDS = 90


def _explainer_submission_lock(owner_user_id: str, idempotency_key: str) -> asyncio.Lock:
    """Serialize one paid generation intent inside this API process."""
    key = (owner_user_id, idempotency_key)
    lock = _explainer_submission_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _explainer_submission_locks[key] = lock
    return lock


def _explainer_request_hash(post_id: str) -> str:
    canonical = json.dumps(
        {"post_id": post_id},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _explainer_task_response(task: XTwitterExplainerVideoTask) -> Dict[str, Any]:
    reference_count = 0
    try:
        snapshot = json.loads(task.submission_payload or "{}")
        reference_count = min(9, len(snapshot.get("image_urls") or []))
    except (TypeError, ValueError):
        pass
    return {
        "post_id": task.post_id,
        "task_id": task.local_task_id,
        "status": task.status or "submitting",
        "model": task.model or "",
        "model_name": task.model_name or "",
        "reference_count": reference_count,
    }


async def _find_explainer_intent(
    owner_user_id: str,
    idempotency_key: str,
) -> Optional[XTwitterExplainerVideoTask]:
    async with get_session() as session:
        result = await session.execute(
            select(XTwitterExplainerVideoTask).where(
                XTwitterExplainerVideoTask.owner_user_id == owner_user_id,
                XTwitterExplainerVideoTask.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()


def _ensure_same_explainer_intent(
    task: XTwitterExplainerVideoTask,
    request_hash: str,
) -> None:
    if task.request_hash != request_hash:
        raise HTTPException(
            409,
            "该 Idempotency Key 已用于另一个视频生成请求",
        )


async def _claim_explainer_submission(
    task: XTwitterExplainerVideoTask,
    owner_user_id: str,
) -> bool:
    """Atomically claim provider submission across API workers."""
    now = _ts()
    async with get_session() as session:
        claimed = await session.execute(
            update(XTwitterExplainerVideoTask)
            .where(
                XTwitterExplainerVideoTask.id == task.id,
                XTwitterExplainerVideoTask.owner_user_id == owner_user_id,
                XTwitterExplainerVideoTask.provider_task_id == "",
                XTwitterExplainerVideoTask.status.in_(["pending", "error"]),
            )
            .values(
                status="submitting",
                progress=0,
                error="",
                updated_ts=now,
                finished_ts=0,
            )
            .execution_options(synchronize_session=False)
        )
        return claimed.rowcount == 1


async def _mark_explainer_submission_error(
    local_task_id: str,
    owner_user_id: str,
    error: Exception,
    *,
    submission_uncertain: bool = False,
) -> None:
    now = _ts()
    async with get_session() as session:
        await session.execute(
            update(XTwitterExplainerVideoTask)
            .where(
                XTwitterExplainerVideoTask.local_task_id == local_task_id,
                XTwitterExplainerVideoTask.owner_user_id == owner_user_id,
                XTwitterExplainerVideoTask.provider_task_id == "",
            )
            .values(
                status=("submission_unknown" if submission_uncertain else "error"),
                error=str(error)[:1000],
                updated_ts=now,
                finished_ts=now,
            )
            .execution_options(synchronize_session=False)
        )


async def _get_post_by_id(session: AsyncSession, post_id: str) -> Optional[XTwitterPost]:
    stmt = select(XTwitterTrendingPost).where(XTwitterTrendingPost.post_id == post_id)
    result = await session.execute(stmt)
    trending_post = result.scalar_one_or_none()
    
    if trending_post:
        return XTwitterPost(
            id=0,
            post_id=trending_post.post_id,
            post_url=trending_post.post_url,
            username=trending_post.username,
            nickname=trending_post.nickname,
            content=trending_post.content,
            video_url=trending_post.video_url,
            image_urls=[trending_post.image_url] if trending_post.image_url else [],
            likes_count=trending_post.likes_count,
            retweets_count=trending_post.retweets_count,
            replies_count=trending_post.replies_count,
            views_count=trending_post.views_count,
            created_at=trending_post.created_at,
            source_keyword=trending_post.topic,
            add_ts=trending_post.crawl_ts,
        )
    
    stmt = select(XTwitterPost).where(XTwitterPost.post_id == post_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ==================== 热点推文列表（整合 hotpoint）====================

@router.get("/trending")
async def get_trending_posts(
    limit: int = Query(200, ge=1),
    keyword: str = Query("", description="搜索关键词"),
    has_video: bool = Query(False, description="只看视频"),
    platform: str = Query("x", description="平台: x/youtube/bilibili/douyin/xiaohongshu 等"),
):
    """获取热点推文（联动 hotpoint_fetcher）

    逻辑：
    1. 所有平台统一从 hotpoint_fetcher 获取最新热点数据（热点聚合负责采集）
    2. X 平台额外把 hotpoint 数据写回数据库，供视频拆解、评论发送等流程复用
    3. 返回统一字段格式（WorkbenchPost）
    """
    # 统一从热点聚合获取数据（热点聚合负责采集最新热点）
    result = await _trending_from_hotpoint(platform, limit, keyword, has_video)
    
    # X 平台额外把 hotpoint 数据写回数据库，供视频拆解等流程复用
    if platform == "x" and result.get("items"):
        try:
            async with get_session() as session:
                await _persist_hotpoint_posts(session, result["items"])
                result["persisted"] = len(result["items"])
                result["hint"] = f"已自动入库 {len(result['items'])} 条"
        except Exception as e:
            logger.warning(f"[get_trending] Persist hotpoint posts failed: {e}")
    
    return result


async def _trending_from_hotpoint(platform: str, limit: int, keyword: str, has_video: bool) -> Dict[str, Any]:
    """从 hotpoint_fetcher 拉取热点并统一字段格式

    额外能力：当 platform=x 且数据库无数据时，把 hotpoint 拉到的数据写回数据库，
    这样后续的视频拆解、评论发送等流程都能复用数据库中已有的 post。
    
    返回数据库真实总量，避免前端显示总是200条的问题。
    """
    try:
        from api.services.hotpoint_fetcher import fetch_platform, PLATFORMS
        if platform not in PLATFORMS:
            return {"source": "error", "platform": platform, "total": 0, "items": [], "error": f"不支持的平台: {platform}"}

        raw_items = await fetch_platform(platform, force_refresh=False)
        items = []
        for idx, it in enumerate(raw_items[:limit], 1):
            title = it.get("title", "")
            if keyword and keyword.lower() not in title.lower():
                continue
            extra = it.get("extra", {}) or {}
            video_url = extra.get("video_url", "")
            if has_video and not video_url:
                continue
            # X 平台用真实 post_id（从 url 解析），其他平台用 rank 作为伪 id
            url = it.get("url", "")
            post_id = it.get("post_id") or ""
            if not post_id:
                if platform == "x" and "/status/" in url:
                    post_id = url.rstrip("/").split("/status/")[-1].split("?")[0]
                else:
                    post_id = f"{platform}_{it.get('rank', idx)}"
            items.append({
                "post_id": post_id,
                "post_url": url,
                "username": it.get("author", ""),
                "nickname": it.get("author", ""),
                "content": title,
                "video_url": video_url,
                "image_urls": "",
                "likes_count": str(it.get("hot", "0")),
                "retweets_count": str(extra.get("retweets", "0")),
                "replies_count": str(extra.get("replies", "0")),
                "views_count": str(extra.get("views", "0")),
                "created_at": it.get("published_at", 0),
                "source_keyword": platform,
            })

        meta = PLATFORMS.get(platform, {})
        # X 平台：把 hotpoint 拉到的数据持久化到 XTwitterPost 表
        # 这样后续的视频拆解、评论发送等流程才能用真实 post_id
        saved_count = 0
        if platform == "x" and items:
            saved_count = await _persist_x_posts_from_hotpoint(items)

        # 查询数据库中 XTwitterPost 表的真实总量
        total_in_db = 0
        if platform == "x":
            async with get_session() as session:
                total_in_db = (await session.execute(select(func.count(XTwitterPost.id)))).scalar() or 0

        return {
            "source": "hotpoint",
            "platform": platform,
            "platform_name": meta.get("name", platform),
            "platform_color": meta.get("color", "#666"),
            "total": len(items),
            "total_in_db": total_in_db,
            "added_count": saved_count,
            "items": items,
            "persisted": saved_count,
            "hint": f"已自动入库 {saved_count} 条 X 数据" if saved_count > 0 else "",
        }
    except Exception as e:
        return {"source": "error", "platform": platform, "total": 0, "items": [], "error": str(e)}


async def _persist_x_posts_from_hotpoint(items: List[Dict[str, Any]]) -> int:
    """把 hotpoint 拉取的 X 数据写入 XTwitterPost 表（已存在则跳过）

    优化:用 IN 批量查询已存在的 post_id,避免每条数据都查询一次(N+1 → 2)
    """
    import time
    saved = 0
    # 收集合法 post_id(跳过伪 id)
    valid_items = [it for it in items if it.get("post_id", "") and "_" not in it.get("post_id", "")]
    if not valid_items:
        return 0
    post_ids = [it["post_id"] for it in valid_items]

    try:
        async with get_session() as session:
            # 批量查询已存在的 post_id(一次查询代替 N 次)
            existing_stmt = select(XTwitterPost.post_id).where(XTwitterPost.post_id.in_(post_ids))
            existing_ids = {row[0] for row in (await session.execute(existing_stmt)).all()}

            now = int(time.time())
            for it in valid_items:
                pid = it["post_id"]
                if pid in existing_ids:
                    continue
                post = XTwitterPost(
                    post_id=pid,
                    post_url=it.get("post_url", ""),
                    username=it.get("username", ""),
                    nickname=it.get("nickname", ""),
                    content=it.get("content", ""),
                    video_url=it.get("video_url", ""),
                    image_urls=it.get("image_urls", ""),
                    likes_count=it.get("likes_count", "0"),
                    retweets_count=it.get("retweets_count", "0"),
                    replies_count=it.get("replies_count", "0"),
                    views_count=it.get("views_count", "0"),
                    created_at=int(it.get("created_at", 0) or 0),
                    source_keyword="hotpoint_sync",
                    add_ts=now,
                )
                session.add(post)
                saved += 1
            await session.commit()
    except Exception as e:
        logger.error(f"persist x posts from hotpoint error: {e}")
    return saved


@router.get("/platforms")
async def list_video_platforms():
    """获取工作台支持的平台列表（用于前端切换）

    平台列表基本静态,缓存 10 分钟,避免每次打开工作台都重新计算。
    """
    try:
        return await _get_platforms_cached()
    except Exception as e:
        return {"platforms": [], "error": str(e)}


@ttl_cache(ttl_seconds=600)
async def _get_platforms_cached():
    """平台列表缓存层(10 分钟 TTL)"""
    from api.services.hotpoint_fetcher import PLATFORMS
    # 优先视频平台 + X
    priority = ["x", "youtube", "bilibili", "douyin", "xiaohongshu"]
    result = []
    for pid in priority:
        if pid in PLATFORMS:
            m = PLATFORMS[pid]
            result.append({
                "id": pid,
                "name": m.get("name", pid),
                "color": m.get("color", "#666"),
                "region": m.get("region", "global"),
            })
    return {"platforms": result}


# ==================== 视频拆解 ====================

@router.post("/breakdown")
async def generate_breakdown(req: BreakdownRequest):
    """生成或获取视频拆解"""
    from api.services import ai_agent_client

    # 先查数据库是否已有拆解
    async with get_session() as session:
        stmt = select(XTwitterVideoBreakdown).where(XTwitterVideoBreakdown.post_id == req.post_id)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing and not req.force_refresh:
            return {
                "source": "cache",
                "post_id": req.post_id,
                "script": existing.script,
                "storyboards": existing.storyboards,
                "key_points": existing.key_points,
                "suggested_comments": existing.suggested_comments,
            }

    # 查推文内容
    async with get_session() as session:
        post = await _get_post_by_id(session, req.post_id)
    if not post:
        raise HTTPException(404, f"推文 {req.post_id} 不存在")

    post_dict = {
        "post_id": post.post_id,
        "post_url": post.post_url,
        "content": post.content,
        "video_url": post.video_url,
        "username": post.username,
    }

    # 调用 AI 生成拆解
    try:
        text = await ai_agent_client.generate_video_breakdown(post_dict)
        parsed = ai_agent_client.parse_breakdown(text)
    except Exception as e:
        raise HTTPException(500, f"AI 拆解失败: {e}")

    # 保存到数据库
    import json
    async with get_session() as session:
        if existing:
            existing.script = parsed["script"]
            existing.storyboards = json.dumps(parsed["storyboard_items"], ensure_ascii=False)
            existing.key_points = json.dumps(parsed["key_points"], ensure_ascii=False)
            existing.suggested_comments = json.dumps(parsed["suggested_comments"], ensure_ascii=False)
        else:
            new_bd = XTwitterVideoBreakdown(
                post_id=req.post_id,
                post_url=post.post_url,
                script=parsed["script"],
                storyboards=json.dumps(parsed["storyboard_items"], ensure_ascii=False),
                key_points=json.dumps(parsed["key_points"], ensure_ascii=False),
                suggested_comments=json.dumps(parsed["suggested_comments"], ensure_ascii=False),
                add_ts=_ts(),
            )
            session.add(new_bd)
        await session.commit()

    return {
        "source": "ai",
        "post_id": req.post_id,
        "script": parsed["script"],
        "storyboards": parsed["storyboard_items"],
        "key_points": parsed["key_points"],
        "suggested_comments": parsed["suggested_comments"],
        "full_text": parsed["full_text"],
    }


@router.post("/explainer-video", dependencies=[Depends(ai_rate_limit())])
async def generate_explainer_video(
    req: ExplainerVideoRequest,
    current_user: dict = Depends(get_current_user),
):
    """使用已保存的视频拆解上下文提交 AI6700 媒体任务。"""
    from api.services.explainer_video_client import (
        AI6700VideoError,
        build_explainer_prompt,
        choose_seedance_model,
        normalize_media_urls,
        submit_explainer_video,
    )
    from config.onellm_config import load_onellm_config
    owner_user_id = str(current_user["id"])
    idempotency_key = str(req.idempotency_key)
    request_hash = _explainer_request_hash(req.post_id)

    async with _explainer_submission_lock(owner_user_id, idempotency_key):
        task = await _find_explainer_intent(owner_user_id, idempotency_key)
        if task is not None:
            _ensure_same_explainer_intent(task, request_hash)
            if task.provider_task_id:
                return _explainer_task_response(task)
            if task.status == "submission_unknown":
                return _explainer_task_response(task)
            if task.status == "submitting":
                if (task.updated_ts or 0) <= _ts() - _EXPLAINER_SUBMISSION_LEASE_SECONDS:
                    await _mark_explainer_submission_error(
                        task.local_task_id,
                        owner_user_id,
                        RuntimeError(
                            "AI6700 提交响应未知；为避免重复扣费，系统不会自动重提。"
                            "请在 AI6700 消费明细中核对最近任务后再创建新请求"
                        ),
                        submission_uncertain=True,
                    )
                    task = await _find_explainer_intent(owner_user_id, idempotency_key)
                return _explainer_task_response(task)

        if task is None:
            async with get_session() as session:
                post = await _get_post_by_id(session, req.post_id)
                breakdown_result = await session.execute(
                    select(XTwitterVideoBreakdown).where(
                        XTwitterVideoBreakdown.post_id == req.post_id
                    )
                )
                breakdown = breakdown_result.scalar_one_or_none()

            if not post:
                raise HTTPException(404, f"推文 {req.post_id} 不存在")
            if not breakdown:
                raise HTTPException(400, "请先完成视频拆解，再生成解说视频")

            image_urls = normalize_media_urls(getattr(post, "image_urls", None))
            video_urls = normalize_media_urls(getattr(post, "video_url", None))
            prompt = build_explainer_prompt(
                post_content=post.content or "",
                script=breakdown.script or "",
                storyboards=_stored_list(breakdown.storyboards),
                key_points=_stored_list(breakdown.key_points),
            )
            submission_payload = json.dumps(
                {
                    "prompt": prompt,
                    "image_urls": image_urls,
                    "video_urls": video_urls,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )

            onellm = load_onellm_config()
            model = choose_seedance_model(image_urls, video_urls)
            model_name = (
                "Seedance 2.0 参考生"
                if model == onellm.reference_video_model
                else "Seedance 2.0 首尾帧"
            )
            now = _ts()
            candidate = XTwitterExplainerVideoTask(
                local_task_id=str(uuid.uuid4()),
                provider_task_id="",
                owner_user_id=owner_user_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                submission_payload=submission_payload,
                connection_id=0,
                grant_id="",
                post_id=req.post_id,
                tenant_id="",
                workspace_id="",
                model=model,
                model_name=model_name,
                status="pending",
                progress=0,
                created_ts=now,
                updated_ts=now,
            )
            try:
                async with get_session() as session:
                    session.add(candidate)
                    await session.flush()
                task = candidate
            except IntegrityError:
                # A different API worker won the unique (owner, key) insert.
                task = await _find_explainer_intent(owner_user_id, idempotency_key)
                if task is None:
                    raise
                _ensure_same_explainer_intent(task, request_hash)
                if task.provider_task_id or task.status in {
                    "submitting",
                    "submission_unknown",
                }:
                    return _explainer_task_response(task)
        if not await _claim_explainer_submission(task, owner_user_id):
            replay = await _find_explainer_intent(owner_user_id, idempotency_key)
            if replay is None:
                raise HTTPException(409, "视频生成意图状态已变化，请重试")
            _ensure_same_explainer_intent(replay, request_hash)
            return _explainer_task_response(replay)

        try:
            snapshot = json.loads(task.submission_payload or "{}")
            prompt = str(snapshot["prompt"])
            image_urls = [str(url) for url in snapshot.get("image_urls") or []]
            video_urls = [str(url) for url in snapshot.get("video_urls") or []]
        except (KeyError, TypeError, ValueError) as exc:
            await _mark_explainer_submission_error(
                task.local_task_id,
                owner_user_id,
                exc,
            )
            raise HTTPException(500, "视频生成提交快照损坏") from exc

        try:
            result = await submit_explainer_video(
                prompt=prompt,
                image_urls=image_urls,
                video_urls=video_urls,
            )
        except AI6700VideoError as exc:
            await _mark_explainer_submission_error(
                task.local_task_id,
                owner_user_id,
                exc,
                submission_uncertain=exc.submission_uncertain,
            )
            raise HTTPException(exc.status_code, str(exc)) from exc

        async with get_session() as session:
            saved = await session.execute(
                update(XTwitterExplainerVideoTask)
                .where(
                    XTwitterExplainerVideoTask.id == task.id,
                    XTwitterExplainerVideoTask.owner_user_id == owner_user_id,
                    XTwitterExplainerVideoTask.provider_task_id == "",
                )
                .values(
                    provider_task_id=result["task_id"],
                    model=result.get("model", task.model or ""),
                    model_name=result.get("model_name", task.model_name or ""),
                    status=result.get("status", "running"),
                    progress=5,
                    error="",
                    updated_ts=_ts(),
                    finished_ts=0,
                )
                .execution_options(synchronize_session=False)
            )
            if saved.rowcount != 1:
                logger.warning(
                    "explainer task provider result raced: local_task_id=%s",
                    task.local_task_id,
                )

        completed = await _find_explainer_intent(owner_user_id, idempotency_key)
        if completed is None:
            raise HTTPException(500, "视频任务本地映射丢失")
        return _explainer_task_response(completed)


@router.get("/explainer-video/{task_id}")
async def explainer_video_status(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """查询 AI6700 解说视频任务进度。"""
    from api.services.explainer_video_client import (
        AI6700VideoError,
        get_explainer_video_status,
    )

    owner_user_id = str(current_user["id"])
    async with get_session() as session:
        task_result = await session.execute(
            select(XTwitterExplainerVideoTask).where(
                XTwitterExplainerVideoTask.local_task_id == task_id,
                XTwitterExplainerVideoTask.owner_user_id == owner_user_id,
            )
        )
        task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "视频任务不存在")
    if not task.provider_task_id:
        if task.status in {"error", "submission_unknown"}:
            return {
                "task_id": task.local_task_id,
                "status": task.status,
                "is_final": True,
                "progress": task.progress or 0,
                "current_step": "error",
                "result_url": task.result_url or "",
                "error": task.error or "任务提交失败",
                "cost": task.cost or 0,
            }
        return {
            "task_id": task.local_task_id,
            "status": task.status or "submitting",
            "is_final": False,
            "progress": task.progress or 0,
            "current_step": "submitting",
            "result_url": "",
            "error": "",
            "cost": 0,
        }

    try:
        status_result = await get_explainer_video_status(task.provider_task_id)
    except AI6700VideoError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    async with get_session() as session:
        task_result = await session.execute(
            select(XTwitterExplainerVideoTask).where(
                XTwitterExplainerVideoTask.local_task_id == task_id,
                XTwitterExplainerVideoTask.owner_user_id == owner_user_id,
            )
        )
        row = task_result.scalar_one()
        row.status = status_result["status"]
        row.progress = status_result["progress"]
        row.result_url = status_result["result_url"]
        row.error = status_result["error"]
        row.cost = str(status_result["cost"])
        row.updated_ts = _ts()
        if status_result["is_final"]:
            row.finished_ts = _ts()
    return {**status_result, "task_id": task_id}


# ==================== 评论生成 ====================

@router.post("/generate-comments", dependencies=[Depends(ai_rate_limit())])
async def generate_comments(req: GenerateCommentsRequest):
    """根据拆解结果生成多条评论"""
    from api.services import ai_agent_client

    async with get_session() as session:
        post = await _get_post_by_id(session, req.post_id)
        stmt = select(XTwitterVideoBreakdown).where(XTwitterVideoBreakdown.post_id == req.post_id)
        bd_result = await session.execute(stmt)
        bd = bd_result.scalar_one_or_none()

    if not post:
        raise HTTPException(404, "推文不存在")

    breakdown_text = ""
    if bd:
        breakdown_text = f"脚本: {bd.script or ''}\n分镜: {bd.storyboards or ''}\n要点: {bd.key_points or ''}"
    else:
        breakdown_text = post.content or ""

    try:
        comments = await ai_agent_client.generate_comments(
            {"content": post.content or ""},
            breakdown_text,
            count=req.count,
        )
    except Exception as e:
        raise HTTPException(500, f"AI 评论生成失败: {e}")

    return {"post_id": req.post_id, "comments": comments}


# ==================== 评论发送 ====================

@router.post("/comments/send")
async def send_comment(req: SendCommentRequest):
    """发送评论到 X.com（真实发送或草稿）

    幂等性保护:同一 (post_id + content) 在 5 分钟内已发送过成功评论时,
    直接返回已有记录,避免用户双击/网络重试导致重复发送。
    """
    from api.services.x_comment_sender import send_comment as _send

    # ===== 幂等性检查 =====
    # 检查最近 5 分钟内是否已成功发送过相同 post_id + content 的评论
    # 防止:用户双击发送按钮、网络超时前端重试、浏览器刷新重复提交
    IDEMPOTENCY_WINDOW = 300  # 5 分钟
    now = _ts()
    idempotency_cutoff = now - IDEMPOTENCY_WINDOW

    async with get_session() as session:
        dup_stmt = (
            select(XTwitterSentComment)
            .where(
                and_(
                    XTwitterSentComment.post_id == req.post_id,
                    XTwitterSentComment.comment_content == req.content,
                    XTwitterSentComment.sent_status == "success",
                    XTwitterSentComment.sent_at >= idempotency_cutoff,
                )
            )
            .order_by(desc(XTwitterSentComment.id))
            .limit(1)
        )
        dup_result = await session.execute(dup_stmt)
        existing_sc = dup_result.scalar_one_or_none()

    if existing_sc:
        logger.info(f"幂等性命中:post_id={req.post_id} content={req.content[:30]}... 已有评论 id={existing_sc.id}")
        return {
            "success": True,
            "mode": "idempotent",
            "message": "评论已发送过(5 分钟内幂等命中),未重复发送",
            "sent_comment_id": existing_sc.id,
            "comment_url": existing_sc.comment_url or "",
        }

    # 先查推文内容用于展示
    async with get_session() as session:
        post = await _get_post_by_id(session, req.post_id)

    post_content = post.content if post else ""
    post_username = post.username if post else ""
    video_url = post.video_url if post else ""

    # 调用发送服务
    result = await _send(
        post_url=req.post_url,
        content=req.content,
        real_send=req.real_send,
    )

    now = _ts()
    sent_status = "success" if result.get("success") else "failed"
    if not result.get("success"):
        # 失败也保存为 draft（避免数据丢失）
        sent_status = "draft" if result.get("mode") == "draft" else "failed"

    # 保存到数据库
    async with get_session() as session:
        sc = XTwitterSentComment(
            post_id=req.post_id,
            post_url=req.post_url,
            post_content=post_content[:500],
            post_username=post_username,
            video_url=video_url,
            comment_content=req.content,
            comment_url=result.get("comment_url", ""),
            sent_status=sent_status,
            sent_error=result.get("error", ""),
            sent_at=now,
            source="workbench",
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

    # 评论数变化,失效统计缓存
    await _get_stats_cached.invalidate()

    return {
        "success": result.get("success", False),
        "mode": result.get("mode", "draft"),
        "message": result.get("message", result.get("error", "")),
        "sent_comment_id": sc_id,
        "comment_url": result.get("comment_url", ""),
    }


# ==================== 已发评论列表 + 回复 ====================

@router.get("/comments")
async def list_sent_comments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query("", description="按状态筛选: success/failed/draft"),
    keyword: str = Query("", description="搜索关键词（匹配评论内容或推文内容）"),
    start_ts: int = Query(0, description="开始时间戳"),
    end_ts: int = Query(0, description="结束时间戳"),
):
    """获取已发评论列表"""
    async with get_session() as session:
        stmt = select(XTwitterSentComment).order_by(desc(XTwitterSentComment.add_ts))
        count_stmt = select(func.count(XTwitterSentComment.id))
        
        if status:
            stmt = stmt.where(XTwitterSentComment.sent_status == status)
            count_stmt = count_stmt.where(XTwitterSentComment.sent_status == status)
        
        if keyword:
            like_pattern = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    XTwitterSentComment.comment_content.like(like_pattern),
                    XTwitterSentComment.post_content.like(like_pattern),
                    XTwitterSentComment.post_username.like(like_pattern),
                )
            )
            count_stmt = count_stmt.where(
                or_(
                    XTwitterSentComment.comment_content.like(like_pattern),
                    XTwitterSentComment.post_content.like(like_pattern),
                    XTwitterSentComment.post_username.like(like_pattern),
                )
            )
        
        if start_ts:
            stmt = stmt.where(XTwitterSentComment.sent_at >= start_ts)
            count_stmt = count_stmt.where(XTwitterSentComment.sent_at >= start_ts)
        
        if end_ts:
            stmt = stmt.where(XTwitterSentComment.sent_at <= end_ts)
            count_stmt = count_stmt.where(XTwitterSentComment.sent_at <= end_ts)

        total = (await session.execute(count_stmt)).scalar() or 0

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(stmt)
        items = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": sc.id,
                "post_id": sc.post_id,
                "post_url": sc.post_url,
                "post_content": sc.post_content,
                "post_username": sc.post_username,
                "video_url": sc.video_url,
                "comment_content": sc.comment_content,
                "comment_url": sc.comment_url,
                "sent_status": sc.sent_status,
                "sent_error": sc.sent_error,
                "sent_at": sc.sent_at,
                "source": sc.source,
                "monitoring": sc.monitoring,
                "reply_count": sc.reply_count,
                "auto_replied_count": sc.auto_replied_count,
                "last_check_ts": sc.last_check_ts,
            }
            for sc in items
        ],
    }


@router.get("/comments/{sent_comment_id}/replies")
async def list_replies(sent_comment_id: int):
    """获取某条已发评论收到的回复"""
    async with get_session() as session:
        stmt = select(XTwitterReply).where(
            XTwitterReply.sent_comment_id == sent_comment_id
        ).order_by(desc(XTwitterReply.add_ts))
        result = await session.execute(stmt)
        replies = result.scalars().all()

    return {
        "total": len(replies),
        "items": [
            {
                "id": r.id,
                "reply_id": r.reply_id,
                "reply_url": r.reply_url,
                "replier_username": r.replier_username,
                "replier_nickname": r.replier_nickname,
                "replier_avatar": r.replier_avatar,
                "reply_content": r.reply_content,
                "reply_likes_count": r.reply_likes_count,
                "reply_created_at": r.reply_created_at,
                "auto_reply_status": r.auto_reply_status,
                "auto_reply_content": r.auto_reply_content,
                "auto_reply_url": r.auto_reply_url,
                "auto_replied_at": r.auto_replied_at,
                "add_ts": r.add_ts,
            }
            for r in replies
        ],
    }


# ==================== 手动回复 ====================

@router.post("/replies/manual")
async def manual_reply(req: ManualReplyRequest):
    """手动回复某条收到的回复（不通过 AI）

    幂等性保护:若该回复已成功发送过(auto_reply_status=sent),
    直接返回已有结果,避免重复回复。
    """
    from api.services.x_comment_sender import reply_to_comment

    # 获取回复信息
    async with get_session() as session:
        reply = await session.get(XTwitterReply, req.reply_id)
        if not reply:
            raise HTTPException(404, "回复记录不存在")
        # 幂等性:已成功发送过的回复不重复发送
        if reply.auto_reply_status == "sent" and reply.auto_reply_content:
            logger.info(f"幂等性命中:reply_id={req.reply_id} 已成功回复过")
            return {
                "success": True,
                "mode": "idempotent",
                "message": "该回复已成功回复过,未重复发送",
                "reply_id": req.reply_id,
                "existing_reply_url": reply.auto_reply_url or "",
            }

    # 真实发送
    result = await reply_to_comment(
        comment_url=reply.reply_url,
        content=req.content,
        real_send=req.real_send,
    )

    now = _ts()
    async with get_session() as session:
        db_reply = await session.get(XTwitterReply, req.reply_id)
        if db_reply:
            db_reply.auto_reply_status = "sent" if result.get("success") else "failed"
            db_reply.auto_reply_content = req.content
            db_reply.auto_reply_url = result.get("comment_url", "")
            db_reply.auto_replied_at = now if result.get("success") else 0
            db_reply.last_modify_ts = now
            await session.commit()

    # 回复状态变化,失效统计缓存
    await _get_stats_cached.invalidate()

    return {
        "success": result.get("success", False),
        "mode": result.get("mode", "draft"),
        "message": result.get("message", result.get("error", "")),
        "reply_id": req.reply_id,
    }


# ==================== AI 自动回复触发 ====================

@router.post("/replies/{reply_id}/auto-reply", dependencies=[Depends(ai_rate_limit())])
async def trigger_auto_reply(reply_id: int):
    """手动触发对某条回复的 AI 自动回复"""
    from api.services import ai_agent_client
    from api.services.x_comment_sender import reply_to_comment

    async with get_session() as session:
        reply = await session.get(XTwitterReply, reply_id)
        if not reply:
            raise HTTPException(404, "回复记录不存在")
        sc = await session.get(XTwitterSentComment, reply.sent_comment_id)
        if not sc:
            raise HTTPException(404, "父评论记录不存在")

    # AI 生成
    try:
        ai_reply = await ai_agent_client.generate_auto_reply(
            post_content=sc.post_content or "",
            my_comment=sc.comment_content or "",
            reply_content=reply.reply_content or "",
            replier=reply.replier_username or "",
        )
    except Exception as e:
        raise HTTPException(500, f"AI 回复生成失败: {e}")

    # 发送
    result = await reply_to_comment(
        comment_url=reply.reply_url,
        content=ai_reply,
        real_send=True,
    )

    now = _ts()
    async with get_session() as session:
        db_reply = await session.get(XTwitterReply, reply_id)
        if db_reply:
            db_reply.auto_reply_status = "sent" if result.get("success") else "failed"
            db_reply.auto_reply_content = ai_reply
            db_reply.auto_reply_url = result.get("comment_url", "")
            db_reply.auto_replied_at = now if result.get("success") else 0
            db_reply.last_modify_ts = now
            await session.commit()
        # 更新父评论计数
        sc_db = await session.get(XTwitterSentComment, reply.sent_comment_id)
        if sc_db and result.get("success"):
            sc_db.auto_replied_count = (sc_db.auto_replied_count or 0) + 1
            await session.commit()

    # 回复状态变化,失效统计缓存
    await _get_stats_cached.invalidate()

    return {
        "success": result.get("success", False),
        "mode": result.get("mode", "real"),
        "ai_reply": ai_reply,
        "message": result.get("message", result.get("error", "")),
    }


# ==================== 监控开关 ====================

@router.put("/comments/monitoring")
async def update_monitoring(req: UpdateMonitoringRequest):
    """更新已发评论的监控状态"""
    async with get_session() as session:
        sc = await session.get(XTwitterSentComment, req.sent_comment_id)
        if not sc:
            raise HTTPException(404, "已发评论记录不存在")
        sc.monitoring = 1 if req.monitoring else 0
        sc.last_modify_ts = _ts()
        await session.commit()
    return {"success": True, "monitoring": sc.monitoring}


@router.post("/monitor/check-now")
async def check_now():
    """立即触发一次回复检查（不等定时任务）"""
    from api.services.comment_reply_monitor import _check_all_sent_comments
    await _check_all_sent_comments()
    return {"success": True, "message": "已触发一次回复检查"}


@router.get("/monitor/status")
async def monitor_status():
    """获取监控服务状态"""
    from api.services.comment_reply_monitor import get_monitor_status
    return await get_monitor_status()


@router.post("/monitor/start", dependencies=[Depends(require_admin)])
async def start_monitor():
    """启动后台监控任务(仅管理员)"""
    from api.services.comment_reply_monitor import start_monitor
    await start_monitor()
    return {"success": True, "message": "监控已启动"}


@router.post("/monitor/stop", dependencies=[Depends(require_admin)])
async def stop_monitor():
    """停止后台监控任务(仅管理员)"""
    from api.services.comment_reply_monitor import stop_monitor
    await stop_monitor()
    return {"success": True, "message": "监控已停止"}


# ==================== AI 健康检查 ====================

@router.get("/ai/health")
async def ai_health():
    """检查 AI6700 Chat Completions API 是否可用。"""
    from api.services import ai_agent_client
    # 重新加载配置（避免启动时未加载）
    ai_agent_client.CONFIG = ai_agent_client._load_config()
    return await ai_agent_client.health_check()


# ==================== 统计 ====================

@router.get("/stats")
async def get_stats():
    """工作台统计数据

    优化:用条件聚合(case when)把 5 次 COUNT 查询合并为 2 次
    (sent_comment 表 1 次 + reply 表 1 次)
    并加 15 秒 TTL 缓存(多个面板同时打开时减少重复查询)
    """
    return await _get_stats_cached()


@ttl_cache(ttl_seconds=15)
async def _get_stats_cached():
    """统计数据缓存层(15 秒 TTL)"""
    async with get_session() as session:
        # 已发评论统计(总数 + 成功数 一次查询)
        sent_row = (await session.execute(
            select(
                func.count(XTwitterSentComment.id).label("total"),
                func.sum(case(
                    (XTwitterSentComment.sent_status == "success", 1),
                    else_=0,
                )).label("success"),
            )
        )).one()
        total_sent = sent_row.total or 0
        success_sent = int(sent_row.success or 0)

        # 回复统计(总数 + AI 已回 + 待处理 一次查询)
        reply_row = (await session.execute(
            select(
                func.count(XTwitterReply.id).label("total"),
                func.sum(case(
                    (XTwitterReply.auto_reply_status == "sent", 1),
                    else_=0,
                )).label("auto_replied"),
                func.sum(case(
                    (XTwitterReply.auto_reply_status == "pending", 1),
                    else_=0,
                )).label("pending"),
            )
        )).one()
        total_replies = reply_row.total or 0
        auto_replied = int(reply_row.auto_replied or 0)
        pending_replies = int(reply_row.pending or 0)

    return {
        "total_sent_comments": total_sent,
        "success_sent": success_sent,
        "draft_or_failed": total_sent - success_sent,
        "total_replies": total_replies,
        "auto_replied": auto_replied,
        "pending_replies": pending_replies,
    }


# ==================== 帖子监控相关接口 ====================

class AddMonitoredPostRequest(BaseModel):
    post_id: str = Field(..., description="推文ID")
    post_url: str = Field(..., description="推文URL")
    post_content: str = Field("", description="推文内容")
    post_username: str = Field("", description="推文作者用户名")


@router.post("/posts/monitor")
async def add_monitored_post(request: AddMonitoredPostRequest):
    """添加要监控的帖子（自己发的帖子，监控评论并自动回复）"""
    async with get_session() as session:
        existing = (await session.execute(
            select(XTwitterMonitoredPost).where(XTwitterMonitoredPost.post_id == request.post_id)
        )).scalar_one_or_none()

        if existing:
            existing.monitoring = 1
            existing.post_content = request.post_content or existing.post_content
            existing.post_username = request.post_username or existing.post_username
            existing.last_modify_ts = int(time.time())
            await session.commit()
            return {"success": True, "message": "帖子已更新为监控状态"}

        new_post = XTwitterMonitoredPost(
            post_id=request.post_id,
            post_url=request.post_url,
            post_content=request.post_content,
            post_username=request.post_username,
            monitoring=1,
            add_ts=int(time.time()),
            last_modify_ts=int(time.time()),
        )
        session.add(new_post)
        await session.commit()
        return {"success": True, "message": "帖子已添加到监控"}


@router.get("/posts/monitor")
async def list_monitored_posts():
    """获取监控帖子列表"""
    async with get_session() as session:
        stmt = select(XTwitterMonitoredPost).order_by(desc(XTwitterMonitoredPost.add_ts))
        result = await session.execute(stmt)
        posts = result.scalars().all()

        items = []
        for p in posts:
            items.append({
                "id": p.id,
                "post_id": p.post_id,
                "post_url": p.post_url,
                "post_content": p.post_content,
                "post_username": p.post_username,
                "monitoring": p.monitoring,
                "total_comments": p.total_comments,
                "auto_replied_count": p.auto_replied_count,
                "add_ts": p.add_ts,
            })

    return {"items": items}


@router.delete("/posts/monitor/{post_id}")
async def remove_monitored_post(post_id: str):
    """移除帖子监控"""
    async with get_session() as session:
        post = (await session.execute(
            select(XTwitterMonitoredPost).where(XTwitterMonitoredPost.post_id == post_id)
        )).scalar_one_or_none()

        if not post:
            raise HTTPException(status_code=404, detail="帖子不存在")

        post.monitoring = 0
        await session.commit()
        return {"success": True, "message": "帖子监控已停止"}


@router.get("/posts/{post_id}/comments")
async def list_post_comments(post_id: str):
    """获取帖子下的评论（监控的帖子）"""
    async with get_session() as session:
        mp = (await session.execute(
            select(XTwitterMonitoredPost).where(XTwitterMonitoredPost.post_id == post_id)
        )).scalar_one_or_none()

        if not mp:
            raise HTTPException(status_code=404, detail="帖子未监控")

        stmt = select(XTwitterPostReply).where(
            XTwitterPostReply.monitored_post_id == mp.id
        ).order_by(desc(XTwitterPostReply.add_ts))
        result = await session.execute(stmt)
        comments = result.scalars().all()

        items = []
        for c in comments:
            items.append({
                "id": c.id,
                "comment_id": c.comment_id,
                "comment_url": c.comment_url,
                "commenter_username": c.commenter_username,
                "commenter_nickname": c.commenter_nickname,
                "comment_content": c.comment_content,
                "auto_reply_status": c.auto_reply_status,
                "auto_reply_content": c.auto_reply_content,
                "add_ts": c.add_ts,
            })

    return {"items": items}


# ==================== 热点采集相关接口 ====================

@router.get("/trending/topics")
async def get_trending_topics(limit: int = 10):
    """获取 X Twitter 热点话题列表"""
    from api.services.x_trending_fetcher import get_trending_topics
    topics = await get_trending_topics(limit)
    return {"items": topics}


@router.get("/trending/posts")
async def get_trending_posts(topic_id: Optional[int] = None, limit: int = 20):
    """获取 X Twitter 热点帖子列表"""
    from api.services.x_trending_fetcher import get_trending_posts
    posts = await get_trending_posts(topic_id, limit)
    return {"items": posts}


@router.get("/trending/stats")
async def get_trending_stats():
    """获取热点采集统计数据"""
    from api.services.x_trending_fetcher import get_trending_stats
    return await get_trending_stats()


@router.post("/trending/crawl")
async def crawl_trending_once():
    """触发一次热点采集"""
    from api.services.x_trending_fetcher import crawl_trending
    asyncio.create_task(crawl_trending())
    return {"success": True, "message": "热点采集任务已启动"}


@router.post("/trending/test")
async def test_trending_crawl():
    """测试热点采集（同步执行，直接返回结果）"""
    from api.services.x_trending_fetcher import _crawl_with_playwright_direct
    
    try:
        posts = await _crawl_with_playwright_direct()
        
        result = {
            "success": True,
            "count": len(posts),
            "posts": []
        }
        
        for post in posts[:10]:
            result["posts"].append({
                "post_id": post.get("post_id"),
                "username": post.get("username"),
                "content": post.get("content", "")[:100] + "..." if len(post.get("content", "")) > 100 else post.get("content"),
                "post_url": post.get("post_url"),
                "likes_count": post.get("likes_count"),
                "views_count": post.get("views_count"),
            })
        
        if len(posts) > 10:
            result["posts"].append({"message": f"... 还有 {len(posts) - 10} 条帖子"})
        
        return result
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


@router.get("/trending/monitor/status")
async def trending_monitor_status():
    """获取热点采集监控状态"""
    from api.services.x_trending_fetcher import get_trending_monitor_status
    return get_trending_monitor_status()


@router.post("/trending/monitor/start")
async def trending_monitor_start():
    """启动热点采集定时任务"""
    from api.services.x_trending_fetcher import start_trending_monitor
    start_trending_monitor()
    return {"success": True, "message": "热点采集定时任务已启动"}


@router.post("/trending/monitor/stop")
async def trending_monitor_stop():
    """停止热点采集定时任务"""
    from api.services.x_trending_fetcher import stop_trending_monitor
    await stop_trending_monitor()
    return {"success": True, "message": "热点采集定时任务已停止"}


# ==================== Cookie 池管理接口 ====================

@router.get("/cookie-pool/status")
async def cookie_pool_status():
    """获取 Cookie 池状态"""
    from api.services.cookie_pool_manager import get_pool_status, get_pool_summary
    return {
        "summary": get_pool_summary(),
        "items": get_pool_status(),
    }


class AddCookieRequest(BaseModel):
    cookie: str = Field(..., description="Cookie 字符串，格式: auth_token=xxx; ct0=yyy")


@router.post("/cookie-pool/add")
async def cookie_pool_add(req: AddCookieRequest):
    """添加 Cookie 到池中"""
    from api.services.cookie_pool_manager import add_cookie_to_env
    success = add_cookie_to_env(req.cookie.strip())
    if success:
        return {"success": True, "message": "Cookie 已添加到池中"}
    return {"success": False, "message": "Cookie 已存在或格式无效"}


class RemoveCookieRequest(BaseModel):
    cookie: str = Field(..., description="要移除的 Cookie 字符串")


@router.post("/cookie-pool/remove")
async def cookie_pool_remove(req: RemoveCookieRequest):
    """从池中移除 Cookie"""
    from api.services.cookie_pool_manager import remove_cookie_from_env
    success = remove_cookie_from_env(req.cookie.strip())
    if success:
        return {"success": True, "message": "Cookie 已从池中移除"}
    return {"success": False, "message": "Cookie 不在池中"}


@router.post("/cookie-pool/reset")
async def cookie_pool_reset():
    """重置所有 Cookie 的失败计数和冷却状态"""
    from api.services.cookie_pool_manager import clear_all_failures
    clear_all_failures()
    return {"success": True, "message": "所有 Cookie 状态已重置"}


@router.post("/cookie-pool/test")
async def cookie_pool_test():
    """测试当前可用的 Cookie（触发一次简单的页面访问）"""
    from api.services.cookie_pool_manager import get_cookie_from_pool, mark_cookie_success, mark_cookie_failure

    cookie = get_cookie_from_pool()
    if not cookie:
        return {"success": False, "message": "Cookie 池为空"}

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = await browser.new_context()

            cookie_list = []
            for pair in cookie.split(";"):
                pair = pair.strip()
                if not pair or "=" not in pair:
                    continue
                k, v = pair.split("=", 1)
                cookie_list.append({
                    "name": k.strip(), "value": v.strip(),
                    "domain": ".x.com", "path": "/",
                    "httpOnly": False, "secure": True, "sameSite": "Lax",
                })

            await context.add_cookies(cookie_list)
            page = await context.new_page()
            await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            try:
                await page.wait_for_selector('div[data-testid="SideNav_NewTweet_Button"]', timeout=5000)
                mark_cookie_success(cookie)
                await browser.close()
                return {"success": True, "message": "Cookie 有效，已成功登录"}
            except Exception:
                mark_cookie_failure(cookie, "登录验证失败")
                await browser.close()
                return {"success": False, "message": "Cookie 无效或已失效"}

    except Exception as e:
        mark_cookie_failure(cookie, str(e))
        return {"success": False, "message": f"测试失败: {e}"}
