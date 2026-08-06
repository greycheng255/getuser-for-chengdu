import json
from types import SimpleNamespace

import pytest

from api.routers import x_twitter_workbench
from api.routers.x_twitter_workbench import (
    GenerateCommentsRequest,
    GeneratePostContentRequest,
    _breakdown_prompt_text,
    _post_context,
)
from api.services import ai_agent_client


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def first(self):
        return self.value


class _FakeSession:
    def __init__(self, results):
        self.results = iter(results)

    async def execute(self, _statement):
        return _FakeResult(next(self.results))


class _FakeSessionContext:
    def __init__(self, results):
        self.session = _FakeSession(results)

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _saved_breakdown():
    return SimpleNamespace(
        script="开场介绍主题",
        storyboards=json.dumps(["近景展示产品", "全景展示现场"], ensure_ascii=False),
        key_points=json.dumps(["8月10日开启申购"], ensure_ascii=False),
        suggested_comments=json.dumps(["你会买吗？"], ensure_ascii=False),
    )


def test_breakdown_prompt_text_formats_saved_json_lists():
    breakdown = _saved_breakdown()

    result = _breakdown_prompt_text(breakdown)

    assert "【脚本分析】\n开场介绍主题" in result
    assert "1. 近景展示产品\n2. 全景展示现场" in result
    assert "【关键要点】\n1. 8月10日开启申购" in result
    assert "【原推荐评论】\n1. 你会买吗？" in result


def test_post_context_uses_request_for_non_x_platform():
    request = SimpleNamespace(
        post_id="douyin-1",
        post_url="https://example.com/post",
        content="字树科技8月10日开启网上申购",
        username="抖音作者",
        video_url="https://example.com/video.mp4",
        platform="douyin",
    )

    assert _post_context(request) == {
        "post_id": "douyin-1",
        "post_url": "https://example.com/post",
        "content": "字树科技8月10日开启网上申购",
        "username": "抖音作者",
        "video_url": "https://example.com/video.mp4",
        "platform": "douyin",
    }


@pytest.mark.asyncio
async def test_comment_endpoint_accepts_non_x_post_context(monkeypatch):
    monkeypatch.setattr(
        x_twitter_workbench,
        "get_session",
        lambda: _FakeSessionContext([None, None, _saved_breakdown()]),
    )
    captured = {}

    async def fake_generate_comments(post, breakdown, count):
        captured.update(post=post, breakdown=breakdown, count=count)
        return ["评论一", "评论二", "评论三"]

    monkeypatch.setattr(ai_agent_client, "generate_comments", fake_generate_comments)

    result = await x_twitter_workbench.generate_comments(
        GenerateCommentsRequest(
            post_id="douyin-1",
            platform="douyin",
            content="热点内容",
            username="抖音作者",
            count=3,
        )
    )

    assert result["comments"] == ["评论一", "评论二", "评论三"]
    assert captured["post"]["content"] == "热点内容"
    assert captured["post"]["platform"] == "douyin"
    assert "【分镜拆解】" in captured["breakdown"]


@pytest.mark.asyncio
async def test_post_content_endpoint_uses_current_platform(monkeypatch):
    monkeypatch.setattr(
        x_twitter_workbench,
        "get_session",
        lambda: _FakeSessionContext([None, None, _saved_breakdown()]),
    )
    captured = {}

    async def fake_generate_post_content(post, breakdown, platform, count):
        captured.update(post=post, breakdown=breakdown, platform=platform, count=count)
        return ["抖音文案一", "抖音文案二", "抖音文案三"]

    monkeypatch.setattr(
        ai_agent_client,
        "generate_platform_post_content",
        fake_generate_post_content,
    )

    result = await x_twitter_workbench.generate_x_post_content(
        GeneratePostContentRequest(
            post_id="douyin-1",
            platform="douyin",
            content="热点内容",
            username="抖音作者",
            count=3,
        )
    )

    assert result["contents"] == ["抖音文案一", "抖音文案二", "抖音文案三"]
    assert captured["platform"] == "douyin"
    assert captured["count"] == 3
