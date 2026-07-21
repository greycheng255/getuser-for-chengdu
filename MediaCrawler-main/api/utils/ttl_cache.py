# -*- coding: utf-8 -*-
"""轻量级 TTL 内存缓存工具

适用场景:
- 读多写少的 API 接口(如平台列表、统计、热点)
- 短时间内重复请求频繁的接口

特性:
- 基于 asyncio.Lock 保证并发安全
- 支持 TTL 自动过期
- 支持 key 维度的缓存失效(主动失效)
- 不依赖外部服务,纯内存

使用示例:
    from api.utils.ttl_cache import ttl_cache

    @ttl_cache(ttl_seconds=60)
    async def get_platforms():
        ...

    # 主动失效
    await get_platforms.invalidate()
"""
import asyncio
import time
from typing import Any, Callable, Dict, Optional, Tuple


class _CacheEntry:
    __slots__ = ("value", "expire_at")

    def __init__(self, value: Any, expire_at: float):
        self.value = value
        self.expire_at = expire_at

    def is_expired(self) -> bool:
        return time.time() >= self.expire_at


class TTLCache:
    """TTL 内存缓存(并发安全)"""

    def __init__(self, ttl_seconds: int = 60, max_entries: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._store: Dict[str, _CacheEntry] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def get_or_compute(self, key: str, factory: Callable[[], Any]) -> Any:
        """获取缓存,不存在或过期则调用 factory 重新计算并缓存。

        factory 应该是 async callable。
        """
        # 快速路径:命中且未过期
        entry = self._store.get(key)
        if entry and not entry.is_expired():
            return entry.value

        # 获取 key 级别的锁,避免缓存击穿(同一 key 并发只算一次)
        async with self._global_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock

        async with lock:
            # double-check:拿到锁后再看一次,可能已被其他请求填充
            entry = self._store.get(key)
            if entry and not entry.is_expired():
                return entry.value

            value = await factory()
            self._store[key] = _CacheEntry(
                value=value,
                expire_at=time.time() + self.ttl_seconds,
            )
            # 简单的容量控制:超过上限时清理最早过期的条目
            if len(self._store) > self.max_entries:
                self._evict_expired()
            return value

    def invalidate(self, key: Optional[str] = None) -> None:
        """主动失效:不传 key 则清空整个缓存"""
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)

    def _evict_expired(self) -> None:
        """清理已过期的条目"""
        now = time.time()
        expired_keys = [k for k, e in self._store.items() if now >= e.expire_at]
        for k in expired_keys:
            self._store.pop(k, None)
        # 如果清理完仍然超限,删除最早过期的(近似 LRU)
        if len(self._store) > self.max_entries:
            sorted_items = sorted(self._store.items(), key=lambda x: x[1].expire_at)
            for k, _ in sorted_items[: len(self._store) - self.max_entries]:
                self._store.pop(k, None)


# ==================== 装饰器 ====================

def ttl_cache(ttl_seconds: int = 60, key_fn: Optional[Callable] = None):
    """装饰器:给 async 函数加 TTL 缓存。

    Args:
        ttl_seconds: 缓存存活秒数
        key_fn: 自定义 key 生成函数 (args, kwargs) -> str
                默认用位置参数 + 关键字参数的字符串拼接

    Returns:
        被装饰的 async 函数,附带 .invalidate() 方法
    """
    cache = TTLCache(ttl_seconds=ttl_seconds)

    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            if key_fn:
                cache_key = key_fn(*args, **kwargs)
            else:
                # 默认 key:函数名 + args + kwargs
                try:
                    arg_str = repr((args, tuple(sorted(kwargs.items()))))
                except Exception:
                    arg_str = str(args)
                cache_key = f"{func.__qualname__}:{arg_str}"

            return await cache.get_or_compute(
                cache_key,
                lambda: func(*args, **kwargs),
            )

        async def invalidate_all():
            cache.invalidate()

        wrapper.invalidate = invalidate_all  # type: ignore
        wrapper._cache = cache  # type: ignore  # 暴露 cache 便于精细控制
        return wrapper

    return decorator
