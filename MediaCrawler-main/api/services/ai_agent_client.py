# -*- coding: utf-8 -*-
"""
X Twitter 工作台 AI Agent 客户端

调用用户配置的 AI Agent API（OpenAI 兼容格式）完成：
1. 视频拆解（脚本/分镜/关键要点/推荐评论）
2. 评论生成（基于拆解结果生成可发送的评论）
3. 自动回复（针对他人回复，生成自然、带表情的回复）

可靠性:
- 使用 tenacity 实现指数退避重试(网络抖动/AI 服务短暂不可用时自动恢复)
- 5xx/超时/网络错误重试,4xx 不重试(参数问题重试无用)
- 重试次数和初始退避由 workbench_config 控制
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    RetryError,
)

from api.utils.workbench_config import workbench_config


logger = logging.getLogger("ai_agent_client")


def _load_config() -> Dict[str, str]:
    """从环境变量加载配置（兼容 .env 已加载的配置）"""
    return {
        "api_key": os.getenv("X_TWITTER_AI_API_KEY", ""),
        "base_url": os.getenv("X_TWITTER_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "model": os.getenv("X_TWITTER_AI_MODEL", "qwen-plus"),
        "tenant_id": os.getenv("DEFAULT_TENANT_ID", ""),
        "workspace_id": os.getenv("DEFAULT_WORKSPACE_ID", ""),
    }


CONFIG = _load_config()

_ai_available = True
_ai_last_fail_time = 0
_AI_COOLDOWN_SECONDS = 300
_MAX_REQUEST_BODY_SIZE = 8192


def _check_ai_cooldown() -> bool:
    """检查 AI 服务是否在冷却中
    
    如果 AI 服务在过去 5 分钟内失败过，跳过调用以避免日志刷屏
    """
    global _ai_available, _ai_last_fail_time
    if not _ai_available:
        if time.time() - _ai_last_fail_time < _AI_COOLDOWN_SECONDS:
            return False
        _ai_available = True
    return True


def _calculate_request_body_size(messages: List[Dict[str, str]]) -> int:
    """估算请求体大小(字节)
    
    用于在发送前检查是否超过上限,避免大请求导致超时或被拒绝。
    """
    import json
    payload = {
        "model": CONFIG["model"],
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 800,
    }
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _truncate_messages(messages: List[Dict[str, str]], max_size: int) -> List[Dict[str, str]]:
    """截断消息列表,确保请求体大小不超过上限
    
    策略:从最后一条消息开始截断,保留核心系统提示。
    """
    if _calculate_request_body_size(messages) <= max_size:
        return messages
    
    truncated = []
    for msg in messages:
        if msg["role"] == "system":
            truncated.append(msg)
        else:
            content = msg["content"]
            max_content_len = max_size // 4
            if len(content) > max_content_len:
                truncated.append({
                    "role": msg["role"],
                    "content": content[:max_content_len] + "...(已截断)",
                })
            else:
                truncated.append(msg)
    
    return truncated


def _mark_ai_unavailable():
    """标记 AI 服务不可用，开始冷却"""
    global _ai_available, _ai_last_fail_time
    _ai_available = False
    _ai_last_fail_time = time.time()


# 可重试的异常:网络错误 + 5xx HTTP 错误
# 4xx 错误不重试(参数问题,重试无用)
class _AIRetryableError(Exception):
    """AI 调用可重试错误(网络/5xx)"""
    pass


class _AINonRetryableError(Exception):
    """AI 调用不可重试错误(4xx/参数问题)"""
    pass


async def _chat(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 800,
    timeout: float = None,
) -> str:
    """统一的 chat completions 调用（OpenAI 兼容）

    内置 tenacity 指数退避重试:
    - 最多重试 workbench_config.ai_retry_max 次(默认 3)
    - 初始退避 workbench_config.ai_retry_initial_delay 秒,指数增长
    - 仅对网络错误和 5xx 重试,4xx 立即失败
    
    新增冷却机制:如果 AI 服务在过去 5 分钟内失败过,跳过调用以避免日志刷屏
    
    智能超时策略:
    - 连接超时: 5 秒(网络层快速失败)
    - 读取超时: 根据 max_tokens 动态调整(生成越多越慢)
    """
    if not CONFIG["api_key"]:
        raise _AINonRetryableError("X_TWITTER_AI_API_KEY 未配置")
    
    if not _check_ai_cooldown():
        raise RuntimeError(f"AI 服务暂时不可用,冷却中({_AI_COOLDOWN_SECONDS}秒后重试)")

    truncated_messages = _truncate_messages(messages, _MAX_REQUEST_BODY_SIZE)
    if truncated_messages != messages:
        logger.warning(f"请求体过大,已自动截断(原始 {_calculate_request_body_size(messages)} 字节 -> 截断后 {_calculate_request_body_size(truncated_messages)} 字节)")

    base_timeout = timeout or workbench_config.ai_timeout
    connect_timeout = min(5.0, base_timeout)
    read_timeout = base_timeout + (max_tokens // 100) * 2

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CONFIG['api_key']}",
    }
    if CONFIG["tenant_id"]:
        headers["X-Tenant-ID"] = CONFIG["tenant_id"]

    payload = {
        "model": CONFIG["model"],
        "messages": truncated_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async def _do_request():
        """单次请求逻辑(被 tenacity 包装)"""
        try:
            timeout_cfg = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=30.0)
            async with httpx.AsyncClient(timeout=timeout_cfg) as client:
                r = await client.post(
                    f"{CONFIG['base_url']}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.ConnectTimeout as e:
            raise _AIRetryableError(f"连接超时({connect_timeout}s): {e}") from e
        except httpx.ReadTimeout as e:
            raise _AIRetryableError(f"读取超时({read_timeout}s): {e}") from e
        except (httpx.ConnectError, httpx.WriteTimeout,
                httpx.PoolTimeout) as e:
            raise _AIRetryableError(f"网络错误: {e}") from e
        except httpx.HTTPError as e:
            raise _AIRetryableError(f"HTTP 错误: {e}") from e

        if r.status_code >= 500:
            raise _AIRetryableError(f"AI API {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise _AINonRetryableError(f"AI API 调用失败 {r.status_code}: {r.text[:200]}")

        try:
            data = r.json()
        except ValueError as e:
            raise _AINonRetryableError(f"AI API 响应解析失败: {e}") from e
        
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as e:
            raise _AINonRetryableError(f"AI API 响应格式异常: {e}") from e

    # 不重试时直接执行
    if workbench_config.ai_retry_max <= 0:
        try:
            return await _do_request()
        except _AINonRetryableError as e:
            raise RuntimeError(str(e))
        except _AIRetryableError as e:
            raise RuntimeError(str(e))

    # 带重试的执行
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(workbench_config.ai_retry_max + 1),
            wait=wait_exponential(
                multiplier=workbench_config.ai_retry_initial_delay,
                min=workbench_config.ai_retry_initial_delay,
                max=30.0,
            ),
            retry=retry_if_exception_type(_AIRetryableError),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        ):
            with attempt:
                return await _do_request()
    except _AIRetryableError as e:
        # 重试耗尽 still 失败
        logger.error(f"AI 调用重试 {workbench_config.ai_retry_max} 次后仍失败: {e}")
        _mark_ai_unavailable()
        raise RuntimeError(f"AI 调用失败(已重试 {workbench_config.ai_retry_max} 次): {e}")
    except _AINonRetryableError as e:
        # 4xx 不重试
        raise RuntimeError(str(e))


# ==================== 视频拆解 ====================

VIDEO_BREAKDOWN_SYSTEM = (
    "你是一位资深短视频内容分析师，擅长拆解热门视频的脚本结构和镜头语言。"
    "即使没有视频原片，也要基于推文文本和视频描述进行专业拆解，不能省略任何章节。"
    "输出必须严格按指定章节，使用中文，格式清晰。"
)

VIDEO_BREAKDOWN_PROMPT = """请分析以下X平台热门内容（可能含视频也可能只是图文），进行脚本和分镜拆解。

