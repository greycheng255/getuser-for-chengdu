# -*- coding: utf-8 -*-
"""各平台互动器（点赞 / 评论 / 回复 / 关注 / 收藏）

阶段二 P1 补齐：导入海外 5 平台互动器（overseas_interactors.py）。
"""
from .douyin_interactor import DouyinInteractor  # noqa: F401
from .xiaohongshu_interactor import XiaohongshuInteractor  # noqa: F401
from .bilibili_interactor import BilibiliInteractor  # noqa: F401
from .weibo_interactor import WeiboInteractor  # noqa: F401
from .zhihu_interactor import ZhihuInteractor  # noqa: F401
from .kuaishou_interactor import KuaishouInteractor  # noqa: F401

# 海外 5 平台互动器（TikTok/Instagram/YouTube/Facebook/Twitter）
try:
    from .overseas_interactors import (
        TiktokInteractor,
        InstagramInteractor,
        YoutubeInteractor,
        FacebookInteractor,
        TwitterInteractor,
    )
except ImportError as e:  # pragma: no cover
    import logging
    logging.getLogger(__name__).warning(f"海外 Interactor 导入失败: {e}")

__all__ = [
    "DouyinInteractor",
    "XiaohongshuInteractor",
    "BilibiliInteractor",
    "WeiboInteractor",
    "ZhihuInteractor",
    "KuaishouInteractor",
    "TiktokInteractor",
    "InstagramInteractor",
    "YoutubeInteractor",
    "FacebookInteractor",
    "TwitterInteractor",
]
