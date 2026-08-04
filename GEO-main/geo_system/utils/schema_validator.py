"""
Schema验证器
验证和优化Schema.org结构化数据
"""

import json
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    errors: List[Dict]
    warnings: List[Dict]
    suggestions: List[Dict]
    completeness_score: float
    seo_score: float


class SchemaValidator:
    """
    Schema.org验证器
    
    验证和优化结构化数据：
    - Schema语法验证
    - 必需属性检查
    - 推荐属性建议
    - SEO优化建议
    - 平台适配检查
    """
    
    def __init__(self):
        self.schema_definitions = self._load_schema_definitions()
        self.validation_rules = self._load_validation_rules()
        
    def _load_schema_definitions(self) -> Dict:
        """加载Schema定义"""
        return {
            "Organization": {
                "required": ["name", "url"],
                "recommended": [
                    "logo", "description", "foundingDate", "address",
                    "contactPoint", "sameAs", "knowsAbout"
                ],
                "optional": [
                    "founders", "employees", "department", "parentOrganization"
                ],
                "seo_critical": ["name", "description", "logo", "url"]
            },
            "WebSite": {
                "required": ["name", "url"],
                "recommended": ["description", "potentialAction", "publisher"],
                "optional": ["inLanguage", "copyrightHolder"],
                "seo_critical": ["name", "url", "potentialAction"]
            },
            "WebPage": {
                "required": ["name"],
                "recommended": [
                    "description", "url", "datePublished", "dateModified",
                    "author", "publisher", "breadcrumb"
                ],
                "optional": ["speakable", "mainEntity", "image"],
                "seo_critical": ["name", "description", "datePublished", "author"]
            },
            "Article": {
                "required": ["headline"],
                "recommended": [
                    "description", "author", "datePublished", "dateModified",
                    "publisher", "image", "articleSection", "keywords"
                ],
                "optional": [
                    "speakable", "wordCount", "articleBody", "backstory"
                ],
                "seo_critical": [
                    "headline", "description", "author", "datePublished",
                    "publisher", "image"
                ]
            },
            "BlogPosting": {
                "required": ["headline"],
                "recommended": [
                    "description", "author", "datePublished", "dateModified"
                ],
                "optional": ["articleBody", "wordCount", "speakable"],
                "seo_critical": ["headline", "author", "datePublished"]
            },
            "Product": {
                "required": ["name"],
                "recommended": [
                    "description", "brand", "offers", "aggregateRating",
                    "image", "sku", "mpn"
                ],
                "optional": [
                    "color", "material", "weight", "dimensions", "reviews"
                ],
                "seo_critical": [
                    "name", "description", "brand", "offers", "aggregateRating"
                ]
            },
            "Service": {
                "required": ["name"],
                "recommended": [
                    "description", "provider", "areaServed", "offers"
                ],
                "optional": [
                    "serviceType", "termsOfService", "availableChannel"
                ],
                "seo_critical": ["name", "description", "provider"]
            },
            "Person": {
                "required": ["name"],
                "recommended": [
                    "description", "jobTitle", "worksFor", "alumniOf", "image"
                ],
                "optional": [
                    "birthDate", "gender", "nationality", "knowsAbout"
                ],
                "seo_critical": ["name", "jobTitle", "worksFor", "image"]
            },
            "FAQPage": {
                "required": ["mainEntity"],
                "recommended": ["name", "description"],
                "optional": ["author", "datePublished"],
                "seo_critical": ["mainEntity"]
            },
            "HowTo": {
                "required": ["name"],
                "recommended": [
                    "description", "step", "totalTime", "estimatedCost"
                ],
                "optional": [
                    "supply", "tool", "image", "video"
                ],
                "seo_critical": ["name", "description", "step"]
            },
            "BreadcrumbList": {
                "required": ["itemListElement"],
                "recommended": ["name"],
                "optional": ["description"],
                "seo_critical": ["itemListElement"]
            }
        }
    
    def _load_validation_rules(self) -> Dict:
        """加载验证规则"""
        return {
            "name": {
                "max_length": 100,
                "min_length": 2,
                "pattern": r"^[^<>]*$",  # 不包含HTML标签
                "description": "名称"
            },
            "description": {
                "max_length": 500,
                "min_length": 10,
                "pattern": r"^[^<>]*$",
                "description": "描述"
            },
            "headline": {
                "max_length": 110,
                "min_length": 5,
                "pattern": r"^[^<>]*$",
                "description": "标题"
            },
            "url": {
                "pattern": r"^https?://",
                "description": "URL"
            },
            "datePublished": {
                "pattern": r"^\d{4}-\d{2}-\d{2}",
                "description": "发布日期"
            },
            "dateModified": {
                "pattern": r"^\d{4}-\d{2}-\d{2}",
                "description": "修改日期"
            }
        }
    
    def validate(self, schema_data: Dict) -> ValidationResult:
        """
        验证Schema数据
        
        Args:
            schema_data: Schema数据
            
        Returns:
            验证结果
        """
        errors = []
        warnings = []
        suggestions = []
        
        # 基本结构检查
        if "@context" not in schema_data:
            errors.append({
                "type": "missing_context",
                "message": "缺少@context字段",
                "severity": "error"
            })
        
        if "@type" not in schema_data:
            errors.append({
                "type": "missing_type",
                "message": "缺少@type字段",
                "severity": "error"
            })
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                suggestions=suggestions,
                completeness_score=0,
                seo_score=0
            )
        
        schema_type = schema_data["@type"]
        
        # 检查Schema类型是否支持
        if schema_type not in self.schema_definitions:
            errors.append({
                "type": "unsupported_schema",
                "message": f"不支持的Schema类型: {schema_type}",
                "severity": "error"
            })
        else:
            definition = self.schema_definitions[schema_type]
            
            # 检查必需属性
            for prop in definition["required"]:
                if prop not in schema_data or not schema_data[prop]:
                    errors.append({
                        "type": "missing_required",
                        "property": prop,
                        "message": f"缺少必需属性: {prop}",
                        "severity": "error"
                    })
            
            # 检查推荐属性
            for prop in definition["recommended"]:
                if prop not in schema_data or not schema_data[prop]:
                    warnings.append({
                        "type": "missing_recommended",
                        "property": prop,
                        "message": f"建议添加属性: {prop}",
                        "severity": "warning"
                    })
            
            # 验证属性值
            for prop, value in schema_data.items():
                if prop.startswith("@"):
                    continue
                    
                if prop in self.validation_rules:
                    rule = self.validation_rules[prop]
                    
                    # 检查长度
                    if isinstance(value, str):
                        if "min_length" in rule and len(value) < rule["min_length"]:
                            warnings.append({
                                "type": "value_too_short",
                                "property": prop,
                                "message": f"{rule['description']}过短（{len(value)}字符），建议至少{rule['min_length']}字符",
                                "severity": "warning"
                            })
                        
                        if "max_length" in rule and len(value) > rule["max_length"]:
                            warnings.append({
                                "type": "value_too_long",
                                "property": prop,
                                "message": f"{rule['description']}过长（{len(value)}字符），建议不超过{rule['max_length']}字符",
                                "severity": "warning"
                            })
                        
                        # 检查模式
                        if "pattern" in rule and not re.match(rule["pattern"], value):
                            warnings.append({
                                "type": "invalid_format",
                                "property": prop,
                                "message": f"{rule['description']}格式不正确",
                                "severity": "warning"
                            })
            
            # 生成建议
            suggestions = self._generate_suggestions(schema_data, definition)
        
        # 计算分数
        completeness = self._calculate_completeness(schema_data, definition if schema_type in self.schema_definitions else {})
        seo_score = self._calculate_seo_score(schema_data, definition if schema_type in self.schema_definitions else {})
        
        return ValidationResult(
            is_valid=len([e for e in errors if e["severity"] == "error"]) == 0,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
            completeness_score=completeness,
            seo_score=seo_score
        )
    
    def _generate_suggestions(self, schema_data: Dict, definition: Dict) -> List[Dict]:
        """生成优化建议"""
        suggestions = []
        
        # 针对特定类型的建议
        schema_type = schema_data.get("@type")
        
        if schema_type == "Article":
            if "speakable" not in schema_data:
                suggestions.append({
                    "type": "add_speakable",
                    "message": "添加speakable属性，支持语音搜索",
                    "priority": "medium"
                })
            
            if "wordCount" not in schema_data:
                suggestions.append({
                    "type": "add_wordcount",
                    "message": "添加wordCount属性，帮助AI理解内容长度",
                    "priority": "low"
                })
        
        elif schema_type == "Organization":
            if "sameAs" not in schema_data:
                suggestions.append({
                    "type": "add_sameas",
                    "message": "添加sameAs属性，链接到社交媒体账号",
                    "priority": "high"
                })
            
            if "knowsAbout" not in schema_data:
                suggestions.append({
                    "type": "add_knowsabout",
                    "message": "添加knowsAbout属性，说明专业领域",
                    "priority": "medium"
                })
        
        elif schema_type == "Product":
            if "aggregateRating" not in schema_data:
                suggestions.append({
                    "type": "add_rating",
                    "message": "添加aggregateRating属性，显示评分信息",
                    "priority": "high"
                })
            
            if "offers" not in schema_data:
                suggestions.append({
                    "type": "add_offers",
                    "message": "添加offers属性，提供价格和库存信息",
                    "priority": "high"
                })
        
        # 通用建议
        if "image" not in schema_data:
            suggestions.append({
                "type": "add_image",
                "message": "添加image属性，提升视觉吸引力",
                "priority": "medium"
            })
        
        return suggestions
    
    def _calculate_completeness(self, schema_data: Dict, definition: Dict) -> float:
        """计算完整度分数"""
        if not definition:
            return 0
        
        required = definition.get("required", [])
        recommended = definition.get("recommended", [])
        
        required_score = sum(1 for prop in required if prop in schema_data and schema_data[prop]) / len(required) if required else 0
        recommended_score = sum(1 for prop in recommended if prop in schema_data and schema_data[prop]) / len(recommended) if recommended else 0
        
        # 必需属性权重60%，推荐属性权重40%
        return (required_score * 0.6 + recommended_score * 0.4) * 100
    
    def _calculate_seo_score(self, schema_data: Dict, definition: Dict) -> float:
        """计算SEO分数"""
        if not definition:
            return 0
        
        seo_critical = definition.get("seo_critical", [])
        
        if not seo_critical:
            return 100
        
        score = sum(1 for prop in seo_critical if prop in schema_data and schema_data[prop]) / len(seo_critical) * 100
        
        # 额外加分项
        extras = ["image", "speakable", "breadcrumb"]
        for extra in extras:
            if extra in schema_data:
                score += 5
        
        return min(100, score)
    
    def fix_schema(self, schema_data: Dict) -> Dict:
        """
        自动修复Schema问题
        
        Args:
            schema_data: 原始Schema数据
            
        Returns:
            修复后的Schema数据
        """
        fixed = schema_data.copy()
        
        # 确保有@context
        if "@context" not in fixed:
            fixed["@context"] = "https://schema.org"
        
        # 确保有@type
        if "@type" not in fixed:
            fixed["@type"] = "WebPage"
        
        schema_type = fixed["@type"]
        
        if schema_type in self.schema_definitions:
            definition = self.schema_definitions[schema_type]
            
            # 为缺失的必需属性添加占位符
            for prop in definition["required"]:
                if prop not in fixed or not fixed[prop]:
                    fixed[prop] = self._get_default_value(prop)
        
        return fixed
    
    def _get_default_value(self, property_name: str) -> Any:
        """获取属性的默认值"""
        defaults = {
            "name": "请填写名称",
            "headline": "请填写标题",
            "description": "请填写描述",
            "url": "https://example.com",
            "datePublished": "2024-01-01",
            "dateModified": "2024-01-01"
        }
        return defaults.get(property_name, "")
    
    def compare_schemas(self, schema1: Dict, schema2: Dict) -> Dict:
        """
        比较两个Schema
        
        Args:
            schema1: 第一个Schema
            schema2: 第二个Schema
            
        Returns:
            比较结果
        """
        result1 = self.validate(schema1)
        result2 = self.validate(schema2)
        
        return {
            "schema1": {
                "type": schema1.get("@type"),
                "valid": result1.is_valid,
                "completeness": result1.completeness_score,
                "seo_score": result1.seo_score
            },
            "schema2": {
                "type": schema2.get("@type"),
                "valid": result2.is_valid,
                "completeness": result2.completeness_score,
                "seo_score": result2.seo_score
            },
            "comparison": {
                "better_completeness": "schema1" if result1.completeness_score > result2.completeness_score else "schema2",
                "better_seo": "schema1" if result1.seo_score > result2.seo_score else "schema2",
                "completeness_difference": abs(result1.completeness_score - result2.completeness_score),
                "seo_difference": abs(result1.seo_score - result2.seo_score)
            }
        }
    
    def generate_schema_template(self, schema_type: str) -> Dict:
        """
        生成Schema模板
        
        Args:
            schema_type: Schema类型
            
        Returns:
            Schema模板
        """
        if schema_type not in self.schema_definitions:
            return {"error": f"不支持的Schema类型: {schema_type}"}
        
        definition = self.schema_definitions[schema_type]
        
        template = {
            "@context": "https://schema.org",
            "@type": schema_type
        }
        
        # 添加必需属性
        for prop in definition["required"]:
            template[prop] = self._get_default_value(prop)
        
        # 添加推荐属性
        for prop in definition["recommended"]:
            template[prop] = self._get_default_value(prop)
        
        return template
    
    def validate_json_ld(self, json_ld_string: str) -> ValidationResult:
        """
        验证JSON-LD字符串
        
        Args:
            json_ld_string: JSON-LD字符串
            
        Returns:
            验证结果
        """
        try:
            # 提取JSON内容
            json_match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', 
                                   json_ld_string, re.DOTALL)
            
            if json_match:
                json_content = json_match.group(1).strip()
            else:
                json_content = json_ld_string.strip()
            
            # 解析JSON
            schema_data = json.loads(json_content)
            
            return self.validate(schema_data)
            
        except json.JSONDecodeError as e:
            return ValidationResult(
                is_valid=False,
                errors=[{
                    "type": "json_parse_error",
                    "message": f"JSON解析错误: {str(e)}",
                    "severity": "error"
                }],
                warnings=[],
                suggestions=[{"type": "fix_json", "message": "检查JSON语法", "priority": "high"}],
                completeness_score=0,
                seo_score=0
            )


