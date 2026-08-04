# -*- coding: utf-8 -*-
"""
图像生成服务（多模型重试链）

迁移自 GEO-main 项目 geo_system/backend/image_generation_service.py，
适配 MediaCrawler 的异步架构与配置规范。

对应 PRD 5.2 视频智能生成 / 内容配图模块 - 图像生成能力。

适配点：
1. 同步 requests 调用 → 异步 httpx.AsyncClient 调用，所有方法改为 async def
2. time.sleep 轮询 → await asyncio.sleep，避免阻塞事件循环
3. 移除 GEO-main 的 ai_service 依赖，submit_media_task / get_task_status
   内联为对图像生成 API 的直接 HTTP 调用（lk888.ai / OpenAI 兼容协议）
4. 配置统一通过环境变量读取：
   - IMAGE_API_KEY / IMAGE_API_BASE_URL：主图像生成 API（lk888.ai / OpenAI 兼容）
   - ONELLM_API_KEY / ONELLM_BASE_URL：onellm 多媒体生成 API（doubao-seedream 等）
5. 不再硬编码任何 API Key、URL 默认值（敏感信息一律走环境变量）
6. 暴露 get_image_generation_service() 单例，符合 MediaCrawler 服务规范

保留的业务逻辑：
- 多模型重试链（onellm → lk888.ai gpt-image-2 → Pollinations.ai → OpenAI DALL-E）
- LLM 总结中文 prompt（强图文相关）+ 规则兜底 prompt
- 小红书封面图 / 多张配图生成
- base64 图片持久化到本地目录
- onellm 同步/异步接口双通道 + 任务轮询
"""

import os
import base64
import asyncio
import logging
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict, Any

import httpx

logger = logging.getLogger(__name__)


