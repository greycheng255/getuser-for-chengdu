from api.services.account_feature_flags import (
    legacy_account_api_enabled,
    unified_account_read_enabled,
    unified_account_write_enabled,
)
from api.services.publisher.publish_feature_flags import (
    douyin_video_publish_enabled,
    xiaohongshu_video_publish_enabled,
)
from api.services.script_feature_flags import unified_script_library_enabled


def test_new_capabilities_are_closed_when_environment_is_missing(monkeypatch):
    names = (
        "UNIFIED_ACCOUNT_READ_ENABLED",
        "UNIFIED_ACCOUNT_WRITE_ENABLED",
        "LEGACY_ACCOUNT_API_ENABLED",
        "UNIFIED_SCRIPT_LIBRARY_ENABLED",
        "DOUYIN_VIDEO_PUBLISH_ENABLED",
        "XIAOHONGSHU_VIDEO_PUBLISH_ENABLED",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)

    assert unified_account_read_enabled() is False
    assert unified_account_write_enabled() is False
    assert unified_script_library_enabled() is False
    assert douyin_video_publish_enabled() is False
    assert xiaohongshu_video_publish_enabled() is False
    assert legacy_account_api_enabled() is True


def test_each_capability_can_be_enabled_independently(monkeypatch):
    monkeypatch.setenv("UNIFIED_ACCOUNT_READ_ENABLED", "true")
    monkeypatch.setenv("UNIFIED_ACCOUNT_WRITE_ENABLED", "1")
    monkeypatch.setenv("UNIFIED_SCRIPT_LIBRARY_ENABLED", "yes")
    monkeypatch.setenv("DOUYIN_VIDEO_PUBLISH_ENABLED", "on")
    monkeypatch.setenv("XIAOHONGSHU_VIDEO_PUBLISH_ENABLED", "TRUE")
    monkeypatch.setenv("LEGACY_ACCOUNT_API_ENABLED", "false")

    assert unified_account_read_enabled() is True
    assert unified_account_write_enabled() is True
    assert unified_script_library_enabled() is True
    assert douyin_video_publish_enabled() is True
    assert xiaohongshu_video_publish_enabled() is True
    assert legacy_account_api_enabled() is False
