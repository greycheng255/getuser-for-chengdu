"""
AI任务管理器
管理从优化方案到AI内容生产的整个流程
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
import json
import uuid

from platform_content_adapter import platform_adapter, PlatformType
from xiaohongshu_content_strategy import content_strategy


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"           # 待处理
    ANALYZING = "analyzing"       # 分析中
    GENERATING = "generating"     # 生成中
    REVIEWING = "reviewing"       # 审核中
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"             # 失败


class TaskType(Enum):
    """任务类型"""
    ARTICLE = "article"           # 文章生成
    LANDING_PAGE = "landing_page" # 落地页
    FAQ = "faq"                   # FAQ生成
    SCHEMA = "schema"             # Schema标记
    SOCIAL = "social"             # 社交媒体内容
    XIAOHONGSHU = "xiaohongshu"   # 小红书内容
    DOUYIN = "douyin"             # 抖音内容
    ZHIHU = "zhihu"               # 知乎内容
    WEIBO = "weibo"               # 微博内容
    WECHAT = "wechat"             # 微信公众号
    BILIBILI = "bilibili"         # B站内容
    KUAISHOU = "kuaishou"         # 快手内容
    TOUTIAO = "toutiao"           # 今日头条


@dataclass
class AITask:
    """AI任务"""
    id: int
    user_id: int
    plan_id: int
    task_type: str
    status: str
    title: str
    description: str
    input_data: Dict
    output_data: Optional[Dict] = None
    result_content: Optional[str] = None
    keywords: Optional[List[str]] = None
    created_at: str = None
    updated_at: str = None
    completed_at: str = None
    error_message: str = None


class AITaskManager:
    """
    AI任务管理器
    
    将优化方案转换为可执行的AI内容生产任务
    """
    
    def __init__(self):
        self._tasks = {}  # 内存中的任务缓存
    
    def get_task(self, task_id: int) -> Optional[AITask]:
        """获取单个任务 - 只从PostgreSQL读取"""
        # 先从内存缓存查找
        if task_id in self._tasks:
            return self._tasks[task_id]
        
        # 从PostgreSQL查找
        try:
            from postgresql_database import PostgreSQLDatabase
            pg_db = PostgreSQLDatabase()
            with pg_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, user_id, plan_id, task_type, status, title, description,
                           input_data, output_data, result_content, keywords,
                           created_at, updated_at, completed_at, error_message
                    FROM ai_tasks WHERE id = %s
                ''', (task_id,))
                row = cursor.fetchone()
                if row:
                    task = self._row_to_task(row)
                    self._tasks[task_id] = task
                    return task
        except Exception as e:
            print(f"从PostgreSQL查找任务失败: {e}")
        
        return None
    
    def get_tasks(self, user_id: int = None, status: str = None, 
                  limit: int = 50) -> List[AITask]:
        """获取任务列表 - 只从PostgreSQL读取"""
        try:
            from postgresql_database import PostgreSQLDatabase
            pg_db = PostgreSQLDatabase()
            with pg_db.get_connection() as conn:
                cursor = conn.cursor()
                
                query = '''
                    SELECT id, user_id, plan_id, task_type, status, title, description,
                           input_data, output_data, result_content, keywords,
                           created_at, updated_at, completed_at, error_message
                    FROM ai_tasks WHERE 1=1
                '''
                params = []
                
                if user_id:
                    query += " AND user_id = %s"
                    params.append(user_id)
                if status:
                    query += " AND status = %s"
                    params.append(status)
                
                query += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                return [self._row_to_task(row) for row in rows]
        except Exception as e:
            print(f"从PostgreSQL获取任务列表失败: {e}")
            return []
    
    def create_task(self, task_data: Dict) -> AITask:
        """创建新任务 - 只存到PostgreSQL"""
        try:
            from postgresql_database import PostgreSQLDatabase
            pg_db = PostgreSQLDatabase()
            with pg_db.get_connection() as conn:
                cursor = conn.cursor()
                
                now = datetime.now().isoformat()
                
                cursor.execute('''
                    INSERT INTO ai_tasks
                    (user_id, plan_id, task_type, status, title, description,
                     input_data, output_data, keywords, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    task_data.get('user_id', 1),
                    task_data.get('plan_id'),
                    task_data.get('task_type', 'article'),
                    task_data.get('status', 'pending'),
                    task_data.get('title', ''),
                    task_data.get('description', ''),
                    json.dumps(task_data.get('input_data', {}), ensure_ascii=False),
                    json.dumps(task_data.get('output_data', {}), ensure_ascii=False),
                    json.dumps(task_data.get('keywords', []), ensure_ascii=False),
                    now,
                    now
                ))
                
                task_id = cursor.fetchone()[0]
                
                task = self.get_task(task_id)
                if task:
                    self._tasks[task_id] = task
                return task
        except Exception as e:
            print(f"PostgreSQL创建任务失败: {e}")
            return None
    
    def update_task(self, task_id: int, updates: Dict) -> Optional[AITask]:
        """更新任务 - 只使用PostgreSQL"""
        allowed_fields = ['status', 'output_data', 'result_content',
                         'error_message', 'completed_at']

        try:
            from postgresql_database import PostgreSQLDatabase
            pg_db = PostgreSQLDatabase()
            with pg_db.get_connection() as conn:
                cursor = conn.cursor()

                set_clauses = []
                params = []

                for field in allowed_fields:
                    if field in updates:
                        set_clauses.append(f"{field} = %s")
                        if field in ['output_data', 'keywords']:
                            params.append(json.dumps(updates[field], ensure_ascii=False))
                        else:
                            params.append(updates[field])

                if set_clauses:
                    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
                    params.append(task_id)

                    cursor.execute(f'''
                        UPDATE ai_tasks SET {', '.join(set_clauses)}
                        WHERE id = %s
                    ''', params)

                # 清除缓存
                if task_id in self._tasks:
                    del self._tasks[task_id]

                return self.get_task(task_id)
        except Exception as e:
            print(f"更新PostgreSQL任务失败: {e}")
            return None
    
    def delete_task(self, task_id: int) -> bool:
        """删除任务 - 只使用PostgreSQL"""
        try:
            from postgresql_database import PostgreSQLDatabase
            pg_db = PostgreSQLDatabase()
            with pg_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM ai_tasks WHERE id = %s', (task_id,))
                
                if task_id in self._tasks:
                    del self._tasks[task_id]
                
                return True
        except Exception as e:
            print(f"PostgreSQL删除任务失败: {e}")
            return False
    
    def _row_to_task(self, row) -> AITask:
        """将PostgreSQL数据库行转换为AITask对象"""
        return AITask(
            id=row[0],
            user_id=row[1],
            plan_id=row[2] or 0,
            task_type=row[3],
            status=row[4],
            title=row[5],
            description=row[6] or '',
            input_data=json.loads(row[7]) if row[7] else {},
            output_data=json.loads(row[8]) if row[8] else None,
            result_content=row[9],
            keywords=json.loads(row[10]) if row[10] else [],
            created_at=row[11].isoformat() if row[11] else None,
            updated_at=row[12].isoformat() if row[12] else None,
            completed_at=row[13].isoformat() if row[13] else None,
            error_message=row[14]
        )
    
    def create_tasks_from_plan(self, plan_data: Dict, user_id: int) -> List[Dict]:
        """
        从优化方案创建AI任务列表
        
        Args:
            plan_data: 优化方案数据
            user_id: 用户ID
            
        Returns:
            任务列表
        """
        plan_id = plan_data.get('id')
        domain = plan_data.get('domain', '')
        brand_name = plan_data.get('brand_name', '')
        industry = plan_data.get('industry', '')
        plan_content = plan_data.get('plan_data', {})
        
        tasks = []
        
        # 1. 创建品牌文章任务
        if plan_content.get('brand_positioning'):
            tasks.append({
                'user_id': user_id,
                'plan_id': plan_id,
                'task_type': TaskType.ARTICLE.value,
                'status': TaskStatus.PENDING.value,
                'title': f'{brand_name} 品牌GEO优化文章',
                'description': f'基于品牌定位分析，生成符合GEO标准的品牌介绍文章',
                'input_data': {
                    'domain': domain,
                    'brand_name': brand_name,
                    'industry': industry,
                    'keywords': plan_data.get('keywords', []),
                    'brand_positioning': plan_content.get('brand_positioning', {}),
                    'target_word_count': 2500,
                    'tone': 'professional',
                    'target_platform': 'chatgpt'
                }
            })
        
        # 2. 创建关键词文章任务
        keyword_matrix = plan_content.get('keyword_matrix', {})
        core_keywords = keyword_matrix.get('core_keywords', [])
        
        for i, keyword in enumerate(core_keywords[:3]):  # 为核心关键词生成小红书内容
            tasks.append({
                'user_id': user_id,
                'plan_id': plan_id,
                'task_type': TaskType.XIAOHONGSHU.value,  # 小红书类型
                'status': TaskStatus.PENDING.value,
                'title': f'{keyword} 小红书种草笔记',
                'description': f'针对关键词"{keyword}"生成小红书风格的种草内容',
                'input_data': {
                    'domain': domain,
                    'brand_name': brand_name,
                    'industry': industry,
                    'target_keyword': keyword,
                    'related_keywords': core_keywords,
                    'target_word_count': 800,  # 小红书适合800字左右
                    'tone': 'casual',  # 小红书用 casual 语气
                    'platform': 'xiaohongshu',
                    'include_hashtags': True,  # 包含话题标签
                    'include_emojis': True,    # 包含表情符号
                    'style': '种草',  # 种草风格
                    'content_type': '种草笔记',
                    'target_audience': '年轻女性用户',
                    'call_to_action': '引导用户咨询或购买'
                }
            })
        
        # 3. 创建FAQ任务
        if plan_content.get('content_strategy'):
            tasks.append({
                'user_id': user_id,
                'plan_id': plan_id,
                'task_type': TaskType.FAQ.value,
                'status': TaskStatus.PENDING.value,
                'title': f'{brand_name} FAQ问答生成',
                'description': '基于用户搜索意图生成FAQ问答内容',
                'input_data': {
                    'domain': domain,
                    'brand_name': brand_name,
                    'industry': industry,
                    'keywords': plan_data.get('keywords', []),
                    'content_strategy': plan_content.get('content_strategy', {}),
                    'faq_count': 10
                }
            })
        
        # 4. 创建Schema标记任务
        tasks.append({
            'user_id': user_id,
            'plan_id': plan_id,
            'task_type': TaskType.SCHEMA.value,
            'status': TaskStatus.PENDING.value,
            'title': f'{brand_name} Schema结构化数据',
            'description': '生成符合GEO标准的Schema.org结构化数据',
            'input_data': {
                'domain': domain,
                'brand_name': brand_name,
                'industry': industry,
                'schema_types': ['Organization', 'WebSite', 'LocalBusiness', 'FAQPage']
            }
        })
        
        # 5. 创建落地页任务
        if plan_content.get('technical_optimization'):
            tasks.append({
                'user_id': user_id,
                'plan_id': plan_id,
                'task_type': TaskType.LANDING_PAGE.value,
                'status': TaskStatus.PENDING.value,
                'title': f'{brand_name} GEO优化落地页',
                'description': '生成高转化率的GEO优化落地页内容',
                'input_data': {
                    'domain': domain,
                    'brand_name': brand_name,
                    'industry': industry,
                    'keywords': plan_data.get('keywords', []),
                    'technical_optimization': plan_content.get('technical_optimization', {}),
                    'cta_sections': ['hero', 'features', 'testimonials', 'faq', 'contact']
                }
            })
        
        # 6. 创建小红书任务
        tasks.append({
            'user_id': user_id,
            'plan_id': plan_id,
            'task_type': TaskType.XIAOHONGSHU.value,
            'status': TaskStatus.PENDING.value,
            'title': f'{brand_name} 小红书内容生成',
            'description': f'为小红书平台生成符合平台调性的种草内容，推广{brand_name}',
            'input_data': {
                'domain': domain,
                'brand_name': brand_name,
                'industry': industry,
                'keywords': plan_data.get('keywords', []),
                'target_keyword': plan_data.get('keywords', [''])[0] if plan_data.get('keywords') else '',
                'platform': 'xiaohongshu',
                'platform_config': {
                    'name': '小红书',
                    'content_type': 'note',
                    'max_title_length': 20,
                    'max_content_length': 1000,
                    'max_images': 9,
                    'tone_style': '真实、亲切、分享式',
                    'hashtag_style': '简洁实用'
                }
            }
        })
        
        return tasks
    
    def generate_content_prompt(self, task: Dict) -> str:
        """
        生成AI内容生产提示词
        
        Args:
            task: 任务数据
            
        Returns:
            AI提示词
        """
        task_type = task.get('task_type')
        input_data = task.get('input_data', {})
        
        # 平台特定任务类型
        platform_types = [
            TaskType.XIAOHONGSHU.value,
            TaskType.DOUYIN.value,
            TaskType.ZHIHU.value,
            TaskType.WEIBO.value,
            TaskType.WECHAT.value,
            TaskType.BILIBILI.value,
            TaskType.KUAISHOU.value,
            TaskType.TOUTIAO.value
        ]
        
        if task_type == TaskType.ARTICLE.value:
            return self._generate_article_prompt(input_data)
        elif task_type == TaskType.FAQ.value:
            return self._generate_faq_prompt(input_data)
        elif task_type == TaskType.SCHEMA.value:
            return self._generate_schema_prompt(input_data)
        elif task_type == TaskType.LANDING_PAGE.value:
            return self._generate_landing_page_prompt(input_data)
        elif task_type in platform_types:
            # 平台特定内容生成
            return self._generate_platform_prompt(task_type, input_data)
        else:
            return "未知任务类型"
    
    def _generate_article_prompt(self, input_data: Dict) -> str:
        """生成文章提示词"""
        brand_name = input_data.get('brand_name', '')
        industry = input_data.get('industry', '')
        target_keyword = input_data.get('target_keyword', '')
        keywords = input_data.get('keywords', [])
        word_count = input_data.get('target_word_count', 2500)
        
        prompt = f"""# GEO内容生成任务

