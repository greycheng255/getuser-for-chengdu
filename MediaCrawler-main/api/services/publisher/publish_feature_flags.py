# -*- coding: utf-8 -*-
"""核心平台发布能力开关；环境未配置时视频能力保持关闭。"""

import os


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def douyin_video_publish_enabled() -> bool:
    return _enabled("DOUYIN_VIDEO_PUBLISH_ENABLED")


def xiaohongshu_video_publish_enabled() -> bool:
    return _enabled("XIAOHONGSHU_VIDEO_PUBLISH_ENABLED")
