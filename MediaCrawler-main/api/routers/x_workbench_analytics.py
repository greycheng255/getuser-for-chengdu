# -*- coding: utf-8 -*-
"""
X Twitter 工作台 - 评论效果分析路由

提供评论效果的多维度分析:
- GET /x-workbench/analytics/summary    总体概览(成功率/回复率/AI覆盖率/平均响应时间)
- GET /x-workbench/analytics/comments   单条评论效果排名(按回复数/互动排序)
- GET /x-workbench/analytics/timeline   时间序列(每日发送量/回复量,用于折线图)
- GET /x-workbench/analytics/topics     按话题分组的效果统计

所有统计基于已发评论表(x_twitter_sent_comment)和回复表(x_twitter_reply)。
"""
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, desc, case, cast, Date, BigInteger

from database.db_session import get_session
from database.models import XTwitterSentComment, XTwitterReply
from api.services.auth import get_current_user
from api.utils.rate_limit import rate_limit
from api.utils.ttl_cache import ttl_cache


router = APIRouter(
    prefix="/x-workbench/analytics",
    tags=["x-twitter-workbench"],
    dependencies=[
        Depends(get_current_user),
        Depends(rate_limit()),
    ],
)

logger = logging.getLogger("x_workbench_analytics")


@router.get("/summary")
async def analytics_summary(
    start_ts: int = Query(0, description="开始时间戳(0=不限)"),
    end_ts: int = Query(0, description="结束时间戳(0=不限)"),
):
    """总体效果概览

    返回:
    - 发送统计:总数/成功/失败/草稿
    - 回复统计:收到回复数/AI已回复数/待处理数
    - 比率:回复率/AI覆盖率/发送成功率
    - 时间:平均响应时间(发送→首次回复)、监控中评论数
    """
    return await _summary_cached(start_ts, end_ts)


@ttl_cache(ttl_seconds=120)
async def _summary_cached(start_ts: int, end_ts: int):
    """概览统计缓存层(2 分钟 TTL,避免频繁聚合查询)"""
    conditions = []
    if start_ts > 0:
        conditions.append(XTwitterSentComment.sent_at >= start_ts)
    if end_ts > 0:
        conditions.append(XTwitterSentComment.sent_at <= end_ts)

    async with get_session() as session:
        # 1. 发送统计(按状态分组)
        status_stmt = (
            select(
                XTwitterSentComment.sent_status,
                func.count(XTwitterSentComment.id),
            )
            .group_by(XTwitterSentComment.sent_status)
        )
        if conditions:
            status_stmt = status_stmt.where(and_(*conditions))
        status_result = await session.execute(status_stmt)
        status_counts = {row[0]: row[1] for row in status_result.all()}

        total_sent = sum(status_counts.values())
        success_count = status_counts.get("success", 0)
        failed_count = status_counts.get("failed", 0)
        draft_count = status_counts.get("draft", 0)

        # 2. 回复统计
        reply_total_stmt = select(func.count(XTwitterReply.id))
        if conditions:
            reply_total_stmt = reply_total_stmt.where(
                XTwitterReply.sent_comment_id.in_(
                    select(XTwitterSentComment.id).where(and_(*conditions))
                )
            )
        total_replies = (await session.execute(reply_total_stmt)).scalar() or 0

        # AI 回复状态分布
        ai_status_stmt = (
            select(XTwitterReply.auto_reply_status, func.count(XTwitterReply.id))
            .group_by(XTwitterReply.auto_reply_status)
        )
        if conditions:
            ai_status_stmt = ai_status_stmt.where(
                XTwitterReply.sent_comment_id.in_(
                    select(XTwitterSentComment.id).where(and_(*conditions))
                )
            )
        ai_status_result = await session.execute(ai_status_stmt)
        ai_status_counts = {row[0]: row[1] for row in ai_status_result.all()}

        ai_replied = ai_status_counts.get("sent", 0)
        ai_pending = ai_status_counts.get("pending", 0)
        ai_failed = ai_status_counts.get("failed", 0)

        # 3. 监控中的评论数
        monitoring_stmt = select(func.count(XTwitterSentComment.id)).where(
            XTwitterSentComment.monitoring == 1
        )
        if conditions:
            monitoring_stmt = monitoring_stmt.where(and_(*conditions))
        monitoring_count = (await session.execute(monitoring_stmt)).scalar() or 0

        # 4. 平均响应时间(发送 → 首次回复)
        # 用最早的 reply.add_ts - sent_comment.sent_at
        avg_response_stmt = select(
            func.avg(XTwitterReply.add_ts - XTwitterSentComment.sent_at)
        ).select_from(XTwitterReply).join(
            XTwitterSentComment,
            XTwitterReply.sent_comment_id == XTwitterSentComment.id,
        ).where(XTwitterReply.add_ts > 0)
        if conditions:
            avg_response_stmt = avg_response_stmt.where(
                XTwitterSentComment.sent_at >= start_ts if start_ts > 0 else True,
                XTwitterSentComment.sent_at <= end_ts if end_ts > 0 else True,
            )
        avg_response_seconds = (await session.execute(avg_response_stmt)).scalar() or 0

    # 计算比率
    send_success_rate = round(success_count / total_sent * 100, 1) if total_sent > 0 else 0.0
    reply_rate = round(total_replies / success_count * 100, 1) if success_count > 0 else 0.0
    ai_coverage = round(ai_replied / total_replies * 100, 1) if total_replies > 0 else 0.0
    avg_response_hours = round(float(avg_response_seconds) / 3600, 1) if avg_response_seconds else 0.0

    return {
        "period": {"start_ts": start_ts, "end_ts": end_ts},
        "send_stats": {
            "total": total_sent,
            "success": success_count,
            "failed": failed_count,
            "draft": draft_count,
            "success_rate": send_success_rate,
        },
        "reply_stats": {
            "total_replies": total_replies,
            "ai_replied": ai_replied,
            "ai_pending": ai_pending,
            "ai_failed": ai_failed,
            "reply_rate": reply_rate,
            "ai_coverage": ai_coverage,
        },
        "monitoring": {
            "active_count": monitoring_count,
        },
        "response_time": {
            "avg_seconds": int(avg_response_seconds),
            "avg_hours": avg_response_hours,
            "desc": f"平均 {avg_response_hours} 小时收到首条回复" if avg_response_hours > 0 else "暂无回复数据",
        },
    }


