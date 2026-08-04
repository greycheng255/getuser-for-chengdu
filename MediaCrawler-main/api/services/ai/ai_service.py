# -*- coding: utf-8 -*-
"""
AI 服务调用模块（迁移自 GEO-main）.

对应 PRD 模块：AI 内容生成 / GEO 优化文章与方案生成.

适配点：
1. 凭据与 Base URL 不再硬编码，统一通过 MediaCrawler 的
   ``config.onellm_config.load_onellm_config()`` 读取
   （环境变量 ONELLM_API_KEY / ONELLM_BASE_URL / ONELLM_CHAT_MODEL），
   与现有 ``api/services/ai6700_client.py`` 保持一致。
2. HTTP 客户端由同步 ``requests`` 改为异步 ``httpx.AsyncClient``，
   所有业务方法改为 ``async def``。
3. 日志使用 ``logging.getLogger(__name__)``，移除 ``print``。
4. 合并 GEO-main ``ai_service_v2`` 的增强能力：重试机制、指数退避、
   ``generate_geo_plan`` 方法（并修复原 v2 中 system_prompt 未闭合
   导致 prompt 被吞掉的语法缺陷）。
5. 提供单例 ``get_ai_service()``。
6. 本模块为纯 HTTP 调用，无数据库依赖，故未引入 PostgreSQL 适配层。
"""

import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from config.onellm_config import OneLLMConfig, load_onellm_config

logger = logging.getLogger(__name__)


