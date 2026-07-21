# -*- coding: utf-8 -*-
"""
X Twitter 工作台 - 评论回复监控服务

后台定时任务：
1. 查询所有 monitoring=1 的已发评论 → 监控评论收到的回复
2. 查询所有 monitoring=1 的帖子 → 监控帖子下的所有评论
3. 通过浏览器访问，提取回复/评论
4. 把新回复写入数据库
5. 对新回复调用 AI Agent 生成自动回复并发送
"""
import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_session import get_session
from database.models import XTwitterSentComment, XTwitterReply, XTwitterMonitoredPost, XTwitterPostReply


# 模块级 logger(统一日志格式,支持日志级别控制和文件输出)
# 自带 handler 确保日志可见,不依赖全局 logging 配置,不影响 uvicorn
logger = logging.getLogger("x_workbench_monitor")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # 避免通过 root logger 重复输出


# 轮询间隔（秒）
CHECK_INTERVAL = int(os.getenv("X_WORKBENCH_REPLY_CHECK_INTERVAL", "180"))
# 每日 AI 回复上限
DAILY_LIMIT = int(os.getenv("X_WORKBENCH_REPLY_DAILY_LIMIT", "100"))
# 单次轮询最多检查多少条已发评论
BATCH_SIZE = 10
# 已发评论多久后停止监控（默认 7 天）
MONITOR_TTL = 7 * 24 * 3600
# 浏览器并发上限(避免同时启动太多浏览器实例导致内存爆炸)
_BROWSER_CONCURRENCY = int(os.getenv("X_WORKBENCH_BROWSER_CONCURRENCY", "3"))
# AI 回复并发上限(避免触发 AI 速率限制)
_AI_REPLY_CONCURRENCY = int(os.getenv("X_WORKBENCH_AI_REPLY_CONCURRENCY", "2"))


# 全局监控任务句柄
_monitor_task: Optional[asyncio.Task] = None
# 是否被显式停止(用户主动 stop_monitor 时设为 True,watchdog 不会自动重启)
_explicitly_stopped: bool = True
# watchdog 重启间隔(秒)
_RESTART_DELAY = 5
# watchdog 最大连续重启失败次数(避免无限重试)
_max_restart_failures = 0


async def start_monitor():
    """启动后台监控任务（幂等，重复调用不会启动多个）

    内置 watchdog:任务异常退出时会自动重启,保证监控服务持续运行,
    除非用户显式调用 stop_monitor()。

    Returns:
        bool: True 表示已启动或已在运行;False 表示启动失败
    """
    global _monitor_task, _explicitly_stopped, _max_restart_failures
    if _monitor_task and not _monitor_task.done():
        return True
    try:
        _explicitly_stopped = False  # 清除"已停止"标志,允许 watchdog 自动重启
        _max_restart_failures = 0
        _monitor_task = asyncio.create_task(_watchdog_loop())
        logger.info(f"已启动(带 watchdog 自动重启),间隔 {CHECK_INTERVAL}s,每日 AI 回复上限 {DAILY_LIMIT}")
        return True
    except Exception as e:
        logger.error(f"启动监控失败: {e}")
        return False


def is_monitor_running() -> bool:
    """检查监控任务是否在运行"""
    return _monitor_task is not None and not _monitor_task.done()


async def _watchdog_loop():
    """watchdog 包装循环:监控主循环异常退出后自动重启

    策略:
    - 调用 _monitor_loop(内部是 while True,正常情况下不会退出)
    - 如果 _monitor_loop 异常退出(返回或抛异常),且未被显式停止,等待 5s 重启
    - 连续重启失败超过 10 次则放弃(避免无限循环,可通过 start_monitor 重置)
    """
    global _max_restart_failures
    while not _explicitly_stopped:
        try:
            await _monitor_loop()
            # _monitor_loop 正常情况下不会返回(while True);返回说明异常退出
            if _explicitly_stopped:
                break
            logger.warning("监控主循环意外返回,准备重启...")
        except asyncio.CancelledError:
            # 显式 cancel(stop_monitor 调用),正常退出
            logger.info("监控任务被 cancel,退出 watchdog")
            raise
        except Exception as e:
            logger.error(f"监控主循环异常退出: {e}")

        if _explicitly_stopped:
            break

        _max_restart_failures += 1
        if _max_restart_failures > 10:
            logger.error(f"监控连续重启失败 {_max_restart_failures} 次,放弃重启(可手动 start_monitor 重置)")
            return

        logger.warning(f"监控将在 {_RESTART_DELAY}s 后自动重启(第 {_max_restart_failures} 次重启)...")
        try:
            await asyncio.sleep(_RESTART_DELAY)
        except asyncio.CancelledError:
            raise


