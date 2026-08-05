# -*- coding: utf-8 -*-
"""
内容审核人工复核工作流

阶段一 P0 任务 1.2：补齐 PRD 5.2 审核机制人工复核流程。

流程：
1. 自动审核通过 → 直接入发布队列
2. 自动审核失败/可疑 → 进入人工复核队列
3. 人工审核通过 → 入发布队列
4. 人工审核拒绝 → 归档 + 通知

对应 PRD 5.2.4 审核机制（自动查重/违规词/低俗内容 + 人工复核）。
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReviewStatus(str, Enum):
    """复核状态"""
    PENDING = "pending"               # 待人工复核
    APPROVED = "approved"             # 人工通过
    REJECTED = "rejected"             # 人工拒绝
    AUTO_APPROVED = "auto_approved"   # 自动通过
    AUTO_REJECTED = "auto_rejected"   # 自动拒绝


class ContentType(str, Enum):
    """内容类型"""
    VIDEO = "video"
    IMAGE = "image"
    TEXT = "text"
    ARTICLE = "article"


@dataclass
class ReviewTask:
    """人工复核任务"""
    review_id: str = ""
    content_type: str = "video"
    content_id: str = ""                 # 关联内容 ID（如视频任务 ID）
    content_url: str = ""                # 内容 URL（如视频 URL）
    content_preview: str = ""            # 内容预览文本（前 500 字）
    auto_moderation_result: Dict[str, Any] = field(default_factory=dict)
    status: str = ReviewStatus.PENDING.value
    reviewer_id: Optional[int] = None    # 复核员 ID
    review_notes: str = ""               # 复核备注
    review_tags: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    owner_user_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReviewWorkflowService:
    """人工复核工作流服务"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if ReviewWorkflowService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS video_review_tasks ("
                        "  review_id VARCHAR(64) PRIMARY KEY,"
                        "  content_type VARCHAR(32) DEFAULT 'video',"
                        "  content_id VARCHAR(128),"
                        "  content_url TEXT,"
                        "  content_preview TEXT,"
                        "  auto_moderation_result TEXT,"
                        "  status VARCHAR(32) DEFAULT 'pending',"
                        "  reviewer_id INTEGER,"
                        "  review_notes TEXT,"
                        "  review_tags TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  reviewed_at TIMESTAMP,"
                        "  owner_user_id INTEGER)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_review_status "
                        "ON video_review_tasks(status, created_at DESC)"
                    )
                )
            ReviewWorkflowService._ensured = True
        except Exception as e:
            logger.warning(f"[ReviewWorkflow] ensure_table failed: {e}")

    async def create_review_task(
        self,
        content_type: str,
        content_id: str,
        content_url: str = "",
        content_preview: str = "",
        auto_moderation_result: Optional[Dict[str, Any]] = None,
        owner_user_id: Optional[int] = None,
    ) -> ReviewTask:
        """创建人工复核任务"""
        await self.ensure_table()
        task = ReviewTask(
            review_id=f"rev_{uuid.uuid4().hex[:12]}",
            content_type=content_type,
            content_id=content_id,
            content_url=content_url,
            content_preview=content_preview[:500] if content_preview else "",
            auto_moderation_result=auto_moderation_result or {},
            status=ReviewStatus.PENDING.value,
            created_at=datetime.now().isoformat(),
            owner_user_id=owner_user_id,
        )
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return task
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO video_review_tasks "
                        "(review_id, content_type, content_id, content_url, content_preview, "
                        " auto_moderation_result, status, reviewer_id, review_notes, "
                        " review_tags, created_at, owner_user_id) "
                        "VALUES (:rid, :ct, :cid, :curl, :cp, :amr, :st, NULL, '', '', :ca, :ouid)"
                    ),
                    {
                        "rid": task.review_id,
                        "ct": task.content_type,
                        "cid": task.content_id,
                        "curl": task.content_url,
                        "cp": task.content_preview,
                        "amr": json.dumps(task.auto_moderation_result, ensure_ascii=False),
                        "st": task.status,
                        "ca": task.created_at,
                        "ouid": task.owner_user_id,
                    },
                )
        except Exception as e:
            logger.warning(f"[ReviewWorkflow] create_review_task failed: {e}")
        return task

    async def list_pending_reviews(
        self,
        owner_user_id: Optional[int] = None,
        content_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列出待复核任务"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                sql = "SELECT * FROM video_review_tasks WHERE status = 'pending'"
                params: Dict[str, Any] = {"limit": limit, "offset": offset}
                if owner_user_id is not None:
                    sql += " AND owner_user_id = :ouid"
                    params["ouid"] = owner_user_id
                if content_type:
                    sql += " AND content_type = :ct"
                    params["ct"] = content_type
                sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[ReviewWorkflow] list_pending_reviews failed: {e}")
            return []

    async def submit_review(
        self,
        review_id: str,
        reviewer_id: int,
        decision: str,  # approved / rejected
        notes: str = "",
        tags: Optional[List[str]] = None,
    ) -> bool:
        """提交人工复核结果

        若 decision=approved 且复核任务关联流水线（content_id 形如 pipeline_xxx），
        自动回调 UnifiedPipeline.proceed_after_review() 推进 Step5 发布调度。
        """
        if decision not in (ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value):
            return False
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE video_review_tasks SET "
                        " status = :st, reviewer_id = :rid, review_notes = :rn, "
                        " review_tags = :rt, reviewed_at = :ra "
                        "WHERE review_id = :rid2 AND status = 'pending'"
                    ),
                    {
                        "st": decision,
                        "rid": reviewer_id,
                        "rn": notes,
                        "rt": json.dumps(tags or [], ensure_ascii=False),
                        "ra": datetime.now().isoformat(),
                        "rid2": review_id,
                    },
                )

            # 复核通过 → 自动推进流水线 Step5
            if decision == ReviewStatus.APPROVED.value:
                try:
                    from api.services.ai.unified_pipeline import get_unified_pipeline
                    result = await get_unified_pipeline().proceed_after_review(review_id)
                    if result.get("success"):
                        logger.info(
                            f"[ReviewWorkflow] 复核 {review_id} 已触发流水线 "
                            f"pipeline_id={result.get('pipeline_id')} "
                            f"schedule_task_id={result.get('schedule_task_id')}"
                        )
                except Exception as e:
                    logger.warning(f"[ReviewWorkflow] 触发流水线失败(非致命): {e}")
            return True
        except Exception as e:
            logger.warning(f"[ReviewWorkflow] submit_review failed: {e}")
            return False

    async def get_review(self, review_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM video_review_tasks WHERE review_id = :rid"),
                    {"rid": review_id},
                )
                row = rows.fetchone()
                return self._row_to_dict(row) if row else None
        except Exception as e:
            logger.warning(f"[ReviewWorkflow] get_review failed: {e}")
            return None

    async def list_recent_reviews(
        self,
        owner_user_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """最近复核记录（含已完成）"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                if owner_user_id is not None:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM video_review_tasks WHERE owner_user_id = :ouid "
                            "ORDER BY reviewed_at DESC NULLS LAST, created_at DESC LIMIT :limit"
                        ),
                        {"ouid": owner_user_id, "limit": limit},
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM video_review_tasks "
                            "ORDER BY reviewed_at DESC NULLS LAST, created_at DESC LIMIT :limit"
                        ),
                        {"limit": limit},
                    )
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[ReviewWorkflow] list_recent_reviews failed: {e}")
            return []

    def _row_to_dict(self, row) -> Dict[str, Any]:
        try:
            amr = json.loads(row[5]) if row[5] else {}
        except Exception:
            amr = {}
        try:
            tags = json.loads(row[9]) if row[9] else []
        except Exception:
            tags = []
        return {
            "review_id": row[0],
            "content_type": row[1],
            "content_id": row[2],
            "content_url": row[3],
            "content_preview": row[4],
            "auto_moderation_result": amr,
            "status": row[6],
            "reviewer_id": row[7],
            "review_notes": row[8],
            "review_tags": tags,
            "created_at": str(row[10]) if row[10] else None,
            "reviewed_at": str(row[11]) if row[11] else None,
            "owner_user_id": row[12],
        }


# ============ 单例 ============
_service: Optional[ReviewWorkflowService] = None


def get_review_workflow_service() -> ReviewWorkflowService:
    global _service
    if _service is None:
        _service = ReviewWorkflowService()
    return _service
