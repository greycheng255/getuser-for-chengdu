"""
GEO文章生成器
基于ERE框架（Entity-Relation-Evidence）生成AI友好的内容
"""

import os
import re
import yaml
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BrandInfo:
    """品牌信息"""
    name: str
    industry: str
    expertise: List[str]
    website: Optional[str] = None
    description: Optional[str] = None


@dataclass
class ArticleConfig:
    """文章配置"""
    title: str
    target_platform: str = "chatgpt"  # chatgpt, perplexity, google_ai_overviews, gemini
    word_count: int = 2500
    tone: str = "professional"  # professional, casual, academic
    include_statistics: bool = True
    include_expert_quotes: bool = True
    min_sources: int = 5


class GEOArticleGenerator:
    """
    GEO文章生成器
    
    基于姚金刚的GEO方法论，生成符合AI引用偏好的高质量内容
    """
    
    def __init__(self, config_path: str = None):
        self.config_path = config_path or os.path.join(
            os.path.dirname(__file__), "..", "config", "geo_rules.yaml"
        )
        self.geo_rules = self._load_geo_rules()
        
    def _load_geo_rules(self) -> Dict:
        """加载GEO规则配置"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            return self._get_default_rules()
    
    def _get_default_rules(self) -> Dict:
        """默认GEO规则"""
        return {
            "ere_framework": {
                "entity": {"required": True, "min_count": 3},
                "relation": {"required": True},
                "evidence": {"required": True, "min_sources": 2}
            },
            "citation_optimization": {
                "statistics": {"required": True, "min_per_article": 3},
                "expert_quotes": {"recommended": True, "min_per_article": 1},
                "sources": {"min_count": 5}
            }
        }
    
    def generate(self, title: str, brand_info: Dict, **kwargs) -> Dict[str, Any]:
        """
        生成GEO优化文章
        
        Args:
            title: 文章标题
            brand_info: 品牌信息字典
            **kwargs: 其他配置参数
            
        Returns:
            包含文章内容和元数据的字典
        """
        brand = BrandInfo(**brand_info)
        config = ArticleConfig(title=title, **kwargs)
        
        # 构建文章结构
        article_structure = self._build_article_structure(config)
        
        # 生成文章大纲
        outline = self._generate_outline(title, brand, config)
        
        # 生成提示词
        prompt = self._build_generation_prompt(title, brand, config, outline)
        
        return {
            "title": title,
            "outline": outline,
            "prompt": prompt,
            "structure": article_structure,
            "brand_info": brand,
            "config": config,
            "generated_at": datetime.now().isoformat(),
            "geo_features": self._extract_geo_features()
        }
    
    def _build_article_structure(self, config: ArticleConfig) -> Dict:
        """构建文章结构"""
        structure = {
            "introduction": {
                "purpose": "吸引读者，提出问题",
                "elements": ["hook", "context", "problem_statement"],
                "length": "300-500字"
            },
            "body_sections": [],
            "conclusion": {
                "purpose": "总结要点，给出行动建议",
                "elements": ["summary", "action_items", "future_outlook"],
                "length": "300-400字"
            },
            "references": {
                "purpose": "提供可信来源",
                "min_count": config.min_sources
            }
        }
        
        # 根据字数计算章节数
        section_count = max(4, min(8, config.word_count // 400))
        
        for i in range(section_count):
            structure["body_sections"].append({
                "order": i + 1,
                "heading_level": 2,
                "length": f"{config.word_count // section_count}字",
                "required_elements": self._get_section_elements(i, section_count)
            })
        
        return structure
    
    def _get_section_elements(self, section_index: int, total_sections: int) -> List[str]:
        """获取每个章节需要的元素"""
        elements_map = {
            0: ["definition", "background"],
            1: ["analysis", "data_support"],
            2: ["case_study", "practical_example"],
            3: ["comparison", "framework"],
            4: ["methodology", "best_practices"],
            5: ["implementation", "tools"],
            6: ["challenges", "solutions"],
            7: ["trends", "future"]
        }
        return elements_map.get(section_index, ["analysis", "evidence"])
    
    def _generate_outline(self, title: str, brand: BrandInfo, config: ArticleConfig) -> List[Dict]:
        """生成文章大纲"""
        outline = [
            {
                "level": 1,
                "title": title,
                "type": "main_title"
            },
            {
                "level": 2,
                "title": "引言：为什么这个问题很重要",
                "type": "introduction",
                "key_points": [
                    "当前行业背景和痛点",
                    "AI搜索时代的新机遇",
                    f"{brand.name}的专业视角"
                ]
            }
        ]
        
        # 根据标题生成相关章节
        sections = self._infer_sections_from_title(title)
        for i, section_title in enumerate(sections, 1):
            outline.append({
                "level": 2,
                "title": section_title,
                "type": "body",
                "section_number": i,
                "key_points": self._generate_key_points(section_title, brand)
            })
        
        outline.append({
            "level": 2,
            "title": "总结与行动建议",
            "type": "conclusion",
            "key_points": [
                "核心要点回顾",
                "可落地的行动步骤",
                "如何开始你的第一步"
            ]
        })
        
        return outline
    
    def _infer_sections_from_title(self, title: str) -> List[str]:
        """从标题推断章节结构"""
        # 提取核心主题词
        keywords = self._extract_keywords(title)
        
        # 标准GEO内容结构
        sections = [
            f"什么是{keywords[0] if keywords else '核心概念'}",
            f"{keywords[0] if keywords else '核心概念'}的工作原理",
            f"为什么{keywords[0] if keywords else '它'}对企业重要",
            f"如何实施{keywords[0] if keywords else '解决方案'}",
            f"{keywords[0] if keywords else '最佳实践'}的成功案例",
            f"常见误区与避坑指南"
        ]
        
        return sections
    
    def _extract_keywords(self, title: str) -> List[str]:
        """从标题提取关键词"""
        # 简单的关键词提取逻辑
        # 实际应用中可以使用NLP工具
        common_words = {"什么", "如何", "为什么", "的", "是", "与", "和", "在", "了"}
        words = re.findall(r'[\u4e00-\u9fff]+', title)
        keywords = [w for w in words if w not in common_words and len(w) >= 2]
        return keywords[:3] if keywords else ["核心主题"]
    
    def _generate_key_points(self, section_title: str, brand: BrandInfo) -> List[str]:
        """为每个章节生成关键要点"""
        return [
            f"结合{brand.industry}行业特点",
            f"引用权威数据支撑",
            f"提供可操作的洞察"
        ]
    
    def _build_generation_prompt(self, title: str, brand: BrandInfo, 
                                  config: ArticleConfig, outline: List[Dict]) -> str:
        """构建文章生成提示词"""
        
        platform_guidance = self._get_platform_guidance(config.target_platform)
        
        prompt = f"""你是一位专业的GEO（生成式引擎优化）内容专家。请根据以下要求创作一篇高质量的文章。

