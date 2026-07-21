# -*- coding: utf-8 -*-
"""数据分析 API 测试

覆盖 PRD Analytics 页面后端:
- /api/analytics/trends 趋势
- /api/analytics/platform 平台分布
- /api/analytics/funnel 转化漏斗
"""
import pytest


@pytest.mark.asyncio
async def test_trends_default_30_days(app_client):
    """默认返回 30 天趋势"""
    resp = await app_client.get("/api/analytics/trends")
    assert resp.status_code == 200
    trends = resp.json()["trends"]
    assert len(trends) == 30
    assert all("date" in t and "leads" in t for t in trends)
    # 空库 leads 全为 0
    assert all(t["leads"] == 0 for t in trends)


@pytest.mark.asyncio
async def test_trends_custom_days(app_client):
    """自定义天数"""
    resp = await app_client.get("/api/analytics/trends?days=7")
    assert resp.status_code == 200
    assert len(resp.json()["trends"]) == 7


@pytest.mark.asyncio
async def test_trends_counts_seeded_leads(app_client, seed_lead):
    """有数据时对应日期的 leads 应 >0"""
    await seed_lead(content="今天的线索")
    resp = await app_client.get("/api/analytics/trends?days=3")
    trends = resp.json()["trends"]
    # 最后一天(今天)应有计数
    assert trends[-1]["leads"] >= 1


@pytest.mark.asyncio
async def test_platform_distribution_empty(app_client):
    """空库平台分布为空列表"""
    resp = await app_client.get("/api/analytics/platform")
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform_distribution"] == []
    assert data["avg_scores"] == {}


@pytest.mark.asyncio
async def test_platform_distribution_with_data(app_client, seed_lead):
    """有数据时按平台分组"""
    await seed_lead(platform="douyin", lead_score=80)
    await seed_lead(platform="douyin", lead_score=60)
    await seed_lead(platform="xhs", lead_score=90)

    resp = await app_client.get("/api/analytics/platform")
    data = resp.json()
    dist = {item["platform"]: item["count"] for item in data["platform_distribution"]}
    assert dist["douyin"] == 2
    assert dist["xhs"] == 1
    # 平均分
    assert data["avg_scores"]["douyin"] == 70.0
    assert data["avg_scores"]["xhs"] == 90.0


@pytest.mark.asyncio
async def test_funnel_empty(app_client):
    """空库漏斗全 0,且包含 4 个标准状态"""
    resp = await app_client.get("/api/analytics/funnel")
    assert resp.status_code == 200
    funnel = resp.json()["funnel"]
    statuses = [f["status"] for f in funnel]
    assert statuses == ["new", "contacted", "qualified", "converted"]
    assert all(f["count"] == 0 for f in funnel)


@pytest.mark.asyncio
async def test_funnel_with_data(app_client, seed_lead):
    """漏斗按状态统计"""
    await seed_lead(status="new", content="n1")
    await seed_lead(status="new", content="n2")
    await seed_lead(status="contacted", content="c1")
    await seed_lead(status="converted", content="v1")

    resp = await app_client.get("/api/analytics/funnel")
    funnel = {f["status"]: f["count"] for f in resp.json()["funnel"]}
    assert funnel["new"] == 2
    assert funnel["contacted"] == 1
    assert funnel["qualified"] == 0
    assert funnel["converted"] == 1
