# -*- coding: utf-8 -*-
r"""用户主页联系方式采集服务 - 访问抖音用户主页,从简介提取手机号/微信号。

核心能力:
1. collect_contact_for_lead(lead_id): 采集单条线索的联系方式
2. collect_contacts_batch(lead_ids): 批量采集(复用浏览器,带频率限制)
3. start_contact_collector_loop(): 后台循环,扫描 contact_status=pending 的线索自动采集

提取规则:
- 手机号: 中国大陆11位手机号 1[3-9]\d{9}
- 微信号: 匹配 "微信/vx/v/➕v/加微/薇" 等前缀后的微信号(字母开头,6-20位)

遵循项目硬约束:
- 使用 cookie_manager 单一数据源,通过 lead_browser 复用独立Chrome
- 频率控制: 每次请求间隔 3-6 秒随机,避免触发风控
"""
import asyncio
import re
import time
from typing import List

from sqlalchemy import select

from database.db_session import get_session
from database.models import CustomerLead
from tools import utils


# 手机号: 支持 138-1234-5678 / 138 1234 5678 / +86 138... / 138．1234．5678
# (用户常加分隔符规避审查,先匹配含分隔符的候选,再清洗为纯数字)
PHONE_RE = re.compile(r'(?:\+?86[\s\-．.·]*)?1[3-9]\d[\s\-．.·]?\d{4}[\s\-．.·]?\d{4}')

# 微信号前缀(覆盖常见话术 + 谐音规避词:卫星/威信/薇信 等用户为躲审查的写法)
WECHAT_PREFIX_RE = re.compile(
    r'(?:微信|薇信|卫星|威信|薇星|微信號|微信号|vx|VX|vx|薇|微|➕v|加v|加微|加薇|v信|V信|wx|WX|w×|w x|w-x|V|v|微❤|➕薇|加卫星)[\s:：➕❤️]*([a-zA-Z][a-zA-Z0-9_-]{5,19})',
    re.IGNORECASE,
)

# QQ号: QQ/QQ号/扣扣/企鹅 前缀 + 5-11位数字
QQ_RE = re.compile(r'(?:QQ|qq|扣扣|企鹅)[\s:：号]*([1-9]\d{4,10})')


def extract_phone(text: str) -> str:
    """从文本提取首个手机号(支持分隔符: 138-1234-5678 / 138 1234 5678 / +86 138...)。"""
    if not text:
        return ''
    m = PHONE_RE.search(text)
    if not m:
        return ''
    # 清洗分隔符和+号,返回纯数字
    cleaned = re.sub(r'[\s\-．.·+]', '', m.group(0))
    # 去掉 86 前缀(如有),返回11位手机号
    if len(cleaned) > 11 and cleaned.startswith('86'):
        cleaned = cleaned[2:]
    return cleaned if len(cleaned) == 11 else ''


def extract_wechat(text: str) -> str:
    """从文本提取微信号。优先匹配带前缀的(含谐音规避词),兼容QQ号。"""
    if not text:
        return ''
    # 1. 带前缀的微信号(最可靠,含卫星/威信等谐音规避)
    for m in WECHAT_PREFIX_RE.finditer(text):
        candidate = m.group(1)
        # 排除明显误匹配(如全数字)
        if not candidate.isdigit():
            return candidate
    # 2. QQ号(QQ/QQ号/扣扣 前缀,标前缀便于区分)
    m = QQ_RE.search(text)
    if m:
        return 'QQ:' + m.group(1)
    return ''