## 品牌信息
- 品牌名称：{brand_name}
- 行业：{industry}
- 目标关键词：{target_keyword}
- 相关关键词：{', '.join(keywords[:5])}

## 任务要求
请生成一篇符合GEO（生成引擎优化）标准的文章，要求：

### 1. ERE框架要求
- **实体（Entity）**：清晰定义文章涉及的核心实体（品牌、产品、概念）
- **关系（Relation）**：建立实体之间的逻辑关系
- **证据（Evidence）**：提供数据、案例、专家观点作为支撑

### 2. 内容规范
- 字数：{word_count}字左右
- 结构：使用清晰的标题层级（H1、H2、H3）
- 段落：每段不超过150字
- 格式：使用列表、表格、引用等丰富格式

### 3. AI引用优化
- 包含3-5个权威数据或统计
- 引用2-3个行业专家观点
- 提供5个以上权威来源链接
- 使用结构化数据标记关键信息

### 4. 输出格式
请按以下结构输出：
1. 文章标题
2. 文章摘要（150字内）
3. 正文内容（分章节）
4. 关键数据清单
5. 引用来源列表
6. 建议的Schema标记

请开始生成内容："""
        
        return prompt
    
    def _generate_faq_prompt(self, input_data: Dict) -> str:
        """生成FAQ提示词"""
        brand_name = input_data.get('brand_name', '')
        industry = input_data.get('industry', '')
        keywords = input_data.get('keywords', [])
        faq_count = input_data.get('faq_count', 10)
        
        prompt = f"""# FAQ问答生成任务

