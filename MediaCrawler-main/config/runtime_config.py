# -*- coding: utf-8 -*-
"""加载本地 ``.env`` 与 Apollo 配置。

Apollo Portal 只用于管理配置；应用运行时必须连接 Config Service 或对应
环境的 Meta Server。加载失败默认降级到本地环境，并由各新能力的安全默认值
保持关闭；设置 ``APOLLO_REQUIRED=true`` 可在部署环境中改为启动失败。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

_loaded = False
_status: Dict[str, Any] = {
    "enabled": False,
    "loaded": False,
    "app_id": "",
    "environment": "",
    "cluster": "",
    "namespace": "",
    "keys_loaded": 0,
    "source": "disabled",
    "last_error": "",
}


def _as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _fetch_json(url: str, timeout: float) -> Any:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - URL is deployment config
        return json.loads(response.read().decode("utf-8"))


def _config_url(base_url: str, app_id: str, cluster: str, namespace: str) -> str:
    return (
        f"{base_url.rstrip('/')}/configs/"
        f"{quote(app_id, safe='')}/{quote(cluster, safe='')}/{quote(namespace, safe='')}"
    )


def _discover_config_server(meta_url: str, app_id: str, timeout: float) -> str:
    query = urlencode({"appId": app_id})
    payload = _fetch_json(f"{meta_url.rstrip('/')}/services/config?{query}", timeout)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("Apollo Meta Server 未返回可用 Config Service")
    for item in payload:
        if isinstance(item, dict):
            homepage = item.get("homepageUrl") or item.get("serviceUrl")
            if homepage:
                return str(homepage).rstrip("/")
    raise RuntimeError("Apollo Config Service 响应缺少 homepageUrl")


def load_apollo_config(*, force: bool = False) -> Dict[str, Any]:
    """将 Apollo ``configurations`` 写入当前进程环境变量。

    返回值仅包含连接状态和键数量，不包含任何配置值。
    """
    global _loaded, _status
    if _loaded and not force:
        return dict(_status)

    enabled = _as_bool("APOLLO_ENABLED", False)
    app_id = os.getenv("APOLLO_APP_ID", "getuser-for-chengdu").strip()
    environment = os.getenv("APOLLO_ENV", "LOCAL").strip()
    cluster = os.getenv("APOLLO_CLUSTER", "dev").strip()
    namespace = os.getenv("APOLLO_NAMESPACE", "application").strip()
    _status = {
        "enabled": enabled,
        "loaded": False,
        "app_id": app_id,
        "environment": environment,
        "cluster": cluster,
        "namespace": namespace,
        "keys_loaded": 0,
        "source": "disabled" if not enabled else "apollo",
        "last_error": "",
    }
    _loaded = True
    if not enabled:
        return dict(_status)

    config_server = os.getenv("APOLLO_CONFIG_SERVER_URL", "").strip()
    meta_server = os.getenv("APOLLO_META_SERVER_URL", "").strip()
    required = _as_bool("APOLLO_REQUIRED", False)
    override = _as_bool("APOLLO_OVERRIDE_ENV", True)
    try:
        timeout = max(0.1, float(os.getenv("APOLLO_TIMEOUT_SECONDS", "3")))
        if not config_server:
            if not meta_server:
                raise RuntimeError(
                    "APOLLO_CONFIG_SERVER_URL 或 APOLLO_META_SERVER_URL 至少配置一项"
                )
            config_server = _discover_config_server(meta_server, app_id, timeout)
            _status["source"] = "meta-discovery"
        else:
            _status["source"] = "config-service"

        payload = _fetch_json(
            _config_url(config_server, app_id, cluster, namespace), timeout
        )
        configurations = payload.get("configurations") if isinstance(payload, dict) else None
        if not isinstance(configurations, dict):
            raise RuntimeError("Apollo Config Service 响应缺少 configurations")

        loaded_count = 0
        for raw_key, raw_value in configurations.items():
            key = str(raw_key).strip()
            if not key or key.startswith("APOLLO_"):
                continue
            if not override and key in os.environ:
                continue
            if isinstance(raw_value, str):
                value = raw_value
            elif raw_value is None:
                value = ""
            else:
                value = json.dumps(raw_value, ensure_ascii=False, separators=(",", ":"))
            os.environ[key] = value
            loaded_count += 1

        _status["loaded"] = True
        _status["keys_loaded"] = loaded_count
        return dict(_status)
    except Exception as exc:
        _status["last_error"] = f"{type(exc).__name__}: {exc}"
        if required:
            raise RuntimeError(f"Apollo 配置加载失败: {_status['last_error']}") from exc
        return dict(_status)


def load_runtime_environment(*, force: bool = False) -> Dict[str, Any]:
    """先加载本地文件，再用 Apollo 配置按策略覆盖。"""
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)
    return load_apollo_config(force=force)


def get_apollo_status() -> Dict[str, Any]:
    return dict(_status)