def _find_user_in_obj(obj, depth=0):
    """递归查找包含 signature 字段的用户对象(用于 RENDER_DATA / __INITIAL_STATE__)。"""
    if depth > 12:
        return None
    if isinstance(obj, dict):
        if "signature" in obj and ("nickname" in obj or "sec_uid" in obj or "uid" in obj):
            return obj
        for v in obj.values():
            result = _find_user_in_obj(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_user_in_obj(item, depth + 1)
            if result:
                return result
    return None


async def _extract_user_info_from_page(page, sec_uid: str) -> dict:
    """从用户主页页面提取用户信息(绕过直接API调用,利用页面自身请求降低风控)。

    策略优先级:
    1. 拦截页面自带的 profile API 响应(浏览器完整指纹,最不易被block)
    2. 从 RENDER_DATA (SSR数据) 提取(服务端渲染,无需API调用)
    3. 从 DOM 选择器提取简介文本
    """
    import json as _json
    import urllib.parse as _urlparse
    import random as _random

    profile_url = f"https://www.douyin.com/user/{sec_uid}"
    captured = {"data": None}

    async def _on_response(response):
        url = response.url
        if "profile/other" in url and response.status == 200:
            try:
                data = await response.json()
                user = data.get("user") if isinstance(data, dict) else None
                if not user and isinstance(data, dict):
                    user = data
                if isinstance(user, dict) and (user.get("signature") is not None or user.get("nickname")):
                    captured["data"] = {
                        "signature": user.get("signature", "") or "",
                        "nickname": user.get("nickname", "") or "",
                        "unique_id": user.get("unique_id", "") or "",
                    }
            except Exception:
                pass

    page.on("response", _on_response)
    try:
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(_random.uniform(3, 5))  # 等待页面自带API响应
    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:
            pass

    # 策略1: 拦截到的API响应(页面自身请求,带完整浏览器指纹)
    if captured["data"]:
        utils.logger.info("[contact_collector] Extracted user info via intercepted page API response")
        return captured["data"]

    # 策略2: 从 RENDER_DATA 提取(SSR数据,服务端渲染,无需API调用)
    try:
        render_raw = await page.evaluate("""() => {
            const el = document.getElementById('RENDER_DATA');
            return el ? el.textContent : null;
        }""")
        if render_raw:
            decoded = _urlparse.unquote(render_raw)
            data = _json.loads(decoded)
            user_info = _find_user_in_obj(data)
            if user_info and user_info.get("signature") is not None:
                utils.logger.info("[contact_collector] Extracted user info via RENDER_DATA (SSR)")
                return {
                    "signature": user_info.get("signature", "") or "",
                    "nickname": user_info.get("nickname", "") or "",
                    "unique_id": user_info.get("unique_id", "") or "",
                }
    except Exception as e:
        utils.logger.warning(f"[contact_collector] RENDER_DATA extraction failed: {e}")

    # 策略3: 从 DOM 选择器提取简介文本(精确匹配 signature 元素,排除导航/关注等信息)
    try:
        result = await page.evaluate("""() => {
            // 昵称
            let nickname = '';
            const nickEl = document.querySelector('[data-e2e="user-info"] h1, h1[class*="title"], [class*="nickname"]');
            if (nickEl) nickname = nickEl.textContent.trim();

            // 抖音号
            let uniqueId = '';
            const allText = document.body.innerText || '';
            const idMatch = allText.match(/抖音号[：:\\s]*([A-Za-z0-9_-]+)/);
            if (idMatch) uniqueId = idMatch[1];

            // 个人简介: 优先精确选择器,退化为排除导航文本的元素
            let bio = '';
            // 3a. 精确简介选择器
            const bioSelectors = [
                '[data-e2e="user-info-desc"]',
                '[data-e2e="user-desc"]',
                '[class*="signature"]',
                '[class*="user-desc"]',
            ];
            for (const sel of bioSelectors) {
                const el = document.querySelector(sel);
                if (el && el.textContent.trim()) {
                    bio = el.textContent.trim();
                    break;
                }
            }
            // 3b. 退化: 从 user-info 容器中提取排除标签后的纯文本
            if (!bio) {
                const infoEl = document.querySelector('[data-e2e="user-info"]');
                if (infoEl) {
                    // 克隆并移除 h1/span(昵称/关注/粉丝/获赞/抖音号/IP属地)
                    const clone = infoEl.cloneNode(true);
                    clone.querySelectorAll('h1, span, button, a, [data-e2e]').forEach(e => e.remove());
                    bio = clone.textContent.trim();
                }
            }
            return { signature: bio, nickname: nickname, unique_id: uniqueId };
        }""")
        if result and result.get("signature"):
            utils.logger.info(f"[contact_collector] Extracted bio via DOM selector (len={len(result['signature'])})")
            return result
        # 即使没提取到简介,也返回昵称和抖音号(有价值)
        if result and (result.get("nickname") or result.get("unique_id")):
            utils.logger.info(f"[contact_collector] Extracted partial user info via DOM (nick={result.get('nickname','')}, id={result.get('unique_id','')})")
            return result
    except Exception as e:
        utils.logger.warning(f"[contact_collector] DOM extraction failed: {e}")

    return None


async def _fetch_profile_via_page_xhr(page, sec_uid: str) -> dict:
    """通过浏览器页面内 XHR 调用 profile/other API(前端自动添加 a_bogus 签名)。

    优势:用浏览器完整指纹 + 前端签名拦截器,避免直接 httpx 调用被风控。
    实现:
    1. 导航到 douyin.com 域(确保 Cookie + a_bogus JS 加载)
    2. 用 page.evaluate + XHR 调用 /aweme/v1/web/user/profile/other/
    3. 提取 signature/nickname/unique_id
    """
    import urllib.parse as _urlparse
    import random as _random

    # 确保在 douyin.com 域(导航到主页即可,无需访问用户主页)
    cur_url = page.url or ""
    if "douyin.com" not in cur_url:
        try:
            await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(_random.uniform(2, 3))
        except Exception as e:
            utils.logger.warning(f"[contact_collector] navigate to douyin.com failed: {e}")

    # 等待页面稳定(避免 SPA 跳转导致执行上下文被摧毁)
    async def _wait_stable(timeout_idle: int = 12000):
        for _ in range(3):
            try:
                await page.wait_for_load_state("networkidle", timeout=timeout_idle)
                return True
            except Exception:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=6000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)
        return False

    await _wait_stable()
    await asyncio.sleep(_random.uniform(1.0, 2.0))

    # 从页面获取 msToken 和硬件参数
    common_params = None
    try:
        common_params = await page.evaluate("""() => {
            const ls = localStorage.getItem('xmst') || '';
            return {
                msToken: ls,
                platform: navigator.platform,
                cores: navigator.hardwareConcurrency || 8,
                mem: navigator.deviceMemory || 8,
                sw: screen.width || 1920,
                sh: screen.height || 1080,
            };
        }""")
    except Exception as e:
        utils.logger.warning(f"[contact_collector] page.evaluate (common_params) failed: {e}")

    ms_token = common_params.get("msToken", "") if common_params else ""
    if not ms_token:
        try:
            cookies = await page.context.cookies()
            ms_token = next((c["value"] for c in cookies if c["name"] == "msToken"), "")
        except Exception:
            pass

    # 构建公共参数(与 client.py __process_req_params 一致)
    def _build_params():
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
            "browser_version": "126.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "126.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": str(common_params.get("cores", 8) if common_params else 8),
            "device_memory": str(common_params.get("mem", 8) if common_params else 8),
            "platform": "PC",
            "screen_width": str(common_params.get("sw", 1920) if common_params else 1920),
            "screen_height": str(common_params.get("sh", 1080) if common_params else 1080),
            "effective_type": "4g",
            "round_trip_time": "50",
        }
        if ms_token:
            p["msToken"] = ms_token
        return p

    # 构建 profile API 请求参数
    api_params = {
        "sec_user_id": sec_uid,
        "publish_video_strategy_type": 2,
        "personal_center_strategy": 1,
    }
    full_params = {**api_params, **_build_params()}
    query_string = _urlparse.urlencode(full_params)
    api_path = "/aweme/v1/web/user/profile/other/"

    # 用页面内 XHR 调用(前端拦截器自动添加 a_bogus 签名)
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

    try:
        result = await asyncio.wait_for(
            page.evaluate(js_expr, [api_path, query_string]),
            timeout=25,
        )
    except asyncio.TimeoutError:
        utils.logger.warning(f"[contact_collector] Browser XHR timed out (25s) for sec_uid={sec_uid[:16]}...")
        return None
    except Exception as e:
        utils.logger.warning(f"[contact_collector] Browser XHR evaluate failed: {e}")
        return None

    if not result or not isinstance(result, dict):
        utils.logger.warning(f"[contact_collector] Browser XHR returned null for sec_uid={sec_uid[:16]}...")
        return None

    status_code = result.get("status_code")
    if status_code and status_code != 0:
        utils.logger.warning(
            f"[contact_collector] Browser XHR API returned status_code={status_code}, "
            f"msg={result.get('status_msg', '')}"
        )
        return None

    user = result.get("user") or result
    if not isinstance(user, dict):
        return None

    signature = user.get("signature") or ""
    nickname = user.get("nickname") or ""
    unique_id = user.get("unique_id") or ""

    if not signature and not nickname:
        utils.logger.info(f"[contact_collector] Browser XHR returned empty user info for sec_uid={sec_uid[:16]}...")
        return None

    utils.logger.info(
        f"[contact_collector] Browser XHR extracted user info "
        f"(nick={nickname[:20]}, bio_len={len(signature)})"
    )
    return {"signature": signature, "nickname": nickname, "unique_id": unique_id}


