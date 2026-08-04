# -*- coding: utf-8 -*-
"""
X Twitter 热点采集服务 - 优化版

多策略采集方案：
1. 主策略：调用已有的爬取接口，使用 XTwitterCrawler（已配置 cookies）
2. 备用策略：从数据库已有帖子中提取热点（按点赞数排序）
3. 兜底策略：使用热门关键词进行搜索爬取

特点：
- 不直接创建浏览器，复用现有爬虫基础设施
- 自动清理过期数据
- 支持定时采集和手动触发
"""
import asyncio
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_session import get_session
from database.models import XTwitterTrendingTopic, XTwitterTrendingPost, XTwitterPost

TRENDING_CRAWL_INTERVAL = int(os.getenv("X_TRENDING_CRAWL_INTERVAL_MINUTES", "30")) * 60
MAX_TOPICS_PER_CRAWL = 20
MAX_POSTS_PER_TOPIC = 200
CLEANUP_HOURS = 24

_trending_task: Optional[asyncio.Task] = None
_trending_running = False
# 最近一次直接爬取是否命中 Cloudflare 挑战页（用于 crawl_trending 短路策略 3，避免无谓串行重试）
_last_cloudflare_hit: bool = False

FALLBACK_KEYWORDS = ["AI", "technology", "programming", "machine learning", "GPT", "Gemini", "OpenAI", "编程副业", "编程兼职", "副业", "兼职", "deep learning", "artificial intelligence", "chatbot", "robot", "metaverse", "blockchain", "crypto", "bitcoin", "ethereum", "web3", "NFT", "virtual reality", "augmented reality", "自动驾驶", "新能源", "云计算", "大数据", "量子计算", "5G", "6G", "智能家居", "物联网", "边缘计算", "人工智能", "机器学习", "深度学习", "自然语言处理", "计算机视觉", "推荐系统"]

# X.com tweet 元素的多级备用选择器（按优先级，应对页面结构变化）
_TWEET_SELECTORS = [
    'article[data-testid="tweet"]',
    '[data-testid="tweet"]',
    'article[role="article"]',
    'div[data-testid="cellInnerDiv"] article',
    'article',
]

# 单关键词搜索整体超时（秒），避免单个关键词卡死整个采集
_PER_KEYWORD_TIMEOUT = 20.0
# wait_for_selector 等待 tweet 元素首次出现的超时（秒）
_TWEET_WAIT_TIMEOUT = 8000  # ms


async def _is_cloudflare_challenge(page) -> bool:
    """检测 Cloudflare 反爬挑战页（与 comment_reply_monitor 一致的快速失败策略）"""
    try:
        title = await page.title()
    except Exception:
        return False
    if not title:
        return False
    t = title.lower()
    return (
        "just a moment" in t
        or "checking your browser" in t
        or "attention required" in t
        or "ddos protection" in t
    )


async def _find_tweet_elements(page):
    """按优先级依次尝试多个选择器，返回首个命中的元素列表与选择器名"""
    for sel in _TWEET_SELECTORS:
        try:
            elements = await page.query_selector_all(sel)
            if elements:
                return elements, sel
        except Exception:
            continue
    return [], None