class ImageGenerationService:
    """图像生成服务 - 强图文相关，多模型重试链"""

    # 文生图模型优先级链（lk888.ai / OpenAI 兼容）
    IMAGE_MODELS = ['gpt-image-2', 'gpt-image-1']

    # onellm 多媒体生成模型优先级链（首选，中文场景表现优秀）
    ONELLM_MODELS = [
        'doubao-seedream-4-5-251128',           # 即梦 4.5（中文场景最佳）
        'doubao-seedream-5-0-260128',           # 即梦 5.0
        'gemini-3-pro-image-preview',            # Nano Banana Pro
        'gpt-image-2-all',                      # GPT Image 2
        'gpt-image-1.5-all',                    # GPT Image 1.5
        'grok-4.1-image',                       # Grok Image 4.1
        'grok-4.2-image',                       # Grok Image 4.2
    ]

    def __init__(self):
        # 主图像生成 API（lk888.ai / OpenAI 兼容）
        # IMAGE_API_BASE_URL 不含 /v1，URL 构造时统一追加
        self.api_key = os.environ.get("IMAGE_API_KEY", "")
        self.api_base = os.environ.get("IMAGE_API_BASE_URL", "").rstrip('/')

        # onellm 多媒体生成 API（独立服务，doubao-seedream 等）
        # ONELLM_BASE_URL 不含 /v1，URL 构造时统一追加
        self.onellm_api_key = os.environ.get("ONELLM_API_KEY", "")
        self.onellm_base_url = os.environ.get("ONELLM_BASE_URL", "").rstrip('/')

    # ==================== LLM 总结 prompt ====================

    async def _summarize_to_image_prompt(
        self,
        title: str,
        content: str,
        keywords: List[str] = None,
        brand_name: str = None,
        scene_role: str = 'cover',
    ) -> Optional[str]:
        """
        用 LLM 把文案内容总结成精准的中文图片生成 prompt

        Args:
            title: 笔记标题
            content: 笔记内容
            keywords: 关键词
            brand_name: 品牌名（如：织然家具）
            scene_role: cover=封面图 / detail=细节配图

        Returns:
            中文图片描述 prompt，失败返回 None
        """
        try:
            # 截断超长内容
            content_snippet = (content or '')[:1200]
            keywords_str = '、'.join((keywords or [])[:8])
            brand = brand_name or ''

            role_desc = {
                'cover': '封面图（整体场景，能一眼看出主题）',
                'detail': '细节配图（聚焦某个物品或局部）',
            }.get(scene_role, '配图')

            system_prompt = (
                "你是小红书家居博主的专业摄影导演。"
                "根据用户提供的笔记标题、正文、关键词和品牌，"
                "输出一段精准、画面感强的【中文】图片生成提示词，"
                "用于 AI 文生图模型（gpt-image-2）。"
            )

            user_prompt = f"""请基于以下小红书笔记信息，生成一段【中文】图片生成提示词：

【品牌】{brand}
【标题】{title}
【关键词】{keywords_str}
【正文节选】
{content_snippet}

【图片角色】{role_desc}

【输出要求】
1. 输出一段 80-180 字的连续中文描述（不要分点，不要 markdown）
2. 必须紧扣标题和正文描述的具体场景/物品/风格，不要泛泛而谈
3. 必须包含：场景（如客厅/卧室/书房）+ 主体物品 + 风格（如简约/原木/奶油风）+ 光线 + 色调 + 构图视角
4. 如果品牌是家具/家居类，要体现真实生活感，不要广告感
5. 结尾追加：「竖版构图 3:4，自然光，真实摄影质感，无水印，无文字」
6. 不要输出任何解释性文字，只输出 prompt 本身"""

            if not self.api_key or not self.api_base:
                logger.warning("[LLM Prompt] 未配置 IMAGE_API_KEY / IMAGE_API_BASE_URL，跳过 LLM 总结")
                return None

            llm_url = f'{self.api_base}/v1/chat/completions'
            llm_model = 'gpt-4o-mini'
            logger.info(f"[LLM Prompt] 使用图像生成 API: {llm_url}")

            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            }
            payload = {
                'model': llm_model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'temperature': 0.7,
                'max_tokens': 400,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(llm_url, headers=headers, json=payload)

            if resp.status_code != 200:
                logger.warning(f"[LLM Prompt] {llm_model} 返回 {resp.status_code}: {resp.text[:200]}")
                return None

            data = resp.json()
            prompt_text = (data.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
            if not prompt_text or len(prompt_text) < 20:
                logger.warning(f"[LLM Prompt] 返回内容过短: {prompt_text!r}")
                return None

            logger.info(f"[LLM Prompt] {scene_role} 生成成功（{len(prompt_text)}字）: {prompt_text[:80]}...")
            return prompt_text

        except Exception as e:
            logger.error(f"[LLM Prompt] 生成失败: {e}")
            return None

    def _build_fallback_prompt(
        self,
        title: str,
        content: str,
        keywords: List[str] = None,
        brand_name: str = None,
    ) -> str:
        """规则兜底：LLM 失败时用规则提取关键信息生成中文 prompt"""
        # 提取房间类型
        room_types = ['客厅', '卧室', '厨房', '书房', '餐厅', '阳台', '卫生间', '玄关', '衣帽间']
        detected_room = next((r for r in room_types if r in (title or '') or r in (content or '')), '客厅')

        # 提取风格
        styles = ['简约', '北欧', '日式', '现代', '复古', '轻奢', '原木', '奶油', '极简', '中古', '侘寂']
        detected_style = next((s for s in styles if s in (title or '') or s in (content or '')), '原木简约')

        # 提取关键元素
        element_keywords = ['沙发', '茶几', '餐桌', '床', '衣柜', '书桌', '窗帘', '灯具', '地板',
                            '墙面', '收纳', '绿植', '地毯', '挂画', '抱枕', '斗柜']
        key_elements = [e for e in element_keywords if e in (content or '')]
        elements_str = '、'.join(key_elements[:4]) if key_elements else '原木家具'

        brand = brand_name or ''
        brand_clause = f'体现{brand}品牌调性，' if brand else ''

        return (f'{detected_style}风格的{detected_room}实景照片，{brand_clause}'
                f'画面主体为{elements_str}，搭配柔光台灯和绿植点缀，'
                f'午后自然光从左侧窗户洒入，温暖治愈的色调，真实生活质感，'
                f'竖版构图 3:4，自然光，真实摄影质感，无水印，无文字')

    # ==================== 主入口：生成单张图片 ====================

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1792",
        quality: str = "hd",
    ) -> Optional[str]:
        """
        生成图片 - 多模型重试链

        重试顺序：
        1. onellm doubao-seedream / gpt-image-2-all / grok-4.1-image（首选，中文场景最佳）
        2. lk888.ai gpt-image-2 / gpt-image-1（备用）
        3. Pollinations.ai（免费兜底）
        4. OpenAI DALL-E（如果配置了）

        Args:
            prompt: 图片生成提示词（推荐中文，gpt-image-2 支持中文）
            size: 图片尺寸（默认竖图 1024x1792）
            quality: 图片质量 standard / hd

        Returns:
            图片的 base64 编码（data URI 格式），失败返回 None
        """
        # 1. 主：onellm 多模型重试链
        for model in self.ONELLM_MODELS:
            result = await self._generate_with_onellm(prompt, size, model)
            if result:
                return result

        # 2. 备：lk888.ai gpt-image-2
        for model in self.IMAGE_MODELS:
            result = await self._generate_with_ai_agent(prompt, size, model)
            if result:
                return result

        # 3. 备：Pollinations.ai
        result = await self._generate_with_pollinations(prompt, size)
        if result:
            return result

        # 4. 备：OpenAI DALL-E（如果配置了）
        if self.api_key:
            result = await self._generate_with_openai(prompt, size, quality)
            if result:
                return result

        logger.error("[图片生成] 所有模型均失败，拒绝生成垃圾图")
        return None

    async def _generate_with_onellm(
        self,
        prompt: str,
        size: str = "1024x1792",
        model: str = 'doubao-seedream-4-5-251128',
    ) -> Optional[str]:
        """
        使用 onellm 多媒体生成 API 生成图片

        Endpoint: POST {ONELLM_BASE_URL}/v1/media/generations (异步) 或 /v1/media/generations/sync (同步)
        认证: Authorization: Bearer {ONELLM_API_KEY}
        """
        try:
            if not self.onellm_api_key:
                logger.warning(f"[onellm] {model} 跳过：未配置 ONELLM_API_KEY")
                return None

            if not self.onellm_base_url:
                logger.warning(f"[onellm] {model} 跳过：未配置 ONELLM_BASE_URL")
                return None

            # 把 1024x1792 这种格式映射到 onellm 支持的参数
            # onellm 既支持 size（如 1536x2048）也支持 aspect_ratio（如 3:4）
            aspect_ratio = '3:4'  # 默认竖图，适配小红书
            onellm_size = '1536x2048'  # 默认尺寸

            if '1792' in size or '1536' in size:
                aspect_ratio = '3:4'
                onellm_size = '1536x2048'
            elif '1024x1024' in size or size == '1024x1024':
                aspect_ratio = '1:1'
                onellm_size = '1024x1024'
            elif '1792x1024' in size:
                aspect_ratio = '4:3'
                onellm_size = '2048x1536'

            logger.info(f"[onellm] 调用 {model} 生成图片: {prompt[:60]}...")

            headers = {
                'Authorization': f'Bearer {self.onellm_api_key}',
                'Content-Type': 'application/json',
            }

            # 优先尝试同步接口（更快），失败后用异步接口
            sync_url = f'{self.onellm_base_url}/v1/media/generations/sync'
            async_url = f'{self.onellm_base_url}/v1/media/generations'

            payload = {
                'model': model,
                'prompt': prompt,
                'size': onellm_size,
                'n': 1,
                'aspect_ratio': aspect_ratio,
            }

            # 步骤 1：尝试同步接口
            try:
                logger.info(f"[onellm] 同步接口调用: POST {sync_url}")
                async with httpx.AsyncClient(timeout=180.0) as client:
                    resp = await client.post(sync_url, headers=headers, json=payload)

                if resp.status_code == 200:
                    data = resp.json()
                    image_url = self._extract_onellm_image_url(data)
                    if image_url:
                        logger.info(f"[onellm] {model} 同步生成成功: {image_url[:100]}")
                        return await self._download_image_as_base64(image_url)
                    logger.warning(f"[onellm] 同步响应无 image url: {str(data)[:200]}")
                else:
                    logger.warning(f"[onellm] 同步 HTTP {resp.status_code}: {resp.text[:200]}")
            except httpx.TimeoutException:
                logger.warning(f"[onellm] 同步接口超时，改用异步")
            except Exception as e:
                logger.warning(f"[onellm] 同步接口异常: {e}")

            # 步骤 2：异步接口（提交任务 + 轮询）
            logger.info(f"[onellm] 异步接口提交: POST {async_url}")
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(async_url, headers=headers, json=payload)

            if resp.status_code != 200:
                logger.warning(f"[onellm] {model} 异步提交失败 HTTP {resp.status_code}: {resp.text[:200]}")
                return None

            task_data = resp.json()
            task_id = task_data.get('id') or task_data.get('task_id')
            if not task_id and isinstance(task_data.get('data'), dict):
                task_id = task_data.get('data', {}).get('task_id')

            if not task_id:
                # 直接返回图片 URL（部分接口立即返回结果）
                image_url = self._extract_onellm_image_url(task_data)
                if image_url:
                    logger.info(f"[onellm] {model} 直接返回图片 URL")
                    return await self._download_image_as_base64(image_url)
                logger.warning(f"[onellm] {model} 未拿到 task_id: {str(task_data)[:200]}")
                return None

            logger.info(f"[onellm] {model} 任务已提交: {task_id}")

            # 轮询任务状态
            status_url = f'{self.onellm_base_url}/v1/media/generations/{task_id}'
            max_attempts = 120  # 最多 240 秒
            for attempt in range(max_attempts):
                await asyncio.sleep(2)
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        status_resp = await client.get(status_url, headers=headers)
                except Exception as e:
                    logger.warning(f"[onellm] 轮询异常: {e}")
                    continue

                if status_resp.status_code != 200:
                    continue

                sdata = status_resp.json()
                status_str = sdata.get('status') or ''
                if not status_str and isinstance(sdata.get('data'), dict):
                    status_str = sdata.get('data', {}).get('status', '')

                if status_str in ('completed', 'succeeded', 'success'):
                    image_url = self._extract_onellm_image_url(sdata)
                    if image_url:
                        logger.info(f"[onellm] {model} 异步任务完成")
                        return await self._download_image_as_base64(image_url)
                    logger.warning(f"[onellm] 任务完成但无 image url: {str(sdata)[:200]}")
                    break
                elif status_str in ('failed', 'error', 'cancelled'):
                    logger.warning(f"[onellm] {model} 任务失败: {status_str}")
                    break

            logger.warning(f"[onellm] {model} 超时或失败")
            return None

        except Exception as e:
            logger.error(f"[onellm] {model} 异常: {e}")
            return None

    def _extract_onellm_image_url(self, data: Dict) -> Optional[str]:
        """从 onellm 响应中提取图片 URL（兼容多种返回格式）"""
        if not isinstance(data, dict):
            return None

        # 直接 url
        if data.get('url'):
            return data['url']

        # data.url
        data_field = data.get('data')
        if isinstance(data_field, dict):
            if data_field.get('url'):
                return data_field['url']
            if data_field.get('image_url'):
                return data_field['image_url']

        # data[0].url（list 形式）
        if isinstance(data_field, list) and data_field:
            first = data_field[0]
            if isinstance(first, dict):
                return first.get('url') or first.get('image_url') or first.get('b64_json')

        # data.images[0].url
        images = data.get('images')
        if not images and isinstance(data_field, dict):
            images = data_field.get('images')
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                return first.get('url') or first.get('image_url')
            elif isinstance(first, str):
                return first

        # result.url
        result = data.get('result')
        if isinstance(result, dict):
            return result.get('url') or result.get('image_url')
        if isinstance(result, str) and result.startswith('http'):
            return result

        return None

    async def _submit_media_task(
        self,
        model: str,
        prompt: str,
        params: Dict[str, Any],
    ) -> Optional[Dict]:
        """提交媒体生成任务到图像生成 API（lk888.ai / OpenAI 兼容协议）

        内联原 GEO-main ai_service.submit_media_task 的 HTTP 调用。
        """
        if not self.api_key or not self.api_base:
            logger.warning("[AI Agent] 未配置 IMAGE_API_KEY / IMAGE_API_BASE_URL，跳过提交")
            return None

        url = f'{self.api_base}/v1/media/generations'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': model,
            'prompt': prompt,
            **params,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                logger.warning(f"[AI Agent] 提交 HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            return resp.json()
        except Exception as e:
            logger.error(f"[AI Agent] 提交异常: {e}")
            return None

    async def _get_media_task_status(self, task_id: str) -> Optional[Dict]:
        """查询媒体任务状态（lk888.ai / OpenAI 兼容协议）

        内联原 GEO-main ai_service.get_task_status 的 HTTP 调用。
        """
        if not self.api_key or not self.api_base:
            return None

        url = f'{self.api_base}/v1/media/generations/{task_id}'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as e:
            logger.warning(f"[AI Agent] 状态查询异常: {e}")
            return None

    async def _generate_with_ai_agent(
        self,
        prompt: str,
        size: str = "1024x1792",
        model: str = 'gpt-image-2',
    ) -> Optional[str]:
        """使用 lk888.ai Agent API 生成图片"""
        try:
            logger.info(f"[AI Agent] 调用 {model} 生成图片: {prompt[:60]}...")

            # gpt-image-2 用 aspect_ratio 控制比例
            aspect = '3:4' if '1792' in size or 'x1536' in size else '1:1'

            result = await self._submit_media_task(
                model=model,
                prompt=prompt,
                params={'aspect_ratio': aspect},
            )

            # 兼容两种返回格式：{code: 200, data: {task_id}} 或 {success: False, error}
            if isinstance(result, dict):
                if result.get('code') not in (200, None) and not result.get('data'):
                    logger.warning(f"[AI Agent] {model} 提交失败: {result.get('msg') or result.get('error')}")
                    return None
            else:
                logger.warning(f"[AI Agent] {model} 返回非 dict: {type(result)}")
                return None

            task_id = None
            if isinstance(result.get('data'), dict):
                task_id = result.get('data', {}).get('task_id')

            if not task_id:
                # 部分接口直接返回 image_url
                image_url = (result.get('data') or {}).get('image_url') or result.get('image_url')
                if image_url:
                    return await self._download_image_as_base64(image_url)
                logger.warning(f"[AI Agent] {model} 未获取到 task_id")
                return None

            logger.info(f"[AI Agent] {model} 任务已提交: {task_id}")

            # 轮询等待
            max_attempts = 90  # 最多 180 秒
            for attempt in range(max_attempts):
                await asyncio.sleep(2)
                status = await self._get_media_task_status(str(task_id))

                if not isinstance(status, dict):
                    continue

                task_data = status.get('data') or status
                task_status = task_data.get('status', '')
                task_state = task_data.get('state', '')

                if task_status == 'completed' or task_state == 'success':
                    image_url = task_data.get('image_url') or task_data.get('url') or task_data.get('result_url')
                    if image_url:
                        logger.info(f"[AI Agent] {model} 图片生成成功")
                        return await self._download_image_as_base64(image_url)
                    break
                elif task_status in ('failed', 'error') or task_state in ('failed', 'error'):
                    logger.warning(f"[AI Agent] {model} 任务失败: {task_data.get('error') or task_data}")
                    break

            logger.warning(f"[AI Agent] {model} 超时或失败")
            return None

        except Exception as e:
            logger.error(f"[AI Agent] {model} 异常: {e}")
            return None

    async def _download_image_as_base64(self, image_url: str) -> Optional[str]:
        """下载图片 URL 并转为 base64 data URI"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                img_response = await client.get(image_url)

            if img_response.status_code == 200:
                b64 = base64.b64encode(img_response.content).decode('utf-8')
                return f"data:image/png;base64,{b64}"
            logger.warning(f"[下载图片] HTTP {img_response.status_code}")
            return None
        except Exception as e:
            logger.error(f"[下载图片] 失败: {e}")
            return None

    async def _generate_with_openai(
        self,
        prompt: str,
        size: str,
        quality: str,
    ) -> Optional[str]:
        """使用 OpenAI 兼容 API 生成图片"""
        try:
            if not self.api_key or not self.api_base:
                return None

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            is_hropenai = "hropenai" in self.api_base.lower()
            model = "gpt-image-2" if is_hropenai else "dall-e-3"

            data = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": quality,
                "response_format": "b64_json",
            }

            logger.info(f"使用 OpenAI 兼容 API 生成图片: model={model}")
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.api_base}/v1/images/generations",
                    headers=headers, json=data,
                )

            if response.status_code == 200:
                result = response.json()
                b64_image = result['data'][0]['b64_json']
                logger.info("[OpenAI] 图片生成成功")
                return f"data:image/png;base64,{b64_image}"

            logger.warning(f"[OpenAI] HTTP {response.status_code}: {response.text[:200]}")
            return None

        except Exception as e:
            logger.warning(f"[OpenAI] 失败: {e}")
            return None

    async def _generate_with_pollinations(
        self,
        prompt: str,
        size: str = "1024x1792",
    ) -> Optional[str]:
        """Pollinations.ai 免费 API（最后兜底）"""
        try:
            logger.info("[Pollinations] 调用免费 API")

            width, height = 1024, 1536
            if size == "1024x1792":
                width, height = 1024, 1536
            elif size == "1792x1024":
                width, height = 1536, 1024

            encoded_prompt = urllib.parse.quote(prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&seed=42"

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(url)

            if response.status_code == 200:
                b64 = base64.b64encode(response.content).decode('utf-8')
                logger.info("[Pollinations] 图片生成成功")
                return f"data:image/png;base64,{b64}"

            logger.error(f"[Pollinations] HTTP {response.status_code}")
            return None

        except Exception as e:
            logger.error(f"[Pollinations] 失败: {e}")
            return None

    # ==================== 小红书专用接口 ====================

    async def generate_xiaohongshu_cover(
        self,
        title: str,
        content: str,
        keywords: List[str] = None,
        brand_name: str = None,
    ) -> Optional[str]:
        """生成小红书封面图 - 用 LLM 总结精准中文 prompt"""
        prompt = await self._summarize_to_image_prompt(
            title=title, content=content, keywords=keywords,
            brand_name=brand_name, scene_role='cover',
        ) or self._build_fallback_prompt(title, content, keywords, brand_name)

        return await self.generate_image(prompt, size="1024x1792", quality="hd")

    async def generate_xiaohongshu_images(
        self,
        title: str,
        content: str = "",
        keywords: List[str] = None,
        count: int = 3,
        brand_name: str = None,
    ) -> List[str]:
        """
        生成小红书配图 - 每张图都基于内容生成独立 prompt，强图文相关

        Args:
            title: 笔记标题
            content: 笔记内容
            keywords: 关键词列表
            count: 生成图片数量（1 封面 + N 细节图）
            brand_name: 品牌名

        Returns:
            图片 base64 列表（data URI 格式）
        """
        images = []
        keywords = keywords or []
        content = content or ''
        brand = brand_name or ''

        logger.info(f"[图片生成] 开始生成 {count} 张图，品牌={brand}，标题={title[:30]}")

        # 第 1 张：封面图
        cover_prompt = await self._summarize_to_image_prompt(
            title=title, content=content, keywords=keywords,
            brand_name=brand, scene_role='cover',
        ) or self._build_fallback_prompt(title, content, keywords, brand)

        cover_image = await self.generate_image(cover_prompt, size="1024x1792", quality="hd")
        if cover_image:
            images.append(cover_image)
            logger.info("[图片生成] 封面图生成成功")

        # 后续：细节配图 - 提取内容中的不同段落作为不同场景
        detail_sections = self._extract_content_sections(content)
        for i in range(count - 1):
            section = detail_sections[i] if i < len(detail_sections) else f'{brand}产品细节'

            detail_prompt = await self._summarize_to_image_prompt(
                title=title, content=f'{section}\n\n参考正文：{content[:600]}',
                keywords=keywords, brand_name=brand, scene_role='detail',
            ) or self._build_fallback_prompt(f'{title} - {section}', content, keywords, brand)

            img = await self.generate_image(detail_prompt, size="1024x1792", quality="hd")
            if img:
                images.append(img)
                logger.info(f"[图片生成] 配图{i + 1}生成成功（场景: {section[:20]}）")

        logger.info(f"[图片生成] 共生成 {len(images)}/{count} 张图片")
        return images

    def save_base64_to_temp(self, base64_image: str) -> Optional[str]:
        """将 base64 图片保存为临时文件（兼容旧调用）"""
        return self.save_base64_to_local(base64_image)

    def save_base64_to_local(
        self,
        base64_image: str,
        brand_name: str = None,
        task_id: int = None,
        index: int = 0,
        subdir: str = 'xiaohongshu',
    ) -> Optional[str]:
        """
        将 base64 图片持久化保存到本地目录

        存储路径：
            {PROJECT_ROOT}/data/generated_images/{subdir}/{brand}_{task_id}_{timestamp}_{index}.jpg

        Args:
            base64_image: base64 编码的图片（data URI 或纯 base64）
            brand_name: 品牌名（用于文件名，便于区分）
            task_id: 任务ID
            index: 图片序号（多张图时区分）
            subdir: 子目录（如 xiaohongshu / douyin / workflow）

        Returns:
            保存后的本地文件绝对路径，失败返回 None
        """
        try:
            if ',' in base64_image:
                base64_image = base64_image.split(',')[1]
            img_data = base64.b64decode(base64_image)

            # 确定 project_root：优先用 api/services/ai 的上三级
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
            # 容器内路径优先（/app/data）
            if os.path.isdir('/app/data'):
                save_dir = f'/app/data/generated_images/{subdir}'
            else:
                save_dir = os.path.join(project_root, 'data', 'generated_images', subdir)
            os.makedirs(save_dir, exist_ok=True)

            # 构造文件名：品牌_task时间戳_序号.jpg
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_brand = ''.join(c if c.isalnum() or c in '-_' else '_' for c in (brand_name or 'brand'))[:20]
            task_part = f't{task_id}' if task_id else 't0'
            filename = f'{safe_brand}_{task_part}_{ts}_{index}.jpg'
            file_path = os.path.join(save_dir, filename)

            with open(file_path, 'wb') as f:
                f.write(img_data)

            logger.info(f"[图片保存] 已保存: {file_path} ({len(img_data)} bytes)")
            return file_path

        except Exception as e:
            logger.error(f"[图片保存] 失败: {e}")
            return None

    def _extract_content_sections(self, content: str) -> List[str]:
        """从内容中提取关键段落作为不同配图主题"""
        import re
        sections = []

        # 按句子切分
        pattern = r'([^。！？\n]+[。！？])'
        sentences = re.findall(pattern, content)

        # 筛选包含具体描述词的句子
        desc_keywords = ['做了', '用了', '选了', '搭配', '设计', '改造', '安装', '摆放',
                         '选择', '采用', '搭配', '呈现', '展现']
        for sent in sentences:
            for keyword in desc_keywords:
                if keyword in sent and len(sent) > 10:
                    clean = sent.strip().replace('其实', '').replace('感觉', '').replace('真的', '')
                    if len(clean) > 5:
                        sections.append(clean[:40])
                        break
            if len(sections) >= 3:
                break

        if not sections:
            sections = ['整体空间效果', '材质细节展示', '实际使用场景']

        return sections


# 单例
_image_generation_service: Optional[ImageGenerationService] = None


def get_image_generation_service() -> ImageGenerationService:
    """获取图像生成服务单例"""
    global _image_generation_service
    if _image_generation_service is None:
        _image_generation_service = ImageGenerationService()
    return _image_generation_service