async def _get_dy_client_and_page(user_id: int):
    """复用获客采集专用浏览器(lead_browser),返回 (DouYinClient, page)。

    浏览器实例由 lead_browser 缓存管理,本服务不应主动关闭。
    """
    from .lead_browser import launch_lead_browser
    from media_platform.douyin.client import DouYinClient
    from .cookie_manager import get_outreach_cookie
    from tools.crawler_util import convert_str_cookie_to_dict

    _browser_context, page, _cdp_manager, _playwright = await launch_lead_browser(
        platform="dy", user_id=user_id
    )

    # 从用户 Cookie 池(sys_user_cookie)读取,与浏览器启动用的 get_outreach_cookie 保持同一个 Cookie。
    # 修复:此前用 get_cookie("dy") 读 .env 单 Cookie,与浏览器登录态不一致,
    #      导致 API 请求 Cookie 与浏览器不匹配而触发风控(account blocked)。
    # get_outreach_cookie 内部:优先用户池 → 退回 .env,池为空时自动 fallback。
    cookie_str = await get_outreach_cookie(user_id, "dy")
    if not cookie_str:
        raise RuntimeError("未找到抖音 Cookie,无法采集联系方式")
    cookie_dict = convert_str_cookie_to_dict(cookie_str)

    # 完整的 Windows Chrome 浏览器请求头(与 Cookie 来源环境一致)
    # 修复要点：之前只有 4 个头,缺失 sec-ch-ua / sec-fetch-* 等现代浏览器头,容易被识别为非浏览器
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
        "Origin": "https://www.douyin.com",
        "Content-Type": "application/json;charset=UTF-8",
        # 现代浏览器 Client Hints(Chrome 126+ 必带)
        "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        # Fetch Metadata 请求头(浏览器自动添加,缺失会被识别)
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "sec-fetch-user": "?1",
        # 标准 Accept 头
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "accept-encoding": "gzip, deflate, br",
    }
    client = DouYinClient(headers=headers, playwright_page=page, cookie_dict=cookie_dict)
    return client, page