## 品牌信息
- 品牌名称：{brand_name}
- 行业：{industry}
- 核心关键词：{', '.join(keywords[:5])}

## 任务要求
请生成{faq_count}个符合GEO标准的FAQ问答对，要求：

### 1. 问题设计原则
- 基于真实用户搜索意图
- 覆盖产品、服务、行业知识
- 包含长尾关键词
- 问题简洁明了（不超过20字）

### 2. 回答规范
- 直接回答，首句给出核心答案
- 补充详细解释和背景
- 包含具体数据或案例
- 适当提及品牌优势
- 每个回答200-300字

### 3. 格式要求
使用JSON格式输出：
{{
  "faqs": [
    {{
      "question": "问题文本",
      "answer": "回答内容",
      "category": "分类",
      "keywords": ["关键词1", "关键词2"]
    }}
  ]
}}

请生成FAQ内容："""
        
        return prompt
    
    def _generate_schema_prompt(self, input_data: Dict) -> str:
        """生成Schema提示词"""
        brand_name = input_data.get('brand_name', '')
        domain = input_data.get('domain', '')
        industry = input_data.get('industry', '')
        
        prompt = f"""# Schema结构化数据生成任务

## 品牌信息
- 品牌名称：{brand_name}
- 网站域名：{domain}
- 行业：{industry}