## 文章主题
{title}

## 品牌信息
- 品牌名称：{brand.name}
- 所属行业：{brand.industry}
- 专业领域：{', '.join(brand.expertise)}
{f"- 品牌介绍：{brand.description}" if brand.description else ""}

## 目标平台
{config.target_platform}
{platform_guidance}

## 文章要求

### 基础要求
- 字数：{config.word_count}字左右
- 语调：{config.tone}
- 结构：遵循大纲中的章节安排

### GEO优化要求（必须遵循）

1. **ERE框架应用**
   - Entity（实体）：明确标识文章中的核心实体（品牌、产品、概念）
   - Relation（关系）：清晰阐述实体之间的关系
   - Evidence（证据）：每个关键观点都需要数据或案例支撑

2. **AI引用优化**
   - 包含至少{self.geo_rules.get('citation_optimization', {}).get('statistics', {}).get('min_per_article', 3)}个权威统计数据
   - 包含至少{self.geo_rules.get('citation_optimization', {}).get('expert_quotes', {}).get('min_per_article', 1)}个专家引言
   - 提供至少{config.min_sources}个可信来源

3. **内容结构**
   - 使用清晰的H2/H3标题层级
   - 每段3-8句话，保持简洁
   - 关键信息前置，符合AI摘要习惯

