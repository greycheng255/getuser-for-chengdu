# -*- coding: utf-8 -*-
"""
AI 文案植入 + 营销信息精细化配置

对应 PRD 5.2 营销信息植入：
- AI 在发布文案中自然植入引流信息（品牌口号 / 引流链接 / 活动信息）
- 阶段一 P0 任务 1.2：精细化配置（自定义位置/时长/形式）

复用 MediaCrawler 现有的 ai_agent_client。
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class InsertPosition(str, Enum):
    """营销信息植入位置"""
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    CENTER = "center"
    WATERMARK = "watermark"           # 全程水印
    LOWER_THIRD = "lower_third"       # 下方字幕条
    END_CARD = "end_card"             # 片尾卡片


class InsertForm(str, Enum):
    """营销信息植入形式"""
    LOGO = "logo"
    QRCODE = "qrcode"
    TEXT_BANNER = "text_banner"
    END_CARD = "end_card"


@dataclass
class InsertConfig:
    """营销信息精细化植入配置（PRD 5.2 营销信息植入）"""
    position: str = InsertPosition.BOTTOM_RIGHT.value
    duration_seconds: int = 0           # 0 = 全程，>0 = 指定时长
    form: str = InsertForm.TEXT_BANNER.value
    opacity: float = 0.8                # 透明度 0-1
    size_ratio: float = 0.15            # 占画面比例


class CopyInserter:
    """AI 文案植入器（含精细化配置）"""

    async def insert_marketing(
        self,
        original_content: str,
        platform: str = "",
        slogans: Optional[List[str]] = None,
        link: Optional[str] = None,
        event_info: Optional[str] = None,
    ) -> str:
        """在原始文案中自然植入营销信息

        Args:
            original_content: 原始文案
            platform: 目标平台（不同平台植入风格不同）
            slogans: 品牌口号列表
            link: 引流链接
            event_info: 活动信息

        Returns:
            植入营销信息后的文案
        """
        # 如果没有营销素材，直接返回原文
        if not slogans and not link and not event_info:
            return original_content

        try:
            from api.services.ai_agent_client import get_ai_agent_client, is_ai_in_cooldown, is_ai_expected_error

            if is_ai_in_cooldown():
                logger.debug("[CopyInserter] AI 服务冷却中，回退到规则植入")
                return self._rule_based_insert(original_content, link, event_info)
            marketing_parts = []
            if slogans:
                marketing_parts.append(f"品牌口号（选一个自然融入）: {', '.join(slogans[:3])}")
            if link:
                marketing_parts.append(f"引流链接: {link}")
            if event_info:
                marketing_parts.append(f"活动信息: {event_info}")

            prompt = (
                f"请把以下营销信息自然地植入到这段发布文案中，要求：\n"
                f"1. 植入要自然，不能生硬\n"
                f"2. 不要改变原文的核心意思\n"
                f"3. 适合{platform or '通用'}平台的发布风格\n"
                f"4. 直接输出修改后的文案，不要解释\n\n"
                f"营销信息：\n" + "\n".join(marketing_parts) + "\n\n"
                f"原始文案：\n{original_content}"
            )
            client = get_ai_agent_client()
            result = await client.generate_text(prompt)
            return result.strip() if result else original_content
        except Exception as e:
            if is_ai_expected_error(e):
                logger.debug(f"[CopyInserter] AI 预期内错误，回退到规则植入: {e}")
            else:
                logger.warning(f"[CopyInserter] AI 植入失败，回退到规则植入: {e}")
            return self._rule_based_insert(original_content, link, event_info)

    async def insert_marketing_with_config(
        self,
        original_content: str,
        platform: str = "",
        slogans: Optional[List[str]] = None,
        link: Optional[str] = None,
        event_info: Optional[str] = None,
        insert_config: Optional[InsertConfig] = None,
    ) -> dict:
        """精细化植入：返回文案 + 视频后处理指令

        阶段一 P0 任务 1.2：补齐 PRD 5.2 营销信息植入的精细化配置。
        文案层面：AI 自然植入
        视频层面：返回后处理指令（位置/时长/形式），由 video_processor 执行

        Returns:
            {
                "content": str,           # 植入后的文案
                "video_overlay": dict,    # 视频贴片指令
            }
        """
        insert_config = insert_config or InsertConfig()
        content = await self.insert_marketing(
            original_content, platform, slogans, link, event_info
        )
        # 构建视频后处理指令（由 marketing/video_processor.py 执行）
        video_overlay = {
            "position": insert_config.position,
            "duration_seconds": insert_config.duration_seconds,
            "form": insert_config.form,
            "opacity": insert_config.opacity,
            "size_ratio": insert_config.size_ratio,
            "text_content": event_info or "",
            "link_url": link or "",
            "logo_url": slogans[0] if slogans else "",
        }
        return {
            "content": content,
            "video_overlay": video_overlay,
        }

    def _rule_based_insert(
        self,
        content: str,
        link: Optional[str] = None,
        event_info: Optional[str] = None,
    ) -> str:
        """规则兜底：在文案末尾追加营销信息"""
        parts = [content]
        if event_info:
            parts.append(f"\n🎁 {event_info}")
        if link:
            parts.append(f"\n🔗 {link}")
        return "".join(parts)

    async def auto_insert_from_library(
        self, content: str, platform: str = ""
    ) -> str:
        """从素材库自动获取营销信息并植入"""
        try:
            from .material_library import get_material_library, MaterialType

            library = get_material_library()
            slogans = await library.get_active_slogans()
            link = await library.get_active_link()
            events = await library.list_materials(material_type=MaterialType.EVENT.value)
            event_info = events[0]["content"] if events else None

            return await self.insert_marketing(
                content, platform, slogans=slogans, link=link, event_info=event_info
            )
        except Exception as e:
            logger.warning(f"[CopyInserter] 自动植入失败: {e}")
            return content


_inserter: Optional[CopyInserter] = None


def get_copy_inserter() -> CopyInserter:
    global _inserter
    if _inserter is None:
        _inserter = CopyInserter()
    return _inserter
