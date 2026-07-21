# -*- coding: utf-8 -*-
"""数据隔离测试

覆盖 PRD §10.6.1:线索按 owner_user_id 隔离,用户只能访问自己的数据。
管理员(admin)可跨用户访问,普通用户(non-admin)严格隔离。

使用 user_context(2) 临时切换到用户2身份,退出上下文后自动恢复 admin。
"""
import pytest


@pytest.mark.asyncio
async def test_admin_sees_all_leads(app_client, seed_lead):
    """admin 可见所有用户的线索"""
    await seed_lead(owner_user_id="1", content="用户1线索")
    await seed_lead(owner_user_id="2", content="用户2线索")

    resp = await app_client.get("/api/leads/list")
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_admin_update_other_user_lead(app_client, seed_lead):
    """admin 可跨用户更新线索状态"""
    lead_id = await seed_lead(owner_user_id="2", status="new")

    resp = await app_client.post(f"/api/leads/{lead_id}/status", json={"status": "qualified"})
    assert resp.status_code == 200

    detail = await app_client.get(f"/api/leads/{lead_id}")
    assert detail.json()["status"] == "qualified"


@pytest.mark.asyncio
async def test_user2_sees_empty_list(user_context, seed_lead):
    """user2 自己没有任何线索时列表为空"""
    await seed_lead(owner_user_id="1", content="用户1线索")

    async with user_context(2) as client:
        resp = await client.get("/api/leads/list")
        assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_user2_cannot_export_others_leads(user_context, seed_lead):
    """user2 导出(无自己的线索)返回空 Excel"""
    await seed_lead(owner_user_id="1", content="导出测试")
    async with user_context(2) as client:
        resp = await client.get("/api/leads/export")
        assert resp.status_code == 200
        assert len(resp.content) > 0


@pytest.mark.asyncio
async def test_user2_cannot_view_admin_lead_detail(user_context, seed_lead):
    """admin 的线索详情,user2 不能查看(403)"""
    lead_id = await seed_lead(owner_user_id="1", content="私密详情")

    async with user_context(2) as client:
        resp = await client.get(f"/api/leads/{lead_id}")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_user2_cannot_update_admin_lead(app_client, user_context, seed_lead):
    """admin 的线索,user2 不能更新状态(403)"""
    lead_id = await seed_lead(owner_user_id="1", status="new")

    async with user_context(2) as client:
        resp = await client.post(f"/api/leads/{lead_id}/status", json={"status": "contacted"})
        assert resp.status_code == 403

    # 退出上下文后恢复 admin,确认状态未变
    detail = await app_client.get(f"/api/leads/{lead_id}")
    assert detail.json()["status"] == "new"


@pytest.mark.asyncio
async def test_user2_list_only_own_leads(user_context, seed_lead):
    """user2 列表只有自己的线索,没有 admin 的"""
    await seed_lead(owner_user_id="1", content="admin线索")
    await seed_lead(owner_user_id="2", content="user2线索")

    async with user_context(2) as client:
        resp = await client.get("/api/leads/list")
        items = resp.json()["items"]
        assert resp.json()["total"] == 1
        assert items[0]["content"] == "user2线索"


@pytest.mark.asyncio
async def test_admin_list_after_user2_queries(app_client, user_context, seed_lead):
    """user2 查询后,admin 仍可正常查询(override 正确恢复)"""
    await seed_lead(owner_user_id="1", content="admin独有")
    await seed_lead(owner_user_id="2", content="user2独有")

    # user2 查到自己1条
    async with user_context(2) as client:
        resp_u2 = await client.get("/api/leads/list")
        assert resp_u2.json()["total"] == 1

    # 退出上下文后恢复 admin,查到全部2条
    resp_admin = await app_client.get("/api/leads/list")
    assert resp_admin.json()["total"] == 2