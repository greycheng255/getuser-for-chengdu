# -*- coding: utf-8 -*-
"""
自动化触达服务 - 使用 Playwright + CDP 模式自动发送私信
核心策略：CDP 连接真实 Chrome 浏览器，绕过自动化检测
"""
import asyncio
import json
import os
import random
import re
import shutil
import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

import config
from tools.cdp_browser import CDPBrowserManager
from tools import utils
from database.db_session import get_async_engine
from database.models import OutreachRecord, OutreachTaskModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, desc


# ==================== 数据模型 ====================

class OutreachStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OutreachStep:
    step: int
    name: str
    status: str
    message: str = ""
    screenshot: Optional[str] = None


@dataclass
class OutreachTask:
    id: str
    user_id: str
    sec_uid: str
    platform: str
    content: str
    status: OutreachStatus
    nickname: str = ""
    method: str = "direct_message"  # direct_message | comment_reply
    note_id: str = ""      # 视频/笔记ID，评论回复时需要
    comment_id: str = ""   # 评论ID，评论回复时需要
    steps: List[OutreachStep] = field(default_factory=list)
    result: Dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    updated_at: int = 0
    error_message: str = ""
    logs: List[str] = field(default_factory=list)


# ==================== 全局状态 ====================

_outreach_tasks: Dict[str, OutreachTask] = {}
_outreach_send_history: List[float] = []

# 频率限制配置（保守策略，降低风控风险）
MAX_SENDS_PER_HOUR = 30      # 每小时最多30条
MAX_SENDS_PER_DAY = 720       # 每天最多720条
MIN_INTERVAL_BETWEEN_SENDS = 15  # 两条消息之间最少间隔15秒

# 风控冷却状态
_risk_control_cooldown_until: float = 0  # 风控冷却截止时间
_consecutive_sends: int = 0  # 连续发送计数（用于递增间隔）
_last_send_time: float = 0  # 上次发送时间

# 浏览器实例缓存（复用，避免每次都重新启动）
_cached_browser: Optional[Dict[str, Any]] = None
_browser_last_used: float = 0
_BROWSER_CACHE_TTL = 600  # 10分钟未使用则关闭
_browser_lock = asyncio.Lock()  # 防止并发任务同时使用浏览器


# ==================== 工具函数 ====================

def _check_rate_limit() -> tuple[bool, str]:
    """检查发送频率限制 — 递增间隔策略
    
    策略：
    - 基础间隔120秒
    - 连续发送越多，间隔越长（递增策略）
    - 每小时不超过5条，每天不超过20条
    - 风控冷却期内禁止发送
    """
    now = time.time()
    global _outreach_send_history, _risk_control_cooldown_until, _consecutive_sends
    _outreach_send_history = [t for t in _outreach_send_history if now - t < 86400]

    # 检查风控冷却
    if now < _risk_control_cooldown_until:
        remaining = int(_risk_control_cooldown_until - now)
        return False, f"风控冷却中，请等待 {remaining} 秒"

    sends_last_hour = len([t for t in _outreach_send_history if now - t < 3600])
    if sends_last_hour >= MAX_SENDS_PER_HOUR:
        return False, f"每小时发送限制已达上限 ({MAX_SENDS_PER_HOUR}次)"

    if len(_outreach_send_history) >= MAX_SENDS_PER_DAY:
        return False, f"每日发送限制已达上限 ({MAX_SENDS_PER_DAY}次)"

    if _outreach_send_history:
        elapsed = now - max(_outreach_send_history)
        # 递增间隔：连续发送越多，需要等待越久
        # 前10条：15秒间隔，11-20条：30秒，21-30条：60秒，30条以上：120秒
        dynamic_interval = MIN_INTERVAL_BETWEEN_SENDS
        if _consecutive_sends > 30:
            dynamic_interval = 120
        elif _consecutive_sends > 20:
            dynamic_interval = 60
        elif _consecutive_sends > 10:
            dynamic_interval = 30
        
        # 加上随机抖动（±5秒）
        dynamic_interval += random.randint(-5, 5)
        
        if elapsed < dynamic_interval:
            return False, f"发送太频繁，请等待 {int(dynamic_interval - elapsed)} 秒"

    return True, ""


def _enter_risk_control_cooldown(duration: int = 1800):
    """进入风控冷却期（默认30分钟）
    
    检测到风控信号时调用，暂停发送一段时间
    """
    global _risk_control_cooldown_until, _consecutive_sends
    _risk_control_cooldown_until = time.time() + duration
    _consecutive_sends = 0  # 重置连续发送计数
    utils.logger.warning(f"[OutreachAutomation] Entered risk control cooldown for {duration}s")


def _record_send():
    global _consecutive_sends
    _consecutive_sends += 1
    _outreach_send_history.append(time.time())


def _randomize_content(content: str) -> str:
    """对消息内容进行深度随机化，避免被风控识别为群发
    
    策略：
    1. 随机添加不同风格的问候语
    2. 随机替换同义词
    3. 随机插入零宽字符（不可见但使文本不同）
    4. 随机调整标点符号
    5. 随机重排句子顺序（如果有多句）
    """
    result = content
    
    # 1. 问候语随机化
    greetings = [
        "", "你好 ", "嗨 ", "哈喽 ", "hi ", "你好呀 ",
        "朋友你好 ", "嘿 ", "亲 ", "同学你好 ", "你好呀~ ",
    ]
    greetings_with_emoji = [
        "", "😊 ", "👋 ", "✨ ", "🎉 ", "💫 ", "🌟 ", "😄 ",
    ]
    
    # 2. 结尾随机化
    endings = [
        "", " ~", " 😊", " 👍", " 希望能帮到你", " 有问题随时问",
        " 期待你的回复", " 随时联系我哦", " 可以试试看",
        "", "",  # 空结尾概率更高
    ]
    
    # 3. 同义词替换表（更丰富）
    replacements = [
        ("平台", ["平台", "工具", "产品", "应用", "网站"]),
        ("注册", ["注册", "开通", "体验", "试用", "加入"]),
        ("有问题", ["有问题", "有需求", "有想法", "想知道", "感兴趣"]),
        ("可以", ["可以", "能够", "没问题", "方便", "支持"]),
        ("需要", ["需要", "想要", "有兴趣", "想了解", "打算"]),
        ("免费", ["免费", "0元", "不花钱", "白嫖", "送"]),
        ("推荐", ["推荐", "安利", "分享", "介绍", "推荐个"]),
        ("关注", ["关注", "留意", "看看", "了解下", "试下"]),
        ("私信", ["私信", "留言", "发消息", "联系"]),
        ("链接", ["链接", "地址", "网址", "入口", "方式"]),
        ("工具", ["工具", "神器", "利器", "助手", "帮手"]),
        ("大模型", ["大模型", "AI模型", "语言模型", "智能模型"]),
        ("便宜", ["便宜", "划算", "实惠", "性价比高", "超值"]),
        ("功能", ["功能", "特点", "亮点", "能力"]),
    ]
    
    # 4. 标点符号变体
    punctuation_variants = [
        ("，", ["，", ",", "、"]),
        ("。", ["。", ".", "~", "！"]),
        ("！", ["！", "!", "~"]),
        ("？", ["？", "?"]),
    ]
    
    # 应用随机化
    # 问候语
    if not any(content.startswith(g) for g in greetings if g):
        result = random.choice(greetings) + random.choice(greetings_with_emoji) + result
    else:
        # 已有问候语，随机加个emoji
        if random.random() > 0.5:
            result = random.choice(greetings_with_emoji) + result
    
    # 结尾
    result = result + random.choice(endings)
    
    # 同义词替换（每次只替换1-2个）
    replace_count = 0
    max_replaces = random.randint(1, 2)
    shuffled_replacements = list(replacements)
    random.shuffle(shuffled_replacements)
    for word, alternatives in shuffled_replacements:
        if word in result and replace_count < max_replaces:
            result = result.replace(word, random.choice(alternatives), 1)
            replace_count += 1
    
    # 标点符号变体（随机替换1-2个）
    punct_count = 0
    for old, variants in punctuation_variants:
        if old in result and punct_count < 2 and random.random() > 0.6:
            result = result.replace(old, random.choice(variants), 1)
            punct_count += 1
    
    # 5. 插入零宽字符使每条消息在字节层面不同（对用户不可见）
    zero_width_chars = ['\u200b', '\u200c', '\u200d', '\ufeff']  # 零宽空格、零宽非连接符等
    # 在随机位置插入1-2个零宽字符
    if len(result) > 5:
        pos = random.randint(2, len(result) - 2)
        result = result[:pos] + random.choice(zero_width_chars) + result[pos:]
    
    return result


def _clean_content_for_risk(content: str) -> str:
    """深度清理消息内容，避免被风控识别为广告
    
    注意：此函数在 _obfuscate_link_in_text 之后运行，
    链接已经被混淆处理过，不应再对域名进行正则匹配替换
    """
    cleaned = content
    # 替换敏感词（不再对域名做正则处理，避免破坏已混淆的链接）
    promo_words = {
        '链接给你': '地址发你', '注册送': '新用户有', '注册': '开通',
        '免费额度': '体验次数', 'token': '点数',
        '一站式AI工具平台': 'AI工具箱',
        '集成ChatGPT、Claude、Gemini等主流大模型': '多个主流模型都能用',
        '加微信': '加V', '微信号': 'V', '加我': '联系我',
        '优惠': '福利', '折扣': '特价', '促销': '活动',
    }
    for old, new in promo_words.items():
        if old in cleaned:
            cleaned = cleaned.replace(old, new)
    return cleaned


async def _reply_to_comment_via_api(page, aweme_id: str, comment_id: str, content: str) -> tuple[bool, str]:
    """通过 DouYinClient API 回复评论（需要浏览器上下文生成 a_bogus 签名）
    
    接口: POST /aweme/v1/web/comment/publish
    参数: aweme_id(视频ID), reply_id(评论ID), text(回复内容)
    """
    from media_platform.douyin.client import DouYinClient
    from .cookie_manager import get_cookie
    from tools.crawler_util import convert_str_cookie_to_dict

    try:
        # 获取 cookies
        cookie_str = get_cookie("dy")
        if not cookie_str:
            return False, "未找到抖音 Cookie"

        cookie_dict = convert_str_cookie_to_dict(cookie_str)
        
        # 检查关键 cookie
        sessionid = cookie_dict.get("sessionid", "")
        if not sessionid:
            return False, "Cookie 中缺少 sessionid，无法回复评论"

        # 清理回复内容
        msg_content = _randomize_content(content)
        msg_content = _clean_content_for_risk(msg_content)

        # 构建 Cookie 头
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())

        # 创建 DouYinClient（利用浏览器页面生成 a_bogus 签名）
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            "Referer": f"https://www.douyin.com/video/{aweme_id}",
            "Origin": "https://www.douyin.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookie_header,
        }
        client = DouYinClient(
            headers=headers,
            playwright_page=page,
            cookie_dict=cookie_dict,
        )

        # 发送评论回复
        uri = "/aweme/v1/web/comment/publish"
        data = {
            "aweme_id": aweme_id,
            "reply_id": comment_id,
            "text": msg_content,
            "text_extra": "[]",
            "item_type": "0",
        }

        result = await client.post(uri, data=data, headers=headers)
        status_code = result.get("status_code", -1)
        
        if status_code == 0:
            utils.logger.info(f"[OutreachAutomation] Comment reply API success: aweme_id={aweme_id}, comment_id={comment_id}")
            return True, ""
        else:
            error_msg = result.get("status_msg", "") or result.get("description", "") or f"status_code={status_code}"
            utils.logger.warning(f"[OutreachAutomation] Comment reply API failed: {error_msg}, response: {result}")
            return False, f"API 返回错误: {error_msg}"

    except Exception as e:
        error_str = str(e)
        if "account blocked" in error_str:
            utils.logger.warning(f"[OutreachAutomation] Comment reply API blocked (empty response), may need cookie refresh")
            return False, "请求被拦截（空响应），可能需要更新 Cookie"
        utils.logger.error(f"[OutreachAutomation] Comment reply API error: {e}")
        return False, f"API 请求异常: {e}"


async def _reply_to_comment_on_page(page, content: str, comment_id: str = "", nickname: str = "") -> tuple[bool, str]:
    """在抖音视频页面回复评论
    
    流程：
    1. 滚动到评论区
    2. 找到目标评论（通过comment_id或nickname）
    3. 点击"回复"按钮
    4. 输入回复内容
    5. 发送
    """
    try:
        # 1. 确保评论区可见 — 滚动到评论区域
        _append_log_task = None  # 不使用全局task引用
        
        # 滚动页面找到评论区
        comment_area_found = await page.evaluate("""() => {
            // 尝试找到评论区容器
            const selectors = [
                '[class*="comment"]', '[class*="Comment"]',
                '[data-e2e="comment-list"]', '[class*="commentList"]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    return true;
                }
            }
            // 如果没找到评论区容器，滚动页面中部
            window.scrollTo(0, document.body.scrollHeight * 0.4);
            return false;
        }""")
        await asyncio.sleep(random.uniform(2, 4))
        
        # 2. 查找目标评论的"回复"按钮
        # 策略：先通过comment_id精确查找，再通过昵称模糊查找
        reply_btn_found = False
        
        if comment_id:
            # 尝试通过评论ID定位（抖音评论DOM中可能包含data属性）
            try:
                # 查找包含该评论ID的元素
                comment_el = await page.evaluate(f"""() => {{
                    // 查找所有评论元素
                    const allComments = document.querySelectorAll('[class*="commentItem"], [class*="CommentItem"], [data-e2e="comment-item"]');
                    for (const el of allComments) {{
                        // 检查元素或子元素中是否包含目标昵称
                        const text = el.innerText || '';
                        if (text.includes('{nickname}')) {{
                            return el;
                        }}
                    }}
                    return null;
                }}""")
            except Exception:
                pass
        
        # 多策略查找回复按钮
        reply_selectors = [
            # 抖音评论区的回复按钮
            'span:has-text("回复")',
            'div:has-text("回复")',
            'a:has-text("回复")',
            'button:has-text("回复")',
            '[class*="reply"]',
            '[class*="Reply"]',
        ]
        
        # 先滚动评论区让更多评论加载
        for scroll_round in range(3):
            await page.evaluate("window.scrollBy(0, 300)")
            await asyncio.sleep(random.uniform(1, 2))
        
        # 回滚到顶部附近
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.3)")
        await asyncio.sleep(random.uniform(2, 3))
        
        # 查找目标评论 — 通过昵称匹配
        target_comment_idx = -1
        if nickname:
            try:
                # 找到所有评论中的昵称
                target_comment_idx = await page.evaluate(f"""() => {{
                    const comments = document.querySelectorAll('[class*="commentItem"], [class*="CommentItem"], [data-e2e="comment-item"], [class*="comment-item"]');
                    for (let i = 0; i < comments.length; i++) {{
                        const text = comments[i].innerText || '';
                        if (text.includes('{nickname}')) {{
                            return i;
                        }}
                    }}
                    return -1;
                }}""")
            except Exception:
                target_comment_idx = -1
        
        # 查找回复按钮
        for selector in reply_selectors:
            try:
                loc = page.locator(selector)
                count = await loc.count()
                if count == 0:
                    continue
                
                # 如果找到了目标评论的索引，优先点击该评论的回复按钮
                if target_comment_idx >= 0 and target_comment_idx < count:
                    el = loc.nth(target_comment_idx)
                    if await el.is_visible():
                        box = await el.bounding_box()
                        if box and box['y'] > 100:
                            await el.click()
                            reply_btn_found = True
                            break
                
                # 否则遍历所有回复按钮，找到可见的
                for i in range(min(count, 20)):
                    el = loc.nth(i)
                    if await el.is_visible():
                        box = await el.bounding_box()
                        if box and box['y'] > 100:
                            # 检查这个回复按钮附近是否有目标昵称
                            if nickname:
                                parent_text = await page.evaluate(f"""() => {{
                                    const btns = document.querySelectorAll('{selector.replace("'", "\\'")}');
                                    if (btns[{i}]) {{
                                        let parent = btns[{i}].closest('[class*="commentItem"], [class*="CommentItem"], [class*="comment-item"]');
                                        return parent ? parent.innerText : '';
                                    }}
                                    return '';
                                }}""")
                                if nickname not in (parent_text or ""):
                                    continue
                            await el.click()
                            reply_btn_found = True
                            break
                if reply_btn_found:
                    break
            except Exception:
                continue
        
        if not reply_btn_found:
            return False, "未找到回复按钮"
        
        # 3. 等待回复输入框出现
        await asyncio.sleep(random.uniform(1, 2))
        
        # 查找输入框 — 扩展选择器
        input_selectors = [
            'textarea[placeholder*="回复"]',
            'textarea[placeholder*="评论"]',
            'textarea[placeholder*="说"]',
            'textarea[placeholder*="输入"]',
            'textarea[placeholder*="友善"]',
            'div[contenteditable="true"]',
            'textarea',
            'input[type="text"]',
            '[class*="commentInput"] textarea',
            '[class*="comment-input"] textarea',
            '[class*="editor"] [contenteditable]',
            '[data-e2e="comment-input"] textarea',
            '[data-e2e="comment-input"] [contenteditable]',
        ]
        
        input_found = False
        used_selector = ""
        for selector in input_selectors:
            try:
                loc = page.locator(selector)
                if await loc.count() > 0:
                    el = loc.first
                    if await el.is_visible():
                        await el.click()
                        await asyncio.sleep(random.uniform(0.5, 1))
                        input_found = True
                        used_selector = selector
                        break
            except Exception:
                continue
        
        if not input_found:
            # 尝试通过坐标点击评论输入区域
            _append_log_fn(f"⚠️ 选择器未找到输入框，尝试坐标点击...")
            input_area = await page.evaluate("""() => {
                // 查找评论区输入框容器
                const containers = document.querySelectorAll('[class*="commentInput"], [class*="comment-input"], [class*="CommentInput"], [data-e2e="comment-input"]');
                for (const ct of containers) {
                    const rect = ct.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 20) {
                        return {x: rect.x + rect.width/2, y: rect.y + rect.height/2, w: rect.width, h: rect.height};
                    }
                }
                // 查找所有 textarea 和 contenteditable
                const textareas = document.querySelectorAll('textarea, [contenteditable="true"]');
                for (const ta of textareas) {
                    const rect = ta.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 15 && rect.y > 100) {
                        return {x: rect.x + rect.width/2, y: rect.y + rect.height/2, w: rect.width, h: rect.height};
                    }
                }
                return null;
            }""")
            if input_area:
                await page.mouse.click(input_area['x'], input_area['y'])
                await asyncio.sleep(random.uniform(1, 2))
                input_found = True
                used_selector = "coordinate_click"
        
        if not input_found:
            return False, "未找到回复输入框"
        
        # 4. 输入回复内容
        msg_content = _randomize_content(content)
        msg_content = _clean_content_for_risk(msg_content)
        
        # 模拟真人打字
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        if used_selector == "coordinate_click":
            # 坐标点击后，直接用键盘输入
            await page.keyboard.type(msg_content, delay=random.randint(30, 80))
        else:
            # 使用 Playwright 的 fill 方法
            try:
                await page.locator(used_selector).first.fill(msg_content)
            except Exception:
                # 如果 fill 失败，尝试 type
                try:
                    await page.keyboard.type(msg_content, delay=random.randint(30, 80))
                except Exception as type_err:
                    return False, f"输入回复内容失败: {type_err}"
        
        await asyncio.sleep(random.uniform(1, 2))
        
        # 5. 发送回复
        # 查找发送按钮
        send_selectors = [
            'button:has-text("发送")',
            'button:has-text("回复")',
            '[class*="submit"]',
            '[class*="Submit"]',
            '[class*="send"]',
            '[class*="Send"]',
        ]
        
        send_clicked = False
        for sel in send_selectors:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    el = loc.last  # 发送按钮通常在最后
                    if await el.is_visible():
                        await el.click()
                        send_clicked = True
                        break
            except Exception:
                continue
        
        if not send_clicked:
            # 尝试按 Enter 发送
            try:
                await page.keyboard.press('Enter')
                send_clicked = True
            except Exception:
                pass
        
        if not send_clicked:
            return False, "未找到发送按钮"
        
        await asyncio.sleep(random.uniform(2, 4))
        return True, ""
        
    except Exception as e:
        return False, str(e)


