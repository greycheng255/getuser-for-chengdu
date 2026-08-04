# -*- coding: utf-8 -*-
"""
客户分配调度单元测试

覆盖场景（对齐用户需求）：
- 10 账号区间分配（精确匹配用户给定场景：账号1:#0001-0020, 账号2:#0021-0058, 账号3:#0059-0088 ...）
- 去重机制（已回复客户被所有账号自动跳过）
- 漏单补发（本区间发完后补发其他账号 sent 未回复客户，确保全覆盖）
- 区间连续 + 无遗漏

测试分层：
1. 纯函数测试：_compute_ranges / _find_account_for_seq（不依赖数据库，快速验证区间算法）
2. 调度逻辑集成测试：用 SQLite 内存数据库 mock，测试 get_next_for_account / batch_mark_replied 的
   去重 + 漏单补发行为（不依赖远程 PostgreSQL，可独立重复运行）

运行方式：
    cd /home/ubuntu/getuser-for-chengdu/MediaCrawler-main
    python3 -m pytest tests/test_customer_dispatch.py -v
"""
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text as sql_text
from sqlalchemy.pool import StaticPool

from api.services.dispatch.customer_dispatch_service import CustomerDispatchService


# ============ 用户给定场景常量 ============
# 10 个抖音账号的区间容量（用户原始需求）
USER_BATCH_SIZES = [20, 38, 30, 50, 70, 80, 90, 100, 110, 412]
# 期望的区间分配结果（start, end）1-based
EXPECTED_RANGES = [
    (1, 20), (21, 58), (59, 88), (89, 138), (139, 208),
    (209, 288), (289, 378), (379, 478), (479, 588), (589, 1000),
]


# ================================================================
# 第一部分：纯函数测试 —— 区间分配算法 _compute_ranges
# ================================================================

class TestComputeRanges:
    """区间分配算法测试（不依赖数据库）"""

    def test_10_accounts_exact_match_user_scenario(self):
        """10账号区间精确匹配用户给定场景（核心需求）"""
        configs = [{"batch_size": bs} for bs in USER_BATCH_SIZES]
        ranges = CustomerDispatchService._compute_ranges(1000, configs)
        assert ranges == EXPECTED_RANGES
        # 逐账号验证区间起止
        for i, (start, end) in enumerate(ranges):
            exp_s, exp_e = EXPECTED_RANGES[i]
            assert start == exp_s, f"账号{i+1} 区间起={start}, 期望={exp_s}"
            assert end == exp_e, f"账号{i+1} 区间止={end}, 期望={exp_e}"

    def test_sum_equals_total(self):
        """区间总和=total（无遗漏）"""
        configs = [{"batch_size": bs} for bs in USER_BATCH_SIZES]
        ranges = CustomerDispatchService._compute_ranges(1000, configs)
        total = sum(end - start + 1 for start, end in ranges)
        assert total == 1000, f"区间总和={total}, 期望=1000"

    def test_ranges_contiguous(self):
        """区间连续：前一个 end+1 = 后一个 start"""
        configs = [{"batch_size": bs} for bs in USER_BATCH_SIZES]
        ranges = CustomerDispatchService._compute_ranges(1000, configs)
        for i in range(len(ranges) - 1):
            assert ranges[i][1] + 1 == ranges[i + 1][0], \
                f"账号{i+1}止{ranges[i][1]}+1 != 账号{i+2}起{ranges[i+1][0]}"

    def test_last_account_bottom(self):
        """最后账号兜底：区间止=total"""
        configs = [{"batch_size": bs} for bs in USER_BATCH_SIZES]
        ranges = CustomerDispatchService._compute_ranges(1000, configs)
        assert ranges[-1][1] == 1000

    def test_single_account_gets_all(self):
        """单账号：拿到全部"""
        ranges = CustomerDispatchService._compute_ranges(100, [{"batch_size": 100}])
        assert ranges == [(1, 100)]

    def test_zero_batch_size_avg_distribution(self):
        """batch_size=0：平均分配"""
        ranges = CustomerDispatchService._compute_ranges(100, [{"batch_size": 0}, {"batch_size": 0}])
        assert ranges == [(1, 50), (51, 100)]

    def test_batch_size_exceeds_total_proportional(self):
        """batch_size 总和 > total：按比例分配，最后兜底"""
        ranges = CustomerDispatchService._compute_ranges(100, [{"batch_size": 200}, {"batch_size": 300}])
        # 200:300 = 2:3 → 40:60
        assert ranges[0][0] == 1
        assert ranges[-1][1] == 100
        assert sum(e - s + 1 for s, e in ranges) == 100


