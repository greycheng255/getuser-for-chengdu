# -*- coding: utf-8 -*-
"""
内容模板系统（P0：内容模板服务）

迁移自 GEO-main content_template_service.py，适配 MediaCrawler：
1. 保留纯内存模板结构（无数据库依赖，启动即可用）
2. 暴露 get_content_template_service() 单例，符合 MediaCrawler 服务规范
3. 支持后续扩展为数据库持久化自定义模板

对应 PRD 5.2 视频智能生成 - 内容参数配置 / 营销文案标准化生产。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class TemplateType(Enum):
    """模板类型"""
    REVIEW = "review"           # 测评类
    SCIENCE = "science"         # 科普类
    RECOMMEND = "recommend"     # 推荐类
    COMPARE = "compare"         # 对比类
    GUIDE = "guide"             # 指南类
    CASE = "case"               # 案例类
    FAQ = "faq"                 # FAQ类
    NEWS = "news"               # 新闻类


class ContentTone(Enum):
    """内容语调"""
    PROFESSIONAL = "professional"   # 专业严谨
    FRIENDLY = "friendly"           # 亲切友好
    PERSUASIVE = "persuasive"       # 说服力强
    OBJECTIVE = "objective"         # 客观中立
    ENTHUSIASTIC = "enthusiastic"   # 热情推荐


@dataclass
class ContentTemplate:
    """内容模板"""
    id: str
    name: str
    type: TemplateType
    description: str
    structure: List[Dict]           # 内容结构
    prompt_template: str            # AI提示词模板
    example: str                    # 示例内容
    tags: List[str]                 # 标签
    industry: List[str]             # 适用行业
    tone: ContentTone               # 语调风格
    min_length: int                 # 最小字数
    max_length: int                 # 最大字数
    seo_keywords: List[str]         # SEO关键词建议
    schema_type: str                # Schema.org类型
    created_at: datetime = None
    updated_at: datetime = None


class ContentTemplateService:
    """内容模板服务（纯内存，无数据库依赖）"""

    def __init__(self):
        self.templates: Dict[str, ContentTemplate] = {}
        self._init_templates()

    def _init_templates(self):
        """初始化内置模板"""

        # 1. 产品测评模板
        self.templates["product_review"] = ContentTemplate(
            id="product_review",
            name="产品深度测评",
            type=TemplateType.REVIEW,
            description="专业的产品测评文章，从多个维度分析产品优缺点",
            structure=[
                {"section": "title", "name": "标题", "description": "包含品牌+产品+测评关键词", "required": True},
                {"section": "intro", "name": "引言", "description": "产品背景介绍和测评目的", "required": True, "word_count": "200-300"},
                {"section": "overview", "name": "产品概览", "description": "产品基本信息和核心卖点", "required": True, "word_count": "300-400"},
                {"section": "features", "name": "功能特点", "description": "详细分析产品功能和特点", "required": True, "word_count": "500-800"},
                {"section": "pros_cons", "name": "优缺点分析", "description": "客观分析优缺点", "required": True, "word_count": "400-600"},
                {"section": "comparison", "name": "竞品对比", "description": "与同类产品对比", "required": False, "word_count": "400-600"},
                {"section": "use_cases", "name": "使用场景", "description": "适合的使用场景和人群", "required": True, "word_count": "300-400"},
                {"section": "verdict", "name": "总结建议", "description": "购买建议和总结", "required": True, "word_count": "300-400"},
                {"section": "faq", "name": "常见问题", "description": "FAQ问答", "required": False, "word_count": "300-500"}
            ],
            prompt_template=(
                "请根据以下信息，撰写一篇专业的产品测评文章。\n\n"
                "产品信息:\n"
                "- 品牌: {brand_name}\n"
                "- 产品名称: {product_name}\n"
                "- 产品类别: {category}\n"
                "- 核心卖点: {selling_points}\n"
                "- 目标用户: {target_users}\n"
                "- 竞品: {competitors}\n\n"
                "内容要求:\n"
                "1. 标题要吸引人，包含品牌和产品关键词\n"
                "2. 内容专业客观，既有优点也要提及缺点\n"
                "3. 使用具体数据和案例支撑观点\n"
                "4. 语言风格: {tone}\n"
                "5. 字数要求: {min_length}-{max_length}字\n"
                "6. 包含以下关键词: {keywords}\n\n"
                "文章结构:\n{structure}\n\n"
                "请按照以上结构生成完整内容。"
            ),
            example="# 产品深度测评：性价比之王还是智商税？\n\n## 引言\n在市场百花齐放的今天...\n",
            tags=["测评", "产品", "深度分析"],
            industry=["家居", "数码", "家电"],
            tone=ContentTone.OBJECTIVE,
            min_length=2000,
            max_length=4000,
            seo_keywords=["测评", "怎么样", "好不好", "推荐", "对比"],
            schema_type="Review",
        )

        # 2. 科普知识模板
        self.templates["knowledge_guide"] = ContentTemplate(
            id="knowledge_guide",
            name="专业知识科普",
            type=TemplateType.SCIENCE,
            description="通俗易懂的专业知识科普文章",
            structure=[
                {"section": "title", "name": "标题", "description": "引发好奇心的标题", "required": True},
                {"section": "hook", "name": "引入", "description": "用问题或场景引入话题", "required": True, "word_count": "150-200"},
                {"section": "concept", "name": "概念解释", "description": "核心概念通俗解释", "required": True, "word_count": "400-600"},
                {"section": "principle", "name": "原理解析", "description": "工作原理或机制", "required": True, "word_count": "500-800"},
                {"section": "application", "name": "应用场景", "description": "实际应用和案例", "required": True, "word_count": "400-600"},
                {"section": "misunderstanding", "name": "常见误区", "description": "常见误区和纠正", "required": False, "word_count": "300-400"},
                {"section": "tips", "name": "实用建议", "description": "专业建议和技巧", "required": True, "word_count": "300-400"},
                {"section": "conclusion", "name": "总结", "description": "要点总结", "required": True, "word_count": "200-300"}
            ],
            prompt_template=(
                "请撰写一篇专业但通俗易懂的科普文章。\n\n"
                "主题: {topic}\n"
                "目标读者: {target_audience}\n"
                "核心知识点: {key_points}\n"
                "相关品牌: {brand_name}\n\n"
                "内容要求:\n"
                "1. 用通俗语言解释专业概念\n"
                "2. 多用类比和例子帮助理解\n"
                "3. 避免过于学术化的表达\n"
                "4. 适当提及品牌如何应用这些知识\n"
                "5. 语言风格: {tone}\n"
                "6. 字数要求: {min_length}-{max_length}字\n"
                "7. 包含关键词: {keywords}\n\n"
                "文章结构:\n{structure}"
            ),
            example="# 专业知识科普\n\n## 引入\n用问题或场景引入话题...\n",
            tags=["科普", "知识", "教育"],
            industry=["家居", "健康", "科技"],
            tone=ContentTone.FRIENDLY,
            min_length=1500,
            max_length=3000,
            seo_keywords=["怎么选", "是什么", "为什么", "如何", "指南"],
            schema_type="Article",
        )

        # 3. 好物推荐模板
        self.templates["product_recommend"] = ContentTemplate(
            id="product_recommend",
            name="好物推荐清单",
            type=TemplateType.RECOMMEND,
            description="产品推荐清单，适合种草和导购",
            structure=[
                {"section": "title", "name": "标题", "description": "数字+卖点+人群", "required": True},
                {"section": "intro", "name": "导语", "description": "推荐背景和选择标准", "required": True, "word_count": "200-300"},
                {"section": "criteria", "name": "选购要点", "description": "选购标准和注意事项", "required": True, "word_count": "400-500"},
                {"section": "products", "name": "产品推荐", "description": "具体产品推荐(3-5款)", "required": True, "word_count": "800-1200"},
                {"section": "comparison_table", "name": "对比表格", "description": "参数对比表格", "required": True},
                {"section": "buying_guide", "name": "购买建议", "description": "不同需求的选择建议", "required": True, "word_count": "300-400"},
                {"section": "conclusion", "name": "结语", "description": "总结和行动号召", "required": True, "word_count": "150-200"}
            ],
            prompt_template=(
                "请撰写一篇产品推荐文章，帮助用户选择合适的产品。\n\n"
                "推荐主题: {topic}\n"
                "推荐品牌: {brand_name}\n"
                "产品类别: {category}\n"
                "目标人群: {target_users}\n"
                "预算范围: {budget_range}\n"
                "核心卖点: {selling_points}\n\n"
                "内容要求:\n"
                "1. 标题要有吸引力，使用数字和具体卖点\n"
                "2. 客观推荐，不夸大产品效果\n"
                "3. 每款产品说明推荐理由\n"
                "4. 提供对比表格方便选择\n"
                "5. 语言风格: {tone}\n"
                "6. 字数要求: {min_length}-{max_length}字\n"
                "7. 包含关键词: {keywords}\n\n"
                "文章结构:\n{structure}"
            ),
            example="# 好物推荐清单\n\n## 导语\n推荐背景和选择标准...\n",
            tags=["推荐", "清单", "种草"],
            industry=["家居", "数码", "美妆"],
            tone=ContentTone.ENTHUSIASTIC,
            min_length=1800,
            max_length=3500,
            seo_keywords=["推荐", "排行榜", "哪个好", "值得买", "选购"],
            schema_type="ItemList",
        )

        # 4. 对比评测模板
        self.templates["product_compare"] = ContentTemplate(
            id="product_compare",
            name="产品对比评测",
            type=TemplateType.COMPARE,
            description="多产品横向对比，帮助用户决策",
            structure=[
                {"section": "title", "name": "标题", "description": "A vs B vs C对比", "required": True},
                {"section": "intro", "name": "引言", "description": "对比目的和维度", "required": True, "word_count": "200-300"},
                {"section": "overview", "name": "产品简介", "description": "各产品基本信息", "required": True, "word_count": "400-600"},
                {"section": "dimension1", "name": "维度一对比", "description": "第一个对比维度", "required": True, "word_count": "400-600"},
                {"section": "dimension2", "name": "维度二对比", "description": "第二个对比维度", "required": True, "word_count": "400-600"},
                {"section": "dimension3", "name": "维度三对比", "description": "第三个对比维度", "required": True, "word_count": "400-600"},
                {"section": "comparison_table", "name": "综合对比表", "description": "全面对比表格", "required": True},
                {"section": "verdict", "name": "选购建议", "description": "不同需求的选择建议", "required": True, "word_count": "400-600"}
            ],
            prompt_template=(
                "请撰写一篇产品对比文章，帮助用户在多个产品中做出选择。\n\n"
                "对比产品:\n{products}\n\n"
                "对比维度:\n{dimensions}\n\n"
                "目标用户: {target_users}\n"
                "主要品牌: {brand_name}\n\n"
                "内容要求:\n"
                "1. 客观公正，不偏向任何一方\n"
                "2. 每个维度有具体的对比分析\n"
                "3. 提供详细的对比表格\n"
                "4. 根据不同需求给出选择建议\n"
                "5. 语言风格: {tone}\n"
                "6. 字数要求: {min_length}-{max_length}字\n"
                "7. 包含关键词: {keywords}\n\n"
                "文章结构:\n{structure}"
            ),
            example="# 产品对比评测\n\n## 引言\n对比目的和维度...\n",
            tags=["对比", "评测", "横评"],
            industry=["家居", "数码", "汽车"],
            tone=ContentTone.OBJECTIVE,
            min_length=2500,
            max_length=4500,
            seo_keywords=["对比", "vs", "哪个好", "区别", "怎么选"],
            schema_type="Review",
        )

        # 5. 使用指南模板
        self.templates["usage_guide"] = ContentTemplate(
            id="usage_guide",
            name="使用指南教程",
            type=TemplateType.GUIDE,
            description="详细的使用教程和操作指南",
            structure=[
                {"section": "title", "name": "标题", "description": "如何/怎样+动词+目标", "required": True},
                {"section": "intro", "name": "简介", "description": "指南目的和适用人群", "required": True, "word_count": "150-200"},
                {"section": "preparation", "name": "准备工作", "description": "需要准备的材料和工具", "required": True, "word_count": "200-300"},
                {"section": "steps", "name": "操作步骤", "description": "详细步骤说明", "required": True, "word_count": "800-1200"},
                {"section": "tips", "name": "注意事项", "description": "常见问题和技巧", "required": True, "word_count": "300-400"},
                {"section": "troubleshooting", "name": "问题排查", "description": "常见问题解决", "required": False, "word_count": "300-500"},
                {"section": "conclusion", "name": "总结", "description": "要点回顾", "required": True, "word_count": "150-200"}
            ],
            prompt_template=(
                "请撰写一篇详细的使用指南教程。\n\n"
                "主题: {topic}\n"
                "目标读者: {target_users}\n"
                "难度级别: {difficulty}\n"
                "相关品牌: {brand_name}\n\n"
                "内容要求:\n"
                "1. 步骤清晰，易于跟随\n"
                "2. 每个步骤有详细说明\n"
                "3. 配合注意事项和技巧\n"
                "4. 语言简洁明了\n"
                "5. 语言风格: {tone}\n"
                "6. 字数要求: {min_length}-{max_length}字\n"
                "7. 包含关键词: {keywords}\n\n"
                "文章结构:\n{structure}"
            ),
            example="# 使用指南教程\n\n## 简介\n指南目的和适用人群...\n",
            tags=["教程", "指南", "how-to"],
            industry=["家居", "数码", "软件"],
            tone=ContentTone.FRIENDLY,
            min_length=1500,
            max_length=3000,
            seo_keywords=["如何", "怎样", "教程", "步骤", "方法"],
            schema_type="HowTo",
        )

        # 6. 案例分享模板
        self.templates["case_study"] = ContentTemplate(
            id="case_study",
            name="真实案例分享",
            type=TemplateType.CASE,
            description="真实用户案例，增强可信度",
            structure=[
                {"section": "title", "name": "标题", "description": "用户+成果+方法", "required": True},
                {"section": "intro", "name": "背景介绍", "description": "用户背景和面临问题", "required": True, "word_count": "300-400"},
                {"section": "challenge", "name": "面临挑战", "description": "具体困难和痛点", "required": True, "word_count": "300-400"},
                {"section": "solution", "name": "解决方案", "description": "如何解决问题", "required": True, "word_count": "500-700"},
                {"section": "implementation", "name": "实施过程", "description": "具体实施步骤", "required": True, "word_count": "400-600"},
                {"section": "results", "name": "成果展示", "description": "具体成果和数据", "required": True, "word_count": "300-400"},
                {"section": "testimonial", "name": "用户评价", "description": "用户真实评价", "required": True, "word_count": "200-300"},
                {"section": "conclusion", "name": "经验总结", "description": "可复制的经验", "required": True, "word_count": "200-300"}
            ],
            prompt_template=(
                "请撰写一篇真实案例分享文章。\n\n"
                "案例类型: {case_type}\n"
                "用户画像: {user_profile}\n"
                "使用产品: {product_name}\n"
                "品牌: {brand_name}\n"
                "核心成果: {results}\n\n"
                "内容要求:\n"
                "1. 真实可信，有具体细节\n"
                "2. 突出前后对比\n"
                "3. 展示具体数据和成果\n"
                "4. 包含用户真实评价\n"
                "5. 语言风格: {tone}\n"
                "6. 字数要求: {min_length}-{max_length}字\n"
                "7. 包含关键词: {keywords}\n\n"
                "文章结构:\n{structure}"
            ),
            example="# 真实案例分享\n\n## 背景介绍\n用户背景和面临问题...\n",
            tags=["案例", "真实故事", "用户故事"],
            industry=["家居", "教育", "服务"],
            tone=ContentTone.FRIENDLY,
            min_length=2000,
            max_length=3500,
            seo_keywords=["案例", "真实", "体验", "分享", "故事"],
            schema_type="Article",
        )

        # 设置创建时间
        now = datetime.utcnow()
        for template in self.templates.values():
            template.created_at = now
            template.updated_at = now

        logger.info("内容模板服务初始化完成，共 %d 个内置模板", len(self.templates))

    def get_all_templates(self) -> List[Dict]:
        """获取所有模板列表"""
        return [
            {
                "id": t.id,
                "name": t.name,
                "type": t.type.value,
                "description": t.description,
                "tags": t.tags,
                "industry": t.industry,
                "tone": t.tone.value,
                "min_length": t.min_length,
                "max_length": t.max_length,
            }
            for t in self.templates.values()
        ]

    def get_template(self, template_id: str) -> Optional[ContentTemplate]:
        """获取指定模板"""
        return self.templates.get(template_id)

    def get_templates_by_type(self, template_type: str) -> List[Dict]:
        """按类型获取模板"""
        try:
            t_enum = TemplateType(template_type)
        except ValueError:
            return []
        return [
            self._template_to_dict(t)
            for t in self.templates.values()
            if t.type == t_enum
        ]

    def get_templates_by_industry(self, industry: str) -> List[Dict]:
        """按行业获取模板"""
        return [
            self._template_to_dict(t)
            for t in self.templates.values()
            if industry in t.industry
        ]

    def _template_to_dict(self, t: ContentTemplate) -> Dict:
        return {
            "id": t.id,
            "name": t.name,
            "type": t.type.value,
            "description": t.description,
            "structure": t.structure,
            "tags": t.tags,
            "industry": t.industry,
            "tone": t.tone.value,
            "min_length": t.min_length,
            "max_length": t.max_length,
            "seo_keywords": t.seo_keywords,
            "schema_type": t.schema_type,
        }

    def generate_prompt(self, template_id: str, variables: Dict) -> Dict:
        """根据模板和变量生成 AI 提示词

        Returns:
            {
                "template_id": str,
                "template_name": str,
                "prompt": str,
                "structure": List[Dict],
                "tone": str,
                "length_range": [min, max],
            }
        """
        template = self.templates.get(template_id)
        if not template:
            raise ValueError(f"模板 {template_id} 不存在")

        # 构建结构描述
        structure_desc = "\n".join(
            [
                f"{i+1}. {s['name']}: {s['description']}"
                + (f" ({s.get('word_count', '')}字)" if s.get("word_count") else "")
                for i, s in enumerate(template.structure)
            ]
        )

        # 填充变量（缺少的变量使用空字符串，避免 KeyError）
        format_vars = {
            "structure": structure_desc,
            "tone": template.tone.value,
            "min_length": template.min_length,
            "max_length": template.max_length,
            "keywords": ", ".join(template.seo_keywords),
        }
        format_vars.update({k: (v if v is not None else "") for k, v in variables.items()})

        try:
            prompt = template.prompt_template.format(**format_vars)
        except KeyError as e:
            raise ValueError(f"模板变量缺失: {e}")

        return {
            "template_id": template.id,
            "template_name": template.name,
            "prompt": prompt,
            "structure": template.structure,
            "tone": template.tone.value,
            "length_range": [template.min_length, template.max_length],
            "seo_keywords": template.seo_keywords,
            "schema_type": template.schema_type,
        }

    def create_custom_template(self, template_data: Dict) -> Dict:
        """创建自定义模板（仅内存，重启后失效）"""
        template = ContentTemplate(
            id=template_data["id"],
            name=template_data["name"],
            type=TemplateType(template_data["type"]),
            description=template_data["description"],
            structure=template_data["structure"],
            prompt_template=template_data["prompt_template"],
            example=template_data.get("example", ""),
            tags=template_data.get("tags", []),
            industry=template_data.get("industry", []),
            tone=ContentTone(template_data.get("tone", "professional")),
            min_length=template_data.get("min_length", 1000),
            max_length=template_data.get("max_length", 3000),
            seo_keywords=template_data.get("seo_keywords", []),
            schema_type=template_data.get("schema_type", "Article"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.templates[template.id] = template
        logger.info("自定义模板创建成功: %s", template.id)
        return self._template_to_dict(template)


# 单例
_content_template_service: Optional[ContentTemplateService] = None


def get_content_template_service() -> ContentTemplateService:
    """获取内容模板服务单例"""
    global _content_template_service
    if _content_template_service is None:
        _content_template_service = ContentTemplateService()
    return _content_template_service
