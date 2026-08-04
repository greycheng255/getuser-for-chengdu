# -*- coding: utf-8 -*-
"""
端到端集成测试脚本 —— 多账号并发取数（模拟真实生产环境）

场景：5 账号 180 客户 50% 重叠区间
独立运行，不依赖远程服务，使用 SQLite 内存库
每个阶段使用独立数据库实例，互不干扰

运行方式：
    cd /home/ubuntu/getuser-for-chengdu/MediaCrawler-main
    python3 tests/e2e_concurrent_dispatch.py
"""
import asyncio
import sys
import os
import time
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text as sql_text
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.services.dispatch.customer_dispatch_service import CustomerDispatchService

# ============ 配置 ============
TOTAL_ACCOUNTS = 5
TOTAL_CUSTOMERS = 180
ACCOUNT_RANGES = [(1, 60), (31, 90), (61, 120), (91, 150), (121, 180)]
LEAD_ID_BASE = 50000

# ============ ANSI 颜色 ============
class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

# ============ 测试结果收集 ============
class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.details = []

    def record(self, name, status, detail=""):
        icon = "✅" if status == "pass" else "❌"
        self.details.append((name, status, detail))
        if status == "pass":
            self.passed += 1
            print(f"  {icon} {C.GREEN}{name}{C.RESET} {detail}")
        else:
            self.failed += 1
            print(f"  {icon} {C.RED}{name}{C.RESET} {detail}")

    def summary(self):
        total = self.passed + self.failed
        color = C.GREEN if self.failed == 0 else C.RED
        print(f"\n{'='*60}")
        print(f"{C.BOLD}测试结果汇总{C.RESET}")
        print(f"{'='*60}")
        print(f"  总用例: {total}  {color}通过: {self.passed}{C.RESET}  {C.RED}失败: {self.failed}{C.RESET}")
        for name, status, detail in self.details:
            icon = "✅" if status == "pass" else "❌"
            print(f"  {icon} {name}")
        print(f"{'='*60}")
        return self.failed == 0


# ============ SQLite 建表 SQL ============
_CREATE_PLAN_TABLE = """
CREATE TABLE IF NOT EXISTS customer_dispatch_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL, platform TEXT DEFAULT 'douyin',
    total_customers INTEGER DEFAULT 0, total_accounts INTEGER DEFAULT 0,
    filter_keywords TEXT DEFAULT '', min_lead_score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active', owner_user_id TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0
)"""
_CREATE_ACCOUNT_TABLE = """
CREATE TABLE IF NOT EXISTS customer_dispatch_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT NOT NULL,
    account_idx INTEGER NOT NULL, account_alias TEXT DEFAULT '',
    cookie_id TEXT DEFAULT '', range_start INTEGER DEFAULT 0,
    range_end INTEGER DEFAULT 0, batch_size INTEGER DEFAULT 20,
    total_assigned INTEGER DEFAULT 0, total_sent INTEGER DEFAULT 0,
    total_replied INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
    created_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0,
    UNIQUE(plan_id, account_idx)
)"""
_CREATE_RECORD_TABLE = """
CREATE TABLE IF NOT EXISTS customer_dispatch_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT NOT NULL,
    customer_lead_id INTEGER NOT NULL, customer_seq INTEGER NOT NULL,
    assigned_account_idx INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
    sent_by_account INTEGER DEFAULT 0, replied_by_account INTEGER DEFAULT 0,
    sent_at INTEGER DEFAULT 0, replied_at INTEGER DEFAULT 0,
    contact_log TEXT DEFAULT '', created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0,
    UNIQUE(plan_id, customer_seq, assigned_account_idx)
)"""