if __name__ == "__main__":
    validator = SchemaValidator()
    
    # 测试Schema
    test_schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": "什么是GEO",
        "description": "GEO是生成式引擎优化的简称",
        "author": {
            "@type": "Person",
            "name": "张三"
        },
        "datePublished": "2024-01-15"
    }
    
    print("=" * 60)
    print("Schema验证")
    print("=" * 60)
    
    result = validator.validate(test_schema)
    
    print(f"\n验证结果: {'通过' if result.is_valid else '未通过'}")
    print(f"完整度得分: {result.completeness_score:.1f}%")
    print(f"SEO得分: {result.seo_score:.1f}%")
    
    if result.errors:
        print(f"\n错误 ({len(result.errors)}个):")
        for error in result.errors:
            print(f"  - {error['message']}")
    
    if result.warnings:
        print(f"\n警告 ({len(result.warnings)}个):")
        for warning in result.warnings[:3]:
            print(f"  - {warning['message']}")
    
    if result.suggestions:
        print(f"\n建议 ({len(result.suggestions)}个):")
        for suggestion in result.suggestions:
            print(f"  - {suggestion['message']}")
    
    # 生成模板
    print("\n" + "=" * 60)
    print("生成Organization模板")
    print("=" * 60)
    
    template = validator.generate_schema_template("Organization")
    print(json.dumps(template, ensure_ascii=False, indent=2))