async def _parse_tweet_element(element) -> Optional[Dict[str, Any]]:
    """解析单个 tweet 元素，提取内容/用户/互动数据。失败返回 None。"""
    try:
        post_data: Dict[str, Any] = {}

        content_el = await element.query_selector('[data-testid="tweetText"]')
        post_data["content"] = await content_el.inner_text() if content_el else ""

        if not post_data["content"]:
            return None

        username_el = await element.query_selector('[data-testid="User-Name"] a span')
        if not username_el:
            username_el = await element.query_selector('a[href^="/"] span')
        post_data["username"] = (await username_el.inner_text()).replace("@", "") if username_el else ""

        nickname_el = await element.query_selector('[data-testid="User-Name"] a div span')
        if not nickname_el:
            nickname_el = await element.query_selector('[data-testid="User-Name"] span')
        post_data["nickname"] = await nickname_el.inner_text() if nickname_el else ""

        link_el = await element.query_selector('[data-testid="User-Name"] a')
        href = await link_el.get_attribute("href") if link_el else ""
        username_part = ""
        if href and "/" in href:
            username_part = href.split("/")[1]

        post_id = ""
        status_links = await element.query_selector_all('a[href*="/status/"]')
        for link in status_links:
            status_href = await link.get_attribute("href")
            if status_href and "/status/" in status_href:
                parts = status_href.split("/status/")
                if len(parts) > 1:
                    post_id = parts[1].split("?")[0].split("/")[0]
                    break

        if not post_id:
            time_el = await element.query_selector('time')
            time_href = await time_el.get_attribute("datetime") if time_el else ""
            post_id = time_href.split(":")[0] if ":" in time_href else ""

        post_data["post_id"] = post_id
        post_data["post_url"] = f"https://x.com/{username_part}/status/{post_id}"

        likes_el = await element.query_selector('[data-testid="like"] span')
        post_data["likes_count"] = await likes_el.inner_text() if likes_el else "0"

        retweets_el = await element.query_selector('[data-testid="retweet"] span')
        post_data["retweets_count"] = await retweets_el.inner_text() if retweets_el else "0"

        replies_el = await element.query_selector('[data-testid="reply"] span')
        post_data["replies_count"] = await replies_el.inner_text() if replies_el else "0"

        views_el = await element.query_selector('[data-testid="view"] span')
        post_data["views_count"] = await views_el.inner_text() if views_el else "0"

        time_el = await element.query_selector('time')
        post_data["created_at"] = await time_el.get_attribute("datetime") if time_el else ""

        video_el = await element.query_selector('[data-testid="video"]')
        post_data["video_url"] = ""
        if video_el:
            video_src = await video_el.get_attribute("src")
            post_data["video_url"] = video_src if video_src else ""

        image_els = await element.query_selector_all('[data-testid="tweetImage"]')
        post_data["image_url"] = ""
        if image_els:
            img_el = await image_els[0].query_selector("img")
            if img_el:
                post_data["image_url"] = await img_el.get_attribute("src") or ""

        if post_data.get("post_id") and post_data.get("content"):
            return post_data
        return None
    except Exception:
        return None


async def _search_one_keyword(page, search_url: str, all_posts: dict) -> None:
    """搜索单个关键词并解析推文，结果累积到 all_posts（按 post_id 去重）。

    优化点：
    1. goto 后立即检测 Cloudflare 挑战页 → 抛出带 cloudflare 标记的异常，触发上层快速失败
    2. 用 wait_for_selector 主动等待 tweet 元素加载（替代固定 sleep 5s）
    3. 检测“没有结果”提示，提前结束
    4. 滚动加载更多，使用多级备用选择器
    """
    await page.goto(search_url, wait_until="domcontentloaded")

    # Cloudflare 挑战页快速失败
    if await _is_cloudflare_challenge(page):
        raise RuntimeError("cloudflare_challenge_detected")

    # 主动等待 tweet 元素出现（最多 _TWEET_WAIT_TIMEOUT ms），替代固定 sleep 5s
    try:
        await page.wait_for_selector(
            ', '.join(_TWEET_SELECTORS),
            timeout=_TWEET_WAIT_TIMEOUT,
        )
    except Exception:
        # 等待超时：可能是无结果页或反爬，进一步检查
        html_content = await page.content()
        if len(html_content) < 5000:
            print(f"[x_trending] 页面内容过短({len(html_content)}字符)，可能为空/反爬，跳过")
            return
        # 检测“没有结果”提示
        try:
            no_result_el = await page.query_selector('[data-testid="empty_state"]')
        except Exception:
            no_result_el = None
        if no_result_el:
            print(f"[x_trending] 页面提示无结果，跳过此关键词")
            return
        # 兜底：直接尝试用多级选择器抓取（可能元素已加载但选择器等待超时）
        print(f"[x_trending] wait_for_selector 超时，尝试直接抓取")

    scroll_count = 0
    max_scrolls = 3
    while scroll_count < max_scrolls:
        try:
            if len(all_posts) >= MAX_POSTS_PER_TOPIC:
                break

            tweet_elements, used_sel = await _find_tweet_elements(page)
            if not tweet_elements:
                print(f"[x_trending] 本轮未找到 tweet 元素（所有选择器均未命中），停止滚动")
                break

            if scroll_count == 0:
                print(f"[x_trending] 命中选择器: {used_sel}, 找到 {len(tweet_elements)} 个元素")

            for element in tweet_elements:
                post_data = await _parse_tweet_element(element)
                if post_data:
                    all_posts[post_data["post_id"]] = post_data

            if len(all_posts) >= MAX_POSTS_PER_TOPIC:
                break

            # 滚动到底部加载更多
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
            scroll_count += 1
        except Exception as e:
            print(f"[x_trending] 滚动抓取异常: {e}")
            break


