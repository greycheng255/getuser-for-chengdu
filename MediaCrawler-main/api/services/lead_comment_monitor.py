# -*- coding: utf-8 -*-
"""线索评论回复监测服务 - 回扫源视频评论区,捕获线索相关的新回复。

监测两类回复:
1. 线索本人回来再说: 回复的 user_id == 线索 user_id (is_from_lead=1)
2. 线索原评论线程内的回复: parent_comment_id == 线索 comment_id

核心能力:
1. monitor_lead_replies(lead_id): 监测单条线索的评论回复
2. monitor_task_replies(task_id): 批量监测任务下所有可监测线索
3. start_reply_monitor_loop(): 后台循环,定时监测已触达线索

遵循项目硬约束: 复用 lead_browser 独立Chrome + cookie_manager 单一数据源,
请求间随机延迟降低风控。
"""
import asyncio
import random
import time
from typing import List

from sqlalchemy import select, update, func, or_

from database.db_session import get_session
from database.models import CustomerLead, LeadCommentReply
from tools import utils


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _get_replies_by_browser(page, aweme_id: str, target_comment_id: str, lead_user_id: str) -> list:
    """通过浏览器页面内 XHR 直接调用评论/回复API(绕过直接httpx调用的风控)。

    策略:
    1. 导航到视频页(确保在 douyin.com 域,前端JS已加载)
    2. 从页面 localStorage 获取 msToken
    3. 用 page.evaluate + XHR 调用 /comment/list/reply/ 和 /comment/list/ API
       (前端拦截器自动添加 a_bogus 签名,请求使用浏览器完整指纹)
    4. 过滤:回复 parent_comment_id==目标评论 或 回复者==线索本人
    """
    import random
    import urllib.parse as _urlparse

    all_replies = []
    all_comments = []

    # 关键: 导航到"视频页"(单视频页加载后稳定,不像 /jingxuan 信息流那样无限加载导致上下文被摧毁)。
    # 用 networkidle 等待 SPA 跳转完全停止,再用 window.stop() 冻结残余加载,确保 XHR 执行上下文稳定。
    # XHR 调用只需在 douyin.com 域内即可获得 Cookie + 前端 a_bogus 签名。
    video_url = f"https://www.douyin.com/video/{aweme_id}"

    async def _wait_for_page_stable(timeout_idle: int = 15000):
        """等待页面稳定(避免导航竞态导致 "Execution context was destroyed")。"""
        for _attempt in range(4):
            try:
                await page.wait_for_load_state("networkidle", timeout=timeout_idle)
                return True
            except Exception:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                await asyncio.sleep(2)
        return False

    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
        await _wait_for_page_stable()
        # 不调用 window.stop():会中断签名 JS 初始化,导致 XHR 不带 a_bogus 被风控。
        # 专用页面无外部导航干扰,networkidle + evaluate 超时已足够保证上下文稳定。
        await asyncio.sleep(random.uniform(1.5, 2.5))
    except Exception as e:
        utils.logger.warning(f"[reply_monitor] navigate to video page failed: {e}")

    # 检测是否被重定向到登录/验证页(会导致后续 XHR 失败)
    try:
        cur_url = page.url or ""
    except Exception:
        cur_url = ""
    if "login" in cur_url or "verify" in cur_url or "captcha" in cur_url:
        utils.logger.warning(f"[reply_monitor] page redirected to {cur_url}, cookie may be invalid")
    else:
        utils.logger.info(f"[reply_monitor] page stable at {cur_url}, ready for XHR")

    # 从页面获取 msToken 和构建参数(带重试,避免导航竞态)
    common_params = None
    for _attempt in range(3):
        try:
            common_params = await page.evaluate("""() => {
                const ls = localStorage.getItem('xmst') || '';
                const ua = navigator.userAgent;
                return {
                    msToken: ls,
                    ua: ua,
                    platform: navigator.platform,
                    cores: navigator.hardwareConcurrency || 8,
                    mem: navigator.deviceMemory || 8,
                    sw: screen.width || 1920,
                    sh: screen.height || 1080,
                };
            }""")
            break
        except Exception as e:
            utils.logger.warning(f"[reply_monitor] page.evaluate attempt {_attempt+1} failed: {e}")
            await _wait_for_page_stable()
            await asyncio.sleep(2)

    ms_token = common_params.get("msToken", "") if common_params else ""
    if not ms_token:
        # 尝试从 cookie 获取
        try:
            cookies = await page.context.cookies()
            ms_token = next((c["value"] for c in cookies if c["name"] == "msToken"), "")
        except Exception:
            pass

    if not ms_token:
        utils.logger.warning("[reply_monitor] msToken missing, API calls may be blocked")

    # 构建公共参数(与 client.py __process_req_params 一致)
    def _build_common_params():
        p = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "version_code": "190600",
            "version_name": "19.6.0",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "cookie_enabled": "true",
            "browser_language": "zh-CN",
            "browser_platform": common_params.get("platform", "Win32") if common_params else "Win32",
            "browser_name": "Chrome",
            "browser_version": "125.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": str(common_params.get("cores", 8) if common_params else 8),
            "device_memory": str(common_params.get("mem", 8) if common_params else 8),
            "engine_version": "109.0",
            "platform": "PC",
            "screen_width": str(common_params.get("sw", 1920) if common_params else 1920),
            "screen_height": str(common_params.get("sh", 1080) if common_params else 1080),
            "effective_type": "4g",
            "round_trip_time": "50",
        }
        if ms_token:
            p["msToken"] = ms_token
        return p

    # 策略1: 用页面内 XHR 调用回复API(前端自动添加 a_bogus)
    async def _fetch_via_page_xhr(api_path, api_params):
        full_params = {**api_params, **_build_common_params()}
        query_string = _urlparse.urlencode(full_params)
        js_expr = """async ([path, qs]) => {
            return new Promise((resolve) => {
                const xhr = new XMLHttpRequest();
                const url = path + '?' + qs;
                xhr.open('GET', url, true);
                xhr.withCredentials = true;
                xhr.timeout = 15000;
                xhr.onload = function() {
                    try { resolve(JSON.parse(xhr.responseText)); }
                    catch(e) { resolve(null); }
                };
                xhr.onerror = function() { resolve(null); };
                xhr.ontimeout = function() { resolve(null); };
                xhr.send();
            });
        }"""
        # 带重试: 导航竞态/SPA 跳转会摧毁执行上下文,重新等待稳定后再试
        last_err = None
        for _attempt in range(3):
            try:
                # asyncio.wait_for 兜底: 前端签名拦截器可能改写 XHR 导致 Promise 不 resolve,
                # page.evaluate 无默认超时会永久挂起,这里强制 25s 超时
                result = await asyncio.wait_for(
                    page.evaluate(js_expr, [api_path, query_string]),
                    timeout=25,
                )
                if result is None:
                    utils.logger.warning(f"[reply_monitor] XHR {api_path} returned null (blocked/aborted) attempt {_attempt+1}")
                else:
                    sc = result.get("status_code") if isinstance(result, dict) else "?"
                    utils.logger.info(f"[reply_monitor] XHR {api_path} ok, status_code={sc}, attempt {_attempt+1}")
                return result
            except asyncio.TimeoutError:
                last_err = "asyncio.TimeoutError"
                utils.logger.warning(f"[reply_monitor] XHR {api_path} evaluate timed out (25s) attempt {_attempt+1}, re-stabilizing")
                await _wait_for_page_stable()
                await asyncio.sleep(2)
                continue
            except Exception as e:
                last_err = e
                msg = str(e)
                if "Execution context was destroyed" in msg or "Target page" in msg or "browser has been closed" in msg:
                    utils.logger.warning(f"[reply_monitor] XHR evaluate attempt {_attempt+1} context lost, re-stabilizing: {msg}")
                    await _wait_for_page_stable()
                    await asyncio.sleep(2)
                    continue
                # 其他异常直接返回,避免无意义重试
                break
        utils.logger.warning(f"[reply_monitor] XHR evaluate failed after retries: {last_err}")
        return None

    # 获取目标评论的子回复
    utils.logger.info(f"[reply_monitor] Fetching sub-comments for comment {target_comment_id} via page XHR...")
    cursor = 0
    for page_num in range(5):
        resp = await _fetch_via_page_xhr("/aweme/v1/web/comment/list/reply/", {
            "comment_id": target_comment_id,
            "cursor": cursor,
            "count": 20,
            "item_type": 0,
            "item_id": aweme_id,
        })
        if not resp or not isinstance(resp, dict):
            utils.logger.warning(f"[reply_monitor] reply API page {page_num} returned empty/blocked")
            break
        if resp.get("status_code") and resp.get("status_code") != 0:
            utils.logger.warning(f"[reply_monitor] reply API returned status_code={resp.get('status_code')}, msg={resp.get('status_msg', '')}")
            break
        sub_comments = resp.get("comments", []) or []
        if not sub_comments:
            break
        for c in sub_comments:
            all_replies.append(_parse_reply(c, aweme_id))
        if resp.get("has_more", 0) != 1:
            break
        cursor = resp.get("cursor", 0) or cursor
        await asyncio.sleep(random.uniform(1.5, 3))

    # 也获取视频的最新评论列表(检查线索本人是否有新评论)
    utils.logger.info(f"[reply_monitor] Fetching comment list for aweme {aweme_id} via page XHR...")
    cursor = 0
    for page_num in range(3):
        resp = await _fetch_via_page_xhr("/aweme/v1/web/comment/list/", {
            "aweme_id": aweme_id,
            "cursor": cursor,
            "count": 20,
            "item_type": 0,
        })
        if not resp or not isinstance(resp, dict):
            break
        if resp.get("status_code") and resp.get("status_code") != 0:
            break
        comments = resp.get("comments", []) or []
        if not comments:
            break
        for c in comments:
            all_comments.append(_parse_reply(c, aweme_id))
        if resp.get("has_more", 0) != 1:
            break
        cursor = resp.get("cursor", 0) or cursor
        await asyncio.sleep(random.uniform(1.5, 3))

    utils.logger.info(f"[reply_monitor] Got {len(all_comments)} comments, {len(all_replies)} replies via page XHR for aweme {aweme_id}")

    # 过滤回复:parent_comment_id 指向目标评论 OR 回复者是线索本人
    filtered = []
    seen_ids = set()
    for rp in all_replies:
        cid = rp.get("comment_id", "")
        if not cid or cid in seen_ids:
            continue
        is_in_thread = rp.get("parent_comment_id", "") == target_comment_id
        is_from_lead = rp.get("user_id", "") and rp.get("user_id") == lead_user_id
        if is_in_thread or is_from_lead:
            rp["is_from_lead"] = 1 if is_from_lead else 0
            seen_ids.add(cid)
            filtered.append(rp)

    # 也检查主评论列表中是否有线索本人的新评论
    for c in all_comments:
        cid = c.get("comment_id", "")
        if not cid or cid in seen_ids:
            continue
        if c.get("user_id", "") and c.get("user_id") == lead_user_id and cid != target_comment_id:
            c["is_from_lead"] = 1
            seen_ids.add(cid)
            filtered.append(c)

    utils.logger.info(f"[reply_monitor] Filtered {len(filtered)} relevant replies for comment {target_comment_id}")
    return filtered



