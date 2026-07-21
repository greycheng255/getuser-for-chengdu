# -*- coding: utf-8 -*-
"""
轻量级内存限流器

设计:
- 基于 token bucket + 滑动窗口
- 按 user_id(已认证)或 client IP(未认证)分桶
- 单进程内存存储(适合 uvicorn 单 worker 部署)
- 不依赖 redis 等外部组件,零运维成本

用法:
    from api.utils.rate_limit import rate_limit

    @router.get("/foo", dependencies=[Depends(rate_limit(60))])
    async def get_foo():
        ...

    # AI 类接口可以用更严格的限流
    @router.post("/ai", dependencies=[Depends(rate_limit(20))])
    async def call_ai():
        ...

进阶:
    如需分布式限流,可改用 slowapi + redis。本模块保持轻量,
    适合中小规模部署(单进程 QPS < 1000)。
"""
import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from fastapi import Depends, HTTPException, Request, status

from .exceptions import RateLimitError
from .workbench_config import workbench_config


@dataclass
class _Bucket:
    """每个客户端一个桶,记录最近 60 秒的请求时间戳"""
    timestamps: Deque[float] = field(default_factory=deque)
    last_cleaned: float = field(default_factory=time.time)


class _RateLimiter:
    """单进程内存限流器"""

    def __init__(self):
        self._buckets: Dict[str, _Bucket] = defaultdict(_Bucket)
        self._lock = asyncio.Lock()
        # 自动清理:每 5 分钟清理一次过期桶,避免内存泄漏
        self._last_gc = time.time()
        self._gc_interval = 300

    async def check(self, key: str, per_minute: int) -> None:
        """检查是否允许请求。若超限,抛出 RateLimitError。

        Args:
            key: 限流键(user_id 或 client_ip)
            per_minute: 每分钟允许的最大请求数
        """
        if per_minute <= 0:
            return  # 0 = 不限流

        now = time.time()
        async with self._lock:
            # 周期性 GC
            if now - self._last_gc > self._gc_interval:
                self._gc(now)
                self._last_gc = now

            bucket = self._buckets[key]
            # 移除 60 秒前的时间戳(滑动窗口)
            while bucket.timestamps and bucket.timestamps[0] < now - 60:
                bucket.timestamps.popleft()

            if len(bucket.timestamps) >= per_minute:
                # 计算还需等多久
                oldest = bucket.timestamps[0]
                retry_after = int(60 - (now - oldest)) + 1
                raise RateLimitError(
                    message=f"请求过于频繁,每分钟限 {per_minute} 次,请 {retry_after} 秒后重试",
                    data={"retry_after": retry_after, "limit": per_minute},
                )

            bucket.timestamps.append(now)

    def _gc(self, now: float) -> None:
        """清理超过 5 分钟未访问的桶"""
        expired = [
            k for k, b in self._buckets.items()
            if not b.timestamps or (now - (b.timestamps[-1] if b.timestamps else b.last_cleaned)) > 300
        ]
        for k in expired:
            del self._buckets[k]


# 全局单例
_limiter = _RateLimiter()


def _get_client_key(request: Request) -> str:
    """提取客户端标识:优先用认证用户的 uid,其次用 X-Forwarded-For,最后用 client.host"""
    # 1. 已认证用户(从 request.state.user 取,由 AuthMiddleware 注入)
    user = getattr(request.state, "user", None)
    if user and isinstance(user, dict) and user.get("id"):
        return f"user:{user['id']}"
    # 2. X-Forwarded-For(经过代理)
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        # 取第一个 IP(最原始的客户端)
        return f"ip:{xff.split(',')[0].strip()}"
    # 3. 直连 IP
    return f"ip:{request.client.host if request.client else 'unknown'}"


def rate_limit(per_minute: Optional[int] = None):
    """FastAPI 依赖:对当前客户端限流

    Args:
        per_minute: 每分钟允许的最大请求数。None 时使用全局默认值(workbench_config.rate_limit_per_minute)
    """
    limit = per_minute if per_minute is not None else workbench_config.rate_limit_per_minute

    async def _dep(request: Request):
        key = _get_client_key(request)
        await _limiter.check(key, limit)

    return _dep


def ai_rate_limit():
    """AI 类接口专用限流(更严格,默认 20 次/分钟)"""
    return rate_limit(per_minute=workbench_config.ai_rate_limit_per_minute)