async def _crawl_with_existing_api(keywords: str = "") -> bool:
    """使用已有的爬取接口进行热点采集（使用 Cookie 池，支持多 cookie 重试）

    改进点：
    1. 从 cookie 池依次尝试多个 cookie（最多 3 次）
    2. 区分「cookie 失效」和「浏览器启动失败」—— 浏览器超时不算 cookie 问题
    3. 使用 try/finally 确保配置一定被恢复
    """
    from api.services.cookie_pool_manager import (
        get_cookie_from_pool,
        mark_cookie_success,
        mark_cookie_failure,
        get_pool_summary,
    )

    pool_summary = get_pool_summary()
    max_retries = min(3, pool_summary.get("available", 1) or 1)
    if max_retries < 1:
        print("[x_trending] Cookie 池为空，无法启动爬虫")
        return False

    import config
    from media_platform.x_twitter.core import XTwitterCrawler

    # 保存原始配置，确保最后一定恢复
    original_crawler_type = getattr(config, "CRAWLER_TYPE", "search")
    original_keywords = getattr(config, "KEYWORDS", "")
    original_max_posts = getattr(config, "X_TWITTER_MAX_POSTS", 20)
    original_cookies = getattr(config, "COOKIES", "")

    tried_cookies = set()
    last_error = ""
    success = False

    try:
        for attempt in range(1, max_retries + 1):
            cookie = get_cookie_from_pool()
            if not cookie or cookie in tried_cookies:
                # 池里没有新 cookie 可试了
                if not cookie:
                    break
                # 同一个 cookie 再次被选中，说明池太小
                if attempt > 1:
                    break

            tried_cookies.add(cookie)
            print(f"[x_trending] 第 {attempt}/{max_retries} 次尝试，使用 cookie: {cookie[:30]}...")

            try:
                # 设置爬虫配置
                if keywords:
                    config.CRAWLER_TYPE = "search"
                    config.KEYWORDS = keywords
                else:
                    config.CRAWLER_TYPE = "trending"
                    config.KEYWORDS = ""
                config.X_TWITTER_MAX_POSTS = MAX_POSTS_PER_TOPIC
                config.COOKIES = cookie

                print(f"[x_trending] 启动爬虫，模式: {config.CRAWLER_TYPE}, 关键词: {config.KEYWORDS}")

                crawler = XTwitterCrawler()
                await crawler.start()

                # 成功！
                mark_cookie_success(cookie)
                print(f"[x_trending] 爬虫采集成功（第 {attempt} 次尝试）")
                success = True
                return True

            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                print(f"[x_trending] 第 {attempt} 次尝试失败: {error_msg[:200]}")

                # 区分错误类型：
                # - 浏览器启动超时 → 不是 cookie 问题，不标记失败，换 cookie 也没用
                # - 登录失效/403/401 → cookie 问题，标记失败
                # - 其他 → 谨慎标记失败
                is_browser_error = (
                    "Browser failed to start" in error_msg
                    or "Target closed" in error_msg
                    or "Navigation timeout" in error_msg
                    or "Page.goto" in error_msg
                    or "TimeoutError" in error_msg
                )
                is_cookie_error = (
                    "login" in error_msg.lower()
                    or "403" in error_msg
                    or "401" in error_msg
                    or "unauthorized" in error_msg.lower()
                    or "cookie" in error_msg.lower()
                )

                if is_cookie_error and not is_browser_error:
                    mark_cookie_failure(cookie, f"Cookie 失效: {error_msg[:100]}")
                    print(f"[x_trending] Cookie 失效已标记，将尝试下一个 cookie")
                elif is_browser_error:
                    print(f"[x_trending] 浏览器启动/导航超时，不标记 cookie 失败（非 cookie 问题）")
                    # 浏览器问题换 cookie 也没用，直接跳出
                    break
                else:
                    # 未知错误，谨慎标记
                    mark_cookie_failure(cookie, f"未知错误: {error_msg[:100]}")

                # 短暂等待后重试
                if attempt < max_retries:
                    print(f"[x_trending] 等待 3 秒后尝试下一个 cookie...")
                    await asyncio.sleep(3)

        if last_error:
            print(f"[x_trending] 所有 cookie 尝试完毕，最终失败: {last_error[:200]}")
        return False

    finally:
        # 无论成功失败，恢复配置
        config.CRAWLER_TYPE = original_crawler_type
        config.KEYWORDS = original_keywords
        config.X_TWITTER_MAX_POSTS = original_max_posts
        config.COOKIES = original_cookies


