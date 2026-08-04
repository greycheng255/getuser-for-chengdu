# -*- coding: utf-8 -*-
"""
AI 随机差异化话术生成器

阶段二 P1 任务 2.5：补齐 PRD 5.4 话术智能配置。

核心能力：
1. 基于 AI 服务生成多个差异化话术变体
2. 同义词替换、句式重排、零宽字符注入
3. 按平台 / 场景定制生成风格
4. 失败兜底：模板组合 + 同义词替换

设计：
- 调用 ai_service.generate_text（多 AI 平台链）
- 5 分钟冷却期（项目 memory AI 服务失败处理要求）
- 同一批次生成 count 条差异化话术
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============ 场景模板 ============

SCENE_TEMPLATES = {
    "comment_reply": {
        "douyin": ["{prefix}{content}{suffix}", "老铁，{content}{emoji}"],
        "xiaohongshu": ["姐妹，{content}{emoji}", "{prefix}{content}，码住！"],
        "bilibili": ["{prefix}{content}{suffix}", "三连了，{content}"],
        "weibo": ["{content}{emoji}", "{prefix}{content}"],
        "zhihu": ["感谢分享，{content}。", "{prefix}{content}，受益匪浅。"],
        "kuaishou": ["{prefix}{content}{suffix}", "老铁{content}！"],
        "default": ["{content}{emoji}", "{prefix}{content}{suffix}"],
    },
    "direct_message": {
        "default": [
            "你好呀～{content}",
            "亲，{content}，欢迎咨询～",
            "{content}，有什么可以帮您的吗？",
        ],
    },
    "engagement_boost": {
        "default": [
            "{content}，你怎么看？",
            "话说{content}，欢迎留言讨论～",
            "{content}，双击屏幕支持一下～",
        ],
    },
    "conversion": {
        "default": [
            "{content}，点击主页链接获取更多～",
            "想要{content}？欢迎私信～",
            "{content}，限时活动，速来！",
        ],
    },
}

# 同义词替换词库（互动话术专用）
SYNONYMS = {
    "好": ["赞", "棒", "强", "优秀", "厉害"],
    "学到": ["领悟", "掌握", "了解", "明白"],
    "支持": ["顶", "撑", "力挺"],
    "喜欢": ["中意", "青睐", "偏爱"],
    "期待": ["等候", "盼望"],
    "有用": ["实用", "管用", "有帮助"],
    "干货": ["精华", "硬货", "实用内容"],
}

# 零宽字符（用于绕过平台查重）
ZERO_WIDTH_CHARS = ["\u200b", "\u200c", "\u200d", "\ufeff"]

# 前缀/后缀/emoji 词库
PREFIXES = ["", "", "", "哇，", "不错！", "哈哈，", "学到了，", "说实话，"]
SUFFIXES = ["", "", "", "～", "！", "。", "👍", "码住。"]
EMOJIS = ["", "👍", "❤️", "🔥", "✨", "👏", "💯"]


@dataclass
class ScriptVariant:
    """话术变体"""
    content: str
    variant_type: str   # ai / template / synonym
    metadata: Dict[str, Any] = field(default_factory=dict)


class ScriptGenerator:
    """AI 话术生成器"""

    # AI 失败冷却（项目 memory：3 次失败后冷却 5 分钟）
    MAX_FAILURES = 3
    COOLDOWN_SECONDS = 300

    def __init__(self):
        self._failure_count = 0
        self._cooldown_until: Optional[datetime] = None

    async def generate(
        self,
        script_type: str = "comment_reply",
        context: str = "",
        platform: str = "",
        count: int = 5,
        *,
        use_ai: bool = True,
    ) -> List[ScriptVariant]:
        """生成多个差异化话术变体

        Args:
            script_type: 场景类型（comment_reply/direct_message/engagement_boost/conversion）
            context: 上下文（如帖子标题、关键词）
            platform: 平台名（不同平台风格不同）
            count: 生成数量
            use_ai: 是否使用 AI（False 则纯模板生成）

        Returns:
            ScriptVariant 列表
        """
        # 1. 尝试 AI 生成
        if use_ai and self._can_call_ai():
            try:
                ai_variants = await self._generate_with_ai(
                    script_type, context, platform, count
                )
                if ai_variants:
                    self._failure_count = 0  # 重置失败计数
                    return ai_variants[:count]
            except Exception as e:
                logger.warning(f"[ScriptGenerator] AI 生成失败，降级模板: {e}")
                self._record_failure()
        # 2. 兜底：模板 + 同义词替换
        return self._generate_with_template(
            script_type, context, platform, count
        )

    # ============ AI 生成 ============

    async def _generate_with_ai(
        self, script_type: str, context: str, platform: str, count: int
    ) -> List[ScriptVariant]:
        """调用 AI 服务生成话术"""
        from api.services.ai_service import get_ai_service

        svc = get_ai_service()
        platform_hint = f"适合{platform}平台风格" if platform else "通用平台风格"
        prompt = (
            f"请生成 {count} 条互动话术，要求：\n"
            f"1. 场景：{script_type}\n"
            f"2. {platform_hint}\n"
            f"3. 上下文：{context[:200]}\n"
            f"4. 每条话术 10-30 字，自然口语化\n"
            f"5. 互相差异化，避免雷同\n"
            f"6. 不要带序号或引号，每行一条\n\n"
            f"直接输出 {count} 行话术："
        )
        result = await svc.generate_text(prompt)
        if not result:
            return []

        # 解析：按行拆分
        lines = [
            line.strip().strip("\"'`").strip()
            for line in result.strip().split("\n")
            if line.strip()
        ]
        # 过滤太短/太长
        lines = [l for l in lines if 5 <= len(l) <= 100]
        # 注入零宽字符避免查重
        variants = [
            ScriptVariant(
                content=self._inject_zero_width(l),
                variant_type="ai",
                metadata={"platform": platform, "scene": script_type},
            )
            for l in lines
        ]
        return variants

    # ============ 模板生成 ============

    def _generate_with_template(
        self, script_type: str, context: str, platform: str, count: int
    ) -> List[ScriptVariant]:
        """模板兜底生成（同义词替换 + 句式重排 + 零宽字符）"""
        scene_templates = SCENE_TEMPLATES.get(script_type, SCENE_TEMPLATES["comment_reply"])
        platform_templates = scene_templates.get(platform) or scene_templates.get("default")

        # 上下文片段（用于填充模板）
        context_text = context[:30] if context else random.choice([
            "干货满满", "内容很实用", "学到了", "讲得清楚", "这个角度新颖",
        ])

        variants: List[ScriptVariant] = []
        seen = set()
        attempts = 0
        max_attempts = count * 5

        while len(variants) < count and attempts < max_attempts:
            attempts += 1
            template = random.choice(platform_templates)
            prefix = random.choice(PREFIXES)
            suffix = random.choice(SUFFIXES)
            emoji = random.choice(EMOJIS)
            content = template.format(
                prefix=prefix, content=context_text, suffix=suffix, emoji=emoji,
            )
            # 同义词替换
            content = self._apply_synonyms(content)
            # 零宽字符注入
            content = self._inject_zero_width(content)
            # 去重
            if content in seen:
                continue
            seen.add(content)
            variants.append(ScriptVariant(
                content=content, variant_type="template",
                metadata={"platform": platform, "scene": script_type},
            ))
        return variants

    # ============ 工具方法 ============

    def _apply_synonyms(self, text: str) -> str:
        """同义词替换"""
        for word, synonyms in SYNONYMS.items():
            if word in text and random.random() < 0.4:
                text = text.replace(word, random.choice(synonyms), 1)
        return text

    def _inject_zero_width(self, text: str) -> str:
        """零宽字符注入（绕过平台查重）"""
        if not text:
            return text
        # 在 1-2 个随机位置注入零宽字符
        positions = random.sample(
            range(1, len(text)), min(2, max(1, len(text) // 5))
        )
        chars = list(text)
        for pos in sorted(positions, reverse=True):
            chars.insert(pos, random.choice(ZERO_WIDTH_CHARS))
        return "".join(chars)

    # ============ AI 失败处理 ============

    def _can_call_ai(self) -> bool:
        """是否可以调用 AI（冷却期判断）"""
        if self._cooldown_until and datetime.now() < self._cooldown_until:
            return False
        return True

    def _record_failure(self) -> None:
        """记录一次失败"""
        self._failure_count += 1
        if self._failure_count >= self.MAX_FAILURES:
            self._cooldown_until = datetime.now() + timedelta(
                seconds=self.COOLDOWN_SECONDS
            )
            logger.warning(
                f"[ScriptGenerator] AI 连续失败 {self._failure_count} 次，"
                f"冷却 {self.COOLDOWN_SECONDS}s"
            )

    def get_status(self) -> Dict[str, Any]:
        """获取生成器状态"""
        return {
            "failure_count": self._failure_count,
            "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
            "can_call_ai": self._can_call_ai(),
        }


# ============ 单例 ============

_generator: Optional[ScriptGenerator] = None


def get_script_generator() -> ScriptGenerator:
    global _generator
    if _generator is None:
        _generator = ScriptGenerator()
    return _generator
