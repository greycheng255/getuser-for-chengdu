# -*- coding: utf-8 -*-
"""
X Twitter 工作台 - X 热点采集控制器

功能：
1. 触发 X Twitter 爬虫（异步任务）抓取最新热点
2. 抓取结果保存到 XTwitterPost 表
3. 提供关键词配置（临时覆盖 KEYWORDS）
4. 抓取完成后，工作台的 trending 接口立即可读到新数据
"""
import asyncio
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# 复用 x_twitter 路由的调度器
from .x_twitter import (
    _x_twitter_scheduler_task,
    _x_twitter_scheduler_running,
)


router = APIRouter(prefix="/x-workbench/crawl", tags=["x-twitter-workbench-crawl"])


# 全局状态：单次采集任务
_one_shot_task: Optional[asyncio.Task] = None
_one_shot_status: Dict[str, Any] = {
    "running": False,
    "started_at": 0,
    "finished_at": 0,
    "keywords": "",
    "error": "",
    "crawled_count": 0,
    "stage": "idle",  # idle/starting/crawling/saving/done/failed
}


class CrawlOnceRequest(BaseModel):
    keywords: str = Field("", description="自定义关键词，逗号分隔。为空则用配置中的 KEYWORDS")
    max_posts: int = Field(20, ge=1, le=100, description="每个关键词最多抓取条数")


@router.post("/once")
async def crawl_once(req: CrawlOnceRequest):
    """触发一次 X Twitter 采集（异步任务，立即返回）
    
    关键词为空时，自动从热点聚合获取最新热点数据，不再使用 config.KEYWORDS
    """
    global _one_shot_task

    if _one_shot_status["running"]:
        return {"success": False, "message": "已有采集任务在运行中", "status": _one_shot_status}

    keywords = req.keywords.strip()
    
    _one_shot_task = asyncio.create_task(_do_crawl_once(keywords, req.max_posts))
    return {
        "success": True,
        "message": "采集任务已启动",
        "keywords": keywords if keywords else "热点聚合自动获取",
        "max_posts": req.max_posts,
    }


async def _do_crawl_once(keywords: str, max_posts: int):
    """实际执行单次采集"""
    global _one_shot_status
    import time
    _one_shot_status.update({
        "running": True,
        "started_at": int(time.time()),
        "finished_at": 0,
        "keywords": keywords if keywords else "热点聚合自动获取",
        "error": "",
        "crawled_count": 0,
        "stage": "starting",
    })

    try:
        _one_shot_status["stage"] = "crawling"
        print(f"[x-workbench-crawl] 开始采集，关键词: {_one_shot_status['keywords']}")

        if keywords:
            from api.services.x_trending_fetcher import _crawl_with_playwright_direct, _save_trending_data

            keywords_list = [k.strip() for k in keywords.split(",") if k.strip()]
            
            all_posts = []
            for idx, kw in enumerate(keywords_list, 1):
                _one_shot_status["stage"] = f"crawling {idx}/{len(keywords_list)}"
                print(f"[x-workbench-crawl] 搜索关键词 {idx}/{len(keywords_list)}: {kw}")
                
                posts = await _crawl_with_playwright_direct(kw)
                all_posts.extend(posts)
                print(f"[x-workbench-crawl] 关键词 {kw} 获取到 {len(posts)} 条帖子")

            if all_posts:
                _one_shot_status["stage"] = "saving"
                print(f"[x-workbench-crawl] 保存 {len(all_posts)} 条帖子...")
                await _save_trending_data(all_posts)

            _one_shot_status["stage"] = "done"
            _one_shot_status["crawled_count"] = len(all_posts)
            print(f"[x-workbench-crawl] 采集完成，共获取 {len(all_posts)} 条帖子")
        else:
            from api.services.x_trending_fetcher import _save_trending_data
            from database.db_session import get_session
            from database.models import XTwitterTrendingPost, XTwitterPost
            from sqlalchemy import select, desc
            
            _one_shot_status["stage"] = "crawling (热点聚合)"
            print("[x-workbench-crawl] 从数据库读取热点数据...")
            
            all_posts = []
            async with get_session() as session:
                stmt = select(XTwitterTrendingPost).order_by(desc(XTwitterTrendingPost.crawl_ts)).limit(max_posts * 5)
                result = await session.execute(stmt)
                trending_posts = result.scalars().all()
                
                if trending_posts:
                    all_posts = [
                        {
                            "post_id": p.post_id,
                            "post_url": p.post_url,
                            "username": p.username,
                            "nickname": p.nickname,
                            "content": p.content,
                            "video_url": p.video_url,
                            "image_url": p.image_url,
                            "likes_count": p.likes_count,
                            "retweets_count": p.retweets_count,
                            "replies_count": p.replies_count,
                            "views_count": p.views_count,
                            "created_at": p.created_at,
                            "topic": p.topic,
                        }
                        for p in trending_posts
                    ]
                    print(f"[x-workbench-crawl] 从 XTwitterTrendingPost 表获取 {len(all_posts)} 条数据")
            
            if not all_posts:
                async with get_session() as session:
                    stmt = select(XTwitterPost).order_by(desc(XTwitterPost.add_ts)).limit(max_posts * 5)
                    result = await session.execute(stmt)
                    posts = result.scalars().all()
                    all_posts = [
                        {
                            "post_id": p.post_id,
                            "post_url": p.post_url,
                            "username": p.username,
                            "nickname": p.nickname,
                            "content": p.content,
                            "video_url": p.video_url,
                            "image_url": p.image_urls[0] if p.image_urls else "",
                            "likes_count": p.likes_count,
                            "retweets_count": p.retweets_count,
                            "replies_count": p.replies_count,
                            "views_count": p.views_count,
                            "created_at": p.created_at,
                            "topic": p.source_keyword,
                        }
                        for p in posts
                    ]
                    print(f"[x-workbench-crawl] 从 XTwitterPost 表获取 {len(all_posts)} 条数据")

            if all_posts:
                _one_shot_status["stage"] = "done"
                _one_shot_status["crawled_count"] = len(all_posts)
                print(f"[x-workbench-crawl] 采集完成，共获取 {len(all_posts)} 条帖子")
            else:
                _one_shot_status["stage"] = "done"
                _one_shot_status["crawled_count"] = 0
                print("[x-workbench-crawl] 采集完成，未获取到数据")

    except Exception as e:
        _one_shot_status["stage"] = "failed"
        _one_shot_status["error"] = str(e)
        print(f"[x-workbench-crawl] 采集失败: {e}")
    finally:
        _one_shot_status["running"] = False
        _one_shot_status["finished_at"] = int(time.time())


