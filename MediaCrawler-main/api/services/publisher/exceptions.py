# -*- coding: utf-8 -*-
"""发布器业务异常体系"""


class PublisherError(Exception):
    """发布器基础异常"""

    def __init__(self, message: str, platform: str = "", *, debug_info: list = None):
        super().__init__(message)
        self.message = message
        self.platform = platform
        self.debug_info = debug_info or []


class LoginExpiredError(PublisherError):
    """登录态失效（cookie 过期 / 被风控踢下线）

    触发后应让 cookie 池标记此 cookie 失效并尝试下一个账号。
    """


class BizError(PublisherError):
    """业务错误（频次过高 / 内容违规 / 账号异常 等）

    通常是不可重试错误，直接返回给上层。
    """


class RateLimitError(PublisherError):
    """平台限流（频次过高）

    触发后此 cookie 应进入冷却期。
    """


class ContentBlockedError(PublisherError):
    """内容被风控拦截（违规词 / 重复内容 / 敏感图）

    触发后应让风控服务记录并阻止再次发布相同内容。
    """