async def _crawl_with_playwright_direct(keywords: str = "") -> List[Dict[str, Any]]:
    """直接使用 Playwright 爬取热点（绕过 CDP browser 基础设施）

    当 XTwitterCrawler 的 CDP browser 启动失败时，使用此函数作为备用方案。
    直接启动 Playwright 浏览器，支持多关键词迭代搜索，累积并去重结果。
    """
    from api.services.cookie_pool_manager import (
        get_cookie_from_pool,
        mark_cookie_success,
        mark_cookie_failure,
        get_pool_summary,
    )

    pool_summary = get_pool_summary()
    max_retries = min(3, pool_summary.get("available", 1) or 1)
    if max_retries < 1:
        print("[x_trending] Cookie 池为空，无法启动直接爬取")
        return []

    if keywords:
        search_keywords = [keywords]
    else:
        search_keywords = FALLBACK_KEYWORDS[:10]

    tried_cookies = set()
    last_error = ""
    # 重置 cloudflare 标记（本次调用会重新设置）
    global _last_cloudflare_hit
    _last_cloudflare_hit = False

    for attempt in range(1, max_retries + 1):
        cookie = get_cookie_from_pool()
        if not cookie or cookie in tried_cookies:
            if not cookie:
                break
            if attempt > 1:
                break

        tried_cookies.add(cookie)
        print(f"[x_trending] 直接爬取 - 第 {attempt}/{max_retries} 次尝试，使用 cookie: {cookie[:30]}...")

        browser = None
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--no-first-run",
                        "--no-zygote",
                        "--disable-gpu",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                )

                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Upgrade-Insecure-Requests": "1",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                    },
                )

                cookie_list = []
                for part in cookie.split(";"):
                    part = part.strip()
                    if "=" in part:
                        key, value = part.split("=", 1)
                        cookie_list.append({"name": key.strip(), "value": value.strip(), "domain": ".x.com", "path": "/"})

                if cookie_list:
                    result = context.add_cookies(cookie_list)
                    if hasattr(result, '__await__'):
                        await result
                    print(f"[x_trending] 设置了 {len(cookie_list)} 个 cookies")

                page = await context.new_page()
                # 降低默认超时，避免单次 goto 卡死 60s
                page.set_default_timeout(15000)

                all_posts = {}
                # Cloudflare 命中后该 cookie 下所有关键词都会失败，提前结束避免无效重试
                cloudflare_hit = False

                for kw_idx, search_kw in enumerate(search_keywords, 1):
                    try:
                        if cloudflare_hit:
                            break
                        if len(all_posts) >= MAX_POSTS_PER_TOPIC:
                            print(f"[x_trending] 已获取 {MAX_POSTS_PER_TOPIC} 条帖子，提前结束")
                            break

                        # 用 f=top（热门）过滤，比默认 live 流更相关；URL 编码关键词
                        from urllib.parse import quote
                        search_url = f"https://x.com/search?q={quote(search_kw)}&src=typed_query&f=top"
                        print(f"[x_trending] 搜索关键词 {kw_idx}/{len(search_keywords)}: {search_kw}, URL: {search_url}")

                        # 单关键词整体超时保护，避免卡死整个采集
                        posts_before = len(all_posts)
                        try:
                            await asyncio.wait_for(
                                _search_one_keyword(page, search_url, all_posts),
                                timeout=_PER_KEYWORD_TIMEOUT,
                            )
                        except asyncio.TimeoutError:
                            print(f"[x_trending] 关键词 {search_kw} 超时({_PER_KEYWORD_TIMEOUT}s)，跳过")
                            continue
                        except Exception as e:
                            err = str(e)
                            if "cloudflare" in err.lower():
                                cloudflare_hit = True
                                _last_cloudflare_hit = True  # 供 crawl_trending 短路策略 3
                                print(f"[x_trending] 检测到 Cloudflare 挑战页，跳过剩余关键词")
                                break
                            print(f"[x_trending] 关键词 {search_kw} 搜索异常: {err[:150]}")
                            continue

                        added = len(all_posts) - posts_before
                        print(f"[x_trending] 关键词 {search_kw} 新增 {added} 条，累计 {len(all_posts)} 条")

                    except Exception as e:
                        print(f"[x_trending] 关键词 {search_kw} 处理失败: {e}")
                        continue

                await browser.close()

                posts = list(all_posts.values())[:MAX_POSTS_PER_TOPIC]

                if posts:
                    mark_cookie_success(cookie)
                print(f"[x_trending] 直接爬取成功，获取 {len(posts)} 条帖子")
                return posts

        except Exception as e:
            error_msg = str(e)
            last_error = error_msg
            print(f"[x_trending] 直接爬取第 {attempt} 次失败: {error_msg[:200]}")

            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

            is_cookie_error = (
                "login" in error_msg.lower()
                or "403" in error_msg
                or "401" in error_msg
                or "unauthorized" in error_msg.lower()
                or "cookie" in error_msg.lower()
            )

            if is_cookie_error:
                mark_cookie_failure(cookie, f"Cookie 失效: {error_msg[:100]}")
                print(f"[x_trending] Cookie 失效已标记")
            else:
                print(f"[x_trending] 非 cookie 错误，不标记失败")

            if attempt < max_retries:
                print(f"[x_trending] 等待 3 秒后尝试下一个 cookie...")
                await asyncio.sleep(3)

    if last_error:
        print(f"[x_trending] 直接爬取所有尝试完毕，最终失败: {last_error[:200]}")
    return []


