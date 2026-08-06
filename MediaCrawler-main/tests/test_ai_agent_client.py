from dataclasses import replace

import pytest

from api.services import ai_agent_client


@pytest.mark.asyncio
async def test_chat_configures_all_httpx_timeouts(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            return FakeResponse()

    monkeypatch.setitem(ai_agent_client.CONFIG, "api_key", "test-key")
    async def fake_balance():
        return {"balance": 100, "unit": "算力"}

    monkeypatch.setattr(ai_agent_client, "ensure_ai6700_balance", fake_balance)
    monkeypatch.setattr(
        ai_agent_client,
        "workbench_config",
        replace(ai_agent_client.workbench_config, ai_retry_max=0),
    )
    monkeypatch.setattr(ai_agent_client.httpx, "AsyncClient", FakeAsyncClient)

    result = await ai_agent_client._chat(
        [{"role": "user", "content": "hello"}],
        max_tokens=100,
        timeout=12.0,
    )

    assert result == "ok"
    assert captured["timeout"].connect == 5.0
    assert captured["timeout"].read == 14.0
    assert captured["timeout"].write == 30.0
    assert captured["timeout"].pool == 5.0


@pytest.mark.asyncio
async def test_generate_comments_cleans_numbering_and_respects_count(monkeypatch):
    async def fake_chat(*args, **kwargs):
        return "1. 第一条评论\n- 第二条评论\n3、第三条评论\n4) 多余评论"

    monkeypatch.setattr(ai_agent_client, "_chat", fake_chat)

    result = await ai_agent_client.generate_comments(
        {"content": "热点内容"},
        "【脚本分析】拆解内容",
        count=3,
    )

    assert result == ["第一条评论", "第二条评论", "第三条评论"]


@pytest.mark.asyncio
async def test_x_post_prompt_uses_requested_count(monkeypatch):
    captured = {}

    async def fake_chat(messages, **kwargs):
        captured["prompt"] = messages[-1]["content"]
        return "文案一\n文案二"

    monkeypatch.setattr(ai_agent_client, "_chat", fake_chat)

    result = await ai_agent_client.generate_x_post_content(
        {"content": "热点内容"},
        "拆解内容",
        count=2,
    )

    assert "生成 2 条" in captured["prompt"]
    assert result == ["文案一", "文案二"]
