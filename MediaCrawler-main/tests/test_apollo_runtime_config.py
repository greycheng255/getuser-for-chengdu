import json

import pytest

from config import runtime_config


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _clear_apollo_env(monkeypatch):
    for name in (
        "APOLLO_ENABLED",
        "APOLLO_META_SERVER_URL",
        "APOLLO_CONFIG_SERVER_URL",
        "APOLLO_APP_ID",
        "APOLLO_ENV",
        "APOLLO_CLUSTER",
        "APOLLO_NAMESPACE",
        "APOLLO_REQUIRED",
        "APOLLO_OVERRIDE_ENV",
        "APOLLO_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_apollo_is_disabled_by_default(monkeypatch):
    _clear_apollo_env(monkeypatch)
    status = runtime_config.load_apollo_config(force=True)
    assert status["enabled"] is False
    assert status["loaded"] is False
    assert status["keys_loaded"] == 0
    assert status["app_id"] == "getuser-for-chengdu"
    assert status["environment"] == "LOCAL"
    assert status["cluster"] == "dev"


def test_config_service_values_are_loaded_without_exposing_values(monkeypatch):
    _clear_apollo_env(monkeypatch)
    monkeypatch.setenv("APOLLO_ENABLED", "true")
    monkeypatch.setenv("APOLLO_CONFIG_SERVER_URL", "http://config.internal:8080")
    monkeypatch.setenv("APOLLO_APP_ID", "LOCAL")
    monkeypatch.setenv("APOLLO_CLUSTER", "default")
    monkeypatch.setenv("APOLLO_NAMESPACE", "application")
    monkeypatch.delenv("UNIFIED_ACCOUNT_READ_ENABLED", raising=False)

    seen_urls = []

    def fake_urlopen(request, timeout):
        seen_urls.append((request.full_url, timeout))
        return FakeResponse({
            "configurations": {
                "UNIFIED_ACCOUNT_READ_ENABLED": "true",
                "SAMPLE_STRUCTURED_VALUE": {"enabled": True},
                "APOLLO_ENABLED": "false",
            }
        })

    monkeypatch.setattr(runtime_config, "urlopen", fake_urlopen)
    status = runtime_config.load_apollo_config(force=True)
    assert status["loaded"] is True
    assert status["keys_loaded"] == 2
    assert status["source"] == "config-service"
    assert "LOCAL/default/application" in seen_urls[0][0]
    assert runtime_config.os.environ["UNIFIED_ACCOUNT_READ_ENABLED"] == "true"
    assert runtime_config.os.environ["SAMPLE_STRUCTURED_VALUE"] == '{"enabled":true}'
    assert runtime_config.os.environ["APOLLO_ENABLED"] == "true"
    assert "configurations" not in status


def test_meta_server_discovers_config_service(monkeypatch):
    _clear_apollo_env(monkeypatch)
    monkeypatch.setenv("APOLLO_ENABLED", "true")
    monkeypatch.setenv("APOLLO_META_SERVER_URL", "http://meta.internal:8080")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if "/services/config" in request.full_url:
            return FakeResponse([{"homepageUrl": "http://config.internal:8080/"}])
        return FakeResponse({"configurations": {"UNIFIED_SCRIPT_LIBRARY_ENABLED": "true"}})

    monkeypatch.setattr(runtime_config, "urlopen", fake_urlopen)
    status = runtime_config.load_apollo_config(force=True)
    assert status["loaded"] is True
    assert status["source"] == "meta-discovery"
    assert len(calls) == 2
    assert calls[0].startswith("http://meta.internal:8080/services/config")
    assert calls[1].startswith("http://config.internal:8080/configs/")


def test_apollo_failure_is_fail_open_or_strict_by_configuration(monkeypatch):
    _clear_apollo_env(monkeypatch)
    monkeypatch.setenv("APOLLO_ENABLED", "true")
    status = runtime_config.load_apollo_config(force=True)
    assert status["loaded"] is False
    assert status["last_error"]

    monkeypatch.setenv("APOLLO_REQUIRED", "true")
    with pytest.raises(RuntimeError, match="Apollo 配置加载失败"):
        runtime_config.load_apollo_config(force=True)
