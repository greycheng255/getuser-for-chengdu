# -*- coding: utf-8 -*-
"""
文本查重 / 相似度检测

对应 PRD 5.6 内容风控 - 查重检测。
使用 SimHash + 汉明距离实现高效近似查重（适用于发布内容去重）。
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# SimHash 位数
_SIMHASH_BITS = 64


def _tokenize(text: str) -> List[str]:
    """中文分词（简易版：按字符 + 双字组合）

    生产环境可替换为 jieba，此处保持零依赖。
    """
    text = re.sub(r"\s+", "", text)
    # 单字 + 双字
    tokens = list(text)
    for i in range(len(text) - 1):
        tokens.append(text[i : i + 2])
    return tokens


def _hash64(token: str) -> int:
    """64 位哈希"""
    h = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def simhash(text: str) -> int:
    """计算文本的 SimHash 指纹

    Returns:
        64 位整数指纹
    """
    tokens = _tokenize(text)
    if not tokens:
        return 0
    v = [0] * _SIMHASH_BITS
    for token in tokens:
        h = _hash64(token)
        for i in range(_SIMHASH_BITS):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    fingerprint = 0
    for i in range(_SIMHASH_BITS):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """计算两个 SimHash 的汉明距离"""
    x = (a ^ b) & ((1 << _SIMHASH_BITS) - 1)
    dist = 0
    while x:
        dist += 1
        x &= x - 1
    return dist


def similarity_from_hash(a: int, b: int) -> float:
    """由 SimHash 计算相似度（0~1）"""
    dist = hamming_distance(a, b)
    return 1.0 - dist / _SIMHASH_BITS


@dataclass
class SimilarityResult:
    """查重结果"""

    is_duplicate: bool
    similarity: float  # 0~1
    matched_id: Optional[int] = None  # 匹配的历史记录 ID
    matched_content_preview: str = ""


class TextDedup:
    """文本查重服务（基于 SimHash + 数据库历史）"""

    def __init__(self, threshold: float = 0.85):
        """Args:
            threshold: 相似度阈值，超过则判定为重复
        """
        self.threshold = threshold

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    def fingerprint(self, text: str) -> int:
        return simhash(text)

    def is_duplicate_by_similarity(self, sim: float) -> bool:
        return sim >= self.threshold

    async def check_against_history(
        self,
        text: str,
        platform: str = "",
        user_id: int = 1,
    ) -> SimilarityResult:
        """与数据库历史发布内容比对

        扫描 moderation_log / publish 记录中的历史内容，找最相似的。
        """
        fp = self.fingerprint(text)
        if fp == 0:
            return SimilarityResult(is_duplicate=False, similarity=0.0)

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return SimilarityResult(is_duplicate=False, similarity=0.0)

            # 查询历史内容（从 publisher 发送记录 / moderation_log）
            async with engine.connect() as conn:
                # 优先查 sent_comments 表（X 平台发送记录）
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, content FROM sent_comments "
                        "WHERE content IS NOT NULL AND content != '' "
                        "ORDER BY id DESC LIMIT 200"
                    )
                )
                best_sim = 0.0
                best_id = None
                best_preview = ""
                for row in rows.fetchall():
                    hist_fp = self.fingerprint(row[1] or "")
                    if hist_fp == 0:
                        continue
                    sim = similarity_from_hash(fp, hist_fp)
                    if sim > best_sim:
                        best_sim = sim
                        best_id = row[0]
                        best_preview = (row[1] or "")[:50]
                is_dup = best_sim >= self.threshold
                return SimilarityResult(
                    is_duplicate=is_dup,
                    similarity=round(best_sim, 4),
                    matched_id=best_id,
                    matched_content_preview=best_preview,
                )
        except Exception as e:
            logger.warning(f"[Dedup] 查重失败（表可能不存在）: {e}")
            return SimilarityResult(is_duplicate=False, similarity=0.0)
