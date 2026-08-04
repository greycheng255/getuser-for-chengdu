# -*- coding: utf-8 -*-
"""
X Twitter 工作台 - 全自动模式服务

将"爬热点 → AI 生成评论 → 发送评论 → 监控回复 → AI 自动回复"
串成一个端到端的自动化流程,可在 Web UI 上一键启停。

设计要点:
1. 后台 asyncio task 持续运行,不阻塞 FastAPI 主线程
2. 单实例运行(重复 start 不会启动多个 task)
3. 状态查询:running / started_at / last_cycle_at / stats
4. 单次循环流程:
   a. 调用 x_trending_fetcher 获取热点(已有 30 分钟定时,这里复用其结果)
   b. 从 DB 拉取最近的未评论热点帖子
   c. 对每条帖子:AI 生成评论 → x_comment_sender.send_comment → 持久化
   d. 启动 comment_reply_monitor(已启动则跳过)
   e. 等待下一轮(默认 1 小时,可配置 X_WORKBENCH_AUTO_MODE_INTERVAL)
5. 单条失败不影响其他;每轮结束记录 stats
6. 与 core.py 的 auto_comment_flow 是平行实现,但更适合 Web 场景(无需 Playwright 完整登录)
"""
import asyncio
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc, and_

from database.db_session import get_session
from database.models import XTwitterPost, XTwitterSentComment


logger = logging.getLogger("auto_mode_service")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# 全局状态
_task: Optional[asyncio.Task] = None
_state: Dict[str, Any] = {
    "running": False,
    "started_at": 0,
    "last_cycle_at": 0,
    "last_cycle_summary": "",
    "total_cycles": 0,
    "total_comments_sent": 0,
    "total_comments_failed": 0,
    "current_phase": "idle",  # idle / crawling / commenting / monitoring
    "error": "",
}

# 配置(可由环境变量覆盖)
CYCLE_INTERVAL_SECONDS = int(os.getenv("X_WORKBENCH_AUTO_MODE_INTERVAL", "3600"))  # 默认 1 小时
MAX_POSTS_PER_CYCLE = int(os.getenv("X_WORKBENCH_AUTO_MODE_MAX_POSTS", "5"))  # 每轮最多处理 5 条
COMMENT_DELAY_MIN = int(os.getenv("X_WORKBENCH_AUTO_MODE_DELAY_MIN", "30"))  # 单条评论间隔最小秒数
COMMENT_DELAY_MAX = int(os.getenv("X_WORKBENCH_AUTO_MODE_DELAY_MAX", "60"))  # 单条评论间隔最大秒数
RECENT_COMMENT_HOURS = 24  # 跳过最近 24 小时内已评论过的帖子(避免重复评论)


def is_running() -> bool:
    """检查全自动模式是否在运行"""
    return _task is not None and not _task.done()


def get_status() -> Dict[str, Any]:
    """获取全自动模式状态"""
    return {
        **_state,
        "running": is_running(),
        "cycle_interval_seconds": CYCLE_INTERVAL_SECONDS,
        "max_posts_per_cycle": MAX_POSTS_PER_CYCLE,
    }


async def start_auto_mode() -> bool:
    """启动全自动模式(幂等)

    Returns:
        bool: True 启动成功/已在运行;False 启动失败
    """
    global _task
    if is_running():
        return True
    try:
        _state["running"] = True
        _state["started_at"] = int(time.time())
        _state["error"] = ""
        _state["current_phase"] = "starting"
        _task = asyncio.create_task(_run_loop())
        logger.info(f"全自动模式已启动,间隔 {CYCLE_INTERVAL_SECONDS}s,每轮最多 {MAX_POSTS_PER_CYCLE} 条")
        return True
    except Exception as e:
        _state["running"] = False
        _state["error"] = f"启动失败: {e}"
        logger.error(f"启动全自动模式失败: {e}")
        return False


async def stop_auto_mode() -> bool:
    """停止全自动模式"""
    global _task
    if not is_running():
        _state["running"] = False
        return True
    try:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    except Exception as e:
        logger.error(f"停止全自动模式异常: {e}")
    finally:
        _task = None
        _state["running"] = False
        _state["current_phase"] = "idle"
        logger.info("全自动模式已停止")
    return True


