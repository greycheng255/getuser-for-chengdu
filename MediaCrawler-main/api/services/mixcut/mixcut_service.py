# -*- coding: utf-8 -*-
"""
AI 一键混剪服务

核心职责：
1. 接收用户上传的素材（视频片段5-8秒）
2. 调用 AI 生成文案（横幅文案 + 口播文案）
3. 使用 FFmpeg 自动混剪成片（随机顺序 + 转场 + 字幕 + 音乐）
4. 支持批量混剪

参考：知了系统的 AI 一键成片功能
"""
import asyncio
import logging
import os
import random
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认输出目录
MIXCUT_OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "mixcut_output")
os.makedirs(MIXCUT_OUTPUT_DIR, exist_ok=True)


class MixcutService:
    """AI 一键混剪服务（单例）"""

    _instance = None

    def __init__(self):
        self._tasks: Dict[str, Dict] = {}

    @classmethod
    def get_instance(cls) -> "MixcutService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def generate_script(
        self,
        industry: str,
        topic: str,
        style: str = "professional",
    ) -> Dict[str, Any]:
        """调用 AI 生成混剪文案（横幅文案 + 口播文案）"""
        try:
            from api.services.ai_agent_client import get_ai_agent_client
            client = get_ai_agent_client()

            prompt = f"""为{industry}行业生成一条短视频混剪文案。
主题：{topic}
风格：{style}

请按 JSON 格式返回：
{{
  "title": "视频标题（15字以内）",
  "banner_text": "横幅大字文案（10字以内，吸引眼球）",
  "voiceover": "口播文案（100-200字，口语化）",
  "subtitle_lines": ["字幕行1", "字幕行2", ...],
  "hashtags": ["#标签1", "#标签2", ...]
}}

只返回 JSON。"""

            response = await client.generate_text(prompt=prompt)
            if not response:
                return {"ok": False, "reason": "AI 生成文案失败"}

            import json
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].strip()

            result = json.loads(text)
            return {"ok": True, "script": result}
        except Exception as e:
            logger.warning(f"[Mixcut] AI 生成文案失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def create_mixcut(
        self,
        video_files: List[str],
        script: Dict[str, Any],
        music_file: Optional[str] = None,
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """使用 FFmpeg 混剪视频素材"""
        task_id = f"mix_{uuid.uuid4().hex[:10]}"
        output_dir = Path(MIXCUT_OUTPUT_DIR) / task_id
        output_dir.mkdir(parents=True, exist_ok=True)

        output_name = output_name or f"{task_id}.mp4"
        output_path = str(output_dir / output_name)

        try:
            # 1. 检查 FFmpeg 是否可用
            if not shutil.which("ffmpeg"):
                return {"ok": False, "reason": "FFmpeg 未安装，请先安装 ffmpeg"}

            # 2. 检查素材文件是否存在
            valid_files = [f for f in video_files if os.path.exists(f)]
            if not valid_files:
                return {"ok": False, "reason": "没有有效的视频素材文件"}

            # 3. 随机打乱素材顺序
            random.shuffle(valid_files)

            # 4. 生成 FFmpeg concat 列表
            concat_list = output_dir / "concat.txt"
            with open(concat_list, "w") as f:
                for vf in valid_files:
                    f.write(f"file '{os.path.abspath(vf)}'\n")

            # 5. 构建 FFmpeg 命令
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                output_path,
            ]

            # 如果有背景音乐
            if music_file and os.path.exists(music_file):
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_list),
                    "-i", music_file,
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-map", "0:v",
                    "-map", "1:a",
                    "-shortest",
                    "-movflags", "+faststart",
                    output_path,
                ]

            # 6. 执行 FFmpeg
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode != 0:
                return {"ok": False, "reason": f"FFmpeg 执行失败: {stderr.decode()[:200]}"}

            # 7. 获取输出文件信息
            file_size = os.path.getsize(output_path)
            duration = await self._get_video_duration(output_path)

            task_data = {
                "task_id": task_id,
                "output_path": output_path,
                "file_size": file_size,
                "duration": duration,
                "script": script,
                "source_files": valid_files,
                "created_at": int(time.time()),
                "status": "completed",
            }
            self._tasks[task_id] = task_data

            logger.info(f"[Mixcut] 混剪完成: {task_id} ({len(valid_files)}个素材, {duration:.1f}s)")
            return {"ok": True, "task_id": task_id, "output_path": output_path, **task_data}

        except asyncio.TimeoutError:
            return {"ok": False, "reason": "FFmpeg 执行超时"}
        except Exception as e:
            logger.warning(f"[Mixcut] 混剪失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def _get_video_duration(self, video_path: str) -> float:
        """获取视频时长"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return float(stdout.decode().strip())
        except Exception:
            return 0.0

    async def batch_mixcut(
        self,
        material_groups: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """批量混剪：多组素材并行混剪"""
        results = []
        for group in material_groups:
            result = await self.create_mixcut(
                video_files=group.get("video_files", []),
                script=group.get("script", {}),
                music_file=group.get("music_file"),
                output_name=group.get("output_name"),
            )
            results.append(result)

        success = sum(1 for r in results if r.get("ok"))
        return {
            "total": len(results),
            "success": success,
            "failed": len(results) - success,
            "results": results,
        }

    async def get_task(self, task_id: str) -> Optional[Dict]:
        """获取混剪任务状态"""
        return self._tasks.get(task_id)

    async def list_tasks(self, limit: int = 20) -> List[Dict]:
        """列出混剪任务"""
        tasks = sorted(
            self._tasks.values(),
            key=lambda t: t.get("created_at", 0),
            reverse=True,
        )
        return tasks[:limit]


def get_mixcut_service() -> MixcutService:
    return MixcutService.get_instance()
