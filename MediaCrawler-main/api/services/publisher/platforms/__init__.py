# -*- coding: utf-8 -*-
"""5 个 Playwright Publisher 子类

迁移自 GEO-main 的 5 个 *_automation.py，重构为继承 BasePublisher：
- 公共流程（init / login check / persist / close）上移到基类
- 子类只实现 _do_publish() 和必要的常量

阶段二新增：
- 视频号、今日头条发布器（任务 2.6）
- 海外 5 平台发布器（overseas_publishers.py，PRD 5.3 缺口补齐）
"""
from .douyin_publisher import DouyinPublisher
from .xiaohongshu_publisher import XiaohongshuPublisher
from .bilibili_publisher import BilibiliPublisher
from .weibo_publisher import WeiboPublisher
from .zhihu_publisher import ZhihuPublisher
from .kuaishou_publisher import KuaishouPublisher
from .wechat_channels_publisher import WechatChannelsPublisher
from .toutiao_publisher import ToutiaoPublisher

# 海外 5 平台（TikTok/Instagram/YouTube/Facebook/Twitter）
try:
    from .overseas_publishers import (
        TiktokPublisher,
        InstagramPublisher,
        YoutubePublisher,
        FacebookPublisher,
        TwitterPublisher,
    )
except ImportError as e:  # pragma: no cover - 容错：缺依赖时跳过
    import logging
    logging.getLogger(__name__).warning(f"海外 Publisher 导入失败: {e}")

__all__ = [
    "DouyinPublisher",
    "XiaohongshuPublisher",
    "BilibiliPublisher",
    "WeiboPublisher",
    "ZhihuPublisher",
    "KuaishouPublisher",
    "WechatChannelsPublisher",
    "ToutiaoPublisher",
    "TiktokPublisher",
    "InstagramPublisher",
    "YoutubePublisher",
    "FacebookPublisher",
    "TwitterPublisher",
]
