# -*- coding: utf-8 -*-
"""
评论 → 意向客户线索识别器

调用 AI（get_ai_agent_client().generate_text）对评论进行意图分类 + 评分：
- is_lead: 是否为潜在意向客户
- intent_type: 意图类型（inquiry / recommendation / comparison / purchase / negative / irrelevant）
- lead_score: 线索评分 0-100
- reason: 判定理由

复用 interaction_monitor 中的 is_ai_in_cooldown / is_ai_expected_error 短路逻辑，
AI 不可用时退化为关键词匹配规则（不阻断主流程）。
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from .platform_comment_fetcher import UnifiedComment

logger = logging.getLogger(__name__)


@dataclass
class LeadExtractionResult:
    """线索识别结果"""
    is_lead: bool = False
    intent_type: str = "irrelevant"  # inquiry/recommendation/comparison/purchase/negative/irrelevant
    lead_score: int = 0
    reason: str = ""
    matched_keywords: List[str] = None

    def __post_init__(self):
        if self.matched_keywords is None:
            self.matched_keywords = []


# 关键词规则兜底（AI 不可用时使用）
DEFAULT_LEAD_KEYWORDS = [
    "怎么卖", "多少钱", "价格", "联系方式", "电话", "地址", "在哪",
    "怎么联系", "可以定制吗", "有货吗", "什么时候发货", "能优惠吗",
    "想买", "求购", "咨询", "下单", "合作", "加盟", "代理", "批发",
    "私聊", "求链接", "哪里买", "门店", "营业时间", "营业",
]


class LeadExtractor:
    """意向客户线索识别器"""

    # 单批 AI 调用合并评论数上限（降低调用次数）
    BATCH_SIZE = 8

    async def extract(
        self,
        comment: UnifiedComment,
        keywords: Optional[List[str]] = None,
        post_title: str = "",
    ) -> LeadExtractionResult:
        """识别单条评论（先尝试 AI，失败兜底关键词）"""
        keywords = keywords or []
        # 1. 关键词匹配（始终执行，作为 matched_keywords 来源）
        matched = self._match_keywords(comment.comment_text, keywords)

        # 2. AI 识别
        ai_result = await self._extract_via_ai(comment, post_title, keywords)
        if ai_result is not None:
            # AI 结果优先，但合并 matched_keywords
            ai_result.matched_keywords = matched or ai_result.matched_keywords
            return ai_result

        # 3. 兜底：基于关键词的规则识别
        return self._rule_based_extract(comment, matched)

    async def extract_batch(
        self,
        comments: List[UnifiedComment],
        keywords: Optional[List[str]] = None,
        post_title: str = "",
    ) -> List[LeadExtractionResult]:
        """批量识别（单批 ≤ BATCH_SIZE，合并 prompt 降低调用次数）"""
        if not comments:
            return []
        keywords = keywords or []
        # 单批限制
        batch = comments[: self.BATCH_SIZE]
        ai_results = await self._extract_batch_via_ai(batch, post_title, keywords)

        results: List[LeadExtractionResult] = []
        for i, c in enumerate(batch):
            matched = self._match_keywords(c.comment_text, keywords)
            if ai_results and i < len(ai_results) and ai_results[i] is not None:
                ai_results[i].matched_keywords = matched or ai_results[i].matched_keywords
                results.append(ai_results[i])
            else:
                results.append(self._rule_based_extract(c, matched))
        return results

    # ============ AI 识别 ============

    async def _extract_via_ai(
        self,
        comment: UnifiedComment,
        post_title: str,
        keywords: List[str],
    ) -> Optional[LeadExtractionResult]:
        """单条 AI 识别"""
        try:
            from api.services.ai_agent_client import (
                get_ai_agent_client,
                is_ai_in_cooldown,
                is_ai_expected_error,
            )

            if is_ai_in_cooldown():
                return None

            prompt = self._build_prompt(
                comments=[comment], post_title=post_title, keywords=keywords
            )
            client = get_ai_agent_client()
            raw = await client.generate_text(prompt)
            if not raw:
                return None
            return self._parse_ai_response(raw, idx=0)
        except Exception as e:
            if self._is_ai_expected(e):
                logger.debug(f"[LeadExtractor] AI 预期内错误跳过: {e}")
            else:
                logger.warning(f"[LeadExtractor] AI 识别失败: {e}")
            return None

    async def _extract_batch_via_ai(
        self,
        comments: List[UnifiedComment],
        post_title: str,
        keywords: List[str],
    ) -> Optional[List[Optional[LeadExtractionResult]]]:
        """批量 AI 识别"""
        try:
            from api.services.ai_agent_client import (
                get_ai_agent_client,
                is_ai_in_cooldown,
                is_ai_expected_error,
            )

            if is_ai_in_cooldown():
                return None

            prompt = self._build_prompt(
                comments=comments, post_title=post_title, keywords=keywords
            )
            client = get_ai_agent_client()
            raw = await client.generate_text(prompt)
            if not raw:
                return None

            # 期望 AI 返回 JSON 数组
            parsed = self._parse_json_array(raw)
            if parsed is None:
                # 兜底尝试单条解析
                single = self._parse_ai_response(raw, idx=0)
                return [single] if single else None

            results: List[Optional[LeadExtractionResult]] = []
            for i, _ in enumerate(comments):
                if i < len(parsed):
                    results.append(self._dict_to_result(parsed[i]))
                else:
                    results.append(None)
            return results
        except Exception as e:
            if self._is_ai_expected(e):
                logger.debug(f"[LeadExtractor] 批量 AI 预期内错误跳过: {e}")
            else:
                logger.warning(f"[LeadExtractor] 批量 AI 识别失败: {e}")
            return None

    def _build_prompt(
        self,
        comments: List[UnifiedComment],
        post_title: str,
        keywords: List[str],
    ) -> str:
        """构造 AI prompt（要求 JSON 输出）"""
        items = []
        for i, c in enumerate(comments):
            items.append(
                f"[{i}] 评论: {c.comment_text}\n    作者: {c.author_nickname}"
            )
        comments_block = "\n".join(items)
        kw = "、".join(keywords) if keywords else "无特定关键词"

        if len(comments) == 1:
            return (
                f"你是一个营销线索分析助手。下面是一条评论，请判断是否为潜在意向客户。\n\n"
                f"帖子标题: {post_title or '(未知)'}\n"
                f"业务关注关键词: {kw}\n\n"
                f"{comments_block}\n\n"
                f"请严格输出 JSON（仅 JSON，不要任何解释或代码块）：\n"
                f'{{"is_lead": true/false, "intent_type": "inquiry|recommendation|comparison|purchase|negative|irrelevant", '
                f'"lead_score": 0-100, "reason": "判定理由（不超过30字）"}}\n'
                f"判定标准：is_lead=true 当评论中包含询价/求购/合作/咨询联系方式等明确意向，lead_score 反映意向强度。"
            )
        else:
            return (
                f"你是一个营销线索分析助手。下面有{len(comments)}条评论，请逐条判断是否为潜在意向客户。\n\n"
                f"帖子标题: {post_title or '(未知)'}\n"
                f"业务关注关键词: {kw}\n\n"
                f"{comments_block}\n\n"
                f"请严格输出 JSON 数组（仅 JSON，不要任何解释或代码块），每条评论一个对象：\n"
                f'[{{"is_lead": true/false, "intent_type": "...", "lead_score": 0-100, "reason": "..."}}]\n'
                f"intent_type 取值: inquiry|recommendation|comparison|purchase|negative|irrelevant。"
                f"is_lead=true 当评论中包含询价/求购/合作/咨询联系方式等明确意向。"
            )

    def _parse_ai_response(self, raw: str, idx: int = 0) -> Optional[LeadExtractionResult]:
        """解析 AI 单条/数组响应"""
        # 尝试解析数组
        arr = self._parse_json_array(raw)
        if arr is not None and idx < len(arr):
            return self._dict_to_result(arr[idx])
        # 尝试解析单对象
        obj = self._parse_json_object(raw)
        if obj is not None:
            return self._dict_to_result(obj)
        return None

    def _parse_json_array(self, raw: str) -> Optional[List[dict]]:
        try:
            cleaned = self._strip_code_fence(raw)
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except Exception:
            pass
        return None

    def _parse_json_object(self, raw: str) -> Optional[dict]:
        try:
            cleaned = self._strip_code_fence(raw)
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        # 兜底：从文本中提取 { ... }
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None

    @staticmethod
    def _strip_code_fence(raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            # 去掉首行 ```json 或 ```
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        return raw

    @staticmethod
    def _dict_to_result(d: dict) -> LeadExtractionResult:
        if not isinstance(d, dict):
            return LeadExtractionResult()
        is_lead = bool(d.get("is_lead", False))
        score = d.get("lead_score", 0)
        try:
            score = int(score)
        except Exception:
            score = 0
        score = max(0, min(100, score))
        return LeadExtractionResult(
            is_lead=is_lead,
            intent_type=str(d.get("intent_type", "irrelevant"))[:50],
            lead_score=score,
            reason=str(d.get("reason", ""))[:200],
        )

    @staticmethod
    def _is_ai_expected(e: Exception) -> bool:
        try:
            from api.services.ai_agent_client import is_ai_expected_error
            return is_ai_expected_error(e)
        except Exception:
            return False

    # ============ 关键词规则兜底 ============

    @staticmethod
    def _match_keywords(text: str, keywords: List[str]) -> List[str]:
        if not text:
            return []
        text_lower = text.lower()
        matched = []
        # 业务关键词 + 默认意向词
        all_kw = list(set(list(keywords) + DEFAULT_LEAD_KEYWORDS))
        for kw in all_kw:
            if not kw:
                continue
            if kw.lower() in text_lower:
                matched.append(kw)
        return matched

    @staticmethod
    def _rule_based_extract(
        comment: UnifiedComment, matched: List[str]
    ) -> LeadExtractionResult:
        """基于关键词的兜底识别"""
        if not matched:
            return LeadExtractionResult(
                is_lead=False, intent_type="irrelevant", lead_score=0
            )
        # 命中关键词数 → 评分
        score = min(80, 30 + len(matched) * 10)
        # 强意向词加分
        strong_signals = ["怎么卖", "多少钱", "想买", "求购", "私聊", "联系方式", "电话", "下单"]
        strong_hits = [kw for kw in strong_signals if kw in comment.comment_text]
        if strong_hits:
            score = min(95, score + 15)
        return LeadExtractionResult(
            is_lead=score >= 50,
            intent_type="inquiry" if strong_hits else "recommendation",
            lead_score=score,
            reason=f"命中关键词: {','.join(matched[:5])}",
            matched_keywords=matched,
        )


# 单例
_lead_extractor: Optional[LeadExtractor] = None


def get_lead_extractor() -> LeadExtractor:
    global _lead_extractor
    if _lead_extractor is None:
        _lead_extractor = LeadExtractor()
    return _lead_extractor
