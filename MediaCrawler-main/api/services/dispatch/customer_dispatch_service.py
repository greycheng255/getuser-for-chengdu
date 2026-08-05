# -*- coding: utf-8 -*-
"""
客户分配调度核心服务

业务场景：
- 1000 个客户，10 个抖音账号
- 账号1 发 0001-0020，账号2 接着 0021-0058，账号3 接着 0059-0088 ...
- 每个账号已回复的客户，下个账号去发时跳过（去重）
- 漏发/未回复的客户由后续账号补发（无遗漏 + 全覆盖）

核心模型：
- customer_dispatch_plan: 分配计划（一次批量分配的元数据）
- customer_dispatch_account: 账号分配（每个账号的区间）
- customer_dispatch_record: 单个客户分配记录（去重核心表）

调度算法（get_next_for_account）：
1. 优先级1：账号自己区间内 status=pending 的客户
2. 优先级2：其他账号区间内 status=sent 但未回复（漏单补发）
3. 跳过：status=replied（去重）
4. 返回 K 个客户并标记 sent_by_account=N
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CustomerDispatchService:
    """客户分配调度服务（单例）"""

    _ensured = False

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if CustomerDispatchService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                # 1. 分配计划
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS customer_dispatch_plan ("
                        "  id SERIAL PRIMARY KEY,"
                        "  plan_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  name VARCHAR(255) NOT NULL,"
                        "  platform VARCHAR(20) DEFAULT 'douyin',"
                        "  total_customers INTEGER DEFAULT 0,"
                        "  total_accounts INTEGER DEFAULT 0,"
                        "  filter_keywords TEXT DEFAULT '',"
                        "  min_lead_score INTEGER DEFAULT 0,"
                        "  status VARCHAR(20) DEFAULT 'active',"
                        "  owner_user_id VARCHAR(64) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                # 2. 账号分配
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS customer_dispatch_account ("
                        "  id SERIAL PRIMARY KEY,"
                        "  plan_id VARCHAR(64) NOT NULL,"
                        "  account_idx INTEGER NOT NULL,"
                        "  account_alias VARCHAR(255) DEFAULT '',"
                        "  cookie_id VARCHAR(64) DEFAULT '',"
                        "  range_start INTEGER DEFAULT 0,"
                        "  range_end INTEGER DEFAULT 0,"
                        "  batch_size INTEGER DEFAULT 20,"
                        "  total_assigned INTEGER DEFAULT 0,"
                        "  total_sent INTEGER DEFAULT 0,"
                        "  total_replied INTEGER DEFAULT 0,"
                        "  status VARCHAR(20) DEFAULT 'active',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0,"
                        "  UNIQUE(plan_id, account_idx)"
                        ")"
                    )
                )
                # 3. 客户分配记录（去重核心表）
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS customer_dispatch_record ("
                        "  id SERIAL PRIMARY KEY,"
                        "  plan_id VARCHAR(64) NOT NULL,"
                        "  customer_lead_id INTEGER NOT NULL,"
                        "  customer_seq INTEGER NOT NULL,"
                        "  assigned_account_idx INTEGER DEFAULT 0,"
                        "  status VARCHAR(20) DEFAULT 'pending',"
                        "  sent_by_account INTEGER DEFAULT 0,"
                        "  replied_by_account INTEGER DEFAULT 0,"
                        "  sent_at BIGINT DEFAULT 0,"
                        "  replied_at BIGINT DEFAULT 0,"
                        "  contact_log TEXT DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0,"
                        "  UNIQUE(plan_id, customer_lead_id),"
                        "  UNIQUE(plan_id, customer_seq)"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_cdr_plan_status "
                        "ON customer_dispatch_record(plan_id, status, customer_seq)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_cdr_plan_account "
                        "ON customer_dispatch_record(plan_id, assigned_account_idx, status)"
                    )
                )
                # 修改约束：允许重叠区间（同一 seq 可属于多个账号）
                # 旧约束 UNIQUE(plan_id, customer_seq) → 新约束 UNIQUE(plan_id, customer_seq, assigned_account_idx)
                # 同时删除 UNIQUE(plan_id, customer_lead_id)（重叠区同一 lead_id 需多条记录）
                try:
                    await conn.execute(
                        sql_text(
                            "ALTER TABLE customer_dispatch_record "
                            "DROP CONSTRAINT IF EXISTS customer_dispatch_record_plan_id_customer_seq_key"
                        )
                    )
                except Exception:
                    pass  # 约束可能不存在（新表或已删除）
                try:
                    await conn.execute(
                        sql_text(
                            "ALTER TABLE customer_dispatch_record "
                            "DROP CONSTRAINT IF EXISTS customer_dispatch_record_plan_id_customer_lead_id_key"
                        )
                    )
                except Exception:
                    pass  # 约束可能不存在
                try:
                    await conn.execute(
                        sql_text(
                            "ALTER TABLE customer_dispatch_record "
                            "ADD CONSTRAINT customer_dispatch_record_plan_id_seq_account_key "
                            "UNIQUE (plan_id, customer_seq, assigned_account_idx)"
                        )
                    )
                except Exception:
                    pass  # 约束可能已存在
            CustomerDispatchService._ensured = True
            print("[customer_dispatch] 表已就绪")
        except Exception as e:
            logger.warning(f"[customer_dispatch] ensure_table failed: {e}")

    # ==================== 计划 CRUD ====================

    async def create_plan(
        self,
        *,
        name: str,
        platform: str = "douyin",
        filter_keywords: str = "",
        min_lead_score: int = 0,
        account_configs: List[Dict],  # [{account_alias, cookie_id, batch_size}, ...]
        owner_user_id: str = "",
        customer_lead_ids: Optional[List[int]] = None,  # 显式指定客户列表
        custom_ranges: Optional[List[Dict]] = None,  # 手动指定区间（支持重叠）
    ) -> Dict:
        """
        创建分配计划 + 预分配客户到账号

        Args:
            account_configs: 账号配置列表，按顺序对应 account_idx 1..N
                [{"account_alias": "账号1", "cookie_id": "xxx", "batch_size": 20}, ...]
            customer_lead_ids: 显式指定的客户ID列表（按顺序分配 seq 1..N）
                若为 None，则从 customer_lead 表按筛选条件查询
            custom_ranges: 手动指定区间（支持重叠）
                [{"account_idx": 1, "range_start": 1, "range_end": 100},
                 {"account_idx": 2, "range_start": 50, "range_end": 150}]
                若为 None，则按 batch_size 比例自动分配（不重叠）
        """
        await self.ensure_table()
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        now = int(time.time())

        # 1. 获取客户列表
        if customer_lead_ids is None:
            customer_lead_ids = await self._fetch_customer_leads(
                platform=platform, filter_keywords=filter_keywords,
                min_lead_score=min_lead_score, owner_user_id=owner_user_id,
            )

        total_customers = len(customer_lead_ids)
        total_accounts = len(account_configs)
        if total_customers == 0:
            return {"created": False, "reason": "未找到符合条件的客户"}
        if total_accounts == 0:
            return {"created": False, "reason": "至少需要 1 个账号"}

        # 2. 计算每个账号的区间
        if custom_ranges:
            # 手动指定区间（支持重叠）
            ranges: List[Tuple[int, int]] = [None] * total_accounts  # type: ignore
            for cr in custom_ranges:
                idx = int(cr["account_idx"])
                if idx < 1 or idx > total_accounts:
                    return {"created": False, "reason": f"custom_ranges: account_idx {idx} 超出范围(1-{total_accounts})"}
                if int(cr["range_start"]) > int(cr["range_end"]):
                    return {"created": False, "reason": f"custom_ranges: account_idx {idx} 的 range_start > range_end"}
                ranges[idx - 1] = (int(cr["range_start"]), int(cr["range_end"]))
            for i, r in enumerate(ranges):
                if r is None:
                    return {"created": False, "reason": f"custom_ranges: 缺少 account_idx {i+1} 的区间配置"}
            logger.info(f"[customer_dispatch] 使用自定义区间(支持重叠): {ranges} [plan={plan_id}]")
        else:
            # 按 batch_size 比例分配，确保总和 = total_customers
            ranges = self._compute_ranges(total_customers, account_configs)

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                # 创建计划
                await conn.execute(
                    sql_text(
                        "INSERT INTO customer_dispatch_plan "
                        "(plan_id, name, platform, total_customers, total_accounts, "
                        " filter_keywords, min_lead_score, status, owner_user_id, "
                        " created_at, updated_at) "
                        "VALUES (:pid, :name, :pf, :tc, :ta, :fk, :ms, 'active', :ouid, :now, :now)"
                    ),
                    {
                        "pid": plan_id, "name": name, "pf": platform,
                        "tc": total_customers, "ta": total_accounts,
                        "fk": filter_keywords, "ms": min_lead_score,
                        "ouid": owner_user_id, "now": now,
                    },
                )
                # 创建账号分配
                for idx, cfg in enumerate(account_configs, start=1):
                    r_start, r_end = ranges[idx - 1]
                    await conn.execute(
                        sql_text(
                            "INSERT INTO customer_dispatch_account "
                            "(plan_id, account_idx, account_alias, cookie_id, "
                            " range_start, range_end, batch_size, total_assigned, "
                            " total_sent, total_replied, status, created_at, updated_at) "
                            "VALUES (:pid, :idx, :alias, :cid, :rs, :re, :bs, :ta, 0, 0, 'active', :now, :now)"
                        ),
                        {
                            "pid": plan_id, "idx": idx,
                            "alias": cfg.get("account_alias", f"账号{idx}"),
                            "cid": cfg.get("cookie_id", ""),
                            "rs": r_start, "re": r_end,
                            "bs": int(cfg.get("batch_size", 20)),
                            "ta": r_end - r_start + 1,
                            "now": now,
                        },
                    )
                # 创建客户分配记录
                # 批量插入（每 500 条一批，重叠区会有多条记录）
                for batch_start in range(0, total_customers, 500):
                    batch = customer_lead_ids[batch_start: batch_start + 500]
                    values_parts = []
                    params: Dict[str, Any] = {"pid": plan_id, "now": now}
                    rec_idx = 0  # 记录索引（重叠区同一 seq 会有多条记录）
                    for i, lead_id in enumerate(batch):
                        seq = batch_start + i + 1  # 1-based
                        # 找到该 seq 所属的所有账号（支持重叠区间，返回列表）
                        acc_indices = self._find_accounts_for_seq(seq, ranges)
                        for acc_idx in acc_indices:
                            ph_lead = f"l{rec_idx}"
                            ph_seq = f"s{rec_idx}"
                            ph_ai = f"a{rec_idx}"
                            params[ph_lead] = lead_id
                            params[ph_seq] = seq
                            params[ph_ai] = acc_idx
                            values_parts.append(
                                f"(:pid, :{ph_lead}, :{ph_seq}, :{ph_ai}, 'pending', 0, 0, 0, 0, '', :now, :now)"
                            )
                            rec_idx += 1
                    sql = (
                        "INSERT INTO customer_dispatch_record "
                        "(plan_id, customer_lead_id, customer_seq, assigned_account_idx, "
                        " status, sent_by_account, replied_by_account, sent_at, replied_at, "
                        " contact_log, created_at, updated_at) VALUES "
                        + ",".join(values_parts)
                        + " ON CONFLICT (plan_id, customer_seq, assigned_account_idx) DO NOTHING"
                    )
                    await conn.execute(sql_text(sql), params)
        except Exception as e:
            logger.error(f"[customer_dispatch] create_plan failed: {e}")
            return {"created": False, "reason": str(e)}

        return {
            "created": True, "plan_id": plan_id,
            "total_customers": total_customers,
            "total_accounts": total_accounts,
            "ranges": [
                {"account_idx": i + 1, **account_configs[i],
                 "range_start": ranges[i][0], "range_end": ranges[i][1]}
                for i in range(total_accounts)
            ],
        }

    async def list_plans(
        self, *, owner_user_id: str = "", is_admin: bool = False,
        page: int = 1, page_size: int = 20,
    ) -> Dict:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = []
            params: Dict[str, Any] = {}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            async with engine.connect() as conn:
                cnt = await conn.execute(
                    sql_text(f"SELECT COUNT(*) FROM customer_dispatch_plan{where}"), params
                )
                total = int(cnt.fetchone()[0] or 0)
                offset = (page - 1) * page_size
                params["lim"] = page_size
                params["off"] = offset
                rows = await conn.execute(
                    sql_text(
                        f"SELECT plan_id, name, platform, total_customers, total_accounts, "
                        f" filter_keywords, min_lead_score, status, owner_user_id, "
                        f" created_at, updated_at "
                        f"FROM customer_dispatch_plan{where} "
                        f"ORDER BY created_at DESC LIMIT :lim OFFSET :off"
                    ),
                    params,
                )
                items = []
                for r in rows.fetchall():
                    items.append({
                        "plan_id": r[0], "name": r[1], "platform": r[2],
                        "total_customers": r[3], "total_accounts": r[4],
                        "filter_keywords": r[5], "min_lead_score": r[6],
                        "status": r[7], "owner_user_id": r[8],
                        "created_at": r[9], "updated_at": r[10],
                    })
            # 为每个 plan 补充进度统计
            for item in items:
                progress = await self.get_plan_progress(item["plan_id"])
                item.update(progress)
            return {"total": total, "page": page, "page_size": page_size, "items": items}
        except Exception as e:
            logger.error(f"[customer_dispatch] list_plans failed: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "items": []}

    async def get_plan(self, plan_id: str, owner_user_id: str = "", is_admin: bool = False) -> Optional[Dict]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["plan_id = :pid"]
            params = {"pid": plan_id}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT plan_id, name, platform, total_customers, total_accounts, "
                        "filter_keywords, min_lead_score, status, owner_user_id, "
                        "created_at, updated_at FROM customer_dispatch_plan WHERE "
                        + " AND ".join(conditions)
                    ),
                    params,
                )
                r = rows.fetchone()
                if not r:
                    return None
                plan = {
                    "plan_id": r[0], "name": r[1], "platform": r[2],
                    "total_customers": r[3], "total_accounts": r[4],
                    "filter_keywords": r[5], "min_lead_score": r[6],
                    "status": r[7], "owner_user_id": r[8],
                    "created_at": r[9], "updated_at": r[10],
                }
            plan.update(await self.get_plan_progress(plan_id))
            plan["accounts"] = await self.list_accounts(plan_id)
            return plan
        except Exception as e:
            logger.error(f"[customer_dispatch] get_plan failed: {e}")
            return None

    async def delete_plan(self, plan_id: str, owner_user_id: str = "", is_admin: bool = False) -> bool:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["plan_id = :pid"]
            params = {"pid": plan_id}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            where = " WHERE " + " AND ".join(conditions)
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(f"DELETE FROM customer_dispatch_record{where}"), params
                )
                await conn.execute(
                    sql_text(f"DELETE FROM customer_dispatch_account{where}"), params
                )
                res = await conn.execute(
                    sql_text(f"DELETE FROM customer_dispatch_plan{where}"), params
                )
                return res.rowcount > 0
        except Exception as e:
            logger.error(f"[customer_dispatch] delete_plan failed: {e}")
            return False

    # ==================== 账号分配 ====================

    async def list_accounts(self, plan_id: str) -> List[Dict]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT account_idx, account_alias, cookie_id, range_start, "
                        "range_end, batch_size, total_assigned, total_sent, total_replied, "
                        "status, created_at, updated_at "
                        "FROM customer_dispatch_account WHERE plan_id = :pid "
                        "ORDER BY account_idx"
                    ),
                    {"pid": plan_id},
                )
                items = []
                for r in rows.fetchall():
                    items.append({
                        "account_idx": r[0], "account_alias": r[1], "cookie_id": r[2],
                        "range_start": r[3], "range_end": r[4], "batch_size": r[5],
                        "total_assigned": r[6], "total_sent": r[7], "total_replied": r[8],
                        "status": r[9], "created_at": r[10], "updated_at": r[11],
                    })
                return items
        except Exception as e:
            logger.error(f"[customer_dispatch] list_accounts failed: {e}")
            return []

    # ==================== 核心调度：get_next_for_account ====================

    async def get_next_for_account(
        self, plan_id: str, account_idx: int, batch_size: int = 20,
        owner_user_id: str = "", is_admin: bool = False,
    ) -> Dict:
        """
        获取账号 N 的下一批待发客户

        调度优先级：
        1. 账号自己区间内 status='pending' 的客户（按 seq 升序）
        2. 其他账号区间内 status='sent' 但 replied_at=0（漏单补发，按 seq 升序）
           —— 跳过自己已发但未回复的（避免重复发）

        返回 K 个客户并标记 sent_by_account=N, status='sent', sent_at=now
        跳过 status='replied'（去重）
        """
        await self.ensure_table()
        # 校验 plan 归属
        plan = await self.get_plan(plan_id, owner_user_id=owner_user_id, is_admin=is_admin)
        if not plan:
            return {"ok": False, "reason": "计划不存在或无权限"}

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            now = int(time.time())
            customer_lead_ids: List[int] = []
            logger.info(
                f"[customer_dispatch] get_next_for_account 开始: plan={plan_id}, "
                f"account_idx={account_idx}, batch_size={batch_size}"
            )

            async with engine.begin() as conn:
                # 1. 优先：自己区间内 pending
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, customer_lead_id, customer_seq FROM customer_dispatch_record "
                        "WHERE plan_id = :pid AND assigned_account_idx = :aidx "
                        "AND status = 'pending' "
                        "ORDER BY customer_seq ASC LIMIT :lim"
                    ),
                    {"pid": plan_id, "aidx": account_idx, "lim": batch_size},
                )
                own_records = rows.fetchall()
                if own_records:
                    logger.info(
                        f"[customer_dispatch] 账号{account_idx}本区间命中{len(own_records)}个pending: "
                        + ", ".join(f"#{r[2]:04d}(lead={r[1]})" for r in own_records)
                        + f" [plan={plan_id}]"
                    )

                # 2. 补充：其他账号区间内 sent 未回复（漏单补发）
                remaining = batch_size - len(own_records)
                leaked_records = []
                if remaining > 0:
                    logger.info(
                        f"[customer_dispatch] 账号{account_idx}本区间取到{len(own_records)}个(需{batch_size}),"
                        f"尚缺{remaining}个,启动漏单补发查询 [plan={plan_id}]"
                    )
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, customer_lead_id, customer_seq, assigned_account_idx, sent_by_account "
                            "FROM customer_dispatch_record "
                            "WHERE plan_id = :pid AND status = 'sent' "
                            "AND replied_at = 0 AND sent_by_account != :aidx "
                            "ORDER BY customer_seq ASC LIMIT :lim"
                        ),
                        {"pid": plan_id, "aidx": account_idx, "lim": remaining},
                    )
                    leaked_records = rows.fetchall()
                    if leaked_records:
                        # 详细打印每个被补发的漏单：seq / lead_id / 原属账号 / 原发送账号
                        leak_details = [
                            f"#{r[2]:04d}(lead={r[1]},原属账号={r[3]},原发账号={r[4]})"
                            for r in leaked_records
                        ]
                        logger.info(
                            f"[customer_dispatch] 漏单补发命中{len(leaked_records)}条 "
                            f"[plan={plan_id}, 补发账号={account_idx}]:\n  "
                            + "\n  ".join(leak_details)
                        )
                    else:
                        logger.info(
                            f"[customer_dispatch] 漏单补发未命中(无可补漏单) "
                            f"[plan={plan_id}, 账号={account_idx}]"
                        )
                else:
                    logger.info(
                        f"[customer_dispatch] 账号{account_idx}本区间已取满{len(own_records)}/{batch_size},"
                        f"无需漏单补发 [plan={plan_id}]"
                    )

                all_records = own_records + leaked_records
                if not all_records:
                    return {
                        "ok": True, "plan_id": plan_id,
                        "account_idx": account_idx,
                        "batch_size": batch_size,
                        "customers": [],
                        "customer_lead_ids": [],
                        "seqs": [],
                        "own_count": 0,
                        "leaked_count": 0,
                        "message": "无待发客户（本账号区间已发完且无漏单可补）",
                    }

                # 标记 sent_by_account=N, status='sent', sent_at=now
                record_ids = [r[0] for r in all_records]
                customer_lead_ids = [r[1] for r in all_records]
                seqs = [r[2] for r in all_records]

                # 批量 UPDATE
                for rid in record_ids:
                    await conn.execute(
                        sql_text(
                            "UPDATE customer_dispatch_record SET status = 'sent', "
                            "sent_by_account = :aidx, sent_at = :now, updated_at = :now "
                            "WHERE id = :rid"
                        ),
                        {"aidx": account_idx, "now": now, "rid": rid},
                    )

                # 更新账号统计 total_sent
                await conn.execute(
                    sql_text(
                        "UPDATE customer_dispatch_account SET total_sent = total_sent + :cnt, "
                        "updated_at = :now WHERE plan_id = :pid AND account_idx = :aidx"
                    ),
                    {"cnt": len(record_ids), "now": now, "pid": plan_id, "aidx": account_idx},
                )

            # 拉取客户详细信息（从 customer_lead 表）
            customers = await self._fetch_lead_details(customer_lead_ids)
            logger.info(
                f"[customer_dispatch] get_next_for_account 完成: plan={plan_id}, "
                f"账号={account_idx}, own={len(own_records)}, leaked={len(leaked_records)}, "
                f"seqs=[{','.join(f'#{s:04d}' for s in seqs)}]"
            )
            return {
                "ok": True, "plan_id": plan_id, "account_idx": account_idx,
                "batch_size": batch_size,
                "customers": customers,
                "customer_lead_ids": customer_lead_ids,
                "seqs": seqs,
                "own_count": len(own_records),
                "leaked_count": len(leaked_records),
            }
        except Exception as e:
            logger.error(f"[customer_dispatch] get_next_for_account failed: {e}")
            return {"ok": False, "reason": str(e)}

    async def mark_replied(
        self, plan_id: str, customer_lead_id: int, account_idx: int,
        contact_log: str = "", owner_user_id: str = "", is_admin: bool = False,
    ) -> bool:
        """标记客户为已回复（去重的核心操作）"""
        await self.ensure_table()
        plan = await self.get_plan(plan_id, owner_user_id=owner_user_id, is_admin=is_admin)
        if not plan:
            return False
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            now = int(time.time())
            async with engine.begin() as conn:
                res = await conn.execute(
                    sql_text(
                        "UPDATE customer_dispatch_record SET status = 'replied', "
                        "replied_by_account = :aidx, replied_at = :now, "
                        "contact_log = :log, updated_at = :now "
                        "WHERE plan_id = :pid AND customer_lead_id = :lid "
                        "AND status != 'replied'"
                    ),
                    {
                        "aidx": account_idx, "now": now, "log": contact_log,
                        "pid": plan_id, "lid": customer_lead_id,
                    },
                )
                if res.rowcount == 0:
                    return False  # 已回复或不存在
                # 更新账号统计 total_replied
                await conn.execute(
                    sql_text(
                        "UPDATE customer_dispatch_account SET total_replied = total_replied + 1, "
                        "updated_at = :now WHERE plan_id = :pid AND account_idx = :aidx"
                    ),
                    {"now": now, "pid": plan_id, "aidx": account_idx},
                )
            return True
        except Exception as e:
            logger.error(f"[customer_dispatch] mark_replied failed: {e}")
            return False

    async def batch_mark_replied(
        self, plan_id: str, customer_lead_ids: List[int], account_idx: int,
        owner_user_id: str = "", is_admin: bool = False,
    ) -> int:
        """批量标记已回复，返回成功数"""
        logger.info(
            f"[customer_dispatch] batch_mark_replied 开始: plan={plan_id}, "
            f"账号={account_idx}, 待标记={len(customer_lead_ids)}个 lead_ids={customer_lead_ids}"
        )
        success = 0
        marked_ok: List[int] = []
        marked_skip: List[int] = []
        for lid in customer_lead_ids:
            ok = await self.mark_replied(
                plan_id, lid, account_idx, owner_user_id=owner_user_id, is_admin=is_admin
            )
            if ok:
                success += 1
                marked_ok.append(lid)
            else:
                marked_skip.append(lid)
        logger.info(
            f"[customer_dispatch] batch_mark_replied 完成: plan={plan_id}, 账号={account_idx}, "
            f"成功标记replied={len(marked_ok)}个(后续账号将跳过去重) lead_ids={marked_ok}; "
            f"跳过={len(marked_skip)}个 lead_ids={marked_skip}"
        )
        return success

    # ==================== 进度统计 ====================

    async def get_plan_progress(self, plan_id: str) -> Dict:
        """获取计划进度：已发/已回复/待发/漏单"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT "
                        " COUNT(*) AS total, "
                        " COUNT(*) FILTER (WHERE status = 'pending') AS pending, "
                        " COUNT(*) FILTER (WHERE status = 'sent' AND replied_at = 0) AS sent_unreplied, "
                        " COUNT(*) FILTER (WHERE status = 'replied') AS replied, "
                        " COUNT(DISTINCT sent_by_account) FILTER (WHERE sent_by_account > 0) AS active_accounts "
                        "FROM customer_dispatch_record WHERE plan_id = :pid"
                    ),
                    {"pid": plan_id},
                )
                r = rows.fetchone()
                if not r:
                    return {}
                total = int(r[0] or 0)
                pending = int(r[1] or 0)
                sent_unreplied = int(r[2] or 0)
                replied = int(r[3] or 0)
                coverage = round(replied * 100.0 / total, 1) if total > 0 else 0.0
                return {
                    "total": total, "pending": pending,
                    "sent_unreplied": sent_unreplied, "replied": replied,
                    "active_accounts": int(r[4] or 0),
                    "coverage_pct": coverage,
                    "remaining": total - replied,
                }
        except Exception as e:
            logger.error(f"[customer_dispatch] get_plan_progress failed: {e}")
            return {}

    async def list_records(
        self, plan_id: str, *, account_idx: Optional[int] = None,
        status: Optional[str] = None, page: int = 1, page_size: int = 50,
        owner_user_id: str = "", is_admin: bool = False,
    ) -> Dict:
        await self.ensure_table()
        plan = await self.get_plan(plan_id, owner_user_id=owner_user_id, is_admin=is_admin)
        if not plan:
            return {"total": 0, "page": page, "page_size": page_size, "items": []}
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["r.plan_id = :pid"]
            params: Dict[str, Any] = {"pid": plan_id}
            if account_idx is not None:
                conditions.append("r.assigned_account_idx = :aidx")
                params["aidx"] = account_idx
            if status:
                conditions.append("r.status = :st")
                params["st"] = status
            where = " AND ".join(conditions)
            async with engine.connect() as conn:
                cnt = await conn.execute(
                    sql_text(
                        f"SELECT COUNT(*) FROM customer_dispatch_record r WHERE {where}"
                    ),
                    params,
                )
                total = int(cnt.fetchone()[0] or 0)
                offset = (page - 1) * page_size
                params["lim"] = page_size
                params["off"] = offset
                rows = await conn.execute(
                    sql_text(
                        f"SELECT r.id, r.plan_id, r.customer_lead_id, r.customer_seq, "
                        f" r.assigned_account_idx, r.status, r.sent_by_account, "
                        f" r.replied_by_account, r.sent_at, r.replied_at, r.contact_log, "
                        f" r.created_at, r.updated_at, "
                        f" l.nickname, l.platform, l.content, l.url, l.lead_score, "
                        f" l.profile_url, l.comment_url, l.intent_type "
                        f"FROM customer_dispatch_record r "
                        f"LEFT JOIN customer_lead l ON l.id = r.customer_lead_id "
                        f"WHERE {where} "
                        f"ORDER BY r.customer_seq ASC LIMIT :lim OFFSET :off"
                    ),
                    params,
                )
                items = []
                for r in rows.fetchall():
                    items.append({
                        "id": r[0], "plan_id": r[1], "customer_lead_id": r[2],
                        "customer_seq": r[3], "assigned_account_idx": r[4],
                        "status": r[5], "sent_by_account": r[6],
                        "replied_by_account": r[7], "sent_at": r[8],
                        "replied_at": r[9], "contact_log": r[10],
                        "created_at": r[11], "updated_at": r[12],
                        "customer_nickname": r[13] or "",
                        "customer_platform": r[14] or "",
                        "customer_content": r[15] or "",
                        "customer_url": r[16] or "",
                        "customer_lead_score": int(r[17] or 0),
                        "customer_profile_url": r[18] or "",
                        "customer_comment_url": r[19] or "",
                        "customer_intent_type": r[20] or "",
                    })
            return {"total": total, "page": page, "page_size": page_size, "items": items}
        except Exception as e:
            logger.error(f"[customer_dispatch] list_records failed: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "items": []}

    # ==================== 内部辅助 ====================

    async def _fetch_customer_leads(
        self, *, platform: str, filter_keywords: str,
        min_lead_score: int, owner_user_id: str,
    ) -> List[int]:
        """从 customer_lead 表按条件查询客户ID列表"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["status != 'deleted'"]
            params: Dict[str, Any] = {}
            if platform:
                conditions.append("platform = :pf")
                params["pf"] = platform
            if min_lead_score > 0:
                conditions.append("lead_score >= :ms")
                params["ms"] = min_lead_score
            if filter_keywords:
                # 关键词模糊匹配 content / matched_keywords
                conditions.append("(content ILIKE :kw OR matched_keywords ILIKE :kw)")
                params["kw"] = f"%{filter_keywords}%"
            if owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            where = " WHERE " + " AND ".join(conditions)
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT id FROM customer_lead{where} "
                        f"ORDER BY lead_score DESC, add_ts ASC"
                    ),
                    params,
                )
                return [int(r[0]) for r in rows.fetchall()]
        except Exception as e:
            logger.error(f"[customer_dispatch] _fetch_customer_leads failed: {e}")
            return []

    async def _fetch_lead_details(self, lead_ids: List[int]) -> List[Dict]:
        """从 customer_lead 表拉取客户详细信息"""
        if not lead_ids:
            return []
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, nickname, platform, content, url, lead_score, "
                        "profile_url, comment_url, intent_type, sec_uid, user_id "
                        "FROM customer_lead WHERE id = ANY(:ids)"
                    ),
                    {"ids": lead_ids},
                )
                # 用 dict 保证顺序与 lead_ids 一致
                detail_map = {}
                for r in rows.fetchall():
                    detail_map[int(r[0])] = {
                        "customer_lead_id": int(r[0]),
                        "nickname": r[1] or "", "platform": r[2] or "",
                        "content": r[3] or "", "url": r[4] or "",
                        "lead_score": int(r[5] or 0),
                        "profile_url": r[6] or "", "comment_url": r[7] or "",
                        "intent_type": r[8] or "",
                        "sec_uid": r[9] or "", "user_id": r[10] or "",
                    }
                return [detail_map[lid] for lid in lead_ids if lid in detail_map]
        except Exception as e:
            logger.error(f"[customer_dispatch] _fetch_lead_details failed: {e}")
            return []

    @staticmethod
    def _compute_ranges(
        total: int, account_configs: List[Dict]
    ) -> List[Tuple[int, int]]:
        """
        按 batch_size 比例分配区间，确保总和 = total

        例：total=100, configs=[{bs:20},{bs:38},{bs:30},...]
        返回：[(1,20), (21,58), (59,88), ...]
        """
        total_bs = sum(int(c.get("batch_size", 20)) for c in account_configs)
        if total_bs == 0:
            # 平均分配
            avg = total // len(account_configs)
            ranges = []
            start = 1
            for i, _ in enumerate(account_configs):
                end = start + avg - 1 if i < len(account_configs) - 1 else total
                ranges.append((start, end))
                start = end + 1
            return ranges

        ranges = []
        start = 1
        for i, cfg in enumerate(account_configs):
            bs = int(cfg.get("batch_size", 20))
            if i == len(account_configs) - 1:
                # 最后一个账号兜底：拿到剩余全部
                end = total
            else:
                # 按比例计算
                count = round(total * bs / total_bs)
                end = start + count - 1
                if end > total:
                    end = total
            ranges.append((start, end))
            start = end + 1
        # 保证最后一个区间结尾 = total
        if ranges:
            last_start, _ = ranges[-1]
            ranges[-1] = (last_start, total)
        return ranges

    @staticmethod
    def _find_account_for_seq(seq: int, ranges: List[Tuple[int, int]]) -> int:
        """找到 seq 所属的账号 idx（1-based，返回第一个匹配，不支持重叠）"""
        for idx, (s, e) in enumerate(ranges, start=1):
            if s <= seq <= e:
                return idx
        return 1  # 兜底

    @staticmethod
    def _find_accounts_for_seq(seq: int, ranges: List[Tuple[int, int]]) -> List[int]:
        """找到 seq 所属的所有账号 idx 列表（支持重叠区间）

        例：ranges=[(1,100),(50,150)]，seq=75 → 返回 [1,2]（两个账号都包含）
            seq=25 → 返回 [1]（仅账号1）
            seq=125 → 返回 [2]（仅账号2）
        """
        result = []
        for idx, (s, e) in enumerate(ranges, start=1):
            if s is not None and e is not None and s <= seq <= e:
                result.append(idx)
        return result if result else [1]  # 兜底返回账号1


# ============ 单例 ============
_customer_dispatch_service: Optional[CustomerDispatchService] = None


def get_customer_dispatch_service() -> CustomerDispatchService:
    global _customer_dispatch_service
    if _customer_dispatch_service is None:
        _customer_dispatch_service = CustomerDispatchService()
    return _customer_dispatch_service