async def _run_loop():
    """全自动模式主循环"""
    logger.info("全自动模式主循环启动")
    # 启动时先触发一次,然后按间隔循环
    while True:
        try:
            await _run_one_cycle()
        except asyncio.CancelledError:
            logger.info("全自动模式收到取消信号,退出")
            raise
        except Exception as e:
            logger.error(f"全自动模式循环异常: {e}")
            _state["error"] = str(e)
        # 等待下一轮
        try:
            await asyncio.sleep(CYCLE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise


async def _run_one_cycle():
    """执行一轮全自动流程:爬热点 → 选评 → 发评论 → 启动监控"""
    _state["current_phase"] = "crawling"
    _state["total_cycles"] += 1
    cycle_start = int(time.time())
    logger.info(f"===== 开始第 {_state['total_cycles']} 轮全自动流程 =====")

    # ===== 1. 触发一次热点采集(异步,不等待完成) =====
    try:
        from api.services.x_trending_fetcher import crawl_trending
        asyncio.create_task(crawl_trending())
        logger.info("已触发热点采集(异步)")
    except Exception as e:
        logger.warning(f"触发热点采集失败(继续用 DB 已有数据): {e}")

    # ===== 2. 从 DB 拉取最近的未评论热点帖子 =====
    _state["current_phase"] = "selecting"
    posts = await _select_uncommented_posts(MAX_POSTS_PER_CYCLE)
    if not posts:
        _state["last_cycle_summary"] = "无可评论的帖子(所有近期帖子已评论或无热点数据)"
        _state["last_cycle_at"] = int(time.time())
        _state["current_phase"] = "monitoring"
        await _ensure_monitor_running()
        logger.warning("本轮无可评论帖子")
        return

    logger.info(f"本轮选中 {len(posts)} 条帖子准备评论")

    # ===== 3. 对每条帖子:AI 生成评论 + 真实发送 =====
    _state["current_phase"] = "commenting"
    sent_count = 0
    failed_count = 0
    for idx, post in enumerate(posts, 1):
        try:
            ok = await _comment_one_post(post)
            if ok:
                sent_count += 1
                _state["total_comments_sent"] += 1
            else:
                failed_count += 1
                _state["total_comments_failed"] += 1
        except Exception as e:
            logger.error(f"评论帖子 {post.get('post_id', '')} 失败: {e}")
            failed_count += 1
            _state["total_comments_failed"] += 1

        # 单条间隔(最后一条不等)
        if idx < len(posts):
            delay = random.uniform(COMMENT_DELAY_MIN, COMMENT_DELAY_MAX)
            logger.info(f"等待 {delay:.1f}s 后评论下一条...")
            await asyncio.sleep(delay)

    # ===== 4. 确保 comment_reply_monitor 在运行 =====
    _state["current_phase"] = "monitoring"
    await _ensure_monitor_running()

    cycle_end = int(time.time())
    _state["last_cycle_at"] = cycle_end
    _state["last_cycle_summary"] = f"本轮发送 {sent_count}/{len(posts)} 条评论,失败 {failed_count} 条,耗时 {cycle_end - cycle_start}s"
    _state["current_phase"] = "waiting"
    logger.info(f"===== 第 {_state['total_cycles']} 轮完成: {_state['last_cycle_summary']} =====")


async def _select_uncommented_posts(limit: int) -> List[Dict[str, Any]]:
    """从 DB 选取最近未评论过的热点帖子

    跳过:最近 RECENT_COMMENT_HOURS 小时内已成功评论过的帖子(避免重复评论)
    优先:有视频的帖子(P2-1 视频帖子走特殊流程)
    """
    cutoff_ts = int(time.time()) - RECENT_COMMENT_HOURS * 3600
    async with get_session() as session:
        # 查询最近 24h 内已成功评论过的 post_id
        recent_stmt = (
            select(XTwitterSentComment.post_id)
            .where(
                and_(
                    XTwitterSentComment.sent_status == "success",
                    XTwitterSentComment.sent_at >= cutoff_ts,
                )
            )
            .distinct()
        )
        recent_result = await session.execute(recent_stmt)
        recent_post_ids = {row[0] for row in recent_result.fetchall()}

        # 拉取最近的热点帖子
        stmt = (
            select(XTwitterPost)
            .order_by(desc(XTwitterPost.add_ts))
            .limit(limit * 5)  # 多取一些用于过滤
        )
        result = await session.execute(stmt)
        all_posts = result.scalars().all()

    # 过滤:跳过已评论过的 + 跳过无 post_url 的
    candidates = []
    for p in all_posts:
        if not p.post_url:
            continue
        if p.post_id in recent_post_ids:
            continue
        candidates.append({
            "post_id": p.post_id,
            "post_url": p.post_url,
            "content": p.content or "",
            "username": p.username or "",
            "video_url": p.video_url or "",
            "image_urls": p.image_urls or "",
            "likes_count": p.likes_count or "0",
            "retweets_count": p.retweets_count or "0",
            "replies_count": p.replies_count or "0",
            "views_count": p.views_count or "0",
            "source_keyword": p.source_keyword or "",
        })
        if len(candidates) >= limit:
            break

    # 优先视频帖子(P2-1):有 video_url 的排前面
    candidates.sort(key=lambda x: (0 if x.get("video_url") else 1))
    return candidates[:limit]


async def _comment_one_post(post: Dict[str, Any]) -> bool:
    """对单条帖子生成 AI 评论并发送

    P2-1: 视频帖子优先调用 generate_video_breakdown 获取分镜,
    再用 breakdown 作为上下文调用 generate_comments 生成更针对性的评论。
    """
    from api.services.ai_agent_client import generate_comments, generate_video_breakdown
    from api.services.x_comment_sender import send_comment

    post_id = post.get("post_id", "")
    post_url = post.get("post_url", "")
    if not post_url:
        return False

    # ===== 1. 生成评论内容 =====
    comment_content = ""
    breakdown = ""
    try:
        # P2-1: 视频帖子特殊流程
        if post.get("video_url"):
            try:
                breakdown = await generate_video_breakdown(post)
                logger.info(f"视频帖子 {post_id} 已生成分镜({len(breakdown)} 字符),用于增强评论上下文")
            except Exception as e:
                logger.warning(f"生成视频分镜失败,继续无分镜生成评论: {e}")
                breakdown = ""

        # AI 生成评论(传入 breakdown 作为上下文)
        comments = await generate_comments(post, breakdown=breakdown, count=1)
        if comments:
            comment_content = comments[0]
    except Exception as e:
        logger.error(f"AI 生成评论失败 post={post_id}: {e}")

    if not comment_content:
        logger.warning(f"AI 生成评论为空,跳过 post={post_id}")
        return False

    # ===== 2. 真实发送评论 =====
    try:
        result = await send_comment(post_url=post_url, content=comment_content, real_send=True)
        ok = bool(result.get("success"))
        mode = result.get("mode", "draft")
        logger.info(f"评论 post={post_id} ok={ok} mode={mode} err={result.get('error', '')[:80]}")

        # ===== 3. 持久化到 XTwitterSentComment(无论成功/失败,与工作台一致) =====
        now = int(time.time())
        sent_status = "success" if ok else ("draft" if mode == "draft" else "failed")
        async with get_session() as session:
            sc = XTwitterSentComment(
                post_id=post_id,
                post_url=post_url,
                post_content=(post.get("content") or "")[:500],
                post_username=post.get("username", ""),
                video_url=post.get("video_url", ""),
                comment_content=comment_content,
                comment_url=result.get("comment_url", ""),
                sent_status=sent_status,
                sent_error=result.get("error", ""),
                sent_at=now,
                source="auto_mode",
                monitoring=1 if sent_status == "success" else 0,
                last_check_ts=0,
                reply_count=0,
                auto_replied_count=0,
                add_ts=now,
                last_modify_ts=now,
            )
            session.add(sc)
            await session.commit()
        return ok
    except Exception as e:
        logger.error(f"发送评论异常 post={post_id}: {e}")
        return False


async def _ensure_monitor_running():
    """确保 comment_reply_monitor 在运行(已运行则跳过)"""
    try:
        from api.services.comment_reply_monitor import is_monitor_running, start_monitor
        if is_monitor_running():
            return
        await start_monitor()
        logger.info("已启动 comment_reply_monitor")
    except Exception as e:
        logger.error(f"启动 comment_reply_monitor 失败: {e}")