async def setup_database():
    """创建独立 SQLite 内存数据库，初始化 5 账号 180 客户 50% 重叠数据"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    plan_id = f"e2e_{int(time.time()*1000) % 1000000}"

    async with engine.begin() as conn:
        await conn.execute(sql_text(_CREATE_PLAN_TABLE))
        await conn.execute(sql_text(_CREATE_ACCOUNT_TABLE))
        await conn.execute(sql_text(_CREATE_RECORD_TABLE))
        await conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_cdr_plan_status "
            "ON customer_dispatch_record(plan_id, status, customer_seq)"))
        await conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS idx_cdr_plan_account "
            "ON customer_dispatch_record(plan_id, assigned_account_idx, status)"))

        await conn.execute(sql_text(
            "INSERT INTO customer_dispatch_plan"
            "(plan_id, name, platform, total_customers, total_accounts, status) "
            "VALUES (:pid, 'E2E并发取数测试', 'douyin', :tc, :ta, 'active')"
        ), {"pid": plan_id, "tc": TOTAL_CUSTOMERS, "ta": TOTAL_ACCOUNTS})

        for idx, (start, end) in enumerate(ACCOUNT_RANGES, 1):
            await conn.execute(sql_text(
                "INSERT INTO customer_dispatch_account"
                "(plan_id, account_idx, account_alias, range_start, range_end, batch_size, total_assigned) "
                "VALUES (:pid, :idx, :alias, :rs, :re, :bs, :ta)"
            ), {"pid": plan_id, "idx": idx, "alias": f"账号{idx}",
                "rs": start, "re": end, "bs": end - start + 1, "ta": end - start + 1})

        total_records = 0
        for seq in range(1, TOTAL_CUSTOMERS + 1):
            lead_id = LEAD_ID_BASE + seq
            for acc_idx in CustomerDispatchService._find_accounts_for_seq(seq, ACCOUNT_RANGES):
                await conn.execute(sql_text(
                    "INSERT INTO customer_dispatch_record"
                    "(plan_id, customer_lead_id, customer_seq, assigned_account_idx, status) "
                    "VALUES (:pid, :lid, :seq, :aidx, 'pending')"
                ), {"pid": plan_id, "lid": lead_id, "seq": seq, "aidx": acc_idx})
                total_records += 1

    return engine, plan_id, total_records


def make_service(engine, plan_id):
    """创建 mock 后的 CustomerDispatchService"""
    CustomerDispatchService._ensured = True
    service = CustomerDispatchService()
    patches = [
        patch("database.db_session.get_async_engine", return_value=engine),
        patch("config.SAVE_DATA_OPTION", "sqlite"),
        patch.object(CustomerDispatchService, "ensure_table", new_callable=AsyncMock),
        patch.object(CustomerDispatchService, "get_plan", new_callable=AsyncMock,
                     return_value={"plan_id": plan_id, "name": "E2E测试", "status": "active"}),
        patch.object(CustomerDispatchService, "_fetch_lead_details", new_callable=AsyncMock, return_value=[]),
    ]
    for p in patches:
        p.start()
    return service, patches


def _leads(seqs):
    return [LEAD_ID_BASE + s for s in seqs]


async def get_seq_status(engine, plan_id, seq):
    async with engine.begin() as conn:
        rows = await conn.execute(sql_text(
            "SELECT assigned_account_idx, status FROM customer_dispatch_record "
            "WHERE plan_id = :pid AND customer_seq = :seq ORDER BY assigned_account_idx"
        ), {"pid": plan_id, "seq": seq})
        return {r[0]: r[1] for r in rows.fetchall()}


async def count_status(engine, plan_id):
    async with engine.begin() as conn:
        rows = await conn.execute(sql_text(
            "SELECT status, COUNT(*) FROM customer_dispatch_record "
            "WHERE plan_id = :pid GROUP BY status"
        ), {"pid": plan_id})
        return {row[0]: row[1] for row in rows.fetchall()}


async def run_isolated(results, test_func, phase_name):
    """独立数据库隔离运行单个测试阶段"""
    engine, plan_id, total = await setup_database()
    service, patches = make_service(engine, plan_id)
    try:
        await test_func(results, service, plan_id, engine)
    finally:
        for p in patches:
            p.stop()
        await engine.dispose()


# ================================================================
# 测试阶段
# ================================================================

async def test_phase1(results, service, plan_id, engine):
    """阶段1：5 账号并发取数（各取 20 个）"""
    print(f"\n{C.CYAN}── 阶段1：5 账号并发取数（独立数据库） ──{C.RESET}")

    results_data = await asyncio.gather(*[
        service.get_next_for_account(plan_id, account_idx=i, batch_size=20, is_admin=True)
        for i in range(1, 6)
    ])

    expected = {1: list(range(1, 21)), 2: list(range(31, 51)), 3: list(range(61, 81)),
                4: list(range(91, 111)), 5: list(range(121, 141))}

    for idx, r in enumerate(results_data, 1):
        exp = expected[idx]
        ok = r["ok"] and r["own_count"] == 20 and r["seqs"] == exp
        results.record(f"阶段1-账号{idx}取数", "pass" if ok else "fail",
                       f"seq #{exp[0]:04d}-#{exp[-1]:04d}" if ok else f"期望{exp}, 实际{r.get('seqs')}")

    all_seqs = [s for r in results_data for s in r["seqs"]]
    results.record("阶段1-seq互不重叠", "pass" if len(all_seqs) == len(set(all_seqs)) else "fail",
                   f"共{len(all_seqs)}个seq")


async def test_phase2(results, service, plan_id, engine):
    """阶段2：账号2标记 replied 后账号3取数跳过（核心：跨账号去重）"""
    print(f"\n{C.CYAN}── 阶段2：账号2→账号3 跨账号去重验证（独立数据库） ──{C.RESET}")
    print(f"  重叠区: 账号2 #0031-0090 ∩ 账号3 #0061-0120 = #0061-0090")

    # 账号2取 30 个 → seq 31-60（独立数据库，从 seq 31 开始）
    r2a = await service.get_next_for_account(plan_id, account_idx=2, batch_size=30, is_admin=True)
    print(f"  步骤1: 账号2取30个 → seq #{r2a['seqs'][0]:04d}-#{r2a['seqs'][-1]:04d}")
    results.record("阶段2-账号2第一轮(seq31-60)", "pass" if r2a["seqs"] == list(range(31, 61)) else "fail",
                   f"实际 #{r2a['seqs'][0]:04d}-#{r2a['seqs'][-1]:04d}")

    # 账号2取 10 个 → seq 61-70（进入重叠区 #0061-0090）
    r2b = await service.get_next_for_account(plan_id, account_idx=2, batch_size=10, is_admin=True)
    print(f"  步骤2: 账号2取10个 → seq #{r2b['seqs'][0]:04d}-#{r2b['seqs'][-1]:04d}（重叠区）")
    results.record("阶段2-账号2进入重叠区(seq61-70)", "pass" if r2b["seqs"] == list(range(61, 71)) else "fail",
                   f"实际 #{r2b['seqs'][0]:04d}-#{r2b['seqs'][-1]:04d}")

    # 标记前：检查 seq 61 的状态
    print(f"  步骤3: 标记前 seq 61/65 状态:")
    for seq in [61, 65]:
        st = await get_seq_status(engine, plan_id, seq)
        print(f"    seq={seq}: acc2={st.get(2)} acc3={st.get(3)}")

    # 账号2标记 seq 61-65 为 replied
    replied_seqs = [61, 62, 63, 64, 65]
    ok = await service.batch_mark_replied(plan_id, _leads(replied_seqs), account_idx=2, is_admin=True)
    print(f"  步骤4: 账号2标记 seq #0061-#0065 为 replied")
    results.record("阶段2-账号2标记replied", "pass" if ok == 5 else "fail", f"成功{ok}个")

    # 标记后：验证跨账号更新
    print(f"  步骤5: 标记后 seq 61-65 状态（验证跨账号更新）:")
    cross_ok = True
    for seq in replied_seqs:
        st = await get_seq_status(engine, plan_id, seq)
        print(f"    seq={seq}: acc2={st.get(2)} acc3={st.get(3)}")
        if st.get(2) != "replied" or st.get(3) != "replied":
            cross_ok = False
    results.record("阶段2-跨账号replied更新(acc2→acc3)", "pass" if cross_ok else "fail",
                   "账号2标记后账号3记录同步变replied" if cross_ok else "账号3记录未更新!")

    # 账号3取 20 个 → 跳过 seq 61-65（replied），取 seq 66-85
    r3 = await service.get_next_for_account(plan_id, account_idx=3, batch_size=20, is_admin=True)
    print(f"  步骤6: 账号3取20个 → seq #{r3['seqs'][0]:04d}-#{r3['seqs'][-1]:04d}")

    replied_set = set(replied_seqs)
    no_replied = all(s not in replied_set for s in r3["seqs"])
    correct = r3["seqs"] == list(range(66, 86))
    results.record("阶段2-账号3跳过replied(去重生效)", "pass" if no_replied and correct else "fail",
                   f"取 #{r3['seqs'][0]:04d}-#{r3['seqs'][-1]:04d}，不含 replied #0061-#0065" if no_replied else f"去重失败!")


async def test_phase3(results, service, plan_id, engine):
    """阶段3：链式去重 —— 账号3标记 replied 后账号4跳过"""
    print(f"\n{C.CYAN}── 阶段3：账号3→账号4 链式去重（独立数据库） ──{C.RESET}")
    print(f"  重叠区: 账号3 #0061-0120 ∩ 账号4 #0091-0150 = #0091-0120")

    # 账号3取 35 个 → seq 61-95
    r3 = await service.get_next_for_account(plan_id, account_idx=3, batch_size=35, is_admin=True)
    print(f"  账号3取35个 → seq #{r3['seqs'][0]:04d}-#{r3['seqs'][-1]:04d}")
    results.record("阶段3-账号3取数(seq61-95)", "pass" if r3["seqs"] == list(range(61, 96)) else "fail", "")

    # 账号3标记 seq 91-95 为 replied
    replied_seqs = [91, 92, 93, 94, 95]
    ok = await service.batch_mark_replied(plan_id, _leads(replied_seqs), account_idx=3, is_admin=True)
    print(f"  账号3标记 seq #0091-#0095 为 replied")
    results.record("阶段3-账号3标记replied", "pass" if ok == 5 else "fail", "")

    # 验证账号4记录也变 replied
    st91 = await get_seq_status(engine, plan_id, 91)
    results.record("阶段3-跨账号更新(acc3→acc4)", "pass" if st91.get(4) == "replied" else "fail",
                   f"seq91 acc4={st91.get(4)}")

    # 账号4取 20 个 → 跳过 seq 91-95，取 seq 96-115
    r4 = await service.get_next_for_account(plan_id, account_idx=4, batch_size=20, is_admin=True)
    no_replied = all(s not in set(replied_seqs) for s in r4["seqs"])
    correct = r4["seqs"] == list(range(96, 116))
    results.record("阶段3-账号4跳过replied", "pass" if no_replied and correct else "fail",
                   f"取 #{r4['seqs'][0]:04d}-#{r4['seqs'][-1]:04d}" if no_replied else f"失败!")


async def test_phase4(results, service, plan_id, engine):
    """阶段4：反向去重 —— 账号5标记 replied 后账号4跳过"""
    print(f"\n{C.CYAN}── 阶段4：账号5→账号4 反向去重（独立数据库） ──{C.RESET}")
    print(f"  重叠区: 账号4 #0091-0150 ∩ 账号5 #0121-0180 = #0121-0150")

    # 账号4取 35 个 → seq 91-125
    r4 = await service.get_next_for_account(plan_id, account_idx=4, batch_size=35, is_admin=True)
    print(f"  账号4取35个 → seq #{r4['seqs'][0]:04d}-#{r4['seqs'][-1]:04d}")
    results.record("阶段4-账号4取数(seq91-125)", "pass" if r4["seqs"] == list(range(91, 126)) else "fail", "")

    # 账号5标记 seq 121-125 为 replied
    replied_seqs = [121, 122, 123, 124, 125]
    ok = await service.batch_mark_replied(plan_id, _leads(replied_seqs), account_idx=5, is_admin=True)
    print(f"  账号5标记 seq #0121-#0125 为 replied")
    results.record("阶段4-账号5标记replied", "pass" if ok == 5 else "fail", "")

    # 验证账号4记录也变 replied（反向跨账号）
    st121 = await get_seq_status(engine, plan_id, 121)
    results.record("阶段4-反向跨账号更新(acc5→acc4)", "pass" if st121.get(4) == "replied" else "fail",
                   f"seq121 acc4={st121.get(4)}")

    # 账号4再取 20 个 → 跳过 seq 121-125，取 seq 126-145
    r4b = await service.get_next_for_account(plan_id, account_idx=4, batch_size=20, is_admin=True)
    no_replied = all(s not in set(replied_seqs) for s in r4b["seqs"])
    correct = r4b["seqs"] == list(range(126, 146))
    results.record("阶段4-账号4跳过replied(反向去重)", "pass" if no_replied and correct else "fail",
                   f"取 #{r4b['seqs'][0]:04d}-#{r4b['seqs'][-1]:04d}" if no_replied else f"失败!")


async def test_phase5(results, service, plan_id, engine):
    """阶段5：并发漏单补发 + 全覆盖验证"""
    print(f"\n{C.CYAN}── 阶段5：并发漏单补发 + 全覆盖（独立数据库） ──{C.RESET}")

    # 第一轮：5 账号各取 40 个
    await asyncio.gather(*[
        service.get_next_for_account(plan_id, account_idx=i, batch_size=40, is_admin=True)
        for i in range(1, 6)
    ])
    print(f"  第一轮: 5 账号各取 40 个")

    # 标记部分 replied
    await service.batch_mark_replied(plan_id, _leads([1, 2, 3]), account_idx=1, is_admin=True)
    print(f"  账号1标记 seq #0001-#0003 为 replied")

    # 第二轮：5 账号并发取数
    results_data = await asyncio.gather(*[
        service.get_next_for_account(plan_id, account_idx=i, batch_size=30, is_admin=True)
        for i in range(1, 6)
    ])
    replied_set = {1, 2, 3}
    all_ok = all(s not in replied_set for r in results_data if r["ok"] for s in r["seqs"])
    total_fetched = sum(len(r["seqs"]) for r in results_data if r["ok"])
    results.record("阶段5-并发漏单补发去重", "pass" if all_ok else "fail",
                   f"5账号共取{total_fetched}个，replied不被补发")

    # 循环取数直到无客户可取
    for round_num in range(15):
        results_data = await asyncio.gather(*[
            service.get_next_for_account(plan_id, account_idx=i, batch_size=30, is_admin=True)
            for i in range(1, 6)
        ])
        total = sum(len(r["seqs"]) for r in results_data if r["ok"])
        if total == 0:
            print(f"  全覆盖: 第{round_num+1}轮无客户可取")
            break

    status_counts = await count_status(engine, plan_id)
    pending = status_counts.get("pending", 0)
    total = sum(status_counts.values())
    print(f"  最终状态: pending={pending} sent={status_counts.get('sent',0)} replied={status_counts.get('replied',0)} total={total}")
    results.record("阶段5-全覆盖无遗漏", "pass" if pending == 0 and total == 300 else "fail",
                   f"pending={pending}(应为0) total={total}(应为300)")


async def test_phase6(results, service, plan_id, engine):
    """阶段6：并发安全性验证（无竞态）"""
    print(f"\n{C.CYAN}── 阶段6：并发安全性（独立数据库） ──{C.RESET}")

    # 5 账号同时取 60 个
    results_data = await asyncio.gather(*[
        service.get_next_for_account(plan_id, account_idx=i, batch_size=60, is_admin=True)
        for i in range(1, 6)
    ])

    fetched_total = sum(len(r["seqs"]) for r in results_data if r["ok"])
    status_counts = await count_status(engine, plan_id)
    sent_total = status_counts.get("sent", 0)
    print(f"  5账号并发各取60个: 取数总数={fetched_total} sent记录数={sent_total}")
    results.record("阶段6-并发无竞态", "pass" if sent_total == fetched_total else "fail",
                   f"sent({sent_total})==取数({fetched_total})" if sent_total == fetched_total else f"竞态!")

    all_ok = all(len(r["seqs"]) == len(set(r["seqs"])) for r in results_data if r["ok"])
    results.record("阶段6-各账号seq无重复", "pass" if all_ok else "fail", "")


async def test_phase7(results, service, plan_id, engine):
    """阶段7：统计准确性验证"""
    print(f"\n{C.CYAN}── 阶段7：统计准确性（独立数据库） ──{C.RESET}")

    await service.get_next_for_account(plan_id, account_idx=1, batch_size=20, is_admin=True)
    await service.get_next_for_account(plan_id, account_idx=2, batch_size=20, is_admin=True)
    await service.batch_mark_replied(plan_id, _leads([1, 2, 3, 4, 5]), account_idx=1, is_admin=True)

    async with engine.begin() as conn:
        rows = await conn.execute(sql_text(
            "SELECT account_idx, total_sent, total_replied "
            "FROM customer_dispatch_account WHERE plan_id = :pid ORDER BY account_idx"
        ), {"pid": plan_id})
        stats = {row[0]: {"sent": row[1], "replied": row[2]} for row in rows.fetchall()}

    s1 = stats[1]["sent"] == 20 and stats[1]["replied"] == 5
    s2 = stats[2]["sent"] == 20 and stats[2]["replied"] == 0
    print(f"  账号1: sent={stats[1]['sent']} replied={stats[1]['replied']} (期望 20/5)")
    print(f"  账号2: sent={stats[2]['sent']} replied={stats[2]['replied']} (期望 20/0)")
    results.record("阶段7-账号1统计", "pass" if s1 else "fail", f"sent={stats[1]['sent']} replied={stats[1]['replied']}")
    results.record("阶段7-账号2统计", "pass" if s2 else "fail", f"sent={stats[2]['sent']} replied={stats[2]['replied']}")


# ============ 主函数 ============

async def main():
    print(f"\n{C.BOLD}{'='*60}{C.RESET}")
    print(f"{C.BOLD}  custom_ranges 端到端集成测试 — 5 账号 50% 重叠并发取数{C.RESET}")
    print(f"{C.BOLD}  每阶段独立数据库实例，互不干扰{C.RESET}")
    print(f"{C.BOLD}{'='*60}{C.RESET}")
    print(f"  账号数: {TOTAL_ACCOUNTS}  客户数: {TOTAL_CUSTOMERS}  重叠比例: 50%")
    print(f"  区间配置:")
    for i, (s, e) in enumerate(ACCOUNT_RANGES, 1):
        overlap = ""
        if i > 1:
            ps, pe = ACCOUNT_RANGES[i - 2]
            os_, oe = max(s, ps), min(e, pe)
            if oe >= os_:
                overlap = f"  (与账号{i-1}重叠 #{os_:04d}-#{oe:04d}={oe-os_+1}客户)"
        print(f"    账号{i}: #{s:04d}-#{e:04d}{overlap}")

    results = Results()
    start = time.time()

    # 每个阶段独立数据库
    await run_isolated(results, test_phase1, "阶段1")
    await run_isolated(results, test_phase2, "阶段2")
    await run_isolated(results, test_phase3, "阶段3")
    await run_isolated(results, test_phase4, "阶段4")
    await run_isolated(results, test_phase5, "阶段5")
    await run_isolated(results, test_phase6, "阶段6")
    await run_isolated(results, test_phase7, "阶段7")

    elapsed = time.time() - start
    all_passed = results.summary()
    print(f"  耗时: {elapsed:.2f}s")
    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