## 任务要求
请生成完整的Schema.org结构化数据，包括：

### 1. Organization Schema
- 品牌基本信息
- 联系方式
- 社交媒体链接
- Logo和图片

### 2. WebSite Schema
- 网站搜索功能
- 网站名称和URL

### 3. LocalBusiness Schema
- 本地业务信息
- 营业时间
- 地理位置
- 服务项目

### 4. FAQPage Schema
- 配合FAQ内容
- 问答结构化标记

### 输出格式
提供JSON-LD格式的代码，可以直接嵌入网页<head>中。

请生成Schema代码："""
        
        return prompt
    
    def _generate_landing_page_prompt(self, input_data: Dict) -> str:
        """生成落地页提示词"""
        brand_name = input_data.get('brand_name', '')
        industry = input_data.get('industry', '')
        keywords = input_data.get('keywords', [])
        
        prompt = f"""# GEO优化落地页生成任务

## 品牌信息
- 品牌名称：{brand_name}
- 行业：{industry}
- 核心关键词：{', '.join(keywords[:3])}

## 任务要求
请生成高转化率的GEO优化落地页内容，包括：

### 1. Hero区域
- 主标题：包含核心关键词，突出价值主张
- 副标题：补充说明，激发兴趣
- CTA按钮：行动导向的文案

