from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from api.services.publisher.account_service import PlatformAccountService
from api.services.publisher.base_publisher import (
    BasePublisher,
    classify_publish_error,
    is_error_code_retryable,
)
from api.services.publisher.multi_publisher import MultiPlatformPublisher
from api.services.publisher.platforms.douyin_publisher import DouyinPublisher
from api.services.publisher.platforms.xiaohongshu_publisher import XiaohongshuPublisher
from api.services.publisher.publish_task import (
    PublishErrorCode,
    PublishResult,
    PublishStatus,
    PublishTask,
)
from database.models import UnifiedAccount


class DummyPublisher(BasePublisher):
    PLATFORM_NAME = "dummy"
    PLATFORM_CN_NAME = "测试平台"
    PUBLISH_URL = "https://creator.test/publish"
    SUPPORTS_VIDEO = True

    def __init__(self, result=None, *, login=True):
        super().__init__(cookies="")
        self._result = result or PublishResult(success=True, platform="dummy", url="https://test/post/1")
        self._login = login

    async def _init_browser(self):
        self.page = SimpleNamespace(
            url=self.PUBLISH_URL,
            goto=AsyncMock(),
        )
        return True

    async def _check_login(self):
        return self._login

    async def _do_publish(self, title, content, images, video_path, **kwargs):
        return self._result

    async def _persist_state(self):
        return None

    async def _close_browser(self):
        return None


@pytest.mark.parametrize(
    ("message", "expected", "retryable"),
    [
        ("Cookie 已过期，请重新登录", PublishErrorCode.AUTH_EXPIRED, False),
        ("请完成滑块验证码", PublishErrorCode.CAPTCHA_REQUIRED, False),
        ("操作频繁，触发限流", PublishErrorCode.RATE_LIMITED, True),
        ("视频文件不存在", PublishErrorCode.INVALID_MEDIA, False),
        ("内容违规被拒绝", PublishErrorCode.CONTENT_REJECTED, False),
        ("视频上传失败", PublishErrorCode.UPLOAD_FAILED, True),
        ("未找到发布按钮", PublishErrorCode.SELECTOR_CHANGED, False),
        ("页面等待超时", PublishErrorCode.TIMEOUT, True),
        ("无法识别的异常", PublishErrorCode.UNKNOWN, False),
    ],
)
def test_publish_error_classification(message, expected, retryable):
    code = classify_publish_error(message)
    assert code == expected
    assert is_error_code_retryable(code) is retryable


@pytest.mark.asyncio
async def test_base_publisher_returns_complete_standard_protocol(monkeypatch):
    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("api.services.publisher.base_publisher.asyncio.sleep", no_sleep)
    result = await DummyPublisher().publish(
        "标题", "正文", task_id="task-1"
    )
    payload = result.to_dict()

    assert result.success is True
    assert payload["task_id"] == "task-1"
    assert payload["post_url"] == "https://test/post/1"
    assert payload["url"] == payload["post_url"]
    assert payload["error_code"] is None
    assert payload["started_at"] and payload["finished_at"]
    assert payload["retryable"] is False


@pytest.mark.asyncio
async def test_base_publisher_maps_login_and_invalid_video(monkeypatch, tmp_path):
    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("api.services.publisher.base_publisher.asyncio.sleep", no_sleep)
    login_result = await DummyPublisher(login=False).publish("", "")
    assert login_result.error_code == PublishErrorCode.AUTH_EXPIRED.value
    assert login_result.retryable is False

    missing = tmp_path / "missing.mp4"
    media_result = await DummyPublisher().publish("", "", video_path=str(missing))
    assert media_result.error_code == PublishErrorCode.INVALID_MEDIA.value
    assert media_result.retryable is False


@pytest.mark.asyncio
async def test_confirmation_extracts_real_post_url_and_id():
    publisher = DummyPublisher()
    publisher.page = SimpleNamespace(
        url="https://www.douyin.com/video/post-123",
        evaluate=AsyncMock(return_value="作品已发布"),
    )
    confirmed, post_url, post_id = await publisher._confirm_publish_success(
        url_markers=["/video/"], success_markers=["发布成功"], attempts=1
    )
    assert confirmed is True
    assert post_url.endswith("/video/post-123")
    assert post_id == "post-123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("publisher_cls", "env_name"),
    [
        (DouyinPublisher, "DOUYIN_VIDEO_PUBLISH_ENABLED"),
        (XiaohongshuPublisher, "XIAOHONGSHU_VIDEO_PUBLISH_ENABLED"),
    ],
)
async def test_core_platform_video_feature_flags_default_closed(
    publisher_cls, env_name, monkeypatch
):
    monkeypatch.delenv(env_name, raising=False)
    publisher = publisher_cls("")
    result = await publisher._do_publish("标题", "正文", [], "video.mp4")
    assert result.success is False
    assert result.error_code == PublishErrorCode.INVALID_MEDIA.value
    assert result.retryable is False


