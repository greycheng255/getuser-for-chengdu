# -*- coding: utf-8 -*-
"""
涉政内容检测器

阶段二 P1 任务 2.3：补齐 PRD 5.6 涉政识别。

三层检测策略：
- L1：涉政敏感词库（内置 + 自定义）+ 正则匹配 → 命中即拦截
- L2：AI 服务语义级涉政识别（兜底语义场景）→ 中危进入人工复核
- L3：高危内容直接拦截，中危进入人工复核

集成到 ModerationService.moderate() 流程。
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PoliticalRiskLevel(str, Enum):
    """涉政风险等级"""
    SAFE = "safe"            # 无风险
    LOW = "low"              # 低风险（敏感词边缘，提示关注）
    MEDIUM = "medium"        # 中风险（疑似涉政，进入人工复核）
    HIGH = "high"            # 高风险（明确涉政，直接拦截）


@dataclass
class PoliticalDetectResult:
    """涉政检测结果"""
    risk_level: str = PoliticalRiskLevel.SAFE.value
    matched_keywords: List[str] = field(default_factory=list)
    ai_flagged: bool = False
    ai_reason: str = ""
    suggestion: str = ""     # 处理建议
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        """是否拦截（高危）"""
        return self.risk_level == PoliticalRiskLevel.HIGH.value

    @property
    def needs_review(self) -> bool:
        """是否需要人工复核（中危）"""
        return self.risk_level == PoliticalRiskLevel.MEDIUM.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "matched_keywords": self.matched_keywords,
            "ai_flagged": self.ai_flagged,
            "ai_reason": self.ai_reason,
            "suggestion": self.suggestion,
            "details": self.details,
        }


# ============ 内置涉政敏感词库（最小集，生产环境应扩展并外部化） ============

# 高危：明确涉政人物/事件/口号（L1 直接拦截）
HIGH_RISK_KEYWORDS = [
    # 占位集合；实际部署应通过外部词库文件加载
    "天安门事件", "六四", "法轮功", "藏独", "疆独", "台独",
    "颠覆国家政权", "推翻共产党",
]

# 中危：涉政人物姓名（L1 命中后进入人工复核）
MEDIUM_RISK_KEYWORDS = [
    "习近平", "毛泽东", "邓小平", "江泽民", "胡锦涛",
    "李克强", "李强", "温家宝", "朱镕基",
]

# 敏感正则模式（涉政数字组合、敏感日期等）
SENSITIVE_PATTERNS = [
    re.compile(r"19[89]\d\s*年\s*6\s*月\s*4\s*日"),
    re.compile(r"6\s*[\.·]\s*4"),
    re.compile(r"坦克\s*人"),
]


class PoliticalDetector:
    """涉政内容检测器"""

    def __init__(
        self,
        high_risk_keywords: Optional[List[str]] = None,
        medium_risk_keywords: Optional[List[str]] = None,
        enable_ai: bool = True,
    ):
        self.high_risk_keywords = high_risk_keywords or HIGH_RISK_KEYWORDS
        self.medium_risk_keywords = medium_risk_keywords or MEDIUM_RISK_KEYWORDS
        self.enable_ai = enable_ai

    def detect(
        self,
        content: str,
        *,
        skip_ai: bool = False,
    ) -> PoliticalDetectResult:
        """检测内容是否涉政

        Args:
            content: 待检测文本
            skip_ai: 是否跳过 AI 检测（默认 False）

        Returns:
            PoliticalDetectResult
        """
        if not content or not content.strip():
            return PoliticalDetectResult()

        # L1: 高危词库直接命中 → HIGH
        high_hits = [kw for kw in self.high_risk_keywords if kw in content]
        if high_hits:
            return PoliticalDetectResult(
                risk_level=PoliticalRiskLevel.HIGH.value,
                matched_keywords=high_hits,
                suggestion="命中高危涉政词，直接拦截",
                details={"layer": "L1_high", "hits": high_hits},
            )

        # L1: 正则模式命中 → HIGH
        pattern_hits = []
        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(content):
                pattern_hits.append(pattern.pattern)
        if pattern_hits:
            return PoliticalDetectResult(
                risk_level=PoliticalRiskLevel.HIGH.value,
                matched_keywords=pattern_hits,
                suggestion="命中涉政敏感模式，直接拦截",
                details={"layer": "L1_pattern", "hits": pattern_hits},
            )

        # L1: 中危词库命中 → MEDIUM
        medium_hits = [kw for kw in self.medium_risk_keywords if kw in content]
        if medium_hits:
            return PoliticalDetectResult(
                risk_level=PoliticalRiskLevel.MEDIUM.value,
                matched_keywords=medium_hits,
                suggestion="命中涉政人物名，建议人工复核",
                details={"layer": "L1_medium", "hits": medium_hits},
            )

        # L2: AI 语义级检测
        if self.enable_ai and not skip_ai:
            try:
                ai_result = self._ai_detect(content)
                if ai_result.get("flagged"):
                    return PoliticalDetectResult(
                        risk_level=PoliticalRiskLevel.MEDIUM.value,
                        ai_flagged=True,
                        ai_reason=ai_result.get("reason", ""),
                        suggestion="AI 判定疑似涉政，建议人工复核",
                        details={"layer": "L2_ai", "raw": ai_result},
                    )
            except Exception as e:
                logger.warning(f"[PoliticalDetector] AI 检测失败: {e}")

        return PoliticalDetectResult(
            risk_level=PoliticalRiskLevel.SAFE.value,
            suggestion="无涉政风险",
        )

    def _ai_detect(self, content: str) -> Dict[str, Any]:
        """调用 AI 服务做语义级涉政识别（同步接口，避免阻塞）"""
        try:
            import asyncio
            from api.services.ai_service import get_ai_service

            async def _call():
                svc = get_ai_service()
                prompt = (
                    "请判断以下内容是否涉及政治敏感话题（涉政人物/事件/口号/颠覆国家政权等）。"
                    "只返回 JSON：{\"flagged\": true/false, \"reason\": \"...\"}\n\n"
                    f"内容：{content[:500]}"
                )
                resp = await svc.generate_text(prompt)
                return resp

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在事件循环内，跳过 AI 检测避免阻塞
                    return {"flagged": False, "reason": "skipped_in_event_loop"}
                result = loop.run_until_complete(_call())
            except RuntimeError:
                result = asyncio.run(_call())

            # 解析 JSON
            import json
            if isinstance(result, str):
                # 提取 JSON
                start = result.find("{")
                end = result.rfind("}") + 1
                if start >= 0 and end > start:
                    return json.loads(result[start:end])
            return {"flagged": False, "reason": "parse_failed"}
        except Exception as e:
            logger.warning(f"[PoliticalDetector] AI 检测异常: {e}")
            return {"flagged": False, "reason": f"error: {e}"}

    async def detect_async(self, content: str) -> PoliticalDetectResult:
        """异步检测入口（与 ModerationService 风格一致）"""
        # 关键词检测同步执行
        result = self.detect(content, skip_ai=True)
        if result.blocked or result.needs_review:
            return result
        # AI 检测异步
        if self.enable_ai:
            try:
                from api.services.ai_service import get_ai_service
                svc = get_ai_service()
                prompt = (
                    "请判断以下内容是否涉及政治敏感话题。"
                    "只返回 JSON：{\"flagged\": true/false, \"reason\": \"...\"}\n\n"
                    f"内容：{content[:500]}"
                )
                resp = await svc.generate_text(prompt)
                import json
                if isinstance(resp, str):
                    start = resp.find("{")
                    end = resp.rfind("}") + 1
                    if start >= 0 and end > start:
                        ai_data = json.loads(resp[start:end])
                        if ai_data.get("flagged"):
                            return PoliticalDetectResult(
                                risk_level=PoliticalRiskLevel.MEDIUM.value,
                                ai_flagged=True,
                                ai_reason=ai_data.get("reason", ""),
                                suggestion="AI 判定疑似涉政，建议人工复核",
                                details={"layer": "L2_ai", "raw": ai_data},
                            )
            except Exception as e:
                logger.warning(f"[PoliticalDetector] detect_async AI 异常: {e}")
        return result


# ============ 单例 ============

_detector: Optional[PoliticalDetector] = None


def get_political_detector() -> PoliticalDetector:
    global _detector
    if _detector is None:
        _detector = PoliticalDetector()
    return _detector
