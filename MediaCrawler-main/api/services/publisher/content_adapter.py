# -*- coding: utf-8 -*-
"""
多平台内容适配器

迁移自 GEO-main 的 platform_content_adapter.py，简化为：
1. 不再依赖 LLM 自动改写（MediaCrawler 已有 ai_agent_client，可单独调用）
2. 提供基于规则的硬性适配（字数截断 / hashtag 风格 / 标题长度）
3. 提供风控预检测接口（基于 platform_configs.XHS_CONTENT_RESTRICTIONS）

设计原则：纯函数式，无副作用，便于单测。
"""

import re
from typing import Dict, List, Optional, Tuple

from .platform_configs import (
    PLATFORM_METADATA,
    PlatformMeta,
    XHS_CONTENT_RESTRICTIONS,
    get_platform_meta,
)


def adapt_title(title: str, platform: str) -> str:
    """按平台规则适配标题

    - 小红书：截断到 20 字，去除绝对化用语
    - 抖音：截断到 55 字
    - 微博：截断到 140 字
    - 其他：截断到平台 max_title_length
    """
    meta = get_platform_meta(platform)
    if not meta:
        return title

    adapted = title.strip()

    # 风控词替换（小红书专用）
    if platform == "xiaohongshu":
        for word in XHS_CONTENT_RESTRICTIONS["absolute_words"]:
            adapted = adapted.replace(word, "")
        for word in XHS_CONTENT_RESTRICTIONS["exaggeration_words"]:
            adapted = adapted.replace(word, "")

    # 字数截断
    if len(adapted) > meta.max_title_length:
        adapted = adapted[: meta.max_title_length].rstrip()

    return adapted.strip()


def adapt_content(content: str, platform: str) -> str:
    """按平台规则适配正文

    - 字数截断
    - hashtag 风格统一（小红书/微博用 #xxx#，抖音/快手用 #xxx）
    - 去除 Markdown 语法（小红书/抖音不支持）
    """
    meta = get_platform_meta(platform)
    if not meta:
        return content

    adapted = content.strip()

    # 小红书 / 抖音不支持 Markdown
    if platform in ("xiaohongshu", "douyin", "kuaishou", "weibo"):
        # 去除 markdown 标题
        adapted = re.sub(r"^#{1,6}\s+", "", adapted, flags=re.MULTILINE)
        # 去除粗体/斜体标记
        adapted = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", adapted)
        # 去除链接
        adapted = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", adapted)
        # 去除代码块
        adapted = re.sub(r"```[\s\S]*?```", "", adapted)
        adapted = re.sub(r"`([^`]+)`", r"\1", adapted)

    # hashtag 风格适配
    if platform in ("xiaohongshu", "weibo"):
        # #话题# 风格（双井号闭合）
        adapted = re.sub(r"#([^#\s]+)\s", r"#\1# ", adapted)
    elif platform in ("douyin", "kuaishou", "bilibili"):
        # #话题 风格（单井号）
        adapted = re.sub(r"#([^#\s]+)#", r"#\1 ", adapted)

    # 字数截断
    if len(adapted) > meta.max_content_length:
        adapted = adapted[: meta.max_content_length].rstrip() + "..."

    return adapted.strip()


def extract_hashtags(content: str, platform: str) -> List[str]:
    """从内容中提取 hashtag"""
    if platform in ("xiaohongshu", "weibo"):
        # #话题# 风格
        return re.findall(r"#([^#\s]+)#", content)
    # #话题 风格
    return re.findall(r"#([^#\s]+)", content)


def moderate_content(content: str, platform: str) -> Tuple[bool, List[str]]:
    """内容风控预检测

    Returns:
        (passed, hits): 是否通过 / 命中的敏感词列表
    """
    hits = []

    if platform == "xiaohongshu":
        # 小红书有完整词库
        for category, words in XHS_CONTENT_RESTRICTIONS.items():
            if not isinstance(words, list):
                continue
            for word in words:
                if word in content:
                    hits.append(f"[{category}] {word}")

        # 内容长度检查
        if len(content.strip()) < XHS_CONTENT_RESTRICTIONS["min_content_length"]:
            hits.append(
                f"[长度不足] 内容少于 {XHS_CONTENT_RESTRICTIONS['min_content_length']} 字"
            )

        # hashtag 数量检查
        hashtags = extract_hashtags(content, platform)
        if len(hashtags) > XHS_CONTENT_RESTRICTIONS["max_hashtags"]:
            hits.append(
                f"[hashtag过多] {len(hashtags)} > {XHS_CONTENT_RESTRICTIONS['max_hashtags']}"
            )
    else:
        # 其他平台使用通用风控（小红书词库的子集）
        universal_words = (
            XHS_CONTENT_RESTRICTIONS["absolute_words"]
            + XHS_CONTENT_RESTRICTIONS["exaggeration_words"]
            + XHS_CONTENT_RESTRICTIONS["inducing_words"]
            + XHS_CONTENT_RESTRICTIONS["medical_words"]
            + XHS_CONTENT_RESTRICTIONS["illegal_marketing"]
            + XHS_CONTENT_RESTRICTIONS["sensitive_topics"]
            + XHS_CONTENT_RESTRICTIONS["sensitive_political"]
            # 常见欺诈/灰产词（补丁：原词库遗漏的高频违规词）
            + ["刷单", "加微信", "加微", "免费领取", "色情视频", "兼职刷",
               "传销", "引流", "黑产", "号商", "卖号", "租号"]
        )
        for word in universal_words:
            if word in content:
                hits.append(f"[通用敏感词] {word}")

    return (len(hits) == 0, hits)


def adapt_for_platform(
    title: str,
    content: str,
    platform: str,
    *,
    enforce_moderation: bool = True,
) -> Dict:
    """一站式适配：标题 + 正文 + 风控检测

    Returns:
        {
            "title": str,           # 适配后的标题
            "content": str,         # 适配后的正文
            "platform": str,
            "moderation_passed": bool,
            "moderation_hits": List[str],
            "warnings": List[str],  # 非阻塞性警告
        }
    """
    warnings = []

    adapted_title = adapt_title(title, platform)
    adapted_content = adapt_content(content, platform)

    # 风控检测
    passed, hits = moderate_content(adapted_content, platform)
    if not passed and enforce_moderation:
        warnings.append(f"内容风控未通过（{len(hits)} 项命中）")
    elif not passed:
        warnings.append(f"内容风控警告（{len(hits)} 项命中）")

    meta = get_platform_meta(platform)
    if meta:
        if len(adapted_title) > meta.max_title_length:
            warnings.append(f"标题超出长度限制（{len(adapted_title)} > {meta.max_title_length}）")
        if len(adapted_content) > meta.max_content_length:
            warnings.append(
                f"正文超出长度限制（{len(adapted_content)} > {meta.max_content_length}）"
            )

    return {
        "title": adapted_title,
        "content": adapted_content,
        "platform": platform,
        "moderation_passed": passed,
        "moderation_hits": hits,
        "warnings": warnings,
    }


def generate_multi_platform_versions(
    title: str,
    content: str,
    platforms: List[str],
    *,
    enforce_moderation: bool = True,
) -> Dict[str, Dict]:
    """为多个平台生成差异化版本

    Returns:
        {platform: adapt_for_platform(...)}
    """
    return {
        p: adapt_for_platform(title, content, p, enforce_moderation=enforce_moderation)
        for p in platforms
        if get_platform_meta(p)
    }