def _parse_reply(comment_item: dict, aweme_id: str) -> dict:
    """从抖音评论响应解析出统一字段(与 store/douyin 映射一致)。"""
    user_info = comment_item.get("user", {}) or {}
    avatar_info = (
        user_info.get("avatar_medium", {})
        or user_info.get("avatar_300x300", {})
        or user_info.get("avatar_thumb", {})
        or {}
    )
    return {
        "comment_id": str(comment_item.get("cid", "")),
        "parent_comment_id": str(comment_item.get("reply_id", "") or ""),
        "user_id": str(user_info.get("uid", "") or ""),
        "sec_uid": str(user_info.get("sec_uid", "") or ""),
        "nickname": user_info.get("nickname", "") or "",
        "avatar": (avatar_info.get("url_list", [""])[0] if avatar_info.get("url_list") else ""),
        "content": comment_item.get("text", "") or "",
        "like_count": str(comment_item.get("digg_count", 0)),
        "create_time": int(comment_item.get("create_time", 0) or 0),
    }


async def _get_dy_client_and_page(user_id: int):
    """复用获客采集专用浏览器(lead_browser),返回 (DouYinClient, page, is_dedicated_page)。

    创建"专用页面":在同一浏览器上下文内,共享 Cookie/登录状态/add_init_script 反检测脚本,
    但导航独立于 contact_collector 缓存页,避免双方互相导航导致 evaluate 上下文被摧毁。
    调用方应在 finally 中关闭专用页面(is_dedicated_page=True 时)。

    浏览器实例由 lead_browser 缓存管理,重试 2 次,每次间隔 5 秒。
    Cookie 使用 get_outreach_cookie 与 lead_browser 加载的 Cookie 保持一致,避免风控。
    """
    from .lead_browser import launch_lead_browser
    from media_platform.douyin.client import DouYinClient
    from .cookie_manager import get_outreach_cookie, get_cookie
    from tools.crawler_util import convert_str_cookie_to_dict

    last_err = None
    for attempt in range(3):
        try:
            browser_context, shared_page, _cdp_manager, _playwright = await launch_lead_browser(
                platform="dy", user_id=user_id
            )
            # 创建专用页面:继承上下文 Cookie + 反检测 init_script,导航独立
            page = shared_page
            is_dedicated = False
            try:
                page = await browser_context.new_page()
                await page.set_viewport_size({"width": 1920, "height": 1080})
                is_dedicated = True
                utils.logger.info(f"[reply_monitor] Created dedicated page (isolated navigation) attempt={attempt+1}")
            except Exception as e:
                utils.logger.warning(f"[reply_monitor] new_page failed (attempt={attempt+1}), using shared page: {e}")
                page = shared_page

            # 验证页面是否真的可用(避免拿到已被关闭的 cached page)
            try:
                await page.evaluate("() => document.title")
            except Exception as ve:
                utils.logger.warning(f"[reply_monitor] page unusable (attempt={attempt+1}), likely closed: {ve}")
                if is_dedicated:
                    try:
                        await page.close()
                    except Exception:
                        pass
                last_err = f"页面不可用(可能被其他任务关闭): {ve}"
                await asyncio.sleep(5)
                continue

            # 优先获客专用 Cookie(与 lead_browser 加载的 Cookie 一致),退回全局 .env
            cookie_str = ""
            if user_id:
                cookie_str = await get_outreach_cookie(user_id, "dy")
            if not cookie_str:
                cookie_str = get_cookie("dy")
            if not cookie_str:
                if is_dedicated:
                    try:
                        await page.close()
                    except Exception:
                        pass
                raise RuntimeError("未找到抖音 Cookie,无法监测评论回复")
            cookie_dict = convert_str_cookie_to_dict(cookie_str)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
                "Referer": "https://www.douyin.com/",
                "Origin": "https://www.douyin.com",
                "Content-Type": "application/json",
            }
            return DouYinClient(headers=headers, playwright_page=page, cookie_dict=cookie_dict), page, is_dedicated
        except Exception as e:
            last_err = str(e)
            utils.logger.warning(f"[reply_monitor] launch_lead_browser failed (attempt={attempt+1}): {e}")
            if attempt < 2:
                await asyncio.sleep(5)

    raise RuntimeError(f"浏览器启动失败(重试 3 次): {last_err}")


