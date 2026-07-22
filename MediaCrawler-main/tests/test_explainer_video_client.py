import pytest

from api.services import explainer_video_client as client
from api.services.ai6700_client import AI6700BalanceError


def _configure_ai6700(monkeypatch):
    monkeypatch.setenv("ONELLM_API_KEY", "ai6700-test-key")
    monkeypatch.setenv("ONELLM_BASE_URL", "https://ai6700.test/api")


async def _positive_balance(settings=None):
    return {"balance": 100, "unit": "算力"}


def test_media_urls_and_model_selection(monkeypatch):
    monkeypatch.delenv("ONELLM_VIDEO_MODEL", raising=False)
    monkeypatch.delenv("ONELLM_REFERENCE_VIDEO_MODEL", raising=False)
    images = client.normalize_media_urls(
        '["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"]'
    )
    videos = client.normalize_media_urls("https://cdn.test/a.mp4")

    assert images == ["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"]
    assert videos == ["https://cdn.test/a.mp4"]
    assert client.choose_seedance_model(images, []) == "kwvideo-v2-ref"
    assert client.choose_seedance_model([], videos) == "kwvideo-v2"
    assert client.choose_seedance_model([], []) == "kwvideo-v2"


def test_prompt_contains_breakdown_context():
    prompt = client.build_explainer_prompt(
        post_content="原帖内容",
        script="核心脚本",
        storyboards=["开场特写", "产品全景"],
        key_points=["重点一", "重点二"],
    )

    assert "10 秒" in prompt
    assert "9:16 竖屏" in prompt
    assert "中文解说" in prompt
    assert "核心脚本" in prompt
    assert "1. 开场特写" in prompt
    assert "- 重点一" in prompt


def test_missing_api_key_is_rejected(monkeypatch):
    monkeypatch.delenv("ONELLM_API_KEY", raising=False)
    with pytest.raises(client.AI6700VideoError) as caught:
        client._headers()
    assert caught.value.status_code == 503
    assert "ONELLM_API_KEY" in str(caught.value)


@pytest.mark.asyncio
async def test_submit_uses_ai6700_media_contract(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "code": 200,
                "msg": "Task created successfully",
                "data": {"task_id": 9784349, "任务ids": [9784349]},
            }

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

    _configure_ai6700(monkeypatch)
    monkeypatch.setattr(client, "ensure_ai6700_balance", _positive_balance)
    monkeypatch.setattr(
        client.httpx,
        "AsyncHTTPTransport",
        lambda *, retries: {"retries": retries},
    )
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeAsyncClient)

    result = await client.submit_explainer_video(
        prompt="拆解上下文",
        image_urls=[
            "https://cdn.test/frame-1.jpg",
            "https://cdn.test/frame-2.jpg",
        ],
        video_urls=["https://cdn.test/source.mp4"],
    )

    assert result["task_id"] == "9784349"
    assert result["status"] == "pending"
    assert result["model"] == "kwvideo-v2-ref"
    assert result["reference_count"] == 2
    assert captured["url"] == "https://ai6700.test/api/v1/media/generate"
    assert captured["headers"]["Authorization"] == "Bearer ai6700-test-key"
    assert "Idempotency-Key" not in captured["headers"]
    assert captured["transport"] == {"retries": 0}
    assert captured["follow_redirects"] is False
    assert captured["body"] == {
        "model": "kwvideo-v2-ref",
        "prompt": "拆解上下文",
        "params": {
            "version": "Mini",
            "duration": "10",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "images": [
                "https://cdn.test/frame-1.jpg",
                "https://cdn.test/frame-2.jpg",
            ],
        },
    }


@pytest.mark.asyncio
async def test_balance_rejection_prevents_paid_submit(monkeypatch):
    client_created = False

    async def insufficient_balance(settings=None):
        raise AI6700BalanceError("余额不足", 402)

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            nonlocal client_created
            client_created = True

    _configure_ai6700(monkeypatch)
    monkeypatch.setattr(client, "ensure_ai6700_balance", insufficient_balance)
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(client.AI6700VideoError) as caught:
        await client.submit_explainer_video(
            prompt="拆解上下文",
            image_urls=[],
            video_urls=[],
        )

    assert caught.value.status_code == 402
    assert client_created is False


@pytest.mark.asyncio
async def test_submit_5xx_is_not_retried_and_is_uncertain(monkeypatch):
    calls = 0

    class FakeResponse:
        status_code = 503
        text = "unavailable"

        @staticmethod
        def json():
            return {"error": {"message": "unavailable", "code": "RUNTIME_DOWN"}}

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

    _configure_ai6700(monkeypatch)
    monkeypatch.setattr(client, "ensure_ai6700_balance", _positive_balance)
    monkeypatch.setattr(
        client.httpx,
        "AsyncHTTPTransport",
        lambda *, retries: {"retries": retries},
    )
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(client.AI6700VideoError) as caught:
        await client.submit_explainer_video(
            prompt="拆解上下文",
            image_urls=[],
            video_urls=[],
        )

    assert caught.value.status_code == 503
    assert caught.value.submission_uncertain is True
    assert calls == 1


@pytest.mark.asyncio
async def test_ai6700_task_status_is_normalized(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "task_id": 9784349,
                "model": "kwvideo-v2-ref",
                "state": "success",
                "status": "生成完成",
                "status_group": "已完成",
                "progress": "100%",
                "is_final": True,
                "result_url": "https://cdn.test/result.mp4",
                "cost": 1.5,
                "refunded": False,
                "refunded_amount": 0,
                "channel_group": "标准渠道",
                "error": None,
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url, *, headers, params):
            captured.update(url=url, headers=headers, params=params)
            return FakeResponse()

    _configure_ai6700(monkeypatch)
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeAsyncClient)

    result = await client.get_explainer_video_status("9784349")

    assert result["status"] == "success"
    assert result["is_final"] is True
    assert result["progress"] == 100
    assert result["result_url"] == "https://cdn.test/result.mp4"
    assert result["cost"] == 1.5
    assert result["channel_group"] == "标准渠道"
    assert captured["url"] == "https://ai6700.test/api/v1/skills/task-status"
    assert captured["params"] == {"task_id": "9784349"}
