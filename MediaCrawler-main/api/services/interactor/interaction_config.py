# -*- coding: utf-8 -*-
"""
互动量配置服务（阶段四任务 4.3）

对应 PRD 5.4 互动运营 - 单条内容互动量区间 + 点赞评论比例 + 时效控制：
1. 单条内容互动量区间（min/max，按平台/场景配置）
2. 点赞评论比例（如 5:1，每条评论对应 5 个点赞）
3. 时效控制（发布后延迟 5-30 分钟启动互动，随机间隔）
4. 互动类型权重（点赞/评论/收藏/转发的比例）
5. 持久化到 interaction_configs 表（含 owner_user_id 隔离）

被 InteractionScheduler / MultiInteractor 调用。
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class InteractionConfig:
    """互动量配置"""

    config_id: str = ""
    name: str = ""  # 配置名称
    platform: str = ""  # 平台，"all" 表示全局
    scene: str = "default"  # 场景：default / hotspot_viral / new_post / marketing

    # 互动量区间
    min_likes: int = 5  # 单条内容最少点赞数
    max_likes: int = 20
    min_comments: int = 1  # 单条内容最少评论数
    max_comments: int = 5
    min_shares: int = 0  # 转发
    max_shares: int = 3
    min_favorites: int = 0  # 收藏
    max_favorites: int = 5

    # 比例控制
    like_comment_ratio: float = 5.0  # 点赞/评论比例（5:1）
    interaction_target_total: int = 30  # 单条内容总互动量目标

    # 时效控制
    delay_start_min_minutes: int = 5  # 发布后延迟启动互动（分钟）
    delay_start_max_minutes: int = 30
    interval_min_seconds: int = 30  # 每次互动之间的最小间隔
    interval_max_seconds: int = 180  # 每次互动之间的最大间隔

    # 互动类型权重（用于在总互动量内分配）
    weight_like: float = 0.6
    weight_comment: float = 0.15
    weight_share: float = 0.1
    weight_favorite: float = 0.15

    owner_user_id: Optional[int] = None
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def compute_split(self, total: int) -> Dict[str, int]:
        """按权重分配总互动量到各类型"""
        if total <= 0:
            return {"like": 0, "comment": 0, "share": 0, "favorite": 0}
        weight_sum = self.weight_like + self.weight_comment + self.weight_share + self.weight_favorite
        if weight_sum <= 0:
            return {"like": total, "comment": 0, "share": 0, "favorite": 0}
        likes = int(round(total * self.weight_like / weight_sum))
        comments = int(round(total * self.weight_comment / weight_sum))
        shares = int(round(total * self.weight_share / weight_sum))
        favorites = max(0, total - likes - comments - shares)
        return {
            "like": max(self.min_likes, min(likes, self.max_likes)),
            "comment": max(self.min_comments, min(comments, self.max_comments)),
            "share": max(self.min_shares, min(shares, self.max_shares)),
            "favorite": max(self.min_favorites, min(favorites, self.max_favorites)),
        }


class InteractionConfigService:
    """互动量配置服务

    表结构：
        interaction_configs:
            config_id VARCHAR(64) PRIMARY KEY
            name VARCHAR(128)
            platform VARCHAR(32)
            scene VARCHAR(32)
            min_likes INT, max_likes INT
            min_comments INT, max_comments INT
            min_shares INT, max_shares INT
            min_favorites INT, max_favorites INT
            like_comment_ratio NUMERIC(4,2)
            interaction_target_total INT
            delay_start_min_minutes INT, delay_start_max_minutes INT
            interval_min_seconds INT, interval_max_seconds INT
            weight_like NUMERIC(3,2), weight_comment NUMERIC(3,2)
            weight_share NUMERIC(3,2), weight_favorite NUMERIC(3,2)
            owner_user_id INT
            is_active BOOLEAN DEFAULT TRUE
            created_at TIMESTAMP, updated_at TIMESTAMP
    """

    TABLE_NAME = "interaction_configs"
    _ensured = False  # DDL 仅首次执行一次，避免每次请求都跑 CREATE TABLE/INDEX

    async def ensure_table(self):
        if InteractionConfigService._ensured:
            return
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        f"CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} ("
                        "  config_id VARCHAR(64) PRIMARY KEY,"
                        "  name VARCHAR(128),"
                        "  platform VARCHAR(32) DEFAULT 'all',"
                        "  scene VARCHAR(32) DEFAULT 'default',"
                        "  min_likes INT DEFAULT 5,"
                        "  max_likes INT DEFAULT 20,"
                        "  min_comments INT DEFAULT 1,"
                        "  max_comments INT DEFAULT 5,"
                        "  min_shares INT DEFAULT 0,"
                        "  max_shares INT DEFAULT 3,"
                        "  min_favorites INT DEFAULT 0,"
                        "  max_favorites INT DEFAULT 5,"
                        "  like_comment_ratio NUMERIC(4,2) DEFAULT 5.0,"
                        "  interaction_target_total INT DEFAULT 30,"
                        "  delay_start_min_minutes INT DEFAULT 5,"
                        "  delay_start_max_minutes INT DEFAULT 30,"
                        "  interval_min_seconds INT DEFAULT 30,"
                        "  interval_max_seconds INT DEFAULT 180,"
                        "  weight_like NUMERIC(3,2) DEFAULT 0.6,"
                        "  weight_comment NUMERIC(3,2) DEFAULT 0.15,"
                        "  weight_share NUMERIC(3,2) DEFAULT 0.1,"
                        "  weight_favorite NUMERIC(3,2) DEFAULT 0.15,"
                        "  owner_user_id INT,"
                        "  is_active BOOLEAN DEFAULT TRUE,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  updated_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_interaction_configs_platform_scene "
                        f"ON {self.TABLE_NAME} (platform, scene, is_active)"
                    )
                )
                # 写入默认全局配置（如不存在）
                await conn.execute(
                    sql_text(
                        f"INSERT INTO {self.TABLE_NAME} "
                        "(config_id, name, platform, scene) "
                        "SELECT CAST(:cid AS VARCHAR(64)), 'default_global', CAST('all' AS VARCHAR(32)), CAST('default' AS VARCHAR(32)) "
                        "WHERE NOT EXISTS ("
                        f"  SELECT 1 FROM {self.TABLE_NAME} WHERE config_id=CAST(:cid AS VARCHAR(64))"
                        ")"
                    ),
                    {"cid": "cfg_default_global"},
                )
            InteractionConfigService._ensured = True
        except Exception as e:
            logger.warning(f"[InteractionConfig] 建表失败: {e}")

    # ==================== CRUD ====================

    async def save(self, cfg: InteractionConfig) -> Optional[str]:
        await self.ensure_table()
        if not cfg.config_id:
            cfg.config_id = f"cfg_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        cfg.updated_at = now.isoformat()
        if not cfg.created_at:
            cfg.created_at = now.isoformat()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return None
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        f"INSERT INTO {self.TABLE_NAME} ("
                        "  config_id, name, platform, scene, "
                        "  min_likes, max_likes, min_comments, max_comments, "
                        "  min_shares, max_shares, min_favorites, max_favorites, "
                        "  like_comment_ratio, interaction_target_total, "
                        "  delay_start_min_minutes, delay_start_max_minutes, "
                        "  interval_min_seconds, interval_max_seconds, "
                        "  weight_like, weight_comment, weight_share, weight_favorite, "
                        "  owner_user_id, is_active, created_at, updated_at"
                        ") VALUES ("
                        "  :cid, :n, :p, :sc, :ml, :xl, :mc, :xc, :ms, :xs, :mf, :xf, "
                        "  :lcr, :itt, :dsm, :dxm, :imn, :imx, :wl, :wc, :ws, :wf, "
                        "  :u, :a, :ca, :ua"
                        ") ON CONFLICT (config_id) DO UPDATE SET "
                        "  name=EXCLUDED.name, platform=EXCLUDED.platform, scene=EXCLUDED.scene, "
                        "  min_likes=EXCLUDED.min_likes, max_likes=EXCLUDED.max_likes, "
                        "  min_comments=EXCLUDED.min_comments, max_comments=EXCLUDED.max_comments, "
                        "  min_shares=EXCLUDED.min_shares, max_shares=EXCLUDED.max_shares, "
                        "  min_favorites=EXCLUDED.min_favorites, max_favorites=EXCLUDED.max_favorites, "
                        "  like_comment_ratio=EXCLUDED.like_comment_ratio, "
                        "  interaction_target_total=EXCLUDED.interaction_target_total, "
                        "  delay_start_min_minutes=EXCLUDED.delay_start_min_minutes, "
                        "  delay_start_max_minutes=EXCLUDED.delay_start_max_minutes, "
                        "  interval_min_seconds=EXCLUDED.interval_min_seconds, "
                        "  interval_max_seconds=EXCLUDED.interval_max_seconds, "
                        "  weight_like=EXCLUDED.weight_like, weight_comment=EXCLUDED.weight_comment, "
                        "  weight_share=EXCLUDED.weight_share, weight_favorite=EXCLUDED.weight_favorite, "
                        "  is_active=EXCLUDED.is_active, updated_at=NOW()"
                    ),
                    {
                        "cid": cfg.config_id,
                        "n": cfg.name,
                        "p": cfg.platform,
                        "sc": cfg.scene,
                        "ml": cfg.min_likes, "xl": cfg.max_likes,
                        "mc": cfg.min_comments, "xc": cfg.max_comments,
                        "ms": cfg.min_shares, "xs": cfg.max_shares,
                        "mf": cfg.min_favorites, "xf": cfg.max_favorites,
                        "lcr": cfg.like_comment_ratio,
                        "itt": cfg.interaction_target_total,
                        "dsm": cfg.delay_start_min_minutes,
                        "dxm": cfg.delay_start_max_minutes,
                        "imn": cfg.interval_min_seconds,
                        "imx": cfg.interval_max_seconds,
                        "wl": cfg.weight_like, "wc": cfg.weight_comment,
                        "ws": cfg.weight_share, "wf": cfg.weight_favorite,
                        "u": cfg.owner_user_id,
                        "a": cfg.is_active,
                        "ca": now,
                        "ua": now,
                    },
                )
            return cfg.config_id
        except Exception as e:
            logger.warning(f"[InteractionConfig] 保存失败: {e}")
            return None

    async def get(self, config_id: str) -> Optional[InteractionConfig]:
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT * FROM {self.TABLE_NAME} WHERE config_id=:cid"
                    ),
                    {"cid": config_id},
                )
                r = rows.fetchone()
                return self._row_to_config(r) if r else None
        except Exception as e:
            logger.warning(f"[InteractionConfig] 查询失败: {e}")
            return None

    async def find(
        self,
        platform: str = "all",
        scene: str = "default",
        owner_user_id: Optional[int] = None,
    ) -> Optional[InteractionConfig]:
        """查找匹配的配置：优先平台+场景+用户，回退到全局"""
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return None

            # 优先级 1：平台+场景+用户
            sql = (
                f"SELECT * FROM {self.TABLE_NAME} WHERE platform=:p AND scene=:sc "
                "AND is_active=TRUE AND owner_user_id=:u LIMIT 1"
            )
            params = {"p": platform, "sc": scene, "u": owner_user_id}
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                r = rows.fetchone()
                if r:
                    return self._row_to_config(r)

                # 优先级 2：平台+场景（无用户）
                sql = (
                    f"SELECT * FROM {self.TABLE_NAME} WHERE platform=:p AND scene=:sc "
                    "AND is_active=TRUE AND owner_user_id IS NULL LIMIT 1"
                )
                rows = await conn.execute(sql_text(sql), {"p": platform, "sc": scene})
                r = rows.fetchone()
                if r:
                    return self._row_to_config(r)

                # 优先级 3：全局默认
                sql = (
                    f"SELECT * FROM {self.TABLE_NAME} WHERE platform='all' AND scene=:sc "
                    "AND is_active=TRUE LIMIT 1"
                )
                rows = await conn.execute(sql_text(sql), {"sc": scene})
                r = rows.fetchone()
                if r:
                    return self._row_to_config(r)

                # 优先级 4：兜底默认
                sql = (
                    f"SELECT * FROM {self.TABLE_NAME} WHERE platform='all' AND scene='default' "
                    "AND is_active=TRUE LIMIT 1"
                )
                rows = await conn.execute(sql_text(sql))
                r = rows.fetchone()
                if r:
                    return self._row_to_config(r)
        except Exception as e:
            logger.warning(f"[InteractionConfig] 查找失败: {e}")
        # 完全失败时返回内存默认
        return InteractionConfig()

    async def list(self, platform: str = "", owner_user_id: Optional[int] = None) -> List[InteractionConfig]:
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return []
            conditions = ["is_active=TRUE"]
            params: Dict[str, Any] = {}
            if platform:
                conditions.append("(platform=:p OR platform='all')")
                params["p"] = platform
            if owner_user_id is not None:
                conditions.append("(owner_user_id=:u OR owner_user_id IS NULL)")
                params["u"] = owner_user_id
            sql = f"SELECT * FROM {self.TABLE_NAME} WHERE " + " AND ".join(conditions)
            sql += " ORDER BY platform DESC, scene ASC"
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_config(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[InteractionConfig] 列表查询失败: {e}")
            return []

    async def deactivate(self, config_id: str) -> bool:
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        f"UPDATE {self.TABLE_NAME} SET is_active=FALSE, updated_at=NOW() "
                        "WHERE config_id=:cid"
                    ),
                    {"cid": config_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[InteractionConfig] 停用失败: {e}")
            return False

    # ==================== 私有 ====================

    def _row_to_config(self, r) -> InteractionConfig:
        m = r._mapping if hasattr(r, "_mapping") else dict(r)
        return InteractionConfig(
            config_id=str(m.get("config_id") or ""),
            name=str(m.get("name") or ""),
            platform=str(m.get("platform") or "all"),
            scene=str(m.get("scene") or "default"),
            min_likes=int(m.get("min_likes") or 5),
            max_likes=int(m.get("max_likes") or 20),
            min_comments=int(m.get("min_comments") or 1),
            max_comments=int(m.get("max_comments") or 5),
            min_shares=int(m.get("min_shares") or 0),
            max_shares=int(m.get("max_shares") or 3),
            min_favorites=int(m.get("min_favorites") or 0),
            max_favorites=int(m.get("max_favorites") or 5),
            like_comment_ratio=float(m.get("like_comment_ratio") or 5.0),
            interaction_target_total=int(m.get("interaction_target_total") or 30),
            delay_start_min_minutes=int(m.get("delay_start_min_minutes") or 5),
            delay_start_max_minutes=int(m.get("delay_start_max_minutes") or 30),
            interval_min_seconds=int(m.get("interval_min_seconds") or 30),
            interval_max_seconds=int(m.get("interval_max_seconds") or 180),
            weight_like=float(m.get("weight_like") or 0.6),
            weight_comment=float(m.get("weight_comment") or 0.15),
            weight_share=float(m.get("weight_share") or 0.1),
            weight_favorite=float(m.get("weight_favorite") or 0.15),
            owner_user_id=m.get("owner_user_id"),
            is_active=bool(m.get("is_active")),
            created_at=str(m.get("created_at")) if m.get("created_at") else None,
            updated_at=str(m.get("updated_at")) if m.get("updated_at") else None,
        )


# ==================== 单例 ====================

_singleton: Optional[InteractionConfigService] = None


def get_interaction_config_service() -> InteractionConfigService:
    global _singleton
    if _singleton is None:
        _singleton = InteractionConfigService()
    return _singleton