async def _collect_one(client, page, lead: CustomerLead) -> dict:
    """采集单条线索的联系方式,返回 {phone, wechat, bio, status}。"""
    import random

    sec_uid = lead.sec_uid or ''
    if not sec_uid:
        return {"phone": "", "wechat": "", "bio": "", "status": "none"}

    try:
        # 策略1: 直接从用户主页页面提取(拦截页面自带API响应 + RENDER_DATA + DOM,绕过直接API调用降低风控)
        user_info = await _extract_user_info_from_page(page, sec_uid)

        # 策略2: 页面提取失败时,用浏览器内 XHR 调用 profile API(前端自动添加 a_bogus 签名,避免直接 API 调用被风控)
        if not user_info:
            utils.logger.info(f"[contact_collector] Page extraction returned None, trying browser XHR for lead {lead.id}")
            try:
                user_info = await _fetch_profile_via_page_xhr(page, sec_uid)
            except Exception as xhr_err:
                utils.logger.warning(f"[contact_collector] Browser XHR failed for lead {lead.id}: {xhr_err}")
                user_info = None

        # 策略3: 浏览器 XHR 也失败时,最后才回退到直接 API 调用(可能被block,但作为最后兜底)
        if not user_info:
            utils.logger.info(f"[contact_collector] Browser XHR returned None, trying direct API fallback for lead {lead.id}")
            if "douyin.com" not in (page.url or ""):
                await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(2, 3))
            try:
                user_info = await client.get_user_info(sec_uid)
            except Exception as api_err:
                utils.logger.warning(f"[contact_collector] API fallback failed for lead {lead.id}: {api_err}")
                user_info = None

        if not user_info or not isinstance(user_info, dict):
            return {"phone": "", "wechat": "", "bio": "", "status": "failed"}

        signature = user_info.get("signature", "") or ""
        # 简介可能包含换行,统一处理
        bio_text = signature.strip()
        phone = extract_phone(bio_text)
        wechat = extract_wechat(bio_text)

        # 顺便回填昵称/平台ID(若线索缺失)
        nickname = user_info.get("nickname", "") or ""
        unique_id = user_info.get("unique_id", "") or ""
        status = "done"
        try:
            async with get_session() as session:
                if session is None:
                    return {"phone": phone, "wechat": wechat, "bio": bio_text, "status": status}
                r = await session.execute(select(CustomerLead).where(CustomerLead.id == lead.id))
                ld = r.scalar_one_or_none()
                if ld:
                    ld.contact_phone = phone
                    ld.contact_wechat = wechat
                    ld.bio_text = bio_text[:2000] if bio_text else ""
                    ld.contact_status = status
                    if not ld.nickname and nickname:
                        ld.nickname = nickname
                    if not ld.platform_display_id and unique_id:
                        ld.platform_display_id = unique_id
                    ld.last_modify_ts = int(time.time() * 1000)
                    await session.commit()
        except Exception as e:
            utils.logger.warning(f"[contact_collector] update lead {lead.id} failed: {e}")

        return {"phone": phone, "wechat": wechat, "bio": bio_text, "status": status}
    except Exception as e:
        err = str(e)
        utils.logger.warning(f"[contact_collector] collect failed for lead {lead.id} (sec_uid={sec_uid[:16]}...): {err}")
        # 这些错误属于"环境性失败"(浏览器被关/IP风控),不应标记 failed
        # 保留 pending 状态,等环境恢复后由自动循环重试
        is_environmental_error = any(kw in err for kw in [
            # 浏览器/页面被关闭
            "Target page", "has been closed", "browser has been closed",
            "Target context", "Browser has been closed",
            # 抖音风控(IP/Cookie 被限流)
            "account blocked", "Risk detected", "blocked",
        ])
        if not is_environmental_error:
            # 真正的失败(无效 sec_uid / 解析错误)标记 failed,避免反复重试无效数据
            try:
                async with get_session() as session:
                    if session is not None:
                        r = await session.execute(select(CustomerLead).where(CustomerLead.id == lead.id))
                        ld = r.scalar_one_or_none()
                        if ld:
                            ld.contact_status = "failed"
                            ld.last_modify_ts = int(time.time() * 1000)
                            await session.commit()
            except Exception:
                pass
        return {"phone": "", "wechat": "", "bio": "", "status": "failed", "error": err}
    finally:
        # 请求间随机延迟,降低风控
        await asyncio.sleep(random.uniform(3, 6))