### 2. 产品/服务特色
- 3-4个核心卖点
- 每个卖点配简短说明
- 使用图标或数字增强可视化

### 3. 社会证明
- 客户评价/案例
- 数据成果展示
- 权威认证或媒体报道

### 4. FAQ区域
- 5个常见问题的简洁回答

### 5. 最终CTA
- 紧迫感营造
- 再次强调价值
- 联系方式

### 6. GEO优化要求
- 所有标题包含关键词
- 使用结构化标题层级
- 段落简短易读
- 包含内部链接建议

请按以上结构生成落地页内容："""
        
        return prompt
    
    def _generate_platform_prompt(self, platform: str, input_data: Dict) -> str:
        """生成平台特定内容提示词"""
        brand_name = input_data.get('brand_name', '')
        industry = input_data.get('industry', '')
        keywords = input_data.get('keywords', [])
        original_content = input_data.get('original_content', '')
        target_keyword = input_data.get('target_keyword', '')
        
        # 小红书使用专门的内容策略
        if platform == 'xiaohongshu':
            try:
                brand_info = {
                    "style": "简约自然",
                    "features": ["原木", "温馨", "实用"],
                    "website": input_data.get('domain', 'www.zhiranhome.com')
                }
                
                # 使用内容策略生成真实分享内容
                generated = content_strategy.generate_content(brand_info, keywords or [target_keyword])
                
                # 构建包含生成内容的提示词
                prompt = f"""# 小红书内容生成任务

## 品牌信息
- 品牌名称：{brand_name}
- 行业：{industry}
- 网站：{input_data.get('domain', '')}

## 生成的内容框架

### 标题
{generated['title']}

### 内容主题
{generated['theme']}

### 参考内容结构
{generated['content']}

### 建议标签
{' '.join([f'#{tag}#' for tag in generated['hashtags']])}

### 图片建议
{chr(10).join(['- ' + prompt for prompt in generated['image_prompts']])}

## 任务要求
请基于以上内容框架，生成一篇真实、自然的小红书笔记：

### 内容规范
1. **真实分享感**：像朋友间聊天，避免营销感
2. **具体细节**：提供真实的使用场景和体验
3. **避免硬广**：不要直接放网址、联系方式、价格
4. **个人化**：加入个人经历和感受
5. **价值输出**：让读者获得实用信息或情感共鸣

### 格式要求
- 标题：20字以内，真实吸引人
- 正文：500-800字，分段清晰
- 标签：3-5个相关标签
- 语气：亲切、真实、像朋友分享

