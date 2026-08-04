# -*- coding: utf-8 -*-
"""
文案仿写服务

复用已有 AIAgentClient._chat() 对口播文案进行语义级改写：
保留爆款逻辑和情绪钩子，但用词、句式、案例全部替换，规避查重。

对标超级IP智能体的"AI文案仿写"功能。
"""
import json
import logging
from typing import Any, Dict, List

from api.services.ai_agent_client import _chat

logger = logging.getLogger("script_rewriter")


async def rewrite_script(
    original_text: str,
    style: str = "",
    industry: str = "",
    tone: str = "",
) -> Dict[str, Any]:
    """对口播文案进行仿写改写

    Args:
        original_text: 原始口播文案
        style: 风格要求（如"激情带货""知识分享""生活vlog"等）
        industry: 行业（如"教育""美妆""餐饮"等）
        tone: 语气（如"专业""亲切""幽默"等）

    Returns:
        {rewritten_text, title_suggestions, tags, hooks}
    """
    if not original_text or not original_text.strip():
        raise ValueError("原始文案不能为空")

    style_hint = style or "自然口语化，适合短视频口播"
    industry_hint = industry or "通用"
    tone_hint = tone or "亲切自然"

    prompt = f"""你是一位顶级短视频文案专家，擅长爆款口播文案仿写。

请对以下口播文案进行深度仿写改写：

【仿写要求】
1. 保留原文的爆款逻辑结构（开头钩子→痛点→解决方案→行动号召）
2. 保留情绪节奏（哪里制造焦虑、哪里给信心、哪里促行动）
3. 但用词、句式、案例、比喻全部替换，确保与原文查重率低于 20%
4. 风格：{style_hint}
5. 行业：{industry_hint}
6. 语气：{tone_hint}
7. 适合 15-60 秒短视频口播，字数控制在 100-300 字

【原文】
{original_text}

【输出格式】
请输出合法 JSON（不要 markdown 代码块），格式如下：
{{
    "rewritten_text": "仿写后的完整口播文案",
    "title_suggestions": ["标题建议1", "标题建议2", "标题建议3"],
    "tags": ["话题标签1", "话题标签2", "话题标签3"],
    "hooks": ["开头钩子1", "开头钩子2"]
}}
"""

    result = await _chat(
        [{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=2000,
    )

    # 解析 JSON 结果
    try:
        # 尝试直接解析
        parsed = json.loads(result)
    except json.JSONDecodeError:
        # 尝试提取 JSON 块
        import re
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
            except json.JSONDecodeError:
                logger.warning(f"[ScriptRewriter] JSON 解析失败，返回原文")
                parsed = {
                    "rewritten_text": result.strip(),
                    "title_suggestions": [],
                    "tags": [],
                    "hooks": [],
                }
        else:
            parsed = {
                "rewritten_text": result.strip(),
                "title_suggestions": [],
                "tags": [],
                "hooks": [],
            }

    logger.info(
        f"[ScriptRewriter] 仿写完成: "
        f"原文{len(original_text)}字 → 改写{len(parsed.get('rewritten_text', ''))}字 "
        f"标题{len(parsed.get('title_suggestions', []))}个 标签{len(parsed.get('tags', []))}个"
    )

    return parsed


async def batch_rewrite(
    scripts: List[str],
    style: str = "",
    industry: str = "",
) -> List[Dict[str, Any]]:
    """批量仿写多篇文案（避免内容同质化）

    Args:
        scripts: 原始文案列表
        style: 风格
        industry: 行业

    Returns:
        仿写结果列表
    """
    results = []
    for i, script in enumerate(scripts):
        try:
            # 每篇给不同的语气变化，避免完全一样
            tone_variations = ["亲切自然", "专业权威", "幽默风趣", "激情澎湃", "温暖治愈"]
            tone = tone_variations[i % len(tone_variations)]
            result = await rewrite_script(script, style=style, industry=industry, tone=tone)
            results.append(result)
        except Exception as e:
            logger.error(f"[ScriptRewriter] 第{i+1}篇仿写失败: {e}")
            results.append({"rewritten_text": "", "error": str(e)})
    return results
