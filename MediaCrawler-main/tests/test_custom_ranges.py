# -*- coding: utf-8 -*-
"""
custom_ranges 功能完整单元测试（覆盖 12 个边界条件）

边界条件清单：
  [参数校验类]
  1. custom_ranges=None → 走自动分配（_compute_ranges），不触发校验错误
  2. account_idx 超出范围（< 1 或 > total_accounts）→ 返回失败
  3. range_start > range_end → 返回失败
  4. 缺少某账号的区间配置 → 返回失败

  [纯函数 _find_accounts_for_seq 类]
  5. 非重叠区 seq → 返回单元素列表 [N]
  6. 重叠区 seq → 返回多元素列表 [N, M]
  7. 越界 seq → 兜底返回 [1]

  [区间分配类]
  8. 不重叠 custom_ranges → 各账号区间独立，每 seq 仅 1 条记录
  9. 部分重叠 custom_ranges → 重叠区 seq 有多条记录
  10. 完全重叠 custom_ranges → 所有 seq 都有多条记录

  [去重逻辑类]
  11. 重叠区去重：账号1标记 replied 后账号2取数跳过（用户重点验证用例）
  12. 重叠区取数独立性：账号1取 sent 后账号2仍可取本区间 pending

运行方式：
    cd /home/ubuntu/getuser-for-chengdu/MediaCrawler-main
    python3 -m pytest tests/test_custom_ranges.py -v
"""
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text as sql_text
from sqlalchemy.pool import StaticPool

from api.services.dispatch.customer_dispatch_service import CustomerDispatchService


# ================================================================
# 第一部分：参数校验（用例 1-4）
# ================================================================

# SQLite 兼容建表 SQL（支持重叠区间：UNIQUE(plan_id, customer_seq, assigned_account_idx)）
_CREATE_PLAN_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS customer_dispatch_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    platform TEXT DEFAULT 'douyin',
    total_customers INTEGER DEFAULT 0,
    total_accounts INTEGER DEFAULT 0,
    filter_keywords TEXT DEFAULT '',
    min_lead_score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    owner_user_id TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
)
"""
_CREATE_ACCOUNT_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS customer_dispatch_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    account_idx INTEGER NOT NULL,
    account_alias TEXT DEFAULT '',
    cookie_id TEXT DEFAULT '',
    range_start INTEGER DEFAULT 0,
    range_end INTEGER DEFAULT 0,
    batch_size INTEGER DEFAULT 20,
    total_assigned INTEGER DEFAULT 0,
    total_sent INTEGER DEFAULT 0,
    total_replied INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0,
    UNIQUE(plan_id, account_idx)
)
"""
# 关键：UNIQUE(plan_id, customer_seq, assigned_account_idx) 允许重叠区间
_CREATE_RECORD_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS customer_dispatch_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    customer_lead_id INTEGER NOT NULL,
    customer_seq INTEGER NOT NULL,
    assigned_account_idx INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    sent_by_account INTEGER DEFAULT 0,
    replied_by_account INTEGER DEFAULT 0,
    sent_at INTEGER DEFAULT 0,
    replied_at INTEGER DEFAULT 0,
    contact_log TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0,
    UNIQUE(plan_id, customer_seq, assigned_account_idx)
)
"""


@pytest.fixture
async def validation_engine():
    """创建 SQLite 内存数据库，用于参数校验 + create_plan 完整流程测试。

    mock 策略：
    - database.db_session.get_async_engine → 返回 SQLite engine
    - config.SAVE_DATA_OPTION → "sqlite"
    - CustomerDispatchService.ensure_table → 跳过（表已手动创建）
    - CustomerDispatchService._fetch_lead_details → 返回空列表
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.execute(sql_text(_CREATE_PLAN_TABLE_SQLITE))
        await conn.execute(sql_text(_CREATE_ACCOUNT_TABLE_SQLITE))
        await conn.execute(sql_text(_CREATE_RECORD_TABLE_SQLITE))
        await conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_cdr_plan_status "
            "ON customer_dispatch_record(plan_id, status, customer_seq)"
        ))
        await conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_cdr_plan_account "
            "ON customer_dispatch_record(plan_id, assigned_account_idx, status)"
        ))

    service = CustomerDispatchService()
    with patch("database.db_session.get_async_engine", return_value=engine), \
         patch("config.SAVE_DATA_OPTION", "sqlite"), \
         patch.object(CustomerDispatchService, "ensure_table", new_callable=AsyncMock), \
         patch.object(
             CustomerDispatchService, "_fetch_lead_details",
             new_callable=AsyncMock, return_value=[],
         ):
        yield engine, service

    await engine.dispose()