async def _extract_hot_posts_from_db() -> List[Dict[str, Any]]:
    """从数据库提取热门帖子（按互动数排序）"""
    async with get_session() as session:
        stmt = (
            select(XTwitterPost)
            .order_by(desc(XTwitterPost.likes_count))
            .limit(50)
        )
        result = await session.execute(stmt)
        posts = result.scalars().all()

        def _to_int(s):
            try:
                return int(float(str(s).replace(",", "")))
            except Exception:
                return 0

        posts_sorted = sorted(posts, key=lambda p: _to_int(p.likes_count) + _to_int(p.retweets_count) * 2, reverse=True)

        extracted = []
        for p in posts_sorted[:MAX_TOPICS_PER_CRAWL]:
            extracted.append({
                "post_id": p.post_id,
                "post_url": p.post_url,
                "username": p.username,
                "nickname": p.nickname,
                "content": p.content,
                "likes_count": p.likes_count,
                "retweets_count": p.retweets_count,
                "replies_count": p.replies_count,
                "views_count": p.views_count,
                "created_at": p.created_at,
                "video_url": p.video_url,
                "image_url": p.image_urls[0] if p.image_urls else "",
            })

    return extracted


async def _save_trending_data(posts: List[Dict[str, Any]]):
    """将热点数据保存到数据库"""
    if not posts:
        return

    now = int(time.time())
    
    async with get_session() as session:
        for idx, post in enumerate(posts, 1):
            topic_name = post["content"][:50] if post["content"] else f"Untitled_{idx}"

            topic_existing = (await session.execute(
                select(XTwitterTrendingTopic).where(XTwitterTrendingTopic.topic == topic_name)
            )).scalar_one_or_none()

            if topic_existing:
                topic_existing.rank = idx
                topic_existing.tweet_count = str(post.get("likes_count", "0"))
                topic_existing.crawl_ts = now
                topic_existing.last_modify_ts = now
            else:
                new_topic = XTwitterTrendingTopic(
                    topic=topic_name,
                    topic_url=post["post_url"] or "",
                    rank=idx,
                    tweet_count=str(post.get("likes_count", "0")),
                    is_hashtag=0,
                    crawl_ts=now,
                    add_ts=now,
                    last_modify_ts=now,
                )
                session.add(new_topic)

            post_existing = (await session.execute(
                select(XTwitterTrendingPost).where(XTwitterTrendingPost.post_id == post["post_id"])
            )).scalar_one_or_none()

            if post_existing:
                post_existing.likes_count = post["likes_count"]
                post_existing.retweets_count = post["retweets_count"]
                post_existing.replies_count = post["replies_count"]
                post_existing.views_count = post["views_count"]
                post_existing.crawl_ts = now
                post_existing.last_modify_ts = now
            else:
                created_at_int = 0
                if post.get("created_at"):
                    try:
                        import datetime
                        dt = datetime.datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
                        created_at_int = int(dt.timestamp())
                    except Exception:
                        created_at_int = 0
                
                new_post = XTwitterTrendingPost(
                    trending_topic_id=0,
                    topic=topic_name,
                    post_id=post["post_id"],
                    post_url=post["post_url"],
                    username=post["username"],
                    nickname=post["nickname"],
                    content=post["content"],
                    likes_count=post["likes_count"],
                    retweets_count=post["retweets_count"],
                    replies_count=post["replies_count"],
                    views_count=post["views_count"],
                    created_at=created_at_int,
                    video_url=post["video_url"],
                    image_url=post["image_url"],
                    crawl_ts=now,
                    add_ts=now,
                    last_modify_ts=now,
                )
                session.add(new_post)

        await session.commit()

    await _cleanup_old_data()
    print(f"[x_trending] 保存了 {len(posts)} 条热点数据")


