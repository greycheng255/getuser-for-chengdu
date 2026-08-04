"""
多AI平台服务
支持百度AI、元宝、豆包、DeepSeek、Kimi、通义千问等国内主流AI平台
"""

import os
import requests
import json
from typing import Dict, List, Optional, Generator
from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class AIPlatform(Enum):
    """支持的AI平台"""
    DOUBAO = "doubao"           # 豆包
    DEEPSEEK = "deepseek"       # DeepSeek
    KIMI = "kimi"               # Kimi
    QIANWEN = "qianwen"         # 通义千问
    BAIDU_AI = "baidu_ai"       # 百度AI (文心一言)
    YUANBAO = "yuanbao"         # 元宝 (腾讯)
    CHATGPT = "chatgpt"         # ChatGPT (海外)
    GEMINI = "gemini"           # Gemini (海外)
    CLAUDE = "claude"           # Claude (海外)


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
    error: str = None
    tokens_used: int = 0
    cost: float = 0.0
    response_time: float = 0.0
    timestamp: datetime = None


class MultiAIPlatformService:
    """多AI平台服务"""

    def __init__(self):
        self.platforms = {}
        self._init_platforms()

    def _init_platforms(self):
        """初始化所有平台配置"""
        # 豆包
        self.platforms[AIPlatform.DOUBAO] = PlatformConfig(
            name="豆包",
            api_base="https://ark.cn-beijing.volces.com/api/v3",
            api_key=os.getenv("DOUBAO_API_KEY", ""),
            model="doubao-pro-32k"
        )

        # DeepSeek
        self.platforms[AIPlatform.DEEPSEEK] = PlatformConfig(
            name="DeepSeek",
            api_base="https://api.deepseek.com/v1",
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            model="deepseek-chat"
        )

        # Kimi
        self.platforms[AIPlatform.KIMI] = PlatformConfig(
            name="Kimi",
            api_base="https://api.moonshot.cn/v1",
            api_key=os.getenv("KIMI_API_KEY", ""),
            model="moonshot-v1-8k"
        )

        # 通义千问
        self.platforms[AIPlatform.QIANWEN] = PlatformConfig(
            name="通义千问",
            api_base="https://dashscope.aliyuncs.com/api/v1",
            api_key=os.getenv("QIANWEN_API_KEY", ""),
            model="qwen-turbo"
        )

        # 百度AI (文心一言)
        self.platforms[AIPlatform.BAIDU_AI] = PlatformConfig(
            name="百度AI",
            api_base="https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat",
            api_key=os.getenv("BAIDU_API_KEY", ""),
            model="ernie-bot-4"
        )

        # 元宝 (腾讯混元)
        self.platforms[AIPlatform.YUANBAO] = PlatformConfig(
            name="元宝",
            api_base="https://hunyuan.tencentcloudapi.com",
            api_key=os.getenv("YUANBAO_API_KEY", ""),
            model="hunyuan-pro"
        )

        # 海外平台
        self.platforms[AIPlatform.CHATGPT] = PlatformConfig(
            name="ChatGPT",
            api_base="https://api.openai.com/v1",
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model="gpt-4o",
            is_available=False  # 默认不可用，需要配置
        )

        self.platforms[AIPlatform.GEMINI] = PlatformConfig(
            name="Gemini",
            api_base="https://generativelanguage.googleapis.com/v1",
            api_key=os.getenv("GEMINI_API_KEY", ""),
            model="gemini-pro",
            is_available=False
        )

        self.platforms[AIPlatform.CLAUDE] = PlatformConfig(
            name="Claude",
            api_base="https://api.anthropic.com/v1",
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            model="claude-3-opus-20240229",
            is_available=False
        )

    def get_available_platforms(self) -> List[Dict]:
        """获取所有可用的平台列表"""
        platforms = []
        for platform, config in self.platforms.items():
            platforms.append({
                "id": platform.value,
                "name": config.name,
                "model": config.model,
                "available": config.is_available and bool(config.api_key),
                "max_tokens": config.max_tokens
            })
        return platforms

    def generate_with_platform(self, platform: AIPlatform, prompt: str,
                               system_prompt: Optional[str] = None,
                               temperature: float = None,
                               max_tokens: int = None) -> GenerationResult:
        """使用指定平台生成内容"""
        import time
        start_time = time.time()

        config = self.platforms.get(platform)
        if not config:
            return GenerationResult(
                platform=platform.value,
                content="",
                success=False,
                error=f"平台 {platform.value} 未配置"
            )

        if not config.api_key:
            return GenerationResult(
                platform=platform.value,
                content="",
                success=False,
                error=f"平台 {config.name} 未配置API密钥"
            )

        try:
            # 根据不同平台调用不同的API
            if platform == AIPlatform.DOUBAO:
                content = self._call_doubao(config, prompt, system_prompt, temperature, max_tokens)
            elif platform == AIPlatform.DEEPSEEK:
                content = self._call_deepseek(config, prompt, system_prompt, temperature, max_tokens)
            elif platform == AIPlatform.KIMI:
                content = self._call_kimi(config, prompt, system_prompt, temperature, max_tokens)
            elif platform == AIPlatform.QIANWEN:
                content = self._call_qianwen(config, prompt, system_prompt, temperature, max_tokens)
            elif platform == AIPlatform.BAIDU_AI:
                content = self._call_baidu(config, prompt, system_prompt, temperature, max_tokens)
            elif platform == AIPlatform.YUANBAO:
                content = self._call_yuanbao(config, prompt, system_prompt, temperature, max_tokens)
            else:
                content = self._call_openai_compatible(config, prompt, system_prompt, temperature, max_tokens)

            response_time = time.time() - start_time

            return GenerationResult(
                platform=platform.value,
                content=content,
                success=True,
                response_time=response_time,
                timestamp=datetime.now()
            )

        except Exception as e:
            return GenerationResult(
                platform=platform.value,
                content="",
                success=False,
                error=str(e),
                response_time=time.time() - start_time
            )

    def _call_doubao(self, config: PlatformConfig, prompt: str,
                     system_prompt: Optional[str], temperature: float, max_tokens: int) -> str:
        """调用豆包API"""
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": config.model,
            "messages": messages,
            "temperature": temperature or config.temperature,
            "max_tokens": max_tokens or config.max_tokens
        }

        response = requests.post(
            f"{config.api_base}/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            raise Exception(f"豆包API错误: {response.status_code} - {response.text}")

    def _call_deepseek(self, config: PlatformConfig, prompt: str,
                       system_prompt: Optional[str], temperature: float, max_tokens: int) -> str:
        """调用DeepSeek API"""
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": config.model,
            "messages": messages,
            "temperature": temperature or config.temperature,
            "max_tokens": max_tokens or config.max_tokens
        }

        response = requests.post(
            f"{config.api_base}/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            raise Exception(f"DeepSeek API错误: {response.status_code} - {response.text}")

    def _call_kimi(self, config: PlatformConfig, prompt: str,
                   system_prompt: Optional[str], temperature: float, max_tokens: int) -> str:
        """调用Kimi API"""
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": config.model,
            "messages": messages,
            "temperature": temperature or config.temperature
        }

        response = requests.post(
            f"{config.api_base}/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            raise Exception(f"Kimi API错误: {response.status_code} - {response.text}")

    def _call_qianwen(self, config: PlatformConfig, prompt: str,
                      system_prompt: Optional[str], temperature: float, max_tokens: int) -> str:
        """调用通义千问API"""
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": config.model,
            "input": {
                "messages": messages
            },
            "parameters": {
                "temperature": temperature or config.temperature,
                "max_tokens": max_tokens or config.max_tokens
            }
        }

        response = requests.post(
            f"{config.api_base}/services/aigc/text-generation/generation",
            headers=headers,
            json=data,
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            return result["output"]["text"]
        else:
            raise Exception(f"通义千问API错误: {response.status_code} - {response.text}")

    def _call_baidu(self, config: PlatformConfig, prompt: str,
                    system_prompt: Optional[str], temperature: float, max_tokens: int) -> str:
        """调用百度AI API"""
        # 百度API需要先获取access_token
        access_token = self._get_baidu_access_token(config.api_key)

        url = f"{config.api_base}/completions_pro?access_token={access_token}"

        headers = {
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "messages": messages,
            "temperature": temperature or config.temperature
        }

        response = requests.post(url, headers=headers, json=data, timeout=60)

        if response.status_code == 200:
            result = response.json()
            return result["result"]
        else:
            raise Exception(f"百度AI API错误: {response.status_code} - {response.text}")

    def _get_baidu_access_token(self, api_key: str) -> str:
        """获取百度API access token"""
        # 这里简化处理，实际应该缓存token
        return api_key

    def _call_yuanbao(self, config: PlatformConfig, prompt: str,
                      system_prompt: Optional[str], temperature: float, max_tokens: int) -> str:
        """调用元宝(腾讯混元) API"""
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "Model": config.model,
            "Messages": messages
        }

        response = requests.post(
            f"{config.api_base}/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            return result["Choices"][0]["Message"]["Content"]
        else:
            raise Exception(f"元宝API错误: {response.status_code} - {response.text}")

    def _call_openai_compatible(self, config: PlatformConfig, prompt: str,
                                system_prompt: Optional[str], temperature: float, max_tokens: int) -> str:
        """调用OpenAI兼容格式的API"""
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": config.model,
            "messages": messages,
            "temperature": temperature or config.temperature,
            "max_tokens": max_tokens or config.max_tokens
        }

        response = requests.post(
            f"{config.api_base}/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            raise Exception(f"API错误: {response.status_code} - {response.text}")

    def generate_with_fallback(self, prompt: str, platforms: List[AIPlatform] = None,
                               system_prompt: Optional[str] = None) -> GenerationResult:
        """带故障转移的多平台生成"""
        if platforms is None:
            # 默认优先级：豆包 > DeepSeek > Kimi > 通义千问
            platforms = [
                AIPlatform.DOUBAO,
                AIPlatform.DEEPSEEK,
                AIPlatform.KIMI,
                AIPlatform.QIANWEN
            ]

        last_error = None
        for platform in platforms:
            result = self.generate_with_platform(platform, prompt, system_prompt)
            if result.success:
                return result
            last_error = result.error

        # 所有平台都失败
        return GenerationResult(
            platform="all",
            content="",
            success=False,
            error=f"所有平台均失败，最后一个错误: {last_error}"
        )

    def batch_generate(self, prompts: List[str], platform: AIPlatform = AIPlatform.DOUBAO,
                       system_prompt: Optional[str] = None) -> List[GenerationResult]:
        """批量生成内容"""
        results = []
        for prompt in prompts:
            result = self.generate_with_platform(platform, prompt, system_prompt)
            results.append(result)
        return results


# 全局服务实例
ai_platform_service = MultiAIPlatformService()


if __name__ == "__main__":
    # 测试
    service = MultiAIPlatformService()
    platforms = service.get_available_platforms()
    print("可用平台:")
    for p in platforms:
        status = "✅" if p["available"] else "❌"
        print(f"  {status} {p['name']} ({p['id']}) - {p['model']}")