@router.get("/status")
async def crawl_status():
    """获取当前/上次单次采集任务状态"""
    return _one_shot_status


@router.post("/cancel")
async def cancel_crawl():
    """取消正在运行的采集任务"""
    global _one_shot_task
    if _one_shot_task and not _one_shot_task.done():
        _one_shot_task.cancel()
        try:
            await _one_shot_task
        except asyncio.CancelledError:
            pass
    _one_shot_task = None
    _one_shot_status["running"] = False
    _one_shot_status["stage"] = "cancelled"
    return {"success": True, "message": "已取消"}


@router.get("/scheduled/status")
async def scheduled_status():
    """获取定时爬取任务状态（复用 x_twitter 路由的调度器）"""
    return {
        "running": _x_twitter_scheduler_running,
        "interval_minutes": _get_x_crawl_interval(),
    }


@router.post("/scheduled/start")
async def scheduled_start():
    """启动定时爬取任务（委托给 x_twitter 路由）"""
    # 直接调用 x_twitter 路由的实现
    from .x_twitter import start_scheduled_crawl
    return await start_scheduled_crawl()


@router.post("/scheduled/stop")
async def scheduled_stop():
    """停止定时爬取任务"""
    from .x_twitter import stop_scheduled_crawl
    return await stop_scheduled_crawl()


def _get_x_crawl_interval() -> int:
    try:
        import config
        return getattr(config, "X_TWITTER_CRAWL_INTERVAL_MINUTES", 60)
    except Exception:
        return 60


@router.get("/keywords")
async def get_keywords():
    """获取当前配置的 X 采集关键词"""
    try:
        import config
        return {
            "keywords": getattr(config, "KEYWORDS", ""),
            "max_posts": getattr(config, "X_TWITTER_MAX_POSTS", 20),
            "interval_minutes": _get_x_crawl_interval(),
        }
    except Exception as e:
        return {"keywords": "", "max_posts": 20, "interval_minutes": 60, "error": str(e)}


class KeywordsRequest(BaseModel):
    keywords: str = Field(..., description="关键词，英文逗号分隔")


@router.put("/keywords")
async def update_keywords(req: KeywordsRequest):
    """临时更新 X 采集关键词（仅当前进程有效，重启后失效）"""
    try:
        import config
        config.KEYWORDS = req.keywords
        return {"success": True, "keywords": config.KEYWORDS, "message": "关键词已更新（仅本次进程有效）"}
    except Exception as e:
        raise HTTPException(500, f"更新失败: {e}")