async def _simulate_human_browse(page, duration: float = None):
    """模拟真人浏览行为 — 滚动、鼠标移动、随机停顿
    
    关键特征：
    - 非匀速滚动（加速→匀速→减速）
    - 鼠标轨迹有弧度（不是直线）
    - 随机停顿（阅读内容）
    - 偶尔回滚（重新看内容）
    """
    if duration is None:
        duration = random.uniform(8, 20)
    
    start_time = time.time()
    
    while time.time() - start_time < duration:
        action = random.choices(
            ['scroll_down', 'scroll_up', 'mouse_move', 'pause', 'read'],
            weights=[40, 10, 25, 15, 10],
            k=1
        )[0]
        
        if action == 'scroll_down':
            # 模拟真人滚动：先加速后减速
            scroll_distance = random.randint(100, 500)
            steps = random.randint(3, 8)
            for step in range(steps):
                # 加速→匀速→减速的滚动量
                progress = step / steps
                if progress < 0.3:
                    factor = progress / 0.3 * 0.5  # 加速段
                elif progress > 0.7:
                    factor = (1 - progress) / 0.3 * 0.5 + 0.5  # 减速段
                else:
                    factor = 1.0  # 匀速段
                scroll_step = int(scroll_distance / steps * factor * 2)
                if scroll_step > 0:
                    await page.mouse.wheel(0, scroll_step)
                await asyncio.sleep(random.uniform(0.02, 0.08))
            await asyncio.sleep(random.uniform(0.3, 1.0))
            
        elif action == 'scroll_up':
            scroll_distance = random.randint(50, 200)
            await page.mouse.wheel(0, -scroll_distance)
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
        elif action == 'mouse_move':
            # 模拟真人鼠标移动（贝塞尔曲线轨迹）
            target_x = random.randint(200, 1700)
            target_y = random.randint(100, 900)
            current_pos = await page.evaluate("() => ({ x: window._lastMouseX || 500, y: window._lastMouseY || 400 })")
            steps = random.randint(5, 15)
            for step in range(steps):
                t = step / steps
                # 简单贝塞尔曲线
                mid_x = (current_pos.get('x', 500) + target_x) / 2 + random.randint(-50, 50)
                mid_y = (current_pos.get('y', 400) + target_y) / 2 + random.randint(-50, 50)
                x = (1-t)**2 * current_pos.get('x', 500) + 2*(1-t)*t * mid_x + t**2 * target_x
                y = (1-t)**2 * current_pos.get('y', 400) + 2*(1-t)*t * mid_y + t**2 * target_y
                await page.mouse.move(int(x), int(y))
                await asyncio.sleep(random.uniform(0.01, 0.05))
            # 记录鼠标位置
            await page.evaluate(f"() => {{ window._lastMouseX = {target_x}; window._lastMouseY = {target_y}; }}")
            await asyncio.sleep(random.uniform(0.2, 0.8))
            
        elif action == 'pause':
            # 随机停顿（模拟阅读或思考）
            await asyncio.sleep(random.uniform(1.0, 4.0))
            
        elif action == 'read':
            # 模拟阅读：鼠标移到某个位置并停留
            read_x = random.randint(300, 1200)
            read_y = random.randint(200, 700)
            await page.mouse.move(read_x, read_y, steps=5)
            await asyncio.sleep(random.uniform(2.0, 5.0))


async def _simulate_human_typing(page, text: str, input_loc=None):
    """模拟真人打字 — 非匀速、有停顿、偶尔退格修改
    
    关键特征：
    - 打字速度在30-80ms/字之间波动
    - 标点符号前停顿更长
    - 偶尔打错字再退格修改
    - 中英文切换时有短暂停顿
    """
    total_chars = len(text)
    
    for i, char in enumerate(text):
        # 基础延迟
        if char in '，。！？、；：':
            # 标点符号前停顿更长（思考措辞）
            delay = random.uniform(80, 200)
        elif char in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ':
            # 英文字母打字更快
            delay = random.uniform(20, 50)
        elif char in '0123456789':
            # 数字稍慢
            delay = random.uniform(40, 80)
        else:
            # 中文正常速度
            delay = random.uniform(30, 70)
        
        # 偶尔在句子中间停顿（思考）
        if random.random() < 0.05 and i > 0 and i < total_chars - 1:
            delay += random.uniform(300, 800)
        
        # 偶尔打错字再退格（1%概率）
        if random.random() < 0.01 and i > 2 and i < total_chars - 2:
            wrong_char = random.choice('的一是不了人我在')
            if input_loc:
                await input_loc.type(wrong_char, delay=0)
            else:
                await page.keyboard.type(wrong_char, delay=0)
            await asyncio.sleep(random.uniform(100, 300) / 1000)
            # 退格删除
            await page.keyboard.press('Backspace')
            await asyncio.sleep(random.uniform(100, 200) / 1000)
        
        # 输入正确字符
        if input_loc:
            await input_loc.type(char, delay=0)
        else:
            await page.keyboard.type(char, delay=0)
        
        await asyncio.sleep(delay / 1000)


def _is_headless_env() -> bool:
    return os.environ.get("DISPLAY") is None or os.environ.get("HEADLESS") == "1"


