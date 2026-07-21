# -*- coding: utf-8 -*-
"""
热点内容采集服务

从国内外主流社交/资讯平台采集热门内容，统一格式后供 API 路由使用。
支持的平台:
  国内: 抖音 / 小红书 / 微博 / 知乎 / 哔哩哔哩 / 百度 / 头条
  国外: X.com (复用已采集的 XTwitterPost) / Hacker News / Reddit / GitHub Trending / YouTube

数据格式 (HotItem):
  {
    "rank": int,
    "title": str,
    "url": str,
    "hot": str,            # 热度数值/描述
    "author": str,         # 作者/来源
    "published_at": int,   # 发布时间戳(秒)，可选
    "extra": dict          # 平台特定附加信息
  }
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

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
    "baidu":       {"name": "百度热搜", "region": "china", "color": "#2932E1", "home": "https://www.baidu.com"},
    "toutiao":     {"name": "今日头条", "region": "china", "color": "#F04142", "home": "https://www.toutiao.com"},
    # ===== 国外 =====
    "x":           {"name": "X (Twitter)", "region": "global", "color": "#000000", "home": "https://x.com"},
    "hackernews":  {"name": "Hacker News", "region": "global", "color": "#FF6600", "home": "https://news.ycombinator.com"},
    "reddit":      {"name": "Reddit", "region": "global", "color": "#FF4500", "home": "https://www.reddit.com"},
    "github":      {"name": "GitHub Trending", "region": "global", "color": "#181717", "home": "https://github.com/trending"},
    "youtube":     {"name": "YouTube", "region": "global", "color": "#FF0000", "home": "https://www.youtube.com"},
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 内存缓存: { platform: (timestamp, items) }
_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
CACHE_TTL = 300  # 5 分钟


def _set_cache(platform: str, items: List[Dict[str, Any]]) -> None:
    _CACHE[platform] = (time.time(), items)


def _get_cache(platform: str) -> Optional[List[Dict[str, Any]]]:
    if platform not in _CACHE:
        return None
    ts, items = _CACHE[platform]
    if time.time() - ts > CACHE_TTL:
        return None
    return items


def _norm(title: str, url: str, rank: int, **extra) -> Dict[str, Any]:
    return {
        "rank": rank,
        "title": title,
        "url": url,
        "hot": str(extra.get("hot", "")),
        "author": str(extra.get("author", "")),
        "published_at": extra.get("published_at", 0),
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
            items.append(_norm(
                title=k.get("keyword", ""),
                url=k.get("goto_url", "") or k.get("uri", ""),
                rank=idx,
                hot=k.get("hot_score", ""),
            ))
        return items
    except Exception as e:
        print(f"[hotpoint] bilibili fetch failed: {e}")
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
    """X.com 热点: 优先从 XTwitterTrendingPost（新热点采集表）查询，回退到 XTwitterPost"""
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
        
        # 优先从新的热点采集表查询（不限制数量）
        async with async_session() as session:
            stmt = select(XTwitterTrendingPost).order_by(desc(XTwitterTrendingPost.crawl_ts))
            result = await session.execute(stmt)
            posts = result.scalars().all()

        # 如果新表没有数据，回退到旧表（不限制数量）
        if not posts:
            async with async_session() as session:
                stmt = select(XTwitterPost).order_by(desc(XTwitterPost.created_at))
                result = await session.execute(stmt)
                posts = result.scalars().all()

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
        print(f"[hotpoint] x fetch success: {len(items)} items from {'XTwitterTrendingPost' if len(posts) > 0 else 'XTwitterPost'}")
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

async def _fetch_youtube() -> List[Dict[str, Any]]:
    """YouTube 热门: 通过 Google News RSS 搜索 youtube.com 内容"""
    try:
        rss_url = "https://news.google.com/rss/search?q=site:youtube.com&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=10, follow_redirects=True) as client:
            r = await client.get(rss_url)
            html = r.text
        items = []
        # 解析 RSS items: <item><title>...</title><link>...</link><guid>...</guid><pubDate>...</pubDate><description>...</description><source url="...">...</source>
        item_pattern = re.compile(
            r'<item>\s*<title>(.*?)</title>\s*<link>(.*?)</link>\s*<guid[^>]*>.*?</guid>\s*<pubDate>(.*?)</pubDate>.*?<source[^>]*>(.*?)</source>',
            re.S,
        )
        for idx, m in enumerate(item_pattern.findall(html)[:30], 1):
            title, link, pubdate, source = m
            title = title.replace('<![CDATA[', '').replace(']]>', '').strip()
            source = source.replace('<![CDATA[', '').replace(']]>', '').strip()
            # title 格式: "Source - Title"
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
        return items
    except Exception as e:
        print(f"[hotpoint] youtube fetch failed: {e}")
        return []


# 平台 -> 抓取函数映射
_FETCHERS: Dict[str, Any] = {
    "douyin": _fetch_douyin,
    "xiaohongshu": _fetch_xiaohongshu,
    "weibo": _fetch_weibo,
    "zhihu": _fetch_zhihu,
    "bilibili": _fetch_bilibili,
    "baidu": _fetch_baidu,
    "toutiao": _fetch_toutiao,
    "x": _fetch_x,
    "hackernews": _fetch_hackernews,
    "reddit": _fetch_reddit,
    "github": _fetch_github,
    "youtube": _fetch_youtube,
}


async def fetch_platform(platform: str, force_refresh: bool = False, return_stats: bool = False) -> List[Dict[str, Any]]:
    """获取指定平台的热点内容（带缓存）"""
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
    
    try:
        # X平台特殊处理：force_refresh时触发实际爬取
        if platform == "x" and force_refresh:
            items = await _FETCHERS[platform](force_crawl=True)
        else:
            items = await _FETCHERS[platform]()
        
        if items:
            _set_cache(platform, items)
        
        new_count = len(items)
        added_count = new_count - old_count
        if added_count < 0:
            added_count = 0
        
        if return_stats:
            return {"items": items, "added": added_count, "total": new_count}
        return items
    except Exception as e:
        print(f"[hotpoint] fetch_platform({platform}) error: {e}")
        return [] if not return_stats else {"items": [], "added": 0, "total": 0}


async def fetch_all(force_refresh: bool = False, return_stats: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """并发获取所有平台热点"""
    platforms = list(_FETCHERS.keys())
    
    if return_stats:
        results = await asyncio.gather(*[fetch_platform(p, force_refresh, return_stats=True) for p in platforms])
        return {p: items for p, items in zip(platforms, results)}
    else:
        results = await asyncio.gather(*[fetch_platform(p, force_refresh) for p in platforms])
        return {p: items for p, items in zip(platforms, results)}


def get_platform_list() -> List[Dict[str, Any]]:
    """返回支持的平台元信息列表"""
    return [{"id": pid, **meta} for pid, meta in PLATFORMS.items()]