class AIService:
    """AI 服务客户端（OneLLM / lk888.ai 网关）。

    封装聊天补全、媒体生成、余额查询、反馈等能力，并提供 GEO 优化
    文章与方案的高层生成方法。
    """

    def __init__(self, settings: Optional[OneLLMConfig] = None) -> None:
        self._settings: OneLLMConfig = settings or load_onellm_config()
        self.timeout: int = int(os.environ.get("AI_SERVICE_TIMEOUT", "120"))
        self.max_retries: int = int(os.environ.get("AI_SERVICE_MAX_RETRIES", "3"))
        self.retry_delay: float = float(os.environ.get("AI_SERVICE_RETRY_DELAY", "2"))

    @property
    def settings(self) -> OneLLMConfig:
        return self._settings

    def _headers(self) -> Dict[str, str]:
        if not self._settings.api_key:
            raise RuntimeError("ONELLM_API_KEY 未配置，无法调用 AI 服务")
        return {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
        }

    async def get_balance(self) -> Dict[str, Any]:
        """查询账户余额。"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    self._settings.endpoint("skills/balance"),
                    headers=self._headers(),
                )
            if response.status_code == 200:
                return response.json()
            return {"success": False, "error": response.text}
        except Exception as e:
            logger.exception("get_balance failed")
            return {"success": False, "error": str(e)}

    async def get_models(self, model_type: str = "chat") -> List[Dict[str, Any]]:
        """获取可用模型列表。

        Args:
            model_type: chat | image | video | audio

        Returns:
            模型列表
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    self._settings.endpoint("skills/models"),
                    params={"type": model_type},
                    headers=self._headers(),
                )
            if response.status_code == 200:
                data = response.json()
                return data.get("models", []) if isinstance(data, dict) else []
            logger.warning(
                "get_models returned %s: %s",
                response.status_code,
                response.text[:200],
            )
            return []
        except Exception as e:
            logger.exception("get_models error")
            return []

    async def get_model_pricing(self, model_name: str) -> Dict[str, Any]:
        """获取模型价格信息。"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    self._settings.endpoint(f"skills/models/{model_name}/pricing"),
                    headers=self._headers(),
                )
            if response.status_code == 200:
                return response.json()
            return {"success": False, "error": response.text}
        except Exception as e:
            logger.exception("get_model_pricing error")
            return {"success": False, "error": str(e)}

    async def submit_media_task(
        self,
        model: str,
        prompt: str,
        params: Optional[Dict[str, Any]] = None,
        workspace_id: str = "default",
    ) -> Dict[str, Any]:
        """提交媒体生成任务（图片/视频/音频）。

        Args:
            model: 模型名称，如 'midjourney-v6', 'kling-v1', 'suno-v3'
            prompt: 提示词
            params: 额外参数
            workspace_id: 工作区 ID

        Returns:
            包含 task_id 的字典
        """
        try:
            data: Dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "workspaceId": workspace_id,
            }
            if params:
                data["params"] = params
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._settings.endpoint("media/generate"),
                    headers=self._headers(),
                    json=data,
                )
            if response.status_code == 200:
                return response.json()
            return {
                "success": False,
                "error": f"{response.status_code}: {response.text[:200]}",
            }
        except Exception as e:
            logger.exception("submit_media_task error")
            return {"success": False, "error": str(e)}

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """查询任务状态。

        Args:
            task_id: 任务 ID

        Returns:
            任务状态信息
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    self._settings.endpoint("media/status"),
                    params={"task_id": task_id},
                    headers=self._headers(),
                )
            if response.status_code == 200:
                return response.json()
            return {"success": False, "error": response.text}
        except Exception as e:
            logger.exception("get_task_status error")
            return {"success": False, "error": str(e)}

    async def submit_feedback(
        self,
        feedback_type: str,
        question: str,
        endpoint: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """提交反馈（BUG/建议/疑问）。

        Args:
            feedback_type: 文档疑问 | 接口报错 | 功能建议
            question: 问题描述
            endpoint: 相关接口路径
            context: 操作背景

        Returns:
            反馈提交结果
        """
        try:
            data: Dict[str, Any] = {
                "type": feedback_type,
                "question": question,
            }
            if endpoint:
                data["endpoint"] = endpoint
            if context:
                data["context"] = context
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    self._settings.endpoint("skills/feedback"),
                    headers=self._headers(),
                    json=data,
                )
            if response.status_code == 200:
                return response.json()
            return {
                "success": False,
                "error": f"{response.status_code}: {response.text[:200]}",
            }
        except Exception as e:
            logger.exception("submit_feedback error")
            return {"success": False, "error": str(e)}

    async def generate_content(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生成内容（带重试与指数退避）。

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数
            model: 指定模型，默认使用配置中的 chat_model

        Returns:
            包含生成内容的字典
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model or self._settings.chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        endpoint = self._settings.endpoint("chat/completions")
        last_error: Optional[str] = None

        for attempt in range(self.max_retries):
            logger.info("AI 生成尝试 %d/%d -> %s", attempt + 1, self.max_retries, endpoint)
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        endpoint, headers=self._headers(), json=payload
                    )
            except httpx.HTTPError as e:
                last_error = f"请求异常: {e}"
                logger.warning("AI 生成请求异常: %s", e)
            else:
                if response.status_code == 200:
                    result = response.json()
                    choices = result.get("choices") or []
                    if choices:
                        content = choices[0].get("message", {}).get("content")
                        return {
                            "success": True,
                            "content": content,
                            "model": result.get(
                                "model", model or self._settings.chat_model
                            ),
                            "usage": result.get("usage", {}),
                            "attempts": attempt + 1,
                        }
                    last_error = "AI 返回为空 choices"
                    logger.warning("AI 响应无 choices: %s", str(result)[:300])
                else:
                    last_error = (
                        f"AI服务返回错误: {response.status_code} - {response.text[:200]}"
                    )
                    logger.warning("AI 生成失败: %s", last_error)

            if attempt < self.max_retries - 1:
                wait_time = self.retry_delay * (attempt + 1)
                logger.info("等待 %.1f 秒后重试...", wait_time)
                await asyncio.sleep(wait_time)

        logger.error("AI 生成失败，所有重试均未成功: %s", last_error)
        return {
            "success": False,
            "error": last_error or "AI 服务暂时不可用，请稍后重试",
            "content": None,
        }

    async def generate_content_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """流式生成内容。

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数
            model: 指定模型，默认使用配置中的 chat_model

        Yields:
            生成的内容片段
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model or self._settings.chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        endpoint = self._settings.endpoint("chat/completions")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", endpoint, headers=self._headers(), json=payload
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        logger.warning(
                            "AI 流式响应状态码 %s: %s",
                            response.status_code,
                            body[:200],
                        )
                        yield f"\n[错误: {response.status_code}]"
                        return
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            choices = chunk.get("choices") or []
                            if choices:
                                delta = choices[0].get("delta", {}) or {}
                                if delta.get("content"):
                                    yield delta["content"]
        except Exception as e:
            logger.exception("流式生成失败")
            yield f"\n[错误: {str(e)}]"

    async def generate_geo_article(
        self,
        title: str,
        brand_info: Dict[str, Any],
        keywords: List[str],
        target_platform: str = "chatgpt",
        word_count: int = 2500,
    ) -> Dict[str, Any]:
        """生成 GEO 优化文章。

        Args:
            title: 文章标题
            brand_info: 品牌信息
            keywords: 关键词列表
            target_platform: 目标平台
            word_count: 字数要求

        Returns:
            包含生成文章的字典
        """
        brand_name = brand_info.get("name", "")
        industry = brand_info.get("industry", "")

        system_prompt = """你是一位专业的GEO（生成式引擎优化）内容专家。
