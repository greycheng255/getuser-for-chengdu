"""
AI服务调用模块 V2
优化版本：更好的错误处理、重试机制、提示词优化
"""

import os
import requests
import json
import time
from typing import Dict, List, Optional, Generator
from dotenv import load_dotenv
import logging

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIServiceV2:
    """优化的AI服务客户端"""

    def __init__(self):
        self.base_url = 'https://ai.hropenai.cn/'
        self.api_key = 'sk-099e46fe8c0761992b84268f741db298ae44cebe1f216086'
        self.model = 'gpt-4o-mini'
        self.timeout = 120
        self.max_retries = 3
        self.retry_delay = 2

        # 可用的API端点
        self.endpoints = [
            f"{self.base_url}/v1/chat/completions",
            f"{self.base_url}/api/v1/chat/completions",
            f"{self.base_url}/chat/completions",
        ]

        logger.info(f"AI服务初始化完成，Base URL: {self.base_url}")

    def _make_request(self, endpoint: str, payload: Dict, headers: Dict) -> Optional[Dict]:
        """发送请求并处理响应"""
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"请求失败: {endpoint}, 状态码: {response.status_code}")
                return None

        except requests.exceptions.Timeout:
            logger.warning(f"请求超时: {endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"请求异常: {endpoint}, 错误: {str(e)}")
            return None

    def generate_content(self, prompt: str, system_prompt: Optional[str] = None,
                        temperature: float = 0.7, max_tokens: int = 4000) -> Dict:
        """
        生成内容 - 带重试机制

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            包含生成内容的字典
        """
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

        # 重试机制
        for attempt in range(self.max_retries):
            logger.info(f"AI生成尝试 {attempt + 1}/{self.max_retries}")

            for endpoint in self.endpoints:
                result = self._make_request(endpoint, payload, headers)

                if result and 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0]['message']['content']
                    logger.info(f"AI生成成功，使用模型: {result.get('model', self.model)}")
                    return {
                        'success': True,
                        'content': content,
                        'model': result.get('model', self.model),
                        'usage': result.get('usage', {}),
                        'attempts': attempt + 1
                    }

            # 如果所有端点都失败，等待后重试
            if attempt < self.max_retries - 1:
                wait_time = self.retry_delay * (attempt + 1)
                logger.info(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)

        # 所有重试都失败
        logger.error("AI生成失败，所有重试都未成功")
        return {
            'success': False,
            'error': 'AI服务暂时不可用，请稍后重试',
            'content': None
        }

    def generate_content_stream(self, prompt: str, system_prompt: Optional[str] = None,
                               temperature: float = 0.7, max_tokens: int = 4000) -> Generator[str, None, None]:
        """
        流式生成内容

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大token数

        Yields:
            生成的内容片段
        """
        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            }

            endpoint = f"{self.base_url}/v1/chat/completions"

            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                stream=True,
                timeout=self.timeout
            )

            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data)
                            if 'choices' in chunk and len(chunk['choices']) > 0:
                                delta = chunk['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    yield delta['content']
                        except:
                            pass

        except Exception as e:
            logger.error(f"流式生成失败: {str(e)}")
            yield f"\n[错误: {str(e)}]"

    def generate_geo_plan(self, domain: str, brand_name: str, industry: str,
                         keywords: List[str], location: str = '') -> Dict:
        """
        生成详细的GEO优化方案

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

        return self.generate_content(prompt, system_prompt, temperature=0.7, max_tokens=8000)

    def generate_geo_article(self, title: str, brand_info: Dict, keywords: List[str],
                            target_platform: str = 'chatgpt', word_count: int = 2500) -> Dict:
        """
        生成GEO优化文章

        Args:
            title: 文章标题
            brand_info: 品牌信息
            keywords: 关键词列表
            target_platform: 目标平台
            word_count: 字数要求

        Returns:
            包含生成文章的字典
        """
        brand_name = brand_info.get('name', '')
        industry = brand_info.get('industry', '')

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
  4. 关键数据或统计（虚构但合理的数据）
  5. 专家观点或引用
  6. 行动号召（CTA）
  7. 相关实体链接建议

请直接输出完整的文章内容。"""

        return self.generate_content(prompt, system_prompt, temperature=0.7, max_tokens=word_count*2)

    def generate_batch_articles(self, tasks: List[Dict]) -> Generator[Dict, None, None]:
        """
        批量生成文章

        Args:
            tasks: 任务列表，每个任务包含title, brand_info, keywords等

        Yields:
            每个任务的生成结果
        """
        for i, task in enumerate(tasks):
            yield {
                'index': i,
                'status': 'processing',
                'message': f'正在生成第 {i+1}/{len(tasks)} 篇文章...'
            }

            result = self.generate_geo_article(
                title=task.get('title', ''),
                brand_info=task.get('brand_info', {}),
                keywords=task.get('keywords', []),
                target_platform=task.get('target_platform', 'chatgpt'),
                word_count=task.get('word_count', 2500)
            )

            yield {
                'index': i,
                'status': 'completed' if result['success'] else 'failed',
                'result': result,
                'task': task
            }


# 全局AI服务实例
ai_service_v2 = AIServiceV2()