async def stop_monitor():
    """停止后台监控任务"""
    global _monitor_task, _explicitly_stopped
    _explicitly_stopped = True  # 标记为显式停止,watchdog 不会自动重启
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
    _monitor_task = None
    # 关闭共享浏览器实例,释放资源
    await _close_shared_browser()
    logger.info("已停止")


async def _monitor_loop():
    """监控主循环"""
    while True:
        try:
            await _check_all_sent_comments()
            await _check_all_monitored_posts()
        except Exception as e:
            logger.error(f"loop error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


async def _check_all_sent_comments():
    """检查所有正在监控的已发评论

    优化:用 asyncio.gather + Semaphore 并发检查多条评论
    (浏览器抓取是 IO 密集型,串行会浪费时间),并在所有检查完成后
    用一次事务批量更新 last_check_ts。
    
    进度日志:记录每个阶段的执行时间,便于性能分析。
    """
    start_time = time.time()
    now = int(time.time())
    cutoff = now - MONITOR_TTL

    async with get_session() as session:
        stmt = (
            select(XTwitterSentComment)
            .where(and_(
                XTwitterSentComment.monitoring == 1,
                XTwitterSentComment.sent_status == "success",
                XTwitterSentComment.sent_at >= cutoff,
            ))
            .order_by(XTwitterSentComment.last_check_ts.asc())
            .limit(BATCH_SIZE)
        )
        result = await session.execute(stmt)
        sent_comments = result.scalars().all()

    query_time = time.time() - start_time
    logger.info(f"查询已发评论({len(sent_comments)}条)耗时: {query_time:.2f}s")

    if not sent_comments:
        return

    logger.info(f"并发检查 {len(sent_comments)} 条已发评论的回复(并发上限 {_BROWSER_CONCURRENCY})")

    sem = asyncio.Semaphore(_BROWSER_CONCURRENCY)

    async def _check_with_sem(sc: XTwitterSentComment):
        async with sem:
            try:
                await _check_one_sent_comment(sc)
            except Exception as e:
                logger.error(f"检查评论 {sc.id} 失败: {e}")

    check_start = time.time()
    await asyncio.gather(*[_check_with_sem(sc) for sc in sent_comments])
    check_time = time.time() - check_start
    logger.info(f"完成 {len(sent_comments)} 条评论检查,耗时: {check_time:.2f}s")

    async with get_session() as session:
        ids_to_update = [sc.id for sc in sent_comments]
        await session.execute(
            update(XTwitterSentComment)
            .where(XTwitterSentComment.id.in_(ids_to_update))
            .values(last_check_ts=now)
        )
        await session.execute(
            update(XTwitterSentComment)
            .where(and_(
                XTwitterSentComment.id.in_(ids_to_update),
                XTwitterSentComment.sent_at < cutoff,
            ))
            .values(monitoring=0)
        )
        await session.commit()

    update_time = time.time() - check_start - check_time
    total_time = time.time() - start_time
    logger.info(f"更新检查时间({len(ids_to_update)}条)耗时: {update_time:.2f}s, 总耗时: {total_time:.2f}s")


async def _check_one_sent_comment(sc: XTwitterSentComment):
    """检查单条已发评论的回复"""
    if sc.sent_status != "success":
        return

    replies = []
    our_comment_id = ""

    if sc.comment_url:
        replies = await _fetch_replies_for_post(sc.comment_url)
        if replies:
            our_comment_id = sc.comment_url.split("/status/")[-1].split("?")[0].split("#")[0]

    if not replies and sc.post_url:
        replies = await _fetch_replies_for_post(sc.post_url)
        if replies:
            for r in replies:
                if sc.comment_content[:20] in r.get("content", ""):
                    our_comment_id = r.get("reply_id", "")
                    break

    if not replies:
        return

    now = int(time.time())
    new_replies_count = 0

    async with get_session() as session:
        existing_stmt = select(XTwitterReply.reply_id).where(
            XTwitterReply.sent_comment_id == sc.id
        )
        existing_result = await session.execute(existing_stmt)
        existing_ids = {row[0] for row in existing_result.all()}

        for r in replies:
            reply_id = r.get("reply_id", "")
            if not reply_id or reply_id in existing_ids:
                continue
            if reply_id == our_comment_id:
                continue
            if r.get("username") and r.get("username") == await _get_my_username_async():
                continue

            new_reply = XTwitterReply(
                sent_comment_id=sc.id,
                post_id=sc.post_id,
                reply_id=reply_id,
                reply_url=r.get("reply_url", ""),
                replier_user_id=r.get("user_id", ""),
                replier_username=r.get("username", ""),
                replier_nickname=r.get("nickname", ""),
                replier_avatar=r.get("avatar", ""),
                reply_content=r.get("content", ""),
                reply_likes_count=str(r.get("likes_count", "0")),
                reply_created_at=r.get("created_at", 0),
                auto_reply_status="pending",
                add_ts=now,
                last_modify_ts=now,
            )
            session.add(new_reply)
            new_replies_count += 1

        if new_replies_count > 0:
            db_obj = await session.get(XTwitterSentComment, sc.id)
            if db_obj:
                db_obj.reply_count = (db_obj.reply_count or 0) + new_replies_count
        await session.commit()

    if new_replies_count > 0:
        logger.info(f"评论 {sc.id} 收到 {new_replies_count} 条新回复")
        # 触发通知(失败不影响主流程)
        try:
            from api.services.x_workbench_notifier import notify_event, EVENT_NEW_REPLY
            await notify_event(
                event=EVENT_NEW_REPLY,
                title=f"收到 {new_replies_count} 条新回复",
                content=f"您在 @{sc.post_username} 下的评论收到 {new_replies_count} 条新回复,系统将自动 AI 回复。",
                extra={
                    "评论ID": sc.id,
                    "推文作者": f"@{sc.post_username}",
                    "评论摘要": (sc.comment_content or "")[:80],
                    "新回复数": new_replies_count,
                    "评论URL": sc.comment_url or "",
                },
            )
        except Exception as e:
            logger.debug(f"触发 new_reply 通知失败(忽略): {e}")
        await _auto_reply_to_new_replies(sc.id)


_MY_USERNAME = ""


async def _get_my_username_async() -> str:
    """获取当前登录用户名(异步版,从数据库已发评论的 comment_url 提取)

    X.com cookie 中 twid 只含数字 user ID,无法直接拿到用户名。
    最可靠的方式:查询已发评论的 comment_url(格式 https://x.com/USERNAME/status/ID),
    从中解析用户名。结果缓存在内存,避免重复查库。
    """
    global _MY_USERNAME
    if _MY_USERNAME:
        return _MY_USERNAME

    # 1. 先尝试从环境变量直接配置(可选,优先级最高)
    env_username = os.getenv("X_TWITTER_MY_USERNAME", "").strip().lstrip("@")
    if env_username:
        _MY_USERNAME = env_username
        return _MY_USERNAME

    # 2. 从数据库已发评论的 comment_url 提取
    try:
        async with get_session() as session:
            stmt = (
                select(XTwitterSentComment.comment_url)
                .where(
                    XTwitterSentComment.comment_url.isnot(None),
                    XTwitterSentComment.comment_url != "",
                    XTwitterSentComment.comment_url.like("https://x.com/%/status/%"),
                )
                .order_by(XTwitterSentComment.id.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.first()
            if row and row[0]:
                username = _extract_username_from_url(row[0])
                if username:
                    _MY_USERNAME = username
                    logger.info(f"已从已发评论提取当前用户名: @{username}")
                    return _MY_USERNAME
    except Exception as e:
        logger.error(f"从数据库提取用户名失败: {e}")

    return ""


def _get_my_username() -> str:
    """获取当前登录用户名(同步版,仅返回缓存值)

    注意:此函数只返回已缓存的用户名,不会触发数据库查询。
    首次调用应使用 _get_my_username_async() 进行初始化。
    """
    return _MY_USERNAME


def _extract_username_from_url(url: str) -> str:
    """从 X.com URL 中提取用户名

    示例: https://x.com/johndoe/status/1234567890 -> johndoe
    """
    if not url:
        return ""
    try:
        # 去掉协议和域名
        if "://x.com/" in url:
            path = url.split("://x.com/", 1)[1]
        elif "://twitter.com/" in url:
            path = url.split("://twitter.com/", 1)[1]
        else:
            return ""
        # path = johndoe/status/1234567890
        parts = path.split("/")
        if parts and parts[0]:
            return parts[0].strip()
    except Exception:
        pass
    return ""


def _extract_username_from_cookies(cookies_str: str) -> str:
    """从 cookie 字符串中提取用户名(已废弃,保留向后兼容)

    X.com cookie 中 twid 只含数字 user ID(格式 u=1234567890),
    无法直接拿到用户名。此函数仅用于检测 cookie 是否包含 twid,
    实际用户名提取请使用 _get_my_username_async()。
    """
    for pair in cookies_str.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        if k == "twid":
            # twid 存在说明 cookie 有效,但无法提取用户名
            return ""
    return ""


async def _fetch_replies_for_post(post_url: str) -> List[Dict[str, Any]]:
    """通过浏览器抓取推文/评论下的回复"""
    return await _fetch_replies_via_browser(post_url)


# ==================== 浏览器实例池(共享单例) ====================
# 避免每次抓取都启动新浏览器(每次启动 1-3s 开销),改为共享一个浏览器实例,
# 每次抓取只创建独立的 context(保持 cookie 隔离),抓取完关闭 context。
_shared_browser = None
_shared_playwright = None
_browser_lock = asyncio.Lock()


async def _get_shared_browser():
    """获取共享的浏览器实例(单例,线程安全)

    如果浏览器未启动或已断开连接,则重新启动。
    Returns: (browser, playwright) 元组
    """
    global _shared_browser, _shared_playwright
    # 快速路径:已启动且连接正常
    if _shared_browser and _shared_browser.is_connected():
        return _shared_browser, _shared_playwright

    async with _browser_lock:
        # double-check:拿到锁后再检查一次
        if _shared_browser and _shared_browser.is_connected():
            return _shared_browser, _shared_playwright

        # 关闭旧实例(可能已断开)
        if _shared_playwright:
            try:
                await _shared_playwright.stop()
            except Exception:
                pass
            _shared_browser = None
            _shared_playwright = None

        # 启动新实例
        from playwright.async_api import async_playwright
        _shared_playwright = await async_playwright().start()
        _shared_browser = await _shared_playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        logger.info("已启动共享浏览器实例(复用模式)")
        return _shared_browser, _shared_playwright


async def _close_shared_browser():
    """关闭共享浏览器实例(监控停止时调用)"""
    global _shared_browser, _shared_playwright
    if _shared_playwright:
        try:
            await _shared_playwright.stop()
            logger.info("已关闭共享浏览器实例")
        except Exception:
            pass
    _shared_browser = None
    _shared_playwright = None


async def _fetch_replies_via_browser(post_url: str) -> List[Dict[str, Any]]:
    """浏览器方案：访问推文/评论页面解析回复

    优化:复用共享浏览器实例,只创建独立 context(保持隔离)。
    避免每次调用都启动新浏览器(节省 1-3s/次)。
    
    智能等待策略:
    - 使用 wait_for_selector 等待推文元素出现,替代固定 sleep(4)
    - 滚动后等待新内容加载(最多 3 次,每次最多 5 秒)
    - 超时时间可配置,避免无限等待
    
    请求拦截优化:
    - 阻止图片、样式表、字体等非必要资源加载
    - 仅允许 HTML、JS、JSON 请求,大幅提升页面加载速度
    """
    cookies_str = os.getenv("X_TWITTER_COOKIES", "")
    if not cookies_str or "auth_token" not in cookies_str:
        return []

    from api.services.x_comment_sender import _parse_cookies
    cookie_list = _parse_cookies(cookies_str)

    context = None
    try:
        browser, _ = await _get_shared_browser()
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        
        await context.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ("image", "stylesheet", "font", "media") 
            else route.continue_())

        await context.add_cookies(cookie_list)
        page = await context.new_page()

        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        
        try:
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        except Exception:
            logger.warning(f"等待推文元素超时,页面可能未正确加载: {post_url}")
            return []

        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 1000)")
            try:
                await page.wait_for_selector('article[data-testid="tweet"]', timeout=5000)
            except Exception:
                pass

        replies = await page.evaluate("""() => {
            const results = [];
            const articles = document.querySelectorAll('article[data-testid="tweet"]');
            articles.forEach((article, idx) => {
                if (idx === 0) return;
                const permalink = article.querySelector('a[href*="/status/"]');
                if (!permalink) return;
                const href = permalink.getAttribute('href');
                if (!href) return;
                const parts = href.replace(/^\\//, '').split('/status/');
                if (parts.length !== 2) return;
                const username = parts[0];
                const status_id = parts[1].split('?')[0].split('#')[0].split('/')[0];
                const reply_url = `https://x.com/${parts[0]}/status/${status_id}`;
                
                const content_elem = article.querySelector('div[data-testid="tweetText"]');
                const content = content_elem ? content_elem.innerText : '';
                if (!content.trim()) return;
                
                const avatar_elem = article.querySelector('img[src*="profile_images"]');
                const avatar = avatar_elem ? avatar_elem.getAttribute('src') : '';
                
                results.push({
                    reply_id: status_id,
                    reply_url: reply_url,
                    username: username,
                    nickname: '',
                    avatar: avatar,
                    content: content,
                    user_id: '',
                    likes_count: '0',
                    created_at: 0,
                });
            });
            return results;
        }""")

        return replies
    except Exception as e:
        logger.error(f"浏览器抓取回复失败: {e}")
        global _shared_browser
        if _shared_browser and not _shared_browser.is_connected():
            _shared_browser = None
        return []
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass


async def _auto_reply_to_new_replies(sent_comment_id: int):
    """对新增的回复进行 AI 自动回复

    优化:用 asyncio.gather + Semaphore 并发处理多条回复
    (AI 生成 + 浏览器发送是 IO 密集型),用原子 SQL UPDATE
    替代 read-modify-write 避免 auto_replied_count 竞态。
    """
    from api.services import ai_agent_client
    from api.services.x_comment_sender import reply_to_comment

    # 检查每日上限
    today_start = int(time.time()) - (int(time.time()) % 86400)
    async with get_session() as session:
        stmt = select(XTwitterReply).where(and_(
            XTwitterReply.sent_comment_id == sent_comment_id,
            XTwitterReply.auto_reply_status == "pending",
        ))
        result = await session.execute(stmt)
        pending_replies = result.scalars().all()

        if not pending_replies:
            return

        # 获取父评论信息
        sc = await session.get(XTwitterSentComment, sent_comment_id)
        if not sc:
            return

        # 今日已 AI 回复数
        count_stmt = select(func.count(XTwitterReply.id)).where(
            XTwitterReply.auto_replied_at >= today_start,
            XTwitterReply.auto_reply_status == "sent",
        )
        count_result = await session.execute(count_stmt)
        today_count = count_result.scalar() or 0

    remaining_quota = max(0, DAILY_LIMIT - today_count)
    if remaining_quota == 0:
        logger.warning(f"今日 AI 回复已达上限 {DAILY_LIMIT}，跳过")
        return

    # AI 服务冷却检查
    if not ai_agent_client._check_ai_cooldown():
        logger.warning(f"AI 服务暂时不可用,冷却中,跳过本次 AI 回复")
        return

    to_process = pending_replies[:remaining_quota]
    logger.info(f"并发对 {len(to_process)} 条新回复进行 AI 回复（剩余配额 {remaining_quota}, 并发上限 {_AI_REPLY_CONCURRENCY}）")

    # 拍照父评论信息(避免并发访问同一 ORM 对象)
    sc_snapshot = {
        "post_id": sc.post_id,
        "post_content": sc.post_content or "",
        "comment_content": sc.comment_content or "",
    }

    sem = asyncio.Semaphore(_AI_REPLY_CONCURRENCY)

    async def _process_one_reply(reply: XTwitterReply):
        async with sem:
            try:
                # AI 生成回复
                ai_reply = await ai_agent_client.generate_auto_reply(
                    post_content=sc_snapshot["post_content"],
                    my_comment=sc_snapshot["comment_content"],
                    reply_content=reply.reply_content or "",
                    replier=reply.replier_username or "",
                )

                # 真实发送回复
                send_result = await reply_to_comment(
                    comment_url=reply.reply_url,
                    content=ai_reply,
                    real_send=True,
                )

                now = int(time.time())
                success = send_result.get("success", False)
                async with get_session() as session:
                    if success:
                        # 原子更新 auto_replied_count(避免并发竞态)
                        await session.execute(
                            update(XTwitterSentComment)
                            .where(XTwitterSentComment.id == sent_comment_id)
                            .values(auto_replied_count=XTwitterSentComment.auto_replied_count + 1)
                        )
                    # 更新回复记录(每个 reply 独立行,无竞态)
                    db_reply = await session.get(XTwitterReply, reply.id)
                    if db_reply:
                        db_reply.auto_reply_status = "sent" if success else "failed"
                        db_reply.auto_reply_content = ai_reply
                        db_reply.auto_reply_url = send_result.get("comment_url", "") if success else ""
                        db_reply.auto_replied_at = now if success else 0
                        db_reply.last_modify_ts = now
                    await session.commit()

                # WebSocket 推送
                try:
                    from api.routers.websocket import notify_x_twitter_reply, notify_x_twitter_reply_sent
                    await notify_x_twitter_reply(
                        post_id=sc_snapshot["post_id"],
                        comment_url=reply.reply_url,
                        reply_content=reply.reply_content[:200],
                        replied_by=reply.replier_username,
                    )
                    await notify_x_twitter_reply_sent(
                        post_id=sc_snapshot["post_id"],
                        comment_url=reply.reply_url,
                        reply_content=ai_reply[:200],
                    )
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"AI 回复失败 reply_id={reply.id}: {e}")
                async with get_session() as session:
                    db_reply = await session.get(XTwitterReply, reply.id)
                    if db_reply:
                        db_reply.auto_reply_status = "failed"
                        db_reply.last_modify_ts = int(time.time())
                        await session.commit()
                # 触发回复失败通知(失败不影响主流程)
                try:
                    from api.services.x_workbench_notifier import notify_event, EVENT_REPLY_FAILED
                    await notify_event(
                        event=EVENT_REPLY_FAILED,
                        title="AI 自动回复失败",
                        content=f"对 @{reply.replier_username} 的回复进行 AI 自动回复时失败: {e}",
                        extra={
                            "父评论ID": sent_comment_id,
                            "回复ID": reply.id,
                            "回复者": f"@{reply.replier_username}",
                            "回复摘要": (reply.reply_content or "")[:80],
                            "错误": str(e)[:200],
                            "回复URL": reply.reply_url or "",
                        },
                    )
                except Exception as ne:
                    logger.debug(f"触发 reply_failed 通知失败(忽略): {ne}")

    await asyncio.gather(*[_process_one_reply(r) for r in to_process])