4. **可信度建设**
   - 引用权威研究机构数据
   - 提供具体案例而非泛泛而谈
   - 使用精确数字而非模糊表述

## 文章大纲
{self._format_outline(outline)}

## 输出格式

请按以下格式输出文章：

```
# {title}

## 引言
[引言内容]

## [章节1标题]
[章节内容]

## [章节2标题]
[章节内容]

...

## 总结与行动建议
[总结内容]

## 参考来源
1. [来源1]
2. [来源2]
...
```

请确保内容专业、有深度，同时易于被AI搜索引擎理解和引用。
"""
        return prompt
    
    def _get_platform_guidance(self, platform: str) -> str:
        """获取平台特定指导"""
        guidance = {
            "chatgpt": """
- ChatGPT偏好深入、全面的内容
- 引用格式：行内引用，如"根据XX研究显示..."
- 内容深度要求高，需要详细解释概念
- 适合2000-4000字的深度文章""",
            
            "perplexity": """
- Perplexity偏好学术化、有来源的内容
- 引用格式：学术引用，标注具体来源
- 需要更多研究性内容和数据支撑
- 适合1500-3000字的研究型文章""",
            
            "google_ai_overviews": """
- Google AI Overviews偏好结构化、简洁的内容
- 引用格式：片段式引用
- 需要清晰的列表、表格等结构化元素
- 适合1000-2500字的信息型文章""",
            
            "gemini": """
- Gemini偏好综合性、多角度的内容
- 引用格式：灵活的引用方式
- 需要平衡深度和广度
- 适合2000-4000字的综合文章"""
        }
        return guidance.get(platform, guidance["chatgpt"])
    
    def _format_outline(self, outline: List[Dict]) -> str:
        """格式化大纲"""
        lines = []
        for item in outline:
            indent = "  " * (item["level"] - 1)
            lines.append(f"{indent}- {item['title']}")
            if "key_points" in item:
                for point in item["key_points"]:
                    lines.append(f"{indent}  * {point}")
        return "\n".join(lines)
    
    def _extract_geo_features(self) -> Dict:
        """提取GEO特性说明"""
        return {
            "ere_framework": {
                "entity_recognition": "自动识别并标注核心实体",
                "relation_mapping": "建立实体间的语义关系",
                "evidence_integration": "整合数据证据支撑观点"
            },
            "citation_optimization": {
                "statistics_integration": "优化统计数据呈现方式",
                "expert_quotes": "增强专家引言的权威性",
                "source_diversity": "确保来源多样性"
            },
            "structure_optimization": {
                "heading_hierarchy": "清晰的标题层级结构",
                "paragraph_length": "优化的段落长度",
                "information_priority": "信息优先级排序"
            }
        }


# 使用示例
if __name__ == "__main__":
    generator = GEOArticleGenerator()
    
    result = generator.generate(
        title="什么是生成式引擎优化（GEO）：AI搜索时代的营销新范式",
        brand_info={
            "name": "智媒科技",
            "industry": "AI营销",
            "expertise": ["GEO", "AI搜索优化", "内容营销"],
            "description": "专注于AI时代的营销技术解决方案"
        },
        target_platform="chatgpt",
        word_count=3000
    )
    
    print("文章大纲：")
    for item in result["outline"]:
        print(f"{'  ' * (item['level']-1)}{item['title']}")
    
    print("\n生成的提示词已准备就绪，可以发送给AI模型生成文章。")