你的任务是根据提供的品牌信息和关键词，生成高质量的SEO/GEO优化文章。

文章要求：
1. 符合AI搜索引擎的引用偏好
2. 包含实体、关系和证据（ERE框架）
3. 使用结构化数据标记
4. 包含统计数据和专家引用
5. 使用Markdown格式输出
6. 包含标题、副标题、正文、结论等完整结构
7. 自然融入关键词，避免堆砌
8. 内容原创、有深度、有价值"""

        prompt = f"""请为以下品牌生成一篇GEO优化文章：

【品牌信息】
- 品牌名称: {brand_name}
- 所属行业: {industry}
- 文章标题: {title}

【目标关键词】
{', '.join(keywords)}

【要求】
- 目标平台: {target_platform}
- 字数要求: {word_count}字左右
- 格式: Markdown
- 需要包含：
  1. 吸引人的标题（H1）
  2. 多个小标题（H2/H3）
  3. 正文内容（包含ERE框架：实体、关系、证据）
  4. 关键数据或统计
  5. 专家观点或引用
  6. 行动号召（CTA）
  7. 相关实体链接建议

请直接输出完整的文章内容。"""

        return await self.generate_content(
            prompt, system_prompt, temperature=0.7, max_tokens=word_count * 2
        )

    async def generate_geo_plan(
        self,
        domain: str,
        brand_name: str,
        industry: str,
        keywords: List[str],
        location: str = "",
    ) -> Dict[str, Any]:
        """生成详细的 GEO 优化方案（JSON 输出）。

        Args:
            domain: 网站域名
            brand_name: 品牌名称
            industry: 所属行业
            keywords: 关键词列表
            location: 目标地域

        Returns:
            包含方案内容的字典
        """
        system_prompt = """你是一位资深的GEO（生成式引擎优化）专家，拥有10年以上的SEO和AI优化经验。
你的任务是为客户生成一份专业、详细、可执行的GEO优化方案。

【核心要求】
1. 内容必须具体到可执行层面，每个建议都要有明确的操作步骤
2. 避免使用"完善"、"优化"、"提升"等空泛词汇，要说清楚"做什么"、"怎么做"、"做到什么程度"
3. 所有数据、指标、时间节点都要具体量化
4. 每个平台、每个渠道都要有具体的操作清单
5. 输出格式必须是合法的JSON

【禁止使用的空泛词汇】
- 完善、优化、提升、加强、改进
- 定期、持续、不断、逐步
- 相关、有关、相应、适当
- 高质量、优质、良好

【必须使用的具体表述】
- 具体数字：如"每周发布3篇文章"、"投入5000元/月"
- 明确动作：如"在知乎发布10篇回答"、"修改首页标题为XXX"
- 量化指标：如"AI引用率从5%提升到15%"、"排名进入前3位"
- 时间节点：如"第一周完成"、"每月15号发布"
"""

        prompt = f"""请为以下品牌生成一份详细的GEO优化方案，必须具体到可执行层面：

