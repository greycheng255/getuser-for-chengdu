# -*- coding: utf-8 -*-
"""
多平台一键拆解流水线任务存储（platform-agnostic）

与 X 专用的 `auto_pipeline.py`（依赖 `XTwitterAutoPipelineTask` ORM 模型）平行存在。
本表不绑定任何平台，存储所有平台（x/douyin/xiaohongshu/bilibili/weibo/zhihu 等）
的"热点→拆解→文案→发布→互动→监控"任务进度。

表 auto_pipeline_tasks:
- task_id              VARCHAR(64)  PK
- platform             VARCHAR(32)  目标平台（x/douyin/xiaohongshu/...）
- source_post_id       VARCHAR(128) 源热点 ID（平台原始 ID 或 URL hash）
- source_post_url      TEXT         源热点 URL
- source_post_content  TEXT         源热点文案
- source_post_video    TEXT         源热点视频 URL
- source_post_author   VARCHAR(128) 源热点作者
- status               VARCHAR(32)  pending/running/completed/failed/cancelled
- current_step         INT          0~8
- step_detail          TEXT         当前步骤说明
- breakdown_text       TEXT         AI 生成的拆解文本（脚本+分镜+要点）
- video_url            TEXT         生成的解说视频 URL
- candidate_contents   JSONB        候选文案列表
- selected_content     TEXT         AI 选中的最佳文案
- published_post_id    VARCHAR(128) 发布后平台返回的帖子 ID
- published_post_url   TEXT         发布后帖子 URL
- account_id           BIGINT       发布所用账号 ID
- interaction_triggered INT         是否已触发互动（0/1）
- monitor_started      INT          是否已启动监控（0/1）
- error_msg           TEXT         错误信息
- options             JSONB        启动参数（skip_video/auto_monitor/trigger_interaction）
- owner_user_id       BIGINT       任务所有者
- add_ts              BIGINT       创建时间戳
- update_ts           BIGINT       更新时间戳

方法：ensure_table / create_task / update_task / get_task / list_tasks / cancel_task
单例：get_auto_pipeline_store()
"""

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# 步骤名（与前端展示对齐）
STEP_NAMES = {
    0: "待启动",
    1: "视频拆解",
    2: "生成解说视频",
    3: "生成发布文案",
    4: "AI选最佳文案",
    5: "填入视频URL",
    6: "发布到目标平台",
    7: "触发互动造势",
    8: "启动评论监控",
}

# 状态允许值
_VALID_STATUS = {"pending", "running", "completed", "failed", "cancelled"}


