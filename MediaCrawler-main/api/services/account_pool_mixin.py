# -*- coding: utf-8 -*-
"""账号池共用集成模块

为非抖音平台（xhs/bili/ks/wb）的爬虫 client 提供 account_pool 集成能力。
设计目标：最小侵入，各平台 client 只需在 request 方法外层包一层即可。

核心模式（参照 douyin/client.py）：
1. 每次请求前从 account_pool 取一个健康账号
2. 把账号的 cookie 注入到请求头
3. 用账号绑定的网卡出口发请求
4. 检测风控信号 → report_failure + switch_account + 重试
5. 请求成功 → report_success

各平台只需提供：
- detect_risk_fn(result, response_text) -> Optional[str]
  用于识别本平台的风控信号（verify_check / captcha / rate_limit / blocked / ...）
"""
import asyncio
from typing import Any, Callable, Dict, Optional

from tools.httpx_util import make_async_client


async def request_with_account_pool(
    *,
    method: str,
    url: str,
    headers: Dict,
    account_pool,
    detect_risk_fn: Callable[[Any, str], Optional[str]],
    proxy: Optional[str] = None,
    timeout: int = 60,
    max_retries: int = 3,
    logger=None,
    platform_name: str = "",
    **kwargs,
) -> Any:
    """带账号池自动切换的请求包装器

    Args:
        method: HTTP 方法
        url: 完整 URL
        headers: 请求头（会被原地修改 Cookie 字段）
        account_pool: AccountPool 实例（None 时退化为普通请求）
        detect_risk_fn: 平台专属风控检测函数
        proxy: 代理
        timeout: 超时秒
        max_retries: 最大重试次数
        logger: 日志对象
        platform_name: 平台名（日志用）
        **kwargs: 透传给 httpx 的参数（params/data/json 等）

    Returns:
        解析后的 JSON 响应

    Raises:
        DataFetchError: 重试耗尽
    """
    from .account_pool import classify_error

    tag = f"[{platform_name}PoolClient]" if platform_name else "[PoolClient]"
    last_error = None
    response_text = ""

    for attempt in range(max_retries):
        # 1. 取健康账号
        if account_pool:
            account = await account_pool.get_healthy_account()
            if account and account.cookie:
                headers["Cookie"] = account.cookie
                current_account_id = account.account_id
                current_interface = account.network_interface
                current_alias = account.cookie_alias or "账号"
                current_public_ip = account.public_ip or ""
                cookie_preview = account.cookie[:30] + "..." if len(account.cookie) > 30 else account.cookie
                if logger:
                    logger.info(
                        f"{tag} >>> {current_alias} | IP: {current_interface} ({current_public_ip}) | "
                        f"Cookie: {cookie_preview} | URL: {url} | attempt {attempt+1}/{max_retries}"
                    )
            else:
                current_account_id = None
                current_interface = None
                current_alias = "默认"
                current_public_ip = ""
                if logger:
                    logger.warning(f"{tag} No healthy account, using default cookie")
        else:
            current_account_id = None
            current_interface = None
            current_alias = "无账号池"
            current_public_ip = ""

        # 2. 发请求
        try:
            async with make_async_client(
                proxy=proxy,
                network_interface=current_interface
            ) as client:
                response = await client.request(method, url, timeout=timeout, **kwargs)

            response_text = response.text
            if response_text == "" or response_text == "blocked":
                if logger:
                    logger.error(f"{tag} Blocked response: {response_text}")
                raise Exception("account blocked")

            result = response.json()

            # 3. 风控检测
            fail_type = detect_risk_fn(result, response_text)
            if fail_type:
                if account_pool and current_account_id:
                    should_switch = await account_pool.report_failure(current_account_id, fail_type)
                    if should_switch and attempt < max_retries - 1:
                        if logger:
                            logger.warning(f"{tag} Risk detected ({fail_type}), switching account...")
                        await account_pool.switch_account(fail_type)
                        continue
                # 无账号池或重试耗尽
                from media_platform.xhs.exception import DataFetchError as XhsDataFetchError
                raise XhsDataFetchError(f"Risk detected: {fail_type}, response: {response_text[:200]}")

            # 4. 成功
            if account_pool and current_account_id:
                await account_pool.report_success(current_account_id)
                if logger:
                    logger.info(
                        f"{tag} ✓ 成功 | {current_alias} | IP: {current_interface} ({current_public_ip})"
                    )

            return result

        except Exception as e:
            # 已是 DataFetchError 直接抛
            if "Risk detected" in str(e):
                raise
            last_error = e
            fail_type = classify_error(e, response_text)
            if account_pool and current_account_id:
                should_switch = await account_pool.report_failure(current_account_id, fail_type)
                if should_switch and attempt < max_retries - 1:
                    if logger:
                        logger.warning(f"{tag} Error ({fail_type}), switching account...")
                    await account_pool.switch_account(fail_type)
                    continue
            if attempt == max_retries - 1:
                from media_platform.xhs.exception import DataFetchError
                raise DataFetchError(f"{e}, {response_text}")