### 禁止内容
- 绝对化用语（最好、第一、顶级等）
- 诱导性用语（不看后悔、必买等）
- 夸张宣传（逆天、封神、yyds等）
- 直接营销（代购、微商、代理等）

请生成最终的小红书笔记内容："""
                
                return prompt
            except Exception as e:
                print(f"小红书内容策略生成失败，使用默认适配: {str(e)}")
        
        # 其他平台使用平台适配器
        adapted = platform_adapter.adapt_content(
            original_content=original_content or f"为{brand_name}生成{industry}相关内容",
            platform=platform,
            keywords=keywords or [target_keyword]
        )
        
        return adapted.get('adaptation_prompt', '请生成平台内容')
    
    def create_platform_tasks(self, plan_data: Dict, user_id: int, 
                             platforms: List[str]) -> List[Dict]:
        """
        为多个平台创建内容生成任务
        
        Args:
            plan_data: 优化方案数据
            user_id: 用户ID
            platforms: 目标平台列表
            
        Returns:
            任务列表
        """
        plan_id = plan_data.get('id')
        domain = plan_data.get('domain', '')
        brand_name = plan_data.get('brand_name', '')
        industry = plan_data.get('industry', '')
        keywords = plan_data.get('keywords', [])
        
        tasks = []
        
        for platform in platforms:
            try:
                platform_enum = PlatformType(platform.lower())
                config = platform_adapter.get_platform_config(platform)
                
                tasks.append({
                    'user_id': user_id,
                    'plan_id': plan_id,
                    'task_type': platform_enum.value,
                    'status': TaskStatus.PENDING.value,
                    'title': f'{brand_name} {config.name_cn}内容生成',
                    'description': f'为{config.name_cn}平台生成符合平台调性的{config.content_type}内容',
                    'input_data': {
                        'domain': domain,
                        'brand_name': brand_name,
                        'industry': industry,
                        'keywords': keywords,
                        'target_keyword': keywords[0] if keywords else '',
                        'platform': platform,
                        'platform_config': {
                            'name': config.name_cn,
                            'content_type': config.content_type,
                            'max_title_length': config.max_title_length,
                            'max_content_length': config.max_content_length,
                            'max_images': config.max_images,
                            'tone_style': config.tone_style,
                            'hashtag_style': config.hashtag_style
                        }
                    }
                })
            except Exception as e:
                print(f"创建平台任务失败 {platform}: {str(e)}")
        
        return tasks


    def execute_xiaohongshu_task(self, task_id: int, user_id: int = None) -> Dict:
        """
        执行小红书任务：生成内容并自动发布
        
        Args:
            task_id: 任务ID
            user_id: 用户ID
            
        Returns:
            执行结果
        """
        try:
            # 获取任务
            task = self.get_task(task_id)
            if not task:
                return {'success': False, 'error': '任务不存在'}
            
            # 如果任务已完成且已有output_data，直接使用已有内容发布（两步操作：先执行，再发布）
            if task.status == TaskStatus.COMPLETED.value and task.output_data:
                output = task.output_data
                xhs_title = output.get('title', task.title[:20])
                xhs_content = output.get('content', '')
                xhs_keywords = output.get('keywords', [])
                brand_name = task.input_data.get('brand_name', '')
                domain = task.input_data.get('domain', '')
                print(f"✅ 任务已完成，使用已有内容发布: {xhs_title}")
            else:
                # 任务未完成，提示用户先执行任务
                return {
                    'success': False,
                    'error': '任务尚未完成，请先点击"开始生成"执行任务',
                    'task_status': task.status
                }
            
            # 自动发布到小红书
            try:
                from xiaohongshu_automation import auto_publish_to_xiaohongshu
                
                # 获取平台账号 - 使用任务所属用户的账号
                from platform_account_postgres import PlatformAccountServicePostgres
                from postgresql_database import PG_CONFIG
                
                platform_service = PlatformAccountServicePostgres()
                # 优先使用任务所属用户的账号
                account_user_id = task.user_id
                account = platform_service.get_account(account_user_id, 'xiaohongshu')
                
                # 如果没有找到，尝试当前用户
                if not account and user_id and user_id != account_user_id:
                    account = platform_service.get_account(user_id, 'xiaohongshu')
                
                if not account:
                    return {
                        'success': False,
                        'error': '未配置小红书账号',
                        'task_id': task_id,
                        'content': {
                            'title': xhs_title,
                            'content': xhs_content,
                            'keywords': xhs_keywords
                        }
                    }
                
                # 生成图片 - 使用AI文生图生成高质量配图，并持久化保存到本地
                image_paths = []
                try:
                    from image_generation_service import image_service
                    import os

                    # 使用AI生成小红书配图（基于真实文案+品牌信息）
                    generated_images = image_service.generate_xiaohongshu_images(
                        title=xhs_title,
                        content=xhs_content,
                        keywords=xhs_keywords,
                        count=3,
                        brand_name=brand_name
                    )

                    if generated_images:
                        for idx, img_base64 in enumerate(generated_images):
                            # 持久化保存到 /app/data/generated_images/xiaohongshu/
                            local_path = image_service.save_base64_to_local(
                                img_base64,
                                brand_name=brand_name,
                                task_id=task_id,
                                index=idx,
                                subdir='xiaohongshu'
                            )
                            if local_path:
                                image_paths.append(local_path)
                                print(f"✅ AI图片{idx+1}已保存到本地: {local_path}")
                        print(f"✅ 共生成 {len(image_paths)} 张AI图片")
                    else:
                        print("⚠️ AI图片生成失败，将尝试无图发布")
                except Exception as e:
                    print(f"⚠️ AI图片生成出错: {str(e)}")

                # 发布到小红书（使用本地图片路径上传）
                result = auto_publish_to_xiaohongshu(
                    title=xhs_title,
                    content=xhs_content,
                    cookies=account.get('cookies', ''),
                    keywords=xhs_keywords,
                    images=image_paths if image_paths else None
                )

                # 注意：不再删除本地图片，便于后续查看、复用和审计
                # 如需清理可手动删除 /app/data/generated_images/xiaohongshu/ 下的文件

                if result.get('success'):
                    # 更新任务状态为已完成，并记录本地图片路径
                    self.update_task(task_id, {
                        'status': TaskStatus.COMPLETED.value,
                        'completed_at': datetime.now().isoformat(),
                        'output_data': {
                            'title': xhs_title,
                            'content': xhs_content,
                            'keywords': xhs_keywords,
                            'platform': 'xiaohongshu',
                            'local_images': image_paths,  # 保存本地图片路径
                            'publish_result': result
                        }
                    })
                    
                    return {
                        'success': True,
                        'task_id': task_id,
                        'message': '小红书笔记发布成功',
                        'note_url': result.get('note_url'),
                        'title': xhs_title
                    }
                else:
                    # 发布失败，更新任务状态
                    self.update_task(task_id, {
                        'status': TaskStatus.FAILED.value,
                        'error_message': result.get('error', '发布失败'),
                        'output_data': {
                            'title': xhs_title,
                            'content': xhs_content,
                            'keywords': xhs_keywords,
                            'platform': 'xiaohongshu',
                            'publish_result': result
                        }
                    })
                    
                    return {
                        'success': False,
                        'task_id': task_id,
                        'error': result.get('error', '发布失败'),
                        'content': {
                            'title': xhs_title,
                            'content': xhs_content,
                            'keywords': xhs_keywords
                        }
                    }
                    
            except ImportError as ie:
                print(f"Playwright未安装: {str(ie)}")
                return {
                    'success': False,
                    'error': '自动发布需要安装Playwright',
                    'task_id': task_id,
                    'content': {
                        'title': xhs_title,
                        'content': xhs_content,
                        'keywords': xhs_keywords
                    }
                }
            except Exception as e:
                print(f"自动发布失败: {str(e)}")
                return {
                    'success': False,
                    'error': f'自动发布失败: {str(e)}',
                    'task_id': task_id,
                    'content': {
                        'title': xhs_title,
                        'content': xhs_content,
                        'keywords': xhs_keywords
                    }
                }
                
        except Exception as e:
            print(f"执行任务失败: {str(e)}")
            return {
                'success': False,
                'error': f'执行任务失败: {str(e)}',
                'task_id': task_id
            }


# 全局任务管理器实例
ai_task_manager = AITaskManager()
