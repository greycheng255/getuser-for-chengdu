# -*- coding: utf-8 -*-
"""
custom_ranges 端到端集成测试 —— 5 账号 50% 重叠并发压力测试

模拟真实生产环境：
- 5 账号，180 客户，区间 50% 重叠（每相邻账号重叠 30 客户）
- 5 账号 asyncio.gather 并发取数
- 链式跨账号去重：账号2标记→账号3跳过、账号3标记→账号4跳过、账号5标记→账号4跳过（反向）
- 漏单补发 + 全覆盖 + 并发安全 + 统计验证

区间设计（50% 重叠）：
  账号1: #0001-0060  (60 客户)
  账号2: #0031-0090  (与账号1重叠 #0031-0060 = 30 客户 = 50%)
  账号3: #0061-0120  (与账号2重叠 #0061-0090 = 30 客户 = 50%)
  账号4: #0091-0150  (与账号3重叠 #0091-0120 = 30 客户 = 50%)
  账号5: #0121-0180  (与账号4重叠 #0121-0150 = 30 客户 = 50%)

  总客户: 180
  总记录: 300（重叠区每个客户2条记录）
    seq 1-30:   仅账号1 → 1 条 × 30 = 30
    seq 31-60:  账号1+2 → 2 条 × 30 = 60
    seq 61-90:  账号2+3 → 2 条 × 30 = 60
    seq 91-120: 账号3+4 → 2 条 × 30 = 60
    seq 121-150:账号4+5 → 2 条 × 30 = 60
    seq 151-180:仅账号5 → 1 条 × 30 = 30

运行方式：
    cd /home/ubuntu/getuser-for-chengdu/MediaCrawler-main
    python3 -m pytest tests/test_custom_ranges_e2e.py -v
"""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text as sql_text
from sqlalchemy.pool import StaticPool

from api.services.dispatch.customer_dispatch_service import CustomerDispatchService


# ============ 常量 ============

TOTAL_ACCOUNTS = 5
TOTAL_CUSTOMERS = 180
# 5 账号区间（50% 重叠）
ACCOUNT_RANGES = [(1, 60), (31, 90), (61, 120), (91, 150), (121, 180)]
LEAD_ID_BASE = 50000  # lead_id = 50000 + seq


# ============ SQLite 兼容建表 SQL ============

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
    UNIQUE(plan_id, customer_seq, assigned_account_idx)
)
"""


@pytest.fixture
async def e2e_db():
    """端到端测试数据库：5 账号 180 客户 50% 重叠区间。

    区间配置：
      账号1: #0001-0060
      账号2: #0031-0090（与账号1重叠 #0031-0060）
      账号3: #0061-0120（与账号2重叠 #0061-0090）
      账号4: #0091-0150（与账号3重叠 #0091-0120）
      账号5: #0121-0180（与账号4重叠 #0121-0150）

    总记录数 = 300 条
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    plan_id = "e2e_5account_overlap_plan"

    async with engine.begin() as conn:
        await conn.execute(sql_text(_CREATE_PLAN_TABLE))
        await conn.execute(sql_text(_CREATE_ACCOUNT_TABLE))
        await conn.execute(sql_text(_CREATE_RECORD_TABLE))
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
            "VALUES (:pid, 'E2E-5账号50%重叠压力测试', 'douyin', :tc, :ta, 'active')"
        ), {"pid": plan_id, "tc": TOTAL_CUSTOMERS, "ta": TOTAL_ACCOUNTS})

        # 插入 5 个账号
        for idx, (start, end) in enumerate(ACCOUNT_RANGES, 1):
            await conn.execute(sql_text(
                "INSERT INTO customer_dispatch_account"
                "(plan_id, account_idx, account_alias, range_start, range_end, batch_size, total_assigned) "
                "VALUES (:pid, :idx, :alias, :rs, :re, :bs, :ta)"
            ), {
                "pid": plan_id, "idx": idx, "alias": f"账号{idx}",
                "rs": start, "re": end, "bs": end - start + 1,
                "ta": end - start + 1,
            })

        # 插入 180 客户记录（重叠区多账号各一条）
        for seq in range(1, TOTAL_CUSTOMERS + 1):
            lead_id = LEAD_ID_BASE + seq
            acc_indices = CustomerDispatchService._find_accounts_for_seq(seq, ACCOUNT_RANGES)
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
             return_value={"plan_id": plan_id, "name": "E2E-5账号压力测试", "status": "active"},
         ), \
         patch.object(
             CustomerDispatchService, "_fetch_lead_details",
             new_callable=AsyncMock, return_value=[],
         ):
        yield engine, service, plan_id

    await engine.dispose()


