# -*- coding: utf-8 -*-
"""
算力计费体系服务

核心职责：
1. 算力账户管理（充值/扣减/查询余额）
2. 算力消耗记录（按功能类型计费）
3. 算力套餐管理
4. 管道收益计算（代理模式）

参考：知了系统的算力机制（1元=1万算力币）
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 算力消耗标准（单位：算力币）
COMPUTE_COSTS = {
    "mixcut_video": 1500,       # 混剪视频 0.15元
    "digital_human": 8000,      # 数字人克隆视频 0.8元
    "text_to_image": 500,       # 文生图 0.05元
    "ai_reply": 10,             # AI 回复 0.001元
    "ai_article": 100,          # AI 文章 0.01元
    "ai_script": 50,            # AI 文案 0.005元
    "video_breakdown": 200,     # 视频拆解 0.02元
}

# 1元 = 10000 算力币
YUAN_TO_COMPUTE = 10000


class ComputeService:
    """算力计费服务（单例）"""

    _ensured = False
    _instance = None

    def __init__(self):
        self._accounts: Dict[str, Dict] = {}

    @classmethod
    def get_instance(cls) -> "ComputeService":
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
        """创建 compute_account / compute_transaction 表"""
        if ComputeService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS compute_account ("
                        "  id SERIAL PRIMARY KEY,"
                        "  account_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  owner_user_id VARCHAR(64) NOT NULL,"
                        "  balance BIGINT DEFAULT 0,"
                        "  total_recharged BIGINT DEFAULT 0,"
                        "  total_consumed BIGINT DEFAULT 0,"
                        "  account_type VARCHAR(20) DEFAULT 'normal',"
                        "  status VARCHAR(20) DEFAULT 'active',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS compute_transaction ("
                        "  id SERIAL PRIMARY KEY,"
                        "  tx_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  account_id VARCHAR(64) NOT NULL,"
                        "  type VARCHAR(20) NOT NULL,"
                        "  amount BIGINT NOT NULL,"
                        "  balance_after BIGINT DEFAULT 0,"
                        "  description VARCHAR(500) DEFAULT '',"
                        "  related_resource VARCHAR(255) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_compute_tx_account "
                        "ON compute_transaction(account_id, created_at)"
                    )
                )

            ComputeService._ensured = True
            logger.info("[Compute] 表创建完成")
        except Exception as e:
            logger.warning(f"[Compute] 建表失败(非致命): {e}")

    async def create_account(
        self,
        owner_user_id: str,
        initial_balance: int = 0,
        account_type: str = "normal",
    ) -> Dict[str, Any]:
        """创建算力账户"""
        account_id = f"comp_{uuid.uuid4().hex[:10]}"
        now = int(time.time())

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO compute_account "
                        "(account_id, owner_user_id, balance, total_recharged, account_type, "
                        "status, created_at, updated_at) "
                        "VALUES (:aid, :owner, :bal, :recharged, :type, 'active', :now, :now)"
                    ),
                    {
                        "aid": account_id,
                        "owner": owner_user_id,
                        "bal": initial_balance,
                        "recharged": initial_balance,
                        "type": account_type,
                        "now": now,
                    },
                )

            self._accounts[account_id] = {
                "account_id": account_id,
                "owner_user_id": owner_user_id,
                "balance": initial_balance,
            }

            logger.info(f"[Compute] 账户创建: {account_id} (余额: {initial_balance})")
            return {"ok": True, "account_id": account_id}
        except Exception as e:
            logger.warning(f"[Compute] 创建账户失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def recharge(
        self,
        account_id: str,
        amount: int,
        description: str = "",
    ) -> Dict[str, Any]:
        """充值算力"""
        if amount <= 0:
            return {"ok": False, "reason": "充值金额必须大于0"}

        now = int(time.time())
        tx_id = f"tx_{uuid.uuid4().hex[:10]}"

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                # 更新余额
                await conn.execute(
                    sql_text(
                        "UPDATE compute_account SET balance = balance + :amount, "
                        "total_recharged = total_recharged + :amount, updated_at = :now "
                        "WHERE account_id = :aid AND status = 'active'"
                    ),
                    {"amount": amount, "now": now, "aid": account_id},
                )

                # 获取新余额
                row = await conn.execute(
                    sql_text("SELECT balance FROM compute_account WHERE account_id = :aid"),
                    {"aid": account_id},
                )
                result = row.fetchone()
                if not result:
                    return {"ok": False, "reason": "账户不存在"}
                new_balance = result[0]

                # 记录交易
                await conn.execute(
                    sql_text(
                        "INSERT INTO compute_transaction "
                        "(tx_id, account_id, type, amount, balance_after, description, created_at) "
                        "VALUES (:tid, :aid, 'recharge', :amount, :bal, :desc, :now)"
                    ),
                    {
                        "tid": tx_id,
                        "aid": account_id,
                        "amount": amount,
                        "bal": new_balance,
                        "desc": description or f"充值 {amount} 算力币",
                        "now": now,
                    },
                )

            logger.info(f"[Compute] 充值: {account_id} +{amount} (余额: {new_balance})")
            return {"ok": True, "tx_id": tx_id, "new_balance": new_balance}
        except Exception as e:
            logger.warning(f"[Compute] 充值失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def consume(
        self,
        account_id: str,
        resource_type: str,
        amount: Optional[int] = None,
        description: str = "",
        related_resource: str = "",
    ) -> Dict[str, Any]:
        """消耗算力"""
        cost = amount or COMPUTE_COSTS.get(resource_type, 0)
        if cost <= 0:
            return {"ok": False, "reason": f"未知资源类型: {resource_type}"}

        now = int(time.time())
        tx_id = f"tx_{uuid.uuid4().hex[:10]}"

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                # 检查余额
                row = await conn.execute(
                    sql_text("SELECT balance FROM compute_account WHERE account_id = :aid"),
                    {"aid": account_id},
                )
                result = row.fetchone()
                if not result:
                    return {"ok": False, "reason": "账户不存在"}
                current_balance = result[0]

                if current_balance < cost:
                    return {"ok": False, "reason": f"余额不足 (需要{cost}, 余额{current_balance})"}

                # 扣减
                new_balance = current_balance - cost
                await conn.execute(
                    sql_text(
                        "UPDATE compute_account SET balance = :bal, "
                        "total_consumed = total_consumed + :cost, updated_at = :now "
                        "WHERE account_id = :aid"
                    ),
                    {"bal": new_balance, "cost": cost, "now": now, "aid": account_id},
                )

                # 记录交易
                await conn.execute(
                    sql_text(
                        "INSERT INTO compute_transaction "
                        "(tx_id, account_id, type, amount, balance_after, description, "
                        "related_resource, created_at) "
                        "VALUES (:tid, :aid, 'consume', :cost, :bal, :desc, :res, :now)"
                    ),
                    {
                        "tid": tx_id,
                        "aid": account_id,
                        "cost": cost,
                        "bal": new_balance,
                        "desc": description or f"消耗: {resource_type}",
                        "res": related_resource,
                        "now": now,
                    },
                )

            return {"ok": True, "tx_id": tx_id, "cost": cost, "new_balance": new_balance}
        except Exception as e:
            logger.warning(f"[Compute] 消耗失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def get_balance(self, account_id: str) -> Dict[str, Any]:
        """查询余额"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.connect() as conn:
                row = await conn.execute(
                    sql_text("SELECT * FROM compute_account WHERE account_id = :aid"),
                    {"aid": account_id},
                )
                result = row.fetchone()
                if not result:
                    return {"ok": False, "reason": "账户不存在"}

                data = dict(result._mapping)
                return {
                    "ok": True,
                    "account_id": account_id,
                    "balance": data["balance"],
                    "balance_yuan": data["balance"] / YUAN_TO_COMPUTE,
                    "total_recharged": data["total_recharged"],
                    "total_consumed": data["total_consumed"],
                }
        except Exception as e:
            logger.warning(f"[Compute] 查询余额失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def get_transactions(
        self,
        account_id: str,
        limit: int = 50,
    ) -> List[Dict]:
        """获取交易记录"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT * FROM compute_transaction WHERE account_id = :aid "
                        "ORDER BY created_at DESC LIMIT :limit"
                    ),
                    {"aid": account_id, "limit": limit},
                )
            return [dict(r._mapping) for r in rows.fetchall()]
        except Exception:
            return []

    async def yuan_to_compute(self, yuan: float) -> int:
        """元转算力币"""
        return int(yuan * YUAN_TO_COMPUTE)

    async def compute_to_yuan(self, compute: int) -> float:
        """算力币转元"""
        return compute / YUAN_TO_COMPUTE


def get_compute_service() -> ComputeService:
    return ComputeService.get_instance()
