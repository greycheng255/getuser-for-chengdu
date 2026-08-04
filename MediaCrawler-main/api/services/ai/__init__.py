# -*- coding: utf-8 -*-
"""
AI 服务（P0：AI 能力扩展）

对应 PRD 5.2 视频智能生成 - AI 内容生成、图像生成、多 AI 平台集成。

迁移自 GEO-main：
- ai_service.py：AI 服务调用（OneLLM/lk888.ai 网关，聊天/媒体/反馈/余额）
- ai_platform_service.py：多 AI 平台集成（豆包/DeepSeek/Kimi/通义/文心等）
- ai_task_manager.py：AI 任务管理（任务生命周期、提示词生成、平台任务）
- ai_citation_scheduler.py：AI 引用率定时检测调度器
- image_generation_service.py：图像生成服务（多模型重试链：onellm/ai_agent/pollinations/openai）

目录结构：
    ai/
    ├── __init__.py
    ├── ai_service.py
    ├── ai_platform_service.py
    ├── ai_task_manager.py
    ├── ai_citation_scheduler.py
    └── image_generation_service.py
"""
from .ai_service import AIService, get_ai_service
from .ai_platform_service import (
    MultiAIPlatformService,
    get_ai_platform_service,
)
from .ai_task_manager import AITaskManager, get_ai_task_service
from .ai_citation_scheduler import (
    AICitationScheduler,
    get_ai_citation_scheduler,
)
from .image_generation_service import (
    ImageGenerationService,
    get_image_generation_service,
)
from .video_generation_config import (
    VideoGenConfig,
    VideoGenerationConfigService,
    get_video_generation_config_service,
)
from .batch_video_generator import (
    BatchVideoGenerator,
    get_batch_video_generator,
)
from .prompt_library import (
    PromptLibrary,
    PromptRecord,
    get_prompt_library,
)
from .storyboard_parser import (
    Scene,
    Storyboard,
    StoryboardParser,
    get_storyboard_parser,
)
from .prompt_storyboard_pipeline import (
    PromptStoryboardPipeline,
    get_prompt_storyboard_pipeline,
)
from .video_asset_library import (
    VideoAssetLibrary,
    get_video_asset_library,
)

__all__ = [
    "AIService",
    "get_ai_service",
    "MultiAIPlatformService",
    "get_ai_platform_service",
    "AITaskManager",
    "get_ai_task_service",
    "AICitationScheduler",
    "get_ai_citation_scheduler",
    "ImageGenerationService",
    "get_image_generation_service",
    "VideoGenConfig",
    "VideoGenerationConfigService",
    "get_video_generation_config_service",
    "BatchVideoGenerator",
    "get_batch_video_generator",
    "PromptLibrary",
    "PromptRecord",
    "get_prompt_library",
    "Scene",
    "Storyboard",
    "StoryboardParser",
    "get_storyboard_parser",
    "PromptStoryboardPipeline",
    "get_prompt_storyboard_pipeline",
    "VideoAssetLibrary",
    "get_video_asset_library",
]