async def _cleanup_old_data():
    """清理过期数据（保留历史数据，不再自动清理）"""
    print("[x_trending] 历史数据保留模式，不执行清理")
    return


async def crawl_trending():
    """执行一次热点采集（多策略）

    策略链优化：
    - 策略1：直接 Playwright 爬取（多关键词，主策略）
    - 策略2：数据库提取历史热点（兜底，秒级）
    - 策略3：仅当策略1 非 Cloudflare 失败时，才用单关键词重试（避免 CF 命中后串行卡死）
    - 策略4：已有爬虫接口（最后备用）
    整体超时保护：120s，避免预热卡死
    """
    print("[x_trending] 开始热点采集...")

    try:
        await asyncio.wait_for(_crawl_trending_inner(), timeout=120.0)
    except asyncio.TimeoutError:
        print(f"[x_trending] 热点采集总超时(120s)，提前结束（不影响服务运行）")


async def _crawl_trending_inner():
    """crawl_trending 的内部实现，带总超时保护"""
    global _last_cloudflare_hit
    posts = []

    # 策略1: 使用直接 Playwright 爬取（首要策略，绕过 CDP）
    print("[x_trending] 使用直接 Playwright 爬取（首要策略）")
    posts = await _crawl_with_playwright_direct()

    # 策略2: 如果主策略失败，从数据库提取
    if not posts:
        print("[x_trending] 直接爬取失败，尝试从数据库提取热点")
        posts = await _extract_hot_posts_from_db()

    # 策略3: 如果数据库也没有，且策略1 不是 Cloudflare 拦截，使用单关键词重试
    # Cloudflare 命中时跳过：CF 拦截与关键词无关，重试 5 个关键词只会卡死预热
    if not posts and not _last_cloudflare_hit:
        print("[x_trending] 数据库无热点，使用单关键词直接爬取")
        for keywords in FALLBACK_KEYWORDS[:3]:  # 从 5 缩减到 3，减少串行卡时
            posts = await _crawl_with_playwright_direct(keywords)
            if posts:
                break
            if _last_cloudflare_hit:
                print("[x_trending] 单关键词重试期间命中 Cloudflare，停止重试")
                break
    elif not posts and _last_cloudflare_hit:
        print("[x_trending] 策略1 命中 Cloudflare，跳过策略3（单关键词重试无意义）")

    # 策略4: 如果都失败，尝试已有的爬虫爬取（作为最后的备用）
    if not posts and not _last_cloudflare_hit:
        print("[x_trending] 尝试已有的爬虫爬取（备用策略）")
        success = await _crawl_with_existing_api()
        if success:
            posts = await _extract_hot_posts_from_db()

    # 策略5: 如果都失败，返回空结果
    if posts:
        print(f"[x_trending] 获取到 {len(posts)} 条帖子，开始保存...")
        try:
            await _save_trending_data(posts)
            print(f"[x_trending] 保存完成")
        except Exception as e:
            print(f"[x_trending] 保存失败: {e}")
    else:
        print("[x_trending] 所有策略均失败，无法获取热点数据")

    print("[x_trending] 热点采集完成")