@pytest.mark.asyncio
async def test_douyin_video_flow_requires_second_confirmation(monkeypatch):
    monkeypatch.setenv("DOUYIN_VIDEO_PUBLISH_ENABLED", "true")
    publisher = DouyinPublisher("")
    publisher.page = SimpleNamespace()
    monkeypatch.setattr(publisher, "_upload_video", AsyncMock(return_value=True))
    monkeypatch.setattr(publisher, "_apply_publish_settings", AsyncMock())
    monkeypatch.setattr(publisher, "_detect_biz_error", AsyncMock(return_value=None))
    monkeypatch.setattr(
        publisher,
        "_confirm_publish_success",
        AsyncMock(return_value=(False, None, None)),
    )
    publisher.page.locator = lambda _selector: SimpleNamespace(
        first=SimpleNamespace(
            count=AsyncMock(return_value=1),
            click=AsyncMock(),
            fill=AsyncMock(),
            is_enabled=AsyncMock(return_value=True),
        )
    )
    publisher.page.keyboard = SimpleNamespace(type=AsyncMock())

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("api.services.publisher.platforms.douyin_publisher.asyncio.sleep", no_sleep)
    result = await publisher._do_publish("标题", "正文", [], "video.mp4")
    assert result.success is False
    assert result.error_code == PublishErrorCode.UNKNOWN.value
    publisher._confirm_publish_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_douyin_compensation_query_can_confirm_publish(monkeypatch):
    monkeypatch.setenv("DOUYIN_VIDEO_PUBLISH_ENABLED", "true")
    publisher = DouyinPublisher("")
    publisher.page = SimpleNamespace()
    monkeypatch.setattr(publisher, "_upload_video", AsyncMock(return_value=True))
    monkeypatch.setattr(publisher, "_apply_publish_settings", AsyncMock())
    monkeypatch.setattr(publisher, "_detect_biz_error", AsyncMock(return_value=None))
    monkeypatch.setattr(
        publisher,
        "_confirm_publish_success",
        AsyncMock(return_value=(False, None, None)),
    )
    monkeypatch.setattr(
        publisher,
        "_query_recent_published_post",
        AsyncMock(return_value=(True, "https://douyin.test/video/work-1", "work-1")),
    )
    publisher.page.locator = lambda _selector: SimpleNamespace(
        first=SimpleNamespace(
            count=AsyncMock(return_value=1),
            click=AsyncMock(),
            fill=AsyncMock(),
            is_enabled=AsyncMock(return_value=True),
        )
    )
    publisher.page.keyboard = SimpleNamespace(type=AsyncMock())

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("api.services.publisher.platforms.douyin_publisher.asyncio.sleep", no_sleep)
    result = await publisher._do_publish("标题", "正文", [], "video.mp4")
    assert result.success is True
    assert result.post_id == "work-1"
    assert result.post_url.endswith("work-1")
    publisher._query_recent_published_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_xiaohongshu_image_and_video_flows_are_confirmed(monkeypatch):
    monkeypatch.setenv("XIAOHONGSHU_VIDEO_PUBLISH_ENABLED", "true")

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr("api.services.publisher.platforms.xiaohongshu_publisher.asyncio.sleep", no_sleep)
    for video_path in (None, "video.mp4"):
        publisher = XiaohongshuPublisher("")
        publisher.page = SimpleNamespace()
        monkeypatch.setattr(publisher, "_upload_images", AsyncMock(return_value=True))
        monkeypatch.setattr(publisher, "_upload_video", AsyncMock(return_value=True))
        monkeypatch.setattr(publisher, "_wait_form_loaded", AsyncMock())
        monkeypatch.setattr(publisher, "_fill_title", AsyncMock(return_value=True))
        monkeypatch.setattr(publisher, "_fill_content", AsyncMock(return_value=True))
        monkeypatch.setattr(publisher, "_click_publish", AsyncMock(return_value=True))
        monkeypatch.setattr(publisher, "_apply_publish_settings", AsyncMock())
        monkeypatch.setattr(publisher, "_detect_biz_error", AsyncMock(return_value=None))
        monkeypatch.setattr(
            publisher,
            "_confirm_publish_success",
            AsyncMock(return_value=(True, "https://xhs.test/explore/note-1", "note-1")),
        )
        result = await publisher._do_publish(
            "标题", "正文", ["image.jpg"] if not video_path else [], video_path
        )
        assert result.success is True
        assert result.post_id == "note-1"
        assert result.post_url.endswith("note-1")
        publisher._confirm_publish_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_multi_platform_task_can_express_partial_success(monkeypatch):
    publisher = MultiPlatformPublisher(account_service=SimpleNamespace())
    monkeypatch.setattr(
        "api.services.publisher.multi_publisher.PublisherFactory.is_supported",
        lambda _platform: True,
    )

    async def fake_publish(task, platform, *_args, **_kwargs):
        task.platform_results[platform] = PublishResult(
            success=platform == "douyin",
            platform=platform,
            error=None if platform == "douyin" else "小红书上传失败",
        ).finalize(task_id=task.task_id)

    monkeypatch.setattr(publisher, "_publish_to_one_platform_with_sem", fake_publish)
    task = PublishTask(target_platforms=["douyin", "xiaohongshu"])
    result = await publisher.publish_to_multiple_platforms(task)
    assert result.status == PublishStatus.PARTIAL
    assert sum(item.success for item in result.platform_results.values()) == 1


@pytest.mark.asyncio
async def test_rate_limit_feedback_can_put_unified_account_in_cooldown(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("UNIFIED_ACCOUNT_WRITE_ENABLED", "true")
    monkeypatch.setenv("UNIFIED_ACCOUNT_READ_ENABLED", "true")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'accounts.db'}")
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(UnifiedAccount.__table__.create)
    service = PlatformAccountService(factory)
    account = await service.save_account(
        user_id=1,
        platform="douyin",
        cookies="sessionid=test",
        account_name="rate-limited-account",
    )
    await service.mark_cooldown(account.id, "RATE_LIMITED", cooldown_seconds=300)
    stored = await service._get_unified_by_internal_id(account.id)
    assert stored["status"] == "cooldown"
    assert stored["cooldown_until"] > 0
    await engine.dispose()