内容/描述: {content}
视频链接: {video_url}
作者: {username}

注意：如果没拿到视频原片转写文本，请基于已有信息（标题/描述/缩略图等）合理推断并完整输出所有章节，绝对不能省略分镜拆解和关键要点。

请按以下章节输出，每个章节用【】包裹标题，章节内必须填入实质内容：

【脚本分析】
视频或图文的核心脚本内容，包括开场白、主体内容、结尾呼吁。即使没有视频原片，也要根据已有文本推演。

【分镜拆解】
按时间顺序列出至少 3-5 个分镜，每个分镜用编号 1. 2. 3. 开头，描述镜头类型（特写/中景/全景）、画面内容、字幕/旁白。例如：
1. 0:00-0:03 特写镜头，产品Logo居中浮现，背景纯色，旁白："xxx"。
2. 0:04-0:08 中景切换，展示使用场景，字幕："xxx"。
3. 0:09-0:12 全景收尾，画面定格，CTA 文字出现。

【关键要点】
视频传达的核心信息点，必须列出 3-5 条，用编号 1. 2. 3. 开头。

【推荐评论】
针对该内容生成 3 条高互动评论建议，每条评论用 - 开头，要求自然口语化、带表情、有互动感。
"""


async def generate_video_breakdown(post: Dict[str, Any]) -> str:
    """生成视频拆解文本（原始字符串，含所有章节）"""
    prompt = VIDEO_BREAKDOWN_PROMPT.format(
        content=post.get("content", ""),
        video_url=post.get("video_url", ""),
        username=post.get("username", ""),
    )
    return await _chat(
        [
            {"role": "system", "content": VIDEO_BREAKDOWN_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=1200,
    )


def parse_breakdown(text: str) -> Dict[str, Any]:
    """把 AI 输出解析为结构化字段"""
    def _section(name: str) -> str:
        # 抓取【name】... 直到下一个【或文末
        import re
        m = re.search(rf"【{name}】(.*?)(?=【|$)", text, re.S)
        return m.group(1).strip() if m else ""

    def _list_items(s: str) -> List[str]:
        if not s:
            return []
        items = []
        for line in s.split("\n"):
            line = line.strip().lstrip("-").lstrip("*").strip()
            # 去掉编号前缀 "1. " "2) "
            import re
            line = re.sub(r"^\d+[\.\)]\s*", "", line)
            if line:
                items.append(line)
        return items

    script = _section("脚本分析")
    storyboard = _section("分镜拆解")
    key_points = _section("关键要点")
    suggested = _section("推荐评论")

    return {
        "script": script,
        "storyboard": storyboard,
        "storyboard_items": _list_items(storyboard),
        "key_points": _list_items(key_points),
        "suggested_comments": _list_items(suggested),
        "full_text": text,
    }


# ==================== 评论生成 ====================

COMMENT_GEN_SYSTEM = (
    "你是社交媒体互动专家，擅长根据视频内容生成自然、有互动感、带表情的评论。"
    "评论要避免广告感，要像真实用户一样。"
)

COMMENT_GEN_PROMPT = """根据以下视频拆解，生成 {count} 条不同的评论。