async def get_monitor_status() -> Dict[str, Any]:
    """获取监控状态"""
    global _monitor_task
    return {
        "running": _monitor_task is not None and not _monitor_task.done(),
        "check_interval": CHECK_INTERVAL,
        "daily_limit": DAILY_LIMIT,
        "batch_size": BATCH_SIZE,
        "monitor_ttl_days": MONITOR_TTL // 86400,
    }


# ==================== 帖子监控相关函数 ====================

async def _check_all_monitored_posts():
    """检查所有正在监控的帖子

    优化:用 asyncio.gather + Semaphore 并发检查,批量更新 last_check_ts。
    
    进度日志:记录每个阶段的执行时间,便于性能分析。
    """
    start_time = time.time()
    now = int(time.time())
    cutoff = now - MONITOR_TTL

    async with get_session() as session:
        stmt = (
            select(XTwitterMonitoredPost)
            .where(and_(
                XTwitterMonitoredPost.monitoring == 1,
                XTwitterMonitoredPost.add_ts >= cutoff,
            ))
            .order_by(XTwitterMonitoredPost.last_check_ts.asc())
            .limit(BATCH_SIZE)
        )
        result = await session.execute(stmt)
        monitored_posts = result.scalars().all()

    query_time = time.time() - start_time
    logger.info(f"查询监控帖子({len(monitored_posts)}条)耗时: {query_time:.2f}s")

    if not monitored_posts:
        return

    logger.info(f"并发检查 {len(monitored_posts)} 个监控帖子的评论(并发上限 {_BROWSER_CONCURRENCY})")

    sem = asyncio.Semaphore(_BROWSER_CONCURRENCY)

    async def _check_with_sem(mp: XTwitterMonitoredPost):
        async with sem:
            try:
                await _check_one_monitored_post(mp)
            except Exception as e:
                logger.error(f"检查帖子 {mp.id} 失败: {e}")

    check_start = time.time()
    await asyncio.gather(*[_check_with_sem(mp) for mp in monitored_posts])
    check_time = time.time() - check_start
    logger.info(f"完成 {len(monitored_posts)} 个帖子检查,耗时: {check_time:.2f}s")

    async with get_session() as session:
        ids_to_update = [mp.id for mp in monitored_posts]
        await session.execute(
            update(XTwitterMonitoredPost)
            .where(XTwitterMonitoredPost.id.in_(ids_to_update))
            .values(last_check_ts=now)
        )
        await session.execute(
            update(XTwitterMonitoredPost)
            .where(and_(
                XTwitterMonitoredPost.id.in_(ids_to_update),
                XTwitterMonitoredPost.add_ts < cutoff,
            ))
            .values(monitoring=0)
        )
        await session.commit()

    update_time = time.time() - check_start - check_time
    total_time = time.time() - start_time
    logger.info(f"更新检查时间({len(ids_to_update)}条)耗时: {update_time:.2f}s, 总耗时: {total_time:.2f}s")