class TestCustomRangesValidation:
    """参数校验测试（用例 1-4）"""

    _ACCOUNT_CONFIGS = [
        {"account_alias": "账号1", "cookie_id": "c1", "batch_size": 50},
        {"account_alias": "账号2", "cookie_id": "c2", "batch_size": 50},
    ]
    _LEAD_IDS = list(range(10001, 10101))  # 100 个客户

    async def test_case01_none_falls_back_to_auto_allocation(self, validation_engine):
        """用例1：custom_ranges=None → 走自动分配（_compute_ranges），创建成功"""
        _, service = validation_engine
        result = await service.create_plan(
            name="测试-自动分配",
            account_configs=self._ACCOUNT_CONFIGS,
            customer_lead_ids=self._LEAD_IDS,
            custom_ranges=None,  # 不传 → 自动分配
        )
        assert result["created"] is True, f"自动分配应创建成功，reason={result.get('reason')}"
        assert result["total_customers"] == 100
        assert result["total_accounts"] == 2
        # 自动分配区间不重叠：账号1 #0001-0050，账号2 #0051-0100
        ranges = result["ranges"]
        assert ranges[0]["range_start"] == 1
        assert ranges[0]["range_end"] == 50
        assert ranges[1]["range_start"] == 51
        assert ranges[1]["range_end"] == 100

    async def test_case02_account_idx_out_of_range(self, validation_engine):
        """用例2：account_idx 超出范围 → 返回失败"""
        _, service = validation_engine
        # account_idx=3 但只有 2 个账号
        result = await service.create_plan(
            name="测试-idx越界",
            account_configs=self._ACCOUNT_CONFIGS,
            customer_lead_ids=self._LEAD_IDS,
            custom_ranges=[
                {"account_idx": 1, "range_start": 1, "range_end": 50},
                {"account_idx": 2, "range_start": 51, "range_end": 100},
                {"account_idx": 3, "range_start": 1, "range_end": 10},  # 越界
            ],
        )
        assert result["created"] is False
        assert "超出范围" in result["reason"]
        assert "3" in result["reason"]

    async def test_case03_range_start_greater_than_end(self, validation_engine):
        """用例3：range_start > range_end → 返回失败"""
        _, service = validation_engine
        result = await service.create_plan(
            name="测试-区间倒置",
            account_configs=self._ACCOUNT_CONFIGS,
            customer_lead_ids=self._LEAD_IDS,
            custom_ranges=[
                {"account_idx": 1, "range_start": 50, "range_end": 10},  # start > end
                {"account_idx": 2, "range_start": 51, "range_end": 100},
            ],
        )
        assert result["created"] is False
        assert "range_start > range_end" in result["reason"]

    async def test_case04_missing_account_range_config(self, validation_engine):
        """用例4：缺少某账号的区间配置 → 返回失败"""
        _, service = validation_engine
        # 只配置了账号1，缺少账号2
        result = await service.create_plan(
            name="测试-缺少账号配置",
            account_configs=self._ACCOUNT_CONFIGS,
            customer_lead_ids=self._LEAD_IDS,
            custom_ranges=[
                {"account_idx": 1, "range_start": 1, "range_end": 100},
                # 缺少 account_idx=2 的配置
            ],
        )
        assert result["created"] is False
        assert "缺少" in result["reason"]
        assert "2" in result["reason"]


# ================================================================
# 第二部分：纯函数 _find_accounts_for_seq（用例 5-7）
# ================================================================

