# -*- coding: utf-8 -*-
"""
视频拆解服务

输入视频链接 → 调用 script_extractor 提取字幕/元数据 → 用 qwen-plus AI 生成结构化拆解报告

输出结构（对标超级IP智能体的"AI拆解"功能）：
- script_analysis: 脚本分析（内容类型、核心信息、结构推断）
- storyboard: 分镜拆解（时间段、画面内容、字幕/旁白、作用）
- key_points: 关键要点列表
- recommended_comments: 推荐评论列表
"""
import json
import logging
import os
from typing import Any, Dict

import httpx

logger = logging.getLogger("video_analyzer")

# AI 模型配置（OpenAI 兼容模式调用 DashScope qwen-plus）
AI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
AI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")
AI_MODEL = os.getenv("OPENAI_MODEL", "qwen-plus")


async def _extract_video_info(video_url: str) -> Dict[str, Any]:
    """调用 script_extractor 提取视频字幕和元数据

    script_extractor 已有完善的降级逻辑：
    解析服务 → API文本提取 → 视频下载+Whisper
    """
    from api.services.ai.script_extractor import extract_script

    result = await extract_script(video_url, platform="")

    # 构建字幕时间轴文本
    segments = result.get("segments", [])
    if segments:
        subtitle_text = "\n".join(
            f"[{s.get('start', 0):.1f}s-{s.get('end', 0):.1f}s] {s.get('text', '')}"
            for s in segments
        )
    else:
        subtitle_text = result.get("raw_text", "")

    return {
        "title": result.get("source_title", ""),
        "author": result.get("author", ""),
        "duration": result.get("duration", 0),
        "subtitle_text": subtitle_text,
        "summary_text": result.get("summary_text", ""),
        "thumbnail": result.get("thumbnail", ""),
        "video_url": result.get("parsed_video_url", ""),
        "extraction_method": result.get("extraction_method", ""),
    }


def _build_analysis_prompt(video_info: Dict[str, Any]) -> str:
    """构建 AI 分析的 prompt"""
    title = video_info.get("title", "")
    author = video_info.get("author", "")
    duration = video_info.get("duration", 0)
    subtitle_text = video_info.get("subtitle_text", "")
    summary_text = video_info.get("summary_text", "")

    duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "未知"

    return f"""你是一位专业的短视频内容分析师，请对以下视频进行深度拆解分析。

## 视频信息
- 标题: {title}
- 作者: {author}
- 时长: {duration_str}
- 字幕/文案:
{subtitle_text[:3000] if subtitle_text else "(无字幕)"}

- 摘要: {summary_text[:500] if summary_text else "(无)"}

## 分析要求
请严格按照以下 JSON 格式输出分析结果（不要输出其他内容，直接输出 JSON）:

```json
{{
  "script_analysis": {{
    "content_type": "内容类型（如：体育赛事/知识科普/剧情演绎/产品测评等）",
    "core_info": "核心信息一句话概括",
    "structure": "整体结构分析（开场如何抓人、主体如何展开、结尾如何收束），100-200字"
  }},
  "storyboard": [
    {{
      "time_range": "0:00-0:03",
      "shot_type": "镜头类型（特写/中景/全景/图文等）",
      "visual": "画面内容描述（基于字幕和标题推断，20-50字）",
      "narration": "该段对应的字幕/旁白内容",
      "purpose": "该镜头的作用（10-20字）"
    }}
  ],
  "key_points": [
    "关键要点1（15-30字）",
    "关键要点2",
    "关键要点3",
    "关键要点4",
    "关键要点5"
  ],
  "recommended_comments": [
    "推荐评论1（引导互动，15-30字）",
    "推荐评论2",
    "推荐评论3"
  ]
}}
```

## 注意事项
1. 分镜拆解按视频时长均匀切分为 5-8 个段落，每个段落 3-8 秒
2. 画面内容是基于字幕和标题的合理推断，用"可能"等措辞
3. 关键要点 3-5 条，每条聚焦一个核心信息
4. 推荐评论 3 条，要能引导用户互动讨论
5. 只输出 JSON，不要输出其他解释文字
"""


async def _call_ai_model(prompt: str) -> str:
    """调用 qwen-plus 模型（OpenAI 兼容模式）"""
    if not AI_API_KEY:
        raise RuntimeError("AI API Key 未配置（OPENAI_API_KEY）")

    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": "你是一位专业的短视频内容分析师，擅长视频拆解和内容分析。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4000,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{AI_BASE_URL}/chat/completions",
            headers=headers,
            json=body,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"AI 模型调用失败: HTTP {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("AI 模型未返回内容")

    return content


def _parse_ai_response(raw_text: str) -> Dict[str, Any]:
    """解析 AI 返回的 JSON（兼容 markdown code block 包裹）"""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    return json.loads(text)


async def analyze_video(video_url: str) -> Dict[str, Any]:
    """视频拆解主函数

    Args:
        video_url: 视频链接（抖音/小红书/B站）

    Returns:
        {
            script_analysis: { content_type, core_info, structure },
            storyboard: [{ time_range, shot_type, visual, narration, purpose }],
            key_points: [str],
            recommended_comments: [str],
            video_info: { title, author, duration, ... }
        }
    """
    logger.info(f"[VideoAnalyzer] 开始拆解视频: {video_url}")

    # 1. 调用 script_extractor 提取字幕和元数据（有降级逻辑保证成功率）
    video_info = await _extract_video_info(video_url)
    logger.info(
        f"[VideoAnalyzer] 文案提取完成: title={video_info.get('title', '')[:30]} "
        f"duration={video_info.get('duration', 0)}s "
        f"subtitles={len(video_info.get('subtitle_text', ''))}字 "
        f"method={video_info.get('extraction_method', '')}"
    )

    # 2. 构建 AI 分析 prompt
    prompt = _build_analysis_prompt(video_info)

    # 3. 调用 AI 模型分析
    raw_response = await _call_ai_model(prompt)
    logger.info(f"[VideoAnalyzer] AI 分析完成, 响应长度={len(raw_response)}")

    # 4. 解析 AI 返回的 JSON
    analysis = _parse_ai_response(raw_response)

    # 5. 合并结果
    result = {
        **analysis,
        "video_info": {
            "title": video_info.get("title", ""),
            "author": video_info.get("author", ""),
            "duration": video_info.get("duration", 0),
            "platform": video_info.get("platform", ""),
            "thumbnail": video_info.get("thumbnail", ""),
            "video_url": video_info.get("video_url", ""),
            "extraction_method": video_info.get("extraction_method", ""),
        },
    }

    logger.info(
        f"[VideoAnalyzer] 拆解完成: "
        f"storyboard={len(result.get('storyboard', []))}段 "
        f"key_points={len(result.get('key_points', []))}条 "
        f"comments={len(result.get('recommended_comments', []))}条"
    )
    return result