视频内容: {content}

视频拆解:
{breakdown}

要求：
1. 每条评论单独一行，不要编号
2. 1-2 句话，自然口语化
3. 适当使用表情
4. 有互动感，引发回复
5. 避免广告感
"""


async def generate_comments(post: Dict[str, Any], breakdown: str, count: int = 3) -> List[str]:
    """根据视频拆解生成多条评论"""
    prompt = COMMENT_GEN_PROMPT.format(
        count=count,
        content=post.get("content", ""),
        breakdown=breakdown[:800],
    )
    text = await _chat(
        [
            {"role": "system", "content": COMMENT_GEN_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
        max_tokens=400,
    )
    return [line.strip() for line in text.split("\n") if line.strip() and not line.strip().startswith("#")]


# ==================== 自动回复 ====================

AUTO_REPLY_SYSTEM = (
    "你是一个活跃的社交媒体用户，擅长用轻松友好的语气回复评论。"
    "回复要求：1)友好积极 2)适当使用表情 3)1-2句话 4)自然口语化 5)避免广告感。"
    "直接给出回复内容，不要解释，不要加引号。"
)

AUTO_REPLY_PROMPT = """请根据以下上下文回复对方的评论。

原推文内容: {post_content}
我发的评论: {my_comment}
对方的回复: {reply_content}
对方用户名: {replier}

请直接给出回复内容（1-2句话，带表情）："""


async def generate_auto_reply(
    *,
    post_content: str,
    my_comment: str,
    reply_content: str,
    replier: str = "",
) -> str:
    """生成针对他人回复的 AI 自动回复"""
    prompt = AUTO_REPLY_PROMPT.format(
        post_content=post_content[:300],
        my_comment=my_comment[:200],
        reply_content=reply_content[:300],
        replier=replier,
    )
    reply = await _chat(
        [
            {"role": "system", "content": AUTO_REPLY_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=100,
    )
    # 去掉首尾引号
    return reply.strip().strip('"').strip("'").strip()


# ==================== 健康检查 ====================

async def health_check() -> Dict[str, Any]:
    """检查 AI Agent API 是否可用"""
    if not CONFIG["api_key"]:
        return {"ok": False, "error": "X_TWITTER_AI_API_KEY 未配置"}
    try:
        reply = await _chat(
            [
                {"role": "system", "content": "你是友好的助手"},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=20,
            timeout=15.0,
        )
        return {
            "ok": True,
            "model": CONFIG["model"],
            "base_url": CONFIG["base_url"],
            "reply": reply[:50],
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "model": CONFIG["model"], "base_url": CONFIG["base_url"]}
