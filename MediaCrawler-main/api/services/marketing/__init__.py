# -*- coding: utf-8 -*-
"""
营销信息植入服务（第四阶段）

对应 PRD 5.2 视频智能生成 - 营销信息植入 + 5.3 发布策略：
1. 营销素材库：LOGO / 二维码 / 引流链接 / 活动信息管理
2. 视频后处理：FFmpeg 在视频中植入水印 / 贴片 / 片尾
3. 文案植入：AI 在发布文案中自然植入引流信息

目录结构：
    marketing/
    ├── __init__.py
    ├── material_library.py   # 营销素材库（DB CRUD）
    ├── video_processor.py    # FFmpeg 视频后处理（水印/贴片/片尾）
    └── copy_inserter.py      # AI 文案植入
"""
from .material_library import (
    MarketingMaterial,
    MaterialType,
    MaterialLibrary,
    get_material_library,
)
from .video_processor import VideoProcessor
from .copy_inserter import CopyInserter, get_copy_inserter

__all__ = [
    "MarketingMaterial",
    "MaterialType",
    "MaterialLibrary",
    "get_material_library",
    "VideoProcessor",
    "CopyInserter",
    "get_copy_inserter",
]