# ================================================================
# 第二部分：纯函数测试 —— seq 定位账号 _find_account_for_seq
# ================================================================

class TestFindAccountForSeq:
    """seq 定位账号测试"""

    def test_find_correct_account(self):
        """seq 能找到正确的账号"""
        test_cases = [
            (1, 1), (20, 1),       # 账号1区间
            (21, 2), (58, 2),      # 账号2区间
            (59, 3), (88, 3),      # 账号3区间
            (589, 10), (1000, 10), # 账号10区间
        ]
        for seq, expected_idx in test_cases:
            idx = CustomerDispatchService._find_account_for_seq(seq, EXPECTED_RANGES)
            assert idx == expected_idx, f"seq={seq} 应属账号{expected_idx}, 实际={idx}"

    def test_boundary_seq(self):
        """边界 seq：每个区间的起止"""
        assert CustomerDispatchService._find_account_for_seq(1, EXPECTED_RANGES) == 1
        assert CustomerDispatchService._find_account_for_seq(20, EXPECTED_RANGES) == 1
        assert CustomerDispatchService._find_account_for_seq(21, EXPECTED_RANGES) == 2
        assert CustomerDispatchService._find_account_for_seq(88, EXPECTED_RANGES) == 3
        assert CustomerDispatchService._find_account_for_seq(89, EXPECTED_RANGES) == 4

    def test_out_of_range_returns_1(self):
        """越界 seq 返回 1（兜底）"""
        assert CustomerDispatchService._find_account_for_seq(0, EXPECTED_RANGES) == 1
        assert CustomerDispatchService._find_account_for_seq(1001, EXPECTED_RANGES) == 1
        assert CustomerDispatchService._find_account_for_seq(-5, EXPECTED_RANGES) == 1


# ================================================================
# 第三部分：调度逻辑集成测试 —— SQLite 内存数据库
# ================================================================

# SQLite 兼容的建表 SQL（用 INTEGER PRIMARY KEY AUTOINCREMENT 替代 PostgreSQL SERIAL）
_CREATE_RECORD_TABLE = """
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
    UNIQUE(plan_id, customer_lead_id),
    UNIQUE(plan_id, customer_seq)
)
"""
_CREATE_PLAN_TABLE = """
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
_CREATE_ACCOUNT_TABLE = """
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