async def collect_contact_for_lead(lead_id: int, owner_uid: str = "") -> dict:
    """采集单条线索联系方式(供手动按钮调用)。"""
    async with get_session() as session:
        if session is None:
            return {"success": False, "message": "数据库不可用"}
        r = await session.execute(select(CustomerLead).where(CustomerLead.id == lead_id))
        lead = r.scalar_one_or_none()
        if not lead:
            return {"success": False, "message": "线索不存在"}
        if not lead.sec_uid:
            # 无sec_uid直接标记
            lead.contact_status = "none"
            lead.last_modify_ts = int(time.time() * 1000)
            await session.commit()
            return {"success": False, "message": "该线索无 sec_uid,无法访问主页"}
        owner_uid = owner_uid or lead.owner_user_id or ""
        # detach 一个轻量副本供后续使用
        lead_snapshot = CustomerLead()
        lead_snapshot.id = lead.id
        lead_snapshot.sec_uid = lead.sec_uid

    try:
        user_id = int(owner_uid) if str(owner_uid).isdigit() else 0
        client, page = await _get_dy_client_and_page(user_id)
        result = await _collect_one(client, page, lead_snapshot)
        return {"success": True, "data": result}
    except Exception as e:
        utils.logger.error(f"[contact_collector] collect_contact_for_lead {lead_id} error: {e}")
        return {"success": False, "message": str(e)}


