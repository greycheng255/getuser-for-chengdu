# -*- coding: utf-8 -*-
"""
分镜结构化解析器（阶段四任务 4.2 独立拆出）

从 ai_agent_client 输出的非结构化拆解文本，解析为 Storyboard 结构化数据。

支持多种格式：
1. JSON 格式（最优）
2. 编号列表格式（"1. ..." / "场景1: ..." / "Scene 1: ..."）
3. 自然语言段落（兜底，按句号分割）

设计为独立模块，便于复用：
- prompt_storyboard_pipeline 调用
- prompt_library 沉淀时调用
- 单独 API 暴露
"""

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Scene:
    """单个分镜场景"""

    scene_index: int = 0
    shot_type: str = ""  # 远景/中景/近景/特写
    duration: float = 0.0  # 秒
    visual_prompt: str = ""  # 视觉描述
    voiceover: str = ""  # 配音文案
    subtitle: str = ""  # 字幕文本
    transition: str = ""  # 转场效果
    camera_motion: str = ""  # 镜头运动


@dataclass
class Storyboard:
    """完整分镜"""

    storyboard_id: str = ""
    source_video_url: str = ""
    title: str = ""
    total_duration: float = 0.0
    scenes: List[Scene] = field(default_factory=list)
    overall_prompt: str = ""  # 整体提示词
    style_keywords: List[str] = field(default_factory=list)
    category: str = ""  # 热点类型
    tags: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    owner_user_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "storyboard_id": self.storyboard_id,
            "source_video_url": self.source_video_url,
            "title": self.title,
            "total_duration": self.total_duration,
            "scenes": [asdict(s) for s in self.scenes],
            "overall_prompt": self.overall_prompt,
            "style_keywords": self.style_keywords,
            "category": self.category,
            "tags": self.tags,
            "created_at": self.created_at,
            "owner_user_id": self.owner_user_id,
        }

    def to_db_dict(self) -> Dict[str, Any]:
        """用于入库的扁平化结构"""
        return {
            "storyboard_id": self.storyboard_id,
            "source_video_url": self.source_video_url,
            "title": self.title,
            "total_duration": self.total_duration,
            "scenes_json": json.dumps([asdict(s) for s in self.scenes], ensure_ascii=False),
            "overall_prompt": self.overall_prompt,
            "style_keywords": self.style_keywords,
            "category": self.category,
            "tags": self.tags,
            "created_at": self.created_at,
            "owner_user_id": self.owner_user_id,
        }


class StoryboardParser:
    """分镜结构化解析器"""

    # 分镜场景的正则模式
    SCENE_PATTERNS = [
        r"(?:场景|分镜|Scene|镜头)\s*(\d+)[：:.\s]+(.*?)(?=(?:场景|分镜|Scene|镜头)\s*\d+|$)",
        r"^\s*(\d+)[.、)\s]+(.*?)(?=^\s*\d+[.、)\s]+|$)",
    ]

    def parse(self, raw_text: str, source_video_url: str = "") -> Storyboard:
        """解析拆解文本为分镜结构"""
        if not raw_text:
            return Storyboard(source_video_url=source_video_url)

        storyboard_id = f"sb_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()

        # 1. 尝试 JSON 解析
        scenes = self._try_parse_json(raw_text)
        # 2. 尝试编号列表解析
        if not scenes:
            scenes = self._try_parse_numbered(raw_text)
        # 3. 兜底：按句号分割
        if not scenes:
            scenes = self._fallback_parse(raw_text)

        # 提取标题和整体提示词
        title = self._extract_title(raw_text)
        overall_prompt = self._extract_overall_prompt(raw_text)
        style_keywords = self._extract_style_keywords(raw_text)
        category = self._extract_category(raw_text)
        tags = self._extract_tags(raw_text)
        total_duration = sum(s.duration for s in scenes)

        return Storyboard(
            storyboard_id=storyboard_id,
            source_video_url=source_video_url,
            title=title,
            total_duration=total_duration,
            scenes=scenes,
            overall_prompt=overall_prompt,
            style_keywords=style_keywords,
            category=category,
            tags=tags,
            created_at=now,
        )

    def _try_parse_json(self, text: str) -> List[Scene]:
        try:
            json_match = re.search(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                data = json.loads(text)
            if isinstance(data, dict):
                data = data.get("scenes", data.get("storyboard", []))
            if not isinstance(data, list):
                return []
            scenes: List[Scene] = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                scenes.append(
                    Scene(
                        scene_index=i,
                        shot_type=item.get("shot_type", item.get("镜头类型", "")),
                        duration=float(item.get("duration", item.get("时长", 0))),
                        visual_prompt=item.get("visual_prompt", item.get("画面", item.get("视觉", ""))),
                        voiceover=item.get("voiceover", item.get("配音", item.get("解说", ""))),
                        subtitle=item.get("subtitle", item.get("字幕", "")),
                        transition=item.get("transition", item.get("转场", "")),
                        camera_motion=item.get("camera_motion", item.get("镜头运动", "")),
                    )
                )
            return scenes
        except Exception:
            return []

    def _try_parse_numbered(self, text: str) -> List[Scene]:
        scenes: List[Scene] = []
        for pattern in self.SCENE_PATTERNS:
            matches = re.findall(pattern, text, re.MULTILINE | re.DOTALL)
            if matches:
                for i, (idx, content) in enumerate(matches):
                    content = content.strip()
                    if not content:
                        continue
                    scenes.append(
                        Scene(
                            scene_index=i,
                            visual_prompt=content[:200],
                            voiceover=content[:200],
                            duration=self._extract_duration(content),
                        )
                    )
                if scenes:
                    break
        return scenes

    def _fallback_parse(self, text: str) -> List[Scene]:
        sentences = re.split(r"[。.\n]+", text)
        scenes: List[Scene] = []
        for i, s in enumerate(sentences):
            s = s.strip()
            if len(s) < 5:
                continue
            scenes.append(
                Scene(
                    scene_index=i,
                    visual_prompt=s[:200],
                    voiceover=s[:200],
                )
            )
            if len(scenes) >= 20:
                break
        return scenes

    def _extract_duration(self, text: str) -> float:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|s|sec)", text)
        return float(m.group(1)) if m else 0.0

    def _extract_title(self, text: str) -> str:
        m = re.search(r"(?:标题|title|主题)[：:]\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _extract_overall_prompt(self, text: str) -> str:
        m = re.search(
            r"(?:整体提示词|overall prompt|提示词)[：:]\s*(.+?)(?:\n\n|\Z)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    def _extract_style_keywords(self, text: str) -> List[str]:
        m = re.search(r"(?:风格|style)[：:]\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
        if m:
            return [s.strip() for s in re.split(r"[,，、]", m.group(1)) if s.strip()]
        return []

    def _extract_category(self, text: str) -> str:
        m = re.search(r"(?:类型|category|分类)[：:]\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _extract_tags(self, text: str) -> List[str]:
        m = re.search(r"(?:标签|tags|关键词)[：:]\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
        if m:
            return [s.strip() for s in re.split(r"[,，、]", m.group(1)) if s.strip()]
        return []


# ==================== 单例 ====================

_parser: Optional[StoryboardParser] = None


def get_storyboard_parser() -> StoryboardParser:
    global _parser
    if _parser is None:
        _parser = StoryboardParser()
    return _parser