class TestFindAccountsForSeq:
    """_find_accounts_for_seq 测试（支持重叠区间，返回列表）"""

    def test_case05_non_overlap_returns_single_account(self):
        """用例5：非重叠区 seq → 返回单元素列表"""
        # 账号1:#0001-0049, 账号2:#0050-0100（不重叠）
        ranges = [(1, 49), (50, 100)]
        assert CustomerDispatchService._find_accounts_for_seq(1, ranges) == [1]
        assert CustomerDispatchService._find_accounts_for_seq(25, ranges) == [1]
        assert CustomerDispatchService._find_accounts_for_seq(49, ranges) == [1]
        assert CustomerDispatchService._find_accounts_for_seq(50, ranges) == [2]
        assert CustomerDispatchService._find_accounts_for_seq(75, ranges) == [2]
        assert CustomerDispatchService._find_accounts_for_seq(100, ranges) == [2]

    def test_case06_overlap_returns_multiple_accounts(self):
        """用例6：重叠区 seq → 返回多元素列表"""
        # 账号1:#0001-0100, 账号2:#0050-0150（重叠区 #0050-0100）
        ranges = [(1, 100), (50, 150)]
        # 非重叠区
        assert CustomerDispatchService._find_accounts_for_seq(25, ranges) == [1]
        assert CustomerDispatchService._find_accounts_for_seq(125, ranges) == [2]
        # 重叠区 → 两个账号都包含
        assert CustomerDispatchService._find_accounts_for_seq(50, ranges) == [1, 2]
        assert CustomerDispatchService._find_accounts_for_seq(75, ranges) == [1, 2]
        assert CustomerDispatchService._find_accounts_for_seq(100, ranges) == [1, 2]

    def test_case07_out_of_range_returns_fallback(self):
        """用例7：越界 seq → 兜底返回 [1]"""
        ranges = [(1, 100), (50, 150)]
        assert CustomerDispatchService._find_accounts_for_seq(0, ranges) == [1]
        assert CustomerDispatchService._find_accounts_for_seq(151, ranges) == [1]
        assert CustomerDispatchService._find_accounts_for_seq(-5, ranges) == [1]
        assert CustomerDispatchService._find_accounts_for_seq(999, ranges) == [1]


# ================================================================
# 第三部分：区间分配（用例 8-10）
# ================================================================

