# -*- coding: utf-8 -*-
"""
视频资产库（video_assets 表）

阶段二 P2-3（部分）：补齐 PRD 视频资产沉淀缺口。
将 batch_video_generator / prompt_storyboard_pipeline 生成成功的视频
持久化到 video_assets 表，便于后续人工复核 / 归档 / 检索复用。
原先生成结果只在内存 BatchVideoTask.results 里，重启即丢失。

设计：
- PostgreSQL 异步（复用 database.db_session.get_async_engine）
- 单例 get_video_asset_library()
- 提供 ensure_table / save_asset / list_assets / get_asset / update_status / delete_asset

注意：
- config_id 字段类型采用 VARCHAR(64)，与 video_generation_configs.config_id
  实际类型保持一致（任务文档写 INT，但既有表 config_id 是 VARCHAR(64)，
  例如 'preset_short_vertical'），以确保关联可真正成立、不破坏已有功能。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class VideoAssetLibrary:
    """视频资产库服务"""

    TABLE_NAME = "video_assets"
    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if VideoAssetLibrary._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS video_assets ("
                        "  asset_id SERIAL PRIMARY KEY,"
                        "  title VARCHAR(255),"
                        "  prompt TEXT,"
                        "  video_url TEXT NOT NULL,"
                        "  thumbnail_url TEXT,"
                        "  duration INT,"
                        "  resolution VARCHAR(16),"
                        "  aspect_ratio VARCHAR(16),"
                        "  source_hotspot_id BIGINT,"
                        "  source_post_url TEXT,"
                        "  config_id VARCHAR(64),"
                        "  owner_user_id BIGINT,"
                        "  status VARCHAR(32) DEFAULT 'ready',"
                        "  created_at TIMESTAMPTZ DEFAULT NOW())"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_video_assets_hotspot "
                        "ON video_assets(source_hotspot_id)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_video_assets_status "
                        "ON video_assets(status)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_video_assets_owner "
                        "ON video_assets(owner_user_id)"
                    )
                )
            VideoAssetLibrary._ensured = True
        except Exception as e:
            logger.warning(f"[VideoAssetLibrary] ensure_table failed: {e}")

    async def save_asset(
        self,
        video_url: str,
        title: str = "",
        prompt: str = "",
        thumbnail_url: Optional[str] = None,
        duration: Optional[int] = None,
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        source_hotspot_id: Optional[int] = None,
        source_post_url: Optional[str] = None,
        config_id: Optional[str] = None,
        owner_user_id: Optional[int] = None,
        status: str = "ready",
    ) -> Optional[int]:
        """持久化一条视频资产，返回 asset_id（失败返回 None）"""
        if not video_url:
            return None
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                rows = await conn.execute(
                    sql_text(
                        "INSERT INTO video_assets "
                        "(title, prompt, video_url, thumbnail_url, duration, resolution, "
                        " aspect_ratio, source_hotspot_id, source_post_url, config_id, "
                        " owner_user_id, status) "
                        "VALUES (:ti, :pr, :vurl, :thumb, :dur, :res, :ar, :shid, :spurl, :cid, :ouid, :st) "
                        "RETURNING asset_id"
                    ),
                    {
                        "ti": title or "",
                        "pr": prompt or "",
                        "vurl": video_url,
                        "thumb": thumbnail_url,
                        "dur": int(duration) if duration is not None else None,
                        "res": resolution,
                        "ar": aspect_ratio,
                        "shid": int(source_hotspot_id) if source_hotspot_id is not None else None,
                        "spurl": source_post_url,
                        "cid": config_id,
                        "ouid": int(owner_user_id) if owner_user_id is not None else None,
                        "st": status or "ready",
                    },
                )
                row = rows.fetchone()
                return int(row[0]) if row else None
        except Exception as e:
            logger.warning(f"[VideoAssetLibrary] save_asset failed: {e}")
            return None

    async def list_assets(
        self,
        owner_user_id: Optional[int] = None,
        source_hotspot_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            sql = "SELECT * FROM video_assets WHERE 1=1"
            params: Dict[str, Any] = {"limit": limit, "offset": offset}
            if owner_user_id is not None:
                sql += " AND owner_user_id = :ouid"
                params["ouid"] = owner_user_id
            if source_hotspot_id is not None:
                sql += " AND source_hotspot_id = :shid"
                params["shid"] = source_hotspot_id
            if status:
                sql += " AND status = :st"
                params["st"] = status
            sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[VideoAssetLibrary] list_assets failed: {e}")
            return []

    async def get_asset(self, asset_id: int) -> Optional[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM video_assets WHERE asset_id = :aid"),
                    {"aid": int(asset_id)},
                )
                row = rows.fetchone()
                return self._row_to_dict(row) if row else None
        except Exception as e:
            logger.warning(f"[VideoAssetLibrary] get_asset failed: {e}")
            return None

    async def update_status(self, asset_id: int, status: str) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE video_assets SET status = :st WHERE asset_id = :aid"
                    ),
                    {"st": status, "aid": int(asset_id)},
                )
            return True
        except Exception as e:
            logger.warning(f"[VideoAssetLibrary] update_status failed: {e}")
            return False

    async def delete_asset(self, asset_id: int) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text("DELETE FROM video_assets WHERE asset_id = :aid"),
                    {"aid": int(asset_id)},
                )
            return True
        except Exception as e:
            logger.warning(f"[VideoAssetLibrary] delete_asset failed: {e}")
            return False

    def _row_to_dict(self, row) -> Dict[str, Any]:
        # 字段顺序与建表一致，索引 0-12
        return {
            "asset_id": row[0],
            "title": row[1],
            "prompt": row[2],
            "video_url": row[3],
            "thumbnail_url": row[4],
            "duration": row[5],
            "resolution": row[6],
            "aspect_ratio": row[7],
            "source_hotspot_id": row[8],
            "source_post_url": row[9],
            "config_id": row[10],
            "owner_user_id": row[11],
            "status": row[12],
            "created_at": str(row[13]) if len(row) > 13 and row[13] else None,
        }


# ============ 单例 ============
_library: Optional[VideoAssetLibrary] = None


def get_video_asset_library() -> VideoAssetLibrary:
    global _library
    if _library is None:
        _library = VideoAssetLibrary()
    return _library
