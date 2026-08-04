# -*- coding: utf-8 -*-
"""
合规留存归档服务

阶段二 P1 任务 2.3：补齐 PRD 5.6 合规留存归档机制。

策略：
- 90 天热数据：保留在 PostgreSQL 主库（compliance_archive 表）
- 1 年冷数据：归档到文件系统（默认 /var/log/mediacrawler/archive）
- 归档内容：发布内容、互动记录、操作日志、审核日志
- API：GET /api/moderation/archive 查询归档记录

设计：
1. 所有发布/互动前自动归档
2. 定时任务（每日凌晨）将超过 90 天的热数据迁移到冷存储
3. 冷存储为 JSON 文件，按 月/日 分目录
4. 支持按平台/类型/时间范围查询
"""

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ArchiveType(str, Enum):
    """归档类型"""
    PUBLISH = "publish"            # 发布内容
    INTERACTION = "interaction"    # 互动记录
    MODERATION = "moderation"      # 审核日志
    OPERATION = "operation"        # 用户操作日志


class ArchiveStatus(str, Enum):
    """归档状态"""
    HOT = "hot"        # 热数据（DB）
    COLD = "cold"      # 已迁移到冷存储
    PURGED = "purged"  # 已删除（超过 1 年）


@dataclass
class ArchiveRecord:
    """归档记录"""
    archive_id: str = ""
    archive_type: str = ArchiveType.PUBLISH.value
    platform: str = ""
    account_id: str = ""
    target_url: str = ""
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    owner_user_id: Optional[int] = None
    status: str = ArchiveStatus.HOT.value
    cold_path: Optional[str] = None   # 冷存储文件路径
    created_at: Optional[str] = None
    archived_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ComplianceArchiveService:
    """合规归档服务"""

    HOT_RETENTION_DAYS = 90          # 热数据保留 90 天
    COLD_RETENTION_DAYS = 365        # 冷数据保留 1 年
    DEFAULT_COLD_DIR = "/var/log/mediacrawler/archive"
    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎(公共方法,消除重复导入)"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if ComplianceArchiveService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS compliance_archive ("
                        "  archive_id VARCHAR(64) PRIMARY KEY,"
                        "  archive_type VARCHAR(32) NOT NULL,"
                        "  platform VARCHAR(32),"
                        "  account_id VARCHAR(64),"
                        "  target_url TEXT,"
                        "  content TEXT,"
                        "  metadata TEXT,"
                        "  owner_user_id INTEGER,"
                        "  status VARCHAR(16) DEFAULT 'hot',"
                        "  cold_path TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  archived_at TIMESTAMP)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_archive_lookup "
                        "ON compliance_archive(archive_type, platform, created_at)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_archive_status "
                        "ON compliance_archive(status, created_at)"
                    )
                )
            ComplianceArchiveService._ensured = True
        except Exception as e:
            logger.warning(f"[ComplianceArchive] ensure_table failed: {e}")

    # ============ 归档写入 ============

    async def archive(
        self,
        archive_type: str,
        platform: str,
        account_id: str,
        content: str = "",
        target_url: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        owner_user_id: Optional[int] = None,
    ) -> str:
        """归档一条记录

        Args:
            archive_type: ArchiveType 枚举值
            platform: 平台名
            account_id: 账号 ID
            content: 文本内容
            target_url: 目标 URL
            metadata: 额外元数据
            owner_user_id: 用户 ID

        Returns:
            archive_id
        """
        await self.ensure_table()
        # 注意：TIMESTAMP 列需要 datetime 对象，asyncpg 不接受 isoformat 字符串
        now_dt = datetime.now()
        record = ArchiveRecord(
            archive_id=f"arch_{uuid.uuid4().hex[:12]}",
            archive_type=archive_type,
            platform=platform,
            account_id=account_id,
            target_url=target_url,
            content=content,
            metadata=metadata or {},
            owner_user_id=owner_user_id,
            created_at=now_dt.isoformat(),
        )
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return record.archive_id
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO compliance_archive "
                        "(archive_id, archive_type, platform, account_id, target_url, "
                        " content, metadata, owner_user_id, status, created_at) "
                        "VALUES (:aid, :at, :pf, :acid, :tu, :ct, :md, :ouid, 'hot', :ca)"
                    ),
                    {
                        "aid": record.archive_id,
                        "at": record.archive_type,
                        "pf": record.platform,
                        "acid": record.account_id,
                        "tu": record.target_url,
                        "ct": record.content,
                        "md": json.dumps(record.metadata, ensure_ascii=False),
                        "ouid": record.owner_user_id,
                        "ca": now_dt,
                    },
                )
        except Exception as e:
            logger.warning(f"[ComplianceArchive] archive failed: {e}")
        return record.archive_id

    # ============ 归档查询 ============

    async def list_records(
        self,
        archive_type: Optional[str] = None,
        platform: Optional[str] = None,
        owner_user_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询归档记录"""
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return []
            async with engine.connect() as conn:
                sql = "SELECT * FROM compliance_archive WHERE 1=1"
                params: Dict[str, Any] = {"limit": limit, "offset": offset}
                if archive_type:
                    sql += " AND archive_type = :at"
                    params["at"] = archive_type
                if platform:
                    sql += " AND platform = :pf"
                    params["pf"] = platform
                if owner_user_id is not None:
                    sql += " AND owner_user_id = :ouid"
                    params["ouid"] = owner_user_id
                if start_date:
                    sql += " AND created_at >= :sd"
                    params["sd"] = start_date
                if end_date:
                    sql += " AND created_at <= :ed"
                    params["ed"] = end_date
                sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_record(r).to_dict() for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[ComplianceArchive] list_records failed: {e}")
            return []

    async def get_record(self, archive_id: str) -> Optional[Dict[str, Any]]:
        """查询单条归档记录"""
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM compliance_archive WHERE archive_id = :aid"),
                    {"aid": archive_id},
                )
                row = rows.fetchone()
                if not row:
                    return None
                record = self._row_to_record(row)
                result = record.to_dict()
                # 如果是冷存储，加载冷文件
                if record.status == ArchiveStatus.COLD.value and record.cold_path:
                    cold_data = self._load_cold(record.cold_path)
                    if cold_data:
                        result["cold_data"] = cold_data
                return result
        except Exception as e:
            logger.warning(f"[ComplianceArchive] get_record failed: {e}")
            return None

    # ============ 冷存储迁移 ============

    async def migrate_cold_storage(self) -> int:
        """将超过 90 天的热数据迁移到冷存储

        Returns:
            迁移的记录数
        """
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return 0
            cutoff = datetime.now() - timedelta(days=self.HOT_RETENTION_DAYS)
            async with engine.begin() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT * FROM compliance_archive "
                        "WHERE status = 'hot' AND created_at < :cutoff "
                        "LIMIT 1000"
                    ),
                    {"cutoff": cutoff},
                )
                records = [self._row_to_record(r) for r in rows.fetchall()]
                if not records:
                    return 0
                cold_dir = os.environ.get(
                    "COMPLIANCE_COLD_DIR", self.DEFAULT_COLD_DIR
                )
                migrated = 0
                for record in records:
                    cold_path = self._write_cold(cold_dir, record)
                    if cold_path:
                        await conn.execute(
                            sql_text(
                                "UPDATE compliance_archive "
                                "SET status = 'cold', cold_path = :cp, "
                                "    archived_at = :aa "
                                "WHERE archive_id = :aid"
                            ),
                            {
                                "cp": cold_path,
                                "aa": datetime.now(),
                                "aid": record.archive_id,
                            },
                        )
                        migrated += 1
                return migrated
        except Exception as e:
            logger.warning(f"[ComplianceArchive] migrate_cold_storage failed: {e}")
            return 0

    async def purge_expired(self) -> int:
        """清理超过 1 年的归档记录（含冷存储文件）"""
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return 0
            cutoff = datetime.now() - timedelta(days=self.COLD_RETENTION_DAYS)
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT archive_id, cold_path FROM compliance_archive "
                        "WHERE created_at < :cutoff AND status != 'purged'",
                    ),
                    {"cutoff": cutoff},
                )
                purged = 0
                for r in rows.fetchall():
                    archive_id = r[0]
                    cold_path = r[1]
                    # 删除冷存储文件
                    if cold_path and os.path.exists(cold_path):
                        try:
                            os.unlink(cold_path)
                        except Exception:
                            pass
                    # 标记为已清理（保留元数据记录，仅删除内容）
                    async with engine.begin() as conn2:
                        await conn2.execute(
                            sql_text(
                                "UPDATE compliance_archive "
                                "SET status = 'purged', content = '', metadata = '{}' "
                                "WHERE archive_id = :aid"
                            ),
                            {"aid": archive_id},
                        )
                    purged += 1
                return purged
        except Exception as e:
            logger.warning(f"[ComplianceArchive] purge_expired failed: {e}")
            return 0

    # ============ 冷存储工具 ============

    def _write_cold(self, cold_dir: str, record: ArchiveRecord) -> Optional[str]:
        """写入冷存储文件"""
        try:
            # 按 月/日 分目录
            now = datetime.now()
            sub_dir = os.path.join(
                cold_dir,
                f"{now.year}", f"{now.month:02d}", f"{now.day:02d}",
            )
            os.makedirs(sub_dir, exist_ok=True)
            file_path = os.path.join(sub_dir, f"{record.archive_id}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)
            return file_path
        except Exception as e:
            logger.warning(f"[ComplianceArchive] _write_cold failed: {e}")
            return None

    def _load_cold(self, cold_path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(cold_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[ComplianceArchive] _load_cold failed: {e}")
            return None

    def _row_to_record(self, row) -> ArchiveRecord:
        try:
            metadata = json.loads(row[6]) if row[6] else {}
        except Exception:
            metadata = {}
        return ArchiveRecord(
            archive_id=row[0],
            archive_type=row[1] or ArchiveType.PUBLISH.value,
            platform=row[2] or "",
            account_id=row[3] or "",
            target_url=row[4] or "",
            content=row[5] or "",
            metadata=metadata,
            owner_user_id=row[7],
            status=row[8] or ArchiveStatus.HOT.value,
            cold_path=row[9],
            created_at=str(row[10]) if row[10] else None,
            archived_at=str(row[11]) if row[11] else None,
        )


# ============ 单例 ============

_svc: Optional[ComplianceArchiveService] = None


def get_compliance_archive_service() -> ComplianceArchiveService:
    global _svc
    if _svc is None:
        _svc = ComplianceArchiveService()
    return _svc
