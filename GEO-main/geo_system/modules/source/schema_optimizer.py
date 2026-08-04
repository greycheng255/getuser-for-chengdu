"""
Schema.org结构化数据优化器
提升AI搜索对结构化数据的识别准确率和信任度
"""

import json
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class SchemaEntity:
    """Schema实体"""
    type: str
    name: str
    description: str
    properties: Dict
    required_properties: List[str]


class SchemaOptimizer:
    """
    Schema.org结构化数据优化器
    
    围绕Schema.org的name和description标签进行语义优化，
    提升AI搜索对结构化数据的识别准确率和信任度
    """
    
    def __init__(self):
        self.schema_types = self._load_schema_types()
        
    def _load_schema_types(self) -> Dict:
        """加载Schema类型定义"""
        return {
            "Organization": {
                "description": "组织实体",
                "required": ["name", "url"],
                "recommended": ["logo", "description", "foundingDate", "address", "contactPoint"],
                "geo_optimized": True
            },
            "WebSite": {
                "description": "网站实体",
                "required": ["name", "url"],
                "recommended": ["description", "potentialAction"],
                "geo_optimized": True
            },
            "WebPage": {
                "description": "网页实体",
                "required": ["name"],
                "recommended": ["description", "url", "datePublished", "dateModified", "author"],
                "geo_optimized": True
            },
            "Article": {
                "description": "文章实体",
                "required": ["headline"],
                "recommended": ["description", "author", "datePublished", "dateModified", "publisher", "image"],
                "geo_optimized": True
            },
            "BlogPosting": {
                "description": "博客文章",
                "required": ["headline"],
                "recommended": ["description", "author", "datePublished", "dateModified"],
                "geo_optimized": True
            },
            "Product": {
                "description": "产品实体",
                "required": ["name"],
                "recommended": ["description", "brand", "offers", "aggregateRating", "image"],
                "geo_optimized": True
            },
            "Service": {
                "description": "服务实体",
                "required": ["name"],
                "recommended": ["description", "provider", "areaServed", "offers"],
                "geo_optimized": True
            },
            "Person": {
                "description": "人物实体",
                "required": ["name"],
                "recommended": ["description", "jobTitle", "worksFor", "alumniOf", "image"],
                "geo_optimized": True
            },
            "FAQPage": {
                "description": "FAQ页面",
                "required": ["mainEntity"],
                "recommended": ["name", "description"],
                "geo_optimized": True
            },
            "HowTo": {
                "description": "操作指南",
                "required": ["name"],
                "recommended": ["description", "step", "totalTime", "estimatedCost"],
                "geo_optimized": True
            }
        }
    
    def optimize_organization(self, org_data: Dict) -> Dict:
        """
        优化Organization结构化数据
        
        Args:
            org_data: 组织原始数据
            
        Returns:
            优化后的Schema数据
        """
        optimized = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": self._optimize_name(org_data.get("name", "")),
            "alternateName": org_data.get("alternate_name"),
            "description": self._optimize_description(
                org_data.get("description", ""),
                target_length=200
            ),
            "url": org_data.get("url"),
            "logo": org_data.get("logo"),
            "foundingDate": org_data.get("founding_date"),
            "founders": self._optimize_persons(org_data.get("founders", [])),
            "address": self._optimize_address(org_data.get("address", {})),
            "contactPoint": self._optimize_contact_points(org_data.get("contacts", [])),
            "sameAs": org_data.get("social_links", []),
            "knowsAbout": org_data.get("expertise_areas", []),
            "hasOfferCatalog": self._optimize_services(org_data.get("services", []))
        }
        
        # 移除空值
        return {k: v for k, v in optimized.items() if v is not None}
    
    def optimize_article(self, article_data: Dict) -> Dict:
        """
        优化Article结构化数据
        
        Args:
            article_data: 文章原始数据
            
        Returns:
            优化后的Schema数据
        """
        optimized = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": self._optimize_headline(article_data.get("title", "")),
            "alternativeHeadline": article_data.get("subtitle"),
            "description": self._optimize_description(
                article_data.get("description", ""),
                target_length=160
            ),
            "image": article_data.get("featured_image"),
            "author": self._optimize_author(article_data.get("author", {})),
            "publisher": self._optimize_publisher(article_data.get("publisher", {})),
            "datePublished": article_data.get("published_date"),
            "dateModified": article_data.get("modified_date") or article_data.get("published_date"),
            "mainEntityOfPage": {
                "@type": "WebPage",
                "@id": article_data.get("url")
            },
            "wordCount": article_data.get("word_count"),
            "articleSection": article_data.get("category"),
            "keywords": article_data.get("tags", []),
            "speakable": {
                "@type": "SpeakableSpecification",
                "cssSelector": [".article-title", ".article-summary"]
            }
        }
        
        return {k: v for k, v in optimized.items() if v is not None}
    
    def optimize_faq(self, faq_data: List[Dict]) -> Dict:
        """
        优化FAQPage结构化数据
        
        Args:
            faq_data: FAQ列表
            
        Returns:
            优化后的Schema数据
        """
        main_entity = []
        for item in faq_data:
            main_entity.append({
                "@type": "Question",
                "name": self._optimize_question(item.get("question", "")),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": self._optimize_answer(item.get("answer", ""))
                }
            })
        
        return {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": main_entity
        }
    
    def optimize_howto(self, howto_data: Dict) -> Dict:
        """
        优化HowTo结构化数据
        
        Args:
            howto_data: 操作指南数据
            
        Returns:
            优化后的Schema数据
        """
        steps = []
        for i, step in enumerate(howto_data.get("steps", []), 1):
            steps.append({
                "@type": "HowToStep",
                "position": i,
                "name": step.get("title", f"步骤{i}"),
                "text": step.get("description", ""),
                "url": step.get("url"),
                "image": step.get("image")
            })
        
        optimized = {
            "@context": "https://schema.org",
            "@type": "HowTo",
            "name": self._optimize_name(howto_data.get("title", "")),
            "description": self._optimize_description(
                howto_data.get("description", ""),
                target_length=200
            ),
            "image": howto_data.get("image"),
            "totalTime": howto_data.get("total_time"),
            "estimatedCost": {
                "@type": "MonetaryAmount",
                "currency": "CNY",
                "value": howto_data.get("cost", "0")
            } if howto_data.get("cost") else None,
            "supply": [{"@type": "HowToSupply", "name": s} for s in howto_data.get("supplies", [])],
            "tool": [{"@type": "HowToTool", "name": t} for t in howto_data.get("tools", [])],
            "step": steps
        }
        
        return {k: v for k, v in optimized.items() if v is not None}
    
    def _optimize_name(self, name: str) -> str:
        """优化name字段"""
        if not name:
            return ""
        
        # 确保名称简洁明了
        name = name.strip()
        
        # 限制长度（SEO最佳实践）
        if len(name) > 60:
            name = name[:57] + "..."
        
        # 确保包含核心关键词
        # 这里可以添加更复杂的逻辑
        
        return name
    
    def _optimize_description(self, description: str, target_length: int = 160) -> str:
        """优化description字段"""
        if not description:
            return ""
        
        # 清理文本
        description = description.strip()
        description = description.replace('\n', ' ')
        description = ' '.join(description.split())  # 移除多余空格
        
        # 调整长度
        if len(description) > target_length:
            # 在句子边界截断
            truncated = description[:target_length]
            last_period = max(truncated.rfind('。'), truncated.rfind('.'), truncated.rfind('！'))
            if last_period > target_length * 0.7:
                description = truncated[:last_period + 1]
            else:
                description = truncated[:target_length-3] + "..."
        
        return description
    
    def _optimize_headline(self, headline: str) -> str:
        """优化headline字段"""
        return self._optimize_name(headline)
    
    def _optimize_question(self, question: str) -> str:
        """优化FAQ问题"""
        if not question:
            return ""
        
        # 确保是问句形式
        question = question.strip()
        if not question.endswith('？') and not question.endswith('?'):
            question += '？'
        
        # 限制长度
        if len(question) > 100:
            question = question[:97] + "...？"
        
        return question
    
    def _optimize_answer(self, answer: str) -> str:
        """优化FAQ答案"""
        if not answer:
            return ""
        
        # 清理文本
        answer = answer.strip()
        
        # 确保答案完整但简洁
        if len(answer) > 500:
            # 在句子边界截断
            truncated = answer[:500]
            last_period = max(truncated.rfind('。'), truncated.rfind('.'), truncated.rfind('！'))
            if last_period > 400:
                answer = truncated[:last_period + 1]
            else:
                answer = truncated[:497] + "..."
        
        return answer
    
    def _optimize_persons(self, persons: List[Dict]) -> List[Dict]:
        """优化人物列表"""
        return [
            {
                "@type": "Person",
                "name": p.get("name"),
                "jobTitle": p.get("title"),
                "description": p.get("bio", "")[:100] if p.get("bio") else None
            }
            for p in persons if p.get("name")
        ]
    
    def _optimize_address(self, address: Dict) -> Optional[Dict]:
        """优化地址信息"""
        if not address:
            return None
        
        return {
            "@type": "PostalAddress",
            "streetAddress": address.get("street"),
            "addressLocality": address.get("city"),
            "addressRegion": address.get("region"),
            "postalCode": address.get("postal_code"),
            "addressCountry": address.get("country", "CN")
        }
    
    def _optimize_contact_points(self, contacts: List[Dict]) -> List[Dict]:
        """优化联系信息"""
        return [
            {
                "@type": "ContactPoint",
                "contactType": c.get("type", "customer service"),
                "telephone": c.get("phone"),
                "email": c.get("email"),
                "availableLanguage": c.get("language", ["Chinese", "English"])
            }
            for c in contacts
        ]
    
    def _optimize_author(self, author: Dict) -> Dict:
        """优化作者信息"""
        if not author:
            return {"@type": "Organization", "name": "Unknown"}
        
        return {
            "@type": "Person" if author.get("type") == "person" else "Organization",
            "name": author.get("name"),
            "url": author.get("url"),
            "description": author.get("bio", "")[:100] if author.get("bio") else None
        }
    
    def _optimize_publisher(self, publisher: Dict) -> Dict:
        """优化发布者信息"""
        if not publisher:
            return {"@type": "Organization", "name": "Unknown"}
        
        return {
            "@type": "Organization",
            "name": publisher.get("name"),
            "logo": {
                "@type": "ImageObject",
                "url": publisher.get("logo")
            } if publisher.get("logo") else None
        }
    
    def _optimize_services(self, services: List[Dict]) -> Optional[Dict]:
        """优化服务目录"""
        if not services:
            return None
        
        return {
            "@type": "OfferCatalog",
            "name": "Services",
            "itemListElement": [
                {
                    "@type": "Offer",
                    "itemOffered": {
                        "@type": "Service",
                        "name": s.get("name"),
                        "description": s.get("description", "")[:100]
                    }
                }
                for s in services
            ]
        }
    
    def generate_schema_markup(self, page_type: str, data: Dict) -> str:
        """
        生成Schema.org标记代码
        
        Args:
            page_type: 页面类型
            data: 页面数据
            
        Returns:
            JSON-LD格式的Schema标记
        """
        schema_data = None
        
        if page_type == "organization":
            schema_data = self.optimize_organization(data)
        elif page_type == "article":
            schema_data = self.optimize_article(data)
        elif page_type == "faq":
            schema_data = self.optimize_faq(data)
        elif page_type == "howto":
            schema_data = self.optimize_howto(data)
        
        if schema_data:
            return f"""<script type="application/ld+json">
{json.dumps(schema_data, ensure_ascii=False, indent=2)}
</script>"""
        
        return ""
    
    def validate_schema(self, schema_data: Dict) -> Dict:
        """
        验证Schema数据完整性
        
        Args:
            schema_data: Schema数据
            
        Returns:
            验证结果
        """
        schema_type = schema_data.get("@type", "")
        type_info = self.schema_types.get(schema_type, {})
        
        required_props = type_info.get("required", [])
        recommended_props = type_info.get("recommended", [])
        
        missing_required = [p for p in required_props if p not in schema_data or not schema_data[p]]
        missing_recommended = [p for p in recommended_props if p not in schema_data or not schema_data[p]]
        
        return {
            "valid": len(missing_required) == 0,
            "schema_type": schema_type,
            "missing_required": missing_required,
            "missing_recommended": missing_recommended,
            "completeness_score": (
                (len(required_props) - len(missing_required)) / len(required_props) * 0.6 +
                (len(recommended_props) - len(missing_recommended)) / len(recommended_props) * 0.4
            ) * 100 if required_props else 0
        }


if __name__ == "__main__":
    optimizer = SchemaOptimizer()
    
    # 测试Organization优化
    org_data = {
        "name": "智媒科技",
        "description": "智媒科技是一家专注于AI营销技术解决方案的创新企业，致力于帮助企业在AI搜索时代获得更好的品牌可见性。我们提供GEO优化、内容策略和数据分析等全方位服务。",
        "url": "https://www.zhimei.tech",
        "founding_date": "2023-01-15",
        "expertise_areas": ["GEO", "AI营销", "内容策略", "数据分析"],
        "social_links": [
            "https://weibo.com/zhimeitech",
            "https://www.linkedin.com/company/zhimeitech"
        ]
    }
    
    optimized_org = optimizer.optimize_organization(org_data)
    print("Organization Schema:")
    print(json.dumps(optimized_org, ensure_ascii=False, indent=2))
    
    # 验证
    validation = optimizer.validate_schema(optimized_org)
    print(f"\n验证结果: 完整度得分 {validation['completeness_score']:.1f}%")
