# -*- coding: utf-8 -*-
"""
AI 任务管理器

迁移自 GEO-main geo_system/backend/ai_task_manager.py，适配 MediaCrawler：
1. 数据库层适配：原使用 GEO-main 的 PostgreSQLDatabase（psycopg2 同步），现改为
   MediaCrawler 的 database.db_session.get_async_engine + SQLAlchemy text() 异步执行。
2. 配置适配：敏感信息与可调参数通过环境变量读取，禁止硬编码。
3. 日志适配：print 全部替换为 logging。
4. 保留原业务逻辑：任务创建、状态管理、提示词生成、小红书发布执行等。
5. 新增 ensure_table() 方法，使用 CREATE TABLE IF NOT EXISTS 建表。

对应 PRD：AI 内容生产任务管理模块（优化方案 -> AI 任务 -> 内容生成 -> 发布）。

适配点说明：
- platform_content_adapter / xiaohongshu_content_strategy 为 GEO-main 专有模块，
  此处改为惰性导入（try/except），缺失时降级为默认提示词，不阻断主流程。
- execute_xiaohongshu_task 依赖的 xiaohongshu_automation / image_generation_service /
  platform_account_postgres 同样惰性导入，缺失时返回明确错误。
"""

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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

    将优化方案转换为可执行的AI内容生产任务，基于 PostgreSQL 异步持久化。
    """

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    # 建表 DDL（PostgreSQL）
    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS ai_tasks (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            plan_id INTEGER,
            task_type VARCHAR(32) NOT NULL,
            status VARCHAR(16) DEFAULT 'pending',
            title VARCHAR(256) NOT NULL,
            description TEXT,
            input_data TEXT,
            output_data TEXT,
            result_content TEXT,
            keywords TEXT,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP
        )
    """

    _CREATE_INDEX_SQL_LIST = [
        "CREATE INDEX IF NOT EXISTS idx_ai_tasks_user ON ai_tasks(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_tasks_status ON ai_tasks(status)",
        "CREATE INDEX IF NOT EXISTS idx_ai_tasks_plan ON ai_tasks(plan_id)",
    ]

    # 查询字段列表（与 _row_to_task 索引一一对应）
    _SELECT_COLUMNS = (
        "id, user_id, plan_id, task_type, status, title, description, "
        "input_data, output_data, result_content, keywords, "
        "created_at, updated_at, completed_at, error_message"
    )

    def __init__(self):
        self._tasks: Dict[int, AITask] = {}  # 内存中的任务缓存
        self._table_ready = False

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """确保 ai_tasks 表存在（幂等，使用 CREATE TABLE IF NOT EXISTS）"""
        if AITaskManager._ensured:
            return
        if self._table_ready:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                logger.warning("[AITaskManager] 数据库引擎不可用，跳过建表")
                return
            async with engine.begin() as conn:
                await conn.execute(sql_text(self._CREATE_TABLE_SQL))
                for index_sql in self._CREATE_INDEX_SQL_LIST:
                    await conn.execute(sql_text(index_sql))
            self._table_ready = True
            AITaskManager._ensured = True
            logger.info("[AITaskManager] ai_tasks 表已就绪")
        except Exception as e:
            logger.error(f"[AITaskManager] 建表失败: {e}")

    async def get_task(self, task_id: int) -> Optional[AITask]:
        """获取单个任务 - 从 PostgreSQL 读取（带内存缓存）"""
        # 先从内存缓存查找
        if task_id in self._tasks:
            return self._tasks[task_id]

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                logger.warning("[AITaskManager] 数据库引擎不可用")
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(f"SELECT {self._SELECT_COLUMNS} FROM ai_tasks WHERE id = :tid"),
                    {"tid": task_id},
                )
                row = rows.fetchone()
                if row:
                    task = self._row_to_task(row)
                    self._tasks[task_id] = task
                    return task
        except Exception as e:
            logger.error(f"[AITaskManager] 从 PostgreSQL 查找任务失败: {e}")

        return None

    async def get_tasks(
        self,
        user_id: int = None,
        status: str = None,
        limit: int = 50,
    ) -> List[AITask]:
        """获取任务列表 - 从 PostgreSQL 读取"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                logger.warning("[AITaskManager] 数据库引擎不可用")
                return []

            query = f"SELECT {self._SELECT_COLUMNS} FROM ai_tasks WHERE 1=1"
            params: Dict[str, Any] = {}

            if user_id:
                query += " AND user_id = :uid"
                params["uid"] = user_id
            if status:
                query += " AND status = :st"
                params["st"] = status

            query += " ORDER BY created_at DESC LIMIT :lim"
            params["lim"] = limit

            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(query), params)
                return [self._row_to_task(row) for row in rows.fetchall()]
        except Exception as e:
            logger.error(f"[AITaskManager] 从 PostgreSQL 获取任务列表失败: {e}")
            return []

    async def create_task(self, task_data: Dict) -> Optional[AITask]:
        """创建新任务 - 存到 PostgreSQL"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                logger.warning("[AITaskManager] 数据库引擎不可用")
                return None

            now = datetime.now().isoformat()

            async with engine.begin() as conn:
                rows = await conn.execute(
                    sql_text(
                        "INSERT INTO ai_tasks "
                        "(user_id, plan_id, task_type, status, title, description, "
                        " input_data, output_data, keywords, created_at, updated_at) "
                        "VALUES (:uid, :pid, :tt, :st, :ti, :ds, :id, :od, :kw, :ca, :ua) "
                        "RETURNING id"
                    ),
                    {
                        "uid": task_data.get("user_id", 1),
                        "pid": task_data.get("plan_id"),
                        "tt": task_data.get("task_type", "article"),
                        "st": task_data.get("status", "pending"),
                        "ti": task_data.get("title", ""),
                        "ds": task_data.get("description", ""),
                        "id": json.dumps(task_data.get("input_data", {}), ensure_ascii=False),
                        "od": json.dumps(task_data.get("output_data", {}), ensure_ascii=False),
                        "kw": json.dumps(task_data.get("keywords", []), ensure_ascii=False),
                        "ca": now,
                        "ua": now,
                    },
                )
                task_id = rows.scalar()

            task = await self.get_task(task_id)
            if task:
                self._tasks[task_id] = task
            return task
        except Exception as e:
            logger.error(f"[AITaskManager] PostgreSQL 创建任务失败: {e}")
            return None

    async def update_task(self, task_id: int, updates: Dict) -> Optional[AITask]:
        """更新任务 - 使用 PostgreSQL"""
        allowed_fields = ["status", "output_data", "result_content",
                          "error_message", "completed_at"]

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                logger.warning("[AITaskManager] 数据库引擎不可用")
                return None

            set_clauses = []
            params: Dict[str, Any] = {}

            for fld in allowed_fields:
                if fld in updates:
                    set_clauses.append(f"{fld} = :{fld}")
                    if fld in ["output_data", "keywords"]:
                        params[fld] = json.dumps(updates[fld], ensure_ascii=False)
                    else:
                        params[fld] = updates[fld]

            if set_clauses:
                set_clauses.append("updated_at = CURRENT_TIMESTAMP")
                params["tid"] = task_id

                async with engine.begin() as conn:
                    await conn.execute(
                        sql_text(
                            f"UPDATE ai_tasks SET {', '.join(set_clauses)} WHERE id = :tid"
                        ),
                        params,
                    )

            # 清除缓存
            if task_id in self._tasks:
                del self._tasks[task_id]

            return await self.get_task(task_id)
        except Exception as e:
            logger.error(f"[AITaskManager] 更新 PostgreSQL 任务失败: {e}")
            return None

    async def delete_task(self, task_id: int) -> bool:
        """删除任务 - 使用 PostgreSQL"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                logger.warning("[AITaskManager] 数据库引擎不可用")
                return False

            async with engine.begin() as conn:
                await conn.execute(
                    sql_text("DELETE FROM ai_tasks WHERE id = :tid"),
                    {"tid": task_id},
                )

            if task_id in self._tasks:
                del self._tasks[task_id]

            return True
        except Exception as e:
            logger.error(f"[AITaskManager] PostgreSQL 删除任务失败: {e}")
            return False

    def _row_to_task(self, row) -> AITask:
        """将 PostgreSQL 数据库行转换为 AITask 对象"""
        return AITask(
            id=row[0],
            user_id=row[1],
            plan_id=row[2] or 0,
            task_type=row[3],
            status=row[4],
            title=row[5],
            description=row[6] or "",
            input_data=json.loads(row[7]) if row[7] else {},
            output_data=json.loads(row[8]) if row[8] else None,
            result_content=row[9],
            keywords=json.loads(row[10]) if row[10] else [],
            created_at=row[11].isoformat() if row[11] else None,
            updated_at=row[12].isoformat() if row[12] else None,
            completed_at=row[13].isoformat() if row[13] else None,
            error_message=row[14],
        )

    def create_tasks_from_plan(self, plan_data: Dict, user_id: int) -> List[Dict]:
        """
        从优化方案创建AI任务列表

        Args:
            plan_data: 优化方案数据
            user_id: 用户ID

        Returns:
            任务列表（尚未落库的任务字典）
        """
        plan_id = plan_data.get("id")
        domain = plan_data.get("domain", "")
        brand_name = plan_data.get("brand_name", "")
        industry = plan_data.get("industry", "")
        plan_content = plan_data.get("plan_data", {})

        tasks: List[Dict] = []

        # 1. 创建品牌文章任务
        if plan_content.get("brand_positioning"):
            tasks.append({
                "user_id": user_id,
                "plan_id": plan_id,
                "task_type": TaskType.ARTICLE.value,
                "status": TaskStatus.PENDING.value,
                "title": f"{brand_name} 品牌GEO优化文章",
                "description": "基于品牌定位分析，生成符合GEO标准的品牌介绍文章",
                "input_data": {
                    "domain": domain,
                    "brand_name": brand_name,
                    "industry": industry,
                    "keywords": plan_data.get("keywords", []),
                    "brand_positioning": plan_content.get("brand_positioning", {}),
                    "target_word_count": 2500,
                    "tone": "professional",
                    "target_platform": "chatgpt",
                },
            })

        # 2. 创建关键词文章任务（小红书种草笔记）
        keyword_matrix = plan_content.get("keyword_matrix", {})
        core_keywords = keyword_matrix.get("core_keywords", [])

        for keyword in core_keywords[:3]:
            tasks.append({
                "user_id": user_id,
                "plan_id": plan_id,
                "task_type": TaskType.XIAOHONGSHU.value,
                "status": TaskStatus.PENDING.value,
                "title": f"{keyword} 小红书种草笔记",
                "description": f'针对关键词"{keyword}"生成小红书风格的种草内容',
                "input_data": {
                    "domain": domain,
                    "brand_name": brand_name,
                    "industry": industry,
                    "target_keyword": keyword,
                    "related_keywords": core_keywords,
                    "target_word_count": 800,
                    "tone": "casual",
                    "platform": "xiaohongshu",
                    "include_hashtags": True,
                    "include_emojis": True,
                    "style": "种草",
                    "content_type": "种草笔记",
                    "target_audience": "年轻女性用户",
                    "call_to_action": "引导用户咨询或购买",
                },
            })

        # 3. 创建FAQ任务
        if plan_content.get("content_strategy"):
            tasks.append({
                "user_id": user_id,
                "plan_id": plan_id,
                "task_type": TaskType.FAQ.value,
                "status": TaskStatus.PENDING.value,
                "title": f"{brand_name} FAQ问答生成",
                "description": "基于用户搜索意图生成FAQ问答内容",
                "input_data": {
                    "domain": domain,
                    "brand_name": brand_name,
                    "industry": industry,
                    "keywords": plan_data.get("keywords", []),
                    "content_strategy": plan_content.get("content_strategy", {}),
                    "faq_count": 10,
                },
            })

        # 4. 创建Schema标记任务
        tasks.append({
            "user_id": user_id,
            "plan_id": plan_id,
            "task_type": TaskType.SCHEMA.value,
            "status": TaskStatus.PENDING.value,
            "title": f"{brand_name} Schema结构化数据",
            "description": "生成符合GEO标准的Schema.org结构化数据",
            "input_data": {
                "domain": domain,
                "brand_name": brand_name,
                "industry": industry,
                "schema_types": ["Organization", "WebSite", "LocalBusiness", "FAQPage"],
            },
        })

        # 5. 创建落地页任务
        if plan_content.get("technical_optimization"):
            tasks.append({
                "user_id": user_id,
                "plan_id": plan_id,
                "task_type": TaskType.LANDING_PAGE.value,
                "status": TaskStatus.PENDING.value,
                "title": f"{brand_name} GEO优化落地页",
                "description": "生成高转化率的GEO优化落地页内容",
                "input_data": {
                    "domain": domain,
                    "brand_name": brand_name,
                    "industry": industry,
                    "keywords": plan_data.get("keywords", []),
                    "technical_optimization": plan_content.get("technical_optimization", {}),
                    "cta_sections": ["hero", "features", "testimonials", "faq", "contact"],
                },
            })

        # 6. 创建小红书任务
        tasks.append({
            "user_id": user_id,
            "plan_id": plan_id,
            "task_type": TaskType.XIAOHONGSHU.value,
            "status": TaskStatus.PENDING.value,
            "title": f"{brand_name} 小红书内容生成",
            "description": f"为小红书平台生成符合平台调性的种草内容，推广{brand_name}",
            "input_data": {
                "domain": domain,
                "brand_name": brand_name,
                "industry": industry,
                "keywords": plan_data.get("keywords", []),
                "target_keyword": plan_data.get("keywords", [""])[0] if plan_data.get("keywords") else "",
                "platform": "xiaohongshu",
                "platform_config": {
                    "name": "小红书",
                    "content_type": "note",
                    "max_title_length": 20,
                    "max_content_length": 1000,
                    "max_images": 9,
                    "tone_style": "真实、亲切、分享式",
                    "hashtag_style": "简洁实用",
                },
            },
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
        task_type = task.get("task_type")
        input_data = task.get("input_data", {})

        platform_types = [
            TaskType.XIAOHONGSHU.value,
            TaskType.DOUYIN.value,
            TaskType.ZHIHU.value,
            TaskType.WEIBO.value,
            TaskType.WECHAT.value,
            TaskType.BILIBILI.value,
            TaskType.KUAISHOU.value,
            TaskType.TOUTIAO.value,
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
            return self._generate_platform_prompt(task_type, input_data)
        else:
            return "未知任务类型"

    def _generate_article_prompt(self, input_data: Dict) -> str:
        """生成文章提示词"""
        brand_name = input_data.get("brand_name", "")
        industry = input_data.get("industry", "")
        target_keyword = input_data.get("target_keyword", "")
        keywords = input_data.get("keywords", [])
        word_count = input_data.get("target_word_count", 2500)

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
        brand_name = input_data.get("brand_name", "")
        industry = input_data.get("industry", "")
        keywords = input_data.get("keywords", [])
        faq_count = input_data.get("faq_count", 10)

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
        brand_name = input_data.get("brand_name", "")
        domain = input_data.get("domain", "")
        industry = input_data.get("industry", "")

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
        brand_name = input_data.get("brand_name", "")
        industry = input_data.get("industry", "")
        keywords = input_data.get("keywords", [])

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
        brand_name = input_data.get("brand_name", "")
        industry = input_data.get("industry", "")
        keywords = input_data.get("keywords", [])
        original_content = input_data.get("original_content", "")
        target_keyword = input_data.get("target_keyword", "")

        # 小红书使用专门的内容策略（GEO-main 专有模块，惰性导入）
        if platform == "xiaohongshu":
            try:
                from xiaohongshu_content_strategy import content_strategy  # type: ignore

                brand_info = {
                    "style": "简约自然",
                    "features": ["原木", "温馨", "实用"],
                    "website": input_data.get("domain", os.environ.get("XHS_DEFAULT_DOMAIN", "www.example.com")),
                }

                generated = content_strategy.generate_content(brand_info, keywords or [target_keyword])

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
{chr(10).join(['- ' + p for p in generated['image_prompts']])}

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
            except ImportError:
                logger.warning("[AITaskManager] xiaohongshu_content_strategy 模块不可用，使用默认小红书提示词")
            except Exception as e:
                logger.warning(f"[AITaskManager] 小红书内容策略生成失败，使用默认提示词: {e}")

            # 默认小红书提示词（降级路径）
            return self._generate_default_xiaohongshu_prompt(brand_name, industry, keywords, target_keyword)

        # 其他平台使用平台适配器（GEO-main 专有模块，惰性导入）
        try:
            from platform_content_adapter import platform_adapter, PlatformType  # type: ignore

            platform_enum = PlatformType(platform.lower())
            config = platform_adapter.get_platform_config(platform)

            adapted = platform_adapter.adapt_content(
                original_content=original_content or f"为{brand_name}生成{industry}相关内容",
                platform=platform,
                keywords=keywords or [target_keyword],
            )
            return adapted.get("adaptation_prompt", "请生成平台内容")
        except ImportError:
            logger.warning(f"[AITaskManager] platform_content_adapter 模块不可用，使用默认 {platform} 提示词")
        except Exception as e:
            logger.warning(f"[AITaskManager] 平台 {platform} 适配失败，使用默认提示词: {e}")

        # 默认平台提示词（降级路径）
        return self._generate_default_platform_prompt(platform, brand_name, industry, keywords, target_keyword)

    def _generate_default_xiaohongshu_prompt(
        self, brand_name: str, industry: str, keywords: List[str], target_keyword: str,
    ) -> str:
        """默认小红书提示词（无内容策略模块时降级使用）"""
        return f"""# 小红书内容生成任务