def _leads_for_seqs(seqs):
    """seq 列表 → lead_id 列表"""
    return [LEAD_ID_BASE + s for s in seqs]


# ================================================================
# 端到端集成测试（8 个阶段）
# ================================================================

class TestE2E5AccountConcurrent:
    """5 账号 50% 重叠端到端集成测试"""

    async def test_phase1_concurrent_fetch_round1(self, e2e_db):
        """阶段1：5 账号并发取数（各取 20 个），验证本区间取数正确性

        预期（各账号本区间 pending 按 seq 升序）：
        - 账号1 取 seq 1-20
        - 账号2 取 seq 31-50
        - 账号3 取 seq 61-80
        - 账号4 取 seq 91-110
        - 账号5 取 seq 121-140
        """
        _, service, plan_id = e2e_db

        results = await asyncio.gather(*[
            service.get_next_for_account(plan_id, account_idx=i, batch_size=20, is_admin=True)
            for i in range(1, 6)
        ])

        expected = {
            1: list(range(1, 21)),
            2: list(range(31, 51)),
            3: list(range(61, 81)),
            4: list(range(91, 111)),
            5: list(range(121, 141)),
        }

        for idx, r in enumerate(results, 1):
            assert r["ok"] is True, f"账号{idx} 取数失败"
            assert r["own_count"] == 20, f"账号{idx} own_count={r['own_count']}"
            assert r["leaked_count"] == 0, f"账号{idx} 不应有漏单补发"
            assert r["seqs"] == expected[idx], \
                f"账号{idx} 应取 seq {expected[idx][0]}-{expected[idx][-1]}，实际 {r['seqs']}"

        # 验证 5 账号取到的 seq 互不重叠
        all_seqs = []
        for r in results:
            all_seqs.extend(r["seqs"])
        assert len(all_seqs) == len(set(all_seqs)), "5 账号取到的 seq 有重复"

    async def test_phase2_account2_mark_replied_account3_skips(self, e2e_db):
        """阶段2：账号2标记 replied 后账号3取数跳过（核心：相邻下游跨账号去重）

        场景：账号2区间 #0031-0090，账号3区间 #0061-0120，重叠区 #0061-0090

        流程：
        1. 账号2取 seq 31-50（20个 sent）
        2. 账号2取 seq 51-60（10个 sent，进入重叠区 #0031-0060 的后半段）
           等等，seq 51-60 在账号2区间 #0031-0090 内，但也在账号1区间 #0001-0060 内（重叠区 #0031-0060）
           不在账号3区间 #0061-0120 内
        3. 账号2取 seq 61-70（10个 sent，进入重叠区 #0061-0090，账号2+账号3）
        4. 账号2标记 seq 61-65 为 replied（lead 50061-50065）
           → mark_replied 按 lead_id 更新，账号3的 assigned_account_idx=3 的 seq 61-65 也变 replied
        5. 账号3取 20 个 → 本区间 pending：
           seq 61-65 的 assigned_account_idx=3 记录已 replied → 跳过
           取 seq 66-85（20个 pending，跳过 61-65）

        验证：账号3取到的 seq 不含 61-65
        """
        _, service, plan_id = e2e_db

        # 账号2取 30 个（seq 31-60，本区间 pending 前 30 个）
        r2a = await service.get_next_for_account(plan_id, account_idx=2, batch_size=30, is_admin=True)
        assert r2a["seqs"] == list(range(31, 61))

        # 账号2再取 10 个（seq 61-70，进入重叠区 #0061-0090）
        r2b = await service.get_next_for_account(plan_id, account_idx=2, batch_size=10, is_admin=True)
        assert r2b["seqs"] == list(range(61, 71))

        # 账号2标记 seq 61-65 为 replied（重叠区 #0061-0090，影响账号3）
        replied_seqs = [61, 62, 63, 64, 65]
        replied_leads = _leads_for_seqs(replied_seqs)
        ok = await service.batch_mark_replied(plan_id, replied_leads, account_idx=2, is_admin=True)
        assert ok == 5, f"账号2标记 replied 应成功 5 个，实际 {ok}"

        # 账号3取 20 个 → 跳过 seq 61-65（replied），取 seq 66-85
        r3 = await service.get_next_for_account(plan_id, account_idx=3, batch_size=20, is_admin=True)
        assert r3["ok"] is True
        assert r3["own_count"] == 20

        # 核心验证：账号3取到的 seq 不含 61-65（跨账号去重生效）
        replied_set = set(replied_seqs)
        for seq in r3["seqs"]:
            assert seq not in replied_set, \
                f"跨账号去重失败：账号3取到了账号2已标记 replied 的 seq={seq}"

        # 账号3应取 seq 66-85（跳过 replied 61-65）
        assert r3["seqs"] == list(range(66, 86)), \
            f"账号3应取 seq 66-85（跳过 replied 61-65），实际 {r3['seqs']}"

    async def test_phase3_chained_dedup_account3_to_account4(self, e2e_db):
        """阶段3：链式去重 —— 账号3标记 replied 后账号4取数跳过

        场景：账号3区间 #0061-0120，账号4区间 #0091-0150，重叠区 #0091-0120

        流程：
        1. 账号3取 seq 61-80（20个 sent）
        2. 账号3取 seq 81-95（15个 sent，进入重叠区 #0091-0120）
        3. 账号3标记 seq 91-95 为 replied
           → 账号4的 assigned_account_idx=4 的 seq 91-95 也变 replied
        4. 账号4取 20 个 → 跳过 seq 91-95，取 seq 96-115

        验证：账号4取到的 seq 不含 91-95
        """
        _, service, plan_id = e2e_db

        # 账号3取 35 个（seq 61-95）
        r3a = await service.get_next_for_account(plan_id, account_idx=3, batch_size=35, is_admin=True)
        assert r3a["seqs"] == list(range(61, 96))

        # 账号3标记 seq 91-95 为 replied（重叠区 #0091-0120，影响账号4）
        replied_seqs = [91, 92, 93, 94, 95]
        replied_leads = _leads_for_seqs(replied_seqs)
        ok = await service.batch_mark_replied(plan_id, replied_leads, account_idx=3, is_admin=True)
        assert ok == 5

        # 账号4取 20 个 → 跳过 seq 91-95（replied），取 seq 96-115
        r4 = await service.get_next_for_account(plan_id, account_idx=4, batch_size=20, is_admin=True)
        assert r4["ok"] is True
        assert r4["own_count"] == 20

        replied_set = set(replied_seqs)
        for seq in r4["seqs"]:
            assert seq not in replied_set, \
                f"链式去重失败：账号4取到了账号3已标记 replied 的 seq={seq}"

        assert r4["seqs"] == list(range(96, 116)), \
            f"账号4应取 seq 96-115（跳过 replied 91-95），实际 {r4['seqs']}"

    async def test_phase4_reverse_dedup_account5_to_account4(self, e2e_db):
        """阶段4：反向去重 —— 账号5标记 replied 后账号4取数跳过

        场景：账号4区间 #0091-0150，账号5区间 #0121-0180，重叠区 #0121-0150

        流程：
        1. 账号4取 seq 91-110（20个 sent）
        2. 账号4取 seq 111-125（15个 sent，进入重叠区 #0121-0150）
        3. 账号5标记 seq 121-125 为 replied
           → 账号4的 assigned_account_idx=4 的 seq 121-125 也变 replied
        4. 账号4再取 20 个 → 跳过 seq 121-125（replied），取 seq 126-145

        验证：账号4取到的 seq 不含 121-125（反向跨账号去重生效）
        """
        _, service, plan_id = e2e_db

        # 账号4取 35 个（seq 91-125）
        r4a = await service.get_next_for_account(plan_id, account_idx=4, batch_size=35, is_admin=True)
        assert r4a["seqs"] == list(range(91, 126))

        # 账号5标记 seq 121-125 为 replied（重叠区 #0121-0150，影响账号4）
        replied_seqs = [121, 122, 123, 124, 125]
        replied_leads = _leads_for_seqs(replied_seqs)
        ok = await service.batch_mark_replied(plan_id, replied_leads, account_idx=5, is_admin=True)
        assert ok == 5

        # 账号4再取 20 个 → 跳过 seq 121-125（replied），取 seq 126-145
        r4b = await service.get_next_for_account(plan_id, account_idx=4, batch_size=20, is_admin=True)
        assert r4b["ok"] is True

        replied_set = set(replied_seqs)
        for seq in r4b["seqs"]:
            assert seq not in replied_set, \
                f"反向去重失败：账号4取到了账号5已标记 replied 的 seq={seq}"

        # 账号4应取 seq 126-145（跳过 replied 121-125）
        assert r4b["seqs"] == list(range(126, 146)), \
            f"账号4应取 seq 126-145（跳过 replied 121-125），实际 {r4b['seqs']}"

    async def test_phase5_concurrent_leak_fill(self, e2e_db):
        """阶段5：5 账号并发漏单补发

        流程：
        1. 5 账号各取 40 个（本区间大部分发完）
        2. 5 账号再次并发取数，触发漏单补发
        3. 验证补发时跳过 replied，不重复取自己已发的
        """
        _, service, plan_id = e2e_db

        # 第一轮：5 账号各取 40 个
        await asyncio.gather(*[
            service.get_next_for_account(plan_id, account_idx=i, batch_size=40, is_admin=True)
            for i in range(1, 6)
        ])

        # 账号1标记 seq 1-5 为 replied
        await service.batch_mark_replied(
            plan_id, _leads_for_seqs([1, 2, 3, 4, 5]), account_idx=1, is_admin=True,
        )

        # 第二轮：5 账号并发取数（触发漏单补发）
        results = await asyncio.gather(*[
            service.get_next_for_account(plan_id, account_idx=i, batch_size=30, is_admin=True)
            for i in range(1, 6)
        ])

        for idx, r in enumerate(results, 1):
            assert r["ok"] is True, f"账号{idx} 第二轮取数失败"

        # 验证 replied 的 seq 1-5 不被任何账号漏单补发取到
        replied_set = {1, 2, 3, 4, 5}
        for idx, r in enumerate(results, 1):
            for seq in r["seqs"]:
                assert seq not in replied_set, \
                    f"漏单补发去重失败：账号{idx} 取到了 replied seq={seq}"

    async def test_phase6_full_coverage_no_pending_left(self, e2e_db):
        """阶段6：全覆盖验证 —— 循环取数直到无客户可取，验证 0 pending 残留

        流程：
        1. 5 账号循环取数（每轮各取 30 个），直到所有账号都无客户可取
        2. 验证所有 300 条记录都已变为 sent 或 replied（pending=0）
        3. 验证所有 sent/replied 记录的 sent_by_account > 0
        """
        engine, service, plan_id = e2e_db

        max_rounds = 15
        for round_num in range(max_rounds):
            results = await asyncio.gather(*[
                service.get_next_for_account(plan_id, account_idx=i, batch_size=30, is_admin=True)
                for i in range(1, 6)
            ])
            total_this_round = sum(len(r["seqs"]) for r in results if r["ok"])
            if total_this_round == 0:
                break

        # 验证：无 pending 残留
        async with engine.begin() as conn:
            rows = await conn.execute(sql_text(
                "SELECT status, COUNT(*) FROM customer_dispatch_record "
                "WHERE plan_id = :pid GROUP BY status"
            ), {"pid": plan_id})
            status_counts = {row[0]: row[1] for row in rows.fetchall()}

        pending = status_counts.get("pending", 0)
        sent = status_counts.get("sent", 0)
        replied = status_counts.get("replied", 0)
        total = pending + sent + replied

        assert total == 300, f"总记录数应为 300，实际 {total}"
        assert pending == 0, \
            f"全覆盖验证失败：仍有 {pending} 条 pending 记录未取数"

        # 验证所有 sent/replied 记录都已分配 sent_by_account
        async with engine.begin() as conn:
            rows = await conn.execute(sql_text(
                "SELECT COUNT(*) FROM customer_dispatch_record "
                "WHERE plan_id = :pid AND status IN ('sent', 'replied') AND sent_by_account = 0"
            ), {"pid": plan_id})
            unassigned = rows.scalar()
            assert unassigned == 0, f"有 {unassigned} 条记录未分配发送账号"

    async def test_phase7_concurrent_safety_no_race(self, e2e_db):
        """阶段7：并发安全性 —— 5 账号同时取 60 个（超过本区间容量），无竞态

        验证：sent 记录总数 = 5 账号取数总数（无同一记录被两账号同时取到）
        """
        engine, service, plan_id = e2e_db

        results = await asyncio.gather(*[
            service.get_next_for_account(plan_id, account_idx=i, batch_size=60, is_admin=True)
            for i in range(1, 6)
        ])

        for idx, r in enumerate(results, 1):
            assert r["ok"] is True, f"账号{idx} 取数失败: {r.get('reason')}"

        fetched_total = sum(len(r["seqs"]) for r in results)

        async with engine.begin() as conn:
            rows = await conn.execute(sql_text(
                "SELECT COUNT(*) FROM customer_dispatch_record "
                "WHERE plan_id = :pid AND status = 'sent'"
            ), {"pid": plan_id})
            sent_total = rows.scalar()

        assert sent_total == fetched_total, \
            f"sent 记录数({sent_total}) != 取数总数({fetched_total})，存在并发竞态"

        # 各账号取到的 seq 无重复
        for idx, r in enumerate(results, 1):
            seqs = r["seqs"]
            assert len(seqs) == len(set(seqs)), \
                f"账号{idx} 取到的 seq 有重复: {seqs}"

    async def test_phase8_statistics_accuracy(self, e2e_db):
        """阶段8：统计验证 —— total_sent / total_replied 准确更新

        流程：
        1. 账号1取 20，账号2取 20，账号3取 20
        2. 账号1标记 5 个 replied，账号2标记 3 个 replied
        3. 验证各账号 total_sent / total_replied 正确
        """
        engine, service, plan_id = e2e_db

        # 3 账号各取 20
        await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
        await service.get_next_for_account(plan_id, account_idx=2, batch_size=20, is_admin=True)
        await service.get_next_for_account(plan_id, account_idx=3, batch_size=20, is_admin=True)

        # 账号1标记 5 个 replied（seq 1-5）
        await service.batch_mark_replied(
            plan_id, _leads_for_seqs([1, 2, 3, 4, 5]), account_idx=1, is_admin=True,
        )
        # 账号2标记 3 个 replied（seq 31-33）
        await service.batch_mark_replied(
            plan_id, _leads_for_seqs([31, 32, 33]), account_idx=2, is_admin=True,
        )

        # 查询统计
        async with engine.begin() as conn:
            rows = await conn.execute(sql_text(
                "SELECT account_idx, total_sent, total_replied "
                "FROM customer_dispatch_account WHERE plan_id = :pid "
                "ORDER BY account_idx"
            ), {"pid": plan_id})
            stats = {row[0]: {"sent": row[1], "replied": row[2]} for row in rows.fetchall()}

        # 账号1: sent=20, replied=5
        assert stats[1]["sent"] == 20, f"账号1 total_sent={stats[1]['sent']}, 期望 20"
        assert stats[1]["replied"] == 5, f"账号1 total_replied={stats[1]['replied']}, 期望 5"

        # 账号2: sent=20, replied=3
        assert stats[2]["sent"] == 20, f"账号2 total_sent={stats[2]['sent']}, 期望 20"
        assert stats[2]["replied"] == 3, f"账号2 total_replied={stats[2]['replied']}, 期望 3"

        # 账号3: sent=20, replied=0
        assert stats[3]["sent"] == 20, f"账号3 total_sent={stats[3]['sent']}, 期望 20"
        assert stats[3]["replied"] == 0, f"账号3 total_replied={stats[3]['replied']}, 期望 0"

        # 账号4/5: sent=0, replied=0
        assert stats[4]["sent"] == 0 and stats[4]["replied"] == 0
        assert stats[5]["sent"] == 0 and stats[5]["replied"] == 0