async def get_trending_topics(limit: int = 10) -> List[Dict[str, Any]]:
    """获取热点话题列表"""
    async with get_session() as session:
        stmt = (
            select(XTwitterTrendingTopic)
            .order_by(desc(XTwitterTrendingTopic.crawl_ts), XTwitterTrendingTopic.rank)
            .limit(limit)
        )
        result = await session.execute(stmt)
        topics = result.scalars().all()

        items = []
        for t in topics:
            items.append({
                "id": t.id,
                "topic": t.topic,
                "topic_url": t.topic_url,
                "rank": t.rank,
                "tweet_count": t.tweet_count,
                "is_hashtag": bool(t.is_hashtag),
                "crawl_ts": t.crawl_ts,
            })

    return items


async def get_trending_posts(topic_id: Optional[int] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """获取热点帖子列表"""
    async with get_session() as session:
        stmt = select(XTwitterTrendingPost)

        if topic_id:
            stmt = stmt.where(XTwitterTrendingPost.trending_topic_id == topic_id)

        stmt = stmt.order_by(desc(XTwitterTrendingPost.crawl_ts)).limit(limit)
        result = await session.execute(stmt)
        posts = result.scalars().all()

        items = []
        for p in posts:
            items.append({
                "id": p.id,
                "topic": p.topic,
                "post_id": p.post_id,
                "post_url": p.post_url,
                "username": p.username,
                "nickname": p.nickname,
                "content": p.content,
                "likes_count": p.likes_count,
                "retweets_count": p.retweets_count,
                "replies_count": p.replies_count,
                "views_count": p.views_count,
                "video_url": p.video_url,
                "image_url": p.image_url,
                "created_at": p.created_at,
                "crawl_ts": p.crawl_ts,
            })

    return items


async def get_trending_stats() -> Dict[str, Any]:
    """获取热点统计数据"""
    async with get_session() as session:
        topic_count = (await session.execute(select(func.count(XTwitterTrendingTopic.id)))).scalar() or 0
        post_count = (await session.execute(select(func.count(XTwitterTrendingPost.id)))).scalar() or 0

        latest_topic = (await session.execute(
            select(XTwitterTrendingTopic).order_by(desc(XTwitterTrendingTopic.crawl_ts)).limit(1)
        )).scalar_one_or_none()

        total_x_posts = (await session.execute(select(func.count(XTwitterPost.id)))).scalar() or 0

    return {
        "topic_count": topic_count,
        "post_count": post_count,
        "last_crawl_ts": latest_topic.crawl_ts if latest_topic else 0,
        "is_running": _trending_running,
        "total_x_posts": total_x_posts,
    }


def start_trending_monitor():
    """启动定时热点采集"""
    global _trending_task
    if _trending_task is None or _trending_task.done():
        _trending_task = asyncio.create_task(_crawl_loop())
        print(f"[x_trending] 定时采集已启动，间隔 {TRENDING_CRAWL_INTERVAL}s")


async def stop_trending_monitor():
    """停止定时热点采集"""
    global _trending_task, _trending_running
    if _trending_task and not _trending_task.done():
        _trending_task.cancel()
        try:
            await _trending_task
        except asyncio.CancelledError:
            pass
    _trending_task = None
    _trending_running = False
    print("[x_trending] 定时采集已停止")


def get_trending_monitor_status() -> Dict[str, Any]:
    """获取热点采集监控状态"""
    return {
        "running": _trending_running,
        "interval_seconds": TRENDING_CRAWL_INTERVAL,
        "max_topics_per_crawl": MAX_TOPICS_PER_CRAWL,
        "max_posts_per_topic": MAX_POSTS_PER_TOPIC,
    }


async def _crawl_loop():
    """定时采集循环"""
    global _trending_running
    _trending_running = True

    while True:
        try:
            await crawl_trending()
        except Exception as e:
            print(f"[x_trending] loop error: {e}")

        await asyncio.sleep(TRENDING_CRAWL_INTERVAL)
