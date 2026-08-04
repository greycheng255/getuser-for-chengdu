# -*- coding: utf-8 -*-
"""
视频生成参数配置中心

阶段一 P0 任务 1.2：补齐 PRD 5.2 视频参数可配置缺口。

提供：
1. VideoGenConfig 数据类：时长/分辨率/画面风格/配音音色/字幕样式/BGM 情绪
2. VideoGenerationConfigService：CRUD + 用户隔离 + 默认预设
3. 持久化到 video_generation_configs 表（PostgreSQL 异步）
4. 通过环境变量提供默认值，可被用户配置覆盖

对应 PRD 5.2.2 内容参数（时长 15-60s、720P/1080P、画面风格、配音音色、字幕样式）。
"""

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============ 默认值（环境变量覆盖） ============
DEFAULT_DURATION = int(os.environ.get("VIDEO_DEFAULT_DURATION", "30"))
DEFAULT_RESOLUTION = os.environ.get("VIDEO_DEFAULT_RESOLUTION", "720p")
DEFAULT_ASPECT_RATIO = os.environ.get("VIDEO_DEFAULT_ASPECT_RATIO", "9:16")
DEFAULT_VISUAL_STYLE = os.environ.get("VIDEO_DEFAULT_VISUAL_STYLE", "modern")
DEFAULT_VOICE_TIMBRE = os.environ.get("VIDEO_DEFAULT_VOICE_TIMBRE", "female_warm")
DEFAULT_SUBTITLE_STYLE = os.environ.get("VIDEO_DEFAULT_SUBTITLE_STYLE", "white_bold_black_outline")
DEFAULT_BGM_MOOD = os.environ.get("VIDEO_DEFAULT_BGM_MOOD", "upbeat")


# ============ 合法取值范围 ============
VALID_RESOLUTIONS = {"720p", "1080p", "480p"}
VALID_ASPECT_RATIOS = {"9:16", "16:9", "1:1", "4:3"}
VALID_VISUAL_STYLES = {"modern", "minimal", "cinematic", "cartoon", "vlog", "documentary"}
VALID_VOICE_TIMBRES = {
    "female_warm", "female_clear", "female_young",
    "male_deep", "male_warm", "male_young",
    "neutral", "child",
}
VALID_SUBTITLE_STYLES = {
    "white_bold_black_outline", "white_thin_black_outline",
    "yellow_bold_black_outline", "karaoke",
    "bottom_bar_white", "top_bar_white",
}
VALID_BGM_MOODS = {"upbeat", "calm", "inspiring", "tense", "sad", "funny", "epic"}