class AutoPipelineStore:
    """多平台流水线任务存储（异步 PostgreSQL）"""

    TABLE_NAME = "auto_pipeline_tasks"
    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """幂等建表"""
        if AutoPipelineStore._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        f"CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} ("
                        "  task_id VARCHAR(64) PRIMARY KEY,"
                        "  platform VARCHAR(32) NOT NULL,"
                        "  source_post_id VARCHAR(128),"
                        "  source_post_url TEXT,"
                        "  source_post_content TEXT,"
                        "  source_post_video TEXT,"
                        "  source_post_author VARCHAR(128),"
                        "  status VARCHAR(32) NOT NULL DEFAULT 'pending',"
                        "  current_step INT NOT NULL DEFAULT 0,"
                        "  step_detail TEXT,"
                        "  breakdown_text TEXT,"
                        "  video_url TEXT,"
                        "  candidate_contents JSONB,"
                        "  selected_content TEXT,"
                        "  published_post_id VARCHAR(128),"
                        "  published_post_url TEXT,"
                        "  account_id BIGINT,"
                        "  interaction_triggered INT DEFAULT 0,"
                        "  monitor_started INT DEFAULT 0,"
                        "  error_msg TEXT,"
                        "  options JSONB,"
                        "  owner_user_id BIGINT,"
                        "  add_ts BIGINT,"
                        "  update_ts BIGINT)"
                    )
                )
                # 索引
                for idx_sql in [
                    f"CREATE INDEX IF NOT EXISTS idx_ap_tasks_platform ON {self.TABLE_NAME} (platform)",
                    f"CREATE INDEX IF NOT EXISTS idx_ap_tasks_status ON {self.TABLE_NAME} (status)",
                    f"CREATE INDEX IF NOT EXISTS idx_ap_tasks_owner ON {self.TABLE_NAME} (owner_user_id)",
                    f"CREATE INDEX IF NOT EXISTS idx_ap_tasks_add_ts ON {self.TABLE_NAME} (add_ts DESC)",
                ]:
                    await conn.execute(sql_text(idx_sql))
            AutoPipelineStore._ensured = True
        except Exception as e:
            logger.warning(f"[AutoPipelineStore] ensure_table failed: {e}")

    async def create_task(
        self,
        *,
        platform: str,
        source_post_id: str,
        source_post_url: str = "",
        source_post_content: str = "",
        source_post_video: str = "",
        source_post_author: str = "",
        options: Optional[Dict[str, Any]] = None,
        owner_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建任务记录，返回 task dict"""
        task_id = str(uuid.uuid4())
        now = int(time.time())
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                raise RuntimeError("数据库引擎不可用")

            options_str = json.dumps(options or {}, ensure_ascii=False)
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO auto_pipeline_tasks "
                        "(task_id, platform, source_post_id, source_post_url, "
                        " source_post_content, source_post_video, source_post_author, "
                        " status, current_step, step_detail, options, "
                        " owner_user_id, add_ts, update_ts) "
                        "VALUES (:tid, :pf, :spid, :spurl, :spc, :spv, :spa, "
                        "        'pending', 0, '任务已创建,等待执行', :opt, "
                        "        :ouid, :now, :now)"
                    ),
                    {
                        "tid": task_id,
                        "pf": platform,
                        "spid": source_post_id or "",
                        "spurl": source_post_url or "",
                        "spc": source_post_content or "",
                        "spv": source_post_video or "",
                        "spa": source_post_author or "",
                        "opt": options_str,
                        "ouid": owner_user_id,
                        "now": now,
                    },
                )
            logger.info(f"[AutoPipelineStore] created task_id={task_id} platform={platform}")
        except Exception as e:
            logger.warning(f"[AutoPipelineStore] create_task failed: {e}")
            raise

        return await self.get_task(task_id) or {
            "task_id": task_id,
            "platform": platform,
            "status": "pending",
            "current_step": 0,
            "step_detail": "任务已创建,等待执行",
        }

    async def update_task(self, task_id: str, **kwargs) -> None:
        """更新任务字段（仅更新存在的字段）"""
        if not kwargs:
            return
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return

            # 字段白名单（防 SQL 注入）
            allowed = {
                "status", "current_step", "step_detail", "breakdown_text",
                "video_url", "candidate_contents", "selected_content",
                "published_post_id", "published_post_url", "account_id",
                "interaction_triggered", "monitor_started", "error_msg",
            }
            sets: List[str] = []
            params: Dict[str, Any] = {"tid": task_id, "now": int(time.time())}
            for k, v in kwargs.items():
                if k not in allowed:
                    continue
                if k == "candidate_contents" and isinstance(v, (list, dict)):
                    v = json.dumps(v, ensure_ascii=False)
                if k == "status" and v not in _VALID_STATUS:
                    continue
                sets.append(f"{k} = :{k}")
                params[k] = v
            if not sets:
                return
            sets.append("update_ts = :now")

            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(f"UPDATE auto_pipeline_tasks SET {', '.join(sets)} WHERE task_id = :tid"),
                    params,
                )
        except Exception as e:
            logger.warning(f"[AutoPipelineStore] update_task failed: {e}")

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(_SELECT_SQL + " WHERE task_id = :tid"),
                    {"tid": task_id},
                )
                row = rows.fetchone()
                if row is None:
                    return None
                return self._row_to_dict(row)
        except Exception as e:
            logger.warning(f"[AutoPipelineStore] get_task failed: {e}")
            return None

    async def list_tasks(
        self,
        *,
        platform: Optional[str] = None,
        status: Optional[str] = None,
        owner_user_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return []

            where_parts: List[str] = []
            params: Dict[str, Any] = {"limit": limit}
            if platform:
                where_parts.append("platform = :pf")
                params["pf"] = platform
            if status:
                where_parts.append("status = :st")
                params["st"] = status
            if owner_user_id is not None:
                where_parts.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            sql = _SELECT_SQL + f" {where_sql} ORDER BY add_ts DESC LIMIT :limit"
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[AutoPipelineStore] list_tasks failed: {e}")
            return []

    async def cancel_task(self, task_id: str) -> bool:
        """标记任务为已取消（仅当任务处于 pending/running 时）"""
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return False
            async with engine.begin() as conn:
                result = await conn.execute(
                    sql_text(
                        "UPDATE auto_pipeline_tasks "
                        "SET status='cancelled', step_detail='用户手动取消', "
                        "    error_msg='user_cancelled', update_ts=:now "
                        "WHERE task_id=:tid AND status IN ('pending','running')"
                    ),
                    {"tid": task_id, "now": int(time.time())},
                )
                return (result.rowcount or 0) > 0
        except Exception as e:
            logger.warning(f"[AutoPipelineStore] cancel_task failed: {e}")
            return False

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        r = row._mapping if hasattr(row, "_mapping") else dict(row)
        candidate = r.get("candidate_contents")
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except Exception:
                candidate = []
        if not isinstance(candidate, list):
            candidate = []

        options = r.get("options")
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except Exception:
                options = {}
        if not isinstance(options, dict):
            options = {}

        current_step = int(r.get("current_step") or 0)
        return {
            "task_id": r.get("task_id"),
            "platform": r.get("platform"),
            "source_post_id": r.get("source_post_id") or "",
            "source_post_url": r.get("source_post_url") or "",
            "source_post_content": r.get("source_post_content") or "",
            "source_post_video": r.get("source_post_video") or "",
            "source_post_author": r.get("source_post_author") or "",
            "status": r.get("status") or "pending",
            "current_step": current_step,
            "step_name": STEP_NAMES.get(current_step, "未知"),
            "step_detail": r.get("step_detail") or "",
            "breakdown_text": r.get("breakdown_text") or "",
            "video_url": r.get("video_url") or "",
            "candidate_contents": candidate,
            "selected_content": r.get("selected_content") or "",
            "published_post_id": r.get("published_post_id") or "",
            "published_post_url": r.get("published_post_url") or "",
            "account_id": r.get("account_id"),
            "interaction_triggered": int(r.get("interaction_triggered") or 0),
            "monitor_started": int(r.get("monitor_started") or 0),
            "error_msg": r.get("error_msg") or "",
            "options": options,
            "owner_user_id": r.get("owner_user_id"),
            "add_ts": r.get("add_ts") or 0,
            "update_ts": r.get("update_ts") or 0,
        }


_SELECT_SQL = (
    "SELECT task_id, platform, source_post_id, source_post_url, "
    " source_post_content, source_post_video, source_post_author, "
    " status, current_step, step_detail, breakdown_text, video_url, "
    " candidate_contents, selected_content, published_post_id, published_post_url, "
    " account_id, interaction_triggered, monitor_started, error_msg, options, "
    " owner_user_id, add_ts, update_ts "
    "FROM auto_pipeline_tasks"
)


# ============ 单例 ============

_store: Optional[AutoPipelineStore] = None


def get_auto_pipeline_store() -> AutoPipelineStore:
    global _store
    if _store is None:
        _store = AutoPipelineStore()
    return _store
