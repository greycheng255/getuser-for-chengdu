# -*- coding: utf-8 -*-
import subprocess
import httpx
import config


def make_async_client(**kwargs) -> httpx.AsyncClient:
    """创建统一配置的 httpx.AsyncClient。

    从配置文件读取 DISABLE_SSL_VERIFY（默认 False，即开启 SSL 验证）。
    仅在使用企业代理、Burp、mitmproxy 等中间人代理时才需将其设为 True。

    支持多网卡出站：传入 network_interface="eth1" 可指定从某个网卡出站，
    实现多公网IP轮换（需服务器配置策略路由）。
    """
    verify = kwargs.pop("verify", not getattr(config, "DISABLE_SSL_VERIFY", False))

    # 处理网卡绑定（多公网IP轮换）
    network_interface = kwargs.pop("network_interface", None)
    proxy = kwargs.pop("proxy", None)

    if network_interface:
        local_ip = _get_interface_ip(network_interface)
        if local_ip:
            # httpx 0.28+ 支持 local_address 参数绑定源IP
            # 注意：使用transport时，verify/proxy需要传给transport而非AsyncClient
            transport_kwargs = {"local_address": local_ip, "verify": verify}
            if proxy:
                transport_kwargs["proxy"] = proxy
            kwargs["transport"] = httpx.AsyncHTTPTransport(**transport_kwargs)
            # transport已处理verify，避免重复
        elif proxy:
            kwargs["proxy"] = proxy
            kwargs["verify"] = verify
    elif proxy:
        kwargs["proxy"] = proxy
        kwargs["verify"] = verify
    else:
        kwargs["verify"] = verify

    return httpx.AsyncClient(**kwargs)


def _get_interface_ip(interface_name: str) -> str:
    """获取网卡的内网IP地址"""
    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show", interface_name],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            for i, part in enumerate(parts):
                if part == "inet" and i + 1 < len(parts):
                    return parts[i + 1].split("/")[0]
    except Exception:
        pass
    return ""