@dataclass
class VideoGenConfig:
    """视频生成参数配置

    对应 PRD 5.2.2：
    - 时长 15s-60s
    - 分辨率 720P/1080P
    - 画面风格
    - 配音音色
    - 字幕样式
    """
    config_id: str = ""
    name: str = ""                       # 配置名称（用户自定义）
    duration_seconds: int = DEFAULT_DURATION       # 时长（秒），15-60
    resolution: str = DEFAULT_RESOLUTION           # 720p/1080p/480p
    aspect_ratio: str = DEFAULT_ASPECT_RATIO       # 9:16/16:9/1:1/4:3
    visual_style: str = DEFAULT_VISUAL_STYLE       # modern/minimal/cinematic/cartoon/vlog/documentary
    voice_timbre: str = DEFAULT_VOICE_TIMBRE       # female_warm/male_deep/neutral/young/...
    subtitle_style: str = DEFAULT_SUBTITLE_STYLE   # white_bold_black_outline/...
    bgm_mood: str = DEFAULT_BGM_MOOD               # upbeat/calm/inspiring/tense/...
    enable_subtitle: bool = True
    enable_voiceover: bool = True
    enable_bgm: bool = True
    owner_user_id: Optional[int] = None
    is_preset: bool = False              # 是否系统预设
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        """校验配置合法性，返回错误信息列表（空列表表示通过）"""
        errors: List[str] = []
        if not (15 <= self.duration_seconds <= 60):
            errors.append(f"时长必须在 15-60 秒之间，当前: {self.duration_seconds}")
        if self.resolution not in VALID_RESOLUTIONS:
            errors.append(f"分辨率不合法: {self.resolution}，合法值: {VALID_RESOLUTIONS}")
        if self.aspect_ratio not in VALID_ASPECT_RATIOS:
            errors.append(f"宽高比不合法: {self.aspect_ratio}，合法值: {VALID_ASPECT_RATIOS}")
        if self.visual_style not in VALID_VISUAL_STYLES:
            errors.append(f"画面风格不合法: {self.visual_style}，合法值: {VALID_VISUAL_STYLES}")
        if self.voice_timbre not in VALID_VOICE_TIMBRES:
            errors.append(f"配音音色不合法: {self.voice_timbre}，合法值: {VALID_VOICE_TIMBRES}")
        if self.subtitle_style not in VALID_SUBTITLE_STYLES:
            errors.append(f"字幕样式不合法: {self.subtitle_style}，合法值: {VALID_SUBTITLE_STYLES}")
        if self.bgm_mood not in VALID_BGM_MOODS:
            errors.append(f"BGM 情绪不合法: {self.bgm_mood}，合法值: {VALID_BGM_MOODS}")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class VideoGenerationConfigService:
    """视频生成配置服务（异步 PostgreSQL）"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    def __init__(self):
        self._presets_loaded = False

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if VideoGenerationConfigService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS video_generation_configs ("
                        "  config_id VARCHAR(64) PRIMARY KEY,"
                        "  name VARCHAR(128) NOT NULL,"
                        "  duration_seconds INTEGER DEFAULT 30,"
                        "  resolution VARCHAR(16) DEFAULT '720p',"
                        "  aspect_ratio VARCHAR(16) DEFAULT '9:16',"
                        "  visual_style VARCHAR(32) DEFAULT 'modern',"
                        "  voice_timbre VARCHAR(32) DEFAULT 'female_warm',"
                        "  subtitle_style VARCHAR(64) DEFAULT 'white_bold_black_outline',"
                        "  bgm_mood VARCHAR(32) DEFAULT 'upbeat',"
                        "  enable_subtitle BOOLEAN DEFAULT TRUE,"
                        "  enable_voiceover BOOLEAN DEFAULT TRUE,"
                        "  enable_bgm BOOLEAN DEFAULT TRUE,"
                        "  owner_user_id INTEGER,"
                        "  is_preset BOOLEAN DEFAULT FALSE,"
                        "  extra TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  updated_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
                # 查询索引：list_configs 按用户/预设过滤 + updated_at 排序
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_videocfg_owner_updated "
                        "ON video_generation_configs(owner_user_id, updated_at DESC)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_videocfg_preset_updated "
                        "ON video_generation_configs(is_preset, updated_at DESC)"
                    )
                )
            if not self._presets_loaded:
                await self._ensure_presets()
                self._presets_loaded = True
            VideoGenerationConfigService._ensured = True
        except Exception as e:
            logger.warning(f"[VideoGenConfig] ensure_table failed: {e}")

    async def _ensure_presets(self) -> None:
        """初始化系统预设配置"""
        presets = [
            VideoGenConfig(
                config_id="preset_short_vertical",
                name="短视频竖屏（15s 抖音/快手）",
                duration_seconds=15,
                resolution="720p",
                aspect_ratio="9:16",
                visual_style="modern",
                voice_timbre="female_warm",
                subtitle_style="white_bold_black_outline",
                bgm_mood="upbeat",
                is_preset=True,
            ),
            VideoGenConfig(
                config_id="preset_standard_vertical",
                name="标准竖屏（30s 主流）",
                duration_seconds=30,
                resolution="1080p",
                aspect_ratio="9:16",
                visual_style="modern",
                voice_timbre="female_warm",
                subtitle_style="white_bold_black_outline",
                bgm_mood="upbeat",
                is_preset=True,
            ),
            VideoGenConfig(
                config_id="preset_horizontal",
                name="横屏（45s B站/YouTube）",
                duration_seconds=45,
                resolution="1080p",
                aspect_ratio="16:9",
                visual_style="cinematic",
                voice_timbre="male_deep",
                subtitle_style="bottom_bar_white",
                bgm_mood="inspiring",
                is_preset=True,
            ),
            VideoGenConfig(
                config_id="preset_square",
                name="方形（30s 小红书/Instagram）",
                duration_seconds=30,
                resolution="1080p",
                aspect_ratio="1:1",
                visual_style="minimal",
                voice_timbre="female_clear",
                subtitle_style="yellow_bold_black_outline",
                bgm_mood="calm",
                is_preset=True,
            ),
        ]
        for preset in presets:
            await self.save_config(preset)

    async def save_config(self, cfg: VideoGenConfig) -> bool:
        """保存（新增或更新）"""
        if not cfg.config_id:
            cfg.config_id = f"vcfg_{uuid.uuid4().hex[:12]}"
        now_dt = datetime.now()
        now_str = now_dt.isoformat()
        if not cfg.created_at:
            cfg.created_at = now_str
        cfg.updated_at = now_str

        errors = cfg.validate()
        if errors:
            logger.warning(f"[VideoGenConfig] 校验失败: {errors}")
            return False

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            # 数据库需要 datetime 对象，而非字符串
            created_dt = self._parse_dt(cfg.created_at) or now_dt
            updated_dt = now_dt
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO video_generation_configs "
                        "(config_id, name, duration_seconds, resolution, aspect_ratio, "
                        " visual_style, voice_timbre, subtitle_style, bgm_mood, "
                        " enable_subtitle, enable_voiceover, enable_bgm, "
                        " owner_user_id, is_preset, extra, created_at, updated_at) "
                        "VALUES (:cid, :nm, :dur, :res, :ar, :vs, :vt, :ss, :bm, "
                        "        :es, :ev, :eb, :ouid, :ip, :ex, :ca, :ua) "
                        "ON CONFLICT (config_id) DO UPDATE SET "
                        " name=EXCLUDED.name, duration_seconds=EXCLUDED.duration_seconds, "
                        " resolution=EXCLUDED.resolution, aspect_ratio=EXCLUDED.aspect_ratio, "
                        " visual_style=EXCLUDED.visual_style, voice_timbre=EXCLUDED.voice_timbre, "
                        " subtitle_style=EXCLUDED.subtitle_style, bgm_mood=EXCLUDED.bgm_mood, "
                        " enable_subtitle=EXCLUDED.enable_subtitle, "
                        " enable_voiceover=EXCLUDED.enable_voiceover, "
                        " enable_bgm=EXCLUDED.enable_bgm, "
                        " owner_user_id=EXCLUDED.owner_user_id, "
                        " extra=EXCLUDED.extra, updated_at=EXCLUDED.updated_at"
                    ),
                    {
                        "cid": cfg.config_id,
                        "nm": cfg.name,
                        "dur": cfg.duration_seconds,
                        "res": cfg.resolution,
                        "ar": cfg.aspect_ratio,
                        "vs": cfg.visual_style,
                        "vt": cfg.voice_timbre,
                        "ss": cfg.subtitle_style,
                        "bm": cfg.bgm_mood,
                        "es": cfg.enable_subtitle,
                        "ev": cfg.enable_voiceover,
                        "eb": cfg.enable_bgm,
                        "ouid": cfg.owner_user_id,
                        "ip": cfg.is_preset,
                        "ex": json.dumps(cfg.extra, ensure_ascii=False),
                        "ca": created_dt,
                        "ua": updated_dt,
                    },
                )
            return True
        except Exception as e:
            logger.warning(f"[VideoGenConfig] save_config failed: {e}")
            return False

    @staticmethod
    def _parse_dt(value):
        """将字符串或 datetime 转换为 datetime 对象"""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            # 兼容带/不带毫秒的 ISO 格式
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    async def list_configs(
        self, owner_user_id: Optional[int] = None, include_presets: bool = True
    ) -> List[Dict[str, Any]]:
        """列出配置（含预设）"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                if owner_user_id is not None:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM video_generation_configs "
                            "WHERE (owner_user_id = :ouid OR is_preset = TRUE) "
                            "ORDER BY is_preset DESC, updated_at DESC"
                        ),
                        {"ouid": owner_user_id},
                    )
                elif include_presets:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM video_generation_configs "
                            "ORDER BY is_preset DESC, updated_at DESC"
                        )
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM video_generation_configs "
                            "WHERE is_preset = FALSE ORDER BY updated_at DESC"
                        )
                    )
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[VideoGenConfig] list_configs failed: {e}")
            return []

    async def get_config(self, config_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM video_generation_configs WHERE config_id = :cid"),
                    {"cid": config_id},
                )
                row = rows.fetchone()
                return self._row_to_dict(row) if row else None
        except Exception as e:
            logger.warning(f"[VideoGenConfig] get_config failed: {e}")
            return None

    async def delete_config(self, config_id: str) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                # 预设不可删除
                await conn.execute(
                    sql_text(
                        "DELETE FROM video_generation_configs "
                        "WHERE config_id = :cid AND is_preset = FALSE"
                    ),
                    {"cid": config_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[VideoGenConfig] delete_config failed: {e}")
            return False

    def _row_to_dict(self, row) -> Dict[str, Any]:
        try:
            extra_raw = row[14] if len(row) >= 15 else None
            extra = json.loads(extra_raw) if extra_raw else {}
        except Exception:
            extra = {}
        return {
            "config_id": row[0],
            "name": row[1],
            "duration_seconds": row[2],
            "resolution": row[3],
            "aspect_ratio": row[4],
            "visual_style": row[5],
            "voice_timbre": row[6],
            "subtitle_style": row[7],
            "bgm_mood": row[8],
            "enable_subtitle": row[9],
            "enable_voiceover": row[10],
            "enable_bgm": row[11],
            "owner_user_id": row[12],
            "is_preset": row[13],
            "extra": extra,
            "created_at": str(row[15]) if row[15] else None,
            "updated_at": str(row[16]) if row[16] else None,
        }

    def get_default_config(self) -> VideoGenConfig:
        """返回默认配置（不入库）"""
        return VideoGenConfig()


# ============ 单例 ============
_service: Optional[VideoGenerationConfigService] = None


def get_video_gen_config_service() -> VideoGenerationConfigService:
    global _service
    if _service is None:
        _service = VideoGenerationConfigService()
    return _service


# 别名：保持长名一致（用于 ai/__init__.py 导出）
def get_video_generation_config_service() -> VideoGenerationConfigService:
    return get_video_gen_config_service()
