# -*- coding: utf-8 -*-
"""
视频尺寸/时长适配器

阶段二 P2-2：补齐 PRD 视频发布规格自动适配。

背景：
multi_publisher.PublishTask.video_path 原先直接透传给各平台 Publisher，
未按平台裁切/缩放（如抖音 9:16 vs B站 16:9）。本模块负责在发布前根据
PLATFORM_METADATA 的 video_aspect_ratio / max_video_duration 用 ffmpeg
做转码，输出加平台后缀的新文件，避免覆盖原视频。

设计：
1. 读取 PLATFORM_METADATA[platform].video_aspect_ratio（如 "9:16" / "16:9" / "1:1"）
   和 max_video_duration（秒）
2. 用 ffprobe 检测原视频的宽高比和时长
3. 不符则用 ffmpeg 转码：
   - 宽高比不符：先 crop 到目标比例（保持中心），再 scale 到标准分辨率
   - 时长超限：-t 截断
4. 输出文件名加平台后缀（如 video_douyin.mp4），避免覆盖原文件
5. 失败时 log warning 并返回原 video_path（降级，不阻断发布）

依赖：系统已安装 ffmpeg / ffprobe（项目环境已具备）。
"""

import asyncio
import json
import logging
import os
from typing import Dict, List, Optional, Tuple

from .platform_configs import get_platform_meta

logger = logging.getLogger(__name__)


