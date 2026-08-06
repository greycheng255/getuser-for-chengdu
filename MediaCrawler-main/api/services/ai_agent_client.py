# -*- coding: utf-8 -*-
"""
X Twitter 工作台 AI Agent 客户端

通过临时接入的 AI6700 Chat Completions API 完成：
1. 视频拆解（脚本/分镜/关键要点/推荐评论）
2. 评论生成（基于拆解结果生成可发送的评论）
3. 自动回复（针对他人回复，生成自然、带表情的回复）

可靠性:
- 使用 tenacity 实现指数退避重试(网络抖动/AI 服务短暂不可用时自动恢复)
- 5xx/超时/网络错误重试,4xx 不重试(参数问题重试无用)
- 重试次数和初始退避由 workbench_config 控制
"""
import logging
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
from api.services.ai6700_client import (
    AI6700BalanceError,
    ensure_ai6700_balance,
)
from config.onellm_config import load_onellm_config


logger = logging.getLogger("ai_agent_client")


def _load_config() -> Dict[str, str]:
    """从统一的 ONELLM_* 环境变量加载临时 AI6700 配置。"""
    settings = load_onellm_config()
    return {
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        "model": settings.chat_model,
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


def is_ai_in_cooldown() -> bool:
    """公开接口：检查 AI 服务是否处于冷却期（供调用方在调用前预检）

    用法：
        from api.services.ai_agent_client import is_ai_in_cooldown
        if is_ai_in_cooldown():
            return None  # 静默跳过，避免日志刷屏
        result = await client.generate_text(prompt)

    被 hotpoint_classifier/prompt_library/dm_replier/copy_inserter/
    interaction_monitor/prompt_storyboard_pipeline 等可选 AI 兜底场景使用。
    """
    return not _check_ai_cooldown()


def get_ai_cooldown_remaining() -> int:
    """公开接口：返回冷却剩余秒数（0 表示可用）"""
    if _ai_available:
        return 0
    remaining = _AI_COOLDOWN_SECONDS - int(time.time() - _ai_last_fail_time)
    return max(0, remaining)


# 预期内的 AI 错误关键词（冷却/余额/内容审核/限流），调用方应降级为 DEBUG 而非 WARNING
_EXPECTED_AI_ERROR_KEYWORDS = (
    "冷却中", "billing_error", " 402", "content_filter", "content filter",
    "余额不足", "channel_switch_error",
)


def is_ai_expected_error(e: Exception) -> bool:
    """公开接口：判断 AI 异常是否属于"预期内"错误（冷却/余额/内容审核/限流）

    调用方应在 except 中使用本函数决定日志级别：
        if is_ai_expected_error(e):
            logger.debug(...)   # 预期内，静默
        else:
            logger.warning(...) # 非预期，告警

    被 hotpoint_classifier/prompt_library/dm_replier/copy_inserter/
    interaction_monitor/prompt_storyboard_pipeline 共享使用。
    """
    err_msg = str(e)
    return any(kw in err_msg for kw in _EXPECTED_AI_ERROR_KEYWORDS) or is_ai_in_cooldown()


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
        raise _AINonRetryableError("ONELLM_API_KEY 未配置")
    
    if not _check_ai_cooldown():
        raise RuntimeError(f"AI 服务暂时不可用,冷却中({_AI_COOLDOWN_SECONDS}秒后重试)")

    truncated_messages = _truncate_messages(messages, _MAX_REQUEST_BODY_SIZE)
    if truncated_messages != messages:
        logger.warning(f"请求体过大,已自动截断(原始 {_calculate_request_body_size(messages)} 字节 -> 截断后 {_calculate_request_body_size(truncated_messages)} 字节)")

    base_timeout = timeout or workbench_config.ai_timeout
    connect_timeout = min(5.0, base_timeout)
    # 读取超时 = 基础超时 + token 生成时间估算，但封顶 60s 避免长时间挂起
    # 原公式 base + (max_tokens//100)*2 对 max_tokens=2000 会算出 100s，过长
    read_timeout = min(base_timeout + (max_tokens // 100) * 2, 60.0)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CONFIG['api_key']}",
    }
    payload = {
        "model": CONFIG["model"],
        "messages": truncated_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async def _do_request():
        """单次请求逻辑(被 tenacity 包装)"""
        try:
            await ensure_ai6700_balance()
        except AI6700BalanceError as e:
            # 余额不足(402)/未授权(401)等需要人工介入的错误，立即触发冷却
            # 避免后续调用继续刷余额接口产生大量 WARNING 日志
            if e.status_code in (401, 402) or not e.retryable:
                _mark_ai_unavailable()
                logger.warning(
                    f"AI 余额/鉴权失败(status={e.status_code})，进入 {_AI_COOLDOWN_SECONDS}s 冷却: {e}"
                )
            error_type = _AIRetryableError if e.retryable else _AINonRetryableError
            raise error_type(str(e)) from e
        try:
            timeout_cfg = httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=30.0,
                pool=connect_timeout,
            )
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
            err_body = r.text[:200]
            # 5xx 中如果包含余额不足/channel_switch_error/billing_error，
            # 实际是 OneLLM 代理把 402 余额错误包装成 502，不可重试，立即触发冷却
            if any(kw in err_body for kw in ("余额不足", "billing_error", "channel_switch_error")):
                _mark_ai_unavailable()
                logger.warning(
                    f"AI API 返回 {r.status_code}(余额不足)，进入 "
                    f"{_AI_COOLDOWN_SECONDS}s 冷却: {err_body}"
                )
                raise _AINonRetryableError(f"AI API 余额不足 {r.status_code}: {err_body}")
            raise _AIRetryableError(f"AI API {r.status_code}: {err_body}")
        if r.status_code >= 400:
            err_body = r.text[:200]
            # 402 billing_error / 401 / 429 限流：需要人工介入或冷却，
            # 立即触发全局冷却避免后续调用继续刷接口产生大量 WARNING
            if r.status_code in (401, 402, 429) or any(
                kw in err_body for kw in ("billing_error", "余额不足", "channel_switch_error")
            ):
                _mark_ai_unavailable()
                logger.warning(
                    f"AI API 返回 {r.status_code}(余额/鉴权/限流)，进入 "
                    f"{_AI_COOLDOWN_SECONDS}s 冷却: {err_body}"
                )
            raise _AINonRetryableError(f"AI API 调用失败 {r.status_code}: {err_body}")

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
    "当提供视频链接时，要分析视频内容本身（画面、人物、场景、字幕、旁白等）。"
    "当没有视频链接时，基于推文文本和视频描述进行专业拆解。"
    "输出必须严格按指定章节，使用中文，格式清晰。"
)

VIDEO_BREAKDOWN_PROMPT = """请分析以下X平台热门内容，进行脚本和分镜拆解。

内容/描述: {content}
视频链接: {video_url}
作者: {username}

注意：
1. 如果提供了视频关键帧，请基于视频帧内容进行逐帧解析（分析画面中的人物、场景、字幕、动作、表情等）
2. 如果没有视频帧但有视频链接，基于视频内容描述进行深度解析
3. 如果只有文本内容，基于已有信息（标题/描述等）合理推断并完整输出所有章节
4. 绝对不能省略分镜拆解和关键要点
5. 分镜拆解要尽量详细，基于实际画面内容，不要凭空想象

请按以下章节输出，每个章节用【】包裹标题，章节内必须填入实质内容：

【脚本分析】
视频或图文的核心脚本内容，包括开场白、主体内容、结尾呼吁。如果有视频帧，请分析视频中的实际画面内容。

【分镜拆解】
按时间顺序列出至少 5-8 个分镜，每个分镜用编号 1. 2. 3. 开头，描述：
- 时间范围（如 0:00-0:03）
- 镜头类型（特写/中景/全景/分屏/快切）
- 画面内容（详细描述画面中的人物、动作、场景、文字、颜色等）
- 字幕/旁白（视频中的文字或配音内容）

例如：
1. 0:00-0:03 特写镜头，画面聚焦一名西装男性的面部表情，表情严肃略带震惊，背景模糊处理。字幕："So this is why Elon wanted to rush the IPO..."
2. 0:04-0:07 中景切换，展示中国产品发布现场，台上有人在演示，台下观众在拍照。字幕："China just did it cheaper..."

【关键要点】
视频传达的核心信息点，必须列出 3-5 条，用编号 1. 2. 3. 开头。

【推荐评论】
针对该内容生成 3 条高互动评论建议，每条评论用 - 开头，要求自然口语化、带表情、有互动感。
"""


async def generate_video_breakdown(post: Dict[str, Any]) -> str:
    """生成视频拆解文本（原始字符串，含所有章节）"""
    video_url = post.get("video_url", "")
    frame_urls = []
    
    if video_url:
        try:
            from api.services.explainer_video_client import extract_video_frames
            frame_urls = await extract_video_frames(video_url, max_frames=5)
        except Exception as e:
            import logging
            logger = logging.getLogger("ai_agent_client")
            logger.warning(f"Failed to extract video frames for breakdown: {e}")
    
    prompt = VIDEO_BREAKDOWN_PROMPT.format(
        content=post.get("content", ""),
        video_url=video_url,
        username=post.get("username", ""),
    )
    
    if frame_urls:
        frame_info = "\n\n视频关键帧（基于这些帧进行逐帧解析）：\n"
        for i, frame_url in enumerate(frame_urls, 1):
            frame_info += f"帧{i}: {frame_url}\n"
        prompt += frame_info
    
    return await _chat(
        [
            {"role": "system", "content": VIDEO_BREAKDOWN_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=2000,
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


# ==================== X 发布文案生成 ====================

X_POST_GEN_SYSTEM = (
    "你是社交媒体内容创作专家，擅长根据视频内容生成吸引人的 X（Twitter）发布文案。"
    "文案要简短有力，使用热门标签，引发互动和转发。"
)

X_POST_GEN_PROMPT = """根据以下视频拆解，生成 {count} 条适合在 X（Twitter）上发布的文案。

视频内容: {content}

视频拆解:
{breakdown}

要求：
1. 每条文案单独一行，不要编号
2. 不超过 280 字符
3. 使用相关的热门话题标签（#标签）
4. 语气自信、有趣、有争议性或有信息量
5. 适合引发讨论和转发
6. 可以使用表情增加活力
7. 结尾可以加相关话题标签
"""


async def generate_x_post_content(post: Dict[str, Any], breakdown: str, count: int = 3) -> List[str]:
    """根据视频拆解生成多条 X 发布文案"""
    prompt = X_POST_GEN_PROMPT.format(
        count=count,
        content=post.get("content", "")[:500],
        breakdown=breakdown[:2000],
    )
    
    response = await _chat([
        {"role": "system", "content": X_POST_GEN_SYSTEM},
        {"role": "user", "content": prompt},
    ])
    lines = response.strip().split("\n")
    results = []
    for line in lines:
        line = line.strip().lstrip("-").lstrip("*").strip()
        import re
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        if line and len(line) <= 280:
            results.append(line)
    return results[:count]


# ==================== 多平台发布文案生成（platform-agnostic） ====================

# 平台调性配置（控制文案风格/长度/标签风格）
_PLATFORM_POST_STYLE: Dict[str, Dict[str, Any]] = {
    "x": {
        "name": "X (Twitter)",
        "max_content": 280,
        "style": "简短有力、话题性强、引发讨论和转发",
        "hashtag_style": "1-2 个 # 标签，放在文末",
        "emoji": "适度使用（1-2 个）",
    },
    "douyin": {
        "name": "抖音",
        "max_content": 2000,
        "style": "短视频文案风格，前 3 句话必须抓眼球，可加悬念",
        "hashtag_style": "3-5 个 # 话题标签，分散在文中",
        "emoji": "多用表情，活泼口语化",
    },
    "xiaohongshu": {
        "name": "小红书",
        "max_content": 1000,
        "style": "种草笔记风格，第一人称体验感，图文并茂感",
        "hashtag_style": "5-8 个 # 标签（如 #好物推荐 #生活日常）",
        "emoji": "大量表情，温柔治愈风格",
    },
    "bilibili": {
        "name": "哔哩哔哩",
        "max_content": 2000,
        "style": "二次元/年轻化表达，可加玩梗、二次元梗",
        "hashtag_style": "3-5 个 # 话题标签",
        "emoji": "适度使用，可加颜文字",
    },
    "weibo": {
        "name": "微博",
        "max_content": 2000,
        "style": "热点资讯风格，可加观点评论，引发转发讨论",
        "hashtag_style": "2-4 个 # 话题标签",
        "emoji": "适度使用",
    },
    "zhihu": {
        "name": "知乎",
        "max_content": 10000,
        "style": "深度思考、专业分析，可加引用、数据论证",
        "hashtag_style": "无标签或 1-2 个 # 话题",
        "emoji": "不用或少用表情",
    },
}

_PLATFORM_POST_SYSTEM = (
    "你是社交媒体内容创作专家，擅长根据视频拆解内容生成符合目标平台调性的发布文案。"
    "文案要自然、有互动感，避免广告感。"
)

_PLATFORM_POST_PROMPT_TEMPLATE = """根据以下视频拆解，生成 {count} 条适合在 {platform_name} 上发布的文案。

视频内容: {content}

视频拆解:
{breakdown}

平台调性要求:
- 最大长度: {max_content} 字符
- 风格: {style}
- 标签: {hashtag_style}
- 表情: {emoji}

通用要求：
1. 每条文案单独一行，不要编号
2. 不超过 {max_content} 字符
3. 语气自然、有互动感
4. 适合引发讨论和互动
5. 避免广告感
"""


async def generate_platform_post_content(
    post: Dict[str, Any],
    breakdown: str,
    platform: str,
    count: int = 3,
) -> List[str]:
    """根据视频拆解生成多条适合指定平台的发布文案

    Args:
        post: 源热点数据 {content, video_url, ...}
        breakdown: 视频拆解文本
        platform: 目标平台（x/douyin/xiaohongshu/bilibili/weibo/zhihu）
        count: 生成条数

    Returns:
        文案列表（每条已按平台 max_content 截断）
    """
    # X 平台直接复用旧函数（保持行为一致）
    if platform == "x":
        return await generate_x_post_content(post, breakdown, count)

    style = _PLATFORM_POST_STYLE.get(platform)
    if not style:
        # 未知平台走通用 prompt
        style = {
            "name": platform,
            "max_content": 2000,
            "style": "自然、有互动感",
            "hashtag_style": "适度使用 # 标签",
            "emoji": "适度使用",
        }

    prompt = _PLATFORM_POST_PROMPT_TEMPLATE.format(
        count=count,
        platform_name=style["name"],
        content=post.get("content", "")[:500],
        breakdown=breakdown[:2000],
        max_content=style["max_content"],
        style=style["style"],
        hashtag_style=style["hashtag_style"],
        emoji=style["emoji"],
    )

    response = await _chat(
        [
            {"role": "system", "content": _PLATFORM_POST_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=2000,
    )

    lines = response.strip().split("\n")
    results: List[str] = []
    for line in lines:
        line = line.strip().lstrip("-").lstrip("*").strip()
        # 去掉编号前缀 "1. " "2) "
        import re
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        if line:
            # 按平台 max_content 截断
            results.append(line[: style["max_content"]])
    return results[:count]


# ==================== 评论生成 ====================

COMMENT_GEN_SYSTEM = (
    "你是社交媒体互动专家，擅长根据视频内容生成自然、有互动感、带表情的评论。"
    "评论要避免广告感，要像真实用户一样。"
)

COMMENT_GEN_PROMPT = """根据以下视频拆解，生成 {count} 条不同的评论。

当前平台: {platform}
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
        platform=post.get("platform", "社交媒体"),
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
    results: List[str] = []
    for line in text.split("\n"):
        line = line.strip().lstrip("-").lstrip("*").strip()
        import re
        line = re.sub(r"^\d+[\.、\)]\s*", "", line)
        if line and not line.startswith("#"):
            results.append(line[:280])
    return results[:count]


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
    """检查 AI6700 Chat Completions API 是否可用。"""
    if not CONFIG["api_key"]:
        return {"ok": False, "error": "ONELLM_API_KEY 未配置"}
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


# ==================== AIAgentClient 单例封装 ====================
#
# 历史：项目多处（hotpoint_classifier/prompt_storyboard_pipeline/prompt_library/
# dm_replier/copy_inserter/interaction_monitor）按 OOP 风格调用：
#     from api.services.ai_agent_client import get_ai_agent_client
#     client = get_ai_agent_client()
#     result = await client.generate_text(prompt)
#     raw_text = await client.breakdown_video(hotspot_video_url)
#
# 但 ai_agent_client.py 本身只提供了独立 async 函数（generate_video_breakdown/_chat/...），
# 没有 AIAgentClient 类也没有 get_ai_agent_client 工厂，导致运行时 ImportError。
#
# 修复：提供 AIAgentClient 类，把现有独立 async 函数包装为实例方法，保持向后兼容。


class AIAgentClient:
    """AI Agent 客户端单例 - 封装 ai_agent_client.py 的独立 async 函数

    方法:
    - generate_text(prompt, system_prompt="", temperature=0.7, max_tokens=2000) -> str
        通用文本生成（被 dm_replier/copy_inserter/prompt_library/hotpoint_classifier 使用）
    - breakdown_video(video_url_or_post) -> str
        视频拆解（被 prompt_storyboard_pipeline 使用），返回带【脚本分析】等章节的文本
    """

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        timeout: float = 60.0,
    ) -> str:
        """通用文本生成接口

        Args:
            prompt: 用户输入提示词
            system_prompt: 系统提示词（可选，默认空）
            temperature: 温度参数，默认 0.7
            max_tokens: 最大生成 token 数
            timeout: 请求超时（秒）

        Returns:
            AI 生成的文本内容
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return await _chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    async def breakdown_video(self, video_url_or_post: Any) -> str:
        """视频拆解 - 包装 generate_video_breakdown

        Args:
            video_url_or_post: 可以是视频 URL 字符串，也可以是 post dict（推荐）

        Returns:
            拆解文本，包含【脚本分析】【分镜拆解】【关键要点】【推荐评论】4 个章节
        """
        # 兼容字符串 URL（自动构造 post dict）
        if isinstance(video_url_or_post, str):
            post = {
                "post_id": "",
                "post_url": "",
                "content": "",
                "video_url": video_url_or_post,
                "username": "",
            }
        elif isinstance(video_url_or_post, dict):
            post = video_url_or_post
        else:
            raise ValueError(f"breakdown_video 不支持的参数类型: {type(video_url_or_post)}")

        return await generate_video_breakdown(post)

    async def generate_comments(
        self,
        post: Dict[str, Any],
        breakdown: str = "",
        count: int = 3,
    ) -> List[str]:
        """生成评论 - 包装 generate_comments 独立函数"""
        if breakdown:
            return await generate_comments(post, breakdown, count)
        # 无 breakdown 时先用 generate_video_breakdown 生成
        if not breakdown:
            breakdown = await generate_video_breakdown(post)
        return await generate_comments(post, breakdown, count)

    async def generate_auto_reply(
        self,
        comment_content: str,
        post_content: str = "",
        language: str = "zh",
    ) -> str:
        """自动回复 - 包装 generate_auto_reply 独立函数"""
        return await generate_auto_reply(comment_content, post_content, language)

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return await health_check()


# ============ 单例工厂 ============

_ai_agent_client_instance: Optional[AIAgentClient] = None


def get_ai_agent_client() -> AIAgentClient:
    """获取 AIAgentClient 单例

    全局共享一个实例（无状态，线程安全）。
    被 hotpoint_classifier/prompt_storyboard_pipeline/prompt_library/
    dm_replier/copy_inserter/interaction_monitor 等模块使用。
    """
    global _ai_agent_client_instance
    if _ai_agent_client_instance is None:
        _ai_agent_client_instance = AIAgentClient()
    return _ai_agent_client_instance
