# -*- coding: utf-8 -*-
"""
多 AI 平台服务（迁移自 GEO-main）.

对应 PRD 模块：多平台 AI 内容生成 / 故障转移.

适配点：
1. 凭据通过环境变量读取（DOUBAO_API_KEY / DEEPSEEK_API_KEY / KIMI_API_KEY /
   QIANWEN_API_KEY / WENXIN_API_KEY 等），原文件中百度平台改用 WENXIN_API_KEY
   命名（原 BAIDU_API_KEY），平台枚举同步更名为 WENXIN。
2. HTTP 客户端由同步 ``requests`` 改为异步 ``httpx.AsyncClient``，
   所有业务方法改为 ``async def``。
3. 日志使用 ``logging.getLogger(__name__)``，移除 ``print`` 与 ``__main__`` 测试块。
4. OpenAI 兼容平台（豆包 / DeepSeek / Kimi / ChatGPT / Gemini / Claude）统一走
   ``_call_openai_compatible``，保留各平台独立的配置与错误信息。
5. 提供单例 ``get_ai_platform_service()``。
6. 本模块为纯 HTTP 调用，无数据库依赖，故未引入 PostgreSQL 适配层。
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class AIPlatform(Enum):
    """支持的 AI 平台"""
    DOUBAO = "doubao"           # 豆包
    DEEPSEEK = "deepseek"       # DeepSeek
    KIMI = "kimi"               # Kimi
    QIANWEN = "qianwen"         # 通义千问
    WENXIN = "wenxin"           # 文心一言（原 BAIDU_AI）
    YUANBAO = "yuanbao"         # 元宝（腾讯混元）
    CHATGPT = "chatgpt"         # ChatGPT（海外）
    GEMINI = "gemini"           # Gemini（海外）
    CLAUDE = "claude"           # Claude（海外）


@dataclass
class PlatformConfig:
    """平台配置"""
    name: str
    api_base: str
    api_key: str
    model: str
    max_tokens: int = 4000
    temperature: float = 0.7
    is_available: bool = True


@dataclass
class GenerationResult:
    """生成结果"""
    platform: str
    content: str
    success: bool
    error: Optional[str] = None
    tokens_used: int = 0
    cost: float = 0.0
    response_time: float = 0.0
    timestamp: Optional[datetime] = None


class MultiAIPlatformService:
    """多 AI 平台服务"""

    def __init__(self) -> None:
        self.platforms: Dict[AIPlatform, PlatformConfig] = {}
        self._init_platforms()

    def _init_platforms(self) -> None:
        """初始化所有平台配置（凭据来自环境变量）。"""
        # 豆包
        self.platforms[AIPlatform.DOUBAO] = PlatformConfig(
            name="豆包",
            api_base=os.environ.get(
                "DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
            ),
            api_key=os.environ.get("DOUBAO_API_KEY", ""),
            model=os.environ.get("DOUBAO_MODEL", "doubao-pro-32k"),
        )

        # DeepSeek
        self.platforms[AIPlatform.DEEPSEEK] = PlatformConfig(
            name="DeepSeek",
            api_base=os.environ.get(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
            ),
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        )

        # Kimi
        self.platforms[AIPlatform.KIMI] = PlatformConfig(
            name="Kimi",
            api_base=os.environ.get(
                "KIMI_BASE_URL", "https://api.moonshot.cn/v1"
            ),
            api_key=os.environ.get("KIMI_API_KEY", ""),
            model=os.environ.get("KIMI_MODEL", "moonshot-v1-8k"),
        )

        # 通义千问
        self.platforms[AIPlatform.QIANWEN] = PlatformConfig(
            name="通义千问",
            api_base=os.environ.get(
                "QIANWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/api/v1",
            ),
            api_key=os.environ.get("QIANWEN_API_KEY", ""),
            model=os.environ.get("QIANWEN_MODEL", "qwen-turbo"),
        )

        # 文心一言（原百度 AI）
        self.platforms[AIPlatform.WENXIN] = PlatformConfig(
            name="文心一言",
            api_base=os.environ.get(
                "WENXIN_BASE_URL",
                "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat",
            ),
            api_key=os.environ.get("WENXIN_API_KEY", ""),
            model=os.environ.get("WENXIN_MODEL", "ernie-bot-4"),
        )

        # 元宝（腾讯混元）
        self.platforms[AIPlatform.YUANBAO] = PlatformConfig(
            name="元宝",
            api_base=os.environ.get(
                "YUANBAO_BASE_URL", "https://hunyuan.tencentcloudapi.com"
            ),
            api_key=os.environ.get("YUANBAO_API_KEY", ""),
            model=os.environ.get("YUANBAO_MODEL", "hunyuan-pro"),
        )

        # 海外平台（默认不可用，需配置凭据）
        self.platforms[AIPlatform.CHATGPT] = PlatformConfig(
            name="ChatGPT",
            api_base=os.environ.get(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
            is_available=False,
        )

        self.platforms[AIPlatform.GEMINI] = PlatformConfig(
            name="Gemini",
            api_base=os.environ.get(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1",
            ),
            api_key=os.environ.get("GEMINI_API_KEY", ""),
            model=os.environ.get("GEMINI_MODEL", "gemini-pro"),
            is_available=False,
        )

        self.platforms[AIPlatform.CLAUDE] = PlatformConfig(
            name="Claude",
            api_base=os.environ.get(
                "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"
            ),
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            model=os.environ.get(
                "ANTHROPIC_MODEL", "claude-3-opus-20240229"
            ),
            is_available=False,
        )

    def get_available_platforms(self) -> List[Dict[str, Any]]:
        """获取所有平台列表（含可用状态）。"""
        platforms: List[Dict[str, Any]] = []
        for platform, config in self.platforms.items():
            platforms.append(
                {
                    "id": platform.value,
                    "name": config.name,
                    "model": config.model,
                    "available": config.is_available and bool(config.api_key),
                    "max_tokens": config.max_tokens,
                }
            )
        return platforms

    async def generate_with_platform(
        self,
        platform: AIPlatform,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> GenerationResult:
        """使用指定平台生成内容。

        Args:
            platform: 目标平台
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            生成结果
        """
        start_time = time.time()
        config = self.platforms.get(platform)
        if not config:
            return GenerationResult(
                platform=platform.value,
                content="",
                success=False,
                error=f"平台 {platform.value} 未配置",
            )

        if not config.api_key:
            return GenerationResult(
                platform=platform.value,
                content="",
                success=False,
                error=f"平台 {config.name} 未配置 API 密钥",
            )

        try:
            if platform == AIPlatform.QIANWEN:
                content = await self._call_qianwen(
                    config, prompt, system_prompt, temperature, max_tokens
                )
            elif platform == AIPlatform.WENXIN:
                content = await self._call_wenxin(
                    config, prompt, system_prompt, temperature, max_tokens
                )
            elif platform == AIPlatform.YUANBAO:
                content = await self._call_yuanbao(
                    config, prompt, system_prompt, temperature, max_tokens
                )
            else:
                # 豆包 / DeepSeek / Kimi / ChatGPT / Gemini / Claude 均走 OpenAI 兼容协议
                content = await self._call_openai_compatible(
                    config, prompt, system_prompt, temperature, max_tokens
                )

            return GenerationResult(
                platform=platform.value,
                content=content,
                success=True,
                response_time=time.time() - start_time,
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.exception("平台 %s 生成失败", platform.value)
            return GenerationResult(
                platform=platform.value,
                content="",
                success=False,
                error=str(e),
                response_time=time.time() - start_time,
            )

    async def _call_openai_compatible(
        self,
        config: PlatformConfig,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        """调用 OpenAI 兼容格式的 API（豆包/DeepSeek/Kimi/ChatGPT 等）。"""
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        data = {
            "model": config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else config.max_tokens,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{config.api_base}/chat/completions",
                headers=headers,
                json=data,
            )
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        raise Exception(f"{config.name} API 错误: {response.status_code} - {response.text}")

    async def _call_qianwen(
        self,
        config: PlatformConfig,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        """调用通义千问 API。"""
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        data = {
            "model": config.model,
            "input": {"messages": messages},
            "parameters": {
                "temperature": temperature if temperature is not None else config.temperature,
                "max_tokens": max_tokens if max_tokens is not None else config.max_tokens,
            },
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{config.api_base}/services/aigc/text-generation/generation",
                headers=headers,
                json=data,
            )
        if response.status_code == 200:
            result = response.json()
            return result["output"]["text"]
        raise Exception(f"通义千问 API 错误: {response.status_code} - {response.text}")

    async def _call_wenxin(
        self,
        config: PlatformConfig,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        """调用文心一言 API。"""
        access_token = self._get_wenxin_access_token(config.api_key)
        url = f"{config.api_base}/completions_pro?access_token={access_token}"
        headers = {"Content-Type": "application/json"}
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        data = {
            "messages": messages,
            "temperature": temperature if temperature is not None else config.temperature,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()
            return result["result"]
        raise Exception(f"文心一言 API 错误: {response.status_code} - {response.text}")

    def _get_wenxin_access_token(self, api_key: str) -> str:
        """获取文心一言 access token（简化处理，实际应缓存 token）。"""
        return api_key

    async def _call_yuanbao(
        self,
        config: PlatformConfig,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        """调用元宝（腾讯混元）API。"""
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        data = {
            "Model": config.model,
            "Messages": messages,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{config.api_base}/chat/completions",
                headers=headers,
                json=data,
            )
        if response.status_code == 200:
            result = response.json()
            return result["Choices"][0]["Message"]["Content"]
        raise Exception(f"元宝 API 错误: {response.status_code} - {response.text}")

    async def generate_with_fallback(
        self,
        prompt: str,
        platforms: Optional[List[AIPlatform]] = None,
        system_prompt: Optional[str] = None,
    ) -> GenerationResult:
        """带故障转移的多平台生成。

        Args:
            prompt: 用户提示词
            platforms: 按优先级排序的平台列表
            system_prompt: 系统提示词

        Returns:
            第一个成功平台的生成结果，或全部失败时的汇总错误
        """
        if platforms is None:
            # 默认优先级：豆包 > DeepSeek > Kimi > 通义千问
            platforms = [
                AIPlatform.DOUBAO,
                AIPlatform.DEEPSEEK,
                AIPlatform.KIMI,
                AIPlatform.QIANWEN,
            ]

        last_error: Optional[str] = None
        for platform in platforms:
            result = await self.generate_with_platform(platform, prompt, system_prompt)
            if result.success:
                return result
            last_error = result.error

        return GenerationResult(
            platform="all",
            content="",
            success=False,
            error=f"所有平台均失败，最后一个错误: {last_error}",
        )

    async def batch_generate(
        self,
        prompts: List[str],
        platform: AIPlatform = AIPlatform.DOUBAO,
        system_prompt: Optional[str] = None,
    ) -> List[GenerationResult]:
        """批量生成内容。

        Args:
            prompts: 提示词列表
            platform: 使用的平台
            system_prompt: 系统提示词

        Returns:
            每个提示词对应的生成结果列表
        """
        results: List[GenerationResult] = []
        for prompt in prompts:
            result = await self.generate_with_platform(platform, prompt, system_prompt)
            results.append(result)
        return results


_ai_platform_service: Optional[MultiAIPlatformService] = None


def get_ai_platform_service() -> MultiAIPlatformService:
    """获取 MultiAIPlatformService 单例。"""
    global _ai_platform_service
    if _ai_platform_service is None:
        _ai_platform_service = MultiAIPlatformService()
    return _ai_platform_service
