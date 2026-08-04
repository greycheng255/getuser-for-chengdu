# -*- coding: utf-8 -*-
"""
系统配置服务(阶段三 P2-7)

将前端 Settings.tsx 的"评分规则"(scoringConfig)和"通知设置"(notificationConfig)
从仅存 localStorage 升级为后端持久化。

设计:
1. sys_config 表: KV 结构,config_value 存 JSON 字符串
   - owner_user_id 为 NULL 表示全局配置,非 NULL 表示用户级配置
   - config_type 用于按类型筛选(scoring / notification / 其他)
2. 提供 get/set/list/delete 四个核心方法
3. 单例 get_system_config_service()

对应 PRD: 评分规则 / 通知设置后端持久化,前后端统一以数据库为准。
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)


def _get_engine():
    """获取异步数据库引擎（公共方法，消除重复导入）"""
    from database.db_session import get_async_engine
    return get_async_engine(config.SAVE_DATA_OPTION)


class SystemConfigService:
    """系统配置服务(异步 PostgreSQL)"""

    def __init__(self):
        self._table_ready = False

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    async def ensure_table(self) -> None:
        """创建 sys_config 表(若不存在)"""
        if SystemConfigService._ensured:
            return
        if self._table_ready:
            return
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return
            async with engine.begin() as conn:
                # 注意: config_key 单独不设 UNIQUE,因为全局(NULL)和用户级(非 NULL)
                # 允许同名 key 共存。改用两个部分唯一索引保证全局/用户级各自唯一。
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS sys_config ("
                        "  config_id SERIAL PRIMARY KEY,"
                        "  config_key VARCHAR(128) NOT NULL,"
                        "  config_value TEXT DEFAULT '',"
                        "  config_type VARCHAR(32) DEFAULT '',"
                        "  owner_user_id BIGINT,"
                        "  updated_at TIMESTAMPTZ DEFAULT NOW()"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_sys_config_type_owner "
                        "ON sys_config(config_type, owner_user_id)"
                    )
                )
                # 全局配置唯一索引(owner_user_id IS NULL)
                await conn.execute(
                    sql_text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_sys_config_key_global "
                        "ON sys_config(config_key) WHERE owner_user_id IS NULL"
                    )
                )
                # 用户级配置唯一索引(owner_user_id IS NOT NULL)
                await conn.execute(
                    sql_text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_sys_config_key_user "
                        "ON sys_config(config_key, owner_user_id) WHERE owner_user_id IS NOT NULL"
                    )
                )
            self._table_ready = True
            SystemConfigService._ensured = True
            logger.info("[SystemConfigService] sys_config 表已就绪")
        except Exception as e:
            logger.warning(f"[SystemConfigService] ensure_table failed: {e}")

    async def get_config(self, key: str, user_id: Optional[int] = None) -> Optional[Any]:
        """读取配置值(自动 JSON 反序列化)

        Args:
            key: 配置键(如 scoring / notification)
            user_id: 用户 ID。None=全局配置;指定=用户级配置
        Returns:
            配置值(反序列化后的对象);不存在返回 None
        """
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return None
            async with engine.connect() as conn:
                if user_id is None:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT config_value FROM sys_config "
                            "WHERE config_key = :k AND owner_user_id IS NULL"
                        ),
                        {"k": key},
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT config_value FROM sys_config "
                            "WHERE config_key = :k AND owner_user_id = :u"
                        ),
                        {"k": key, "u": user_id},
                    )
                r = rows.fetchone()
                if r is None or r[0] is None:
                    return None
                try:
                    return json.loads(r[0])
                except (json.JSONDecodeError, TypeError):
                    return r[0]
        except Exception as e:
            logger.warning(f"[SystemConfigService] get_config failed: {e}")
            return None

    async def set_config(
        self,
        key: str,
        value: Any,
        user_id: Optional[int] = None,
        config_type: str = "",
    ) -> bool:
        """写入配置值(自动 JSON 序列化,UPSERT)

        Args:
            key: 配置键
            value: 配置值(任意可 JSON 序列化的对象)
            user_id: 用户 ID。None=全局配置;指定=用户级配置
            config_type: 配置类型(如 scoring / notification)
        Returns:
            是否成功
        """
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return False
            # 序列化为 JSON 字符串
            try:
                value_str = json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                value_str = str(value)
            async with engine.begin() as conn:
                if user_id is None:
                    # 全局配置: 冲突目标为部分唯一索引 uq_sys_config_key_global
                    await conn.execute(
                        sql_text(
                            "INSERT INTO sys_config (config_key, config_value, config_type, owner_user_id, updated_at) "
                            "VALUES (:k, :v, :t, NULL, NOW()) "
                            "ON CONFLICT (config_key) WHERE owner_user_id IS NULL "
                            "DO UPDATE SET config_value = EXCLUDED.config_value, "
                            "  config_type = EXCLUDED.config_type, "
                            "  updated_at = NOW()"
                        ),
                        {"k": key, "v": value_str, "t": config_type},
                    )
                else:
                    # 用户级配置: 冲突目标为部分唯一索引 uq_sys_config_key_user
                    await conn.execute(
                        sql_text(
                            "INSERT INTO sys_config (config_key, config_value, config_type, owner_user_id, updated_at) "
                            "VALUES (:k, :v, :t, :u, NOW()) "
                            "ON CONFLICT (config_key, owner_user_id) WHERE owner_user_id IS NOT NULL "
                            "DO UPDATE SET config_value = EXCLUDED.config_value, "
                            "  config_type = EXCLUDED.config_type, "
                            "  updated_at = NOW()"
                        ),
                        {"k": key, "v": value_str, "t": config_type, "u": user_id},
                    )
            return True
        except Exception as e:
            logger.warning(f"[SystemConfigService] set_config failed: {e}")
            return False

    async def list_configs(
        self,
        config_type: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """列出配置(可按 config_type / user_id 筛选)"""
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return []
            sql = (
                "SELECT config_id, config_key, config_value, config_type, owner_user_id, updated_at "
                "FROM sys_config WHERE 1=1"
            )
            params: Dict[str, Any] = {}
            if config_type is not None:
                sql += " AND config_type = :t"
                params["t"] = config_type
            if user_id is None:
                sql += " AND owner_user_id IS NULL"
            else:
                sql += " AND owner_user_id = :u"
                params["u"] = user_id
            sql += " ORDER BY config_key"
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                result: List[Dict[str, Any]] = []
                for r in rows.fetchall():
                    try:
                        value = json.loads(r[2]) if r[2] else None
                    except (json.JSONDecodeError, TypeError):
                        value = r[2]
                    result.append({
                        "config_id": r[0],
                        "config_key": r[1],
                        "config_value": value,
                        "config_type": r[3] or "",
                        "owner_user_id": r[4],
                        "updated_at": str(r[5]) if r[5] else None,
                    })
                return result
        except Exception as e:
            logger.warning(f"[SystemConfigService] list_configs failed: {e}")
            return []

    async def delete_config(self, key: str, user_id: Optional[int] = None) -> bool:
        """删除配置"""
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return False
            async with engine.begin() as conn:
                if user_id is None:
                    result = await conn.execute(
                        sql_text(
                            "DELETE FROM sys_config WHERE config_key = :k AND owner_user_id IS NULL"
                        ),
                        {"k": key},
                    )
                else:
                    result = await conn.execute(
                        sql_text(
                            "DELETE FROM sys_config WHERE config_key = :k AND owner_user_id = :u"
                        ),
                        {"k": key, "u": user_id},
                    )
                return (result.rowcount or 0) > 0
        except Exception as e:
            logger.warning(f"[SystemConfigService] delete_config failed: {e}")
            return False


# ============ 单例 ============
_service: Optional[SystemConfigService] = None


def get_system_config_service() -> SystemConfigService:
    global _service
    if _service is None:
        _service = SystemConfigService()
    return _service
