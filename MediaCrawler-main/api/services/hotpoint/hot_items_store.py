# -*- coding: utf-8 -*-
"""
热点条目持久化存储（hot_items 表）

阶段一 P1-2 + P2-4 + P2-3（部分）：
统一存储多平台抓取到的热点条目，供突发预警 / 筛选配置预览 / 热度预测 /
批量视频生成等模块读写。原先 hotpoint_alert / hotpoint_filter_config /
heat_predictor / batch_video_generator 都 SELECT 一张从未创建的 hot_items
表，本模块补齐建表与读写接口。

设计：
- PostgreSQL 异步（复用 database.db_session.get_async_engine，与项目其他建表代码风格一致）
- 唯一键 (platform, source_id)：upsert 时更新热度字段 + last_seen_at
- 提供爆款 / 收藏 / 禁用标记
- 提供 list / get / mark_* / list_recent / get_history_samples 接口
- 单例 get_hot_items_store()
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HotItemsStore:
    """hot_items 表的读写服务"""

    TABLE_NAME = "hot_items"
    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """建表（IF NOT EXISTS）+ 索引"""
        if HotItemsStore._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS hot_items ("
                        "  hot_id SERIAL PRIMARY KEY,"
                        "  platform VARCHAR(32) NOT NULL,"
                        "  source_id VARCHAR(128),"
                        "  title VARCHAR(500),"
                        "  content TEXT,"
                        "  url TEXT,"
                        "  video_url TEXT,"
                        "  username VARCHAR(128),"
                        "  heat_value BIGINT DEFAULT 0,"
                        "  likes_count BIGINT DEFAULT 0,"
                        "  retweets_count BIGINT DEFAULT 0,"
                        "  replies_count BIGINT DEFAULT 0,"
                        "  views_count BIGINT DEFAULT 0,"
                        "  source_keyword VARCHAR(64),"
                        "  category VARCHAR(32),"
                        "  is_viral BOOLEAN DEFAULT FALSE,"
                        "  is_favorited BOOLEAN DEFAULT FALSE,"
                        "  is_disabled BOOLEAN DEFAULT FALSE,"
                        "  recommended_platforms TEXT,"
                        "  first_seen_at TIMESTAMPTZ DEFAULT NOW(),"
                        "  last_seen_at TIMESTAMPTZ DEFAULT NOW(),"
                        "  owner_user_id BIGINT,"
                        "  extra JSONB)"
                    )
                )
                # 唯一索引：同一平台同一 source_id 仅保留一条
                await conn.execute(
                    sql_text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_hot_items_platform_source "
                        "ON hot_items(platform, source_id)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_hot_items_heat "
                        "ON hot_items(heat_value DESC)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_hot_items_platform "
                        "ON hot_items(platform)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_hot_items_viral "
                        "ON hot_items(is_viral)"
                    )
                )
            HotItemsStore._ensured = True
        except Exception as e:
            logger.warning(f"[HotItemsStore] ensure_table failed: {e}")

    async def upsert(self, item: dict) -> Optional[int]:
        """插入或更新（基于 platform + source_id 唯一键）

        更新热度字段（heat_value / likes_count / ...）与 last_seen_at；
        标记字段（is_viral / is_favorited / is_disabled）默认不覆盖既有值，
        但允许调用方在 item 中显式传入以覆盖。

        Returns:
            hot_id（成功） / None（失败）
        """
        if not item:
            return None
        platform = item.get("platform") or ""
        source_id = item.get("source_id") or ""
        if not platform:
            return None
        # source_id 为空时基于 url/title 兜底生成，避免唯一索引冲突
        if not source_id:
            fallback = (item.get("url") or item.get("title") or "")[:64]
            source_id = f"noid_{platform}_{fallback}"

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None

            rec_platforms = item.get("recommended_platforms")
            if isinstance(rec_platforms, (list, tuple)):
                rec_platforms = json.dumps(list(rec_platforms), ensure_ascii=False)
            extra = item.get("extra")
            if isinstance(extra, (dict, list)):
                extra = json.dumps(extra, ensure_ascii=False)

            async with engine.begin() as conn:
                rows = await conn.execute(
                    sql_text(
                        "INSERT INTO hot_items "
                        "(platform, source_id, title, content, url, video_url, username, "
                        " heat_value, likes_count, retweets_count, replies_count, views_count, "
                        " source_keyword, category, is_viral, is_favorited, is_disabled, "
                        " recommended_platforms, owner_user_id, extra) "
                        "VALUES (:pf, :sid, :ti, :ct, :url, :vurl, :un, :hv, :lk, :rt, :rp, :vw, "
                        "        :sk, :cat, :iv, :ifav, :idbl, :rp_plat, :ouid, :ex) "
                        "ON CONFLICT (platform, source_id) DO UPDATE SET "
                        " title=EXCLUDED.title, content=EXCLUDED.content, url=EXCLUDED.url, "
                        " video_url=EXCLUDED.video_url, username=EXCLUDED.username, "
                        " heat_value=EXCLUDED.heat_value, likes_count=EXCLUDED.likes_count, "
                        " retweets_count=EXCLUDED.retweets_count, replies_count=EXCLUDED.replies_count, "
                        " views_count=EXCLUDED.views_count, source_keyword=EXCLUDED.source_keyword, "
                        " category=EXCLUDED.category, is_viral=EXCLUDED.is_viral, "
                        " recommended_platforms=EXCLUDED.recommended_platforms, "
                        " extra=EXCLUDED.extra, last_seen_at=NOW() "
                        "RETURNING hot_id"
                    ),
                    {
                        "pf": platform,
                        "sid": source_id,
                        "ti": item.get("title") or "",
                        "ct": item.get("content") or "",
                        "url": item.get("url") or "",
                        "vurl": item.get("video_url") or "",
                        "un": item.get("username") or "",
                        "hv": int(item.get("heat_value") or 0),
                        "lk": int(item.get("likes_count") or 0),
                        "rt": int(item.get("retweets_count") or 0),
                        "rp": int(item.get("replies_count") or 0),
                        "vw": int(item.get("views_count") or 0),
                        "sk": item.get("source_keyword") or "",
                        "cat": item.get("category") or "",
                        "iv": bool(item.get("is_viral") or False),
                        "ifav": bool(item.get("is_favorited") or False),
                        "idbl": bool(item.get("is_disabled") or False),
                        "rp_plat": rec_platforms,
                        "ouid": item.get("owner_user_id"),
                        "ex": extra,
                    },
                )
                row = rows.fetchone()
                return int(row[0]) if row else None
        except Exception as e:
            logger.warning(f"[HotItemsStore] upsert failed: {e}")
            return None

    async def list_hot_items(
        self,
        platform: Optional[str] = None,
        keyword: Optional[str] = None,
        only_viral: Optional[bool] = None,
        only_favorited: Optional[bool] = None,
        exclude_disabled: bool = True,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """列表查询（多条件过滤，按热度降序）"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            sql = "SELECT * FROM hot_items WHERE 1=1"
            params: Dict[str, Any] = {"limit": limit}
            if platform:
                sql += " AND platform = :pf"
                params["pf"] = platform
            if keyword:
                sql += " AND (title ILIKE :kw OR content ILIKE :kw)"
                params["kw"] = f"%{keyword}%"
            if only_viral is not None:
                sql += " AND is_viral = :iv"
                params["iv"] = only_viral
            if only_favorited is not None:
                sql += " AND is_favorited = :ifav"
                params["ifav"] = only_favorited
            if exclude_disabled:
                sql += " AND is_disabled = FALSE"
            sql += " ORDER BY heat_value DESC LIMIT :limit"
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[HotItemsStore] list_hot_items failed: {e}")
            return []

    async def list_recent(
        self, hours: int = 1, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """列出最近 N 小时的热点（按 last_seen_at 过滤，热度降序）"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT * FROM hot_items "
                        "WHERE last_seen_at >= NOW() - (:hours || ' hours')::INTERVAL "
                        "ORDER BY heat_value DESC LIMIT :lim"
                    ),
                    {"hours": str(int(hours)), "lim": limit},
                )
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[HotItemsStore] list_recent failed: {e}")
            return []

    async def get_hot_item(self, hot_id: int) -> Optional[Dict[str, Any]]:
        """按主键获取单条热点"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM hot_items WHERE hot_id = :hid"),
                    {"hid": int(hot_id)},
                )
                row = rows.fetchone()
                return self._row_to_dict(row) if row else None
        except Exception as e:
            logger.warning(f"[HotItemsStore] get_hot_item failed: {e}")
            return None

    async def get_history_samples(
        self, hotspot_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """获取热点历史热度采样

        hot_items 表只保留当前热度（不存历史曲线），因此这里返回单条最新采样，
        供 HeatPredictor 等模块降级使用（原 hotpoint_history 表同样未创建）。
        """
        try:
            hid = int(hotspot_id)
        except (TypeError, ValueError):
            return []
        item = await self.get_hot_item(hid)
        if not item:
            return []
        ts = item.get("last_seen_at") or datetime.utcnow().isoformat()
        return [{"timestamp": str(ts), "heat_value": float(item.get("heat_value") or 0)}]

    async def mark_viral(self, hot_id: int, is_viral: bool = True) -> bool:
        return await self._update_flag(hot_id, "is_viral", is_viral)

    async def mark_favorited(self, hot_id: int, is_favorited: bool = True) -> bool:
        return await self._update_flag(hot_id, "is_favorited", is_favorited)

    async def mark_disabled(self, hot_id: int, is_disabled: bool = True) -> bool:
        return await self._update_flag(hot_id, "is_disabled", is_disabled)

    async def _update_flag(self, hot_id: int, field: str, value: bool) -> bool:
        # field 由本类内部白名单传入，安全拼接
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(f"UPDATE hot_items SET {field} = :val WHERE hot_id = :hid"),
                    {"val": bool(value), "hid": int(hot_id)},
                )
            return True
        except Exception as e:
            logger.warning(f"[HotItemsStore] update {field} failed: {e}")
            return False

    def _row_to_dict(self, row) -> Dict[str, Any]:
        """行转 dict，兼容旧字段名（id/description）"""
        # 字段顺序与建表一致，索引 0-22
        try:
            rec_raw = row[18]
            if rec_raw:
                recommended_platforms = (
                    json.loads(rec_raw) if isinstance(rec_raw, str) else rec_raw
                )
            else:
                recommended_platforms = []
        except Exception:
            recommended_platforms = []
        try:
            ex_raw = row[22]
            if ex_raw:
                extra = json.loads(ex_raw) if isinstance(ex_raw, str) else ex_raw
            else:
                extra = {}
        except Exception:
            extra = {}
        return {
            "hot_id": row[0],
            "id": row[0],  # 兼容旧字段名
            "platform": row[1],
            "source_id": row[2],
            "title": row[3],
            "content": row[4],
            "description": row[4],  # 兼容旧字段名
            "url": row[5],
            "video_url": row[6],
            "username": row[7],
            "heat_value": int(row[8] or 0),
            "likes_count": int(row[9] or 0),
            "retweets_count": int(row[10] or 0),
            "replies_count": int(row[11] or 0),
            "views_count": int(row[12] or 0),
            "source_keyword": row[13],
            "category": row[14],
            "is_viral": row[15],
            "is_favorited": row[16],
            "is_disabled": row[17],
            "recommended_platforms": recommended_platforms,
            "first_seen_at": str(row[19]) if row[19] else None,
            "last_seen_at": str(row[20]) if row[20] else None,
            "owner_user_id": row[21],
            "extra": extra,
        }


# ============ 单例 ============
_store: Optional[HotItemsStore] = None


def get_hot_items_store() -> HotItemsStore:
    global _store
    if _store is None:
        _store = HotItemsStore()
    return _store