@pytest.fixture
async def dispatch_db():
    """创建 SQLite 内存数据库，初始化 10 账号 1000 客户测试数据。

    patch 策略：
    - database.db_session.get_async_engine → 返回 SQLite engine
    - CustomerDispatchService.ensure_table → 跳过（表已手动创建）
    - CustomerDispatchService.get_plan → 返回 mock plan（跳过权限检查）
    - CustomerDispatchService._fetch_lead_details → 返回空列表（customer_lead 表不存在）

    这样 get_next_for_account / batch_mark_replied 的核心调度 SQL 能在 SQLite 上真实执行，
    完整验证去重与漏单补发逻辑，且不依赖远程 PostgreSQL。
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # 内存库需共享同一连接池，否则表会丢失
    )
    plan_id = "test_plan_001"

    async with engine.begin() as conn:
        await conn.execute(sql_text(_CREATE_RECORD_TABLE))
        await conn.execute(sql_text(_CREATE_PLAN_TABLE))
        await conn.execute(sql_text(_CREATE_ACCOUNT_TABLE))
        await conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_cdr_plan_status "
            "ON customer_dispatch_record(plan_id, status, customer_seq)"
        ))
        await conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_cdr_plan_account "
            "ON customer_dispatch_record(plan_id, assigned_account_idx, status)"
        ))

        # 插入 1 个 plan
        await conn.execute(sql_text(
            "INSERT INTO customer_dispatch_plan(plan_id, name, platform, total_customers, total_accounts, status) "
            "VALUES (:pid, '测试计划-10账号1000客户', 'douyin', 1000, 10, 'active')"
        ), {"pid": plan_id})

        # 插入 10 个账号（区间对齐用户场景）
        for i, (start, end) in enumerate(EXPECTED_RANGES, 1):
            await conn.execute(sql_text(
                "INSERT INTO customer_dispatch_account"
                "(plan_id, account_idx, account_alias, range_start, range_end, batch_size, total_assigned) "
                "VALUES (:pid, :idx, :alias, :rs, :re, :bs, :ta)"
            ), {
                "pid": plan_id, "idx": i, "alias": f"账号{i}",
                "rs": start, "re": end,
                "bs": USER_BATCH_SIZES[i - 1],
                "ta": end - start + 1,
            })

        # 插入 1000 个客户记录（lead_id 9900000~9900999，seq 1~1000）
        for seq in range(1, 1001):
            lead_id = 9900000 + seq - 1
            acc_idx = CustomerDispatchService._find_account_for_seq(seq, EXPECTED_RANGES)
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
             return_value={"plan_id": plan_id, "name": "测试计划", "status": "active"},
         ), \
         patch.object(
             CustomerDispatchService, "_fetch_lead_details",
             new_callable=AsyncMock, return_value=[],
         ):
        yield engine, service, plan_id

    await engine.dispose()


# ----------------------------------------------------------------
# 调度逻辑：本区间取数 + 区间连续
# ----------------------------------------------------------------

class TestDispatchOwnRange:
    """账号本区间取数测试"""

    async def test_account1_fetch_own_range(self, dispatch_db):
        """账号1 取 20 个：本区间 #0001-#0020"""
        _, service, plan_id = dispatch_db
        result = await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        assert result["ok"] is True
        assert result["own_count"] == 20
        assert result["leaked_count"] == 0
        assert result["seqs"] == list(range(1, 21))
        assert result["customer_lead_ids"] == list(range(9900000, 9900020))

    async def test_account2_fetch_continuous_after_account1(self, dispatch_db):
        """账号2 取数：区间连续（接续 #0021）"""
        _, service, plan_id = dispatch_db
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        result = await service.get_next_for_account(plan_id, account_idx=2, batch_size=20, is_admin=True)
        assert result["ok"] is True
        assert result["own_count"] == 20
        assert result["leaked_count"] == 0
        assert result["seqs"] == list(range(21, 41)), "账号2 应接续账号1 从 #0021 开始"

    async def test_account3_fetch_own_range(self, dispatch_db):
        """账号3 取 30 个：本区间 #0059-#0088"""
        _, service, plan_id = dispatch_db
        result = await service.get_next_for_account(plan_id, account_idx=3, batch_size=30, is_admin=True)
        assert result["own_count"] == 30
        assert result["seqs"] == list(range(59, 89))

    async def test_account10_fetch_large_batch(self, dispatch_db):
        """账号10 取 412 个：本区间 #0589-#1000"""
        _, service, plan_id = dispatch_db
        result = await service.get_next_for_account(plan_id, account_idx=10, batch_size=412, is_admin=True)
        assert result["own_count"] == 412
        assert result["seqs"][0] == 589
        assert result["seqs"][-1] == 1000


# ----------------------------------------------------------------
# 调度逻辑：去重机制
# ----------------------------------------------------------------

