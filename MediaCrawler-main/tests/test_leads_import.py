# -*- coding: utf-8 -*-
"""批量导入线索测试

覆盖 PRD §10.7 第三批 #6:`POST /api/leads/import-file` 支持 CSV/Excel
"""
import io
import pytest


def _csv_bytes(rows: list) -> bytes:
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8-sig")


def _xlsx_bytes(rows: list) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_import_csv(app_client):
    """CSV 导入:含表头 + 2 条有效 + 1 条无 content(跳过)"""
    csv_data = _csv_bytes([
        ["content", "nickname", "lead_score", "intent_type", "ip_location"],
        ["想学吉他,多少钱", "张三", 75, "purchase", "北京"],
        ["咨询课程价格", "李四", 60, "inquiry", "上海"],
        ["", "无内容用户", 50, "discussion", ""],  # 应被跳过
    ])
    resp = await app_client.post(
        "/api/leads/import-file?task_id=task_imp_1&platform=manual",
        files={"file": ("leads.csv", csv_data, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["imported"] == 2
    assert data["skipped"] == 1
    assert data["total_rows"] == 3  # 不含表头

    # 校验已入库
    list_resp = await app_client.get("/api/leads/list?task_id=task_imp_1")
    assert list_resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_import_csv_with_chinese_headers(app_client):
    """CSV 中文表头映射(content/咨询内容 均可)"""
    csv_data = _csv_bytes([
        ["咨询内容", "昵称", "线索评分"],
        ["中文表头测试", "用户A", "80"],
    ])
    resp = await app_client.post(
        "/api/leads/import-file?task_id=task_imp_2",
        files={"file": ("leads.csv", csv_data, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1
    items = (await app_client.get("/api/leads/list?task_id=task_imp_2")).json()["items"]
    assert items[0]["content"] == "中文表头测试"
    assert items[0]["nickname"] == "用户A"
    assert items[0]["lead_score"] == 80


@pytest.mark.asyncio
async def test_import_xlsx(app_client):
    """Excel 导入"""
    xlsx_data = _xlsx_bytes([
        ["content", "nickname", "lead_score", "status"],
        ["Excel导入测试1", "U1", 55, "new"],
        ["Excel导入测试2", "U2", 90, "contacted"],
    ])
    resp = await app_client.post(
        "/api/leads/import-file?task_id=task_xlsx_1",
        files={"file": ("leads.xlsx", xlsx_data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 2
    items = (await app_client.get("/api/leads/list?task_id=task_xlsx_1")).json()["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_import_requires_task_id(app_client):
    """缺 task_id 应 422(必填参数)"""
    csv_data = _csv_bytes([["content"], ["x"]])
    resp = await app_client.post(
        "/api/leads/import-file",
        files={"file": ("leads.csv", csv_data, "text/csv")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_unsupported_format(app_client):
    """不支持的文件格式应 400"""
    resp = await app_client.post(
        "/api/leads/import-file?task_id=t1",
        files={"file": ("leads.txt", b"plain text", "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_import_empty_file(app_client):
    """空文件(无数据行)应 400"""
    csv_data = _csv_bytes([["content", "nickname"]])  # 仅表头
    resp = await app_client.post(
        "/api/leads/import-file?task_id=t1",
        files={"file": ("leads.csv", csv_data, "text/csv")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_import_all_rows_missing_content(app_client):
    """所有行都缺 content 应 400"""
    csv_data = _csv_bytes([
        ["content", "nickname"],
        ["", "A"],
        ["", "B"],
    ])
    resp = await app_client.post(
        "/api/leads/import-file?task_id=t1",
        files={"file": ("leads.csv", csv_data, "text/csv")},
    )
    assert resp.status_code == 400
    assert "content" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_import_lead_score_clamped(app_client):
    """lead_score 超出 0-100 应被夹紧"""
    csv_data = _csv_bytes([
        ["content", "lead_score"],
        ["分数超上限", "150"],
        ["分数负值", "-20"],
    ])
    resp = await app_client.post(
        "/api/leads/import-file?task_id=t1",
        files={"file": ("leads.csv", csv_data, "text/csv")},
    )
    assert resp.status_code == 200
    items = (await app_client.get("/api/leads/list?task_id=t1")).json()["items"]
    scores = sorted(i["lead_score"] for i in items)
    assert scores == [0, 100]
