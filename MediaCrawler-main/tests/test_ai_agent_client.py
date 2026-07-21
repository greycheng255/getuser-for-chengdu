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