async def monitor_lead_replies(lead_id: int, owner_uid: str = "") -> dict:
    """监测单条线索的评论回复(供手动按钮 + 后台循环调用)。"""
    async with get_session() as session:
        if session is None:
            return {"success": False, "message": "数据库不可用"}
        r = await session.execute(select(CustomerLead).where(CustomerLead.id == lead_id))
        lead = r.scalar_one_or_none()
        if not lead:
            return {"success": False, "message": "线索不存在"}
        aweme_id = lead.source_aweme_id or ""
        comment_id = str(lead.data_id or "")
        lead_user_id = str(lead.user_id or "")
        if not aweme_id or not comment_id:
            # 无视频/评论上下文,无法监测
            lead.reply_monitor_ts = _now_ms()
            await session.commit()
            return {"success": False, "message": "该线索无源视频/评论ID,无法监测"}
        owner_uid = owner_uid or lead.owner_user_id or ""
        lead_snapshot = {
            "id": lead.id,
            "task_id": lead.task_id or "",
            "platform": lead.platform or "douyin",
            "owner_user_id": owner_uid,
        }

    user_id = int(owner_uid) if str(owner_uid).isdigit() else 0
    is_dedicated = False
    try:
        client, page, is_dedicated = await _get_dy_client_and_page(user_id)
    except Exception as e:
        utils.logger.error(f"[reply_monitor] launch browser failed: {e}")
        return {"success": False, "message": f"浏览器启动失败: {e}"}

    new_replies = []
    try:
        # 策略1: 通过浏览器拦截页面评论/回复API响应(绕过直接API调用的风控)
        new_replies = await _get_replies_by_browser(page, aweme_id, comment_id, lead_user_id)

        # 去重入库(已存在的 comment_id 跳过)
        added = 0
        if new_replies:
            async with get_session() as session:
                if session is not None:
                    existing_ids = set(
                        (await session.execute(
                            select(LeadCommentReply.comment_id).where(
                                LeadCommentReply.lead_id == lead_id
                            )
                        )).scalars().all()
                    )
                    now_ms = _now_ms()
                    for rp in new_replies:
                        if rp["comment_id"] in existing_ids:
                            continue
                        session.add(LeadCommentReply(
                            lead_id=lead_id,
                            task_id=lead_snapshot["task_id"],
                            platform=lead_snapshot["platform"],
                            aweme_id=aweme_id,
                            comment_id=rp["comment_id"],
                            parent_comment_id=rp["parent_comment_id"],
                            user_id=rp["user_id"],
                            sec_uid=rp["sec_uid"],
                            nickname=rp["nickname"],
                            avatar=rp["avatar"],
                            content=rp["content"],
                            like_count=rp["like_count"],
                            create_time=rp["create_time"],
                            is_from_lead=rp["is_from_lead"],
                            is_read=0,
                            owner_user_id=lead_snapshot["owner_user_id"],
                            add_ts=now_ms,
                        ))
                        added += 1
                    await session.commit()

        # 更新监测时间戳
        async with get_session() as session:
            if session is not None:
                await session.execute(
                    update(CustomerLead).where(CustomerLead.id == lead_id)
                    .values(reply_monitor_ts=_now_ms(), last_modify_ts=_now_ms())
                )
                await session.commit()

        return {"success": True, "message": f"监测完成,新增 {added} 条回复", "added": added}
    except Exception as e:
        utils.logger.error(f"[reply_monitor] monitor_lead_replies {lead_id} error: {e}")
        return {"success": False, "message": str(e)}
    finally:
        # 关闭专用页面,避免页面堆积(共享缓存页不关闭)
        if is_dedicated:
            try:
                await page.close()
                utils.logger.info("[reply_monitor] Closed dedicated page after monitoring")
            except Exception:
                pass


