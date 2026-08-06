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
import os
import time
import uuid
from typing import Any, Dict, List, Optional
from weakref import WeakValueDictionary

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Request
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
    post_id: str = Field(..., description="帖子ID")
    force_refresh: bool = Field(False, description="是否强制重新生成拆解")
    platform: str = Field("x", description="平台: x/dy/xhs/bili/wb/ks/youtube等")
    post_url: str = Field("", description="帖子URL（非X平台必填，用于AI拆解）")
    content: str = Field("", description="帖子内容（非X平台必填，用于AI拆解）")
    username: str = Field("", description="帖子作者（非X平台可选）")
    video_url: str = Field("", description="视频URL（非X平台可选）")


class ExplainerVideoRequest(BaseModel):
    post_id: str = Field(..., description="帖子ID")
    idempotency_key: UUID4 = Field(..., description="本次视频生成意图 UUID v4")
    platform: str = Field("x", description="平台: x/douyin/xiaohongshu/bilibili/weibo/kuaishou/youtube")
    post_url: str = Field("", description="帖子URL（非X平台必填）")
    content: str = Field("", description="帖子内容（非X平台必填）")
    video_url: str = Field("", description="视频URL（非X平台可选）")
    username: str = Field("", description="帖子作者（非X平台可选）")
    custom_prompt: str = Field("", description="用户自定义视频内容/参考（覆盖拆解上下文）")


class GenerateCommentsRequest(BaseModel):
    post_id: str = Field(..., description="帖子ID")
    count: int = Field(3, ge=1, le=10, description="生成评论数")
    platform: str = Field("x", description="平台: x/douyin/xiaohongshu/bilibili/weibo等")
    post_url: str = Field("", description="帖子URL（非X平台可选）")
    content: str = Field("", description="帖子内容（非X平台必填）")
    username: str = Field("", description="帖子作者")
    video_url: str = Field("", description="视频URL")


class GeneratePostContentRequest(BaseModel):
    post_id: str = Field(..., description="帖子ID")
    count: int = Field(3, ge=1, le=10, description="生成文案数量")
    platform: str = Field("x", description="目标平台: x/douyin/xiaohongshu/bilibili/weibo等")
    post_url: str = Field("", description="帖子URL（非X平台可选）")
    content: str = Field("", description="帖子内容（非X平台必填）")
    username: str = Field("", description="帖子作者")
    video_url: str = Field("", description="视频URL")


class SendCommentRequest(BaseModel):
    post_id: str = Field(..., description="推文ID")
    post_url: str = Field(..., description="推文URL")
    content: str = Field(..., min_length=1, max_length=280, description="评论内容")
    real_send: bool = Field(True, description="是否真实发送。False=草稿模式")
    platform: str = Field("x", description="评论所属平台: x/dy/xhs/bili/wb/ks")


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