class TestDispatchDedup:
    """去重机制测试：已回复客户被所有账号跳过"""

    async def test_mark_replied_success(self, dispatch_db):
        """标记已回复成功"""
        _, service, plan_id = dispatch_db
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        ok = await service.batch_mark_replied(
            plan_id, [9900000, 9900001, 9900002, 9900003, 9900004],
            account_idx=1, is_admin=True,
        )
        assert ok == 5

    async def test_mark_replied_twice_returns_false(self, dispatch_db):
        """重复标记已回复：第二次失败（已回复不可重复标记）"""
        _, service, plan_id = dispatch_db
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        await service.batch_mark_replied(plan_id, [9900000], account_idx=1, is_admin=True)
        # 第二次标记同一客户
        ok = await service.batch_mark_replied(plan_id, [9900000], account_idx=1, is_admin=True)
        assert ok == 0, "已回复客户重复标记应返回 0"

    async def test_replied_customer_not_fetched_again(self, dispatch_db):
        """去重：已回复客户不会被漏单补发再次取到"""
        _, service, plan_id = dispatch_db
        # 账号1取20个(sent)，账号2取20个(sent)
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        await service.get_next_for_account(plan_id, account_idx=2, batch_size=20, is_admin=True)
        # 标记账号2区间前3个(seq 21-23, lead 9900020-9900022)为已回复
        await service.batch_mark_replied(
            plan_id, [9900020, 9900021, 9900022], account_idx=2, is_admin=True,
        )
        # 账号1漏单补发20个：账号2有 20-3=17 个 sent 未回复可补，故 leaked=17
        result = await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        assert result["leaked_count"] == 17, "账号2的20个sent中3个已replied，只剩17个漏单可补"
        assert result["own_count"] == 0
        # 验证取到的 seq 不包含已回复的 21-23
        replied_seqs = {21, 22, 23}
        for seq in result["seqs"]:
            assert seq not in replied_seqs, f"已回复 seq={seq} 不应被补发（去重失败）"

    async def test_replied_lead_id_not_in_any_fetch(self, dispatch_db):
        """去重：已回复的 lead_id 不会出现在任何后续取数结果中"""
        _, service, plan_id = dispatch_db
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        await service.batch_mark_replied(plan_id, [9900000, 9900001], account_idx=1, is_admin=True)
        # 账号1再取（漏单补发），验证 lead_id 不含已回复的
        await service.get_next_for_account(plan_id, account_idx=2, batch_size=20, is_admin=True)
        result = await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        replied_leads = {9900000, 9900001}
        for lid in result["customer_lead_ids"]:
            assert lid not in replied_leads, f"已回复 lead_id={lid} 不应被取到"


# ----------------------------------------------------------------
# 调度逻辑：漏单补发
# ----------------------------------------------------------------

class TestDispatchLeakFill:
    """漏单补发测试：本区间发完后补发其他账号 sent 未回复客户"""

    async def test_leak_fill_from_other_account_range(self, dispatch_db):
        """漏单补发：账号1发完后补发账号2区间的漏单"""
        _, service, plan_id = dispatch_db
        # 账号1取20个(sent)，账号2取20个(sent)
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        await service.get_next_for_account(plan_id, account_idx=2, batch_size=20, is_admin=True)
        # 账号1再取：本区间已发完，应补发账号2区间漏单
        result = await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        assert result["ok"] is True
        assert result["own_count"] == 0, "账号1本区间已发完，own 应为 0"
        assert result["leaked_count"] == 20, "应补发 20 个漏单"
        # 验证取到的 seq 全部在账号2区间(21-58)
        for seq in result["seqs"]:
            assert 21 <= seq <= 58, f"漏单 seq={seq} 应在账号2区间(21-58)"

    async def test_leak_fill_excludes_own_sent(self, dispatch_db):
        """漏单补发排除自己已发的（避免重复发）"""
        _, service, plan_id = dispatch_db
        # 账号1取20个(sent)
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        # 账号1再取：本区间已发完，但其他账号还没发，无漏单可补
        result = await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        assert result["own_count"] == 0
        assert result["leaked_count"] == 0, "其他账号未发，无漏单可补"
        assert result["customers"] == []

    async def test_leak_fill_partial_batch(self, dispatch_db):
        """漏单补发部分填充：本区间剩 10 个 + 漏单补 10 个"""
        _, service, plan_id = dispatch_db
        # 账号1先取10个(batch_size=10)
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=10, is_admin=True)
        # 账号2取20个(sent)
        await service.get_next_for_account(plan_id, account_idx=2, batch_size=20, is_admin=True)
        # 账号1再取20个：本区间剩10个 + 漏单补10个
        result = await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        assert result["own_count"] == 10, "本区间还剩 10 个 pending"
        assert result["leaked_count"] == 10, "补发 10 个漏单"
        assert len(result["seqs"]) == 20

    async def test_leak_fill_order_by_seq(self, dispatch_db):
        """漏单补发按 seq 升序（跨多账号区间）"""
        _, service, plan_id = dispatch_db
        # 账号1先取完本区间20个(sent)
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        # 账号2、账号3各取20个(sent)
        await service.get_next_for_account(plan_id, account_idx=2, batch_size=20, is_admin=True)
        await service.get_next_for_account(plan_id, account_idx=3, batch_size=20, is_admin=True)
        # 账号1漏单补发30个：应先补账号2区间(seq 21-40)再补账号3区间(seq 59-68)
        result = await service.get_next_for_account(plan_id, account_idx=1, batch_size=30, is_admin=True)
        assert result["own_count"] == 0, "账号1本区间已发完"
        assert result["leaked_count"] == 30
        # seqs 应升序
        assert result["seqs"] == sorted(result["seqs"])
        # 前20个在账号2区间(21-40)，后10个在账号3区间(59-68)
        first_batch = result["seqs"][:20]
        second_batch = result["seqs"][20:]
        for seq in first_batch:
            assert 21 <= seq <= 40
        for seq in second_batch:
            assert 59 <= seq <= 68

    async def test_no_leak_available_returns_empty(self, dispatch_db):
        """无漏单可补时返回空（本区间已发完且无其他账号漏单）"""
        _, service, plan_id = dispatch_db
        # 账号10取完全区间412个
        await service.get_next_for_account(plan_id, account_idx=10, batch_size=412, is_admin=True)
        # 再取：本区间已发完，其他账号没发，无漏单
        result = await service.get_next_for_account(plan_id, account_idx=10, batch_size=20, is_admin=True)
        assert result["ok"] is True
        assert result["own_count"] == 0
        assert result["leaked_count"] == 0
        assert result["customers"] == []
        assert "无待发客户" in result.get("message", "")