async def monitor_task_replies(task_id: str, owner_uid: str = "", limit: int = 50, job_id: str = "", filters: dict = None) -> dict:
    """批量监测任务下所有可监测线索(顺序执行+频率限制)。

    Args:
        job_id: 可选,传入则按条更新 customer_lead._batch_jobs 进度,供前端轮询展示。
        filters: 可选,与列表/预查询一致的筛选条件(platform/role_tag/ip_location/status/level/start_ts/end_ts)。
                 必须应用与 monitor_task_replies_ep 预查询完全相同的筛选,否则 total 与实际监测量不一致。
    """
    def _report_progress(completed: int, success: int, failed: int, message: str = ""):
        if not job_id:
            return
        try:
            from ..routers.customer_lead import _update_batch_job
            _update_batch_job(
                job_id,
                completed=completed,
                success=success,
                failed=failed,
                message=message,
            )
        except Exception:
            pass

    if not isinstance(filters, dict):
        filters = {}

    async with get_session() as session:
        if session is None:
            _report_progress(0, 0, 0, "数据库不可用")
            if job_id:
                try:
                    from ..routers.customer_lead import _finish_batch_job
                    _finish_batch_job(job_id, status="failed", message="数据库不可用")
                except Exception:
                    pass
            return {"success": False, "message": "数据库不可用"}
        q = select(CustomerLead.id, CustomerLead.owner_user_id).where(
            CustomerLead.task_id == task_id,
            CustomerLead.source_aweme_id != "",
            CustomerLead.data_id != "",
        )
        # 用户隔离(与预查询一致)
        if owner_uid:
            q = q.where(CustomerLead.owner_user_id == owner_uid)
        # 应用与 monitor_task_replies_ep 预查询完全一致的筛选条件,避免 total 与实际监测量不符
        if filters.get("platform"):
            q = q.where(CustomerLead.platform == filters["platform"])
        if filters.get("role_tag"):
            q = q.where(CustomerLead.role_tag == filters["role_tag"])
        if filters.get("ip_location"):
            q = q.where(CustomerLead.ip_location.contains(filters["ip_location"]))
        if filters.get("status"):
            q = q.where(CustomerLead.status == filters["status"])
        lvl = (filters.get("level") or "").lower() if filters.get("level") else ""
        if lvl == "high":
            q = q.where(CustomerLead.lead_score >= 80)
        elif lvl == "medium":
            q = q.where(CustomerLead.lead_score >= 50).where(CustomerLead.lead_score < 80)
        elif lvl == "low":
            q = q.where(CustomerLead.lead_score < 50)
        if filters.get("start_ts") is not None:
            q = q.where(
                func.coalesce(CustomerLead.create_time * 1000, CustomerLead.add_ts) >= int(filters["start_ts"])
            )
        if filters.get("end_ts") is not None:
            q = q.where(
                func.coalesce(CustomerLead.create_time * 1000, CustomerLead.add_ts) <= int(filters["end_ts"])
            )
        # 任务自动地区过滤(与 list_leads 一致):若未单独指定 ip_location,则按 target_regions 过滤
        if not filters.get("ip_location") and task_id:
            try:
                from database.models import CrawlerTaskModel
                import json as _json
                tr = await session.execute(
                    select(CrawlerTaskModel.target_regions).where(CrawlerTaskModel.id == task_id)
                )
                trow = tr.first()
                if trow and trow[0]:
                    regions = _json.loads(trow[0])
                    if regions and isinstance(regions, list) and len(regions) > 0:
                        conds = [CustomerLead.ip_location.contains(r) for r in regions]
                        if conds:
                            q = q.where(or_(*conds))
            except Exception:
                pass
        q = q.limit(limit)
        r = await session.execute(q)
        rows = r.all()
    if not rows:
        _report_progress(0, 0, 0, "该任务下无可监测线索")
        if job_id:
            try:
                from ..routers.customer_lead import _finish_batch_job
                _finish_batch_job(job_id, status="completed", message="该任务下无可监测线索")
            except Exception:
                pass
        return {"success": False, "message": "该任务下无可监测线索(需有源视频+评论ID)"}

    owner_uid = owner_uid or (rows[0][1] if rows else "")
    total = len(rows)
    success = 0
    new_count = 0
    failed = 0
    completed = 0
    _report_progress(0, 0, 0, f"开始监测 {total} 条线索的评论回复")
    for lead_id, _ in rows:
        res = await monitor_lead_replies(lead_id, owner_uid)
        if res.get("success"):
            success += 1
            new_count += res.get("added", 0)
        else:
            failed += 1
        completed += 1
        _report_progress(
            completed, success, failed,
            f"进度 {completed}/{total}: 成功 {success}, 失败 {failed}, 新增回复 {new_count}"
        )
        await asyncio.sleep(random.uniform(2, 4))

    msg = f"监测完成: 共 {total} 条线索, 成功 {success}, 失败 {failed}, 新增回复 {new_count} 条"
    _report_progress(completed, success, failed, msg)
    # 标记 job 终态(此前只更新进度未改 status,导致前端永远显示"执行中...")
    if job_id:
        try:
            from ..routers.customer_lead import _finish_batch_job
            _finish_batch_job(job_id, status="completed", message=msg)
        except Exception:
            pass
    return {
        "success": True,
        "message": msg,
        "stats": {"total": total, "success": success, "failed": failed, "new_replies": new_count},
    }