def _find_existing_chrome_cdp_port() -> Optional[int]:
    """查找已有的Chrome CDP调试端口 - 优先返回搜索任务的9222端口"""
    import subprocess
    try:
        result = subprocess.run(["pgrep", "-a", "chrome"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            ports = []
            for line in result.stdout.strip().split("\n"):
                import re
                match = re.search(r'--remote-debugging-port=(\d+)', line)
                if match:
                    port = int(match.group(1))
                    # 验证端口是否可连接
                    try:
                        import socket
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.settimeout(2)
                            s.connect(("localhost", port))
                            ports.append(port)
                    except Exception:
                        continue
            # 优先返回9222（搜索任务的浏览器，有完整登录状态）
            if 9222 in ports:
                return 9222
            # 其次返回其他端口
            if ports:
                return ports[0]
    except Exception:
        pass
    return None


def _cleanup_stale_processes():
    """清理无效的 Xvfb 和 Chrome 孤儿进程，释放系统资源
    
    策略：
    1. 检查每个 Xvfb 进程对应的 DISPLAY 是否有效
    2. 检查是否有 Chrome 进程连接到该 DISPLAY
    3. 无效的 Xvfb 和对应的孤儿 Chrome 进程一并清理
    """
    try:
        import subprocess
        
        # 获取当前有效 DISPLAY
        current_display = os.environ.get("DISPLAY", "")
        
        # 查找所有 Xvfb 进程
        result = subprocess.run(["pgrep", "-a", "Xvfb"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return  # 没有 Xvfb 进程
        
        xvfb_to_kill = []
        valid_displays = set()
        
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pid = int(parts[0])
            display = parts[1] if parts[1].startswith(":") else ""
            if not display:
                continue
            
            # 当前正在使用的 DISPLAY 保留
            if display == current_display:
                valid_displays.add(display)
                continue
            
            # 检查这个 DISPLAY 是否有效
            try:
                check = subprocess.run(
                    ["xdpyinfo", "-display", display],
                    capture_output=True, timeout=3,
                    env={**os.environ, "DISPLAY": display}
                )
                if check.returncode == 0:
                    valid_displays.add(display)
                    # 有效的 DISPLAY，检查是否有 Chrome 在用
                    chrome_check = subprocess.run(
                        ["pgrep", "-a", "chrome"],
                        capture_output=True, text=True, timeout=5
                    )
                    has_chrome = False
                    if chrome_check.returncode == 0:
                        for chrome_line in chrome_check.stdout.strip().split("\n"):
                            if display in chrome_line or f"DISPLAY={display}" in chrome_line:
                                has_chrome = True
                                break
                    if has_chrome:
                        continue  # 有 Chrome 在用，保留
                    # 有效的 Xvfb 但没有 Chrome 在用，可以清理
                    xvfb_to_kill.append((pid, display))
                else:
                    # 无效的 Xvfb，清理
                    xvfb_to_kill.append((pid, display))
            except Exception:
                # 检查失败，可能是无效的 Xvfb
                xvfb_to_kill.append((pid, display))
        
        # 清理无效的 Xvfb
        for pid, display in xvfb_to_kill:
            try:
                os.kill(pid, 9)
                # 清理 lock 文件
                display_num = display.lstrip(":")
                lock_file = f"/tmp/.X{display_num}-lock"
                if os.path.exists(lock_file):
                    os.remove(lock_file)
                utils.logger.info(f"[OutreachAutomation] Cleaned up stale Xvfb PID={pid} display={display}")
            except ProcessLookupError:
                pass
            except Exception as e:
                utils.logger.warning(f"[OutreachAutomation] Failed to kill Xvfb PID={pid}: {e}")
        
        # 清理孤儿 Chrome 进程（没有有效 DISPLAY 的）
        if xvfb_to_kill:
            chrome_result = subprocess.run(["pgrep", "-a", "chrome"], capture_output=True, text=True, timeout=5)
            if chrome_result.returncode == 0:
                killed_displays = {d for _, d in xvfb_to_kill}
                for chrome_line in chrome_result.stdout.strip().split("\n"):
                    parts = chrome_line.split()
                    if len(parts) < 1:
                        continue
                    try:
                        chrome_pid = int(parts[0])
                    except ValueError:
                        continue
                    # 检查这个 Chrome 是否属于被清理的 DISPLAY
                    # 通过检查 /proc/PID/environ 获取其 DISPLAY
                    try:
                        with open(f"/proc/{chrome_pid}/environ", "rb") as f:
                            env_data = f.read().decode("utf-8", errors="ignore")
                            chrome_display = ""
                            for env_var in env_data.split("\0"):
                                if env_var.startswith("DISPLAY="):
                                    chrome_display = env_var.split("=", 1)[1]
                                    break
                            if chrome_display in killed_displays:
                                os.kill(chrome_pid, 9)
                                utils.logger.info(f"[OutreachAutomation] Cleaned up orphan Chrome PID={chrome_pid} display={chrome_display}")
                    except (FileNotFoundError, ProcessLookupError):
                        pass
                    except Exception:
                        pass
        
        if xvfb_to_kill:
            utils.logger.info(f"[OutreachAutomation] Cleaned up {len(xvfb_to_kill)} stale Xvfb processes")
    
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Error during stale process cleanup: {e}")


def _ensure_xvfb():
    """在无头环境中自动启动 Xvfb 虚拟显示器（复用已有实例，自动清理无效实例）"""
    # 先清理无效的 Xvfb 和 Chrome 孤儿进程
    _cleanup_stale_processes()
    
    # 如果 DISPLAY 已经设置，检查是否有效
    current_display = os.environ.get("DISPLAY", "")
    if current_display:
        # 验证 DISPLAY 是否可用
        try:
            import subprocess
            result = subprocess.run(["xdpyinfo"], capture_output=True, timeout=3,
                                   env={**os.environ, "DISPLAY": current_display})
            if result.returncode == 0:
                return  # DISPLAY 有效，无需操作
        except Exception:
            pass
        # DISPLAY 设置了但无效，清除它
        del os.environ["DISPLAY"]

    if not shutil.which("Xvfb"):
        utils.logger.warning("[OutreachAutomation] Xvfb not found, CDP headed mode may not work")
        return

    # 查找已有的 Xvfb 实例
    try:
        import subprocess
        result = subprocess.run(["pgrep", "-a", "Xvfb"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].startswith(":"):
                    display = parts[1]
                    # 验证这个 DISPLAY 是否可用
                    try:
                        check = subprocess.run(["xdpyinfo"], capture_output=True, timeout=3,
                                              env={**os.environ, "DISPLAY": display})
                        if check.returncode == 0:
                            os.environ["DISPLAY"] = display
                            utils.logger.info(f"[OutreachAutomation] Reusing existing Xvfb on {display}")
                            return
                    except Exception:
                        continue
    except Exception:
        pass

    # 启动新的 Xvfb 实例
    try:
        import subprocess
        display_num = 99
        while os.path.exists(f"/tmp/.X{display_num}-lock"):
            display_num += 1
        proc = subprocess.Popen(
            ["Xvfb", f":{display_num}", "-screen", "0", "1920x1080x24",
             "-nolisten", "tcp", "-noreset"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = f":{display_num}"
        time.sleep(1)
        if proc.poll() is not None:
            utils.logger.warning("[OutreachAutomation] Xvfb exited unexpectedly")
            return
        utils.logger.info(f"[OutreachAutomation] Xvfb started on :{display_num} (PID={proc.pid})")
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Failed to start Xvfb: {e}")


def get_outreach_task(task_id: str) -> Optional[OutreachTask]:
    """从内存获取任务（同步，用于执行期间快速访问）"""
    return _outreach_tasks.get(task_id)


async def get_outreach_task_from_db(task_id: str) -> Optional[OutreachTask]:
    """从数据库获取任务（内存没有时使用）"""
    task = _outreach_tasks.get(task_id)
    if task:
        return task
    try:
        engine = get_async_engine(config.SAVE_DATA_OPTION)
        if not engine:
            return None
        AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(OutreachTaskModel).where(OutreachTaskModel.id == task_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            task = _db_row_to_task(row)
            _outreach_tasks[task_id] = task
            return task
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Failed to load task from DB: {e}")
        return None


async def get_all_outreach_tasks(limit: int = 100, offset: int = 0) -> List[OutreachTask]:
    """从数据库获取所有任务列表"""
    try:
        engine = get_async_engine(config.SAVE_DATA_OPTION)
        if not engine:
            return list(_outreach_tasks.values())
        AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(OutreachTaskModel)
                .order_by(desc(OutreachTaskModel.created_at))
                .limit(limit).offset(offset)
            )
            rows = result.scalars().all()
            tasks = []
            for row in rows:
                task = _db_row_to_task(row)
                _outreach_tasks[task.id] = task  # 同步到内存缓存
                tasks.append(task)
            return tasks
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Failed to load tasks from DB: {e}")
        return list(_outreach_tasks.values())


def _task_to_db_dict(task: OutreachTask) -> dict:
    """将 OutreachTask 转换为数据库字段字典"""
    steps_data = [{"step": s.step, "name": s.name, "status": s.status,
                   "message": s.message, "screenshot": s.screenshot or ""} for s in task.steps]
    screenshot = ""
    for s in task.steps:
        if s.screenshot:
            screenshot = s.screenshot
            break
    return {
        "id": task.id,
        "user_id": task.user_id,
        "sec_uid": task.sec_uid,
        "platform": task.platform,
        "content": task.content,
        "nickname": task.nickname,
        "status": task.status.value if isinstance(task.status, OutreachStatus) else task.status,
        "error_message": task.error_message,
        "result": json.dumps(task.result, ensure_ascii=False),
        "steps": json.dumps(steps_data, ensure_ascii=False),
        "logs": json.dumps(task.logs, ensure_ascii=False),
        "screenshot": screenshot,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _db_row_to_task(row: OutreachTaskModel) -> OutreachTask:
    """将数据库行转换为 OutreachTask"""
    steps_data = json.loads(row.steps or "[]")
    steps = [OutreachStep(s["step"], s["name"], s["status"],
                          s.get("message", ""), s.get("screenshot")) for s in steps_data]
    return OutreachTask(
        id=row.id, user_id=row.user_id, sec_uid=row.sec_uid,
        platform=row.platform, content=row.content, nickname=row.nickname,
        status=OutreachStatus(row.status),
        steps=steps,
        result=json.loads(row.result or "{}"),
        logs=json.loads(row.logs or "[]"),
        error_message=row.error_message or "",
        created_at=row.created_at or 0,
        updated_at=row.updated_at or 0,
    )


async def _sync_task_to_db(task: OutreachTask):
    """将任务状态同步到数据库"""
    try:
        engine = get_async_engine(config.SAVE_DATA_OPTION)
        if not engine:
            return
        AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(OutreachTaskModel).where(OutreachTaskModel.id == task.id)
            )
            row = result.scalar_one_or_none()
            data = _task_to_db_dict(task)
            if row:
                for k, v in data.items():
                    setattr(row, k, v)
            else:
                row = OutreachTaskModel(**data)
                session.add(row)
            await session.commit()
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Failed to sync task to DB: {e}")


async def create_outreach_task_data(
    user_id: str, sec_uid: str, platform: str, content: str, nickname: str = "",
    method: str = "direct_message", note_id: str = "", comment_id: str = "",
) -> OutreachTask:
    task_id = f"outreach_{uuid.uuid4().hex[:8]}"
    now = int(time.time() * 1000)
    
    # 根据触达方式设置不同的步骤
    if method == "comment_reply":
        steps = [
            OutreachStep(1, "启动浏览器", "pending"),
            OutreachStep(2, "打开视频页面", "pending"),
            OutreachStep(3, "回复评论", "pending"),
            OutreachStep(4, "确认结果", "pending"),
        ]
    else:
        steps = [
            OutreachStep(1, "启动浏览器", "pending"),
            OutreachStep(2, "访问用户主页", "pending"),
            OutreachStep(3, "发送私信", "pending"),
            OutreachStep(4, "确认结果", "pending"),
        ]
    
    task = OutreachTask(
        id=task_id, user_id=user_id, sec_uid=sec_uid, platform=platform,
        content=content, nickname=nickname, status=OutreachStatus.PENDING,
        method=method, note_id=note_id, comment_id=comment_id,
        steps=steps,
        created_at=now, updated_at=now,
    )
    _outreach_tasks[task_id] = task
    # 同步到数据库
    await _sync_task_to_db(task)
    return task


def _append_log(task: OutreachTask, message: str):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    task.logs.append(f"[{timestamp}] {message}")
    task.updated_at = int(time.time() * 1000)


def _update_step(task: OutreachTask, step_num: int, status: str, message: str = "", screenshot: Optional[str] = None):
    for step in task.steps:
        if step.step == step_num:
            step.status = status
            step.message = message
            if screenshot:
                step.screenshot = screenshot
            break
    if message:
        _append_log(task, f"Step {step_num} [{status}]: {message}")
    task.updated_at = int(time.time() * 1000)


async def _save_debug_screenshot(page: Page, task_id: str, step_name: str) -> Optional[str]:
    try:
        screenshot_dir = os.path.join(os.getcwd(), "data", "outreach_screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        filename = f"{task_id}_{step_name}_{int(time.time())}.png"
        filepath = os.path.join(screenshot_dir, filename)
        await page.screenshot(path=filepath, full_page=True)
        return filename
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Screenshot save failed: {e}")
        return None


async def _save_outreach_record(task: OutreachTask, status: str, error_message: str = "", screenshot: str = ""):
    try:
        engine = get_async_engine(config.SAVE_DATA_OPTION)
        if engine:
            AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with AsyncSessionFactory() as session:
                if task.platform == "xhs":
                    user_url = f"https://www.xiaohongshu.com/user/profile/{task.user_id}"
                else:
                    user_url = f"https://www.douyin.com/user/{task.sec_uid}"
                record = OutreachRecord(
                    task_id=task.id, user_id=task.user_id, sec_uid=task.sec_uid,
                    platform=task.platform, nickname=task.nickname, user_url=user_url,
                    message_content=task.content, status=status,
                    error_message=error_message, screenshot=screenshot,
                    send_time=int(time.time() * 1000), add_ts=int(time.time() * 1000),
                )
                session.add(record)
                await session.commit()
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Failed to save outreach record: {e}")


# ==================== 核心流程 ====================

async def _launch_browser_for_outreach(platform: str = "dy"):
    """启动浏览器 - 优先复用已有实例，CDP 模式优先，自动启动 Xvfb"""
    global _cached_browser, _browser_last_used

    # 检查是否有可复用的浏览器实例
    now = time.time()
    if _cached_browser is not None:
        # 检查是否过期
        if now - _browser_last_used > _BROWSER_CACHE_TTL:
            utils.logger.info("[OutreachAutomation] Cached browser expired, closing...")
            await _close_cached_browser()
        else:
            # 验证浏览器是否仍然可用
            try:
                page = _cached_browser["page"]
                # 简单检查页面是否还活着
                await page.evaluate("() => document.title")
                # 刷新 Cookie 确保登录状态
                await _load_platform_cookies(_cached_browser["browser_context"], platform)
                await page.reload(wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                login_ok = await _verify_login(page, platform)
                if login_ok:
                    utils.logger.info("[OutreachAutomation] ✅ Reusing cached browser (login OK)")
                    _browser_last_used = now
                    return _cached_browser["browser_context"], page, _cached_browser["cdp_manager"], _cached_browser["playwright"]
                else:
                    utils.logger.warning("[OutreachAutomation] Cached browser login expired, re-launching...")
                    await _close_cached_browser()
            except Exception as e:
                utils.logger.warning(f"[OutreachAutomation] Cached browser unusable: {e}, re-launching...")
                await _close_cached_browser()

    cdp_manager = CDPBrowserManager()
    playwright = await async_playwright().start()

    # CDP 模式下启动 Xvfb，使 headed 模式可用（反检测效果更好）
    _ensure_xvfb()
    headless = _is_headless_env()

    try:
        # 优先连接到搜索任务的已有浏览器（有完整登录状态，IM面板才能正常工作）
        # 注意：小红书不能复用抖音浏览器，需要独立启动
        existing_port = _find_existing_chrome_cdp_port() if platform != "xhs" else None
        connected_existing = False

        if existing_port:
            utils.logger.info(f"[OutreachAutomation] Found existing Chrome on port {existing_port}, connecting...")
            try:
                # 获取 WebSocket URL
                import httpx
                resp = httpx.get(f"http://localhost:{existing_port}/json/version", timeout=5)
                ws_url = resp.json()["webSocketDebuggerUrl"]

                # 连接到已有浏览器，增加超时时间
                browser = await playwright.chromium.connect_over_cdp(ws_url, timeout=120000)

                # 获取已有上下文（有登录状态）
                contexts = browser.contexts
                if contexts:
                    browser_context = contexts[0]
                    # 使用已有页面（共享登录状态），而不是创建新页面
                    pages = browser_context.pages
                    if pages:
                        page = pages[0]
                    else:
                        page = await browser_context.new_page()
                    await page.set_viewport_size({"width": 1920, "height": 1080})
                    connected_existing = True
                    utils.logger.info("[OutreachAutomation] ✅ Connected to existing browser with login state")
                    
                    # 连接已有浏览器后，先导航到首页刷新登录状态
                    try:
                        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
                        await asyncio.sleep(3)
                        # 加载Cookie确保登录状态
                        await _load_platform_cookies(browser_context, platform)
                        await page.reload(wait_until="domcontentloaded", timeout=20000)
                        await asyncio.sleep(2)
                        utils.logger.info("[OutreachAutomation] Refreshed login state on existing browser")
                    except Exception as refresh_err:
                        utils.logger.warning(f"[OutreachAutomation] Failed to refresh existing browser: {refresh_err}")
                else:
                    utils.logger.warning("[OutreachAutomation] No contexts in existing browser")
            except Exception as e:
                utils.logger.warning(f"[OutreachAutomation] Failed to connect to existing browser: {e}")

        # 如果连接已有浏览器失败，启动独立Chrome
        if not connected_existing:
            if getattr(config, 'ENABLE_CDP_MODE', False):
                # 根据平台选择 user-data-dir
                if platform == "xhs":
                    search_user_data = os.path.join(os.getcwd(), "browser_data", "cdp_xhs_user_data_dir")
                    outreach_user_data = os.path.join(os.getcwd(), "browser_data", "cdp_xhs_outreach_user_data_dir")
                else:
                    search_user_data = os.path.join(os.getcwd(), "browser_data", "cdp_dy_user_data_dir")
                    outreach_user_data = os.path.join(os.getcwd(), "browser_data", "cdp_dy_outreach_user_data_dir")
                os.makedirs(outreach_user_data, exist_ok=True)

                # 复制搜索任务的 Cookies 到 outreach 目录（确保登录状态）
                try:
                    src_cookie = os.path.join(search_user_data, "Default", "Cookies")
                    dst_cookie = os.path.join(outreach_user_data, "Default", "Cookies")
                    dst_dir = os.path.dirname(dst_cookie)
                    os.makedirs(dst_dir, exist_ok=True)
                    if os.path.exists(src_cookie):
                        import shutil
                        shutil.copy2(src_cookie, dst_cookie)
                        # 也复制 Local Storage
                        src_ls = os.path.join(search_user_data, "Default", "Local Storage")
                        dst_ls = os.path.join(outreach_user_data, "Default", "Local Storage")
                        if os.path.exists(src_ls):
                            if os.path.exists(dst_ls):
                                shutil.rmtree(dst_ls)
                            shutil.copytree(src_ls, dst_ls)
                        utils.logger.info("[OutreachAutomation] Copied login state from search browser")
                except Exception as e:
                    utils.logger.warning(f"[OutreachAutomation] Failed to copy login state: {e}")

                # 找一个可用端口
                import socket as _socket
                available_port = None
                for port in range(9230, 9260):
                    try:
                        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                            s.bind(('localhost', port))
                            available_port = port
                            break
                    except OSError:
                        continue
                if not available_port:
                    raise RuntimeError("No available port for outreach Chrome")

                orig_debug_port = config.CDP_DEBUG_PORT
                config.CDP_DEBUG_PORT = available_port
                utils.logger.info(f"[OutreachAutomation] Launching independent Chrome on port {available_port}")
                try:
                    cdp_manager = CDPBrowserManager(user_data_dir_override=outreach_user_data)
                    browser_context = await cdp_manager.launch_and_connect(playwright, headless=headless)
                finally:
                    config.CDP_DEBUG_PORT = orig_debug_port
            else:
                utils.logger.info("[OutreachAutomation] Using persistent context mode")
                if platform == "xhs":
                    user_data_dir = os.path.join(os.getcwd(), "browser_data", "xhs_user_data_dir")
                else:
                    user_data_dir = os.path.join(os.getcwd(), "browser_data", "dy_user_data_dir")
                os.makedirs(user_data_dir, exist_ok=True)
                browser_context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir, headless=headless,
                    viewport={"width": 1920, "height": 1080},
                )

            page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
            await page.set_viewport_size({"width": 1920, "height": 1080})

            # 根据平台导航并注入Cookie
            if platform == "xhs":
                await page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=30000)
            else:
                await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            await _load_platform_cookies(browser_context, platform)
            await page.reload(wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

        # 验证登录状态
        login_ok = await _verify_login(page, platform)
        if not login_ok:
            utils.logger.warning("[OutreachAutomation] Login verification failed!")
            # 登录失败时关闭浏览器缓存，下次会重新启动浏览器并加载最新cookie
            await _close_cached_browser()
            raise Exception(f"{platform} 登录验证失败，请在Cookie管理中更新Cookie后重试")

        # 注入反自动化检测脚本（在所有页面生效）
        await _inject_anti_detection(browser_context)
        utils.logger.info("[OutreachAutomation] ✅ Anti-detection scripts injected")

        # 缓存浏览器实例
        _cached_browser = {
            "browser_context": browser_context,
            "page": page,
            "cdp_manager": cdp_manager,
            "playwright": playwright,
        }
        _browser_last_used = time.time()
        utils.logger.info("[OutreachAutomation] ✅ Browser launched and cached for reuse")

        return browser_context, page, cdp_manager, playwright
    except Exception as e:
        await playwright.stop()
        raise e


async def _inject_anti_detection(browser_context: BrowserContext):
    """注入反自动化检测脚本，隐藏Playwright/自动化特征
    
    主要防护：
    1. navigator.webdriver = false
    2. chrome.runtime 属性
    3. Permissions API 行为
    4. Plugin/MimeType 数量
    5. WebGL 渲染器信息
    6. 自动化相关的 window 属性
    """
    anti_detection_js = """
    // 1. 隐藏 webdriver 标志
    Object.defineProperty(navigator, 'webdriver', {
        get: () => false,
        configurable: true
    });
    
    // 2. 添加 chrome.runtime（正常浏览器有此属性）
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            connect: function() {},
            sendMessage: function() {},
            onMessage: { addListener: function() {} },
            id: undefined
        };
    }
    
    // 3. 修复 Permissions API（自动化环境下行为不同）
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
    
    // 4. 添加 Plugin 和 MimeType（正常浏览器有这些）
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
            ];
            plugins.length = 3;
            return plugins;
        },
        configurable: true
    });
    
    Object.defineProperty(navigator, 'mimeTypes', {
        get: () => {
            const mimeTypes = [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            ];
            mimeTypes.length = 2;
            return mimeTypes;
        },
        configurable: true
    });
    
    // 5. 隐藏自动化相关的 window 属性
    delete window.__playwright;
    delete window.__pw_manual;
    delete window.__PW_inspect;
    
    // 6. 修复 iframe contentWindow 检测
    const originalContentWindow = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
        get: function() {
            const result = originalContentWindow.get.call(this);
            if (result) {
                try {
                    // 隐藏 iframe 中的 webdriver
                    Object.defineProperty(result.navigator, 'webdriver', {
                        get: () => false,
                        configurable: true
                    });
                } catch (e) {
                    // 跨域 iframe 无法修改，忽略
                }
            }
            return result;
        },
        configurable: true
    });
    
    // 7. 修复 toString 检测（某些网站通过 toString 检测函数是否被修改）
    const nativeToString = Function.prototype.toString;
    const patchedFunctions = new Map();
    
    function patchToString(fn, nativeStr) {
        patchedFunctions.set(fn, nativeStr);
    }
    
    Function.prototype.toString = function() {
        if (patchedFunctions.has(this)) {
            return patchedFunctions.get(this);
        }
        return nativeToString.call(this);
    };
    
    // 标记已修改的函数
    patchToString(navigator.permissions.query, 'function query() { [native code] }');
    
    // 8. 随机化 Canvas 指纹（轻微噪声，不影响显示）
    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        // 添加微小噪声到canvas数据
        const context = this.getContext('2d');
        if (context && this.width > 0 && this.height > 0) {
            const imageData = context.getImageData(0, 0, Math.min(this.width, 1), Math.min(this.height, 1));
            if (imageData.data.length > 0) {
                imageData.data[0] = imageData.data[0] ^ 1; // 微小变化
                context.putImageData(imageData, 0, 0);
            }
        }
        return originalToDataURL.apply(this, arguments);
    };
    
    // 9. 修复 navigator.languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en-US', 'en'],
        configurable: true
    });
    
    // 10. 隐藏 HeadlessChrome 标识
    const originalUserAgent = navigator.userAgent;
    Object.defineProperty(navigator, 'userAgent', {
        get: () => originalUserAgent.replace('HeadlessChrome/', 'Chrome/'),
        configurable: true
    });
    
    console.log('[AntiDetection] All protections active');
    """
    
    # 为浏览器上下文的所有新页面注入脚本
    await browser_context.add_init_script(anti_detection_js)
    
    # 对已有页面也注入
    for existing_page in browser_context.pages:
        try:
            await existing_page.evaluate(anti_detection_js)
        except Exception:
            pass


async def _close_cached_browser():
    """关闭缓存的浏览器实例"""
    global _cached_browser, _browser_last_used
    if _cached_browser is None:
        return
    try:
        playwright = _cached_browser.get("playwright")
        if playwright:
            await playwright.stop()
        utils.logger.info("[OutreachAutomation] Cached browser closed")
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Error closing cached browser: {e}")
    finally:
        _cached_browser = None
        _browser_last_used = 0


async def _load_platform_cookies(browser_context: BrowserContext, platform: str = "dy"):
    """根据平台加载Cookie"""
    if platform == "xhs":
        await _load_xhs_cookies(browser_context)
    else:
        await _load_douyin_cookies(browser_context)


async def _load_xhs_cookies(browser_context: BrowserContext):
    """加载小红书 Cookie 到浏览器上下文"""
    try:
        from .cookie_manager import get_cookie
        from tools.crawler_util import convert_str_cookie_to_dict

        cookie_str = get_cookie("xhs")
        if not cookie_str:
            utils.logger.warning("[OutreachAutomation] No XHS cookie found")
            return

        # 先清除浏览器中所有小红书相关的旧cookie
        try:
            existing_cookies = await browser_context.cookies()
            xhs_cookies = [c for c in existing_cookies if 'xiaohongshu.com' in c.get('domain', '')]
            if xhs_cookies:
                for c in xhs_cookies:
                    try:
                        await browser_context.clear_cookies(name=c['name'], domain=c['domain'])
                    except Exception:
                        pass
                utils.logger.info(f"[OutreachAutomation] Cleared {len(xhs_cookies)} old XHS cookies")
        except Exception as clear_err:
            utils.logger.warning(f"[OutreachAutomation] Failed to clear old XHS cookies: {clear_err}")

        cookie_dict = convert_str_cookie_to_dict(cookie_str)
        cookies_to_add = [
            {"name": k, "value": v, "domain": ".xiaohongshu.com", "path": "/"}
            for k, v in cookie_dict.items()
        ]

        await browser_context.add_cookies(cookies_to_add)
        utils.logger.info(f"[OutreachAutomation] Loaded {len(cookies_to_add)} XHS cookies")
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Failed to load XHS cookies: {e}")


async def _load_douyin_cookies(browser_context: BrowserContext):
    """加载抖音 Cookie 到浏览器上下文"""
    try:
        from .cookie_manager import get_cookie
        from tools.crawler_util import convert_str_cookie_to_dict
        import urllib.parse

        cookie_str = get_cookie("dy")
        if not cookie_str:
            utils.logger.warning("[OutreachAutomation] No Douyin cookie found")
            return

        # 先清除浏览器中所有抖音相关的旧cookie，避免过期cookie干扰
        try:
            existing_cookies = await browser_context.cookies()
            dy_cookies = [c for c in existing_cookies if 'douyin.com' in c.get('domain', '')]
            if dy_cookies:
                for c in dy_cookies:
                    try:
                        await browser_context.clear_cookies(name=c['name'], domain=c['domain'])
                    except Exception:
                        pass
                utils.logger.info(f"[OutreachAutomation] Cleared {len(dy_cookies)} old Douyin cookies")
        except Exception as clear_err:
            utils.logger.warning(f"[OutreachAutomation] Failed to clear old cookies: {clear_err}")

        cookie_dict = convert_str_cookie_to_dict(cookie_str)
        cookies_to_add = [
            {"name": k, "value": v, "domain": ".douyin.com", "path": "/"}
            for k, v in cookie_dict.items()
        ]

        # 补充 uid（从 PhoneResumeUidCacheV1 提取）
        phone_uid_raw = cookie_dict.get('PhoneResumeUidCacheV1', '')
        if phone_uid_raw and not cookie_dict.get('uid'):
            try:
                uid_data = json.loads(urllib.parse.unquote(phone_uid_raw))
                uid_value = list(uid_data.keys())[0] if uid_data else ''
                if uid_value:
                    cookies_to_add.append({"name": "uid", "value": uid_value, "domain": ".douyin.com", "path": "/"})
            except Exception:
                pass

        await browser_context.add_cookies(cookies_to_add)
        utils.logger.info(f"[OutreachAutomation] Loaded {len(cookies_to_add)} cookies")
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Failed to load cookies: {e}")


async def _verify_login(page: Page, platform: str = "dy") -> bool:
    """通过 API 验证登录状态"""
    try:
        if platform == "xhs":
            # 小红书：检查页面是否有登录标识
            result = await page.evaluate("""
                () => {
                    // 检查是否有用户头像或昵称（登录后才显示）
                    const avatar = document.querySelector('.user-info .avatar, .sidebar-user-info, [class*="login-btn"]');
                    const loginBtn = document.querySelector('[class*="login-btn"], [class*="LoginButton"]');
                    // 如果有登录按钮且可见，说明未登录
                    if (loginBtn && loginBtn.offsetParent !== null) {
                        return { logged_in: false, reason: 'login_button_visible' };
                    }
                    return { logged_in: true, reason: 'no_login_button' };
                }
            """)
            is_ok = result.get('logged_in', False)
        else:
            # 抖音：通过API验证
            result = await page.evaluate("""
                async () => {
                    try {
                        const resp = await fetch('https://www.douyin.com/passport/web/get_user_info/', {
                            credentials: 'include'
                        });
                        const data = await resp.json();
                        return { status: resp.status, code: data.status_code, hasUser: !!data.data };
                    } catch(e) { return { error: e.message }; }
                }
            """)
            is_ok = result.get('hasUser', False)
        utils.logger.info(f"[OutreachAutomation] Login check: {result}")
        return is_ok
    except Exception as e:
        utils.logger.warning(f"[OutreachAutomation] Login verification error: {e}")
        return False


async def _handle_xhs_captcha(page: Page, max_retries: int = 3) -> bool:
    """处理小红书验证码 - 滑块验证

    小红书访问用户主页时可能触发安全验证（滑块验证），
    需要自动完成验证才能继续。
    """
    for attempt in range(max_retries):
        current_url = page.url
        if "captcha" not in current_url and "verify" not in current_url:
            utils.logger.info("[OutreachAutomation] XHS: No captcha on page")
            return True

        utils.logger.info(f"[OutreachAutomation] XHS: Captcha detected (attempt {attempt+1}/{max_retries}), URL: {current_url}")

        try:
            # 等待验证码加载
            await asyncio.sleep(2)

            # 检查验证码类型
            captcha_type = await page.evaluate("""
                () => {
                    const captchaDiv = document.querySelector('#captcha-div, .fe-captcha-app, [class*="captcha"]');
                    if (!captchaDiv) return 'none';

                    const text = document.body.innerText || '';
                    // 滑块验证
                    if (text.includes('滑块') || text.includes('拖动') || text.includes('滑动')) return 'slider';
                    // 图片验证
                    if (text.includes('点击') || text.includes('选择')) return 'image_click';
                    // 通用
                    return 'unknown';
                }
            """)
            utils.logger.info(f"[OutreachAutomation] XHS: Captcha type: {captcha_type}")

            if captcha_type == 'slider':
                # 尝试自动完成滑块验证
                slider_ok = await _solve_xhs_slider(page)
                if slider_ok:
                    utils.logger.info("[OutreachAutomation] XHS: Slider captcha solved!")
                    await asyncio.sleep(3)
                    # 检查是否通过了验证
                    if "captcha" not in page.url and "verify" not in page.url:
                        return True
                    utils.logger.warning("[OutreachAutomation] XHS: Still on captcha after slider solve")
                else:
                    utils.logger.warning("[OutreachAutomation] XHS: Slider solve failed")

            elif captcha_type == 'image_click':
                utils.logger.warning("[OutreachAutomation] XHS: Image click captcha not supported, waiting for manual...")
                await asyncio.sleep(15)
                if "captcha" not in page.url and "verify" not in page.url:
                    return True

            else:
                # 未知类型，等待看是否能自动通过
                utils.logger.info("[OutreachAutomation] XHS: Unknown captcha, waiting...")
                await asyncio.sleep(5)
                if "captcha" not in page.url and "verify" not in page.url:
                    return True

            # 尝试刷新页面重新获取验证码
            if attempt < max_retries - 1:
                utils.logger.info("[OutreachAutomation] XHS: Retrying captcha...")
                # 先回到首页，再重新访问
                await page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                # 重新导航到目标页面
                redirect_path = page.url
                if "captcha" in current_url:
                    # 从captcha URL中提取原始目标URL
                    import urllib.parse
                    try:
                        parsed = urllib.parse.urlparse(current_url)
                        params = urllib.parse.parse_qs(parsed.query)
                        redirect = params.get('redirectPath', [''])[0]
                        if redirect:
                            await page.goto(f"https://www.xiaohongshu.com{redirect}", wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(3)
                    except Exception as e:
                        utils.logger.warning(f"[OutreachAutomation] XHS: Failed to extract redirect: {e}")

        except Exception as e:
            utils.logger.error(f"[OutreachAutomation] XHS: Captcha handling error: {e}")
            await asyncio.sleep(3)

    return "captcha" not in page.url and "verify" not in page.url


async def _solve_xhs_slider(page: Page) -> bool:
    """自动解决小红书滑块验证"""
    try:
        # 查找滑块元素
        slider_info = await page.evaluate("""
            () => {
                // 查找滑块按钮
                const sliderBtn = document.querySelector(
                    '.slider-btn, .slider_btn, [class*="slider-btn"], [class*="drag-btn"], ' +
                    '[class*="sliderBtn"], [class*="dragBtn"], [class*="drag"]'
                );
                if (!sliderBtn) return null;

                const rect = sliderBtn.getBoundingClientRect();
                return {
                    x: rect.x,
                    y: rect.y,
                    w: rect.width,
                    h: rect.height,
                    cls: sliderBtn.className?.toString().substring(0, 50)
                };
            }
        """)

        if not slider_info:
            utils.logger.warning("[OutreachAutomation] XHS: Slider button not found")
            return False

        utils.logger.info(f"[OutreachAutomation] XHS: Slider found: {slider_info}")

        # 获取滑块轨道宽度
        track_width = await page.evaluate("""
            () => {
                const track = document.querySelector(
                    '.slider-track, .slider_track, [class*="slider-track"], [class*="track"]'
                );
                if (!track) return 300; // 默认宽度
                const rect = track.getBoundingClientRect();
                return rect.width;
            }
        """)

        # 生成滑块轨迹
        from tools.slider_util import get_track_simple
        distance = track_width - slider_info['w']
        tracks = get_track_simple(distance)

        start_x = slider_info['x'] + slider_info['w'] / 2
        start_y = slider_info['y'] + slider_info['h'] / 2

        # 执行拖动
        await page.mouse.move(start_x, start_y)
        await asyncio.sleep(0.3)
        await page.mouse.down()
        await asyncio.sleep(0.2)

        x = start_x
        for i, track in enumerate(tracks):
            y_offset = random.uniform(-1.5, 1.5)
            await page.mouse.move(x + track, start_y + y_offset, steps=random.randint(5, 10))
            x += track
            if random.random() < 0.1:
                await asyncio.sleep(random.uniform(0.02, 0.08))

        await asyncio.sleep(random.uniform(0.15, 0.35))
        await page.mouse.up()

        utils.logger.info(f"[OutreachAutomation] XHS: Slider drag completed, moved {x - start_x:.0f}px")
        await asyncio.sleep(3)

        # 检查是否通过验证
        if "captcha" not in page.url and "verify" not in page.url:
            return True

        # 检查页面上是否有"验证成功"提示
        success_check = await page.evaluate("""
            () => {
                const text = document.body.innerText || '';
                return text.includes('验证成功') || text.includes('验证通过');
            }
        """)
        return success_check

    except Exception as e:
        utils.logger.error(f"[OutreachAutomation] XHS: Slider solve error: {e}")
        return False


async def _navigate_to_user_page(page: Page, sec_uid: str, platform: str) -> bool:
    """访问用户主页"""
    if platform in ("dy", "douyin"):
        url = f"https://www.douyin.com/user/{sec_uid}"
    elif platform == "xhs":
        url = f"https://www.xiaohongshu.com/user/profile/{sec_uid}"
    else:
        url = f"https://www.douyin.com/user/{sec_uid}"

    try:
        utils.logger.info(f"[OutreachAutomation] Navigating to {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as nav_err:
            err_str = str(nav_err)
            # ERR_ABORTED 通常是页面正在跳转或被其他导航中断，不一定是真正的失败
            if "ERR_ABORTED" in err_str:
                utils.logger.warning(f"[OutreachAutomation] Navigation aborted (likely interrupted), checking page state...")
                await asyncio.sleep(3)
                # 检查当前页面URL是否已经是目标页面
                current_url = page.url
                if sec_uid in current_url:
                    utils.logger.info(f"[OutreachAutomation] Page already at target URL after abort: {current_url}")
                else:
                    # 尝试重新导航
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    except Exception as retry_err:
                        utils.logger.warning(f"[OutreachAutomation] Retry navigation also failed: {retry_err}")
                        # 即使重试失败，也检查页面是否已加载
                        await asyncio.sleep(3)
            else:
                raise nav_err

        # 小红书：检查并处理验证码
        if platform == "xhs":
            captcha_handled = await _handle_xhs_captcha(page)
            if not captcha_handled:
                utils.logger.warning("[OutreachAutomation] XHS captcha not resolved, continuing anyway")

        # 等待页面关键元素渲染
        if platform == "xhs":
            # 小红书SPA页面需要等待用户信息区域渲染
            # 先等待DOM加载
            await asyncio.sleep(3)
            
            # 等待用户主页主体内容出现（最多等30秒）
            for attempt in range(15):
                has_content = await page.evaluate("""
                    () => {
                        // 检查是否有用户昵称/头像区域（用户主页主体内容）
                        const nickEl = document.querySelector('[class*="nickname"], [class*="user-name"], [class*="userName"]');
                        const avatarEl = document.querySelector('[class*="avatar"], [class*="userAvatar"]');
                        const descEl = document.querySelector('[class*="desc"], [class*="description"]');
                        const bodyText = document.body.innerText || '';
                        const hasNickname = nickEl && nickEl.getBoundingClientRect().width > 0;
                        const hasAvatar = avatarEl && avatarEl.getBoundingClientRect().width > 0;
                        const hasDesc = descEl && descEl.getBoundingClientRect().width > 0;
                        const hasBodyContent = bodyText.length > 100;
                        return hasNickname || hasAvatar || hasDesc || hasBodyContent;
                    }
                """)
                if has_content:
                    utils.logger.info(f"[OutreachAutomation] XHS page content loaded after {(attempt+1)*2}s")
                    break
                await asyncio.sleep(2)
            else:
                utils.logger.warning("[OutreachAutomation] XHS page content not loaded after 30s, continuing anyway")
                # 保存调试截图
                await _save_debug_screenshot(page, "xhs_page_not_loaded", "nav_noload")
        else:
            try:
                await page.wait_for_selector(
                    'button:has-text("私信"), button:has-text("关注"), h1, .nickname',
                    timeout=15000, state='visible'
                )
            except PlaywrightTimeoutError:
                utils.logger.warning("[OutreachAutomation] Key elements not found within 15s, continuing anyway")

        await asyncio.sleep(3)

        # 再次检查验证码（页面加载后可能触发）
        if platform == "xhs" and ("captcha" in page.url or "verify" in page.url):
            captcha_handled = await _handle_xhs_captcha(page)
            if not captcha_handled:
                utils.logger.warning("[OutreachAutomation] XHS captcha still present after retry")

        # 检查页面状态
        page_status = await page.evaluate("""
            () => {
                const text = document.body.innerText || '';
                return {
                    title: document.title,
                    url: location.href.substring(0, 80),
                    hasUserNotFound: text.includes('用户不存在') || text.includes('该用户不存在') || text.includes('页面不存在'),
                    hasUserBanned: text.includes('用户已注销') || text.includes('账号被封禁') || text.includes('账号异常'),
                    hasCaptcha: location.href.includes('captcha') || location.href.includes('verify'),
                    bodyLength: text.length,
                };
            }
        """)
        utils.logger.info(f"[OutreachAutomation] Page status: {page_status}")

        # 抖音页面内容为空或极少（bodyLength < 100），说明页面未正常渲染
        # 可能是反爬检测或页面加载失败，等待并重试
        if platform in ("dy", "douyin") and page_status.get('bodyLength', 0) < 100:
            utils.logger.warning(f"[OutreachAutomation] Page body too short ({page_status.get('bodyLength', 0)} chars), waiting for content to load...")
            for retry in range(3):
                await asyncio.sleep(5)
                page_status = await page.evaluate("""
                    () => {
                        const text = document.body.innerText || '';
                        return { bodyLength: text.length, title: document.title };
                    }
                """)
                if page_status.get('bodyLength', 0) >= 100:
                    utils.logger.info(f"[OutreachAutomation] Page content loaded after {(retry+1)*5}s: {page_status}")
                    break
            else:
                # 3次等待后仍然为空，尝试刷新页面
                utils.logger.warning("[OutreachAutomation] Page still empty after 15s, trying reload...")
                try:
                    await page.reload(wait_until='domcontentloaded', timeout=20000)
                    await asyncio.sleep(8)
                    page_status = await page.evaluate("""
                        () => {
                            const text = document.body.innerText || '';
                            return { bodyLength: text.length, title: document.title };
                        }
                    """)
                    utils.logger.info(f"[OutreachAutomation] After reload: {page_status}")
                except Exception as reload_err:
                    utils.logger.warning(f"[OutreachAutomation] Reload failed: {reload_err}")

        if page_status.get('hasUserNotFound') or page_status.get('hasUserBanned'):
            return False

        # 如果仍在验证页面，返回失败
        if page_status.get('hasCaptcha'):
            utils.logger.warning("[OutreachAutomation] Still on captcha page after handling")
            return False

        # 小红书：额外检查页面主体内容是否加载
        if platform == "xhs" and page_status.get('bodyLength', 0) < 50:
            utils.logger.warning("[OutreachAutomation] XHS page body too short, likely not loaded properly")
            # 尝试刷新页面
            await page.reload(wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            # 重新检查
            body_len = await page.evaluate("() => (document.body.innerText || '').length")
            if body_len < 50:
                utils.logger.error("[OutreachAutomation] XHS page still empty after reload")
                return False

        return True
    except Exception as e:
        utils.logger.error(f"[OutreachAutomation] Navigate failed: {e}")
        return False


async def _click_pm_button_xhs(page: Page, user_id: str = "") -> bool:
    """点击小红书私信按钮 - 多策略匹配

    小红书网页版私信流程：
    0. 先检查页面是否加载了用户主页主体内容
    1. 用户主页查找"私信"/"关注并私信"按钮（包括SVG图标按钮）
    2. 如果没有，先关注用户，再查找私信按钮
    3. 如果仍然没有，通过消息中心发送
    4. 最后尝试创作服务平台的私信功能
    """
    try:
        # 先滚动到页面顶部确保按钮可见
        await page.evaluate("() => { window.scrollTo(0, 0); }")
        await asyncio.sleep(1)

        # 检查是否在验证页面
        if "captcha" in page.url or "verify" in page.url:
            utils.logger.warning("[OutreachAutomation] XHS: Still on captcha page, cannot find PM button")
            return False

        # ===== 策略0: 检查页面主体内容是否加载 =====
        page_body_len = await page.evaluate("() => (document.body.innerText || '').length")
        if page_body_len < 50:
            utils.logger.warning(f"[OutreachAutomation] XHS: Page body too short ({page_body_len}), content not loaded")
            # 尝试等待更长时间
            await asyncio.sleep(5)
            page_body_len = await page.evaluate("() => (document.body.innerText || '').length")
            if page_body_len < 50:
                utils.logger.error("[OutreachAutomation] XHS: Page still empty, cannot find PM button")
                return False

        # ===== 策略1: 直接查找"私信"或"关注并私信"按钮 =====
        btn_info = await page.evaluate("""
            () => {
                const pmTexts = ['私信', '发消息', '发私信', '聊一聊', '关注并私信'];
                const results = [];

                // 搜索范围：所有可交互元素
                const candidates = document.querySelectorAll('button, div, span, a, [role="button"], section');
                for (const el of candidates) {
                    const text = el.textContent?.trim() || '';
                    const isMatch = pmTexts.some(pm => text === pm || text.includes(pm));
                    if (!isMatch) continue;

                    const rect = el.getBoundingClientRect();
                    // 排除顶部导航栏和不可见元素
                    if (rect.y < 50 || rect.width < 10 || rect.height < 10) continue;
                    // 排除过大的容器（可能是整个卡片区域）
                    if (rect.width > 400 || rect.height > 100) continue;

                    results.push({
                        x: rect.x + rect.width/2,
                        y: rect.y + rect.height/2,
                        w: rect.width,
                        h: rect.height,
                        tag: el.tagName,
                        text: text.substring(0, 20),
                        area: rect.width * rect.height,
                        childCount: el.children.length
                    });
                }

                // 优先选择面积较小且子元素少的（更精确的按钮）
                results.sort((a, b) => (a.childCount * 1000 + a.area) - (b.childCount * 1000 + b.area));
                return results.length > 0 ? results[0] : null;
            }
        """)

        if btn_info:
            utils.logger.info(f"[OutreachAutomation] Found XHS PM button: {btn_info}")
            try:
                await page.mouse.click(btn_info['x'], btn_info['y'])
                utils.logger.info(f"[OutreachAutomation] XHS PM button clicked via mouse at ({btn_info['x']:.0f}, {btn_info['y']:.0f})")
                await asyncio.sleep(3)
                return True
            except Exception as e:
                utils.logger.warning(f"[OutreachAutomation] XHS mouse click failed: {e}")

        # ===== 策略1.5: 查找SVG图标按钮（小红书可能用图标代替文字） =====
        svg_btn_info = await page.evaluate("""
            () => {
                // 在用户信息区域查找所有按钮（包括SVG图标按钮）
                const results = [];
                const buttons = document.querySelectorAll('button, [role="button"]');
                for (const btn of buttons) {
                    const rect = btn.getBoundingClientRect();
                    // 只关注用户主页右侧区域的按钮（y在100-400之间，x在右侧）
                    if (rect.y < 80 || rect.width < 20 || rect.height < 20 || rect.width > 200) continue;
                    
                    const svg = btn.querySelector('svg');
                    const ariaLabel = btn.getAttribute('aria-label') || '';
                    const title = btn.getAttribute('title') || '';
                    const text = btn.textContent?.trim() || '';
                    const cls = btn.className?.toString() || '';
                    
                    // 检查是否是私信相关的图标按钮
                    const isPmRelated = ariaLabel.includes('私信') || ariaLabel.includes('消息') ||
                                       title.includes('私信') || title.includes('消息') ||
                                       cls.includes('message') || cls.includes('chat') || cls.includes('pm') ||
                                       cls.includes('private') || cls.includes('contact');
                    
                    if (isPmRelated || (svg && rect.width < 60 && rect.y > 100 && rect.y < 400)) {
                        results.push({
                            x: rect.x + rect.width/2,
                            y: rect.y + rect.height/2,
                            w: rect.width,
                            h: rect.height,
                            text: text.substring(0, 20),
                            ariaLabel: ariaLabel,
                            title: title,
                            hasSvg: !!svg,
                            cls: cls.substring(0, 60),
                            isPmRelated: isPmRelated,
                        });
                    }
                }
                
                // 优先选择明确是私信相关的
                results.sort((a, b) => (b.isPmRelated ? 1 : 0) - (a.isPmRelated ? 1 : 0));
                return results.length > 0 ? results : null;
            }
        """)

        if svg_btn_info:
            utils.logger.info(f"[OutreachAutomation] XHS SVG button candidates: {svg_btn_info}")
            # 尝试点击每个可能的SVG按钮
            for btn in svg_btn_info:
                try:
                    await page.mouse.click(btn['x'], btn['y'])
                    utils.logger.info(f"[OutreachAutomation] XHS: Clicked SVG button at ({btn['x']:.0f}, {btn['y']:.0f})")
                    await asyncio.sleep(3)
                    # 检查是否打开了对话框
                    dialog_check = await page.evaluate("""
                        () => {
                            const editables = document.querySelectorAll('[contenteditable="true"]');
                            for (const e of editables) {
                                const r = e.getBoundingClientRect();
                                if (r.width > 100 && r.height > 20) return true;
                            }
                            const textareas = document.querySelectorAll('textarea');
                            for (const ta of textareas) {
                                const r = ta.getBoundingClientRect();
                                if (r.width > 100 && r.height > 20) return true;
                            }
                            return false;
                        }
                    """)
                    if dialog_check:
                        utils.logger.info("[OutreachAutomation] XHS: Dialog opened after SVG button click!")
                        return True
                except Exception as e:
                    utils.logger.warning(f"[OutreachAutomation] XHS SVG click failed: {e}")

        # ===== 策略2: 先关注用户，再查找私信按钮 =====
        utils.logger.info("[OutreachAutomation] XHS: No direct PM button, trying follow first...")
        follow_result = await page.evaluate("""
            () => {
                // 查找"关注"按钮（排除"已关注"）
                const btns = document.querySelectorAll('button, [role="button"]');
                for (const btn of btns) {
                    const text = btn.textContent?.trim() || '';
                    if (text === '关注' || text === '+ 关注' || text === '关注并私信') {
                        const rect = btn.getBoundingClientRect();
                        if (rect.y > 50 && rect.width > 0 && rect.height > 0) {
                            btn.click();
                            return {clicked: true, text: text, y: Math.round(rect.y)};
                        }
                    }
                }
                return {clicked: false};
            }
        """)
        if follow_result and follow_result.get('clicked'):
            utils.logger.info(f"[OutreachAutomation] XHS: Clicked follow button: {follow_result}")
            await asyncio.sleep(3)

            # 关注后重新查找私信按钮
            btn_info2 = await page.evaluate("""
                () => {
                    const pmTexts = ['私信', '发消息', '发私信', '聊一聊'];
                    const candidates = document.querySelectorAll('button, div, span, a, [role="button"]');
                    for (const el of candidates) {
                        const text = el.textContent?.trim() || '';
                        if (pmTexts.includes(text)) {
                            const rect = el.getBoundingClientRect();
                            if (rect.y > 50 && rect.width > 10 && rect.height > 10 && rect.width < 400) {
                                return {x: rect.x + rect.width/2, y: rect.y + rect.height/2, text: text};
                            }
                        }
                    }
                    return null;
                }
            """)
            if btn_info2:
                await page.mouse.click(btn_info2['x'], btn_info2['y'])
                utils.logger.info(f"[OutreachAutomation] XHS: PM button found after following: {btn_info2}")
                await asyncio.sleep(3)
                return True

        # ===== 策略3: 通过消息中心发送 =====
        utils.logger.info("[OutreachAutomation] XHS: Trying message center approach...")
        # 保存当前URL以便回退
        original_url = page.url

        # 尝试访问消息中心
        await page.goto("https://www.xiaohongshu.com/message", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        # 检查是否被重定向
        current_url = page.url
        if "message" not in current_url:
            utils.logger.warning(f"[OutreachAutomation] XHS: Message page redirected to {current_url}")

            # 尝试创作服务平台
            utils.logger.info("[OutreachAutomation] XHS: Trying creator platform...")
            await page.goto("https://creator.xiaohongshu.com/message/chat", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)

            if "creator" not in page.url:
                utils.logger.warning("[OutreachAutomation] XHS: Creator platform also redirected")
                # 回到原始页面
                await page.goto(original_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                # 最后尝试：查找页面上所有可能的私信入口
                return await _xhs_fallback_pm_search(page, user_id)

        # 在消息中心页面查找"发消息"按钮
        new_chat_result = await page.evaluate("""
            () => {
                // 查找所有可能的"发消息"入口
                const btns = document.querySelectorAll('button, [role="button"], a, div, span');
                const targetTexts = ['发消息', '新建对话', '发私信', '+'];
                for (const btn of btns) {
                    const text = btn.textContent?.trim() || '';
                    if (targetTexts.includes(text) || text.includes('发消息')) {
                        const rect = btn.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0 && rect.width < 200) {
                            btn.click();
                            return {clicked: true, text: text, y: Math.round(rect.y)};
                        }
                    }
                }
                // 查找带+图标的按钮
                const iconBtns = document.querySelectorAll('[class*="add"], [class*="create"], [class*="new"]');
                for (const btn of iconBtns) {
                    const rect = btn.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && rect.width < 60) {
                        btn.click();
                        return {clicked: true, text: 'icon', y: Math.round(rect.y)};
                    }
                }
                return {clicked: false};
            }
        """)

        if new_chat_result and new_chat_result.get('clicked'):
            utils.logger.info(f"[OutreachAutomation] XHS: Clicked new chat button: {new_chat_result}")
            await asyncio.sleep(2)

            # 搜索用户
            if user_id:
                # 查找搜索输入框
                search_ok = await page.evaluate(f"""
                    () => {{
                        const inputs = document.querySelectorAll('input, textarea');
                        for (const input of inputs) {{
                            const placeholder = input.placeholder || '';
                            if (placeholder.includes('搜索') || placeholder.includes('用户') || placeholder.includes('昵称')) {{
                                input.focus();
                                input.value = '{user_id}';
                                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                return true;
                            }}
                        }}
                        return false;
                    }}
                """)

                if search_ok:
                    await asyncio.sleep(3)
                    # 点击搜索结果中的第一个用户
                    clicked = await page.evaluate("""
                        () => {
                            const items = document.querySelectorAll('[class*="search"], [class*="result"], [class*="user-item"], [class*="contact"]');
                            for (const item of items) {
                                const rect = item.getBoundingClientRect();
                                if (rect.width > 0 && rect.height > 0) {
                                    item.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if clicked:
                        utils.logger.info("[OutreachAutomation] XHS: User found in message center search")
                        await asyncio.sleep(2)
                        return True

        # ===== 策略4: 回到用户主页，尝试更多菜单 =====
        utils.logger.info("[OutreachAutomation] XHS: Trying 'More' menu on user profile...")
        if "profile" not in page.url:
            await page.goto(original_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

        # 处理可能的验证码
        if "captcha" in page.url or "verify" in page.url:
            captcha_ok = await _handle_xhs_captcha(page)
            if not captcha_ok:
                return False

        more_clicked = await page.evaluate("""
            () => {
                const candidates = document.querySelectorAll('button, [role="button"], div, span');
                for (const el of candidates) {
                    const text = el.textContent?.trim() || '';
                    const cls = el.className?.toString() || '';
                    if (text === '更多' || text === '⋯' || cls.includes('more') || cls.includes('More')) {
                        const rect = el.getBoundingClientRect();
                        if (rect.y > 50 && rect.width > 0 && rect.height > 0 && rect.y < 300) {
                            el.click();
                            return {x: rect.x + rect.width/2, y: rect.y + rect.height/2, text: text};
                        }
                    }
                }
                return null;
            }
        """)
        if more_clicked:
            utils.logger.info(f"[OutreachAutomation] XHS: Clicked 'More' menu: {more_clicked}")
            await asyncio.sleep(1.5)
            pm_in_menu = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('div, span, a, button, [role="menuitem"], [role="button"]');
                    const pmTexts = ['私信', '发消息', '发私信'];
                    for (const el of items) {
                        const text = el.textContent?.trim() || '';
                        if (pmTexts.includes(text)) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                el.click();
                                return {x: rect.x + rect.width/2, y: rect.y + rect.height/2, text: text};
                            }
                        }
                    }
                    return null;
                }
            """)
            if pm_in_menu:
                utils.logger.info(f"[OutreachAutomation] XHS: Found PM in menu: {pm_in_menu}")
                await asyncio.sleep(3)
                return True
            await page.keyboard.press('Escape')
            await asyncio.sleep(0.5)

        # ===== 调试: 输出页面上所有可见的交互元素 =====
        debug_info = await page.evaluate("""
            () => {
                const els = document.querySelectorAll('button, [role="button"], a');
                const results = [];
                for (const e of els) {
                    const r = e.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.y > 0) {
                        results.push({
                            tag: e.tagName,
                            text: e.textContent?.trim().substring(0, 30),
                            cls: e.className?.toString().substring(0, 50),
                            y: Math.round(r.y),
                            w: Math.round(r.width),
                            h: Math.round(r.height)
                        });
                    }
                }
                return results;
            }
        """)
        utils.logger.warning(f"[OutreachAutomation] XHS PM button not found. Page elements: {debug_info}")

        try:
            await page.screenshot(path="/tmp/xhs_no_pm_button.png")
            utils.logger.info("[OutreachAutomation] Debug screenshot saved to /tmp/xhs_no_pm_button.png")
        except:
            pass

        return False
    except Exception as e:
        utils.logger.error(f"[OutreachAutomation] XHS click PM button failed: {e}")
        return False


async def _xhs_fallback_pm_search(page: Page, user_id: str = "") -> bool:
    """小红书私信后备方案：在用户主页尝试所有可能的私信入口"""
    try:
        # 查找所有可点击元素，包括SVG图标按钮
        all_clickable = await page.evaluate("""
            () => {
                const results = [];
                // 查找所有button和role=button
                document.querySelectorAll('button, [role="button"]').forEach(btn => {
                    const r = btn.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.y > 50 && r.y < 300) {
                        const svg = btn.querySelector('svg');
                        const ariaLabel = btn.getAttribute('aria-label') || '';
                        const title = btn.getAttribute('title') || '';
                        results.push({
                            text: btn.textContent?.trim().substring(0, 20),
                            ariaLabel: ariaLabel,
                            title: title,
                            hasSvg: !!svg,
                            cls: btn.className?.toString().substring(0, 60),
                            x: r.x + r.width/2,
                            y: r.y + r.height/2,
                            w: r.width,
                            h: r.height
                        });
                    }
                });
                return results;
            }
        """)

        utils.logger.info(f"[OutreachAutomation] XHS fallback: Found {len(all_clickable)} clickable elements")
        for el in all_clickable:
            # 尝试点击每个可能的按钮
            if el.get('hasSvg') and el['w'] < 60:
                utils.logger.info(f"[OutreachAutomation] XHS fallback: Trying SVG button: {el}")
                await page.mouse.click(el['x'], el['y'])
                await asyncio.sleep(2)
                # 检查是否弹出了私信对话框
                dialog_check = await page.evaluate("""
                    () => {
                        const editables = document.querySelectorAll('[contenteditable="true"]');
                        for (const e of editables) {
                            const r = e.getBoundingClientRect();
                            if (r.width > 100 && r.height > 0) return true;
                        }
                        const textareas = document.querySelectorAll('textarea');
                        for (const ta of textareas) {
                            const r = ta.getBoundingClientRect();
                            if (r.width > 100 && r.height > 0) return true;
                        }
                        return false;
                    }
                """)
                if dialog_check:
                    utils.logger.info("[OutreachAutomation] XHS fallback: Dialog found after clicking SVG button!")
                    return True
                # 关闭可能的弹出菜单
                await page.keyboard.press('Escape')
                await asyncio.sleep(0.5)

        return False
    except Exception as e:
        utils.logger.error(f"[OutreachAutomation] XHS fallback PM search failed: {e}")
        return False


async def _click_pm_button(page: Page, platform: str, user_id: str = "") -> tuple[bool, str]:
    """点击私信按钮 - 支持抖音和小红书
    返回 (success, reason): success=True表示点击成功，reason为空或跳过原因
    """
    if platform == "xhs":
        ok = await _click_pm_button_xhs(page, user_id=user_id)
        return (ok, "" if ok else "未找到私信按钮")

    if platform not in ("dy", "douyin"):
        return (False, "不支持的平台")

    try:
        # 先等待私信按钮出现（最多等15秒），避免页面还没渲染完就查找
        try:
            pm_btn_locator = page.locator('button:has-text("私信")')
            # 等待至少一个私信按钮出现在 y>100 的位置
            for wait_i in range(15):
                count = await pm_btn_locator.count()
                for idx in range(count):
                    box = await pm_btn_locator.nth(idx).bounding_box()
                    if box and box['y'] > 100 and box['width'] > 0:
                        utils.logger.info(f"[OutreachAutomation] PM button appeared after {wait_i}s wait")
                        break
                else:
                    await asyncio.sleep(1)
                    continue
                break
        except Exception as wait_err:
            utils.logger.warning(f"[OutreachAutomation] Wait for PM button failed: {wait_err}")

        # 核心策略: 找到用户主页上的"私信"按钮（排除顶部导航栏的私信入口）
        # 用户主页的私信按钮特征：button标签，y坐标 > 100（不在顶部导航栏），宽度 > 0
        btn_info = await page.evaluate("""
            () => {
                const pmTexts = ['私信', '发消息', '私信TA'];
                // 优先找 button 标签
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    const text = btn.textContent?.trim();
                    if (pmTexts.includes(text)) {
                        const rect = btn.getBoundingClientRect();
                        // 排除顶部导航栏（y < 100）和不可见的按钮
                        if (rect.y > 100 && rect.width > 0 && rect.height > 0) {
                            return {x: rect.x + rect.width/2, y: rect.y + rect.height/2, w: rect.width, h: rect.height, tag: 'BUTTON', text: text};
                        }
                    }
                }
                // 备选：找其他标签类型的私信按钮（不在导航栏）
                const all = document.querySelectorAll('div, span, a');
                for (const el of all) {
                    const text = el.textContent?.trim();
                    if (pmTexts.includes(text)) {
                        const rect = el.getBoundingClientRect();
                        if (rect.y > 100 && rect.width > 0 && rect.height > 0 && rect.width > 30) {
                            return {x: rect.x + rect.width/2, y: rect.y + rect.height/2, w: rect.width, h: rect.height, tag: el.tagName, text: text};
                        }
                    }
                }
                return null;
            }
        """)

        if btn_info:
            utils.logger.info(f"[OutreachAutomation] Found PM button: {btn_info}")

            # 方法1: 使用JS dispatchEvent触发按钮点击（最可靠，直接触发React事件）
            try:
                click_result = await page.evaluate("""
                    () => {
                        const buttons = document.querySelectorAll('button');
                        for (const btn of buttons) {
                            const text = btn.textContent?.trim();
                            const rect = btn.getBoundingClientRect();
                            if (text === '私信' && rect.y > 100 && rect.width > 0) {
                                const events = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
                                for (const eventType of events) {
                                    btn.dispatchEvent(new MouseEvent(eventType, {
                                        bubbles: true, cancelable: true,
                                        clientX: rect.x + rect.width/2,
                                        clientY: rect.y + rect.height/2,
                                    }));
                                }
                                return {success: true, text: text, y: rect.y};
                            }
                        }
                        return {success: false};
                    }
                """)
                utils.logger.info(f"[OutreachAutomation] PM button clicked via JS dispatchEvent: {click_result}")
                await asyncio.sleep(5)
                # 检查IM容器是否打开
                im_check = await page.evaluate("""
                    () => {
                        const im = document.querySelector('.imContainer');
                        if (!im) return {found: false};
                        const r = im.getBoundingClientRect();
                        return {found: true, w: r.width, h: r.height};
                    }
                """)
                if im_check.get("w", 0) > 50:
                    utils.logger.info(f"[OutreachAutomation] IM container opened after JS click: {im_check}")
                    return (True, "")
                utils.logger.info(f"[OutreachAutomation] IM container not opened after JS click: {im_check}, trying mouse click...")
            except Exception as e:
                utils.logger.warning(f"[OutreachAutomation] JS click failed: {e}")

            # 方法2: 真实鼠标移动+点击
            try:
                await page.evaluate(f"() => {{ window.scrollTo(0, {max(0, btn_info['y'] - 200)}); }}")
                await asyncio.sleep(0.5)
                await page.mouse.move(btn_info['x'], btn_info['y'], steps=10)
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await page.mouse.click(btn_info['x'], btn_info['y'])
                utils.logger.info(f"[OutreachAutomation] PM button clicked via mouse.move+click at ({btn_info['x']:.0f}, {btn_info['y']:.0f})")
                await asyncio.sleep(5)
                return (True, "")
            except Exception as e:
                utils.logger.warning(f"[OutreachAutomation] Mouse click failed: {e}")

            # 方法3: Playwright locator click
            try:
                pm_locator = page.locator('button:has-text("私信")').nth(0)
                count = await pm_locator.count()
                for idx in range(count):
                    loc = page.locator('button:has-text("私信")').nth(idx)
                    box = await loc.bounding_box()
                    if box and box['y'] > 100:
                        await loc.click(force=True)
                        utils.logger.info(f"[OutreachAutomation] PM button clicked via locator at y={box['y']:.0f}")
                        await asyncio.sleep(5)
                        return (True, "")
            except Exception as e:
                utils.logger.warning(f"[OutreachAutomation] Locator click failed: {e}")

        # 备选策略: 在关注按钮附近查找私信按钮
        clicked_nearby = await page.evaluate("""
            () => {
                const all = Array.from(document.querySelectorAll('*')).filter(e => e.offsetParent !== null);
                const followBtn = all.find(el => {
                    const text = el.textContent?.trim();
                    return (text === '关注' || text === '已关注') && el.children.length === 0;
                });
                if (!followBtn) return null;

                const pmTexts = ['私信', '发消息', '私信TA'];
                let ancestor = followBtn.parentElement;
                for (let i = 0; i < 5 && ancestor; i++) {
                    const pmBtn = Array.from(ancestor.querySelectorAll('*')).find(el => {
                        const text = el.textContent?.trim();
                        return pmTexts.includes(text) && el !== followBtn && el.offsetParent !== null;
                    });
                    if (pmBtn) {
                        const rect = pmBtn.getBoundingClientRect();
                        return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};
                    }
                    ancestor = ancestor.parentElement;
                }
                return null;
            }
        """)
        if clicked_nearby:
            utils.logger.info("[OutreachAutomation] PM button clicked via nearby search")
            await page.mouse.click(clicked_nearby['x'], clicked_nearby['y'])
            await asyncio.sleep(5)
            return (True, "")

        # 调试：输出页面上所有按钮文本
        all_texts = await page.evaluate("""
            () => {
                const els = document.querySelectorAll('button, [role="button"], a');
                return Array.from(els).map(e => ({
                    text: e.textContent?.trim(),
                    rect: (() => { const r = e.getBoundingClientRect(); return {y: Math.round(r.y), w: Math.round(r.width)}; })()
                })).filter(t => t.text && t.text.length < 20 && t.rect.w > 0).slice(0, 20);
            }
        """)
        utils.logger.warning(f"[OutreachAutomation] PM button not found. Page buttons: {all_texts}")

        # 检测用户是否关闭了私信功能
        dm_disabled = await page.evaluate("""
            () => {
                // 检查是否有"未开启私信"等提示
                const body = document.body.innerText;
                if (body.includes('未开启私信') || body.includes('未开放私信') ||
                    body.includes('暂不接受私信') || body.includes('不允许私信') ||
                    body.includes('无法发送私信') || body.includes('私信功能未开启') ||
                    body.includes('该用户暂未开启私信')) {
                    return true;
                }
                // 检查是否只有"关注"按钮没有"私信"按钮（通常意味着关闭了私信）
                const buttons = document.querySelectorAll('button');
                let hasFollow = false;
                let hasPM = false;
                for (const btn of buttons) {
                    const text = btn.textContent?.trim();
                    const rect = btn.getBoundingClientRect();
                    if (rect.y > 100 && rect.width > 0) {
                        if (text === '关注' || text === '已关注') hasFollow = true;
                        if (text === '私信' || text === '发消息') hasPM = true;
                    }
                }
                // 有关注按钮但没有私信按钮，说明用户关闭了私信
                if (hasFollow && !hasPM) return true;
                return false;
            }
        """)
        if dm_disabled:
            utils.logger.info(f"[OutreachAutomation] User has DM disabled, skipping")
            return (False, "用户未开启私信")

        # 未找到私信按钮，尝试刷新页面后重试一次
        utils.logger.warning(f"[OutreachAutomation] PM button not found on first attempt, refreshing page to retry...")
        try:
            await page.reload(wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(random.uniform(5, 8))
            await page.evaluate("() => { window.scrollTo(0, 0); }")
            await asyncio.sleep(random.uniform(1, 2))

            # 刷新后重新查找私信按钮
            btn_info_retry = await page.evaluate("""
                () => {
                    const pmTexts = ['私信', '发消息', '私信TA'];
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = btn.textContent?.trim();
                        if (pmTexts.includes(text)) {
                            const rect = btn.getBoundingClientRect();
                            if (rect.y > 100 && rect.width > 0 && rect.height > 0) {
                                return {x: rect.x + rect.width/2, y: rect.y + rect.height/2, w: rect.width, h: rect.height, tag: 'BUTTON', text: text};
                            }
                        }
                    }
                    return null;
                }
            """)
            if btn_info_retry:
                utils.logger.info(f"[OutreachAutomation] PM button found after refresh: {btn_info_retry}")
                await page.mouse.move(btn_info_retry['x'], btn_info_retry['y'], steps=10)
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await page.mouse.click(btn_info_retry['x'], btn_info_retry['y'])
                await asyncio.sleep(5)
                return (True, "")

            # 刷新后再次检测用户是否关闭私信
            dm_disabled_retry = await page.evaluate("""
                () => {
                    const body = document.body.innerText;
                    if (body.includes('未开启私信') || body.includes('未开放私信') ||
                        body.includes('暂不接受私信') || body.includes('不允许私信') ||
                        body.includes('无法发送私信') || body.includes('私信功能未开启') ||
                        body.includes('该用户暂未开启私信')) {
                        return true;
                    }
                    const buttons = document.querySelectorAll('button');
                    let hasFollow = false;
                    let hasPM = false;
                    for (const btn of buttons) {
                        const text = btn.textContent?.trim();
                        const rect = btn.getBoundingClientRect();
                        if (rect.y > 100 && rect.width > 0) {
                            if (text === '关注' || text === '已关注') hasFollow = true;
                            if (text === '私信' || text === '发消息') hasPM = true;
                        }
                    }
                    if (hasFollow && !hasPM) return true;
                    return false;
                }
            """)
            if dm_disabled_retry:
                utils.logger.info(f"[OutreachAutomation] User has DM disabled (detected after refresh)")
                return (False, "用户未开启私信")

            # 刷新后仍然找不到，输出调试信息
            all_texts_retry = await page.evaluate("""
                () => {
                    const els = document.querySelectorAll('button, [role="button"], a');
                    return Array.from(els).map(e => ({
                        text: e.textContent?.trim(),
                        rect: (() => { const r = e.getBoundingClientRect(); return {y: Math.round(r.y), w: Math.round(r.width)}; })()
                    })).filter(t => t.text && t.text.length < 20 && t.rect.w > 0).slice(0, 20);
                }
            """)
            utils.logger.warning(f"[OutreachAutomation] PM button still not found after refresh. Page buttons: {all_texts_retry}")
        except Exception as retry_err:
            utils.logger.error(f"[OutreachAutomation] Page refresh retry failed: {retry_err}")

        return (False, "未找到私信按钮")
    except Exception as e:
        utils.logger.error(f"[OutreachAutomation] Click PM button failed: {e}")
        return (False, f"点击私信按钮异常: {str(e)}")


async def _wait_for_dialog(page: Page, timeout: int = 30, platform: str = "dy") -> bool:
    """等待私信对话框出现 - 支持抖音和小红书"""
    im_container_forced = False
    conversation_clicked = False
    
    for i in range(timeout // 2):
        # 检查输入框是否出现（通用检测）
        dialog_state = await page.evaluate("""
            () => {
                // 检查 contenteditable 输入框（抖音和小红书通用）
                const editables = document.querySelectorAll('[contenteditable="true"]');
                let inputFound = false;
                let inputRect = null;
                for (const e of editables) {
                    const r = e.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        // 排除搜索框等非聊天输入框（搜索框通常较窄）
                        const placeholder = e.getAttribute('data-placeholder') || '';
                        const cls = e.className || '';
                        const parentText = e.closest('.imContainer') ? 'in_im' : 'outside';
                        
                        if (placeholder.includes('发送') || placeholder.includes('消息') ||
                            cls.includes('messageEditor') || cls.includes('chat-input') ||
                            cls.includes('editor-kit')) {
                            inputFound = true;
                            inputRect = {x: r.x, y: r.y, w: r.width, h: r.height};
                            break;
                        }
                        // IM容器内的contenteditable元素，宽度>100即可认为是聊天输入框
                        if (parentText === 'in_im' && r.width > 100) {
                            inputFound = true;
                            inputRect = {x: r.x, y: r.y, w: r.width, h: r.height};
                            break;
                        }
                        // 如果没有明确的聊天标识，也接受较大的输入框
                        if (!inputFound && r.width > 200) {
                            inputFound = true;
                            inputRect = {x: r.x, y: r.y, w: r.width, h: r.height};
                        }
                    }
                }
                // 检查 textarea 输入框（小红书可能用 textarea）
                if (!inputFound) {
                    const textareas = document.querySelectorAll('textarea');
                    for (const ta of textareas) {
                        const r = ta.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0 && r.width > 100) {
                            inputFound = true;
                            inputRect = {x: r.x, y: r.y, w: r.width, h: r.height};
                            break;
                        }
                    }
                }
                // 检查IM容器尺寸（抖音）
                const imContainer = document.querySelector('.imContainer');
                const imRect = imContainer ? (() => { const r = imContainer.getBoundingClientRect(); return {w: r.width, h: r.height}; })() : null;
                // 检查小红书聊天窗口
                const xhsChat = document.querySelector('.chat-input, [class*="chat-input"], [class*="message-input"], [class*="pm-dialog"], [class*="chat-container"]');
                const xhsChatRect = xhsChat ? (() => { const r = xhsChat.getBoundingClientRect(); return {w: r.width, h: r.height}; })() : null;
                
                // 检查IM容器内部结构（抖音）
                let imDetails = null;
                if (imContainer && imRect && imRect.w > 0) {
                    const convItems = imContainer.querySelectorAll('[class*="conversationItem"], [class*="conv-item"], [data-e2e="chat-item"]');
                    const newChatBtn = imContainer.querySelector('[data-e2e="im-new-chat"], [class*="new-chat"], button');
                    imDetails = {
                        convCount: convItems.length,
                        hasNewChatBtn: !!newChatBtn,
                        newChatBtnText: newChatBtn ? newChatBtn.textContent?.trim()?.substring(0, 20) : '',
                        innerHTML: imContainer.innerHTML?.substring(0, 200),
                    };
                }
                
                return { inputFound, inputRect, imRect, xhsChatRect, imDetails };
            }
        """)

        if dialog_state.get("inputFound"):
            utils.logger.info(f"[OutreachAutomation] Dialog input found after {(i+1)*2}s: {dialog_state['inputRect']}")
            return True

        # IM容器存在但尺寸为0，说明IM面板还没打开或被隐藏
        im_rect = dialog_state.get("imRect")
        if im_rect and im_rect.get("w") == 0 and not im_container_forced:
            im_container_forced = True
            utils.logger.info("[OutreachAutomation] IM container is 0x0, trying to wait for it to appear naturally...")
            
            # 等待IM容器自然出现（最多15秒）
            im_appeared = False
            for wait_i in range(15):
                await asyncio.sleep(1)
                im_size = await page.evaluate("""
                    () => {
                        const im = document.querySelector('.imContainer');
                        if (!im) return {w: 0, h: 0};
                        const r = im.getBoundingClientRect();
                        return {w: r.width, h: r.height};
                    }
                """)
                if im_size.get("w", 0) > 50:
                    utils.logger.info(f"[OutreachAutomation] IM container appeared naturally after {wait_i+1}s: {im_size}")
                    im_appeared = True
                    break
            
            if not im_appeared:
                # 如果IM容器没有自然出现，尝试force显示作为后备
                utils.logger.warning("[OutreachAutomation] IM container did not appear naturally, force showing...")
                await page.evaluate("""
                    () => {
                        const im = document.querySelector('.imContainer');
                        if (!im) return;
                        let el = im;
                        for (let j = 0; j < 10; j++) {
                            el = el.parentElement;
                            if (!el || el === document.body) break;
                            const s = window.getComputedStyle(el);
                            if (s.display === 'none') {
                                el.style.display = 'flex';
                                el.style.visibility = 'visible';
                                break;
                            }
                        }
                    }
                """)
            await asyncio.sleep(2)
            continue

        # IM容器有尺寸但没有输入框 → 需要在IM面板中点击对话或新建对话
        if im_rect and im_rect.get("w", 0) > 100 and not dialog_state.get("inputFound") and not conversation_clicked:
            conversation_clicked = True
            utils.logger.info(f"[OutreachAutomation] IM container open ({im_rect['w']}x{im_rect['h']}) but no input, trying to click conversation...")
            im_details = dialog_state.get("imDetails", {})
            utils.logger.info(f"[OutreachAutomation] IM details: {im_details}")
            
            # 策略0: 点击IM面板中的"+"按钮（新建对话），然后搜索目标用户
            new_chat_result = await page.evaluate("""
                () => {
                    const imContainer = document.querySelector('.imContainer');
                    if (!imContainer) return null;
                    
                    // 查找新建对话按钮（"+"图标、data-e2e="im-new-chat"等）
                    const newChatSelectors = [
                        '[data-e2e="im-new-chat"]',
                        '[data-e2e="new-chat"]',
                        '[class*="new-chat"]',
                        '[class*="add-chat"]',
                        '[class*="create-chat"]',
                    ];
                    
                    for (const sel of newChatSelectors) {
                        const btn = imContainer.querySelector(sel);
                        if (btn) {
                            const rect = btn.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                btn.click();
                                return {action: 'new_chat_click', selector: sel, x: rect.x + rect.width/2, y: rect.y + rect.height/2};
                            }
                        }
                    }
                    
                    // 查找包含"+"或"发消息"文本的按钮
                    const allBtns = imContainer.querySelectorAll('button, [role="button"], div[class*="icon"], svg');
                    for (const btn of allBtns) {
                        const text = btn.textContent?.trim() || '';
                        const title = btn.getAttribute('title') || btn.getAttribute('aria-label') || '';
                        const cls = btn.className?.toString() || '';
                        if (text.includes('发消息') || text.includes('新建') || title.includes('发消息') || title.includes('新建') ||
                            title.includes('新聊天') || title.includes('new chat') ||
                            cls.includes('new-chat') || cls.includes('add') || cls.includes('create')) {
                            const rect = btn.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0 && rect.y > 50) {
                                btn.click();
                                return {action: 'new_chat_click', text: text, title: title, cls: cls.substring(0, 40), x: rect.x + rect.width/2, y: rect.y + rect.height/2};
                            }
                        }
                    }
                    
                    // 查找SVG加号图标（抖音新版可能用图标代替文字）
                    const svgBtns = imContainer.querySelectorAll('svg');
                    for (const svg of svgBtns) {
                        const parent = svg.closest('button, [role="button"], div[class*="icon"]');
                        if (!parent) continue;
                        const path = svg.querySelector('path');
                        const d = path ? path.getAttribute('d') || '' : '';
                        const title = parent.getAttribute('title') || parent.getAttribute('aria-label') || '';
                        // 加号图标的path通常包含M和L的特定模式
                        if (title.includes('新建') || title.includes('发消息') || title.includes('新聊天') || title.includes('new')) {
                            const rect = parent.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                parent.click();
                                return {action: 'new_chat_click', svg_title: title, x: rect.x + rect.width/2, y: rect.y + rect.height/2};
                            }
                        }
                    }
                    
                    return null;
                }
            """)
            
            if new_chat_result:
                utils.logger.info(f"[OutreachAutomation] Clicked new chat button: {new_chat_result}")
                await asyncio.sleep(2)
                
                # 在搜索框中输入目标用户昵称
                # 先尝试找到搜索框
                search_result = await page.evaluate("""
                    () => {
                        const imContainer = document.querySelector('.imContainer');
                        if (!imContainer) return null;
                        
                        // 查找搜索输入框
                        const searchInputs = imContainer.querySelectorAll('input[type="text"], input[type="search"], input:not([type]), textarea');
                        for (const input of searchInputs) {
                            const rect = input.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                const placeholder = input.getAttribute('placeholder') || '';
                                input.focus();
                                return {action: 'search_input_found', placeholder: placeholder, x: rect.x + rect.width/2, y: rect.y + rect.height/2};
                            }
                        }
                        
                        // 查找contenteditable搜索框
                        const editables = imContainer.querySelectorAll('[contenteditable="true"]');
                        for (const el of editables) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                el.focus();
                                return {action: 'search_editable_found', x: rect.x + rect.width/2, y: rect.y + rect.height/2};
                            }
                        }
                        
                        return null;
                    }
                """)
                
                if search_result:
                    utils.logger.info(f"[OutreachAutomation] Found search input: {search_result}")
                    # 获取目标用户昵称（从页面标题或用户信息中提取）
                    target_nickname = await page.evaluate("""
                        () => {
                            // 从页面标题提取昵称（格式：xxx的抖音 - 抖音）
                            const title = document.title || '';
                            const match = title.match(/^(.+?)的抖音/);
                            if (match) return match[1];
                            // 从用户信息区域提取
                            const nickEl = document.querySelector('[class*="nickname"], [class*="user-name"], h1, h2');
                            return nickEl ? nickEl.textContent?.trim() : '';
                        }
                    """)
                    
                    if target_nickname:
                        utils.logger.info(f"[OutreachAutomation] Typing target nickname: {target_nickname}")
                        # 使用keyboard输入昵称
                        await page.keyboard.type(target_nickname, delay=100)
                        await asyncio.sleep(2)
                        
                        # 点击搜索结果中的第一个用户
                        user_clicked = await page.evaluate("""
                            () => {
                                const imContainer = document.querySelector('.imContainer');
                                if (!imContainer) return null;
                                
                                // 查找搜索结果列表项
                                const resultItems = imContainer.querySelectorAll('[class*="search-result"], [class*="user-item"], [class*="result-item"], [data-e2e="search-user-item"]');
                                for (const item of resultItems) {
                                    const rect = item.getBoundingClientRect();
                                    if (rect.width > 0 && rect.height > 0) {
                                        item.click();
                                        return {action: 'user_clicked', text: item.textContent?.trim()?.substring(0, 30)};
                                    }
                                }
                                
                                // 如果没有特定搜索结果，尝试点击列表中的第一个可点击项
                                const listItems = imContainer.querySelectorAll('[class*="list"] > div, [class*="item"]');
                                for (const item of listItems) {
                                    const rect = item.getBoundingClientRect();
                                    if (rect.width > 50 && rect.height > 20 && rect.y > 100) {
                                        item.click();
                                        return {action: 'list_item_clicked', text: item.textContent?.trim()?.substring(0, 30)};
                                    }
                                }
                                
                                return null;
                            }
                        """)
                        
                        if user_clicked:
                            utils.logger.info(f"[OutreachAutomation] Clicked search result: {user_clicked}")
                            await asyncio.sleep(3)
                            continue
                    else:
                        utils.logger.warning("[OutreachAutomation] Could not extract target nickname from page")
                else:
                    utils.logger.warning("[OutreachAutomation] No search input found after clicking new chat")
            
            # 策略1: 点击第一个对话项（回退方案）
            clicked_conv = await page.evaluate("""
                () => {
                    const imContainer = document.querySelector('.imContainer');
                    if (!imContainer) return null;
                    
                    // 查找对话列表项
                    const convSelectors = [
                        '[class*="conversationItem"]',
                        '[class*="conv-item"]', 
                        '[data-e2e="chat-item"]',
                        '[class*="chat-item"]',
                        '[class*="session"]',
                    ];
                    
                    for (const sel of convSelectors) {
                        const items = imContainer.querySelectorAll(sel);
                        for (const item of items) {
                            const rect = item.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                item.click();
                                return {selector: sel, w: Math.round(rect.width), h: Math.round(rect.height)};
                            }
                        }
                    }
                    
                    // 如果没有对话列表项，尝试点击IM容器内的第一个可点击元素
                    const clickables = imContainer.querySelectorAll('div[role="button"], button, [data-e2e]');
                    for (const el of clickables) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 30 && rect.height > 10 && rect.y > 100) {
                            el.click();
                            return {selector: 'clickable', text: el.textContent?.trim()?.substring(0, 20), w: Math.round(rect.width)};
                        }
                    }
                    
                    return null;
                }
            """)
            if clicked_conv:
                utils.logger.info(f"[OutreachAutomation] Clicked conversation: {clicked_conv}")
                await asyncio.sleep(3)
                continue
            
            # 策略2: 点击"发消息"或新建对话按钮
            new_chat_clicked = await page.evaluate("""
                () => {
                    const imContainer = document.querySelector('.imContainer');
                    if (!imContainer) return null;
                    
                    const btns = imContainer.querySelectorAll('button, [role="button"], [data-e2e]');
                    for (const btn of btns) {
                        const text = btn.textContent?.trim() || '';
                        const e2e = btn.getAttribute('data-e2e') || '';
                        if (text.includes('发消息') || text.includes('新建') || text.includes('+') ||
                            e2e.includes('new-chat') || e2e.includes('create')) {
                            const rect = btn.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                btn.click();
                                return {text: text, e2e: e2e};
                            }
                        }
                    }
                    return null;
                }
            """)
            if new_chat_clicked:
                utils.logger.info(f"[OutreachAutomation] Clicked new chat button: {new_chat_clicked}")
                await asyncio.sleep(3)
                continue

        # 小红书：如果在消息中心页面，检查是否有聊天窗口出现
        if platform == "xhs" and "message" in page.url:
            xhs_rect = dialog_state.get("xhsChatRect")
            if xhs_rect and xhs_rect.get("w", 0) > 0:
                utils.logger.info(f"[OutreachAutomation] XHS chat window found: {xhs_rect}")
                return True

        if i % 4 == 0 and i > 0:
            utils.logger.info(f"[OutreachAutomation] Waiting for dialog... {(i+1)*2}s, state: {dialog_state}")
        await asyncio.sleep(2)

    # 最后尝试：检查所有 contenteditable 元素和IM容器内部结构
    final_check = await page.evaluate("""
        () => {
            const all = document.querySelectorAll('[contenteditable]');
            const editables = Array.from(all).map(e => ({
                tag: e.tagName,
                placeholder: e.getAttribute('data-placeholder'),
                visible: e.offsetParent !== null,
                rect: (() => { const r = e.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height)}; })()
            }));
            // 检查IM容器内部
            const im = document.querySelector('.imContainer');
            let imInfo = null;
            if (im) {
                const r = im.getBoundingClientRect();
                imInfo = {
                    size: `${Math.round(r.width)}x${Math.round(r.height)}`,
                    childCount: im.children.length,
                    firstChildTag: im.children[0]?.tagName,
                    firstChildCls: im.children[0]?.className?.toString()?.substring(0, 60),
                    textPreview: im.textContent?.substring(0, 100),
                };
            }
            return {editables, imInfo};
        }
    """)
    utils.logger.warning(f"[OutreachAutomation] Dialog input not found. Final check: {final_check}")
    return False


async def _type_and_send(page: Page, content: str, platform: str = "dy") -> tuple[bool, str]:
    """在私信对话框中输入并发送消息 - 支持抖音和小红书"""
    try:
        # 找到输入框
        input_loc = page.locator('div[contenteditable="true"]').first
        is_contenteditable = True
        if await input_loc.count() == 0:
            input_loc = page.locator('textarea').first
            is_contenteditable = False
        if await input_loc.count() == 0:
            return False, "未找到私信输入框"

        # 使用纯 JS 操作输入框（绕过 Playwright 视口限制）
        # 抖音私信输入框在可滚动容器内，Playwright 无法正确滚动到它
        escaped = content.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
        input_ok = await page.evaluate(f"""
            () => {{
                const input = document.querySelector('div[contenteditable="true"]') || document.querySelector('textarea');
                if (!input) return false;
                // 滚动输入框到容器可视区域
                input.scrollIntoView({{block: 'center', behavior: 'instant'}});
                input.focus();
                // 清空已有内容
                if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {{
                    input.value = '';
                }} else {{
                    input.innerHTML = '<br>';
                }}
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                return true;
            }}
        """)
        if not input_ok:
            return False, "未找到私信输入框"
        await asyncio.sleep(0.3)

        # 通过 keyboard.type 输入内容（最接近真实用户输入）
        await page.keyboard.type(content, delay=random.randint(20, 60))
        await asyncio.sleep(1)

        # 验证输入是否成功
        input_text = await page.evaluate("""
            () => {
                const input = document.querySelector('div[contenteditable="true"]') || document.querySelector('textarea');
                if (!input) return '';
                return input.innerText || input.value || '';
            }
        """)
        if not input_text.strip():
            utils.logger.warning("[OutreachAutomation] Input empty after fill, trying JS fallback...")
            # JS fallback：直接设置 innerText
            escaped = content.replace("`", "\\`").replace("\\", "\\\\")
            await page.evaluate(f"""
                () => {{
                    const input = document.querySelector('div[contenteditable="true"]') || document.querySelector('textarea');
                    if (!input) return;
                    input.focus();
                    if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {{
                        input.value = `{escaped}`;
                    }} else {{
                        input.innerText = `{escaped}`;
                    }}
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            """)
            await asyncio.sleep(0.5)

        # 点击发送按钮
        send_ok = await page.evaluate("""
            () => {
                // 抖音：优先使用 e2e-send-msg-btn
                const e2eBtn = document.querySelector('.e2e-send-msg-btn');
                if (e2eBtn) {
                    e2eBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                    return 'e2e';
                }
                // 通用：查找"发送"文本按钮
                const btns = document.querySelectorAll('button, div, span');
                for (const btn of btns) {
                    const text = btn.textContent?.trim();
                    if ((text === '发送' || text === 'Send') && btn.offsetParent !== null) {
                        btn.click();
                        return 'text';
                    }
                }
                // 小红书：查找发送图标按钮（可能在输入框旁边）
                const sendIcons = document.querySelectorAll('[class*="send"], [class*="submit"]');
                for (const icon of sendIcons) {
                    const rect = icon.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        icon.click();
                        return 'icon';
                    }
                }
                return null;
            }
        """)

        if not send_ok:
            # Fallback: 按 Enter 键
            await input_loc.press('Enter')
            send_ok = 'enter'
            utils.logger.info("[OutreachAutomation] Sent via Enter key fallback")

        utils.logger.info(f"[OutreachAutomation] Send method: {send_ok}")
        await asyncio.sleep(3)

        # 检查风控错误 — 只检查发送后新出现的提示
        # 先获取发送前IM面板的文本快照（在发送前已保存）
        error_keywords = await page.evaluate("""
            () => {
                // 检查是否有明显的风控弹窗/提示（toast、modal等）
                // 这些通常是发送后新出现的，不在历史消息中
                const toastSelectors = [
                    '[class*="toast"]', '[class*="Toast"]',
                    '[class*="modal"]', '[class*="Modal"]',
                    '[class*="alert"]', '[class*="Alert"]',
                    '[class*="notice"]', '[class*="Notice"]',
                    '[class*="message-tip"]', '[class*="tip-bar"]',
                    '[role="alert"]', '[role="status"]',
                ];
                
                for (const sel of toastSelectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const text = el.innerText || el.textContent || '';
                        const keywords = ['系统繁忙', '重新登录', '操作频繁', '发送失败', '暂时无法', '无法发送', '频繁操作', '稍后再试', '限制'];
                        const found = keywords.filter(p => text.includes(p));
                        if (found.length > 0) {
                            return found;
                        }
                    }
                }
                
                // 检查输入框附近是否有错误提示（紧邻输入框的提示文字）
                const input = document.querySelector('div[contenteditable="true"]') || document.querySelector('textarea');
                if (input) {
                    // 检查输入框的父级容器中是否有错误提示
                    let container = input.parentElement;
                    for (let i = 0; i < 3 && container; i++) {
                        const siblings = container.parentElement ? Array.from(container.parentElement.children) : [];
                        for (const sib of siblings) {
                            if (sib === container) continue;
                            const sibText = sib.innerText || sib.textContent || '';
                            const keywords = ['系统繁忙', '重新登录', '操作频繁', '发送失败', '暂时无法', '无法发送', '频繁操作', '稍后再试'];
                            const found = keywords.filter(p => sibText.includes(p));
                            if (found.length > 0) return found;
                        }
                        container = container.parentElement;
                    }
                }
                
                // 最后检查：输入框是否被清空（发送成功的标志）
                // 如果输入框内容已清空，说明发送成功，不需要检查风控
                const inputEl = document.querySelector('div[contenteditable="true"]') || document.querySelector('textarea');
                if (inputEl) {
                    const val = inputEl.innerText || inputEl.value || '';
                    if (val.trim().length === 0) {
                        return []; // 输入框已清空，发送成功
                    }
                }
                
                return [];
            }
        """)

        if error_keywords:
            error_msg = ', '.join(error_keywords)
            utils.logger.warning(f"[OutreachAutomation] Risk control detected: {error_msg}")

            # 如果是登录问题，直接返回错误 + 进入冷却
            if any(k in error_keywords for k in ['重新登录', '无法发送']):
                _enter_risk_control_cooldown(1800)  # 冷却30分钟（之前1小时太长）
                return False, f"风控拦截: {error_msg}，请刷新Cookie后重试"

            # 操作频繁 → 进入冷却期
            if '操作频繁' in error_keywords:
                _enter_risk_control_cooldown(600)  # 冷却10分钟（之前30分钟太长）
                return False, f"风控拦截: 操作频繁，已进入10分钟冷却期"

            # 其他错误，等待后重试一次
            _enter_risk_control_cooldown(300)  # 轻度冷却5分钟
            utils.logger.info("[OutreachAutomation] Waiting 60s before retry...")
            await asyncio.sleep(60)

            # 重新输入并发送（纯 JS 方式绕过视口限制）
            await page.evaluate("""
                () => {
                    const input = document.querySelector('div[contenteditable="true"]') || document.querySelector('textarea');
                    if (input) { input.scrollIntoView({block: 'center'}); input.focus(); }
                }
            """)
            await page.keyboard.type(content, delay=random.randint(20, 60))
            await asyncio.sleep(1)
            await page.evaluate("""
                () => {
                    const e2eBtn = document.querySelector('.e2e-send-msg-btn');
                    if (e2eBtn) e2eBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                }
            """)
            await asyncio.sleep(3)

            # 再次检查
            error_keywords2 = await page.evaluate("""
                () => {
                    const text = document.body.innerText;
                    return ['系统繁忙', '重新登录', '操作频繁', '发送失败', '暂时无法', '无法发送']
                        .filter(p => text.includes(p));
                }
            """)
            if error_keywords2:
                return False, f"重试后仍被风控拦截: {', '.join(error_keywords2)}"

        # 验证发送成功：检查输入框是否清空
        input_cleared = await page.evaluate("""
            () => {
                const input = document.querySelector('div[contenteditable="true"]') || document.querySelector('textarea');
                if (!input) return true;
                const val = input.innerText || input.value || '';
                return val.trim().length === 0;
            }
        """)

        if input_cleared:
            utils.logger.info("[OutreachAutomation] Input cleared, message sent successfully")
            return True, ""

        # 输入框未清空，可能发送失败
        utils.logger.warning("[OutreachAutomation] Input not cleared, checking message count...")
        msg_count = await page.evaluate("""
            () => {
                const selectors = ['[class*="message-item"]', '[class*="chat-item"]', '[class*="bubble"]'];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) return els.length;
                }
                return 0;
            }
        """)
        utils.logger.info(f"[OutreachAutomation] Message count in dialog: {msg_count}")

        if msg_count > 0:
            return True, ""

        return False, "消息发送后验证失败，输入框未清空且对话框无消息"

    except Exception as e:
        return False, f"发送过程异常: {str(e)}"


# ==================== 主流程 ====================

async def execute_outreach_automation(task_id: str) -> Dict[str, Any]:
    """执行自动化触达任务"""
    task = _outreach_tasks.get(task_id)
    if not task:
        return {"success": False, "error": "Task not found"}

    # 频率限制 — 自动等待并重试（最多等待5分钟）
    allowed, reason = _check_rate_limit()
    if not allowed:
        max_total_wait = 300  # 最多总共等待5分钟
        total_waited = 0
        while not allowed and total_waited < max_total_wait:
            # 解析等待秒数
            import re
            wait_match = re.search(r'等待\s*(\d+)\s*秒', reason)
            wait_seconds = int(wait_match.group(1)) if wait_match else 60
            # 多等5秒确保间隔足够
            wait_seconds = min(wait_seconds + 5, max_total_wait - total_waited)
            
            _append_log(task, f"⏳ 频率限制，自动等待 {wait_seconds} 秒后重试...")
            _update_step(task, 1, "running", f"等待发送间隔 ({wait_seconds}秒)...")
            await _sync_task_to_db(task)
            await asyncio.sleep(wait_seconds)
            total_waited += wait_seconds
            
            # 重新检查
            allowed, reason = _check_rate_limit()
        
        if not allowed:
            _append_log(task, f"❌ 等待{total_waited}秒后仍被限制: {reason}")
            task.status = OutreachStatus.FAILED
            task.error_message = reason
            await _sync_task_to_db(task)
            return {"success": False, "error": reason}
        _append_log(task, "✅ 等待结束，继续执行")

    task.status = OutreachStatus.RUNNING
    _append_log(task, f"任务启动 - 目标: {task.nickname} ({task.sec_uid[:20]}...)")
    await _sync_task_to_db(task)

    browser_context = None
    page = None
    cdp_manager = None
    playwright = None
    screenshot_filename = ""

    # 获取浏览器锁，防止并发任务同时使用浏览器导致冲突
    async with _browser_lock:
        utils.logger.info(f"[OutreachAutomation] Acquired browser lock for task {task_id}")
        try:
            # Step 1: 启动浏览器
            _update_step(task, 1, "running", "正在启动浏览器...")
            browser_context, page, cdp_manager, playwright = await _launch_browser_for_outreach(platform=task.platform)
            _append_log(task, "✅ 浏览器启动成功")
            _update_step(task, 1, "success", "浏览器启动成功")
            await _sync_task_to_db(task)

            # Step 2: 根据触达方式执行不同逻辑
            if task.method == "comment_reply":
                # ===== 评论回复模式 =====
                if not task.note_id:
                    _update_step(task, 1, "failed", "缺少视频ID(note_id)，无法回复评论")
                    task.status = OutreachStatus.FAILED
                    task.error_message = "缺少视频ID(note_id)"
                    await _sync_task_to_db(task)
                    return {"success": False, "error": "缺少视频ID(note_id)"}
                
                if not task.comment_id:
                    _update_step(task, 1, "failed", "缺少评论ID(comment_id)，无法回复评论")
                    task.status = OutreachStatus.FAILED
                    task.error_message = "缺少评论ID(comment_id)"
                    await _sync_task_to_db(task)
                    return {"success": False, "error": "缺少评论ID(comment_id)"}

                # 访问视频页面
                _update_step(task, 2, "running", "正在访问视频页面...")
                video_url = f"https://www.douyin.com/video/{task.note_id}"
                _append_log(task, f"正在访问视频页面: {video_url}")
                
                try:
                    await page.goto(video_url, wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(random.uniform(5, 8))
                except Exception as nav_err:
                    _append_log(task, f"⚠️ 视频页面加载超时，继续尝试: {nav_err}")
                
                # 处理弹窗
                try:
                    await page.evaluate("""() => {
                        const els = Array.from(document.querySelectorAll('button, div, span'));
                        for (const el of els) {
                            const text = el.textContent?.trim();
                            if ((text === '保存' || text === '取消' || text === '我知道了') && el.offsetParent !== null) {
                                el.click(); return;
                            }
                        }
                    }""")
                    await asyncio.sleep(1)
                except Exception:
                    pass
                
                await _simulate_human_browse(page, duration=random.uniform(5, 10))
                _append_log(task, "✅ 视频页面加载完成")
                _update_step(task, 2, "success", "已打开视频页面")
                await _sync_task_to_db(task)

                # 通过浏览器自动化回复评论
                _update_step(task, 3, "running", "正在查找评论并回复...")
                await _save_debug_screenshot(page, task.id, "before_comment_reply")
                
                reply_ok, reply_err = await _reply_to_comment_on_page(
                    page, task.content, task.comment_id, task.nickname
                )
                
                if not reply_ok:
                    _append_log(task, f"❌ 评论回复失败: {reply_err}")
                    debug_ss = await _save_debug_screenshot(page, task.id, "comment_reply_failed")
                    _update_step(task, 3, "failed", f"评论回复失败: {reply_err}", debug_ss)
                    task.status = OutreachStatus.FAILED
                    task.error_message = reply_err
                    await _sync_task_to_db(task)
                    return {"success": False, "error": reply_err}
                
                _append_log(task, "✅ 评论回复成功")
                _update_step(task, 3, "success", "评论已回复")
                _record_send()
                await _sync_task_to_db(task)
                
            else:
                # ===== 私信模式（原有逻辑） =====
                _update_step(task, 2, "running", "正在访问用户主页...")
                target_id = task.user_id if task.platform == "xhs" else task.sec_uid
                nav_ok = await _navigate_to_user_page(page, target_id, task.platform)
                if not nav_ok:
                    _update_step(task, 2, "failed", "访问用户主页失败")
                    task.status = OutreachStatus.FAILED
                    task.error_message = "访问用户主页失败"
                    await _sync_task_to_db(task)
                    return {"success": False, "error": "访问用户主页失败"}

                # 模拟真人浏览（使用增强版行为模拟）
                await _simulate_human_browse(page, duration=random.uniform(8, 15))
                await page.evaluate("() => { window.scrollTo(0, 0); }")
                await asyncio.sleep(random.uniform(1, 2))

                # 检测页面是否加载异常（如"服务异常"），自动刷新重试
                page_error = await page.evaluate("""() => {
                    const body = document.body.innerText;
                    if (body.includes('服务异常') || body.includes('页面加载失败') ||
                        body.includes('网络异常') || body.includes('加载失败')) {
                        return 'page_error';
                    }
                    // 检查用户主页关键元素是否存在（用户信息区域）
                    const buttons = document.querySelectorAll('button');
                    let hasProfileBtn = false;
                    for (const btn of buttons) {
                        const text = btn.textContent?.trim();
                        const rect = btn.getBoundingClientRect();
                        if (rect.y > 100 && rect.width > 0) {
                            if (text === '关注' || text === '已关注' || text === '私信') hasProfileBtn = true;
                        }
                    }
                    if (!hasProfileBtn) return 'no_profile_buttons';
                    return null;
                }""")
                if page_error:
                    utils.logger.warning(f"[OutreachAutomation] Page load issue detected: {page_error}, refreshing...")
                    _append_log(task, f"⚠️ 页面加载异常({page_error})，正在刷新重试...")
                    try:
                        await page.reload(wait_until='domcontentloaded', timeout=20000)
                        await asyncio.sleep(random.uniform(5, 8))
                        await _simulate_human_browse(page, duration=random.uniform(3, 6))
                        await page.evaluate("() => { window.scrollTo(0, 0); }")
                        await asyncio.sleep(random.uniform(1, 2))
                        _append_log(task, "✅ 页面刷新完成")
                    except Exception as reload_err:
                        utils.logger.warning(f"[OutreachAutomation] Page reload failed: {reload_err}")
                        _append_log(task, f"⚠️ 页面刷新失败: {reload_err}")

                _append_log(task, "✅ 用户主页加载完成")
                _update_step(task, 2, "success", "已访问用户主页")
                await _sync_task_to_db(task)

                # Step 3: 点击私信按钮 + 输入发送
                _update_step(task, 3, "running", "正在发送私信...")

                # 保存截图用于调试
                await _save_debug_screenshot(page, task.id, "before_pm_click")

                pm_ok, pm_reason = await _click_pm_button(page, task.platform, user_id=task.user_id)
                if not pm_ok:
                    # 区分"用户未开启私信"和"未找到按钮"
                    if pm_reason == "用户未开启私信":
                        _update_step(task, 3, "skipped", "用户未开启私信")
                        task.status = OutreachStatus.FAILED
                        task.error_message = "用户未开启私信"
                        await _sync_task_to_db(task)
                        return {"success": False, "error": "用户未开启私信", "skip_retry": True}
                    else:
                        _update_step(task, 3, "failed", pm_reason or "未找到私信按钮")
                        task.status = OutreachStatus.FAILED
                        task.error_message = pm_reason or "未找到私信按钮"
                        await _sync_task_to_db(task)
                        # 关闭浏览器缓存，下次重新启动（可能是登录过期或页面状态异常）
                        utils.logger.info("[OutreachAutomation] PM button not found (not user-disabled), closing browser cache for fresh start...")
                        await _close_cached_browser()
                        return {"success": False, "error": pm_reason or "未找到私信按钮"}

                # 等待对话框
                dialog_ok = await _wait_for_dialog(page, timeout=30, platform=task.platform)
                if not dialog_ok:
                    # 保存截图和页面URL用于调试
                    debug_ss = await _save_debug_screenshot(page, task.id, "no_dialog")
                    current_url = page.url
                    utils.logger.warning(f"[OutreachAutomation] Dialog not found. URL: {current_url}")
                    _update_step(task, 3, "failed", "私信对话框未出现", debug_ss)
                    task.status = OutreachStatus.FAILED
                    task.error_message = "私信对话框未出现"
                    await _sync_task_to_db(task)
                    return {"success": False, "error": "私信对话框未出现"}

                # 模拟真人：打开对话框后先浏览对话，再输入消息
                await asyncio.sleep(random.uniform(3, 8))
                # 模拟鼠标在对话区域移动
                await page.mouse.move(random.randint(1100, 1600), random.randint(300, 600), steps=8)
                await asyncio.sleep(random.uniform(2, 5))

                # 准备消息内容
                msg_content = _randomize_content(task.content)
                msg_content = _clean_content_for_risk(msg_content)
                if msg_content != task.content:
                    _append_log(task, "消息内容已随机微调并清理敏感词")

                # 输入并发送
                send_ok, send_err = await _type_and_send(page, msg_content, platform=task.platform)
                if not send_ok:
                    _append_log(task, f"❌ 发送失败: {send_err}")
                    debug_ss = await _save_debug_screenshot(page, task.id, "send_failed")
                    _update_step(task, 3, "failed", f"发送失败: {send_err}", debug_ss)
                    task.status = OutreachStatus.FAILED
                    task.error_message = send_err
                    await _sync_task_to_db(task)
                    return {"success": False, "error": send_err}

                _append_log(task, "✅ 私信发送成功")
                _update_step(task, 3, "success", "私信已发送")
                _record_send()
                await _sync_task_to_db(task)

            # Step 4: 截图确认
            _update_step(task, 4, "running", "正在保存结果截图...")
            await asyncio.sleep(2)
            try:
                screenshot_dir = os.path.join(os.getcwd(), "data", "outreach_screenshots")
                os.makedirs(screenshot_dir, exist_ok=True)
                screenshot_filename = f"{task_id}_result_{int(time.time())}.png"
                await page.screenshot(path=os.path.join(screenshot_dir, screenshot_filename), full_page=True)
                _append_log(task, f"✅ 截图已保存: {screenshot_filename}")
            except Exception as e:
                _append_log(task, f"⚠️ 截图保存失败: {e}")
            _update_step(task, 4, "success", "已保存结果截图", screenshot_filename)

            # 完成
            task.status = OutreachStatus.SUCCESS
            _append_log(task, "🎉 任务执行成功 - 私信已发送")

            user_homepage = f"https://www.douyin.com/user/{task.sec_uid}"
            if task.platform == "xhs":
                user_homepage = f"https://www.xiaohongshu.com/user/profile/{task.user_id}"

            task.result = {
                "success": True, "message": "私信发送成功",
                "user_homepage": user_homepage, "content": task.content,
            }

            await _save_outreach_record(task, "success", screenshot=screenshot_filename)
            await _sync_task_to_db(task)
            return {"success": True, "task_id": task_id, "status": "success", "message": "私信发送成功"}

        except Exception as e:
            utils.logger.error(f"[OutreachAutomation] Task {task_id} failed: {e}")
            _append_log(task, f"❌ 执行异常: {e}")
            task.status = OutreachStatus.FAILED
            task.error_message = str(e)
            await _save_outreach_record(task, "failed", error_message=str(e))
            await _sync_task_to_db(task)
            # 如果是浏览器相关异常，关闭缓存实例以便下次重新创建
            if any(kw in str(e).lower() for kw in ['browser', 'context', 'page', 'timeout', 'connect', 'target']):
                utils.logger.info("[OutreachAutomation] Browser-related error, invalidating cache...")
                await _close_cached_browser()
            return {"success": False, "error": str(e)}

        finally:
            # 不关闭浏览器，保持缓存复用
            # 只更新最后使用时间
            global _browser_last_used
            _browser_last_used = time.time()
            # 如果是风控失败，关闭浏览器实例（下次重新启动以刷新状态）
            if task.status == OutreachStatus.FAILED and task.error_message and '风控' in task.error_message:
                utils.logger.info("[OutreachAutomation] Risk control failure, closing browser for fresh start next time...")
                await _close_cached_browser()


async def execute_outreach_async(task_id: str):
    """异步执行触达任务（后台运行）"""
    asyncio.create_task(execute_outreach_automation(task_id))
