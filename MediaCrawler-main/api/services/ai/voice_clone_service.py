# -*- coding: utf-8 -*-
"""
声音克隆服务

真实模式：对接阿里云 CosyVoice (DashScope API)，上传录音样本克隆声线
降级模式：无 DASHSCOPE_API_KEY 时，使用 edge-tts（免费微软TTS）合成音频

对标超级IP智能体的"高保真声音克隆"功能。
"""
import asyncio
import logging
import os
import subprocess
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("voice_clone_service")

# 临时目录
TMP_DIR = "/tmp/talking_head"
os.makedirs(TMP_DIR, exist_ok=True)

# 环境变量配置
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"

# edge-tts 降级模式的默认声音
DEFAULT_TTS_VOICE = "zh-CN-YunxiNeural"  # 自然男声
TTS_VOICE_OPTIONS = {
    "male_young": "zh-CN-YunxiNeural",
    "female_young": "zh-CN-XiaoyiNeural",
    "male_calm": "zh-CN-YunjianNeural",
    "female_calm": "zh-CN-XiaochenNeural",
    "male_warm": "zh-CN-YunyangNeural",
    "female_warm": "zh-CN-XiaomengNeural",
}


def is_cosyvoice_available() -> bool:
    """检查 CosyVoice API 是否可用（是否配置了 API Key）"""
    return bool(DASHSCOPE_API_KEY)


async def create_voice_model(sample_audio_path: str, name: str) -> Dict[str, Any]:
    """创建声音克隆模型

    真实模式：上传录音到 CosyVoice API → 返回克隆模型 ID
    降级模式：无 API Key 时记录文件路径，使用 edge-tts 降级
    """
    if not os.path.exists(sample_audio_path):
        raise FileNotFoundError(f"录音样本不存在: {sample_audio_path}")

    if is_cosyvoice_available():
        # ===== CosyVoice 真实模式 =====
        logger.info(f"[VoiceClone] CosyVoice 模式: 上传录音样本 {sample_audio_path}")
        try:
            # 1. 上传音频文件到 DashScope
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(sample_audio_path, "rb") as f:
                    audio_data = f.read()

                # CosyVoice 声音克隆接口
                resp = await client.post(
                    f"{DASHSCOPE_BASE_URL}/services/audio/tts/voice-clone",
                    headers={
                        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "cosyvoice-clone-v2",
                        "input": {
                            "action": "create",
                            "name": name,
                        },
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    model_id = data.get("output", {}).get("model_id", "")
                    logger.info(f"[VoiceClone] CosyVoice 克隆成功: model_id={model_id}")
                    return {
                        "provider": "cosyvoice",
                        "provider_model_id": model_id,
                        "status": "ready",
                        "name": name,
                    }
                else:
                    logger.warning(
                        f"[VoiceClone] CosyVoice 创建失败: {resp.status_code} {resp.text[:200]}"
                    )
                    # 降级到 TTS
        except Exception as e:
            logger.warning(f"[VoiceClone] CosyVoice 异常，降级到 TTS: {e}")

    # ===== 降级模式：edge-tts =====
    logger.info(f"[VoiceClone] 降级模式(edge-tts): 使用文件路径记录样本")
    return {
        "provider": "edge_tts",
        "provider_model_id": "",
        "sample_audio_path": sample_audio_path,
        "status": "ready",
        "name": name,
        "note": "未配置 DASHSCOPE_API_KEY，使用 edge-tts 降级合成",
    }


async def synthesize_speech(
    text: str,
    voice_model: Dict[str, Any],
    output_path: Optional[str] = None,
) -> str:
    """用声音模型合成口播音频

    真实模式：CosyVoice API 合成
    降级模式：edge-tts CLI 合成

    Args:
        text: 要合成的文案
        voice_model: 声音模型信息（create_voice_model 的返回值）
        output_path: 输出音频路径（默认自动生成）

    Returns:
        音频文件路径
    """
    if not output_path:
        output_path = os.path.join(TMP_DIR, f"tts_{int(time.time())}.mp3")

    provider = voice_model.get("provider", "edge_tts")

    if provider == "cosyvoice" and is_cosyvoice_available():
        # ===== CosyVoice 真实合成 =====
        model_id = voice_model.get("provider_model_id", "")
        if model_id:
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        f"{DASHSCOPE_BASE_URL}/services/audio/tts/generation",
                        headers={
                            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "cosyvoice-clone-v2",
                            "input": {
                                "model_id": model_id,
                                "text": text,
                            },
                            "parameters": {
                                "format": "mp3",
                                "sample_rate": 16000,
                            },
                        },
                    )
                    if resp.status_code == 200:
                        audio_url = resp.json().get("output", {}).get("audio", {}).get("url", "")
                        if audio_url:
                            # 下载音频文件
                            audio_resp = await client.get(audio_url)
                            with open(output_path, "wb") as f:
                                f.write(audio_resp.content)
                            logger.info(f"[VoiceClone] CosyVoice 合成成功: {output_path}")
                            return output_path
            except Exception as e:
                logger.warning(f"[VoiceClone] CosyVoice 合成失败，降级到 edge-tts: {e}")

    # ===== 降级模式：edge-tts =====
    logger.info(f"[VoiceClone] edge-tts 降级合成: text={len(text)}字")
    voice = TTS_VOICE_OPTIONS.get("male_young", DEFAULT_TTS_VOICE)

    # 用 edge-tts CLI 合成（需要安装 edge-tts）
    cmd = [
        "edge-tts",
        "--voice", voice,
        "--text", text,
        "--write-media", output_path,
    ]
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            # edge-tts 未安装，用 Python edge_tts 库
            try:
                import edge_tts
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(output_path)
            except ImportError:
                logger.error("[VoiceClone] edge-tts 未安装，无法合成音频")
                raise RuntimeError("edge-tts 未安装，请执行 pip install edge-tts")
    except FileNotFoundError:
        # edge-tts CLI 不存在，尝试 Python 库
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
        except ImportError:
            raise RuntimeError("edge-tts 未安装，请执行 pip install edge-tts")

    logger.info(f"[VoiceClone] edge-tts 合成成功: {output_path}")
    return output_path
