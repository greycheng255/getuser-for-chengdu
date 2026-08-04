# -*- coding: utf-8 -*-
"""
PublisherFactory 注册式工厂

设计：
1. 使用装饰器 @PublisherFactory.register("douyin") 注册子类
2. create() 根据 platform 名返回实例
3. 支持运行时动态注册新平台（无需修改 factory 代码）
4. list_platforms() 返回所有已注册平台

迁移自 GEO-main publish_service.py 的 platform_handlers 字典（伪工厂），
改造为真正的工厂模式 + 懒加载。
"""

import logging
from typing import Dict, List, Optional, Type

from .base_publisher import BasePublisher

logger = logging.getLogger(__name__)


class PublisherFactory:
    """发布器工厂（注册式）"""

    _registry: Dict[str, Type[BasePublisher]] = {}

    @classmethod
    def register(cls, platform: str):
        """装饰器：注册一个 Publisher 子类

        用法：
            @PublisherFactory.register("douyin")
            class DouyinPublisher(BasePublisher):
                ...
        """

        def decorator(publisher_cls: Type[BasePublisher]) -> Type[BasePublisher]:
            if not issubclass(publisher_cls, BasePublisher):
                raise TypeError(f"{publisher_cls.__name__} 必须继承 BasePublisher")
            cls._registry[platform] = publisher_cls
            publisher_cls.PLATFORM_NAME = platform
            logger.debug(f"[PublisherFactory] 已注册 {platform} -> {publisher_cls.__name__}")
            return publisher_cls

        return decorator

    @classmethod
    def create(
        cls,
        platform: str,
        cookies: str,
        user_id: Optional[int] = None,
        **kwargs,
    ) -> BasePublisher:
        """创建 Publisher 实例

        Args:
            platform: 平台名（douyin / xiaohongshu / bilibili / weibo / zhihu）
            cookies: cookie 字符串
            user_id: 用户 ID（用于 storage_state 持久化）
            **kwargs: 传递给 Publisher 构造函数的额外参数
        """
        publisher_cls = cls._registry.get(platform)
        if not publisher_cls:
            available = list(cls._registry.keys())
            raise ValueError(
                f"不支持的平台: {platform}，已注册: {available}"
            )
        return publisher_cls(cookies=cookies, user_id=user_id, **kwargs)

    @classmethod
    def is_supported(cls, platform: str) -> bool:
        """检查平台是否已注册"""
        return platform in cls._registry

    @classmethod
    def list_platforms(cls) -> List[str]:
        """列出所有已注册平台"""
        return list(cls._registry.keys())

    @classmethod
    def get_publisher_class(cls, platform: str) -> Optional[Type[BasePublisher]]:
        """获取 Publisher 类（不实例化）"""
        return cls._registry.get(platform)


def _register_all():
    """自动注册所有内置 Publisher

    在模块导入时触发，确保 platforms/ 下的所有 Publisher 都已注册。
    platforms/__init__.py 导入即注册（装饰器副作用），这里只需 import 该包。
    """
    # pylint: disable=import-outside-toplevel
    try:
        # 导入 platforms 包即触发所有子模块的 @register 装饰器
        from . import platforms  # noqa: F401
    except ImportError as e:
        logger.warning(f"[PublisherFactory] Publisher 注册失败: {e}")


# 模块加载时自动注册
_register_all()