【品牌信息】
- 品牌名称: {brand_name}
- 网站域名: {domain}
- 所属行业: {industry}
- 目标地域: {location or '全国'}
- 核心关键词: {', '.join(keywords) if keywords else '待分析'}

【输出格式要求】
必须以以下JSON格式输出，每个字段都要有具体的值：

{{
  "brand_positioning": {{
    "brand_name": "品牌名称",
    "industry": "具体行业",
    "target_users": "具体用户画像：25-40岁、月收入1-3万、一二线城市、关注XXX",
    "geo_strategy": "具体策略描述，包含3-5个核心动作"
  }},
  "keyword_matrix": {{
    "core_keywords": ["关键词1", "关键词2", "关键词3"],
    "long_tail_keywords": ["长尾词1", "长尾词2", "长尾词3"],
    "location_keywords": ["地域词1", "地域词2"]
  }},
  "content_strategy": {{
    "content_types": ["博客文章-每周2篇", "知乎回答-每周3个", "小红书笔记-每周5篇"],
    "content_topics": [
      "主题1：XXX（包含具体标题和3个要点）",
      "主题2：XXX（包含具体标题和3个要点）"
    ],
    "distribution_platforms": ["知乎-每周3篇", "公众号-每周2篇", "小红书-每周5篇"]
  }},
  "authority_building": {{
    "official_channels": "官网：修改首页标题为XXX，添加XXX页面；百度百科：创建XXX词条",
    "search_ecosystem": "百度知道：回答10个问题；百度地图：认领并完善商户信息",
    "industry_media": "申请XXX行业协会认证；在XXX媒体发布3篇新闻稿",
    "content_platforms": "知乎：每周回答3个问题；小红书：每周发布5篇笔记"
  }},
  "execution_roadmap": {{
    "month_1": ["第1周：完成XXX", "第2周：完成XXX", "第3周：完成XXX", "第4周：完成XXX"],
    "month_2_3": ["每周发布2篇博客", "每周回答3个知乎问题", "每周发布5篇小红书"],
    "ongoing": ["每月更新10篇旧文章", "每月新增5个FAQ", "每月监测排名变化"]
  }},
  "expected_results": {{
    "ai_citation_rate": "从X%提升到X%（3个月）",
    "local_search_rank": "进入前3位",
    "conversion_rate": "从X%提升到X%",
    "monitoring_period": "每周监测，每月总结"
  }}
}}

【内容要求】
1. 每个字段都要填写具体的内容，不能是空字符串或"待确定"
2. 数字必须具体：如"每周发布3篇文章"而不是"定期发布文章"
3. 动作必须明确：如"在知乎搜索XXX关键词并回答前10个问题"
4. 时间必须具体：如"每周一、三、五各发布1篇"而不是"定期发布"
5. 预算必须量化：如"每月投入5000元用于XXX"
6. 效果必须可衡量：如"3个月内AI引用率从5%提升到15%"

请直接输出JSON格式的完整方案，确保所有字段都有具体的、可执行的值。"""

        return await self.generate_content(
            prompt, system_prompt, temperature=0.7, max_tokens=8000
        )

    async def generate_batch_articles(
        self, tasks: List[Dict[str, Any]]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """批量生成文章。

        Args:
            tasks: 任务列表，每个任务包含 title, brand_info, keywords 等

        Yields:
            每个任务的生成结果
        """
        total = len(tasks)
        for i, task in enumerate(tasks):
            yield {
                "index": i,
                "status": "processing",
                "message": f"正在生成第 {i + 1}/{total} 篇文章...",
            }
            result = await self.generate_geo_article(
                title=task.get("title", ""),
                brand_info=task.get("brand_info", {}),
                keywords=task.get("keywords", []),
                target_platform=task.get("target_platform", "chatgpt"),
                word_count=task.get("word_count", 2500),
            )
            yield {
                "index": i,
                "status": "completed" if result.get("success") else "failed",
                "result": result,
                "task": task,
            }


_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    """获取 AIService 单例。"""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