class VideoAdapter:
    """视频尺寸/时长适配器

    所有方法均为 classmethod / async，无实例状态，便于在 multi_publisher 中直接调用。
    """

    FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
    FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")

    # 各宽高比对应的标准输出分辨率（短边 1080）
    _STANDARD_RES: Dict[str, Tuple[int, int]] = {
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "1:1": (1080, 1080),
        "4:3": (1440, 1080),
        "3:4": (1080, 1440),
    }

    # 宽高比容差（2%），小于此差异视为已符合，避免不必要的转码
    _RATIO_TOLERANCE = 0.02

    # ============ 对外入口 ============

    @classmethod
    async def adapt_video(cls, video_path: str, platform: str) -> str:
        """根据平台元数据适配视频尺寸/时长

        Args:
            video_path: 原视频文件路径
            platform: 目标平台名（如 douyin / bilibili / xiaohongshu）

        Returns:
            适配后的视频路径；失败或无需转码时返回原 video_path（降级，不阻断发布）
        """
        if not video_path or not os.path.exists(video_path):
            return video_path

        meta = get_platform_meta(platform)
        if not meta:
            return video_path

        target_ratio = meta.video_aspect_ratio
        max_duration = meta.max_video_duration

        # 平台未声明视频规格，跳过
        if not target_ratio and not max_duration:
            return video_path

        try:
            info = await cls._probe_video(video_path)
        except FileNotFoundError as e:
            logger.warning(
                f"[VideoAdapter] ffmpeg/ffprobe 未安装，跳过视频适配: {e}"
            )
            return video_path
        except Exception as e:
            logger.warning(
                f"[VideoAdapter][{platform}] 探测视频失败，降级使用原视频: {e}"
            )
            return video_path

        need_transcode = False
        vf_filters: List[str] = []
        truncate_duration = False

        # 1. 宽高比检测
        if target_ratio and info["width"] and info["height"]:
            cur_ratio = info["width"] / info["height"]
            target_w, target_h = cls._parse_ratio(target_ratio)
            target_value = target_w / target_h
            if abs(cur_ratio - target_value) > cls._RATIO_TOLERANCE:
                need_transcode = True
                vf = cls._build_ratio_filter(
                    info["width"], info["height"], target_ratio
                )
                if vf:
                    vf_filters.append(vf)
                logger.info(
                    f"[VideoAdapter][{platform}] 宽高比不符 "
                    f"{info['width']}x{info['height']}({cur_ratio:.3f}) -> {target_ratio}，需转码"
                )

        # 2. 时长检测
        duration = info.get("duration", 0) or 0
        if max_duration and duration > max_duration:
            need_transcode = True
            truncate_duration = True
            logger.info(
                f"[VideoAdapter][{platform}] 时长超限 "
                f"{duration:.1f}s -> {max_duration}s，需截断"
            )

        if not need_transcode:
            logger.debug(f"[VideoAdapter][{platform}] 视频规格已符合，跳过转码")
            return video_path

        # 3. 输出路径：{base}_{platform}.mp4（避免覆盖原文件）
        base, _ = os.path.splitext(video_path)
        out_path = f"{base}_{platform}.mp4"

        # 4. 构建 ffmpeg 命令
        cmd = [cls.FFMPEG_BIN, "-y", "-loglevel", "error", "-i", video_path]
        if vf_filters:
            cmd.extend(["-vf", ",".join(vf_filters)])
        if truncate_duration:
            cmd.extend(["-t", str(max_duration)])
        cmd.extend(
            [
                "-c:v", "libx264",
                "-preset", "fast",
                "-c:a", "aac",
                "-movflags", "+faststart",
                out_path,
            ]
        )

        # 5. 异步执行（避免阻塞 event loop）
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                logger.warning(
                    f"[VideoAdapter][{platform}] 转码失败 returncode={process.returncode} "
                    f"stderr={stderr.decode(errors='ignore')[-500:]}"
                )
                return video_path
        except FileNotFoundError as e:
            logger.warning(
                f"[VideoAdapter] ffmpeg 未安装，跳过视频适配: {e}"
            )
            return video_path
        except Exception as e:
            logger.warning(
                f"[VideoAdapter][{platform}] 转码异常，降级使用原视频: {e}"
            )
            return video_path

        if not os.path.exists(out_path):
            logger.warning(
                f"[VideoAdapter][{platform}] 转码后输出文件不存在: {out_path}"
            )
            return video_path

        logger.info(
            f"[VideoAdapter][{platform}] 转码成功: {video_path} -> {out_path}"
        )
        return out_path

    # ============ 工具方法 ============

    @staticmethod
    def _parse_ratio(ratio: str) -> Tuple[int, int]:
        """解析 "9:16" -> (9, 16)"""
        parts = ratio.split(":")
        if len(parts) != 2:
            return (16, 9)
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            return (16, 9)

    @classmethod
    def _build_ratio_filter(
        cls, src_w: int, src_h: int, target_ratio: str
    ) -> Optional[str]:
        """构建宽高比适配 filter

        策略：保持原视频中心 crop 到目标比例（裁掉多余边缘），再 scale 到标准分辨率。
        相比 pad 黑边方案，裁切不会出现黑边，更适合短视频平台。

        例：原视频 1920x1080(16:9) -> 目标 9:16
            crop=608:1080 -> scale=1080:1920
        """
        target_w, target_h = cls._parse_ratio(target_ratio)
        src_ratio = src_w / src_h
        target_value = target_w / target_h

        if src_ratio > target_value:
            # 源更宽：横向裁切，保持高度
            crop_w = int(src_h * target_value)
            crop_w = crop_w - (crop_w % 2)  # 确保偶数（H.264 要求）
            crop_filter = f"crop={crop_w}:{src_h}"
        else:
            # 源更高：纵向裁切，保持宽度
            crop_h = int(src_w / target_value)
            crop_h = crop_h - (crop_h % 2)
            crop_filter = f"crop={src_w}:{crop_h}"

        # scale 到标准分辨率
        out_w, out_h = cls._STANDARD_RES.get(
            target_ratio, (1080, int(1080 * target_h / target_w))
        )
        return f"{crop_filter},scale={out_w}:{out_h}"

    @classmethod
    async def _probe_video(cls, video_path: str) -> Dict:
        """用 ffprobe 探测视频信息

        Returns:
            {"width": int|None, "height": int|None, "duration": float}
        """
        cmd = [
            cls.FFPROBE_BIN,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration:format=duration",
            "-of", "json",
            video_path,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return {"width": None, "height": None, "duration": 0.0}
        try:
            data = json.loads(stdout.decode() or "{}")
        except json.JSONDecodeError:
            return {"width": None, "height": None, "duration": 0.0}

        streams = data.get("streams", [])
        width = height = None
        if streams:
            s = streams[0]
            try:
                width = int(s.get("width", 0)) or None
                height = int(s.get("height", 0)) or None
            except (TypeError, ValueError):
                pass

        # 优先取 format.duration，兜底取 stream.duration
        duration = 0.0
        fmt = data.get("format", {})
        if fmt:
            try:
                duration = float(fmt.get("duration", 0) or 0)
            except (TypeError, ValueError):
                duration = 0.0
        if not duration and streams:
            try:
                duration = float(streams[0].get("duration", 0) or 0)
            except (TypeError, ValueError):
                duration = 0.0

        return {"width": width, "height": height, "duration": duration}


# 模块级便捷函数
async def adapt_video_for_platform(video_path: str, platform: str) -> str:
    """便捷函数：按平台适配视频尺寸/时长

    等价于 VideoAdapter.adapt_video(video_path, platform)。
    """
    return await VideoAdapter.adapt_video(video_path, platform)
