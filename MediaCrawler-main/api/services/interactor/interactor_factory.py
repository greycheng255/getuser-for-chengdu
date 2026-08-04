# -*- coding: utf-8 -*-
"""
InteractorFactory 注册式工厂

与 PublisherFactory 对齐，使用装饰器注册各平台 Interactor。
"""

import logging
from typing import Dict, List, Optional, Type

from .base_interactor import BaseInteractor

logger = logging.getLogger(__name__)


class InteractorFactory:
    """互动器工厂（注册式）"""

    _registry: Dict[str, Type[BaseInteractor]] = {}

    @classmethod
    def register(cls, platform: str):
        def decorator(interactor_cls: Type[BaseInteractor]) -> Type[BaseInteractor]:
            if not issubclass(interactor_cls, BaseInteractor):
                raise TypeError(f"{interactor_cls.__name__} 必须继承 BaseInteractor")
            cls._registry[platform] = interactor_cls
            interactor_cls.PLATFORM_NAME = platform
            logger.debug(f"[InteractorFactory] 已注册 {platform} -> {interactor_cls.__name__}")
            return interactor_cls

        return decorator

    @classmethod
    def create(
        cls,
        platform: str,
        cookies: str,
        user_id: Optional[int] = None,
        **kwargs,
    ) -> BaseInteractor:
        interactor_cls = cls._registry.get(platform)
        if not interactor_cls:
            available = list(cls._registry.keys())
            raise ValueError(f"不支持的平台: {platform}，已注册: {available}")
        return interactor_cls(cookies=cookies, user_id=user_id, **kwargs)

    @classmethod
    def is_supported(cls, platform: str) -> bool:
        return platform in cls._registry

    @classmethod
    def list_platforms(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def get_interactor_class(cls, platform: str) -> Optional[Type[BaseInteractor]]:
        return cls._registry.get(platform)


def _register_all():
    """自动注册所有内置 Interactor（导入即注册）

    platforms/__init__.py 导入即触发所有子模块的 @register 装饰器。
    """
    try:
        from . import platforms  # noqa: F401
    except ImportError as e:
        logger.warning(f"[InteractorFactory] Interactor 注册失败: {e}")


_register_all()