# ============================================================
# 平台专属风控检测函数
# ============================================================

def detect_xhs_risk(result: Any, response_text: str) -> Optional[str]:
    """小红书风控信号检测"""
    if not isinstance(result, dict):
        return None
    # 常见风控字段
    success = result.get("success", True)
    code = result.get("code")
    msg = str(result.get("msg", "")) or ""

    # 小红书未登录 / 风控
    if code in (300012, 300013, 300015, 300021):
        return "blocked"
    if "未登录" in msg or "登录" in msg and "验证" in msg:
        return "blocked"
    if any(kw in response_text.lower() for kw in ["captcha", "verify", "验证码", "shield", "风险"]):
        return "captcha"
    if any(kw in msg for kw in ["频繁", "频率", "限制", "稍后"]):
        return "rate_limit"
    if success is False and code and code != 0:
        return "blocked"
    return None


def detect_bili_risk(result: Any, response_text: str) -> Optional[str]:
    """B站风控信号检测"""
    if not isinstance(result, dict):
        return None
    code = result.get("code")
    message = str(result.get("message", "")) or ""
    # B站常见风控 code
    if code in (-101, -352, -403, -509, -799):
        return "blocked"
    if "频率" in message or "限制" in message or "稍后" in message:
        return "rate_limit"
    if any(kw in response_text.lower() for kw in ["captcha", "验证码", "geetest", "risk"]):
        return "captcha"
    return None


def detect_ks_risk(result: Any, response_text: str) -> Optional[str]:
    """快手风控信号检测"""
    if not isinstance(result, dict):
        return None
    # 快手 GraphQL 风控
    errors = result.get("errors") or []
    if errors:
        msg = str(errors[0].get("message", "")) if isinstance(errors[0], dict) else str(errors[0])
        if any(kw in msg for kw in ["风险", "验证", "限制", "频繁"]):
            return "blocked"
    if any(kw in response_text.lower() for kw in ["captcha", "verify", "验证码", "risk"]):
        return "captcha"
    return None


def detect_wb_risk(result: Any, response_text: str) -> Optional[str]:
    """微博风控信号检测"""
    if not isinstance(result, dict):
        return None
    ok = result.get("ok")
    if ok == 0:
        msg = str(result.get("msg", "")) or ""
        if any(kw in msg for kw in ["频率", "限制", "稍后"]):
            return "rate_limit"
        if any(kw in msg for kw in ["验证", "风险", "异常"]):
            return "blocked"
    if any(kw in response_text.lower() for kw in ["captcha", "verify", "验证码"]):
        return "captcha"
    return None


# ============================================================
# 启动时初始化账号池（各平台 core.py 调用）
# ============================================================

async def init_platform_account_pool(platform: str, logger=None):
    """初始化指定平台的账号池

    从 cookie_manager 的 Cookie 池加载所有 Cookie 到 account_pool。
    各平台 core.py 在 startup 时调用此函数即可。

    Args:
        platform: 平台标识 (xhs/bili/ks/wb)
        logger: 日志对象

    Returns:
        AccountPool 实例（无 Cookie 时返回 None）
    """
    from .account_pool import init_account_pool
    from .cookie_manager import get_cookie_pool

    cookie_list = get_cookie_pool(platform)
    if not cookie_list:
        if logger:
            logger.info(f"[init_platform_account_pool] {platform} 无Cookie池，跳过初始化")
        return None

    pool = await init_account_pool(platform=platform)

    # 清理旧账号，重新加载
    if pool.accounts:
        if logger:
            logger.info(
                f"[init_platform_account_pool] {platform} 清理 {len(pool.accounts)} 个旧账号"
            )
        pool.accounts = []
        pool.current_account = None

    for i, cookie_str in enumerate(cookie_list):
        await pool.add_account(
            cookie=cookie_str,
            cookie_alias=f"{platform}账号{i+1}",
            # 不绑网卡，由 get_healthy_account 动态随机分配
        )

    if logger:
        logger.info(
            f"[init_platform_account_pool] {platform} 已加载 {len(pool.accounts)} 个账号"
        )
    return pool