@router.get("/comments")
async def analytics_comments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("reply_count", description="排序字段: reply_count/auto_replied_count/sent_at"),
    start_ts: int = Query(0),
    end_ts: int = Query(0),
):
    """单条评论效果排名

    返回每条评论的:
    - 基础信息(post_id, content, sent_at, status)
    - 互动数据(reply_count, auto_replied_count)
    - 互动评分(综合回复数和AI回复数)
    - 监控状态
    """
    sort_field_map = {
        "reply_count": XTwitterSentComment.reply_count,
        "auto_replied_count": XTwitterSentComment.auto_replied_count,
        "sent_at": XTwitterSentComment.sent_at,
    }
    sort_field = sort_field_map.get(sort_by, XTwitterSentComment.reply_count)

    conditions = [XTwitterSentComment.sent_status == "success"]
    if start_ts > 0:
        conditions.append(XTwitterSentComment.sent_at >= start_ts)
    if end_ts > 0:
        conditions.append(XTwitterSentComment.sent_at <= end_ts)

    async with get_session() as session:
        # 总数
        count_stmt = select(func.count(XTwitterSentComment.id)).where(and_(*conditions))
        total = (await session.execute(count_stmt)).scalar() or 0

        # 列表(按指定字段倒序)
        stmt = (
            select(XTwitterSentComment)
            .where(and_(*conditions))
            .order_by(desc(sort_field), desc(XTwitterSentComment.id))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        comments = result.scalars().all()

    now = int(time.time())
    items = []
    for c in comments:
        # 互动评分 = 回复数 * 2 + AI已回复数 * 1 + (监控中 +1)
        score = (c.reply_count or 0) * 2 + (c.auto_replied_count or 0) * 1
        if c.monitoring == 1:
            score += 1
        items.append({
            "id": c.id,
            "post_id": c.post_id,
            "post_username": c.post_username,
            "post_content": (c.post_content or "")[:100],
            "comment_content": (c.comment_content or "")[:100],
            "comment_url": c.comment_url or "",
            "sent_at": c.sent_at,
            "sent_status": c.sent_status,
            "reply_count": c.reply_count or 0,
            "auto_replied_count": c.auto_replied_count or 0,
            "monitoring": c.monitoring,
            "engagement_score": score,
            "hours_since_sent": round((now - c.sent_at) / 3600, 1) if c.sent_at else 0,
            "reply_rate": round((c.reply_count or 0) * 100 / max(1, (c.auto_replied_count or 0) + 1), 1),
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "sort_by": sort_by,
        "items": items,
    }


@router.get("/timeline")
async def analytics_timeline(
    days: int = Query(30, ge=1, le=90, description="最近 N 天"),
):
    """时间序列数据(每日发送量/回复量,用于折线图)

    返回最近 N 天的数据:
    - dates: 日期列表 ["2026-07-01", ...]
    - sent_counts: 每日发送评论数
    - reply_counts: 每日收到回复数
    - ai_reply_counts: 每日 AI 自动回复数
    """
    return await _timeline_cached(days)


@ttl_cache(ttl_seconds=300)
async def _timeline_cached(days: int):
    """时间序列缓存层(5 分钟 TTL)"""
    now = int(time.time())
    start_ts = now - days * 24 * 3600

    async with get_session() as session:
        # 按日期分组统计发送量
        # 注:不同 DB 的日期函数不同,这里用 Python 端聚合(数据量不大时性能可接受)
        sent_stmt = (
            select(XTwitterSentComment.sent_at, XTwitterSentComment.sent_status)
            .where(XTwitterSentComment.sent_at >= start_ts)
        )
        sent_result = await session.execute(sent_stmt)
        sent_rows = sent_result.all()

        reply_stmt = (
            select(XTwitterReply.add_ts, XTwitterReply.auto_reply_status)
            .where(XTwitterReply.add_ts >= start_ts)
        )
        reply_result = await session.execute(reply_stmt)
        reply_rows = reply_result.all()

    # Python 端按日期聚合
    from datetime import datetime, timedelta
    date_map: Dict[str, Dict[str, int]] = {}
    for i in range(days):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        date_map[d] = {"sent": 0, "success": 0, "reply": 0, "ai_reply": 0}

    for row in sent_rows:
        ts = row[0] or 0
        status = row[1] or ""
        if ts == 0:
            continue
        d = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        if d in date_map:
            date_map[d]["sent"] += 1
            if status == "success":
                date_map[d]["success"] += 1

    for row in reply_rows:
        ts = row[0] or 0
        ai_status = row[1] or ""
        if ts == 0:
            continue
        d = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        if d in date_map:
            date_map[d]["reply"] += 1
            if ai_status == "sent":
                date_map[d]["ai_reply"] += 1

    # 按日期正序排列
    sorted_dates = sorted(date_map.keys())
    return {
        "days": days,
        "dates": sorted_dates,
        "sent_counts": [date_map[d]["sent"] for d in sorted_dates],
        "success_counts": [date_map[d]["success"] for d in sorted_dates],
        "reply_counts": [date_map[d]["reply"] for d in sorted_dates],
        "ai_reply_counts": [date_map[d]["ai_reply"] for d in sorted_dates],
    }


@router.get("/topics")
@ttl_cache(ttl_seconds=300)
async def analytics_topics(
    start_ts: int = Query(0),
    end_ts: int = Query(0),
):
    """按话题(source_keyword)分组的效果统计

    返回每个话题的:
    - 评论数、成功数、回复数、AI回复数
    - 回复率、AI覆盖率
    """
    conditions = []
    if start_ts > 0:
        conditions.append(XTwitterSentComment.sent_at >= start_ts)
    if end_ts > 0:
        conditions.append(XTwitterSentComment.sent_at <= end_ts)

    async with get_session() as session:
        stmt = (
            select(
                XTwitterSentComment.post_username,
                func.count(XTwitterSentComment.id).label("total"),
                func.sum(case(
                    (XTwitterSentComment.sent_status == "success", 1),
                    else_=0,
                )).label("success_count"),
                func.sum(XTwitterSentComment.reply_count).label("reply_count"),
                func.sum(XTwitterSentComment.auto_replied_count).label("ai_replied"),
            )
            .group_by(XTwitterSentComment.post_username)
            .order_by(desc(func.sum(XTwitterSentComment.reply_count)))
        )
        if conditions:
            stmt = stmt.where(and_(*conditions))
        result = await session.execute(stmt)
        rows = result.all()

    items = []
    for row in rows:
        topic = row[0] or "(未知)"
        total = row[1] or 0
        success = row[2] or 0
        replies = row[3] or 0
        ai_replied = row[4] or 0
        items.append({
            "topic": topic,
            "comment_count": total,
            "success_count": success,
            "reply_count": replies,
            "ai_replied_count": ai_replied,
            "reply_rate": round(replies / success * 100, 1) if success > 0 else 0.0,
            "ai_coverage": round(ai_replied / replies * 100, 1) if replies > 0 else 0.0,
        })

    return {"total_topics": len(items), "items": items}