async def collect_contacts_batch(lead_ids: List[int], owner_uid: str = "", job_id: str = "") -> dict:
    """批量采集联系方式(复用浏览器,顺序执行+频率限制)。

    Args:
        job_id: 可选,传入则按条更新 customer_lead._batch_jobs 进度,供前端轮询展示。
    """
    if not lead_ids:
        return {"success": False, "message": "未选择线索"}

    def _report_progress(completed: int, success: int, failed: int, message: str = ""):
        """更新 job 进度(若 job_id 存在)。失败静默忽略,不影响主流程。"""
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

    # 加载线索快照
    leads = []
    async with get_session() as session:
        if session is None:
            _report_progress(0, 0, 0, "数据库不可用")
            return {"success": False, "message": "数据库不可用"}
        r = await session.execute(
            select(CustomerLead).where(CustomerLead.id.in_(lead_ids))
        )
        for ld in r.scalars().all():
            if ld.sec_uid:
                leads.append(ld)

    if not leads:
        _report_progress(0, 0, 0, "所选线索均无 sec_uid")
        if job_id:
            try:
                from ..routers.customer_lead import _finish_batch_job
                _finish_batch_job(job_id, status="completed", message="所选线索均无 sec_uid")
            except Exception:
                pass
        return {"success": False, "message": "所选线索均无 sec_uid,无法采集"}

    owner_uid = owner_uid or (leads[0].owner_user_id if leads else "")
    user_id = int(owner_uid) if str(owner_uid).isdigit() else 0

    try:
        client, page = await _get_dy_client_and_page(user_id)
    except Exception as e:
        # 启动浏览器失败,标记所有为failed
        async with get_session() as session:
            if session is not None:
                from sqlalchemy import update
                await session.execute(
                    update(CustomerLead).where(CustomerLead.id.in_(lead_ids))
                    .values(contact_status="failed", last_modify_ts=int(time.time() * 1000))
                )
                await session.commit()
        _report_progress(len(leads), 0, len(leads), f"浏览器启动失败: {e}")
        if job_id:
            try:
                from ..routers.customer_lead import _finish_batch_job
                _finish_batch_job(job_id, status="failed", message=f"浏览器启动失败: {e}")
            except Exception:
                pass
        return {"success": False, "message": f"浏览器启动失败: {e}"}

    success = 0
    failed = 0
    no_contact = 0
    completed = 0
    total = len(leads)
    _report_progress(0, 0, 0, f"开始采集 {total} 条线索")
    for lead in leads:
        # 检测 page 是否仍可用(其他任务可能调用 _close_cached_browser 关闭了浏览器)
        try:
            await page.evaluate("() => document.title")
        except Exception as pe:
            utils.logger.warning(f"[contact_collector] page lost before lead {lead.id}: {pe}, re-launching browser")
            _report_progress(completed, success, failed, f"页面失效,正在重新启动浏览器(可能被私信任务关闭)")
            try:
                client, page = await _get_dy_client_and_page(user_id)
                utils.logger.info(f"[contact_collector] browser re-launched for lead {lead.id}")
            except Exception as rel_err:
                utils.logger.error(f"[contact_collector] re-launch failed: {rel_err}")
                failed += 1
                completed += 1
                _report_progress(completed, success, failed, f"浏览器重启失败: {rel_err}")
                continue

        result = await _collect_one(client, page, lead)
        st = result.get("status", "failed")
        # 检测"页面已被关闭"异常 — 即使前置检查通过,采集过程中也可能被其他任务关闭
        if st == "failed":
            err_msg = str(result.get("error", ""))
            if "Target page" in err_msg or "has been closed" in err_msg or "browser has been closed" in err_msg:
                utils.logger.warning(f"[contact_collector] page closed during lead {lead.id}, re-launching and retrying")
                try:
                    client, page = await _get_dy_client_and_page(user_id)
                    # 重试一次
                    result = await _collect_one(client, page, lead)
                    st = result.get("status", "failed")
                except Exception as rel_err:
                    utils.logger.error(f"[contact_collector] retry re-launch failed: {rel_err}")

        if st == "done":
            if result.get("phone") or result.get("wechat"):
                success += 1
            else:
                no_contact += 1
        else:
            failed += 1
        completed += 1
        # 每完成一条更新进度(前端轮询可见百分比变化)
        _report_progress(
            completed, success, failed,
            f"进度 {completed}/{total}: 提取到 {success} 条, 失败 {failed} 条"
        )

    msg = f"采集完成: 提取到联系方式 {success} 条, 无联系方式 {no_contact} 条, 失败 {failed} 条"
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
        "stats": {"extracted": success, "no_contact": no_contact, "failed": failed, "total": total},
    }


