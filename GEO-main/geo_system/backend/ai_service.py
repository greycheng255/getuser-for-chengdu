"""
AI服务调用模块
调用外部AI服务生成真实内容
"""

import os
import requests
import json
from typing import Dict, List, Optional, Generator
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class AIService:
    """AI服务客户端 - ai.hropenai.cn / api.lk888.ai"""

    def __init__(self):
        # 使用 lk888.ai API 服务
        self.base_url = 'https://api.lk888.ai/api'
        self.api_key = 'sk-099e46fe8c0761992b84268f741db298ae44cebe1f216086'
        self.model = 'gpt-5.4'
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

    def get_balance(self) -> Dict:
        """查询账户余额"""
        try:
            response = requests.get(
                f"{self.base_url}/v1/skills/balance",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return {'success': False, 'error': response.text}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_models(self, model_type: str = 'chat') -> List[Dict]:
        """
        获取可用模型列表

        Args:
            model_type: chat | image | video | audio

        Returns:
            模型列表
        """
        try:
            response = requests.get(
                f"{self.base_url}/v1/skills/models?type={model_type}",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('models', [])
            return []
        except Exception as e:
            print(f"[AI Service] Get models error: {e}")
            return []

    def get_model_pricing(self, model_name: str) -> Dict:
        """获取模型价格信息"""
        try:
            response = requests.get(
                f"{self.base_url}/v1/skills/models/{model_name}/pricing",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return {'success': False, 'error': response.text}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def submit_media_task(self, model: str, prompt: str, params: Dict = None,
                         workspace_id: str = 'default') -> Dict:
        """
        提交媒体生成任务（图片/视频/音频）

        Args:
            model: 模型名称，如 'midjourney-v6', 'kling-v1', 'suno-v3'
            prompt: 提示词
            params: 额外参数
            workspace_id: 工作区ID

        Returns:
            包含task_id的字典
        """
        try:
            data = {
                'model': model,
                'prompt': prompt,
                'workspaceId': workspace_id
            }
            if params:
                data['params'] = params

            response = requests.post(
                f"{self.base_url}/v1/media/generate",
                headers=self.headers,
                json=data,
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {
                    'success': False,
                    'error': f'{response.status_code}: {response.text[:200]}'
                }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_task_status(self, task_id: str) -> Dict:
        """
        查询任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务状态信息
        """
        try:
            response = requests.get(
                f"{self.base_url}/v1/media/status?task_id={task_id}",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return {'success': False, 'error': response.text}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def submit_feedback(self, feedback_type: str, question: str,
                       endpoint: str = None, context: str = None) -> Dict:
        """
        提交反馈（BUG/建议/疑问）

        Args:
            feedback_type: 文档疑问 | 接口报错 | 功能建议
            question: 问题描述
            endpoint: 相关接口路径
            context: 操作背景

        Returns:
            反馈提交结果
        """
        try:
            data = {
                'type': feedback_type,
                'question': question
            }
            if endpoint:
                data['endpoint'] = endpoint
            if context:
                data['context'] = context

            response = requests.post(
                f"{self.base_url}/v1/skills/feedback",
                headers=self.headers,
                json=data,
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                return result
            else:
                return {
                    'success': False,
                    'error': f'{response.status_code}: {response.text[:200]}'
                }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def generate_content(self, prompt: str, system_prompt: Optional[str] = None,
                        temperature: float = 0.7, max_tokens: int = 4000,
                        model: str = None) -> Dict:
        """
        生成内容

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大token数
            model: 指定模型，默认使用 self.model

        Returns:
            包含生成内容的字典
        """
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": model or self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False
            }

            endpoint = f"{self.base_url}/v1/chat/completions"

            print(f"[AI Service] Calling endpoint: {endpoint}")
            response = requests.post(
                endpoint,
                headers=self.headers,
                json=payload,
                timeout=120
            )
            print(f"[AI Service] Response status: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0]['message']['content']
                    return {
                        'success': True,
                        'content': content,
                        'model': result.get('model', model or self.model),
                        'usage': result.get('usage', {})
                    }
            else:
                print(f"[AI Service] Error response: {response.text[:500]}")
                return {
                    'success': False,
                    'error': f'AI服务返回错误: {response.status_code} - {response.text[:200]}',
                    'content': None
                }

        except Exception as e:
            print(f"[AI Service] Exception: {str(e)}")
            return {
                'success': False,
                'error': f'AI服务调用异常: {str(e)}',
                'content': None
            }

    def generate_content_stream(self, prompt: str, system_prompt: Optional[str] = None,
                               temperature: float = 0.7, max_tokens: int = 4000,
                               model: str = None) -> Generator[str, None, None]:
        """
        流式生成内容

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大token数
            model: 指定模型，默认使用 self.model

        Yields:
            生成的内容片段
        """
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": model or self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            }

            endpoint = f"{self.base_url}/v1/chat/completions"

            response = requests.post(
                endpoint,
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=120
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
            yield f"\n[错误: {str(e)}]"

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
文章应该：
1. 符合AI搜索引擎的引用偏好
2. 包含实体、关系和证据（ERE框架）
3. 使用结构化数据标记
4. 包含统计数据和专家引用
5. 使用Markdown格式输出
6. 包含标题、副标题、正文、结论等完整结构"""

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
  3. 正文内容
  4. 关键数据或统计
  5. 专家观点或引用
  6. 行动号召（CTA）

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
ai_service = AIService()