async def _check_one_monitored_post(mp: XTwitterMonitoredPost):
    """检查单个监控帖子的评论"""
    if not mp.post_url:
        return

    comments = await _fetch_comments_for_post(mp.post_url)
    if not comments:
        return

    now = int(time.time())
    new_comments_count = 0

    async with get_session() as session:
        existing_stmt = select(XTwitterPostReply.comment_id).where(
            XTwitterPostReply.monitored_post_id == mp.id
        )
        existing_result = await session.execute(existing_stmt)
        existing_ids = {row[0] for row in existing_result.all()}

        my_username = await _get_my_username_async()

        for c in comments:
            comment_id = c.get("comment_id", "")
            if not comment_id or comment_id in existing_ids:
                continue
            if c.get("username") and c.get("username") == my_username:
                continue

            new_comment = XTwitterPostReply(
                monitored_post_id=mp.id,
                post_id=mp.post_id,
                comment_id=comment_id,
                comment_url=c.get("comment_url", ""),
                commenter_user_id=c.get("user_id", ""),
                commenter_username=c.get("username", ""),
                commenter_nickname=c.get("nickname", ""),
                commenter_avatar=c.get("avatar", ""),
                comment_content=c.get("content", ""),
                comment_likes_count=str(c.get("likes_count", "0")),
                comment_created_at=c.get("created_at", 0),
                auto_reply_status="pending",
                add_ts=now,
                last_modify_ts=now,
            )
            session.add(new_comment)
            new_comments_count += 1

        if new_comments_count > 0:
            db_obj = await session.get(XTwitterMonitoredPost, mp.id)
            if db_obj:
                db_obj.total_comments = (db_obj.total_comments or 0) + new_comments_count
        await session.commit()

    if new_comments_count > 0:
        logger.info(f"帖子 {mp.id} 收到 {new_comments_count} 条新评论")
        await _auto_reply_to_post_comments(mp.id)


