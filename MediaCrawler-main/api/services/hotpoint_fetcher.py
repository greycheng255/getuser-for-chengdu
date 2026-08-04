# -*- coding: utf-8 -*-
"""
热点内容采集服务

从国内外主流社交/资讯平台采集热门内容，统一格式后供 API 路由使用。
支持的平台:
  国内: 抖音 / 小红书 / 微博 / 知乎 / 哔哩哔哩 / 百度 / 头条 (region="china")
  国外: X.com (复用已采集的 XTwitterPost) / Hacker News / Reddit / GitHub Trending /
        YouTube (Data API v3 + Google News RSS) /
        TikTok / Instagram / Facebook (region="global"，Google News RSS 聚合兜底)

数据格式 (HotItem):
  {
    "rank": int,
    "title": str,
    "url": str,
    "hot": str,            # 热度数值/描述
    "author": str,         # 作者/来源
    "published_at": int,   # 发布时间戳(秒)，可选
    "region": str,         # 区域标识：china / global / 具体国家代码
    "extra": dict          # 平台特定附加信息
  }
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

import config


def _get_engine():
    """获取异步数据库引擎（公共方法，消除重复导入）"""
    from database.db_session import get_async_engine
    return get_async_engine(config.SAVE_DATA_OPTION)

# ------------------------------------------------------------------------------
# 统一数据结构 & 平台元信息
# ------------------------------------------------------------------------------

PLATFORMS: Dict[str, Dict[str, Any]] = {
    # ===== 国内 =====
    "douyin":      {"name": "抖音", "region": "china", "color": "#000000", "home": "https://www.douyin.com"},
    "xiaohongshu": {"name": "小红书", "region": "china", "color": "#FF2442", "home": "https://www.xiaohongshu.com"},
    "weibo":       {"name": "微博", "region": "china", "color": "#E6162D", "home": "https://weibo.com"},
    "zhihu":       {"name": "知乎", "region": "china", "color": "#0084FF", "home": "https://www.zhihu.com"},
    "bilibili":    {"name": "哔哩哔哩", "region": "china", "color": "#00A1D6", "home": "https://www.bilibili.com"},
    "kuaishou":    {"name": "快手", "region": "china", "color": "#FF4906", "home": "https://www.kuaishou.com"},
    "baidu":       {"name": "百度热搜", "region": "china", "color": "#2932E1", "home": "https://www.baidu.com"},
    "toutiao":     {"name": "今日头条", "region": "china", "color": "#F04142", "home": "https://www.toutiao.com"},
    # ===== 国外 =====
    "x":           {"name": "X (Twitter)", "region": "global", "color": "#000000", "home": "https://x.com"},
    "hackernews":  {"name": "Hacker News", "region": "global", "color": "#FF6600", "home": "https://news.ycombinator.com"},
    "reddit":      {"name": "Reddit", "region": "global", "color": "#FF4500", "home": "https://www.reddit.com"},
    "github":      {"name": "GitHub Trending", "region": "global", "color": "#181717", "home": "https://github.com/trending"},
    "youtube":     {"name": "YouTube", "region": "global", "color": "#FF0000", "home": "https://www.youtube.com"},
    "tiktok":      {"name": "TikTok", "region": "global", "color": "#010101", "home": "https://www.tiktok.com"},
    "instagram":   {"name": "Instagram", "region": "global", "color": "#E4405F", "home": "https://www.instagram.com"},
    "facebook":    {"name": "Facebook", "region": "global", "color": "#1877F2", "home": "https://www.facebook.com"},
}

PLATFORM_ALIASES: Dict[str, str] = {
    "x_twitter": "x",
    "x_twitter_publisher": "x",
    "yt": "youtube",
    "ig": "instagram",
    "fb": "facebook",
    "tw": "x",
}

def normalize_platform_id(platform: str) -> str:
    return PLATFORM_ALIASES.get(platform, platform)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 内存缓存: { platform: (timestamp, items) }
_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
CACHE_TTL = 300  # 5 分钟

# 正在后台刷新的平台集合（stale-while-revalidate：防止多请求重复触发刷新）
_refreshing: set = set()


def _set_cache(platform: str, items: List[Dict[str, Any]]) -> None:
    _CACHE[platform] = (time.time(), items)


def _get_cache(platform: str) -> Optional[List[Dict[str, Any]]]:
    if platform not in _CACHE:
        return None
    ts, items = _CACHE[platform]
    if time.time() - ts > CACHE_TTL:
        return None
    return items


def _get_stale_cache(platform: str) -> Optional[List[Dict[str, Any]]]:
    """返回过期缓存数据（stale-while-revalidate 用）。

    与 _get_cache 不同：不检查 TTL，只要缓存存在就返回。
    用于缓存过期时立即返回旧数据，避免请求路径同步抓取导致慢请求。
    """
    if platform not in _CACHE:
        return None
    _, items = _CACHE[platform]
    return items


def _ensure_background_refresh(platform: str) -> None:
    """启动后台刷新任务（per-platform 去重，避免多请求重复刷新）。

    stale-while-revalidate 的核心：缓存过期时立即返回 stale 数据，
    同时后台异步刷新，下一次请求即可拿到新数据。
    """
    if platform in _refreshing:
        return
    if platform not in _FETCHERS:
        return
    _refreshing.add(platform)

    async def _refresh():
        try:
            items = await _FETCHERS[platform]()
            if items:
                _set_cache(platform, items)
        except Exception as e:
            print(f"[hotpoint] background refresh({platform}) error: {e}")
        finally:
            _refreshing.discard(platform)

    try:
        asyncio.create_task(_refresh())
    except RuntimeError:
        # 无事件循环（如同步上下文调用），降级跳过后台刷新
        _refreshing.discard(platform)


def _norm(title: str, url: str, rank: int, **extra) -> Dict[str, Any]:
    return {
        "rank": rank,
        "title": title,
        "url": url,
        "hot": str(extra.get("hot", "")),
        "author": str(extra.get("author", "")),
        "published_at": extra.get("published_at", 0),
        # 区域标识：国内平台 region="china"，海外平台 region="global" 或具体国家代码
        # 老调用方未传 region 时默认空串（向后兼容），新海外 fetcher 会传 "global"
        "region": str(extra.get("region", "")),
        "extra": extra.get("extra", {}),
    }


# ------------------------------------------------------------------------------
# 各平台 fetcher
# ------------------------------------------------------------------------------

async def _fetch_douyin() -> List[Dict[str, Any]]:
    url = "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1"
    try:
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10, follow_redirects=True) as client:
            # 从 login.douyin.com 获取必要 cookie
            try:
                login_resp = await client.get("https://login.douyin.com/")
                cookies = "; ".join([f"{k}={v}" for k, v in login_resp.cookies.items()])
            except Exception:
                cookies = ""
            headers = {**DEFAULT_HEADERS, "Referer": "https://www.douyin.com/"}
            if cookies:
                headers["Cookie"] = cookies
            r = await client.get(url, headers=headers)
            data = r.json()
        items = []
        for idx, k in enumerate(data.get("data", {}).get("word_list", [])[:30], 1):
            items.append(_norm(
                title=k.get("word", ""),
                url=f"https://www.douyin.com/hot/{k.get('sentence_id', '')}",
                rank=idx,
                hot=str(k.get("hot_value", "")),
                extra={"event_time": str(k.get("event_time", ""))},
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] douyin fetch failed: {e}")
        return []


async def _fetch_xiaohongshu() -> List[Dict[str, Any]]:
    url = "https://edith.xiaohongshu.com/api/sns/v1/search/hot_list"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.7(0x18000733) NetType/WIFI Language/zh_CN",
        "Referer": "https://app.xhs.cn/",
        "xy-direction": "22",
        "shield": "XYAAAAAQAAAAEAAABTAAAAUzUWEe4xG1IYD9/c+qCLOlKGmTtFa+lG434Oe+FTRagxxoaz6rUWSZ3+juJYz8RZqct+oNMyZQxLEBaBEL+H3i0RhOBVGrauzVSARchIWFYwbwkV",
        "xy-platform-info": "platform=iOS&version=8.7&build=8070515&deviceId=C323D3A5-6A27-4CE6-AA0E-51C9D4C26A24&bundle=com.xingin.discover",
        "xy-common-params": "app_id=ECFAAF02&build=8070515&channel=AppStore&deviceId=C323D3A5-6A27-4CE6-AA0E-51C9D4C26A24&device_fingerprint=20230920120211bd7b71a80778509cf4211099ea911000010d2f20f6050264&device_fingerprint1=20230920120211bd7b71a80778509cf4211099ea911000010d2f20f6050264&device_model=phone&fid=1695182528-0-0-63b29d709954a1bb8c8733eb2fb58f29&gid=7dc4f3d168c355f1a886c54a898c6ef21fe7b9a847359afc77fc24ad&identifier_flag=0&lang=zh-Hans&launch_id=716882697&platform=iOS&project_id=ECFAAF&sid=session.1695189743787849952190&t=1695190591&teenager=0&tz=Asia/Shanghai&uis=light&version=8.7",
    }
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10) as client:
            r = await client.get(url)
            data = r.json()
        if not data.get("success") or not data.get("data", {}).get("items"):
            return []
        items = []
        for idx, it in enumerate(data["data"]["items"][:30], 1):
            title = it.get("title", "")
            items.append(_norm(
                title=title,
                url=f"https://www.xiaohongshu.com/search_result?keyword={title}",
                rank=idx,
                hot=str(it.get("score", "")),
                extra={"icon": it.get("icon", "")},
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] xiaohongshu fetch failed: {e}")
        return []


async def _fetch_weibo() -> List[Dict[str, Any]]:
    url = "https://s.weibo.com/top/summary?cate=realtimehot"
    headers = {
        **DEFAULT_HEADERS,
        "Cookie": "SUB=_2AkMWIuNSf8NxqwJRmP8dy2rhaoV2ygrEieKgfhKJJRMxHRl-yT9jqk86tRB6PaLNvQZR6zYUcYVT1zSjoSreQHidcUq7",
        "referer": url,
    }
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=True) as client:
            r = await client.get(url)
            html = r.text
        items = []
        row_pattern = re.compile(
            r'<td class="td-02">.*?<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>(?:.*?<span>(\d+)</span>)?.*?</td>',
            re.S,
        )
        for idx, m in enumerate(row_pattern.findall(html)[:30], 1):
            href, title, hot = m
            if not title.strip() or "javascript:" in href:
                continue
            items.append(_norm(
                title=title.strip(),
                url=f"https://s.weibo.com{href}",
                rank=idx,
                hot=hot,
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] weibo fetch failed: {e}")
        return []


async def _fetch_zhihu() -> List[Dict[str, Any]]:
    url = "https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=30&desktop=true"
    headers = {**DEFAULT_HEADERS, "Referer": "https://www.zhihu.com/hot"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10) as client:
            r = await client.get(url)
            data = r.json()
        items = []
        for idx, k in enumerate(data.get("data", [])[:30], 1):
            target = k.get("target", {})
            title_area = target.get("title_area", {})
            link = target.get("link", {})
            items.append(_norm(
                title=title_area.get("text", ""),
                url=link.get("url", ""),
                rank=idx,
                hot=target.get("metrics_area", {}).get("text", ""),
                extra={
                    "excerpt": target.get("excerpt_area", {}).get("text", ""),
                    "image": target.get("image_area", {}).get("url", ""),
                },
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] zhihu fetch failed: {e}")
        return []


async def _fetch_bilibili() -> List[Dict[str, Any]]:
    url = "https://api.bilibili.com/x/web-interface/search/square?limit=30"
    try:
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10) as client:
            r = await client.get(url)
            data = r.json()
        items = []
        for idx, k in enumerate(data.get("data", {}).get("trending", {}).get("list", [])[:30], 1):
            keyword = k.get("keyword", "") or k.get("show_name", "")
            # B站热搜 square 接口的 goto_url/uri 均为空，用关键词构造搜索页 URL
            import urllib.parse
            item_url = k.get("goto_url", "") or k.get("uri", "")
            if not item_url and keyword:
                item_url = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(keyword)}"
            # 注意字段名是 heat_score（不是 hot_score）
            items.append(_norm(
                title=keyword,
                url=item_url,
                rank=idx,
                hot=str(k.get("heat_score", "") or k.get("hot_score", "")),
                extra={"icon": k.get("icon", ""), "show_name": k.get("show_name", "")},
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] bilibili fetch failed: {e}")
        return []


async def _fetch_kuaishou() -> List[Dict[str, Any]]:
    """快手热搜抓取

    通过快手 GraphQL 接口 visionHotRank 拉取热搜榜，
    若 GraphQL 失败则回退到搜索页 URL（用关键词构造）。
    """
    import urllib.parse
    graphql_url = "https://www.kuaishou.com/graphql"
    headers = {
        **DEFAULT_HEADERS,
        "Referer": "https://www.kuaishou.com/",
        "Origin": "https://www.kuaishou.com",
        "Content-Type": "application/json",
    }
    try:
        payload = {
            "operationName": "visionHotRank",
            "query": (
                "query visionHotRank($page:String, $count:Int){"
                " visionHotRank(page:$page, count:$count){"
                " itemList{ rank photoId tag displayName hotValue viewCount"
                " } } }"
            ),
            "variables": {"page": "1", "count": "30"},
        }
        items: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=True) as client:
            try:
                r = await client.post(graphql_url, json=payload)
                data = r.json()
                rank_list = (
                    data.get("data", {})
                    .get("visionHotRank", {})
                    .get("itemList", [])
                )
                for idx, k in enumerate(rank_list[:30], 1):
                    title = k.get("displayName", "") or k.get("tag", "")
                    photo_id = k.get("photoId", "")
                    item_url = (
                        f"https://www.kuaishou.com/short-video/{photo_id}"
                        if photo_id else
                        f"https://www.kuaishou.com/search/video?searchKey={urllib.parse.quote(title)}"
                    )
                    items.append(_norm(
                        title=title,
                        url=item_url,
                        rank=idx,
                        hot=str(k.get("hotValue", "") or k.get("viewCount", "")),
                        extra={"photo_id": photo_id, "source": "graphql"},
                    ))
                if items:
                    return items
            except Exception as ge:
                print(f"[hotpoint] kuaishou graphql failed: {ge}")

            # 回退：抓取热搜榜 HTML 页面（公开页面）
            try:
                r = await client.get("https://www.kuaishou.com/?isHome=1")
                html = r.text
                # 提取页面内嵌的 __APOLLO_STATE__ / window.__data
                m = re.search(r'"hotRankList":\[(.*?)\]', html, re.S)
                if m:
                    import json as _json
                    raw = "[" + m.group(1) + "]"
                    try:
                        arr = _json.loads(raw)
                    except Exception:
                        arr = []
                    for idx, k in enumerate(arr[:30], 1):
                        title = k.get("tagName", "") or k.get("name", "")
                        if not title:
                            continue
                        items.append(_norm(
                            title=title,
                            url=f"https://www.kuaishou.com/search/video?searchKey={urllib.parse.quote(title)}",
                            rank=idx,
                            hot=str(k.get("viewCount", "") or k.get("hotValue", "")),
                            extra={"source": "html"},
                        ))
                if items:
                    return items
            except Exception as he:
                print(f"[hotpoint] kuaishou html fallback failed: {he}")

        return items
    except Exception as e:
        print(f"[hotpoint] kuaishou fetch failed: {e}")
        return []


async def _fetch_baidu() -> List[Dict[str, Any]]:
    url = "https://top.baidu.com/board?tab=realtime"
    try:
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10, follow_redirects=True) as client:
            r = await client.get(url)
            html = r.text
        # 解析页面内嵌的 JSON 数据
        m = re.search(r'<!--s-data:(.*?)-->', html, re.S)
        if not m:
            # 回退到 API 接口
            api_url = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
            async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10) as client:
                r = await client.get(api_url)
                data = r.json()
        else:
            import json as _json
            data = _json.loads(m.group(1))
        items = []
        cards = data.get("data", {}).get("cards", [{}])
        content = cards[0].get("content", []) if cards else []
        # 过滤置顶项
        content = [k for k in content if not k.get("isTop")]
        for idx, k in enumerate(content[:30], 1):
            items.append(_norm(
                title=k.get("word", "") or k.get("query", ""),
                url=k.get("rawUrl", "") or k.get("url", ""),
                rank=idx,
                hot=str(k.get("hotScore", "")),
                author=k.get("name", ""),
                extra={"desc": k.get("desc", ""), "image": k.get("img", "")},
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] baidu fetch failed: {e}")
        return []


async def _fetch_toutiao() -> List[Dict[str, Any]]:
    url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
    try:
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10) as client:
            r = await client.get(url)
            data = r.json()
        items = []
        for idx, k in enumerate(data.get("data", [])[:30], 1):
            items.append(_norm(
                title=k.get("Title", ""),
                url=k.get("Url", ""),
                rank=idx,
                hot=k.get("HotValue", ""),
                extra={"label": k.get("Label", ""), "image": k.get("Image", "")},
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] toutiao fetch failed: {e}")
        return []


# ------------------------------------------------------------------------------
# 国外平台
# ------------------------------------------------------------------------------

async def _fetch_x(force_crawl: bool = False) -> List[Dict[str, Any]]:
    """X.com 热点: 从 XTwitterPost（权威全集表）查询，确保展示条数与数据库总计一致

    说明：XTwitterPost 是所有热点数据的权威存储（热点采集数据会同步到此表），
    total_in_db 也从此表计数，因此 _fetch_x 必须读同一张表，
    避免"本次 N 条"与"数据库总计 M 条"来自不同表导致不一致。
    """
    try:
        import config
        from database.db_session import get_async_engine
        from database.models import XTwitterPost, XTwitterTrendingPost
        from sqlalchemy import select, desc
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        # 如果强制刷新，先执行爬取
        if force_crawl:
            print(f"[hotpoint] x force_crawl=True, executing crawl_trending...")
            try:
                from api.services.x_trending_fetcher import crawl_trending
                await crawl_trending()
            except Exception as e:
                print(f"[hotpoint] x crawl_trending failed: {e}")

        engine = get_async_engine(config.SAVE_DATA_OPTION)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # 主源: XTwitterPost（权威全集表，与 total_in_db 同源，确保条数一致）
        async with async_session() as session:
            stmt = select(XTwitterPost).order_by(desc(XTwitterPost.created_at))
            result = await session.execute(stmt)
            posts = result.scalars().all()
            source_table = "XTwitterPost"

        # 回退: 若 XTwitterPost 为空(极少数情况)，从 XTwitterTrendingPost 读取
        if not posts:
            async with async_session() as session:
                stmt = select(XTwitterTrendingPost).order_by(desc(XTwitterTrendingPost.crawl_ts))
                result = await session.execute(stmt)
                posts = result.scalars().all()
                source_table = "XTwitterTrendingPost"

        def _to_int(s):
            try:
                s = str(s).replace(",", "").strip()
                if s.endswith("K") or s.endswith("k"):
                    return int(float(s[:-1]) * 1000)
                if s.endswith("M") or s.endswith("m"):
                    return int(float(s[:-1]) * 1000000)
                return int(float(s))
            except Exception:
                return 0

        posts_list = sorted(posts, key=lambda p: _to_int(p.likes_count), reverse=True)
        items = []
        for idx, p in enumerate(posts_list, 1):
            items.append(_norm(
                title=(p.content or "")[:100],
                url=p.post_url or "",
                rank=idx,
                hot=p.likes_count or "0",
                author=p.nickname or p.username or "",
                published_at=p.created_at or 0,
                extra={
                    "retweets": p.retweets_count,
                    "replies": p.replies_count,
                    "views": p.views_count,
                    "video_url": p.video_url or "",
                },
            ))
        print(f"[hotpoint] x fetch success: {len(items)} items from {source_table}")
        return items
    except Exception as e:
        print(f"[hotpoint] x fetch failed: {e}")
        return []


async def _fetch_hackernews() -> List[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10) as client:
            r = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
            ids = r.json()[:30]
            async def get_item(iid):
                rr = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{iid}.json")
                return rr.json()
            details = await asyncio.gather(*[get_item(i) for i in ids], return_exceptions=True)
        items = []
        for idx, d in enumerate(details, 1):
            if not isinstance(d, dict):
                continue
            items.append(_norm(
                title=d.get("title", ""),
                url=d.get("url") or f"https://news.ycombinator.com/item?id={d.get('id', '')}",
                rank=idx,
                hot=d.get("score", 0),
                author=d.get("by", ""),
                published_at=d.get("time", 0),
                extra={"comments": d.get("descendants", 0)},
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] hackernews fetch failed: {e}")
        return []


async def _fetch_reddit() -> List[Dict[str, Any]]:
    """Reddit 热点: 多策略获取，应对反爬限制"""
    # 策略1: 通过 Google News RSS 搜索 reddit.com 帖子
    try:
        rss_url = "https://news.google.com/rss/search?q=site:reddit.com+OR+reddit.com&hl=en-US&gl=US&ceid=US:en"
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10, follow_redirects=True) as client:
            r = await client.get(rss_url)
        if r.status_code == 200 and r.text:
            items = []
            item_pattern = re.compile(
                r'<item>\s*<title>(.*?)</title>\s*<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>.*?<source[^>]*>(.*?)</source>',
                re.S,
            )
            for idx, m in enumerate(item_pattern.findall(r.text)[:30], 1):
                title, link, pubdate, source = m
                title = title.replace('<![CDATA[', '').replace(']]>', '').strip()
                source = source.replace('<![CDATA[', '').replace(']]>', '').strip()
                if ' - ' in title:
                    parts = title.split(' - ', 1)
                    author, real_title = parts[0].strip(), parts[1].strip()
                else:
                    author, real_title = source, title
                items.append(_norm(
                    title=real_title,
                    url=link.strip(),
                    rank=idx,
                    hot="",
                    author=author,
                    published_at=0,
                    extra={"source": source, "pubDate": pubdate.strip()},
                ))
            if items:
                return items
    except Exception as e:
        print(f"[hotpoint] reddit (google news) failed: {e}")

    # 策略2: 直接 reddit.com RSS (可能被限流)
    try:
        headers = {"User-Agent": "python:hotpoint:1.0.0 (by /u/hotpoint)"}
        async with httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=True) as client:
            r = await client.get("https://www.reddit.com/r/popular.rss")
        if r.status_code == 200 and r.text:
            items = []
            item_pattern = re.compile(
                r'<item>\s*<title>(.*?)</title>\s*<link>(.*?)</link>(?:.*?)<dc:creator[^>]*>(.*?)</dc:creator>(?:.*?)<pubDate>(.*?)</pubDate>',
                re.S,
            )
            for idx, m in enumerate(item_pattern.findall(r.text)[:30], 1):
                title, link, author, pubdate = m
                title = title.replace('<![CDATA[', '').replace(']]>', '').strip()
                author = author.replace('<![CDATA[', '').replace(']]>', '').strip()
                items.append(_norm(
                    title=title,
                    url=link.strip(),
                    rank=idx,
                    hot="",
                    author=author,
                    published_at=0,
                    extra={"pubDate": pubdate.strip()},
                ))
            if items:
                return items
    except Exception as e:
        print(f"[hotpoint] reddit (rss) failed: {e}")

    return []

async def _fetch_github() -> List[Dict[str, Any]]:
    url = "https://github.com/trending"
    try:
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=15, follow_redirects=True) as client:
            r = await client.get(url)
            html = r.text
        items = []
        # 匹配 <h2 ...><a href="/owner/repo">...</a></h2>
        repo_pattern = re.compile(
            r'<h2[^>]*>\s*<a[^>]*href="(/[^"]+)"[^>]*>(.*?)</a>\s*</h2>',
            re.S,
        )
        matches = repo_pattern.findall(html)
        # 过滤非仓库链接 (例如 /login, /settings 等)
        repo_matches = [(href, name) for href, name in matches if href.count('/') == 2 and not href.startswith('/login')]
        for idx, (href, name) in enumerate(repo_matches[:30], 1):
            full_name = href.strip().lstrip("/")
            # 清除 name 中的 HTML 标签和空白
            clean_name = re.sub(r'<[^>]+>', '', name)
            clean_name = re.sub(r'\s+', ' ', clean_name).strip()
            # 提取描述 (在 article 中的 <p> 标签)
            desc_match = re.search(
                re.escape(href) + r'".*?</h2>.*?<p[^>]*>([^<]*)</p>',
                html, re.S
            )
            desc = desc_match.group(1).strip() if desc_match else ""
            items.append(_norm(
                title=full_name,
                url=f"https://github.com{href}",
                rank=idx,
                hot="",
                extra={"description": desc},
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] github fetch failed: {e}")
        return []

async def _fetch_google_news_rss(
    query: str, region: str = "global", source_label: str = ""
) -> List[Dict[str, Any]]:
    """通用 Google News RSS 聚合源抓取（海外平台兜底）

    由于 TikTok/Instagram/Facebook 公开趋势接口多数需要签名/登录或有反爬限制，
    统一使用 Google News RSS 聚合源作为公开、免费、稳定的兜底数据源。

    Args:
        query: Google News search query，例如 "site:tiktok.com OR tiktok.com"
        region: 区域标识，海外平台默认 "global"，可传具体国家代码
        source_label: 来源标签，用于标识原始平台（如 "tiktok-google-news"）

    Returns:
        与 _fetch_x 一致的 HotItem 列表（字段: rank/title/url/hot/author/published_at/region/extra）
    """
    rss_url = (
        f"https://news.google.com/rss/search?q={query}"
        "&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS, timeout=30, follow_redirects=True
        ) as client:
            r = await client.get(rss_url)
            text = r.text
        items: List[Dict[str, Any]] = []
        # RSS item 结构: <item><title>...</title><link>...</link>...<pubDate>...</pubDate>...<source>...</source>
        item_pattern = re.compile(
            r'<item>\s*<title>(.*?)</title>\s*<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>.*?<source[^>]*>(.*?)</source>',
            re.S,
        )
        for idx, m in enumerate(item_pattern.findall(text)[:30], 1):
            title, link, pubdate, source = m
            title = title.replace('<![CDATA[', '').replace(']]>', '').strip()
            source = source.replace('<![CDATA[', '').replace(']]>', '').strip()
            # Google News RSS title 格式通常为 "Source - Title"
            if ' - ' in title:
                parts = title.split(' - ', 1)
                author, real_title = parts[0].strip(), parts[1].strip()
            else:
                author, real_title = source, title
            items.append(_norm(
                title=real_title,
                url=link.strip(),
                rank=idx,
                hot="",
                author=author,
                published_at=0,
                region=region,
                extra={
                    "source": source,
                    "source_label": source_label,
                    "pubDate": pubdate.strip(),
                },
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] google news rss ({source_label}) failed: {e}")
        return []


async def _fetch_tiktok() -> List[Dict[str, Any]]:
    """TikTok 热门: 优先尝试 TikTok 公开趋势接口，失败回退 Google News RSS 聚合源

    返回结构同 _fetch_x，region="global"。
    extra 字段携带 video_url/username/likes_count/retweets_count/replies_count/views_count/source_label
    """
    # 策略1: TikTok 公开趋势接口（通常需要签名，大概率被限流，作为尝试）
    try:
        trending_url = (
            "https://www.tiktok.com/api/trending/category/list/"
            "?count=30&aid=1988&app_language=en&region=US&device_id=0"
        )
        headers = {
            **DEFAULT_HEADERS,
            "Referer": "https://www.tiktok.com/trending",
            "Accept": "application/json, text/plain, */*",
        }
        async with httpx.AsyncClient(
            headers=headers, timeout=30, follow_redirects=True
        ) as client:
            r = await client.get(trending_url)
            if r.status_code == 200 and r.text:
                try:
                    data = r.json()
                except Exception:
                    data = None
                # TikTok 趋势接口可能返回 {"itemList": [...]} 或直接为 list
                raw_items = []
                if isinstance(data, dict):
                    raw_items = data.get("itemList") or data.get("items") or []
                elif isinstance(data, list):
                    raw_items = data
                if raw_items:
                    items: List[Dict[str, Any]] = []
                    for idx, k in enumerate(raw_items[:30], 1):
                        stats = k.get("stats", {}) or {}
                        author = k.get("author", {}) or {}
                        video = k.get("video", {}) or {}
                        vid = k.get("id", "")
                        uid = author.get("unique_id", "")
                        items.append(_norm(
                            title=(k.get("desc", "") or "")[:120],
                            url=(
                                f"https://www.tiktok.com/@{uid}/video/{vid}"
                                if vid else ""
                            ),
                            rank=idx,
                            hot=str(stats.get("diggCount", 0) or stats.get("playCount", 0)),
                            author=author.get("nickname", "") or uid,
                            published_at=0,
                            region="global",
                            extra={
                                "platform": "tiktok",
                                "video_url": video.get("playAddr", "") or video.get("downloadAddr", ""),
                                "username": uid,
                                "likes_count": int(stats.get("diggCount", 0) or 0),
                                "retweets_count": int(stats.get("shareCount", 0) or 0),
                                "replies_count": int(stats.get("commentCount", 0) or 0),
                                "views_count": int(stats.get("playCount", 0) or 0),
                                "source_label": "tiktok-trending",
                            },
                        ))
                    if items:
                        return items
    except Exception as e:
        print(f"[hotpoint] tiktok (trending api) failed: {e}")

    # 策略2: Google News RSS 聚合源兜底
    return await _fetch_google_news_rss(
        query="site:tiktok.com OR tiktok.com",
        region="global",
        source_label="tiktok-google-news",
    )


async def _fetch_instagram() -> List[Dict[str, Any]]:
    """Instagram 热门: Instagram 公开探索页需登录，无官方 RSS，使用 Google News RSS 聚合源

    返回结构同 _fetch_x，region="global"。
    extra 字段携带 source_label="instagram-google-news"
    """
    return await _fetch_google_news_rss(
        query="site:instagram.com OR instagram.com",
        region="global",
        source_label="instagram-google-news",
    )


async def _fetch_facebook() -> List[Dict[str, Any]]:
    """Facebook 热门: Facebook 公共趋势已于 2018 年下线，使用 Google News RSS 聚合源

    返回结构同 _fetch_x，region="global"。
    extra 字段携带 source_label="facebook-google-news"
    """
    return await _fetch_google_news_rss(
        query="site:facebook.com OR facebook.com",
        region="global",
        source_label="facebook-google-news",
    )


async def _fetch_youtube() -> List[Dict[str, Any]]:
    """YouTube 热门: 优先调用 YouTube Data API v3 videos?chart=mostPopular（需配置 YOUTUBE_API_KEY），
    并补充 Google News RSS 搜索 youtube.com 内容作为兜底/聚合，最终合并去重后返回。

    返回结构同 _fetch_x，region="global"。
    extra 字段携带 video_url/likes_count/comments_count/views_count/tags/thumbnail
    """
    items: List[Dict[str, Any]] = []
    seen_urls: set = set()

    # 策略1: YouTube Data API v3 - videos?chart=mostPopular（需 YOUTUBE_API_KEY）
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if api_key:
        try:
            api_url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "maxResults": 30,
                "regionCode": "US",
                "hl": "en",
                "key": api_key,
            }
            async with httpx.AsyncClient(
                headers=DEFAULT_HEADERS, timeout=30, follow_redirects=True
            ) as client:
                r = await client.get(api_url, params=params)
                data = r.json()
            for idx, v in enumerate(data.get("items", [])[:30], 1):
                snippet = v.get("snippet", {}) or {}
                stats = v.get("statistics", {}) or {}
                vid = v.get("id", "")
                watch_url = f"https://www.youtube.com/watch?v={vid}" if vid else ""
                if watch_url and watch_url in seen_urls:
                    continue
                if watch_url:
                    seen_urls.add(watch_url)
                items.append(_norm(
                    title=snippet.get("title", ""),
                    url=watch_url,
                    rank=idx,
                    hot=str(stats.get("viewCount", "") or ""),
                    author=snippet.get("channelTitle", ""),
                    published_at=0,
                    region="global",
                    extra={
                        "source": "youtube-data-api-v3",
                        "video_url": watch_url,
                        "username": snippet.get("channelTitle", ""),
                        "likes_count": int(stats.get("likeCount", 0) or 0),
                        "comments_count": int(stats.get("commentCount", 0) or 0),
                        "views_count": int(stats.get("viewCount", 0) or 0),
                        "tags": snippet.get("tags", []) or [],
                        "thumbnail": (snippet.get("thumbnails", {}) or {})
                        .get("high", {})
                        .get("url", ""),
                    },
                ))
        except Exception as e:
            print(f"[hotpoint] youtube (data api v3) failed: {e}")

    # 策略2: Google News RSS 兜底/补充（无论策略1是否成功都补充）
    try:
        rss_url = "https://news.google.com/rss/search?q=site:youtube.com&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS, timeout=30, follow_redirects=True
        ) as client:
            r = await client.get(rss_url)
            html = r.text
        item_pattern = re.compile(
            r'<item>\s*<title>(.*?)</title>\s*<link>(.*?)</link>\s*<guid[^>]*>.*?</guid>\s*<pubDate>(.*?)</pubDate>.*?<source[^>]*>(.*?)</source>',
            re.S,
        )
        start_rank = len(items) + 1
        for idx, m in enumerate(
            item_pattern.findall(html)[:30], start_rank
        ):
            title, link, pubdate, source = m
            title = title.replace('<![CDATA[', '').replace(']]>', '').strip()
            source = source.replace('<![CDATA[', '').replace(']]>', '').strip()
            # title 格式: "视频标题 - YouTube" 或 "Source - Title"
            # 修复：如果 split 后 real_title 是平台名（YouTube），说明 author 才是真正的标题
            if ' - ' in title:
                parts = title.split(' - ', 1)
                left, right = parts[0].strip(), parts[1].strip()
                # 如果右边是平台名（YouTube），则左边是真正的标题
                if right.lower() in ('youtube', 'google news', 'news', 'reddit'):
                    author, real_title = source or right, left
                else:
                    author, real_title = left, right
            else:
                author, real_title = source, title
            link = link.strip()
            if link and link in seen_urls:
                continue
            if link:
                seen_urls.add(link)
            items.append(_norm(
                title=real_title,
                url=link,
                rank=idx,
                hot="",
                author=author,
                published_at=0,
                region="global",
                extra={"source": source, "pubDate": pubdate.strip()},
            ))
    except Exception as e:
        print(f"[hotpoint] youtube (google news) failed: {e}")

    return items


# 平台 -> 抓取函数映射
_FETCHERS: Dict[str, Any] = {
    "douyin": _fetch_douyin,
    "xiaohongshu": _fetch_xiaohongshu,
    "weibo": _fetch_weibo,
    "zhihu": _fetch_zhihu,
    "bilibili": _fetch_bilibili,
    "kuaishou": _fetch_kuaishou,
    "baidu": _fetch_baidu,
    "toutiao": _fetch_toutiao,
    "x": _fetch_x,
    "hackernews": _fetch_hackernews,
    "reddit": _fetch_reddit,
    "github": _fetch_github,
    "youtube": _fetch_youtube,
    "tiktok": _fetch_tiktok,
    "instagram": _fetch_instagram,
    "facebook": _fetch_facebook,
}


async def fetch_platform(platform: str, force_refresh: bool = False, return_stats: bool = False) -> List[Dict[str, Any]]:
    """获取指定平台的热点内容（带缓存 + stale-while-revalidate）

    缓存策略：
    1. 缓存未过期：直接返回（快）
    2. force_refresh=True：同步抓取最新（refresh 后台任务用）
    3. 缓存过期 + 有 stale 数据：立即返回 stale + 后台异步刷新（避免请求路径同步抓取导致慢请求）
    4. 缓存过期 + 无 stale（首次/重启后）：同步抓取（不可避免）
    """
    if platform not in _FETCHERS:
        return [] if not return_stats else {"items": [], "added": 0, "total": 0}

    old_count = 0
    cached = _get_cache(platform)
    if cached is not None:
        old_count = len(cached)
        if not force_refresh:
            if return_stats:
                return {"items": cached, "added": 0, "total": old_count}
            return cached

    # force_refresh：refresh 后台任务需要最新数据，同步抓取
    if force_refresh:
        try:
            if platform == "x":
                items = await _FETCHERS[platform](force_crawl=True)
            else:
                items = await _FETCHERS[platform]()
            if items:
                _set_cache(platform, items)
            new_count = len(items)
            added_count = max(0, new_count - old_count)
            if return_stats:
                return {"items": items, "added": added_count, "total": new_count}
            return items
        except Exception as e:
            print(f"[hotpoint] fetch_platform({platform}) error: {e}")
            return [] if not return_stats else {"items": [], "added": 0, "total": 0}

    # 缓存过期（非 force_refresh）：stale-while-revalidate
    stale = _get_stale_cache(platform)
    if stale is not None:
        # 有旧数据：后台刷新 + 立即返回 stale（请求路径零等待）
        _ensure_background_refresh(platform)
        if return_stats:
            return {"items": stale, "added": 0, "total": len(stale)}
        return stale

    # 无任何缓存（首次/服务重启后）：短超时尝试抓取，超时返回空 + 后台刷新
    # 避免切换到未缓存平台时同步抓取 10-30s 阻塞请求（用户体验差）
    try:
        if platform == "x":
            fetch_coro = _FETCHERS[platform](force_crawl=True)
        else:
            fetch_coro = _FETCHERS[platform]()
        try:
            items = await asyncio.wait_for(fetch_coro, timeout=8.0)
        except asyncio.TimeoutError:
            print(f"[hotpoint] fetch_platform({platform}) 无缓存首抓超时(8s)，返回空 + 后台继续抓取")
            _ensure_background_refresh(platform)
            return [] if not return_stats else {"items": [], "added": 0, "total": 0}
        if items:
            _set_cache(platform, items)
        new_count = len(items)
        added_count = max(0, new_count - old_count)
        if return_stats:
            return {"items": items, "added": added_count, "total": new_count}
        return items
    except Exception as e:
        print(f"[hotpoint] fetch_platform({platform}) error: {e}")
        return [] if not return_stats else {"items": [], "added": 0, "total": 0}


async def fetch_all(force_refresh: bool = False, return_stats: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """并发获取所有平台热点

    性能优化：用 Semaphore 限制并发数为 3，避免 15 个平台同时抓取打满 CPU/内存。
    在单核/双核机器上，全并发抓取会导致 CPU 100% 持续数十秒。
    """
    platforms = list(_FETCHERS.keys())
    # 限制并发数，避免 CPU/内存打满（P1-10 性能优化）
    _sem = asyncio.Semaphore(3)

    # 普通请求路径（非 force_refresh）加单平台超时保护：
    # 避免单个慢平台（如 x 的 Playwright 爬取）拖垮整体，导致 HTTP 60s 超时。
    # force_refresh（后台预热/刷新任务）不限制，后台跑可拿完整数据。
    use_timeout = not force_refresh
    _per_platform_timeout = 6.0

    async def _fetch_with_limit(p: str):
        async with _sem:
            if use_timeout:
                try:
                    return await asyncio.wait_for(
                        fetch_platform(p, force_refresh, return_stats=return_stats),
                        timeout=_per_platform_timeout,
                    )
                except asyncio.TimeoutError:
                    print(f"[hotpoint] fetch_all({p}) 超时({_per_platform_timeout}s)，跳过，由后台预热补全")
                    return [] if not return_stats else {"items": [], "added": 0, "total": 0}
            return await fetch_platform(p, force_refresh, return_stats=return_stats)

    results = await asyncio.gather(*[_fetch_with_limit(p) for p in platforms])
    return {p: items for p, items in zip(platforms, results)}


def get_platform_list() -> List[Dict[str, Any]]:
    """返回支持的平台元信息列表"""
    return [{"id": pid, **meta} for pid, meta in PLATFORMS.items()]