## 品牌信息
- 品牌名称：{brand_name}
- 行业：{industry}
- 目标关键词：{target_keyword}
- 相关关键词：{', '.join(keywords[:5])}

## 任务要求
请生成一篇真实、自然的小红书笔记：

### 内容规范
- 标题：20字以内，真实吸引人
- 正文：500-800字，分段清晰
- 标签：3-5个相关标签
- 语气：亲切、真实、像朋友分享
- 避免硬广和绝对化用语

请生成最终的小红书笔记内容："""

    def _generate_default_platform_prompt(
        self, platform: str, brand_name: str, industry: str,
        keywords: List[str], target_keyword: str,
    ) -> str:
        """默认平台提示词（无平台适配器时降级使用）"""
        return f"""# {platform} 内容生成任务

## 品牌信息
- 品牌名称：{brand_name}
- 行业：{industry}
- 目标关键词：{target_keyword}
- 相关关键词：{', '.join(keywords[:5])}

## 任务要求
请生成符合 {platform} 平台调性的内容，注意平台风格与字数限制。

请生成内容："""

    def create_platform_tasks(
        self, plan_data: Dict, user_id: int, platforms: List[str],
    ) -> List[Dict]:
        """
        为多个平台创建内容生成任务

        Args:
            plan_data: 优化方案数据
            user_id: 用户ID
            platforms: 目标平台列表

        Returns:
            任务列表
        """
        plan_id = plan_data.get("id")
        domain = plan_data.get("domain", "")
        brand_name = plan_data.get("brand_name", "")
        industry = plan_data.get("industry", "")
        keywords = plan_data.get("keywords", [])

        tasks: List[Dict] = []

        for platform in platforms:
            try:
                # 尝试使用 GEO-main 平台适配器获取详细配置
                platform_config = None
                platform_value = platform.lower()
                try:
                    from platform_content_adapter import platform_adapter, PlatformType  # type: ignore
                    platform_enum = PlatformType(platform.lower())
                    platform_value = platform_enum.value
                    platform_config = platform_adapter.get_platform_config(platform)
                except ImportError:
                    logger.warning(f"[AITaskManager] platform_content_adapter 不可用，使用默认配置创建 {platform} 任务")
                except Exception as e:
                    logger.warning(f"[AITaskManager] 获取平台 {platform} 配置失败: {e}")

                if platform_config:
                    tasks.append({
                        "user_id": user_id,
                        "plan_id": plan_id,
                        "task_type": platform_value,
                        "status": TaskStatus.PENDING.value,
                        "title": f"{brand_name} {platform_config.name_cn}内容生成",
                        "description": f"为{platform_config.name_cn}平台生成符合平台调性的{platform_config.content_type}内容",
                        "input_data": {
                            "domain": domain,
                            "brand_name": brand_name,
                            "industry": industry,
                            "keywords": keywords,
                            "target_keyword": keywords[0] if keywords else "",
                            "platform": platform,
                            "platform_config": {
                                "name": platform_config.name_cn,
                                "content_type": platform_config.content_type,
                                "max_title_length": platform_config.max_title_length,
                                "max_content_length": platform_config.max_content_length,
                                "max_images": platform_config.max_images,
                                "tone_style": platform_config.tone_style,
                                "hashtag_style": platform_config.hashtag_style,
                            },
                        },
                    })
                else:
                    # 降级：使用默认配置
                    tasks.append({
                        "user_id": user_id,
                        "plan_id": plan_id,
                        "task_type": platform_value,
                        "status": TaskStatus.PENDING.value,
                        "title": f"{brand_name} {platform}内容生成",
                        "description": f"为{platform}平台生成符合平台调性的内容",
                        "input_data": {
                            "domain": domain,
                            "brand_name": brand_name,
                            "industry": industry,
                            "keywords": keywords,
                            "target_keyword": keywords[0] if keywords else "",
                            "platform": platform,
                        },
                    })
            except Exception as e:
                logger.error(f"[AITaskManager] 创建平台任务失败 {platform}: {e}")

        return tasks

    async def execute_xiaohongshu_task(self, task_id: int, user_id: int = None) -> Dict:
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
            task = await self.get_task(task_id)
            if not task:
                return {"success": False, "error": "任务不存在"}

            # 如果任务已完成且已有 output_data，直接使用已有内容发布
            if task.status == TaskStatus.COMPLETED.value and task.output_data:
                output = task.output_data
                xhs_title = output.get("title", task.title[:20])
                xhs_content = output.get("content", "")
                xhs_keywords = output.get("keywords", [])
                brand_name = task.input_data.get("brand_name", "")
                logger.info(f"[AITaskManager] 任务已完成，使用已有内容发布: {xhs_title}")
            else:
                # 任务未完成，提示用户先执行任务
                return {
                    "success": False,
                    "error": "任务尚未完成，请先点击\"开始生成\"执行任务",
                    "task_status": task.status,
                }

            # 自动发布到小红书（依赖 GEO-main 专有模块，惰性导入）
            try:
                from xiaohongshu_automation import auto_publish_to_xiaohongshu  # type: ignore
                from platform_account_postgres import PlatformAccountServicePostgres  # type: ignore

                # 获取平台账号 - 使用任务所属用户的账号
                platform_service = PlatformAccountServicePostgres()
                account_user_id = task.user_id
                account = platform_service.get_account(account_user_id, "xiaohongshu")

                # 如果没有找到，尝试当前用户
                if not account and user_id and user_id != account_user_id:
                    account = platform_service.get_account(user_id, "xiaohongshu")

                if not account:
                    return {
                        "success": False,
                        "error": "未配置小红书账号",
                        "task_id": task_id,
                        "content": {
                            "title": xhs_title,
                            "content": xhs_content,
                            "keywords": xhs_keywords,
                        },
                    }

                # 生成图片 - 使用 AI 文生图生成高质量配图，并持久化保存到本地
                image_paths: List[str] = []
                try:
                    from image_generation_service import image_service  # type: ignore

                    generated_images = image_service.generate_xiaohongshu_images(
                        title=xhs_title,
                        content=xhs_content,
                        keywords=xhs_keywords,
                        count=3,
                        brand_name=brand_name,
                    )

                    if generated_images:
                        for idx, img_base64 in enumerate(generated_images):
                            local_path = image_service.save_base64_to_local(
                                img_base64,
                                brand_name=brand_name,
                                task_id=task_id,
                                index=idx,
                                subdir="xiaohongshu",
                            )
                            if local_path:
                                image_paths.append(local_path)
                                logger.info(f"[AITaskManager] AI图片{idx+1}已保存到本地: {local_path}")
                        logger.info(f"[AITaskManager] 共生成 {len(image_paths)} 张AI图片")
                    else:
                        logger.warning("[AITaskManager] AI图片生成失败，将尝试无图发布")
                except ImportError:
                    logger.warning("[AITaskManager] image_generation_service 模块不可用，将尝试无图发布")
                except Exception as e:
                    logger.warning(f"[AITaskManager] AI图片生成出错: {e}")

                # 发布到小红书（使用本地图片路径上传）
                result = auto_publish_to_xiaohongshu(
                    title=xhs_title,
                    content=xhs_content,
                    cookies=account.get("cookies", ""),
                    keywords=xhs_keywords,
                    images=image_paths if image_paths else None,
                )

                if result.get("success"):
                    await self.update_task(task_id, {
                        "status": TaskStatus.COMPLETED.value,
                        "completed_at": datetime.now().isoformat(),
                        "output_data": {
                            "title": xhs_title,
                            "content": xhs_content,
                            "keywords": xhs_keywords,
                            "platform": "xiaohongshu",
                            "local_images": image_paths,
                            "publish_result": result,
                        },
                    })

                    return {
                        "success": True,
                        "task_id": task_id,
                        "message": "小红书笔记发布成功",
                        "note_url": result.get("note_url"),
                        "title": xhs_title,
                    }
                else:
                    await self.update_task(task_id, {
                        "status": TaskStatus.FAILED.value,
                        "error_message": result.get("error", "发布失败"),
                        "output_data": {
                            "title": xhs_title,
                            "content": xhs_content,
                            "keywords": xhs_keywords,
                            "platform": "xiaohongshu",
                            "publish_result": result,
                        },
                    })

                    return {
                        "success": False,
                        "task_id": task_id,
                        "error": result.get("error", "发布失败"),
                        "content": {
                            "title": xhs_title,
                            "content": xhs_content,
                            "keywords": xhs_keywords,
                        },
                    }

            except ImportError as ie:
                logger.warning(f"[AITaskManager] 自动发布依赖未安装: {ie}")
                return {
                    "success": False,
                    "error": "自动发布需要安装 GEO-main 的 xiaohongshu_automation 模块",
                    "task_id": task_id,
                    "content": {
                        "title": xhs_title,
                        "content": xhs_content,
                        "keywords": xhs_keywords,
                    },
                }
            except Exception as e:
                logger.error(f"[AITaskManager] 自动发布失败: {e}")
                return {
                    "success": False,
                    "error": f"自动发布失败: {e}",
                    "task_id": task_id,
                    "content": {
                        "title": xhs_title,
                        "content": xhs_content,
                        "keywords": xhs_keywords,
                    },
                }

        except Exception as e:
            logger.error(f"[AITaskManager] 执行任务失败: {e}")
            return {
                "success": False,
                "error": f"执行任务失败: {e}",
                "task_id": task_id,
            }


# 单例
_ai_task_service: Optional[AITaskManager] = None


def get_ai_task_service() -> AITaskManager:
    """获取 AI 任务管理服务单例"""
    global _ai_task_service
    if _ai_task_service is None:
        _ai_task_service = AITaskManager()
    return _ai_task_service