# ----------------------------------------------------------------
# 调度逻辑：全覆盖验证
# ----------------------------------------------------------------

class TestDispatchFullCoverage:
    """10 账号全覆盖测试"""

    async def test_10_accounts_sequential_total_1000(self, dispatch_db):
        """10 账号依次取数，总和=1000（全覆盖无遗漏）"""
        _, service, plan_id = dispatch_db
        total_fetched = 0
        all_seqs = []
        for idx in range(1, 11):
            bs = USER_BATCH_SIZES[idx - 1]
            result = await service.get_next_for_account(
                plan_id, account_idx=idx, batch_size=bs, is_admin=True,
            )
            assert result["ok"] is True
            total_fetched += len(result["seqs"])
            all_seqs.extend(result["seqs"])
        assert total_fetched == 1000, f"10账号取数总和={total_fetched}, 期望=1000"
        # 验证 seq 唯一（无重复取数）
        assert len(set(all_seqs)) == 1000, "存在重复 seq，去重失败"
        # 验证覆盖 1~1000
        assert set(all_seqs) == set(range(1, 1001))

    async def test_full_flow_dedup_and_leak_fill(self, dispatch_db):
        """完整流程：取数→标记已回复→漏单补发→验证去重与补发正确"""
        _, service, plan_id = dispatch_db
        # 1. 账号1取20个(本区间 #0001-#0020)
        r1 = await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        assert r1["own_count"] == 20
        assert r1["leaked_count"] == 0
        # 2. 标记账号1前5个为已回复（去重）
        replied_leads = r1["customer_lead_ids"][:5]
        ok = await service.batch_mark_replied(plan_id, replied_leads, account_idx=1, is_admin=True)
        assert ok == 5
        # 3. 账号2取20个(本区间 #0021-#0040，区间连续)
        r2 = await service.get_next_for_account(plan_id, account_idx=2, batch_size=20, is_admin=True)
        assert r2["own_count"] == 20
        assert r2["seqs"][0] == 21, "账号2 应接续 #0021"
        # 4. 账号1漏单补发20个（补发账号2区间的 sent 未回复客户）
        r3 = await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        assert r3["own_count"] == 0, "账号1本区间已发完"
        assert r3["leaked_count"] == 20, "应补发账号2区间20个漏单"
        # 5. 验证漏单补发的客户全部在账号2区间(lead 9900020-9900039)
        for lid in r3["customer_lead_ids"]:
            assert 9900020 <= lid <= 9900039, f"漏单 lead={lid} 应在账号2区间"
        # 6. 验证漏单补发的客户不包含已回复的(去重生效)
        replied_set = set(replied_leads)
        for lid in r3["customer_lead_ids"]:
            assert lid not in replied_set, f"已回复 lead={lid} 不应被补发"
        # 7. 验证 r1 和 r2 的客户不重叠（不同账号区间）
        r1_set = set(r1["customer_lead_ids"])
        r2_set = set(r2["customer_lead_ids"])
        assert r1_set.isdisjoint(r2_set), "账号1和账号2区间客户不应重叠"
        # 8. 验证 r3 补发的是 r2 的客户（漏单补发=同一批客户被另一账号重发）
        assert set(r3["customer_lead_ids"]) == r2_set, "漏单补发应取账号2已发但未回复的客户"