# ==================== 后台自动采集循环 ====================
_LOOP_INTERVAL_SEC = 120  # 每2分钟扫描一次pending线索
_BATCH_PER_CYCLE = 3  # 每轮最多采集3条(避免长时间占用浏览器)


# 风控熔断器: 连续 N 次 "account blocked" 后,暂停自动循环一段时间避免加重风控
_BLOCKED_CONSECUTIVE_LIMIT = 3      # 连续 3 次风控即熔断
_BLOCKED_COOLDOWN_SEC = 1800        # 熔断后冷却 30 分钟
_blocked_counter = 0
_blocked_until_ts = 0.0             # 熔断到期时间(时间戳)


def _record_blocked_failure():
    """记录一次风控失败,达到阈值则触发熔断。"""
    global _blocked_counter, _blocked_until_ts
    _blocked_counter += 1
    if _blocked_counter >= _BLOCKED_CONSECUTIVE_LIMIT and _blocked_until_ts < time.time():
        _blocked_until_ts = time.time() + _BLOCKED_COOLDOWN_SEC
        utils.logger.warning(
            f"[contact_collector] 🚫 Risk-control circuit breaker tripped after "
            f"{_blocked_counter} consecutive blocked failures. Auto-collect paused for "
            f"{_BLOCKED_COOLDOWN_SEC//60} minutes (until {time.strftime('%H:%M:%S', time.localtime(_blocked_until_ts))})"
        )


def _record_success():
    """采集成功时重置计数器(部分成功不算熔断)。"""
    global _blocked_counter
    if _blocked_counter > 0:
        utils.logger.info(f"[contact_collector] risk-control counter reset (was {_blocked_counter})")
    _blocked_counter = 0


def _is_circuit_open() -> bool:
    """是否处于熔断状态。"""
    return _blocked_until_ts > time.time()


async def _contact_collector_loop():
    """后台循环:扫描 contact_status=pending 的线索,自动采集。"""
    print("[contact_collector] auto-collect loop started (interval=120s, batch=3)")
    while True:
        try:
            await asyncio.sleep(_LOOP_INTERVAL_SEC)
            # 风控熔断检查:熔断期内跳过自动采集
            if _is_circuit_open():
                remaining = int(_blocked_until_ts - time.time())
                utils.logger.info(f"[contact_collector] ⏸ auto-collect paused due to risk control, {remaining}s remaining")
                continue
            # 查找pending且无归属或归属当前用户的线索(跨用户轮流采集)
            async with get_session() as session:
                if session is None:
                    continue
                r = await session.execute(
                    select(CustomerLead)
                    .where(CustomerLead.contact_status == "pending")
                    .where(CustomerLead.sec_uid != "")
                    .where(CustomerLead.sec_uid.isnot(None))
                    .order_by(CustomerLead.add_ts.asc())
                    .limit(_BATCH_PER_CYCLE)
                )
                pending = r.scalars().all()
                if not pending:
                    continue
                pending_ids = [ld.id for ld in pending]
                owner_uid = pending[0].owner_user_id or ""

            print(f"[contact_collector] auto-collecting {len(pending_ids)} pending leads: {pending_ids}")
            result = await collect_contacts_batch(pending_ids, owner_uid)
            # 根据结果调整熔断计数器
            if isinstance(result, dict):
                stats = result.get("stats") or {}
                success_count = stats.get("extracted", 0) + stats.get("no_contact", 0)  # done 状态(有/无联系方式)
                failed_count = stats.get("failed", 0)
                # 全部失败(可能 account blocked)→ 计入熔断;有任何成功→ 重置
                if success_count == 0 and failed_count > 0:
                    _record_blocked_failure()
                elif success_count > 0:
                    _record_success()
        except asyncio.CancelledError:
            print("[contact_collector] auto-collect loop cancelled")
            raise
        except Exception as e:
            print(f"[contact_collector] loop error: {e}")
            await asyncio.sleep(15)


async def start_contact_collector_loop():
    """启动后台自动采集循环(由 main.py startup 调用)。"""
    asyncio.create_task(_contact_collector_loop())
