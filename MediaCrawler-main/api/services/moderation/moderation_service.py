# -*- coding: utf-8 -*-
"""
内容审核服务

对应 PRD 5.6 内容风控：
1. 违规词检测（复用 publisher/content_adapter.py 词库）
2. 查重检测（dedup.TextDedup）
3. 发布前自动审核（整合违规词 + 查重，给出审核决策）
4. 审核日志记录（PostgreSQL moderation_log 表）

设计：异步 + MediaCrawler 数据库，与 account_service 风格一致。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from .dedup import TextDedup, SimilarityResult

logger = logging.getLogger(__name__)


class ModerationDecision(str, Enum):
    """审核决策"""

    APPROVED = "approved"  # 通过
    REJECTED = "rejected"  # 拒绝（违规词/严重重复）
    NEEDS_REVIEW = "needs_review"  # 人工复审（轻度重复/疑似违规）


@dataclass
class ModerationResult:
    """审核结果"""

    decision: str
    platform: str
    content_preview: str = ""
    violation_hits: List[str] = field(default_factory=list)  # 违规词命中
    dedup_result: Optional[SimilarityResult] = None
    warnings: List[str] = field(default_factory=list)
    log_id: Optional[int] = None
    checked_at: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.decision == ModerationDecision.APPROVED.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "platform": self.platform,
            "content_preview": self.content_preview,
            "violation_hits": self.violation_hits,
            "dedup": (
                {
                    "is_duplicate": self.dedup_result.is_duplicate,
                    "similarity": self.dedup_result.similarity,
                    "matched_id": self.dedup_result.matched_id,
                }
                if self.dedup_result
                else None
            ),
            "warnings": self.warnings,
            "log_id": self.log_id,
            "checked_at": self.checked_at,
        }


class ModerationService:
    """内容审核服务（异步）"""

    def __init__(self, dedup_threshold: float = 0.85):
        self._dedup = TextDedup(threshold=dedup_threshold)

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def moderate(
        self,
        content: str,
        platform: str = "",
        *,
        enable_dedup: bool = True,
        enable_political: bool = True,
        strict: bool = False,
    ) -> ModerationResult:
        """发布前内容审核

        Args:
            content: 待审核内容
            platform: 目标平台（不同平台词库不同）
            enable_dedup: 是否启用查重
            enable_political: 是否启用涉政检测（任务 2.3）
            strict: 严格模式（轻度违规也拒绝）
        """
        from api.services.publisher.content_adapter import moderate_content

        result = ModerationResult(
            decision=ModerationDecision.APPROVED.value,
            platform=platform,
            content_preview=content[:80],
            checked_at=datetime.utcnow().isoformat(),
        )

        # 1. 违规词检测
        passed, hits = moderate_content(content, platform or "xiaohongshu")
        if not passed:
            result.violation_hits = hits
            # 严重违规词直接拒绝
            severe_keywords = ["违法", "色情", "赌博", "毒品", "枪支", "诈骗"]
            is_severe = any(
                any(kw in h for kw in severe_keywords) for h in hits
            )
            if is_severe or strict:
                result.decision = ModerationDecision.REJECTED.value
                result.warnings.append(f"命中 {len(hits)} 项违规词（含严重违规）")
            else:
                result.decision = ModerationDecision.NEEDS_REVIEW.value
                result.warnings.append(f"命中 {len(hits)} 项违规词，建议人工复审")

        # 2. 涉政内容检测（任务 2.3）
        if enable_political:
            try:
                from .political_detector import get_political_detector
                detector = get_political_detector()
                pol_result = await detector.detect_async(content)
                if pol_result.blocked:
                    # 高危涉政直接拒绝
                    result.decision = ModerationDecision.REJECTED.value
                    result.violation_hits = result.violation_hits + pol_result.matched_keywords
                    result.warnings.append(
                        f"涉政检测拦截: {pol_result.suggestion}"
                    )
                elif pol_result.needs_review:
                    # 中危涉政进入人工复核
                    if result.decision == ModerationDecision.APPROVED.value:
                        result.decision = ModerationDecision.NEEDS_REVIEW.value
                    result.violation_hits = result.violation_hits + pol_result.matched_keywords
                    result.warnings.append(
                        f"涉政检测疑似: {pol_result.suggestion}"
                    )
            except Exception as e:
                logger.warning(f"[ModerationService] 涉政检测失败: {e}")

        # 3. 查重检测
        if enable_dedup:
            dup = await self._dedup.check_against_history(content, platform)
            result.dedup_result = dup
            if dup.is_duplicate:
                if dup.similarity >= 0.95:
                    result.decision = ModerationDecision.REJECTED.value
                    result.warnings.append(
                        f"与历史内容高度重复（相似度 {dup.similarity:.2%}）"
                    )
                elif result.decision == ModerationDecision.APPROVED.value:
                    result.decision = ModerationDecision.NEEDS_REVIEW.value
                    result.warnings.append(
                        f"与历史内容相似（相似度 {dup.similarity:.2%}）"
                    )

        # 4. 触发内容异常预警（高违规率）
        if result.decision == ModerationDecision.REJECTED.value:
            try:
                from api.services.alert.alert_center import (
                    emit_content_violation, AlertSeverity,
                )
                await emit_content_violation(
                    platform=platform,
                    content_preview=result.content_preview,
                    violation_type="auto_rejected",
                    severity=AlertSeverity.WARNING.value,
                )
            except Exception:
                pass

        # 5. 记录审核日志 + 合规归档
        log_id = await self._log_moderation(result, content)
        result.log_id = log_id
        try:
            from .compliance_archive import (
                get_compliance_archive_service, ArchiveType,
            )
            await get_compliance_archive_service().archive(
                archive_type=ArchiveType.MODERATION.value,
                platform=platform,
                account_id="",
                content=content,
                metadata={"decision": result.decision, "hits": result.violation_hits},
            )
        except Exception:
            pass

        # 审计日志：内容审核完成（P1-6）
        try:
            from api.services.utils.audit_log import (
                get_audit_log_service, AuditActionType,
            )
            audit_status = "success"
            if result.decision == ModerationDecision.REJECTED.value:
                audit_status = "failed"
            elif result.decision == ModerationDecision.NEEDS_REVIEW.value:
                audit_status = "needs_review"
            await get_audit_log_service().log(
                action_type=AuditActionType.CONFIG_CHANGE.value,
                platform=platform,
                target=result.content_preview[:80],
                description=(
                    f"内容审核: decision={result.decision} "
                    f"hits={len(result.violation_hits)} warnings={len(result.warnings)}"
                ),
                request_data={
                    "content_preview": result.content_preview,
                    "platform": platform,
                    "strict": strict,
                },
                response_data={
                    "decision": result.decision,
                    "violation_hits": result.violation_hits,
                    "warnings": result.warnings,
                    "dedup_similarity": (
                        result.dedup_result.similarity if result.dedup_result else None
                    ),
                    "moderation_log_id": log_id,
                },
                status=audit_status,
            )
        except Exception as e:
            logger.warning(f"[Moderation] 记录审计日志失败: {e}")

        return result

    async def _log_moderation(self, result: ModerationResult, full_content: str) -> Optional[int]:
        """记录审核日志到数据库"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS moderation_log ("
                        "  id SERIAL PRIMARY KEY,"
                        "  platform VARCHAR(32),"
                        "  content TEXT,"
                        "  decision VARCHAR(32),"
                        "  violation_hits TEXT,"
                        "  dedup_similarity FLOAT,"
                        "  warnings TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
                row = await conn.execute(
                    sql_text(
                        "INSERT INTO moderation_log "
                        "(platform, content, decision, violation_hits, dedup_similarity, warnings) "
                        "VALUES (:p, :c, :d, :v, :s, :w) RETURNING id"
                    ),
                    {
                        "p": result.platform,
                        "c": full_content[:2000],
                        "d": result.decision,
                        "v": " | ".join(result.violation_hits)[:500],
                        "s": result.dedup_result.similarity if result.dedup_result else None,
                        "w": " | ".join(result.warnings)[:500],
                    },
                )
                r = row.fetchone()
                return r[0] if r else None
        except Exception as e:
            logger.warning(f"[Moderation] 记录审核日志失败: {e}")
            return None

    async def list_logs(
        self, platform: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """查询审核日志"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                if platform:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, platform, content, decision, violation_hits, "
                            "dedup_similarity, warnings, created_at "
                            "FROM moderation_log WHERE platform=:p "
                            "ORDER BY id DESC LIMIT :l"
                        ),
                        {"p": platform, "l": limit},
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, platform, content, decision, violation_hits, "
                            "dedup_similarity, warnings, created_at "
                            "FROM moderation_log ORDER BY id DESC LIMIT :l"
                        ),
                        {"l": limit},
                    )
                return [
                    {
                        "id": r[0],
                        "platform": r[1],
                        "content_preview": (r[2] or "")[:80],
                        "decision": r[3],
                        "violation_hits": r[4],
                        "dedup_similarity": r[5],
                        "warnings": r[6],
                        "created_at": str(r[7]) if r[7] else None,
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[Moderation] 查询日志失败: {e}")
            return []


# 单例
_moderation: Optional[ModerationService] = None


def get_moderation_service() -> ModerationService:
    global _moderation
    if _moderation is None:
        _moderation = ModerationService()
    return _moderation
