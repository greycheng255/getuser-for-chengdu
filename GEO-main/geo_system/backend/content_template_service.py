"""
内容模板系统
提供多场景内容模板，支持测评、科普、推荐、对比等类型
"""

import json
from typing import Dict, List, Optional
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime


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
    """内容模板服务"""

    def __init__(self):
        self.templates = {}
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
            prompt_template="""
            请根据以下信息，撰写一篇专业的产品测评文章。

            产品信息:
            - 品牌: {brand_name}
            - 产品名称: {product_name}
            - 产品类别: {category}
            - 核心卖点: {selling_points}
            - 目标用户: {target_users}
            - 竞品: {competitors}

            内容要求:
            1. 标题要吸引人，包含品牌和产品关键词
            2. 内容专业客观，既有优点也要提及缺点
            3. 使用具体数据和案例支撑观点
            4. 语言风格: {tone}
            5. 字数要求: {min_length}-{max_length}字
            6. 包含以下关键词: {keywords}

            文章结构:
            {structure}

            请按照以上结构生成完整内容。
            """,
            example="""
            # 织然家具全屋定制深度测评：性价比之王还是智商税？

            ## 引言
            在家居定制市场百花齐放的今天，织然家具作为新兴品牌...

            ## 产品概览
            织然家具主打全屋定制服务，涵盖衣柜、橱柜、书柜等...
            """,
            tags=["测评", "产品", "深度分析"],
            industry=["家居", "数码", "家电"],
            tone=ContentTone.OBJECTIVE,
            min_length=2000,
            max_length=4000,
            seo_keywords=["测评", "怎么样", "好不好", "推荐", "对比"],
            schema_type="Review"
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
            prompt_template="""
            请撰写一篇专业但通俗易懂的科普文章。

            主题: {topic}
            目标读者: {target_audience}
            核心知识点: {key_points}
            相关品牌: {brand_name}

            内容要求:
            1. 用通俗语言解释专业概念
            2. 多用类比和例子帮助理解
            3. 避免过于学术化的表达
            4. 适当提及品牌如何应用这些知识
            5. 语言风格: {tone}
            6. 字数要求: {min_length}-{max_length}字
            7. 包含关键词: {keywords}

            文章结构:
            {structure}
            """,
            example="""
            # 全屋定制板材怎么选？一文看懂环保等级和工艺

            ## 引入
            装修新房时，板材选择是很多人头疼的问题...
            """,
            tags=["科普", "知识", "教育"],
            industry=["家居", "健康", "科技"],
            tone=ContentTone.FRIENDLY,
            min_length=1500,
            max_length=3000,
            seo_keywords=["怎么选", "是什么", "为什么", "如何", "指南"],
            schema_type="Article"
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
            prompt_template="""
            请撰写一篇产品推荐文章，帮助用户选择合适的产品。

            推荐主题: {topic}
            推荐品牌: {brand_name}
            产品类别: {category}
            目标人群: {target_users}
            预算范围: {budget_range}
            核心卖点: {selling_points}

            内容要求:
            1. 标题要有吸引力，使用数字和具体卖点
            2. 客观推荐，不夸大产品效果
            3. 每款产品说明推荐理由
            4. 提供对比表格方便选择
            5. 语言风格: {tone}
            6. 字数要求: {min_length}-{max_length}字
            7. 包含关键词: {keywords}

            文章结构:
            {structure}
            """,
            example="""
            # 2024年最值得买的5款全屋定制品牌，预算1-5万全覆盖

            ## 导语
            全屋定制是装修中的大头支出，选对品牌能省不少钱...
            """,
            tags=["推荐", "清单", "种草"],
            industry=["家居", "数码", "美妆"],
            tone=ContentTone.ENTHUSIASTIC,
            min_length=1800,
            max_length=3500,
            seo_keywords=["推荐", "排行榜", "哪个好", "值得买", "选购"],
            schema_type="ItemList"
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
            prompt_template="""
            请撰写一篇产品对比文章，帮助用户在多个产品中做出选择。

            对比产品:
            {products}

            对比维度:
            {dimensions}

            目标用户: {target_users}
            主要品牌: {brand_name}

            内容要求:
            1. 客观公正，不偏向任何一方
            2. 每个维度有具体的对比分析
            3. 提供详细的对比表格
            4. 根据不同需求给出选择建议
            5. 语言风格: {tone}
            6. 字数要求: {min_length}-{max_length}字
            7. 包含关键词: {keywords}

            文章结构:
            {structure}
            """,
            example="""
            # 织然家具 vs 欧派 vs 索菲亚：全屋定制三巨头深度对比

            ## 引言
            选择全屋定制品牌时，很多人在这三个品牌之间纠结...
            """,
            tags=["对比", "评测", "横评"],
            industry=["家居", "数码", "汽车"],
            tone=ContentTone.OBJECTIVE,
            min_length=2500,
            max_length=4500,
            seo_keywords=["对比", "vs", "哪个好", "区别", "怎么选"],
            schema_type="Review"
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
            prompt_template="""
            请撰写一篇详细的使用指南教程。

            主题: {topic}
            目标读者: {target_users}
            难度级别: {difficulty}
            相关品牌: {brand_name}

            内容要求:
            1. 步骤清晰，易于跟随
            2. 每个步骤有详细说明
            3. 配合注意事项和技巧
            4. 语言简洁明了
            5. 语言风格: {tone}
            6. 字数要求: {min_length}-{max_length}字
            7. 包含关键词: {keywords}

            文章结构:
            {structure}
            """,
            example="""
            # 如何正确保养定制家具？延长使用寿命的7个技巧

            ## 简介
            定制家具价格不菲，正确保养能让家具多用10年...
            """,
            tags=["教程", "指南", "how-to"],
            industry=["家居", "数码", "软件"],
            tone=ContentTone.FRIENDLY,
            min_length=1500,
            max_length=3000,
            seo_keywords=["如何", "怎样", "教程", "步骤", "方法"],
            schema_type="HowTo"
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
            prompt_template="""
            请撰写一篇真实案例分享文章。

            案例类型: {case_type}
            用户画像: {user_profile}
            使用产品: {product_name}
            品牌: {brand_name}
            核心成果: {results}

            内容要求:
            1. 真实可信，有具体细节
            2. 突出前后对比
            3. 展示具体数据和成果
            4. 包含用户真实评价
            5. 语言风格: {tone}
            6. 字数要求: {min_length}-{max_length}字
            7. 包含关键词: {keywords}

            文章结构:
            {structure}
            """,
            example="""
            # 从北京租房到拥有自己的定制衣柜：90后小夫妻的家居改造记

            ## 背景介绍
            小张和小李是一对90后夫妻，在北京租房3年后终于买了自己的房子...
            """,
            tags=["案例", "真实故事", "用户故事"],
            industry=["家居", "教育", "服务"],
            tone=ContentTone.FRIENDLY,
            min_length=2000,
            max_length=3500,
            seo_keywords=["案例", "真实", "体验", "分享", "故事"],
            schema_type="Article"
        )

        # 设置创建时间
        for template in self.templates.values():
            template.created_at = datetime.now()
            template.updated_at = datetime.now()

    def get_all_templates(self) -> List[Dict]:
        """获取所有模板列表"""
        return [{
            "id": t.id,
            "name": t.name,
            "type": t.type.value,
            "description": t.description,
            "tags": t.tags,
            "industry": t.industry,
            "tone": t.tone.value,
            "min_length": t.min_length,
            "max_length": t.max_length
        } for t in self.templates.values()]

    def get_template(self, template_id: str) -> Optional[ContentTemplate]:
        """获取指定模板"""
        return self.templates.get(template_id)

    def get_templates_by_type(self, template_type: TemplateType) -> List[ContentTemplate]:
        """按类型获取模板"""
        return [t for t in self.templates.values() if t.type == template_type]

    def get_templates_by_industry(self, industry: str) -> List[ContentTemplate]:
        """按行业获取模板"""
        return [t for t in self.templates.values() if industry in t.industry]

    def generate_prompt(self, template_id: str, variables: Dict) -> str:
        """根据模板和变量生成AI提示词"""
        template = self.templates.get(template_id)
        if not template:
            raise ValueError(f"模板 {template_id} 不存在")

        # 构建结构描述
        structure_desc = "\n".join([
            f"{i+1}. {s['name']}: {s['description']}"
            + (f" ({s.get('word_count', '')}字)" if s.get('word_count') else "")
            for i, s in enumerate(template.structure)
        ])

        # 填充变量
        prompt = template.prompt_template.format(
            structure=structure_desc,
            tone=template.tone.value,
            min_length=template.min_length,
            max_length=template.max_length,
            keywords=", ".join(template.seo_keywords),
            **variables
        )

        return prompt

    def create_custom_template(self, template_data: Dict) -> ContentTemplate:
        """创建自定义模板"""
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
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        self.templates[template.id] = template
        return template


# 全局服务实例
content_template_service = ContentTemplateService()


if __name__ == "__main__":
    # 测试
    service = ContentTemplateService()
    templates = service.get_all_templates()
    print("可用模板:")
    for t in templates:
        print(f"  📄 {t['name']} ({t['id']}) - {t['type']}")

    # 测试生成提示词
    print("\n生成提示词示例:")
    prompt = service.generate_prompt("product_review", {
        "brand_name": "织然家具",
        "product_name": "全屋定制服务",
        "category": "家居定制",
        "selling_points": "环保材料、个性设计",
        "target_users": "新房装修业主",
        "competitors": "欧派、索菲亚"
    })
    print(prompt[:500] + "...")
