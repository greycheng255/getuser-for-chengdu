# -*- coding: utf-8 -*-
"""
设备管理服务

核心职责：
1. 设备注册与绑定（手机/电脑）
2. 设备状态监控（在线/离线/功能界面）
3. 设备功能分配（哪些功能在哪些设备上运行）
4. 设备心跳检测

参考：知了系统的设备管理功能
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 设备心跳超时（秒）
HEARTBEAT_TIMEOUT = 300  # 5分钟


class DeviceService:
    """设备管理服务（单例）"""

    _ensured = False
    _instance = None

    def __init__(self):
        self._devices: Dict[str, Dict] = {}

    @classmethod
    def get_instance(cls) -> "DeviceService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """创建 device 表"""
        if DeviceService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS device ("
                        "  id SERIAL PRIMARY KEY,"
                        "  device_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  device_name VARCHAR(255) DEFAULT '',"
                        "  device_type VARCHAR(20) NOT NULL,"
                        "  platform VARCHAR(50) DEFAULT '',"
                        "  account_bound VARCHAR(255) DEFAULT '',"
                        "  status VARCHAR(20) DEFAULT 'offline',"
                        "  last_heartbeat BIGINT DEFAULT 0,"
                        "  enabled_features TEXT DEFAULT '[]',"
                        "  owner_user_id VARCHAR(64) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0"
                        ")"
                    )
                )

            DeviceService._ensured = True
            logger.info("[Device] 表创建完成")
        except Exception as e:
            logger.warning(f"[Device] 建表失败(非致命): {e}")

    async def register_device(
        self,
        device_name: str,
        device_type: str,
        platform: str = "",
        account_bound: str = "",
        enabled_features: Optional[List[str]] = None,
        owner_user_id: str = "",
    ) -> Dict[str, Any]:
        """注册设备"""
        device_id = f"dev_{uuid.uuid4().hex[:10]}"
        now = int(time.time())

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO device "
                        "(device_id, device_name, device_type, platform, account_bound, "
                        "status, last_heartbeat, enabled_features, owner_user_id, created_at, updated_at) "
                        "VALUES (:did, :name, :type, :plat, :account, 'online', :now, :features, :owner, :now, :now)"
                    ),
                    {
                        "did": device_id,
                        "name": device_name,
                        "type": device_type,
                        "plat": platform,
                        "account": account_bound,
                        "now": now,
                        "features": str(enabled_features or []),
                        "owner": owner_user_id,
                    },
                )

            self._devices[device_id] = {
                "device_id": device_id,
                "device_name": device_name,
                "device_type": device_type,
                "status": "online",
            }

            logger.info(f"[Device] 设备注册: {device_id} ({device_name})")
            return {"ok": True, "device_id": device_id}
        except Exception as e:
            logger.warning(f"[Device] 注册失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def heartbeat(self, device_id: str) -> Dict[str, Any]:
        """设备心跳"""
        now = int(time.time())

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE device SET last_heartbeat = :now, status = 'online', updated_at = :now "
                        "WHERE device_id = :did"
                    ),
                    {"now": now, "did": device_id},
                )

            return {"ok": True, "timestamp": now}
        except Exception as e:
            logger.warning(f"[Device] 心跳失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def list_devices(self, owner_user_id: str = "") -> List[Dict]:
        """列出设备"""
        now = int(time.time())

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM device ORDER BY created_at DESC"),
                )

            devices = []
            for r in rows.fetchall():
                data = dict(r._mapping)
                # 检查心跳超时
                if now - data.get("last_heartbeat", 0) > HEARTBEAT_TIMEOUT:
                    data["status"] = "offline"
                devices.append(data)

            return devices
        except Exception:
            return []

    async def get_device(self, device_id: str) -> Optional[Dict]:
        """获取设备详情"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.connect() as conn:
                row = await conn.execute(
                    sql_text("SELECT * FROM device WHERE device_id = :did"),
                    {"did": device_id},
                )
                result = row.fetchone()
                return dict(result._mapping) if result else None
        except Exception:
            return None

    async def update_device_features(
        self,
        device_id: str,
        enabled_features: List[str],
    ) -> bool:
        """更新设备功能"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE device SET enabled_features = :features, updated_at = :now "
                        "WHERE device_id = :did"
                    ),
                    {"features": str(enabled_features), "now": int(time.time()), "did": device_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[Device] 更新功能失败: {e}")
            return False


def get_device_service() -> DeviceService:
    return DeviceService.get_instance()