async def _fetch_comments_for_post(post_url: str) -> List[Dict[str, Any]]:
    """通过浏览器抓取帖子下的所有评论"""
    return await _fetch_replies_via_browser(post_url)


async def _auto_reply_to_post_comments(monitored_post_id: int):
    """对帖子下的新评论进行 AI 自动回复

    优化:用 asyncio.gather + Semaphore 并发处理,用原子 SQL UPDATE
    替代 read-modify-write 避免 auto_replied_count 竞态。
    """
    from api.services import ai_agent_client
    from api.services.x_comment_sender import reply_to_comment

    today_start = int(time.time()) - (int(time.time()) % 86400)
    async with get_session() as session:
        stmt = select(XTwitterPostReply).where(and_(
            XTwitterPostReply.monitored_post_id == monitored_post_id,
            XTwitterPostReply.auto_reply_status == "pending",
        ))
        result = await session.execute(stmt)
        pending_comments = result.scalars().all()

        if not pending_comments:
            return

        mp = await session.get(XTwitterMonitoredPost, monitored_post_id)
        if not mp:
            return

        count_stmt = select(func.count(XTwitterReply.id)).where(
            XTwitterReply.auto_replied_at >= today_start,
            XTwitterReply.auto_reply_status == "sent",
        )
        count_result = await session.execute(count_stmt)
        today_count = count_result.scalar() or 0

    remaining_quota = max(0, DAILY_LIMIT - today_count)
    if remaining_quota == 0:
        logger.warning(f"今日 AI 回复已达上限 {DAILY_LIMIT}，跳过")
        return

    to_process = pending_comments[:remaining_quota]
    logger.info(f"并发对 {len(to_process)} 条帖子评论进行 AI 回复（剩余配额 {remaining_quota}, 并发上限 {_AI_REPLY_CONCURRENCY}）")

    # 拍照父帖子信息(避免并发访问同一 ORM 对象)
    mp_snapshot = {
        "post_id": mp.post_id,
        "post_content": mp.post_content or "",
    }

    sem = asyncio.Semaphore(_AI_REPLY_CONCURRENCY)

    async def _process_one_comment(comment: XTwitterPostReply):
        async with sem:
            try:
                ai_reply = await ai_agent_client.generate_auto_reply(
                    post_content=mp_snapshot["post_content"],
                    my_comment="",
                    reply_content=comment.comment_content or "",
                    replier=comment.commenter_username or "",
                )

                send_result = await reply_to_comment(
                    comment_url=comment.comment_url,
                    content=ai_reply,
                    real_send=True,
                )

                now = int(time.time())
                success = send_result.get("success", False)
                async with get_session() as session:
                    if success:
                        # 原子更新 auto_replied_count(避免并发竞态)
                        await session.execute(
                            update(XTwitterMonitoredPost)
                            .where(XTwitterMonitoredPost.id == monitored_post_id)
                            .values(auto_replied_count=XTwitterMonitoredPost.auto_replied_count + 1)
                        )
                    db_comment = await session.get(XTwitterPostReply, comment.id)
                    if db_comment:
                        db_comment.auto_reply_status = "sent" if success else "failed"
                        db_comment.auto_reply_content = ai_reply
                        db_comment.auto_reply_url = send_result.get("comment_url", "") if success else ""
                        db_comment.auto_replied_at = now if success else 0
                        db_comment.last_modify_ts = now
                    await session.commit()

                try:
                    from api.routers.websocket import notify_x_twitter_reply, notify_x_twitter_reply_sent
                    await notify_x_twitter_reply(
                        post_id=mp_snapshot["post_id"],
                        comment_url=comment.comment_url,
                        reply_content=comment.comment_content[:200],
                        replied_by=comment.commenter_username,
                    )
                    await notify_x_twitter_reply_sent(
                        post_id=mp_snapshot["post_id"],
                        comment_url=comment.comment_url,
                        reply_content=ai_reply[:200],
                    )
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"AI 回复帖子评论失败 comment_id={comment.id}: {e}")
                async with get_session() as session:
                    db_comment = await session.get(XTwitterPostReply, comment.id)
                    if db_comment:
                        db_comment.auto_reply_status = "failed"
                        db_comment.last_modify_ts = int(time.time())
                        await session.commit()
                # 触发回复失败通知(失败不影响主流程)
                try:
                    from api.services.x_workbench_notifier import notify_event, EVENT_REPLY_FAILED
                    await notify_event(
                        event=EVENT_REPLY_FAILED,
                        title="AI 自动回复失败",
                        content=f"对帖子下 @{comment.commenter_username} 的评论进行 AI 自动回复时失败: {e}",
                        extra={
                            "监控帖子ID": monitored_post_id,
                            "评论ID": comment.id,
                            "评论者": f"@{comment.commenter_username}",
                            "评论摘要": (comment.comment_content or "")[:80],
                            "错误": str(e)[:200],
                            "评论URL": comment.comment_url or "",
                        },
                    )
                except Exception as ne:
                    logger.debug(f"触发 reply_failed 通知失败(忽略): {ne}")

    await asyncio.gather(*[_process_one_comment(c) for c in to_process])
