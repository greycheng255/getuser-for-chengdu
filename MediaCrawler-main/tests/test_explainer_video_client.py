import pytest

from api.services import explainer_video_client as client
from api.services.opennotebook_oauth import OpenNotebookCredentials


def _credentials() -> OpenNotebookCredentials:
    return OpenNotebookCredentials(
        connection_id=1,
        owner_user_id="1",
        credential_version=1,
        access_token="test-token",
        token_type="Bearer",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        workspace_name="测试工作区",
        grant_id="grant-1",
    )


def test_media_urls_and_model_selection():
    images = client.normalize_media_urls('["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"]')
    videos = client.normalize_media_urls("https://cdn.test/a.mp4")

    assert images == ["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"]
    assert videos == ["https://cdn.test/a.mp4"]
    assert client.choose_seedance_model(images, []) == "kwvideo-v2-ref"
    assert client.choose_seedance_model([], videos) == "kwvideo-v2-ref"
    assert client.choose_seedance_model([], []) == "kwvideo-v2"


def test_prompt_contains_breakdown_context():
    prompt = client.build_explainer_prompt(
        post_content="原帖内容",
        script="核心脚本",
        storyboards=["开场特写", "产品全景"],
        key_points=["重点一", "重点二"],
    )

    assert "4 秒" in prompt
    assert "中文解说" in prompt
    assert "核心脚本" in prompt
    assert "1. 开场特写" in prompt
    assert "- 重点一" in prompt


@pytest.mark.asyncio
async def test_agent_api_rejects_remote_plain_http_by_default(monkeypatch):
    monkeypatch.delenv("OPENNOTEBOOK_ALLOW_INSECURE_HTTP", raising=False)
    monkeypatch.setenv(
        "AGENT_API_URL",
        "http://212.129.240.112:31003/api/v1/agent",
    )
    with pytest.raises(client.AgentVideoError) as caught:
        await client._agent_api_url()
    assert caught.value.status_code == 503
    assert "HTTPS" in str(caught.value)


@pytest.mark.asyncio
async def test_agent_api_comes_from_discovery_without_legacy_variable(monkeypatch):
    monkeypatch.delenv("AGENT_API_URL", raising=False)

    async def fake_provider_config():
        return {"agent_endpoint": "https://api.onb.test/api/v1/agent"}

    monkeypatch.setattr(client, "oauth_provider_config", fake_provider_config)

    assert await client._agent_api_url() == "https://api.onb.test/api/v1/agent"


@pytest.mark.asyncio
async def test_submit_uses_reference_seedance_and_low_cost_params(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"code": 200, "data": {"task_id": "task-123"}}

    class FakeAsyncClient:
        def __init__(self, *, timeout, transport, follow_redirects):
            captured.update(
                timeout=timeout,
                transport=transport,
                follow_redirects=follow_redirects,
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, body=json)
            return FakeResponse()

    monkeypatch.setenv("AGENT_API_URL", "https://agent.test/api/v1/agent")
    monkeypatch.setattr(
        client.httpx,
        "AsyncHTTPTransport",
        lambda *, retries: {"retries": retries},
    )
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeAsyncClient)

    result = await client.submit_explainer_video(
        credentials=_credentials(),
        prompt="拆解上下文",
        image_urls=["https://cdn.test/frame.jpg"],
        video_urls=["https://cdn.test/source.mp4"],
        idempotency_key="cc19fa10-bcfe-40b8-a433-693b50596155",
    )

    assert result["task_id"] == "task-123"
    assert result["model"] == "kwvideo-v2-ref"
    assert captured["url"] == "https://agent.test/api/v1/agent/generate"
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["headers"]["X-Tenant-ID"] == "tenant-1"
    assert captured["headers"]["Idempotency-Key"] == "cc19fa10-bcfe-40b8-a433-693b50596155"
    assert captured["transport"] == {"retries": 0}
    assert captured["follow_redirects"] is False
    assert captured["body"]["type"] == "videogen"
    assert captured["body"]["workspace_id"] == "workspace-1"
    assert captured["body"]["params"] == {
        "prompt": "拆解上下文",
        "model_id": "kwvideo-v2-ref",
        "model_name": "Seedance 2.0 参考生",
        "version": "Mini",
        "duration": "4",
        "aspect_ratio": "16:9",
        "resolution": "480p",
        "images": ["https://cdn.test/frame.jpg"],
        "videos": ["https://cdn.test/source.mp4"],
    }


@pytest.mark.asyncio
async def test_submit_5xx_is_not_retried(monkeypatch):
    calls = 0

    class FakeResponse:
        status_code = 503
        text = "unavailable"

        @staticmethod
        def json():
            return {"detail": "unavailable"}

    class FakeAsyncClient:
        def __init__(self, *, timeout, transport, follow_redirects):
            assert transport == {"retries": 0}
            assert follow_redirects is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            nonlocal calls
            calls += 1
            return FakeResponse()

    monkeypatch.setenv("AGENT_API_URL", "https://agent.test/api/v1/agent")
    monkeypatch.setattr(
        client.httpx,
        "AsyncHTTPTransport",
        lambda *, retries: {"retries": retries},
    )
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(client.AgentVideoError) as caught:
        await client.submit_explainer_video(
            credentials=_credentials(),
            prompt="拆解上下文",
            image_urls=[],
            video_urls=[],
            idempotency_key="5b55dd49-823b-4f41-86e8-7bc807997163",
        )

    assert caught.value.status_code == 503
    assert calls == 1


@pytest.mark.asyncio
async def test_status_response_is_normalized(monkeypatch):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "code": 200,
                "data": {
                    "task_id": "task-123",
                    "status": "done",
                    "is_final": True,
                    "progress": "100%",
                    "result_url": "https://cdn.test/result.mp4",
                    "current_step": "done",
                    "cost": 2.5,
                    "error": "",
                },
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url, *, headers, params):
            return FakeResponse()

    monkeypatch.setenv("AGENT_API_URL", "https://agent.test/api/v1/agent")
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeAsyncClient)

    result = await client.get_explainer_video_status(
        "task-123",
        credentials=_credentials(),
    )

    assert result["is_final"] is True
    assert result["progress"] == 100
    assert result["result_url"] == "https://cdn.test/result.mp4"
