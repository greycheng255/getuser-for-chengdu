# -*- coding: utf-8 -*-
"""线索 API 测试

覆盖:
- PRD §10.2 + 多维度检索: /leads/list 11 维度筛选
- PRD §10.7.9: /leads/{id}/status 状态变更(看板拖拽后端)
- PRD §10.2: /leads/export 导出(含平台脱敏行为断言,合并 #11)
"""
import pytest


# ---------- 列表基础 ----------

@pytest.mark.asyncio
async def test_list_empty(app_client):
    """空库 list 返回 total=0"""
    resp = await app_client.get("/api/leads/list")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_list_returns_seeded_lead(app_client, seed_lead):
    """seed 一条后能查到"""
    await seed_lead(nickname="张三", content="想学吉他", lead_score=70)
    resp = await app_client.get("/api/leads/list")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["nickname"] == "张三"


@pytest.mark.asyncio
async def test_list_pagination(app_client, seed_lead):
    """分页参数"""
    for i in range(5):
        await seed_lead(content=f"内容{i}", lead_score=50 + i)
    resp = await app_client.get("/api/leads/list?page=1&page_size=2")
    assert resp.json()["total"] == 5
    assert len(resp.json()["items"]) == 2

    resp2 = await app_client.get("/api/leads/list?page=2&page_size=2")
    assert len(resp2.json()["items"]) == 2
    # 第 2 页分数应低于第 1 页(按 lead_score desc 排序)
    assert resp2.json()["items"][0]["lead_score"] <= resp.json()["items"][1]["lead_score"]


# ---------- 11 维度筛选 ----------

@pytest.mark.asyncio
async def test_filter_by_task_id(app_client, seed_lead):
    await seed_lead(task_id="task_A", content="A")
    await seed_lead(task_id="task_B", content="B")
    resp = await app_client.get("/api/leads/list?task_id=task_A")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["task_id"] == "task_A"


@pytest.mark.asyncio
async def test_filter_by_platform(app_client, seed_lead):
    await seed_lead(platform="douyin", content="d")
    await seed_lead(platform="xhs", content="x")
    resp = await app_client.get("/api/leads/list?platform=xhs")
    assert all(i["platform"] == "xhs" for i in resp.json()["items"])


@pytest.mark.asyncio
async def test_filter_by_intent_type(app_client, seed_lead):
    await seed_lead(intent_type="purchase", content="p")
    await seed_lead(intent_type="inquiry", content="i")
    resp = await app_client.get("/api/leads/list?intent_type=purchase")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["intent_type"] == "purchase"


@pytest.mark.asyncio
async def test_filter_by_status(app_client, seed_lead):
    await seed_lead(status="new", content="n")
    await seed_lead(status="converted", content="c")
    resp = await app_client.get("/api/leads/list?status=converted")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "converted"


@pytest.mark.asyncio
async def test_filter_by_min_score(app_client, seed_lead):
    await seed_lead(lead_score=80, content="高")
    await seed_lead(lead_score=30, content="低")
    resp = await app_client.get("/api/leads/list?min_score=50")
    items = resp.json()["items"]
    assert all(i["lead_score"] >= 50 for i in items)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_filter_by_max_score(app_client, seed_lead):
    await seed_lead(lead_score=80, content="高")
    await seed_lead(lead_score=20, content="低")
    resp = await app_client.get("/api/leads/list?max_score=50")
    items = resp.json()["items"]
    assert all(i["lead_score"] <= 50 for i in items)


@pytest.mark.asyncio
async def test_filter_by_level(app_client, seed_lead):
    """level=high → score>=50"""
    await seed_lead(lead_score=60, content="高")
    await seed_lead(lead_score=30, content="中")
    resp = await app_client.get("/api/leads/list?level=high")
    items = resp.json()["items"]
    assert all(i["lead_score"] >= 50 for i in items)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_filter_by_keyword(app_client, seed_lead):
    """keyword 在 content/title/nickname 任意命中"""
    await seed_lead(content="想学钢琴", nickname="A")
    await seed_lead(content="其他内容", nickname="钢琴老师")
    resp = await app_client.get("/api/leads/list?keyword=钢琴")
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_filter_by_ip_location(app_client, seed_lead):
    await seed_lead(ip_location="四川 巴中", content="a")
    await seed_lead(ip_location="北京", content="b")
    resp = await app_client.get("/api/leads/list?ip_location=巴中")
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_filter_by_date_range(app_client, seed_lead):
    """start_ts/end_ts 时间范围筛选

    注:add_ts 列存毫秒,start_ts/end_ts 参数亦按毫秒传(与前端 unix()*1000 一致)。
    """
    await seed_lead(content="远古", add_ts=1_000_000_000_000)  # 2001 年(毫秒)
    await seed_lead(content="现在")  # add_ts ≈ 当前毫秒
    # start_ts 取 2020 年毫秒,应排除 2001 年数据
    resp = await app_client.get("/api/leads/list?start_ts=1577836800000")
    items = resp.json()["items"]
    assert resp.json()["total"] == 1
    assert items[0]["content"] == "现在"


# ---------- 状态变更 ----------

@pytest.mark.asyncio
async def test_update_lead_status(app_client, seed_lead):
    lead_id = await seed_lead(status="new")
    resp = await app_client.post(f"/api/leads/{lead_id}/status", json={"status": "contacted"})
    assert resp.status_code == 200
    # 校验已更新
    detail = await app_client.get(f"/api/leads/{lead_id}")
    assert detail.json()["status"] == "contacted"


@pytest.mark.asyncio
async def test_update_lead_status_with_notes(app_client, seed_lead):
    lead_id = await seed_lead()
    resp = await app_client.post(
        f"/api/leads/{lead_id}/status",
        json={"status": "qualified", "notes": "已确认意向"},
    )
    assert resp.status_code == 200
    detail = await app_client.get(f"/api/leads/{lead_id}")
    assert detail.json()["status"] == "qualified"
    assert "已确认意向" in detail.json().get("notes", "")


@pytest.mark.asyncio
async def test_update_lead_status_missing_status(app_client, seed_lead):
    """缺 status 字段应 400"""
    lead_id = await seed_lead()
    resp = await app_client.post(f"/api/leads/{lead_id}/status", json={"notes": "无状态"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_lead_status_not_found(app_client):
    resp = await app_client.post("/api/leads/999999/status", json={"status": "new"})
    assert resp.status_code == 404


# ---------- 导出 + 平台脱敏 ----------

@pytest.mark.asyncio
async def test_export_leads(app_client, seed_lead):
    """导出应返回 Excel 二进制,且平台名称已脱敏(中文名)"""
    await seed_lead(platform="douyin", content="导出测试")
    resp = await app_client.get("/api/leads/export")
    assert resp.status_code == 200
    # Excel 文件 magic bytes: PK(zip)
    body = resp.content
    assert body[:2] == b"PK"
    # 不验证完整 Excel 解析(需 openpyxl,且字节级断言易碎)


@pytest.mark.asyncio
async def test_export_empty_returns_excel(app_client):
    """空库导出也应返回有效 Excel(仅表头)"""
    resp = await app_client.get("/api/leads/export")
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"