@pytest.fixture
async def overlap_db():
    """创建支持重叠区间的 SQLite 内存数据库，预插入 plan + account + record 数据。

    测试数据：
    - 客户 seq 1-20, lead_id 2001-2020
    - 账号1区间 #0001-0010, 账号2区间 #0006-0015（部分重叠 #0006-0010）
    - seq 1-5:   仅账号1记录 (assigned_account_idx=1)
    - seq 6-10:  账号1+账号2各一条记录（重叠区）
    - seq 11-15: 仅账号2记录 (assigned_account_idx=2)
    - seq 16-20: 无记录（超出两个账号区间）

    mock 策略同 validation_engine，额外 mock get_plan 跳过权限检查。
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    plan_id = "test_overlap_plan_001"

    async with engine.begin() as conn:
        await conn.execute(sql_text(_CREATE_PLAN_TABLE_SQLITE))
        await conn.execute(sql_text(_CREATE_ACCOUNT_TABLE_SQLITE))
        await conn.execute(sql_text(_CREATE_RECORD_TABLE_SQLITE))
        await conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_cdr_plan_status "
            "ON customer_dispatch_record(plan_id, status, customer_seq)"
        ))
        await conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_cdr_plan_account "
            "ON customer_dispatch_record(plan_id, assigned_account_idx, status)"
        ))

        # 插入 plan
        await conn.execute(sql_text(
            "INSERT INTO customer_dispatch_plan"
            "(plan_id, name, platform, total_customers, total_accounts, status) "
            "VALUES (:pid, '重叠区间测试计划', 'douyin', 15, 2, 'active')"
        ), {"pid": plan_id})

        # 插入账号1（区间 #0001-0010）和账号2（区间 #0006-0015）
        await conn.execute(sql_text(
            "INSERT INTO customer_dispatch_account"
            "(plan_id, account_idx, account_alias, range_start, range_end, batch_size, total_assigned) "
            "VALUES (:pid, 1, '账号1', 1, 10, 10, 10)"
        ), {"pid": plan_id})
        await conn.execute(sql_text(
            "INSERT INTO customer_dispatch_account"
            "(plan_id, account_idx, account_alias, range_start, range_end, batch_size, total_assigned) "
            "VALUES (:pid, 2, '账号2', 6, 15, 10, 10)"
        ), {"pid": plan_id})

        # 插入客户记录（支持重叠区间）
        ranges = [(1, 10), (6, 15)]  # 账号1, 账号2
        for seq in range(1, 21):
            lead_id = 2000 + seq
            acc_indices = CustomerDispatchService._find_accounts_for_seq(seq, ranges)
            for acc_idx in acc_indices:
                await conn.execute(sql_text(
                    "INSERT INTO customer_dispatch_record"
                    "(plan_id, customer_lead_id, customer_seq, assigned_account_idx, status) "
                    "VALUES (:pid, :lid, :seq, :aidx, 'pending')"
                ), {"pid": plan_id, "lid": lead_id, "seq": seq, "aidx": acc_idx})

    service = CustomerDispatchService()
    with patch("database.db_session.get_async_engine", return_value=engine), \
         patch("config.SAVE_DATA_OPTION", "sqlite"), \
         patch.object(CustomerDispatchService, "ensure_table", new_callable=AsyncMock), \
         patch.object(
             CustomerDispatchService, "get_plan", new_callable=AsyncMock,
             return_value={"plan_id": plan_id, "name": "重叠区间测试计划", "status": "active"},
         ), \
         patch.object(
             CustomerDispatchService, "_fetch_lead_details",
             new_callable=AsyncMock, return_value=[],
         ):
        yield engine, service, plan_id

    await engine.dispose()


class TestCustomRangesAllocation:
    """区间分配测试（用例 8-10）"""

    async def test_case08_non_overlap_custom_ranges(self, validation_engine):
        """用例8：不重叠 custom_ranges → 各账号区间独立，每 seq 仅 1 条记录"""
        engine, service = validation_engine
        result = await service.create_plan(
            name="测试-不重叠区间",
            account_configs=[
                {"account_alias": "账号1", "cookie_id": "c1", "batch_size": 50},
                {"account_alias": "账号2", "cookie_id": "c2", "batch_size": 50},
            ],
            customer_lead_ids=list(range(10001, 10101)),  # 100 个客户
            custom_ranges=[
                {"account_idx": 1, "range_start": 1, "range_end": 50},
                {"account_idx": 2, "range_start": 51, "range_end": 100},
            ],
        )
        assert result["created"] is True
        plan_id = result["plan_id"]

        # 验证：每 seq 仅 1 条记录
        async with engine.begin() as conn:
            rows = await conn.execute(sql_text(
                "SELECT customer_seq, COUNT(*) as cnt FROM customer_dispatch_record "
                "WHERE plan_id = :pid GROUP BY customer_seq ORDER BY customer_seq"
            ), {"pid": plan_id})
            for row in rows.fetchall():
                assert row[1] == 1, f"seq={row[0]} 有 {row[1]} 条记录，期望 1（不重叠）"

    async def test_case09_partial_overlap_custom_ranges(self, validation_engine):
        """用例9：部分重叠 custom_ranges → 重叠区 seq 有多条记录"""
        engine, service = validation_engine
        # 账号1:#0001-0070, 账号2:#0051-0100（重叠区 #0051-0070）
        result = await service.create_plan(
            name="测试-部分重叠区间",
            account_configs=[
                {"account_alias": "账号1", "cookie_id": "c1", "batch_size": 70},
                {"account_alias": "账号2", "cookie_id": "c2", "batch_size": 50},
            ],
            customer_lead_ids=list(range(10001, 10101)),  # 100 个客户
            custom_ranges=[
                {"account_idx": 1, "range_start": 1, "range_end": 70},
                {"account_idx": 2, "range_start": 51, "range_end": 100},
            ],
        )
        assert result["created"] is True
        plan_id = result["plan_id"]

        async with engine.begin() as conn:
            # 非重叠区 seq 1-50：仅 1 条记录
            rows = await conn.execute(sql_text(
                "SELECT customer_seq, COUNT(*) as cnt FROM customer_dispatch_record "
                "WHERE plan_id = :pid AND customer_seq <= 50 "
                "GROUP BY customer_seq ORDER BY customer_seq"
            ), {"pid": plan_id})
            for row in rows.fetchall():
                assert row[1] == 1, f"非重叠区 seq={row[0]} 有 {row[1]} 条记录，期望 1"

            # 重叠区 seq 51-70：2 条记录
            rows = await conn.execute(sql_text(
                "SELECT customer_seq, COUNT(*) as cnt FROM customer_dispatch_record "
                "WHERE plan_id = :pid AND customer_seq BETWEEN 51 AND 70 "
                "GROUP BY customer_seq ORDER BY customer_seq"
            ), {"pid": plan_id})
            overlap_seqs = []
            for row in rows.fetchall():
                assert row[1] == 2, f"重叠区 seq={row[0]} 有 {row[1]} 条记录，期望 2"
                overlap_seqs.append(row[0])
            assert len(overlap_seqs) == 20, f"重叠区应有 20 个 seq，实际 {len(overlap_seqs)}"

            # 非重叠区 seq 71-100：仅 1 条记录
            rows = await conn.execute(sql_text(
                "SELECT customer_seq, COUNT(*) as cnt FROM customer_dispatch_record "
                "WHERE plan_id = :pid AND customer_seq >= 71 "
                "GROUP BY customer_seq ORDER BY customer_seq"
            ), {"pid": plan_id})
            for row in rows.fetchall():
                assert row[1] == 1, f"非重叠区 seq={row[0]} 有 {row[1]} 条记录，期望 1"

    async def test_case10_full_overlap_custom_ranges(self, validation_engine):
        """用例10：完全重叠 custom_ranges → 所有 seq 都有多条记录"""
        engine, service = validation_engine
        # 账号1:#0001-0050, 账号2:#0001-0050（完全重叠）
        result = await service.create_plan(
            name="测试-完全重叠区间",
            account_configs=[
                {"account_alias": "账号1", "cookie_id": "c1", "batch_size": 50},
                {"account_alias": "账号2", "cookie_id": "c2", "batch_size": 50},
            ],
            customer_lead_ids=list(range(10001, 10051)),  # 50 个客户
            custom_ranges=[
                {"account_idx": 1, "range_start": 1, "range_end": 50},
                {"account_idx": 2, "range_start": 1, "range_end": 50},
            ],
        )
        assert result["created"] is True
        plan_id = result["plan_id"]

        async with engine.begin() as conn:
            # 所有 seq 都应有 2 条记录
            rows = await conn.execute(sql_text(
                "SELECT customer_seq, COUNT(*) as cnt FROM customer_dispatch_record "
                "WHERE plan_id = :pid GROUP BY customer_seq ORDER BY customer_seq"
            ), {"pid": plan_id})
            all_seqs = []
            for row in rows.fetchall():
                assert row[1] == 2, f"完全重叠区 seq={row[0]} 有 {row[1]} 条记录，期望 2"
                all_seqs.append(row[0])
            assert len(all_seqs) == 50, f"应有 50 个 seq，实际 {len(all_seqs)}"


# ================================================================
# 第四部分：去重逻辑（用例 11-12）
# ================================================================

class TestCustomRangesDedup:
    """去重逻辑测试（用例 11-12）

    核心机制：mark_replied 按 customer_lead_id 更新（不带 assigned_account_idx 条件），
    因此重叠区同一客户的所有记录（不同 assigned_account_idx）都会被标记为 replied，
    实现跨账号去重。
    """

    async def test_case11_overlap_dedup_account2_skips_replied(self, overlap_db):
        """用例11：重叠区去重 —— 账号1标记 replied 后账号2取数跳过

        场景（使用 overlap_db fixture）：
        - 账号1区间 #0001-0010, 账号2区间 #0006-0015（重叠区 #0006-0010）
        - 步骤1：账号1取5个 → seq 1-5（非重叠区，sent_by_account=1）
        - 步骤2：账号1取5个 → seq 6-10（重叠区，sent_by_account=1）
        - 步骤3：账号1标记 seq 6-10 为 replied
                → mark_replied 按 lead_id 更新，assigned_account_idx=2 的 seq 6-10 也变 replied
        - 步骤4：账号2取5个 → 本区间 pending：
                seq 6-10 的 assigned_account_idx=2 记录已是 replied → 跳过
                seq 11-15 的 assigned_account_idx=2 记录是 pending → 取这5个

        验证：账号2取到 seq 11-15，不含 6-10
        """
        _, service, plan_id = overlap_db

        # 步骤1：账号1取5个 → seq 1-5
        r1 = await service.get_next_for_account(plan_id, account_idx=1, batch_size=5, is_admin=True)
        assert r1["ok"] is True
        assert r1["own_count"] == 5
        assert r1["leaked_count"] == 0
        assert r1["seqs"] == [1, 2, 3, 4, 5]

        # 步骤2：账号1取5个 → seq 6-10（重叠区）
        r2 = await service.get_next_for_account(plan_id, account_idx=1, batch_size=5, is_admin=True)
        assert r2["ok"] is True
        assert r2["own_count"] == 5
        assert r2["seqs"] == [6, 7, 8, 9, 10]

        # 步骤3：账号1标记 seq 6-10 为 replied（lead_id 2006-2010）
        replied_leads = [2006, 2007, 2008, 2009, 2010]
        ok = await service.batch_mark_replied(plan_id, replied_leads, account_idx=1, is_admin=True)
        assert ok == 5, f"应成功标记5个，实际 {ok}"

        # 步骤4：账号2取5个 → 应跳过 seq 6-10（replied），取 seq 11-15（pending）
        r3 = await service.get_next_for_account(plan_id, account_idx=2, batch_size=5, is_admin=True)
        assert r3["ok"] is True
        assert r3["own_count"] == 5, f"账号2本区间应取5个 pending，实际 {r3['own_count']}"
        assert r3["leaked_count"] == 0

        # 核心验证：账号2取到的 seq 不含 6-10（去重生效）
        replied_seqs = {6, 7, 8, 9, 10}
        for seq in r3["seqs"]:
            assert seq not in replied_seqs, \
                f"去重失败：账号2取到了已回复的 seq={seq}（账号1已标记 replied）"

        # 验证账号2取到的是 seq 11-15
        assert r3["seqs"] == [11, 12, 13, 14, 15], \
            f"账号2应取 seq 11-15，实际取到 {r3['seqs']}"

        # 验证账号2取到的 lead_id 不含已回复的
        replied_lead_set = set(replied_leads)
        for lid in r3["customer_lead_ids"]:
            assert lid not in replied_lead_set, \
                f"去重失败：账号2取到了已回复的 lead_id={lid}"

    async def test_case12_overlap_independent_pending_fetch(self, overlap_db):
        """用例12：重叠区取数独立性 —— 账号1取 sent 后账号2仍可取本区间 pending

        场景（使用 overlap_db fixture）：
        - 账号1区间 #0001-0010, 账号2区间 #0006-0015（重叠区 #0006-0010）
        - 步骤1：账号1取5个 → seq 1-5（sent_by_account=1）
        - 步骤2：账号2取5个 → 本区间 pending：
                seq 6-10 的 assigned_account_idx=2 记录是 pending（独立记录，未被账号1影响）
                → 账号2取到 seq 6-10

        验证：账号1取 sent 不影响账号2取本区间 pending（重叠区独立取数）
        （只有 mark_replied 才会跨账号去重，sent 状态不跨账号）
        """
        _, service, plan_id = overlap_db

        # 步骤1：账号1取5个 → seq 1-5（非重叠区）
        r1 = await service.get_next_for_account(plan_id, account_idx=1, batch_size=5, is_admin=True)
        assert r1["ok"] is True
        assert r1["seqs"] == [1, 2, 3, 4, 5]

        # 步骤2：账号2取5个 → 应取 seq 6-10（重叠区 pending，assigned_account_idx=2 独立记录）
        r2 = await service.get_next_for_account(plan_id, account_idx=2, batch_size=5, is_admin=True)
        assert r2["ok"] is True
        assert r2["own_count"] == 5, f"账号2本区间应取5个 pending，实际 {r2['own_count']}"
        assert r2["leaked_count"] == 0

        # 核心验证：账号2取到 seq 6-10（重叠区，与账号1区间重叠但独立取数）
        assert r2["seqs"] == [6, 7, 8, 9, 10], \
            f"账号2应取重叠区 seq 6-10（pending），实际取到 {r2['seqs']}"

        # 验证账号1和账号2取到了相同的客户（重叠区独立取数，未标记 replied 前都可取）
        assert set(r1["customer_lead_ids"]).isdisjoint(set(r2["customer_lead_ids"])), \
            "账号1取 seq 1-5，账号2取 seq 6-10，lead_id 不应重叠"

        # 额外验证：账号1再取5个 → 本区间 seq 6-10 仍可取（assigned_account_idx=1 记录仍 pending）
        r3 = await service.get_next_for_account(plan_id, account_idx=1, batch_size=5, is_admin=True)
        assert r3["ok"] is True
        assert r3["own_count"] == 5
        assert r3["seqs"] == [6, 7, 8, 9, 10], \
            f"账号1应取重叠区 seq 6-10（assigned_account_idx=1 的 pending），实际 {r3['seqs']}"

        # 验证账号1和账号2都取到了 seq 6-10 的客户（重叠区独立取数）
        r2_leads = set(r2["customer_lead_ids"])
        r3_leads = set(r3["customer_lead_ids"])
        assert r2_leads == r3_leads, \
            "重叠区 seq 6-10 应被账号1和账号2各自独立取到（同一批客户）"