# ==================== 后台自动监测循环 ====================
_LOOP_INTERVAL_SEC = 600  # 每10分钟扫描一次
_BATCH_PER_CYCLE = 5  # 每轮最多监测5条(优先监测最久未监测的)


async def _reply_monitor_loop():
    """后台循环: 定时监测已触达线索的评论回复。"""
    print("[reply_monitor] auto-monitor loop started (interval=600s, batch=5)")
    while True:
        try:
            await asyncio.sleep(_LOOP_INTERVAL_SEC)
            # 优先监测 reply_monitor_ts 最久未监测的可监测线索
            async with get_session() as session:
                if session is None:
                    continue
                r = await session.execute(
                    select(CustomerLead.id, CustomerLead.owner_user_id).where(
                        CustomerLead.source_aweme_id != "",
                        CustomerLead.data_id != "",
                    ).order_by(CustomerLead.reply_monitor_ts.asc()).limit(_BATCH_PER_CYCLE)
                )
                rows = r.all()
            if not rows:
                continue
            owner_uid = rows[0][1] or ""
            for lead_id, _ in rows:
                try:
                    await monitor_lead_replies(lead_id, owner_uid)
                except Exception as e:
                    print(f"[reply_monitor] monitor lead {lead_id} error: {e}")
                await asyncio.sleep(random.uniform(2, 4))
        except asyncio.CancelledError:
            print("[reply_monitor] auto-monitor loop cancelled")
            raise
        except Exception as e:
            print(f"[reply_monitor] loop error: {e}")
            await asyncio.sleep(30)


async def start_reply_monitor_loop():
    """启动后台自动监测循环(由 main.py startup 调用)。"""
    asyncio.create_task(_reply_monitor_loop())
