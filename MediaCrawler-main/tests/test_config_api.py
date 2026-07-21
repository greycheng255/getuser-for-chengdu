# -*- coding: utf-8 -*-
"""评分规则 CRUD 测试

覆盖 PRD §10.7.8:`/api/config/intent-rules` 增删改查 + 首次自动 seed
"""
import pytest


@pytest.mark.asyncio
async def test_intent_rules_auto_seed_on_first_access(app_client):
    """首次访问 list 应自动从 tasks.py 硬编码规则 seed 数据"""
    resp = await app_client.get("/api/config/intent-rules")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    # 首次 seed 应返回多条规则(strong_intent/nostalgia/discussion 等)
    assert data["total"] > 0
    rule_types = {item["rule_type"] for item in data["items"]}
    assert "strong_intent" in rule_types or "nostalgia" in rule_types


@pytest.mark.asyncio
async def test_intent_rules_create(app_client):
    """POST 创建规则后,list 应包含该规则"""
    payload = {
        "rule_type": "strong_intent",
        "pattern": "测试关键词_唯一",
        "action": "upgrade",
        "target_level": "high",
        "score_delta": 20,
        "score_cap": 0,
        "enabled": 1,
        "category": "test",
        "note": "由测试创建",
    }
    resp = await app_client.post("/api/config/intent-rules", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    rule_id = body["id"]
    assert isinstance(rule_id, int)

    # list 应能查到
    list_resp = await app_client.get("/api/config/intent-rules")
    patterns = [item["pattern"] for item in list_resp.json()["items"]]
    assert "测试关键词_唯一" in patterns


@pytest.mark.asyncio
async def test_intent_rules_update(app_client):
    """PUT 更新规则字段"""
    # 先建
    create = await app_client.post("/api/config/intent-rules", json={
        "rule_type": "discussion",
        "pattern": "待更新_模式",
        "action": "downgrade",
        "target_level": "middle",
        "score_delta": -10,
        "score_cap": 45,
        "enabled": 1,
        "category": "general",
        "note": "初始",
    })
    rule_id = create.json()["id"]

    # 改 enabled 和 note
    resp = await app_client.put(f"/api/config/intent-rules/{rule_id}", json={
        "enabled": 0,
        "note": "已禁用",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    # 校验
    item = next(i for i in (await app_client.get("/api/config/intent-rules")).json()["items"]
                if i["id"] == rule_id)
    assert item["enabled"] is False
    assert item["note"] == "已禁用"


@pytest.mark.asyncio
async def test_intent_rules_update_not_found(app_client):
    """更新不存在的规则应 404"""
    resp = await app_client.put("/api/config/intent-rules/999999", json={"enabled": 0})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_intent_rules_update_empty_body(app_client):
    """空更新体应 400"""
    # 先建一条
    create = await app_client.post("/api/config/intent-rules", json={
        "rule_type": "nostalgia", "pattern": "x", "action": "downgrade",
    })
    rule_id = create.json()["id"]
    resp = await app_client.put(f"/api/config/intent-rules/{rule_id}", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_intent_rules_delete(app_client):
    """DELETE 删除规则后,list 不再包含"""
    create = await app_client.post("/api/config/intent-rules", json={
        "rule_type": "past_purchase",
        "pattern": "待删除",
        "action": "downgrade",
        "target_level": "low",
    })
    rule_id = create.json()["id"]

    resp = await app_client.delete(f"/api/config/intent-rules/{rule_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 再删应 404
    resp2 = await app_client.delete(f"/api/config/intent-rules/{rule_id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_intent_rules_filter_by_type(app_client):
    """按 rule_type 筛选"""
    await app_client.post("/api/config/intent-rules", json={
        "rule_type": "industry_template",
        "pattern": "行业模板测试",
        "action": "upgrade",
        "target_level": "high",
    })
    resp = await app_client.get("/api/config/intent-rules?rule_type=industry_template")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) > 0
    assert all(i["rule_type"] == "industry_template" for i in items)


@pytest.mark.asyncio
async def test_intent_rules_filter_by_enabled(app_client):
    """按 enabled 筛选"""
    # 建一条禁用的
    create = await app_client.post("/api/config/intent-rules", json={
        "rule_type": "strong_intent",
        "pattern": "禁用项筛选测试",
        "action": "upgrade",
        "enabled": 0,
    })
    rule_id = create.json()["id"]

    resp = await app_client.get("/api/config/intent-rules?enabled=0")
    items = resp.json()["items"]
    assert any(i["id"] == rule_id for i in items)

    resp_enabled = await app_client.get("/api/config/intent-rules?enabled=1")
    items_enabled = resp_enabled.json()["items"]
    assert all(i["enabled"] is True for i in items_enabled)
