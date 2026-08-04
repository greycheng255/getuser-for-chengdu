# -*- coding: utf-8 -*-
"""
视频后处理（FFmpeg）

对应 PRD 5.2 营销信息植入 - 视频后处理：
在生成的视频中植入水印 / 贴片 / 片尾。

依赖：系统 ffmpeg（项目已使用 ffmpeg 提取关键帧，确认可用）。
"""

import asyncio
import logging
import os
import shutil
from typing import List, Optional

logger = logging.getLogger(__name__)


# 水印位置 → ffmpeg overlay 滤镜参数
POSITION_MAP = {
    "top-left": "10:10",
    "top-right": "main_w-overlay_w-10:10",
    "bottom-left": "10:main_h-overlay_h-10",
    "bottom-right": "main_w-overlay_w-10:main_h-overlay_h-10",
    "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
}


class VideoProcessor:
    """视频后处理（FFmpeg）"""

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg = shutil.which(ffmpeg_path) or ffmpeg_path

    async def add_watermark(
        self,
        video_path: str,
        logo_path: str,
        output_path: str,
        position: str = "bottom-right",
        scale: str = "iw*0.15",
    ) -> str:
        """给视频添加图片水印

        Args:
            video_path: 源视频路径
            logo_path: 水印图片路径
            output_path: 输出路径
            position: 水印位置
            scale: 水印缩放（默认为视频宽度的 15%）
        """
        pos = POSITION_MAP.get(position, POSITION_MAP["bottom-right"])
        filter_complex = (
            f"[1:v]scale={scale}:-1[wm];"
            f"[0:v][wm]overlay={pos}"
        )
        cmd = [
            self.ffmpeg, "-y", "-i", video_path, "-i", logo_path,
            "-filter_complex", filter_complex,
            "-c:a", "copy",
            output_path,
        ]
        return await self._run_ffmpeg(cmd, output_path)

    async def add_text_watermark(
        self,
        video_path: str,
        text: str,
        output_path: str,
        position: str = "bottom-right",
        font_size: int = 24,
        font_color: str = "white",
    ) -> str:
        """给视频添加文字水印"""
        pos = POSITION_MAP.get(position, POSITION_MAP["bottom-right"])
        # drawtext 滤镜
        escaped_text = text.replace(":", "\\:").replace("'", "\\'")
        filter_complex = (
            f"drawtext=text='{escaped_text}':fontcolor={font_color}:"
            f"fontsize={font_size}:x={pos.split(':')[0]}:y={pos.split(':')[1]}"
        )
        cmd = [
            self.ffmpeg, "-y", "-i", video_path,
            "-vf", filter_complex,
            "-c:a", "copy",
            output_path,
        ]
        return await self._run_ffmpeg(cmd, output_path)

    async def concat_outro(
        self,
        video_path: str,
        outro_path: str,
        output_path: str,
    ) -> str:
        """拼接片尾视频

        Args:
            video_path: 主视频
            outro_path: 片尾视频
            output_path: 输出
        """
        # 创建 concat 列表文件
        list_file = output_path + ".list.txt"
        with open(list_file, "w") as f:
            f.write(f"file '{os.path.abspath(video_path)}'\n")
            f.write(f"file '{os.path.abspath(outro_path)}'\n")
        try:
            cmd = [
                self.ffmpeg, "-y", "-f", "concat", "-safe", "0",
                "-i", list_file, "-c", "copy", output_path,
            ]
            return await self._run_ffmpeg(cmd, output_path)
        finally:
            try:
                os.remove(list_file)
            except OSError:
                pass

    async def add_qr_code(
        self,
        video_path: str,
        qr_image_path: str,
        output_path: str,
        position: str = "bottom-right",
        duration: float = 5.0,
    ) -> str:
        """在视频末尾添加二维码贴片（最后 N 秒显示）

        Args:
            duration: 二维码显示时长（秒）
        """
        pos = POSITION_MAP.get(position, POSITION_MAP["bottom-right"])
        total_duration = await self._get_duration(video_path)
        start_time = max(0, total_duration - duration)
        filter_complex = (
            f"[1:v]scale=iw*0.2:-1[qr];"
            f"[0:v][qr]overlay={pos}:enable='gte(t,{start_time})'"
        )
        cmd = [
            self.ffmpeg, "-y", "-i", video_path, "-i", qr_image_path,
            "-filter_complex", filter_complex,
            "-c:a", "copy",
            output_path,
        ]
        return await self._run_ffmpeg(cmd, output_path)

    async def _get_duration(self, video_path: str) -> float:
        """获取视频时长（秒）"""
        cmd = [
            self.ffmpeg.replace("ffmpeg", "ffprobe") if "ffmpeg" in self.ffmpeg else "ffprobe",
            "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            return float(out.decode().strip() or 0)
        except Exception:
            return 0.0

    async def _run_ffmpeg(self, cmd: List[str], output_path: str) -> str:
        """执行 ffmpeg 命令"""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        logger.info(f"[VideoProcessor] 执行: {' '.join(cmd[:6])}...")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = stderr.decode()[-500:]
                logger.error(f"[VideoProcessor] ffmpeg 失败: {err}")
                raise RuntimeError(f"ffmpeg 处理失败: {err}")
            logger.info(f"[VideoProcessor] 处理完成: {output_path}")
            return output_path
        except FileNotFoundError:
            logger.error("[VideoProcessor] ffmpeg 未安装")
            raise RuntimeError("ffmpeg 未安装，无法进行视频后处理")
