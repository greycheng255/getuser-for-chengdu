# -*- coding: utf-8 -*-
"""
营销素材库

对应 PRD 5.2 营销信息植入 - 营销素材库：
管理 LOGO / 二维码 / 引流链接 / 活动信息，供视频后处理和文案植入使用。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)


def _get_engine():
    """获取异步数据库引擎（公共方法，消除重复导入）"""
    from database.db_session import get_async_engine
    return get_async_engine(config.SAVE_DATA_OPTION)


class MaterialType(str, Enum):
    LOGO = "logo"  # 品牌 LOGO（图片）
    QR_CODE = "qr_code"  # 二维码（图片）
    LINK = "link"  # 引流链接
    SLOGAN = "slogan"  # 品牌口号 / 标语
    EVENT = "event"  # 活动信息
    CONTACT = "contact"  # 联系方式


@dataclass
class MarketingMaterial:
    id: Optional[int] = None
    name: str = ""
    material_type: str = MaterialType.SLOGAN.value
    content: str = ""  # 文本内容 / 文件路径
    file_path: str = ""  # 素材文件路径（LOGO/QR 等图片）
    link_url: str = ""  # 引流链接
    position: str = "bottom-right"  # 水印位置
    is_active: bool = True
    created_at: Optional[datetime] = None


class MaterialLibrary:
    """营销素材库（异步 + PostgreSQL）"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    async def ensure_table(self):
        if MaterialLibrary._ensured:
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
                        "CREATE TABLE IF NOT EXISTS marketing_materials ("
                        "  id SERIAL PRIMARY KEY,"
                        "  name VARCHAR(128),"
                        "  material_type VARCHAR(32),"
                        "  content TEXT,"
                        "  file_path TEXT,"
                        "  link_url VARCHAR(512),"
                        "  position VARCHAR(32) DEFAULT 'bottom-right',"
                        "  is_active BOOLEAN DEFAULT TRUE,"
                        "  created_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
            MaterialLibrary._ensured = True
        except Exception as e:
            logger.warning(f"[Material] 建表失败: {e}")

    async def add(self, material: MarketingMaterial) -> Optional[int]:
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return None
            async with engine.begin() as conn:
                row = await conn.execute(
                    sql_text(
                        "INSERT INTO marketing_materials "
                        "(name, material_type, content, file_path, link_url, position, is_active) "
                        "VALUES (:n, :t, :c, :f, :l, :p, :a) RETURNING id"
                    ),
                    {
                        "n": material.name,
                        "t": material.material_type,
                        "c": material.content,
                        "f": material.file_path,
                        "l": material.link_url,
                        "p": material.position,
                        "a": material.is_active,
                    },
                )
                r = row.fetchone()
                return r[0] if r else None
        except Exception as e:
            logger.error(f"[Material] 添加素材失败: {e}")
            return None

    async def list_materials(
        self, material_type: str = "", only_active: bool = True
    ) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return []
            conditions = []
            params: Dict[str, Any] = {}
            if material_type:
                conditions.append("material_type=:t")
                params["t"] = material_type
            if only_active:
                conditions.append("is_active=TRUE")
            sql = "SELECT id, name, material_type, content, file_path, link_url, position, is_active, created_at FROM marketing_materials"
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY id DESC"
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                return [
                    {
                        "id": r[0],
                        "name": r[1],
                        "material_type": r[2],
                        "content": r[3],
                        "file_path": r[4],
                        "link_url": r[5],
                        "position": r[6],
                        "is_active": r[7],
                        "created_at": str(r[8]) if r[8] else None,
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[Material] 查询失败: {e}")
            return []

    async def get_active_slogans(self) -> List[str]:
        """获取所有活跃的品牌口号（供文案植入用）"""
        materials = await self.list_materials(material_type=MaterialType.SLOGAN.value)
        return [m["content"] for m in materials if m["content"]]

    async def get_active_link(self) -> Optional[str]:
        """获取活跃的引流链接"""
        materials = await self.list_materials(material_type=MaterialType.LINK.value)
        return materials[0]["link_url"] if materials else None

    async def delete(self, material_id: int) -> bool:
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text("DELETE FROM marketing_materials WHERE id=:i"),
                    {"i": material_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[Material] 删除失败: {e}")
            return False


_library: Optional[MaterialLibrary] = None


def get_material_library() -> MaterialLibrary:
    global _library
    if _library is None:
        _library = MaterialLibrary()
    return _library