def _explainer_request_hash(post_id: str, platform: str = "x", custom_prompt: str = "") -> str:
    canonical = json.dumps(
        {"post_id": post_id, "platform": platform, "custom_prompt": custom_prompt},
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
    trending_post = result.scalars().first()
    
    if trending_post:
        video_url = trending_post.video_url
        if not video_url and trending_post.post_url:
            video_url = f"{trending_post.post_url}/video/1"
        
        return XTwitterPost(
            id=0,
            post_id=trending_post.post_id,
            post_url=trending_post.post_url,
            username=trending_post.username,
            nickname=trending_post.nickname,
            content=trending_post.content,
            video_url=video_url,
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
    post = result.scalars().first()
    
    if post and not post.video_url and post.post_url:
        post.video_url = f"{post.post_url}/video/1"
    
    return post


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
    import time as _time
    _t0 = _time.time()
    # 统一从热点聚合获取数据（热点聚合负责采集最新热点）
    result = await _trending_from_hotpoint(platform, limit, keyword, has_video)
    _elapsed = _time.time() - _t0
    logger.info(f"[get_trending] platform={platform} limit={limit} items={len(result.get('items',[]))} elapsed={_elapsed:.2f}s")
    
    # X 平台额外把 hotpoint 数据写回数据库，供视频拆解等流程复用
    if platform == "x" and result.get("items"):
        try:
            saved = await _persist_x_posts_from_hotpoint(result["items"])
            result["persisted"] = saved
            if saved > 0:
                result["hint"] = f"已自动入库 {saved} 条"
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
        meta = PLATFORMS.get(platform, {})
        platform_name = meta.get("name", platform)
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
            # 作者：优先用真实 author，为空时用平台展示名（如"小红书"）避免显示 @unknown
            author = it.get("author", "") or platform_name
            items.append({
                "post_id": post_id,
                "post_url": url,
                "username": author,
                "nickname": author,
                "content": title,
                "video_url": video_url,
                "image_urls": "",
                "likes_count": str(it.get("hot", "0")),
                "retweets_count": str(extra.get("retweets", "0")),
                "replies_count": str(extra.get("replies", "0")),
                "views_count": str(extra.get("views", "0")),
                "created_at": it.get("published_at", 0),
                # 用平台展示名（如"小红书"）而非原始 id（"xiaohongshu"），前端 Tag 更友好
                "source_keyword": platform_name,
            })

        # X 平台：把 hotpoint 拉到的数据持久化到 XTwitterPost 表
        # 这样后续的视频拆解、评论发送等流程才能用真实 post_id
        saved_count = 0
        if platform == "x" and items:
            saved_count = await _persist_x_posts_from_hotpoint(items)

        # 查询数据库中该平台的数据总量
        # X 平台查 XTwitterPost 表，其他平台查 hot_items 表（统一热点库）
        total_in_db = 0
        if platform == "x":
            async with get_session() as session:
                total_in_db = (await session.execute(select(func.count(XTwitterPost.id)))).scalar() or 0
        else:
            # 其他平台查 hot_items 表（统一热点库）
            try:
                from api.services.hotpoint.hot_items_store import get_hot_items_store
                store = get_hot_items_store()
                await store.ensure_table()
                # 通过 store 查询该平台的数据量
                from database.db_session import get_async_engine
                import config
                from sqlalchemy import text as sql_text
                engine = get_async_engine(config.SAVE_DATA_OPTION)
                if engine:
                    async with engine.connect() as conn:
                        r = await conn.execute(
                            sql_text("SELECT COUNT(*) FROM hot_items WHERE platform = :p AND is_disabled = FALSE"),
                            {"p": platform},
                        )
                        total_in_db = r.fetchone()[0] or 0
            except Exception as e:
                logger.warning(f"[get_trending] 查询 {platform} 平台 total_in_db 失败: {e}")
                total_in_db = len(items)

        # 非X平台：后台异步把数据 upsert 到 hot_items 表（真正不阻塞响应）
        # 集成热点分类器：若上游未带 category，调用 HotpointClassifier 标注
        # ⚠️ 必须用 asyncio.create_task 后台执行，否则 500 条 × (AI分类1-5s + DB写入) = 数分钟阻塞
        if platform != "x" and items:
            asyncio.create_task(_background_upsert_hot_items(platform, items))

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


async def _background_upsert_hot_items(platform: str, items: List[Dict[str, Any]]) -> None:
    """后台异步把热点数据 upsert 到 hot_items 表 + 集成热点分类器

    ⚠️ 此函数通过 asyncio.create_task 后台调用，绝不阻塞 HTTP 响应。
    之前的实现在请求路径中串行 await classifier.classify + store.upsert，
    导致 500 条数据 × (AI分类1-5s + DB写入) = 数分钟阻塞，切换平台极慢。
    """
    try:
        from api.services.hotpoint.hot_items_store import get_hot_items_store
        from api.services.hotpoint.hotpoint_classifier import get_hotpoint_classifier
        store = get_hot_items_store()
        classifier = get_hotpoint_classifier()

        # 预检 AI 冷却状态，冷却中跳过分类（静默降级）
        ai_in_cooldown = False
        try:
            from api.services.ai_agent_client import is_ai_in_cooldown
            ai_in_cooldown = is_ai_in_cooldown()
        except Exception:
            pass

        for it in items:
            try:
                title = (it.get("content", "") or "")[:500]
                content = it.get("content", "")
                category = ""
                recommended_platforms = ""
                # 仅在 AI 未冷却时调用分类器
                if title and not ai_in_cooldown:
                    try:
                        classification = await classifier.classify(title, content)
                        category = classification.category
                        if classification.recommended_platforms:
                            recommended_platforms = ",".join(classification.recommended_platforms)
                    except Exception as ce:
                        logger.debug(f"[bg_upsert] hotpoint classify 跳过(非致命): {ce}")
                await store.upsert({
                    "platform": platform,
                    "source_id": it.get("post_id", "")[:128],
                    "title": title,
                    "content": content,
                    "url": it.get("post_url", ""),
                    "video_url": it.get("video_url", ""),
                    "username": (it.get("username", "") or "")[:128],
                    "heat_value": int(it.get("likes_count", "0") or 0),
                    "source_keyword": platform,
                    "category": category,
                    "recommended_platforms": recommended_platforms,
                })
            except Exception:
                continue
        logger.info(f"[bg_upsert] {platform} 后台入库完成, 共 {len(items)} 条, AI冷却={ai_in_cooldown}")
    except Exception as e:
        logger.warning(f"[bg_upsert] {platform} 后台入库失败(非致命): {e}")


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
    """生成或获取视频拆解（支持所有平台）

    - X 平台：从 XTwitterPost/XTwitterTrendingPost 表查帖子内容
    - 非 X 平台（抖音/小红书/B站等）：直接使用请求中的 post_url/content/video_url，
      不依赖数据库查表（这些平台的帖子不在 X 专属表中）
    """
    from api.services import ai_agent_client
    from api.services.hotpoint_fetcher import normalize_platform_id

    norm_platform = normalize_platform_id(req.platform)

    # 先查数据库是否已有拆解（所有平台共用 XTwitterVideoBreakdown 表，post_id 唯一）
    async with get_session() as session:
        stmt = select(XTwitterVideoBreakdown).where(XTwitterVideoBreakdown.post_id == req.post_id)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        # 如果已有缓存且不是强制刷新，则返回缓存
        if existing and not req.force_refresh:
            # X 平台额外检查是否有视频URL（无视频的帖子不适合拆解）
            if norm_platform == "x":
                post = await _get_post_by_id(session, req.post_id)
                if post and not post.video_url:
                    pass  # 有缓存但无视频，继续重新生成
                else:
                    def _parse_json_list(value: str) -> list:
                        if not value:
                            return []
                        try:
                            import json
                            return json.loads(value)
                        except (TypeError, ValueError):
                            return []

                    return {
                        "source": "cache",
                        "post_id": req.post_id,
                        "script": existing.script,
                        "storyboards": _parse_json_list(existing.storyboards),
                        "key_points": _parse_json_list(existing.key_points),
                        "suggested_comments": _parse_json_list(existing.suggested_comments),
                    }
            else:
                # 非 X 平台：直接返回缓存
                def _parse_json_list(value: str) -> list:
                    if not value:
                        return []
                    try:
                        import json
                        return json.loads(value)
                    except (TypeError, ValueError):
                        return []

                return {
                    "source": "cache",
                    "post_id": req.post_id,
                    "script": existing.script,
                    "storyboards": _parse_json_list(existing.storyboards),
                    "key_points": _parse_json_list(existing.key_points),
                    "suggested_comments": _parse_json_list(existing.suggested_comments),
                }

    # 获取帖子内容用于 AI 拆解
    if norm_platform == "x":
        # X 平台：从数据库查帖子
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
    else:
        # 非 X 平台：直接使用请求中的数据（前端已持有帖子信息）
        if not req.content and not req.post_url:
            raise HTTPException(400, f"非X平台拆解需要提供 post_url 和 content")
        post_dict = {
            "post_id": req.post_id,
            "post_url": req.post_url,
            "content": req.content,
            "video_url": req.video_url,
            "username": req.username or norm_platform,
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
                post_url=post_dict["post_url"],
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
        extract_video_frames,
        normalize_media_urls,
        submit_explainer_video,
    )
    from config.onellm_config import load_onellm_config
    owner_user_id = str(current_user["id"])
    idempotency_key = str(req.idempotency_key)
    request_hash = _explainer_request_hash(req.post_id, req.platform, req.custom_prompt)

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
            from api.services.hotpoint_fetcher import normalize_platform_id
            norm_platform = normalize_platform_id(req.platform)

            async with get_session() as session:
                if norm_platform == "x":
                    post = await _get_post_by_id(session, req.post_id)
                else:
                    # 非 X 平台：从请求数据构造 post-like 对象（不依赖 X 专属表）
                    class _NonXPost:
                        pass
                    post = _NonXPost()
                    post.post_id = req.post_id
                    post.post_url = req.post_url
                    post.content = req.content
                    post.video_url = req.video_url
                    post.image_urls = []
                    post.username = req.username or norm_platform

                breakdown_result = await session.execute(
                    select(XTwitterVideoBreakdown).where(
                        XTwitterVideoBreakdown.post_id == req.post_id
                    )
                )
                breakdown = breakdown_result.scalar_one_or_none()

            if norm_platform == "x" and not post:
                raise HTTPException(404, f"推文 {req.post_id} 不存在")
            if not breakdown:
                raise HTTPException(400, "请先完成视频拆解，再生成解说视频")

            image_urls = normalize_media_urls(getattr(post, "image_urls", None))
            video_urls = normalize_media_urls(getattr(post, "video_url", None))

            if not image_urls:
                video_url_to_use = ""
                if video_urls:
                    video_url_to_use = video_urls[0]
                elif post.post_url:
                    video_url_to_use = f"{post.post_url}/video/1"

                if video_url_to_use:
                    logger.info(f"[generate_explainer_video] Extracting frames from video: {video_url_to_use}")
                    try:
                        frames = await extract_video_frames(video_url_to_use, max_frames=3)
                        if frames:
                            image_urls = frames
                            logger.info(f"[generate_explainer_video] Extracted {len(frames)} frames as reference images")
                        else:
                            logger.warning(f"[generate_explainer_video] Failed to extract frames from video")
                    except Exception as e:
                        logger.warning(f"[generate_explainer_video] Error extracting frames: {e}")

            # 用户自定义内容优先，否则用拆解上下文构建 prompt
            if req.custom_prompt and req.custom_prompt.strip():
                prompt = req.custom_prompt.strip()
            else:
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


@router.get("/explainer-video/by-post/{post_id}")
async def get_explainer_video_by_post(
    post_id: str,
    current_user: dict = Depends(get_current_user),
):
    """按 post_id 查询当前用户最新的解说视频任务。

    用于页面关闭后重新进入时恢复已生成/生成中的视频,避免重复扣费生成。
    返回最新一条任务记录;若无任何记录返回 404。
    """
    owner_user_id = str(current_user["id"])
    async with get_session() as session:
        result = await session.execute(
            select(XTwitterExplainerVideoTask)
            .where(
                XTwitterExplainerVideoTask.owner_user_id == owner_user_id,
                XTwitterExplainerVideoTask.post_id == post_id,
            )
            .order_by(desc(XTwitterExplainerVideoTask.created_ts))
            .limit(1)
        )
        task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(404, "该内容暂无视频任务记录")

    is_final = task.status in {"done", "error", "submission_unknown"}
    return {
        "task_id": task.local_task_id,
        "status": task.status or "submitting",
        "is_final": is_final,
        "progress": task.progress or 0,
        "current_step": task.status or "submitting",
        "result_url": task.result_url or "",
        "error": task.error or "",
        "cost": task.cost or 0,
        "model_name": task.model_name or "",
        "created_ts": task.created_ts or 0,
    }


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

def _breakdown_prompt_text(breakdown: XTwitterVideoBreakdown) -> str:
    """把数据库中的拆解 JSON 转成适合模型阅读的完整上下文。"""
    def _format_items(value: str) -> str:
        if not value:
            return ""
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return str(value)
        if isinstance(parsed, list):
            return "\n".join(f"{index}. {item}" for index, item in enumerate(parsed, 1))
        return str(parsed)

    return (
        f"【脚本分析】\n{breakdown.script or ''}\n\n"
        f"【分镜拆解】\n{_format_items(breakdown.storyboards)}\n\n"
        f"【关键要点】\n{_format_items(breakdown.key_points)}\n\n"
        f"【原推荐评论】\n{_format_items(breakdown.suggested_comments)}"
    )


def _post_context(req: Any, db_post: Any = None) -> Dict[str, str]:
    """X 使用数据库原帖，其他平台使用前端携带的热点内容。"""
    return {
        "post_id": req.post_id,
        "post_url": (getattr(db_post, "post_url", "") or req.post_url),
        "content": (getattr(db_post, "content", "") or req.content),
        "username": (getattr(db_post, "username", "") or req.username),
        "video_url": (getattr(db_post, "video_url", "") or req.video_url),
        "platform": req.platform,
    }


@router.post("/generate-comments", dependencies=[Depends(ai_rate_limit())])
async def generate_comments(req: GenerateCommentsRequest):
    """根据拆解结果生成多条评论"""
    from api.services import ai_agent_client

    async with get_session() as session:
        post = await _get_post_by_id(session, req.post_id)
        stmt = select(XTwitterVideoBreakdown).where(XTwitterVideoBreakdown.post_id == req.post_id)
        bd_result = await session.execute(stmt)
        bd = bd_result.scalar_one_or_none()

    if not post and not req.content.strip():
        raise HTTPException(404, "帖子不存在，且请求中未提供帖子内容")
    if not bd:
        raise HTTPException(400, "请先完成视频拆解，再生成候选评论")

    breakdown_text = _breakdown_prompt_text(bd)
    post_dict = _post_context(req, post)

    try:
        comments = await ai_agent_client.generate_comments(
            post_dict,
            breakdown_text,
            count=req.count,
        )
    except Exception as e:
        raise HTTPException(500, f"AI 评论生成失败: {e}")

    return {"post_id": req.post_id, "comments": comments, "platform": req.platform}


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
            platform=req.platform,
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

_sent_comment_column_ensured = False

async def _ensure_sent_comment_platform_column():
    """确保 x_twitter_sent_comment 表有 platform 列（兼容历史数据的自动迁移）

    首次调用时执行 ALTER TABLE ADD COLUMN IF NOT EXISTS，
    将 platform 列添加到已有表中，默认值 'x'（历史数据都是 X 平台）。
    后续调用直接跳过（_sent_comment_column_ensured = True）。
    """
    global _sent_comment_column_ensured
    if _sent_comment_column_ensured:
        return
    try:
        from database.db_session import get_async_engine
        import config
        from sqlalchemy import text as sql_text
        engine = get_async_engine(config.SAVE_DATA_OPTION)
        if engine:
            async with engine.begin() as conn:
                await conn.execute(sql_text(
                    "ALTER TABLE x_twitter_sent_comment "
                    "ADD COLUMN IF NOT EXISTS platform VARCHAR(32) DEFAULT 'x'"
                ))
                # 为已有数据设置默认平台为 x（仅更新 NULL 行）
                await conn.execute(sql_text(
                    "UPDATE x_twitter_sent_comment SET platform = 'x' "
                    "WHERE platform IS NULL"
                ))
            _sent_comment_column_ensured = True
            logger.info("[sent_comment] platform 列已确保存在（迁移完成）")
    except Exception as e:
        logger.warning(f"[sent_comment] 确保 platform 列失败(非致命): {e}")


@router.get("/comments")
async def list_sent_comments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query("", description="按状态筛选: success/failed/draft"),
    keyword: str = Query("", description="搜索关键词（匹配评论内容或推文内容）"),
    start_ts: int = Query(0, description="开始时间戳"),
    end_ts: int = Query(0, description="结束时间戳"),
    platform: str = Query("", description="按平台筛选: x/dy/xhs/bili/wb/ks（空=全部）"),
):
    """获取已发评论列表（按平台过滤）"""
    # 兼容历史数据：确保 platform 列存在（首次调用时自动迁移）
    await _ensure_sent_comment_platform_column()

    # 平台别名归一化（x_twitter → x, xhs → xiaohongshu 等）
    from api.services.hotpoint_fetcher import normalize_platform_id
    norm_platform = normalize_platform_id(platform) if platform else ""

    async with get_session() as session:
        stmt = select(XTwitterSentComment).order_by(desc(XTwitterSentComment.add_ts))
        count_stmt = select(func.count(XTwitterSentComment.id))

        # 按平台过滤（核心修复：切换平台时只显示对应平台的评论）
        if norm_platform:
            stmt = stmt.where(XTwitterSentComment.platform == norm_platform)
            count_stmt = count_stmt.where(XTwitterSentComment.platform == norm_platform)

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
                "platform": sc.platform or "x",
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
    from api.services.comment_reply_monitor import _check_all_sent_comments, _check_all_monitored_posts
    import asyncio
    # 并行执行两个检查（与 _monitor_loop 保持一致）
    await asyncio.gather(
        _check_all_sent_comments(),
        _check_all_monitored_posts(),
    )
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

@router.get("/monitor/platforms")
async def monitor_platforms_overview():
    """多平台监控总览：返回所有 15 个平台（7 国内 + 8 国外）的数据采集状态

    返回每个平台的：展示名、区域、颜色、DB 条数、缓存条数、缓存年龄、最近采集信息
    """
    import time as _time
    from api.services.hotpoint_fetcher import PLATFORMS
    # 兼容：hotpoint_fetcher 的 _CACHE 是 {platform: (timestamp, items)}
    from api.services import hotpoint_fetcher as _hp

    overview = []
    # 查询 hot_items 表中各平台的条数（非 X 平台）
    platform_counts: Dict[str, int] = {}
    try:
        from database.db_session import get_async_engine
        import config
        from sqlalchemy import text as sql_text
        engine = get_async_engine(config.SAVE_DATA_OPTION)
        if engine:
            async with engine.connect() as conn:
                r = await conn.execute(
                    sql_text(
                        "SELECT platform, COUNT(*) FROM hot_items "
                        "WHERE is_disabled = FALSE GROUP BY platform"
                    )
                )
                for row in r.fetchall():
                    platform_counts[row[0]] = int(row[1] or 0)
    except Exception as e:
        logger.warning(f"[monitor_platforms] 查询 hot_items 统计失败: {e}")

    # X 平台查 XTwitterPost 表
    x_count = 0
    try:
        async with get_session() as session:
            x_count = (await session.execute(select(func.count(XTwitterPost.id)))).scalar() or 0
    except Exception:
        pass

    now = _time.time()
    for pid, meta in PLATFORMS.items():
        cache_count = 0
        cache_age = -1
        if pid in _hp._CACHE:
            ts, cached_items = _hp._CACHE[pid]
            cache_count = len(cached_items)
            cache_age = int(now - ts)

        db_count = x_count if pid == "x" else platform_counts.get(pid, 0)
        overview.append({
            "id": pid,
            "name": meta.get("name", pid),
            "region": meta.get("region", ""),
            "color": meta.get("color", "#666"),
            "home": meta.get("home", ""),
            "db_count": db_count,
            "cache_count": cache_count,
            "cache_age_seconds": cache_age,
        })

    return {
        "platforms": overview,
        "total_platforms": len(overview),
        "domestic_count": sum(1 for p in overview if p["region"] == "china"),
        "global_count": sum(1 for p in overview if p["region"] == "global"),
    }


@router.get("/stats")
async def get_stats(
    platform: str = Query("", description="按平台筛选统计: x/dy/xhs/bili/wb/ks（空=全部）"),
):
    """工作台统计数据（按平台过滤）

    优化:用条件聚合(case when)把 5 次 COUNT 查询合并为 2 次
    (sent_comment 表 1 次 + reply 表 1 次)
    并加 15 秒 TTL 缓存(多个面板同时打开时减少重复查询)
    """
    # 兼容历史数据：确保 platform 列存在
    await _ensure_sent_comment_platform_column()
    from api.services.hotpoint_fetcher import normalize_platform_id
    norm_platform = normalize_platform_id(platform) if platform else ""
    return await _get_stats_cached(norm_platform)


@ttl_cache(ttl_seconds=15)
async def _get_stats_cached(norm_platform: str = ""):
    """统计数据缓存层(15 秒 TTL)，按平台过滤"""
    async with get_session() as session:
        # 已发评论统计(总数 + 成功数 一次查询)
        sent_query = select(
            func.count(XTwitterSentComment.id).label("total"),
            func.sum(case(
                (XTwitterSentComment.sent_status == "success", 1),
                else_=0,
            )).label("success"),
        )
        if norm_platform:
            sent_query = sent_query.where(XTwitterSentComment.platform == norm_platform)
        sent_row = (await session.execute(sent_query)).one()
        total_sent = sent_row.total or 0
        success_sent = int(sent_row.success or 0)

        # 回复统计(总数 + AI 已回 + 待处理 一次查询)
        # 通过 JOIN sent_comment 表按平台过滤回复
        reply_query = select(
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
        if norm_platform:
            reply_query = reply_query.join(
                XTwitterSentComment,
                XTwitterReply.sent_comment_id == XTwitterSentComment.id,
                isouter=True,
            ).where(XTwitterSentComment.platform == norm_platform)
        reply_row = (await session.execute(reply_query)).one()
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


# ==================== 多平台发布文案生成 ====================

@router.post("/x-post-content", dependencies=[Depends(ai_rate_limit())])
async def generate_x_post_content(req: GeneratePostContentRequest):
    """根据视频拆解生成适合当前平台发布的文案。"""
    from api.services import ai_agent_client
    from api.services.hotpoint_fetcher import normalize_platform_id

    async with get_session() as session:
        post = await _get_post_by_id(session, req.post_id)
        breakdown_result = await session.execute(
            select(XTwitterVideoBreakdown).where(XTwitterVideoBreakdown.post_id == req.post_id)
        )
        breakdown = breakdown_result.scalar_one_or_none()

    if not post and not req.content.strip():
        raise HTTPException(404, f"帖子 {req.post_id} 不存在，且请求中未提供帖子内容")
    if not breakdown:
        raise HTTPException(400, "请先完成视频拆解，再生成发布文案")

    platform = normalize_platform_id(req.platform)
    breakdown_text = _breakdown_prompt_text(breakdown)
    post_dict = _post_context(req, post)

    try:
        contents = await ai_agent_client.generate_platform_post_content(
            post_dict,
            breakdown_text,
            platform,
            req.count,
        )
    except Exception as e:
        raise HTTPException(500, f"AI 发布文案生成失败: {e}") from e

    return {"post_id": req.post_id, "contents": contents, "platform": platform}


# ==================== 发布视频到 X ====================

class PublishToXRequest(BaseModel):
    post_id: str = Field(..., description="原推文ID")
    content: str = Field(..., description="发布文案")
    video_url: str = Field(None, description="视频URL（可选）")
    auto_monitor: bool = Field(True, description="是否自动监控发布后的评论")


async def _do_publish_to_x(cookies_str: str, content: str, video_url: str = None, server_base_url: str = "http://localhost:8000"):
    """执行实际的发布操作

    使用 X 的媒体上传 API + GraphQL CreateTweet 直接发布，绕过不可靠的 UI 文件上传。
    流程：
    1. 用 Playwright 打开 x.com，拦截 bearer token + 提取 ct0 (CSRF)
    2. 如有视频：通过分块上传 API (INIT→APPEND→FINALIZE→STATUS) 上传视频，获得 media_id
    3. 提取 CreateTweet queryId（JS 搜索 → UI 拦截 → 硬编码兜底）
    4. 用 GraphQL CreateTweet 发布推文（带 media_ids）
    """
    import os
    import re
    import base64
    import tempfile
    import httpx
    import json as _json
    from playwright.async_api import async_playwright

    if video_url and not video_url.startswith(("http://", "https://")):
        video_url = server_base_url.rstrip("/") + "/" + video_url.lstrip("/")

    cookie_list = []
    for pair in cookies_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        cookie_list.append({
            "name": k.strip(),
            "value": v.strip(),
            "domain": ".x.com",
            "path": "/",
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        })

    browser = None
    context = None
    page = None
    video_path = None
    p = None
    try:
        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-gpu", "--disable-software-rasterizer",
        ], timeout=60000)

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        await context.add_cookies(cookie_list)

        page = await context.new_page()
        page.set_default_timeout(60000)

        # ========== 1. 打开 x.com 获取 bearer token + ct0 ==========
        bearer_token = {"value": None}

        def _on_request(req):
            auth = req.headers.get("authorization", "")
            if auth.startswith("Bearer ") and not bearer_token["value"]:
                bearer_token["value"] = auth[7:]

        page.on("request", _on_request)

        logger.info("[publish_to_x] 打开 x.com 获取认证信息...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(8)

        all_cookies = await context.cookies()
        ct0 = next((c["value"] for c in all_cookies if c["name"] == "ct0"), None)
        logger.info(f"[publish_to_x] ct0={'有' if ct0 else '无'}, bearer={'有' if bearer_token['value'] else '无'}")

        if not ct0 or not bearer_token["value"]:
            raise RuntimeError(f"缺少认证信息: ct0={'有' if ct0 else '无'}, bearer={'有' if bearer_token['value'] else '无'}")

        bearer = bearer_token["value"]

        # ========== 2. 上传视频（如有）==========
        media_id = None
        if video_url:
            logger.info(f"[publish_to_x] 下载视频: {video_url}")
            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(video_url, timeout=60.0)
                if response.status_code != 200:
                    raise RuntimeError(f"下载视频失败: HTTP {response.status_code}")
                video_bytes = response.content
            logger.info(f"[publish_to_x] 视频下载成功，大小: {len(video_bytes)} 字节")

            # INIT
            init_result = await page.evaluate("""async (params) => {
                const body = new URLSearchParams();
                body.append('command', 'INIT');
                body.append('total_bytes', params.total_bytes);
                body.append('media_type', 'video/mp4');
                const r = await fetch('https://upload.x.com/i/media/upload.json', {
                    method: 'POST',
                    headers: {'authorization': 'Bearer ' + params.bearer, 'x-csrf-token': params.ct0, 'content-type': 'application/x-www-form-urlencoded'},
                    body: body.toString(), credentials: 'include',
                });
                return {status: r.status, body: await r.text()};
            }""", {"total_bytes": len(video_bytes), "bearer": bearer, "ct0": ct0})

            if init_result["status"] not in (200, 202):
                raise RuntimeError(f"媒体上传 INIT 失败: {init_result['status']} {init_result['body'][:200]}")

            init_data = _json.loads(init_result["body"])
            media_id = init_data.get("media_id_string")
            logger.info(f"[publish_to_x] INIT 成功, media_id={media_id}")

            # APPEND (分块上传，每块 1MB)
            chunk_size = 1024 * 1024
            total_chunks = (len(video_bytes) + chunk_size - 1) // chunk_size
            for seg_idx in range(total_chunks):
                start = seg_idx * chunk_size
                end = min(start + chunk_size, len(video_bytes))
                chunk_b64 = base64.b64encode(video_bytes[start:end]).decode("ascii")

                append_result = await page.evaluate("""async (params) => {
                    const bin = atob(params.chunk_b64);
                    const arr = new Uint8Array(bin.length);
                    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                    const blob = new Blob([arr], {type: 'application/octet-stream'});
                    const body = new FormData();
                    body.append('command', 'APPEND');
                    body.append('media_id', params.media_id);
                    body.append('segment_index', params.seg_idx);
                    body.append('media', blob);
                    const r = await fetch('https://upload.x.com/i/media/upload.json', {
                        method: 'POST',
                        headers: {'authorization': 'Bearer ' + params.bearer, 'x-csrf-token': params.ct0},
                        body: body, credentials: 'include',
                    });
                    return {status: r.status, body: await r.text()};
                }""", {"media_id": media_id, "seg_idx": seg_idx, "chunk_b64": chunk_b64, "bearer": bearer, "ct0": ct0})

                if append_result["status"] != 204:
                    raise RuntimeError(f"媒体上传 APPEND 块 {seg_idx} 失败: {append_result['status']} {append_result['body'][:200]}")
                logger.info(f"[publish_to_x] APPEND 块 {seg_idx + 1}/{total_chunks} 成功")

            # FINALIZE
            finalize_result = await page.evaluate("""async (params) => {
                const body = new URLSearchParams();
                body.append('command', 'FINALIZE');
                body.append('media_id', params.media_id);
                const r = await fetch('https://upload.x.com/i/media/upload.json', {
                    method: 'POST',
                    headers: {'authorization': 'Bearer ' + params.bearer, 'x-csrf-token': params.ct0, 'content-type': 'application/x-www-form-urlencoded'},
                    body: body.toString(), credentials: 'include',
                });
                return {status: r.status, body: await r.text()};
            }""", {"media_id": media_id, "bearer": bearer, "ct0": ct0})

            if finalize_result["status"] not in (200, 202):
                raise RuntimeError(f"媒体上传 FINALIZE 失败: {finalize_result['status']} {finalize_result['body'][:200]}")

            finalize_data = _json.loads(finalize_result["body"])
            processing_info = finalize_data.get("processing_info", {})
            logger.info(f"[publish_to_x] FINALIZE 成功, processing_info={processing_info}")

            # STATUS 轮询等待处理完成
            if processing_info.get("state") != "succeeded":
                for i in range(60):
                    await asyncio.sleep(2)
                    status_result = await page.evaluate("""async (params) => {
                        const r = await fetch('https://upload.x.com/i/media/upload.json?command=STATUS&media_id=' + params.media_id, {
                            method: 'GET',
                            headers: {'authorization': 'Bearer ' + params.bearer, 'x-csrf-token': params.ct0},
                            credentials: 'include',
                        });
                        return {status: r.status, body: await r.text()};
                    }""", {"media_id": media_id, "bearer": bearer, "ct0": ct0})

                    status_data = _json.loads(status_result["body"])
                    state = status_data.get("processing_info", {}).get("state", "unknown")
                    progress = status_data.get("processing_info", {}).get("progress_percent", 0)
                    logger.info(f"[publish_to_x] 视频处理: state={state}, progress={progress}%")

                    if state == "succeeded":
                        break
                    if state == "failed":
                        raise RuntimeError(f"视频处理失败: {status_data}")

        # ========== 3. 提取 CreateTweet queryId ==========
        query_id = None

        # 方法1: 搜索 JS bundle
        try:
            query_id = await asyncio.wait_for(page.evaluate("""async () => {
                const resources = performance.getEntriesByType('resource')
                    .filter(r => r.name.endsWith('.js') && r.transferSize > 50000)
                    .sort((a, b) => b.transferSize - a.transferSize).slice(0, 15).map(r => r.name);
                const patterns = [
                    /queryId["']?\\s*[:=]\\s*["']([A-Za-z0-9_-]{15,30})["'][\\s\\S]{0,300}CreateTweet/,
                    /CreateTweet[\\s\\S]{0,300}queryId["']?\\s*[:=]\\s*["']([A-Za-z0-9_-]{15,30})["']/,
                    /["']([A-Za-z0-9_-]{15,30})["']\\s*[,}]\\s*["']?operationName["']?\\s*[:=]\\s*["']CreateTweet["']/,
                ];
                for (const url of resources) {
                    try {
                        const r = await fetch(url);
                        const text = await r.text();
                        if (!text.includes('CreateTweet')) continue;
                        for (const p of patterns) { const m = text.match(p); if (m) return m[1]; }
                    } catch(e) {}
                }
                return null;
            }"""), timeout=30)
            if query_id:
                logger.info(f"[publish_to_x] 从 JS bundle 提取 queryId: {query_id}")
        except Exception as e:
            logger.warning(f"[publish_to_x] JS 搜索 queryId 失败: {e}")

        # 方法2: UI 拦截 — 只填入文本触发 GraphQL 请求拦截，不点击发送按钮（避免误发 "test" 推文）
        if not query_id:
            captured_url = {"value": None}
            async def _capture_route(route):
                captured_url["value"] = route.request.url
                await route.abort()
            await page.route("**/graphql/**/CreateTweet**", _capture_route)
            try:
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                compose_btn = await page.query_selector('[data-testid="SideNav_NewTweet_Button"], a[href="/compose/post"]')
                if compose_btn:
                    await compose_btn.click()
                    await asyncio.sleep(3)
                else:
                    await page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(5)
                textarea = await page.query_selector('[data-testid="tweetTextarea_0"]')
                if textarea:
                    await textarea.click()
                    await textarea.fill("test")
                    await asyncio.sleep(1)
                    # 不再点击发送按钮！只填入文本，X 会预加载 CreateTweet GraphQL 端点
                    # 通过 page.route 拦截请求 URL 即可获取 queryId
                    # 等待 X 前端发起 CreateTweet 请求（输入文本后前端会 prefetch/validate）
                    await asyncio.sleep(3)
                    if not captured_url["value"]:
                        # 如果仅填写未触发，尝试通过 JS 监听 fetch 拦截
                        captured_url["value"] = await page.evaluate("""() => {
                            const entries = performance.getEntriesByType('resource');
                            for (const e of entries) {
                                if (e.name.includes('CreateTweet')) return e.name;
                            }
                            return null;
                        }""")
                if captured_url["value"]:
                    m = re.search(r'/graphql/([^/]+)/CreateTweet', captured_url["value"])
                    if m:
                        query_id = m.group(1)
                        logger.info(f"[publish_to_x] 从 UI 拦截提取 queryId: {query_id}")
            except Exception as e:
                logger.warning(f"[publish_to_x] UI 拦截 queryId 失败: {e}")
            finally:
                try:
                    await page.unroute("**/graphql/**/CreateTweet**")
                except Exception:
                    pass

        # 方法3: 硬编码兜底
        if not query_id:
            query_id = "hIL9XdleMYEtVXOZVbr8Bg"
            logger.warning(f"[publish_to_x] 使用硬编码 queryId: {query_id}")

        # ========== 4. GraphQL CreateTweet 发布推文 ==========
        logger.info(f"[publish_to_x] 通过 GraphQL 发布推文 (media_id={media_id})...")

        # 发布前记录用户主页已有推文 ID 快照，用于后续对比识别新增推文
        pre_tweet_ids: list = []
        try:
            username = os.getenv("X_TWITTER_MY_USERNAME", "GreyCheng90328")
            await page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            pre_links = await page.query_selector_all('article[data-testid="tweet"] a[href*="/status/"]')
            for link in pre_links:
                href = await link.get_attribute("href")
                if href and "/status/" in href:
                    tid = href.split("/status/")[1].split("/")[0].split("?")[0]
                    pre_tweet_ids.append(tid)
            logger.info(f"[publish_to_x] 发布前快照: 主页已有 {len(pre_tweet_ids)} 条推文")
        except Exception as e:
            logger.warning(f"[publish_to_x] 获取发布前快照失败(不影响发布): {e}")

        create_result = await page.evaluate("""async (params) => {
            const features = {
                "communities_web_enable_tweet_community_results_fetch": true,
                "c9s_tweet_anatomy_moderator_badge_enabled": true,
                "tweetypie_unmention_optimization_enabled": true,
                "responsive_web_edit_tweet_api_enabled": true,
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled": true,
                "view_counts_everywhere_api_enabled": true,
                "longform_notetweets_consumption_enabled": true,
                "responsive_web_twitter_article_tweet_consumption_enabled": true,
                "tweet_awards_web_tipping_enabled": false,
                "creator_subscriptions_quote_tweet_enabled": true,
                "longform_notetweets_rich_text_read_enabled": true,
                "longform_notetweets_inline_media_enabled": true,
                "articles_preview_enabled": true,
                "rweb_video_timestamps_enabled": true,
                "rweb_tipjar_consumption_enabled": true,
                "responsive_web_graphql_exclude_directive_enabled": true,
                "verified_phone_label_enabled": false,
                "freedom_of_speech_not_reach_fetch_enabled": true,
                "standardized_nudges_misinfo": true,
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": true,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": false,
                "responsive_web_graphql_timeline_navigation_enabled": true,
                "responsive_web_enhance_cards_enabled": false
            };
            const media_entities = params.media_id
                ? [{"media_id": params.media_id, "tagged_users": []}]
                : [];
            const variables = {
                "tweet_text": params.content,
                "media": {"media_entities": media_entities, "possibly_sensitive": false},
                "semantic_annotation_ids": [],
                "disallowed_reply_options": null,
                "semantic_annotation_options": {"source": "Htl"}
            };
            const body = JSON.stringify({
                variables: JSON.stringify(variables),
                features: JSON.stringify(features),
                queryId: params.query_id,
            });
            const url = 'https://api.x.com/graphql/' + params.query_id + '/CreateTweet';
            const r = await fetch(url, {
                method: 'POST',
                headers: {
                    'authorization': 'Bearer ' + params.bearer,
                    'x-csrf-token': params.ct0,
                    'content-type': 'application/json',
                    'x-twitter-active-user': 'yes',
                    'x-twitter-auth-type': 'OAuth2Session',
                    'x-twitter-client-language': 'en',
                },
                body: body, credentials: 'include',
            });
            return {status: r.status, body: await r.text()};
        }""", {"content": content, "media_id": media_id, "query_id": query_id, "bearer": bearer, "ct0": ct0})

        logger.info(f"[publish_to_x] CreateTweet status={create_result['status']}")

        if create_result["status"] != 200:
            raise RuntimeError(f"CreateTweet 失败: {create_result['status']} {create_result['body'][:300]}")

        # 解析响应获取 tweet_id (多路径解析，应对 X 响应结构变化)
        new_tweet_id = ""
        new_tweet_url = ""
        try:
            data = _json.loads(create_result["body"])
            logger.info(f"[publish_to_x] 响应体(前500字符): {create_result['body'][:500]}")
        except Exception as e:
            logger.warning(f"[publish_to_x] JSON 解析失败: {e}, body={create_result['body'][:300]}")
            data = {}

        # 检查 GraphQL 错误（X 返回 HTTP 200 但响应体可能包含 errors）
        # 注意：必须在 try-except 之外检查，确保错误能正确传播
        gql_errors = data.get("errors", []) if isinstance(data, dict) else []
        if gql_errors:
            error_msgs = [e.get("message", str(e)) for e in gql_errors]
            combined = "; ".join(error_msgs)
            logger.error(f"[publish_to_x] GraphQL 返回错误: {combined}")
            raise RuntimeError(f"X API 拒绝发布: {combined}")

        # 多路径解析 tweet_id
        try:
            # 路径1: data.create_tweet.tweet_results.result.rest_id (标准路径)
            tweet_result = data.get("data", {}).get("create_tweet", {}).get("tweet_results", {})
            tweet = tweet_result.get("result", {}) if isinstance(tweet_result, dict) else {}
            new_tweet_id = tweet.get("rest_id", "") if isinstance(tweet, dict) else ""

            # 路径2: data.create_tweet.tweet_results.result.legacy.id_str
            if not new_tweet_id and isinstance(tweet, dict):
                new_tweet_id = tweet.get("legacy", {}).get("id_str", "")

            # 路径3: data.create_tweet.tweet_results.result.core.user_results.result.rest_id
            # (core 下是用户对象,不能直接取 core.id_str — 那是用户 ID 不是推文 ID)
            if not new_tweet_id and isinstance(tweet, dict):
                core = tweet.get("core", {})
                user_results = core.get("user_results", {}) if isinstance(core, dict) else {}
                user = user_results.get("result", {}) if isinstance(user_results, dict) else {}
                # 注意: 这是用户 ID,不是推文 ID — 仅作为最后手段,正常不会走到这里
                # 留空,不取用户 ID 冒充推文 ID
                pass

            # 路径4: 深度搜索 — 在整个响应中查找第一个 tweet ID (19位数字)
            if not new_tweet_id:
                import re as _re
                id_matches = _re.findall(r'"(?:rest_id|id_str)"\s*:\s*"?(\d{15,25})"?', create_result["body"])
                if id_matches:
                    new_tweet_id = id_matches[0]
                    logger.info(f"[publish_to_x] 通过深度搜索提取 tweet_id={new_tweet_id}")

            if new_tweet_id:
                new_tweet_url = f"https://x.com/i/status/{new_tweet_id}"
                logger.info(f"[publish_to_x] 发布成功! tweet_id={new_tweet_id}")
        except Exception as e:
            logger.warning(f"[publish_to_x] tweet_id 解析失败: {e}")

        # 如果响应中没有 tweet_id，导航到用户主页获取最新推文
        if not new_tweet_id:
            logger.warning("[publish_to_x] 响应中无 tweet_id，CreateTweet 可能失败。检查用户主页找新增推文...")
            try:
                username = os.getenv("X_TWITTER_MY_USERNAME", "GreyCheng90328")
                await page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(8)  # 等待足够长确保新推文已加载

                # 收集所有推文链接，按出现顺序去重
                tweet_links = await page.query_selector_all('article[data-testid="tweet"] a[href*="/status/"]')
                seen_ids = set()
                candidate_ids = []
                for link in tweet_links:
                    href = await link.get_attribute("href")
                    if href and "/status/" in href:
                        tid = href.split("/status/")[1].split("/")[0].split("?")[0]
                        if tid not in seen_ids:
                            seen_ids.add(tid)
                            candidate_ids.append((tid, href))

                # 对比发布前快照，只接受新增的推文 ID（避免抓到旧推文）
                pre_existing_ids = set(pre_tweet_ids) if pre_tweet_ids else set()
                new_candidates = [(tid, href) for tid, href in candidate_ids if tid not in pre_existing_ids]

                if new_candidates:
                    new_tweet_id, href = new_candidates[0]
                    new_tweet_url = f"https://x.com{href}" if href.startswith("/") else href
                    logger.info(f"[publish_to_x] 从主页获取新增 tweet_id={new_tweet_id} (共 {len(candidate_ids)} 条, 新增 {len(new_candidates)} 条)")
                else:
                    logger.error(
                        f"[publish_to_x] 主页无新增推文！共 {len(candidate_ids)} 条全部是旧推文。"
                        f"CreateTweet 实际失败但响应未报错。pre_ids={list(pre_existing_ids)[:5]}"
                    )
                    # 不返回旧推文 ID，明确标记失败
                    raise RuntimeError(
                        "CreateTweet 发布失败: 响应无 tweet_id 且主页无新增推文，可能是 X API 静默拒绝"
                    )
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning(f"[publish_to_x] 检查主页失败: {e}")

        return {
            "success": True,
            "tweet_id": new_tweet_id,
            "tweet_url": new_tweet_url,
            "video_path": video_path,
        }

    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.unlink(video_path)
            except Exception:
                pass
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            if context:
                await context.close()
        except Exception:
            pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        try:
            if p:
                await p.stop()
        except Exception:
            pass


@router.post("/publish-x")
async def publish_to_x(req: PublishToXRequest, request: Request = None):
    """发布视频/文案到 X（Twitter）"""
    
    cookies_str = os.getenv("X_TWITTER_COOKIES", "")
    if not cookies_str:
        raise HTTPException(400, "X_TWITTER_COOKIES 未配置，无法发布")

    if "auth_token" not in cookies_str and "ct0" not in cookies_str:
        raise HTTPException(400, "Cookie 中缺少 auth_token 或 ct0，无法登录")

    max_retries = 3
    last_error = ""
    
    server_base_url = "http://localhost:8000"
    if request:
        server_base_url = f"{request.url.scheme}://{request.url.hostname}"
        if request.url.port and request.url.port not in (80, 443):
            server_base_url += f":{request.url.port}"
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"[publish_to_x] 第 {attempt}/{max_retries} 次尝试发布")
            result = await _do_publish_to_x(cookies_str, req.content, req.video_url, server_base_url)
            
            if result.get("success", False):
                new_tweet_id = result.get("tweet_id", "")
                new_tweet_url = result.get("tweet_url", "")
                
                if req.auto_monitor and new_tweet_id:
                    async with get_session() as session:
                        existing = (await session.execute(
                            select(XTwitterMonitoredPost).where(XTwitterMonitoredPost.post_id == new_tweet_id)
                        )).scalar_one_or_none()

                        if existing:
                            existing.monitoring = 1
                            existing.last_modify_ts = _ts()
                        else:
                            new_post = XTwitterMonitoredPost(
                                post_id=new_tweet_id,
                                post_url=new_tweet_url,
                                post_content=req.content[:500],
                                post_username="",
                                monitoring=1,
                                add_ts=_ts(),
                                last_modify_ts=_ts(),
                            )
                            session.add(new_post)
                        await session.commit()

                return {
                    "success": True,
                    "message": "发布成功",
                    "tweet_id": new_tweet_id,
                    "tweet_url": new_tweet_url,
                    "auto_monitor": req.auto_monitor and bool(new_tweet_id),
                    "attempts": attempt,
                }
            
            last_error = "发布返回失败"
            
        except Exception as e:
            last_error = str(e)
            logger.error(f"[publish_to_x] 第 {attempt}/{max_retries} 次尝试失败: {e}")
            if attempt < max_retries:
                await asyncio.sleep(5)

    # 所有重试都失败 → 发送发布失败预警到 alert_center
    try:
        from api.services.alert.alert_center import emit_publish_failure
        await emit_publish_failure(
            platform="x_twitter",
            account_label="X_TWITTER_COOKIES(env)",
            error_message=last_error,
            content_preview=req.content[:200] if req.content else "",
            post_id=req.post_id if hasattr(req, "post_id") else "",
        )
    except Exception as ae:
        logger.warning(f"[publish_to_x] 发送发布失败预警异常(非致命): {ae}")

    raise HTTPException(500, f"发布失败，已重试 {max_retries} 次: {last_error}")


# ==================== 文件上传 ====================

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    """上传视频文件"""
    try:
        file_ext = os.path.splitext(file.filename)[1] if file.filename else ".mp4"
        if not file_ext.lower() in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            raise HTTPException(400, "不支持的文件格式，仅支持 MP4/MOV/AVI/MKV/WEBM")

        file_hash = hashlib.md5(file.filename.encode() + str(time.time()).encode()).hexdigest()[:8]
        filename = f"{file_hash}_{file.filename}{file_ext}" if not file.filename.endswith(file_ext) else f"{file_hash}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, filename)

        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        file_url = f"/api/x-workbench/download-video/{filename}"
        
        logger.info(f"[upload_video] Uploaded video: {filename}, size: {len(contents)} bytes")
        
        return {
            "success": True,
            "filename": filename,
            "file_path": file_path,
            "file_url": file_url,
            "size": len(contents),
        }
    except Exception as e:
        logger.error(f"[upload_video] Failed: {e}")
        raise HTTPException(500, f"上传失败: {e}")


@router.get("/download-video/{filename}")
async def download_video(filename: str):
    """下载已上传的视频文件"""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "文件不存在")
    
    return FileResponse(file_path, media_type="video/mp4", filename=filename)
