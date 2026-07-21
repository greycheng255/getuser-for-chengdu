# -*- coding: utf-8 -*-
"""
工作台集中配置

把分散在各处的环境变量读取统一收口,避免:
1. 同一个配置项在不同文件用不同默认值
2. 配置项改名时需要全局搜索
3. 缺乏类型转换和默认值文档

用法:
    from api.utils.workbench_config import workbench_config
    interval = workbench_config.reply_check_interval
    if workbench_config.enable_cdp_mode:
        ...

所有配置在模块加载时读取一次(运行时修改环境变量不会生效,需重启)。
"""
import os
from dataclasses import dataclass, field


def _get_int(key: str, default: int) -> int:
    """读取整型环境变量,转换失败用默认值"""
    v = os.getenv(key, "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _get_bool(key: str, default: bool) -> bool:
    """读取布尔型环境变量(支持 1/0/true/false/yes/no)"""
    v = os.getenv(key, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _get_str(key: str, default: str) -> str:
    return os.getenv(key, default).strip()


@dataclass(frozen=True)
class WorkbenchConfig:
    """X Twitter 工作台配置(只读)"""

    # ---------- 监控相关 ----------
    # 评论回复检查间隔(秒)
    reply_check_interval: int = field(default_factory=lambda: _get_int("X_WORKBENCH_REPLY_CHECK_INTERVAL", 180))
    # 每日 AI 回复上限
    reply_daily_limit: int = field(default_factory=lambda: _get_int("X_WORKBENCH_REPLY_DAILY_LIMIT", 100))
    # 单次轮询最多检查多少条已发评论
    batch_size: int = field(default_factory=lambda: _get_int("X_WORKBENCH_BATCH_SIZE", 10))
    # 已发评论多久后停止监控(秒,默认 7 天)
    monitor_ttl: int = field(default_factory=lambda: _get_int("X_WORKBENCH_MONITOR_TTL", 7 * 24 * 3600))
    # 浏览器并发上限
    browser_concurrency: int = field(default_factory=lambda: _get_int("X_WORKBENCH_BROWSER_CONCURRENCY", 3))
    # AI 回复并发上限
    ai_reply_concurrency: int = field(default_factory=lambda: _get_int("X_WORKBENCH_AI_REPLY_CONCURRENCY", 2))

    # ---------- AI 调用相关 ----------
    # AI 调用最大重试次数(0 = 不重试)
    ai_retry_max: int = field(default_factory=lambda: _get_int("X_WORKBENCH_AI_RETRY_MAX", 3))
    # AI 调用初始重试间隔(秒,指数退避)
    ai_retry_initial_delay: float = field(default_factory=lambda: float(_get_str("X_WORKBENCH_AI_RETRY_INITIAL_DELAY", "1.0")))
    # AI 调用超时(秒)
    ai_timeout: float = field(default_factory=lambda: float(_get_str("X_WORKBENCH_AI_TIMEOUT", "60.0")))

    # ---------- 限流相关 ----------
    # 每分钟最多请求数(全局,0 = 不限)
    rate_limit_per_minute: int = field(default_factory=lambda: _get_int("X_WORKBENCH_RATE_LIMIT_PER_MINUTE", 120))
    # AI 类接口每分钟最多请求数(更严格,0 = 不限)
    ai_rate_limit_per_minute: int = field(default_factory=lambda: _get_int("X_WORKBENCH_AI_RATE_LIMIT_PER_MINUTE", 20))

    # ---------- 浏览器/CDP ----------
    enable_cdp_mode: bool = field(default_factory=lambda: _get_bool("ENABLE_CDP_MODE", True))

    # ---------- 评论模板 ----------
    # 是否启用评论模板系统
    enable_comment_templates: bool = field(default_factory=lambda: _get_bool("X_WORKBENCH_ENABLE_TEMPLATES", True))

    # ---------- 通知系统 ----------
    # 是否启用通知(收到新回复时推送)
    enable_notifications: bool = field(default_factory=lambda: _get_bool("X_WORKBENCH_ENABLE_NOTIFICATIONS", False))
    # 通知渠道:email,dingtalk,wechat,逗号分隔
    notification_channels: str = field(default_factory=lambda: _get_str("X_WORKBENCH_NOTIFICATION_CHANNELS", ""))
    # 邮件通知收件人(逗号分隔)
    notification_email_to: str = field(default_factory=lambda: _get_str("X_WORKBENCH_NOTIFICATION_EMAIL_TO", ""))
    # 钉钉 webhook
    notification_dingtalk_webhook: str = field(default_factory=lambda: _get_str("X_WORKBENCH_DINGTALK_WEBHOOK", ""))
    # 企业微信 webhook
    notification_wechat_webhook: str = field(default_factory=lambda: _get_str("X_WORKBENCH_WECHAT_WEBHOOK", ""))

    # ---------- 数据导出 ----------
    # 单次导出最大行数(防止 OOM)
    export_max_rows: int = field(default_factory=lambda: _get_int("X_WORKBENCH_EXPORT_MAX_ROWS", 10000))

    # ---------- 通用 ----------
    # 当前账号用户名(可选,优先级高于从数据库提取)
    my_username: str = field(default_factory=lambda: _get_str("X_TWITTER_MY_USERNAME", ""))

    def as_dict(self) -> dict:
        """转字典(用于调试和文档)"""
        return {
            "reply_check_interval": self.reply_check_interval,
            "reply_daily_limit": self.reply_daily_limit,
            "batch_size": self.batch_size,
            "monitor_ttl": self.monitor_ttl,
            "browser_concurrency": self.browser_concurrency,
            "ai_reply_concurrency": self.ai_reply_concurrency,
            "ai_retry_max": self.ai_retry_max,
            "ai_timeout": self.ai_timeout,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "ai_rate_limit_per_minute": self.ai_rate_limit_per_minute,
            "enable_cdp_mode": self.enable_cdp_mode,
            "enable_comment_templates": self.enable_comment_templates,
            "enable_notifications": self.enable_notifications,
            "notification_channels": self.notification_channels,
            "export_max_rows": self.export_max_rows,
        }


# 全局单例
workbench_config = WorkbenchConfig()
