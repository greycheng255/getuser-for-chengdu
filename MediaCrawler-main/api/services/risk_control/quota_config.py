# -*- coding: utf-8 -*-
"""
统一频次硬限制配置中心

阶段二 P1 任务 2.3：补齐 PRD 5.6 频次硬限制配置。

数据类 QuotaConfig：
- platform: 平台名
- max_publishes_per_day: 单账号单日最大发布数
- max_interactions_per_day: 单账号单日最大互动数
- max_comments_per_post: 单条内容最大评论数
- like_comment_ratio: 点赞评论比例

设计：
1. 持久化到 quota_configs 表（含 owner_user_id 隔离）
2. 在 publisher/interactor 执行前校验
3. 超额则拒绝执行并返回明确错误
4. 默认值参考主流平台风控阈值
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============ 平台默认配额（参考主流平台风控阈值） ============

PLATFORM_DEFAULT_QUOTAS = {
    "douyin":       {"max_publishes_per_day": 5,  "max_interactions_per_day": 80,  "max_comments_per_post": 10, "like_comment_ratio": 5.0},
    "xiaohongshu":  {"max_publishes_per_day": 5,  "max_interactions_per_day": 80,  "max_comments_per_post": 8,  "like_comment_ratio": 5.0},
    "bilibili":     {"max_publishes_per_day": 4,  "max_interactions_per_day": 60,  "max_comments_per_post": 8,  "like_comment_ratio": 5.0},
    "weibo":        {"max_publishes_per_day": 10, "max_interactions_per_day": 100, "max_comments_per_post": 10, "like_comment_ratio": 4.0},
    "zhihu":        {"max_publishes_per_day": 5,  "max_interactions_per_day": 50,  "max_comments_per_post": 5,  "like_comment_ratio": 5.0},
    "kuaishou":     {"max_publishes_per_day": 5,  "max_interactions_per_day": 80,  "max_comments_per_post": 10, "like_comment_ratio": 5.0},
    "x_twitter_publisher": {"max_publishes_per_day": 20, "max_interactions_per_day": 100, "max_comments_per_post": 5, "like_comment_ratio": 4.0},
    "tiktok":       {"max_publishes_per_day": 5,  "max_interactions_per_day": 100, "max_comments_per_post": 10, "like_comment_ratio": 5.0},
    "instagram":    {"max_publishes_per_day": 5,  "max_interactions_per_day": 80,  "max_comments_per_post": 8,  "like_comment_ratio": 5.0},
    "youtube":      {"max_publishes_per_day": 3,  "max_interactions_per_day": 50,  "max_comments_per_post": 5,  "like_comment_ratio": 5.0},
    "facebook":     {"max_publishes_per_day": 5,  "max_interactions_per_day": 80,  "max_comments_per_post": 8,  "like_comment_ratio": 5.0},
}


@dataclass
class QuotaConfig:
    """频次硬限制配置"""
    config_id: str = ""
    platform: str = ""
    max_publishes_per_day: int = 5
    max_interactions_per_day: int = 80
    max_comments_per_post: int = 10
    like_comment_ratio: float = 5.0
    owner_user_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def validate(self) -> List[str]:
        errors = []
        if self.max_publishes_per_day < 0:
            errors.append("max_publishes_per_day 必须 >= 0")
        if self.max_interactions_per_day < 0:
            errors.append("max_interactions_per_day 必须 >= 0")
        if self.max_comments_per_post < 0:
            errors.append("max_comments_per_post 必须 >= 0")
        if self.like_comment_ratio <= 0:
            errors.append("like_comment_ratio 必须 > 0")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuotaCheckResult:
    """配额校验结果"""
    allowed: bool = True
    reason: str = ""
    current_usage: Dict[str, int] = field(default_factory=dict)
    limit: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class QuotaConfigService:
    """频次配置服务（异步 PostgreSQL）"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if QuotaConfigService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS quota_configs ("
                        "  config_id VARCHAR(64) PRIMARY KEY,"
                        "  platform VARCHAR(32) NOT NULL,"
                        "  max_publishes_per_day INTEGER DEFAULT 5,"
                        "  max_interactions_per_day INTEGER DEFAULT 80,"
                        "  max_comments_per_post INTEGER DEFAULT 10,"
                        "  like_comment_ratio FLOAT DEFAULT 5.0,"
                        "  owner_user_id INTEGER,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  updated_at TIMESTAMP DEFAULT NOW())"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_quota_platform_user "
                        "ON quota_configs(platform, COALESCE(owner_user_id, -1))"
                    )
                )
                # 配额使用记录表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS quota_usage ("
                        "  id SERIAL PRIMARY KEY,"
                        "  platform VARCHAR(32) NOT NULL,"
                        "  account_id VARCHAR(64),"
                        "  action_type VARCHAR(32) NOT NULL,"
                        "  target_url TEXT,"
                        "  owner_user_id INTEGER,"
                        "  recorded_at TIMESTAMP DEFAULT NOW())"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_quota_usage_lookup "
                        "ON quota_usage(platform, account_id, action_type, recorded_at)"
                    )
                )
            QuotaConfigService._ensured = True
        except Exception as e:
            logger.warning(f"[QuotaConfigService] ensure_table failed: {e}")

    # ============ 配置 CRUD ============

    async def get_config(
        self, platform: str, owner_user_id: Optional[int] = None
    ) -> QuotaConfig:
        """获取配置（不存在则返回默认值）"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return self._default_config(platform, owner_user_id)
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT * FROM quota_configs "
                        "WHERE platform = :pf AND "
                        "  (owner_user_id = :ouid OR (owner_user_id IS NULL AND :ouid IS NULL)) "
                        "ORDER BY owner_user_id DESC LIMIT 1"
                    ),
                    {"pf": platform, "ouid": owner_user_id},
                )
                row = rows.fetchone()
                if row:
                    return QuotaConfig(
                        config_id=row[0],
                        platform=row[1],
                        max_publishes_per_day=int(row[2] or 5),
                        max_interactions_per_day=int(row[3] or 80),
                        max_comments_per_post=int(row[4] or 10),
                        like_comment_ratio=float(row[5] or 5.0),
                        owner_user_id=row[6],
                        created_at=str(row[7]) if row[7] else None,
                        updated_at=str(row[8]) if row[8] else None,
                    )
            return self._default_config(platform, owner_user_id)
        except Exception as e:
            logger.warning(f"[QuotaConfigService] get_config failed: {e}")
            return self._default_config(platform, owner_user_id)

    async def save_config(self, cfg: QuotaConfig) -> bool:
        """保存配置（upsert）"""
        await self.ensure_table()
        errors = cfg.validate()
        if errors:
            return False
        if not cfg.config_id:
            cfg.config_id = f"quota_{uuid.uuid4().hex[:12]}"
        cfg.updated_at = datetime.now().isoformat()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO quota_configs "
                        "(config_id, platform, max_publishes_per_day, max_interactions_per_day, "
                        " max_comments_per_post, like_comment_ratio, owner_user_id, updated_at) "
                        "VALUES (:cid, :pf, :mpd, :mid, :mcp, :lcr, :ouid, :ua) "
                        "ON CONFLICT (config_id) DO UPDATE SET "
                        " max_publishes_per_day = :mpd, "
                        " max_interactions_per_day = :mid, "
                        " max_comments_per_post = :mcp, "
                        " like_comment_ratio = :lcr, "
                        " updated_at = :ua"
                    ),
                    {
                        "cid": cfg.config_id,
                        "pf": cfg.platform,
                        "mpd": cfg.max_publishes_per_day,
                        "mid": cfg.max_interactions_per_day,
                        "mcp": cfg.max_comments_per_post,
                        "lcr": cfg.like_comment_ratio,
                        "ouid": cfg.owner_user_id,
                        "ua": datetime.now(),
                    },
                )
            return True
        except Exception as e:
            logger.warning(f"[QuotaConfigService] save_config failed: {e}")
            return False

    async def list_configs(
        self, platform: Optional[str] = None,
        owner_user_id: Optional[int] = None,
    ) -> List[QuotaConfig]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                sql = "SELECT * FROM quota_configs WHERE 1=1"
                params: Dict[str, Any] = {}
                if platform:
                    sql += " AND platform = :pf"
                    params["pf"] = platform
                if owner_user_id is not None:
                    sql += " AND owner_user_id = :ouid"
                    params["ouid"] = owner_user_id
                sql += " ORDER BY platform, owner_user_id"
                rows = await conn.execute(sql_text(sql), params)
                result = []
                for r in rows.fetchall():
                    result.append(QuotaConfig(
                        config_id=r[0], platform=r[1],
                        max_publishes_per_day=int(r[2] or 5),
                        max_interactions_per_day=int(r[3] or 80),
                        max_comments_per_post=int(r[4] or 10),
                        like_comment_ratio=float(r[5] or 5.0),
                        owner_user_id=r[6],
                        created_at=str(r[7]) if r[7] else None,
                        updated_at=str(r[8]) if r[8] else None,
                    ))
                return result
        except Exception as e:
            logger.warning(f"[QuotaConfigService] list_configs failed: {e}")
            return []

    # ============ 配额校验 ============

    async def check_publish_quota(
        self,
        platform: str,
        account_id: str,
        owner_user_id: Optional[int] = None,
    ) -> QuotaCheckResult:
        """校验发布配额"""
        cfg = await self.get_config(platform, owner_user_id)
        usage = await self._get_usage_today(
            platform, account_id, "publish", owner_user_id
        )
        if usage >= cfg.max_publishes_per_day:
            return QuotaCheckResult(
                allowed=False,
                reason=f"已达单日发布上限 {cfg.max_publishes_per_day}",
                current_usage={"publishes_today": usage},
                limit={"max_publishes_per_day": cfg.max_publishes_per_day},
            )
        return QuotaCheckResult(
            allowed=True,
            current_usage={"publishes_today": usage},
            limit={"max_publishes_per_day": cfg.max_publishes_per_day},
        )

    async def check_interaction_quota(
        self,
        platform: str,
        account_id: str,
        interaction_type: str = "like",
        owner_user_id: Optional[int] = None,
    ) -> QuotaCheckResult:
        """校验互动配额"""
        cfg = await self.get_config(platform, owner_user_id)
        usage = await self._get_usage_today(
            platform, account_id, "interaction", owner_user_id
        )
        if usage >= cfg.max_interactions_per_day:
            return QuotaCheckResult(
                allowed=False,
                reason=f"已达单日互动上限 {cfg.max_interactions_per_day}",
                current_usage={"interactions_today": usage},
                limit={"max_interactions_per_day": cfg.max_interactions_per_day},
            )
        return QuotaCheckResult(
            allowed=True,
            current_usage={"interactions_today": usage},
            limit={"max_interactions_per_day": cfg.max_interactions_per_day},
        )

    async def record_usage(
        self,
        platform: str,
        account_id: str,
        action_type: str,  # publish / interaction
        target_url: str = "",
        owner_user_id: Optional[int] = None,
    ) -> bool:
        """记录配额使用"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO quota_usage "
                        "(platform, account_id, action_type, target_url, owner_user_id) "
                        "VALUES (:pf, :aid, :at, :tu, :ouid)"
                    ),
                    {
                        "pf": platform, "aid": account_id,
                        "at": action_type, "tu": target_url, "ouid": owner_user_id,
                    },
                )
            return True
        except Exception as e:
            logger.warning(f"[QuotaConfigService] record_usage failed: {e}")
            return False

    async def _get_usage_today(
        self,
        platform: str,
        account_id: str,
        action_type: str,
        owner_user_id: Optional[int] = None,
    ) -> int:
        """查询今日使用量"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return 0
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT COUNT(*) FROM quota_usage "
                        "WHERE platform = :pf AND account_id = :aid "
                        "AND action_type = :at "
                        "AND recorded_at >= CURRENT_DATE"
                    ),
                    {"pf": platform, "aid": account_id, "at": action_type},
                )
                return int(rows.fetchone()[0] or 0)
        except Exception:
            return 0

    def _default_config(
        self, platform: str, owner_user_id: Optional[int]
    ) -> QuotaConfig:
        """根据平台默认值生成配置"""
        defaults = PLATFORM_DEFAULT_QUOTAS.get(platform, {})
        return QuotaConfig(
            config_id="",
            platform=platform,
            max_publishes_per_day=defaults.get("max_publishes_per_day", 5),
            max_interactions_per_day=defaults.get("max_interactions_per_day", 80),
            max_comments_per_post=defaults.get("max_comments_per_post", 10),
            like_comment_ratio=defaults.get("like_comment_ratio", 5.0),
            owner_user_id=owner_user_id,
        )


# ============ 单例 ============

_svc: Optional[QuotaConfigService] = None


def get_quota_config_service() -> QuotaConfigService:
    global _svc
    if _svc is None:
        _svc = QuotaConfigService()
    return _svc
