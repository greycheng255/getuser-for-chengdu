"""
GEO工作流示例
展示完整的GEO内容生产流程
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.content_generator import GEOArticleGenerator
from core.content_optimizer import GEOContentOptimizer
from core.rag_engine import RAGEngine, GEOKnowledgeBuilder
from modules.source.authority_builder import AuthorityBuilder
from modules.source.platform_distributor import PlatformDistributor
from modules.source.schema_optimizer import SchemaOptimizer
from modules.data.metrics_tracker import GEOMetricsTracker, GEOMetrics
from modules.data.roi_calculator import ROICalculator
from utils.content_analyzer import ContentAnalyzer
from utils.citation_optimizer import CitationOptimizer
from datetime import datetime


class GEOWorkflow:
    """
    GEO完整工作流
    
    从内容规划到发布的完整流程
    """
    
    def __init__(self):
        self.generator = GEOArticleGenerator()
        self.optimizer = GEOContentOptimizer()
        self.rag_engine = RAGEngine()
        self.knowledge_builder = GEOKnowledgeBuilder(self.rag_engine)
        self.authority_builder = AuthorityBuilder()
        self.platform_distributor = PlatformDistributor()
        self.schema_optimizer = SchemaOptimizer()
        self.metrics_tracker = GEOMetricsTracker()
        self.roi_calculator = ROICalculator()
        self.content_analyzer = ContentAnalyzer()
        self.citation_optimizer = CitationOptimizer()
    
    def run_full_workflow(self, topic: str, brand_info: Dict):
        """
        运行完整工作流
        
        Args:
            topic: 文章主题
            brand_info: 品牌信息
            
        Returns:
            工作流结果
        """
        print("=" * 70)
        print("GEO内容工程工作流")
        print("=" * 70)
        
        results = {
            "topic": topic,
            "start_time": datetime.now().isoformat(),
            "steps": []
        }
        
        # 步骤1: 知识库准备
        print("\n📚 步骤1: 准备知识库")
        print("-" * 70)
        knowledge_result = self._prepare_knowledge_base(topic)
        results["steps"].append({"step": 1, "name": "知识库准备", "result": knowledge_result})
        
        # 步骤2: 内容生成
        print("\n✍️ 步骤2: 生成内容大纲")
        print("-" * 70)
        generation_result = self._generate_content(topic, brand_info)
        results["steps"].append({"step": 2, "name": "内容生成", "result": generation_result})
        
        # 步骤3: 内容优化
        print("\n🔧 步骤3: 优化内容")
        print("-" * 70)
        # 模拟内容
        sample_content = self._create_sample_content(topic)
        optimization_result = self._optimize_content(sample_content)
        results["steps"].append({"step": 3, "name": "内容优化", "result": optimization_result})
        
        # 步骤4: 引用优化
        print("\n📖 步骤4: 优化引用")
        print("-" * 70)
        citation_result = self._optimize_citations(sample_content)
        results["steps"].append({"step": 4, "name": "引用优化", "result": citation_result})
        
        # 步骤5: 平台适配
        print("\n📱 步骤5: 平台适配")
        print("-" * 70)
        distribution_result = self._plan_distribution(sample_content)
        results["steps"].append({"step": 5, "name": "平台适配", "result": distribution_result})
        
        # 步骤6: Schema优化
        print("\n🏗️ 步骤6: Schema结构化数据")
        print("-" * 70)
        schema_result = self._optimize_schema(brand_info)
        results["steps"].append({"step": 6, "name": "Schema优化", "result": schema_result})
        
        # 步骤7: 效果预测
        print("\n📊 步骤7: ROI预测")
        print("-" * 70)
        roi_result = self._predict_roi()
        results["steps"].append({"step": 7, "name": "ROI预测", "result": roi_result})
        
        # 步骤8: 生成发布清单
        print("\n✅ 步骤8: 生成发布清单")
        print("-" * 70)
        checklist = self._generate_checklist()
        results["steps"].append({"step": 8, "name": "发布清单", "result": checklist})
        
        results["end_time"] = datetime.now().isoformat()
        
        print("\n" + "=" * 70)
        print("工作流完成！")
        print("=" * 70)
        
        return results
    
    def _prepare_knowledge_base(self, topic: str) -> Dict:
        """准备知识库"""
        # 添加核心实体
        self.knowledge_builder.add_entity(
            name=topic,
            definition=f"关于{topic}的核心概念",
            attributes={
                "重要性": "高",
                "适用场景": "AI搜索优化"
            }
        )
        
        # 添加相关证据
        self.knowledge_builder.add_evidence(
            claim=f"{topic}对企业至关重要",
            evidence="相关数据显示效果显著",
            source="行业研究",
            evidence_type="研究数据"
        )
        
        # 查询相关知识
        knowledge = self.knowledge_builder.query_for_article(topic)
        
        print(f"✓ 已添加 {len(knowledge['entities'])} 个实体到知识库")
        print(f"✓ 已添加 {len(knowledge['relations'])} 个关系到知识库")
        print(f"✓ 已添加 {len(knowledge['evidence'])} 条证据到知识库")
        
        return {
            "entities_count": len(knowledge['entities']),
            "relations_count": len(knowledge['relations']),
            "evidence_count": len(knowledge['evidence'])
        }
    
    def _generate_content(self, topic: str, brand_info: Dict) -> Dict:
        """生成内容"""
        result = self.generator.generate(
            title=f"什么是{topic}：AI搜索时代的必备指南",
            brand_info=brand_info,
            target_platform="chatgpt",
            word_count=3000
        )
        
        print(f"✓ 已生成文章大纲，包含 {len(result['outline'])} 个章节")
        print(f"✓ 提示词长度: {len(result['prompt'])} 字符")
        print(f"\n文章结构:")
        for item in result['outline'][:5]:
            indent = "  " * (item['level'] - 1)
            print(f"{indent}- {item['title']}")
        if len(result['outline']) > 5:
            print(f"  ... 还有 {len(result['outline']) - 5} 个章节")
        
        return {
            "outline_count": len(result['outline']),
            "prompt_length": len(result['prompt']),
            "target_platform": result['config'].target_platform
        }
    
    def _create_sample_content(self, topic: str) -> str:
        """创建示例内容"""
        return f"""
# 什么是{topic}

{topic}是一种针对AI搜索引擎的内容优化方法。

## 为什么{topic}很重要

根据2024年的研究显示，超过60%的用户开始使用AI搜索。

## 如何实施{topic}

首先，你需要理解ERE框架。其次，优化你的内容结构。

## 成功案例

某公司在实施{topic}后业绩提升了2倍。

## 总结

{topic}是未来的趋势。
"""
    
    def _optimize_content(self, content: str) -> Dict:
        """优化内容"""
        analysis = self.content_analyzer.analyze(content)
        
        print(f"✓ 内容分析完成")
        print(f"  - 整体得分: {analysis.overall_score}/100")
        print(f"  - 结构得分: {analysis.structure_score}/100")
        print(f"  - 引用得分: {analysis.citation_score}/100")
        print(f"  - 可读性得分: {analysis.readability_score}/100")
        
        if analysis.issues:
            print(f"\n  发现 {len(analysis.issues)} 个问题:")
            for issue in analysis.issues[:2]:
                print(f"    - {issue}")
        
        if analysis.suggestions:
            print(f"\n  优化建议:")
            for suggestion in analysis.suggestions[:2]:
                print(f"    - {suggestion}")
        
        return {
            "overall_score": analysis.overall_score,
            "structure_score": analysis.structure_score,
            "citation_score": analysis.citation_score,
            "issues_count": len(analysis.issues),
            "suggestions_count": len(analysis.suggestions)
        }
    
    def _optimize_citations(self, content: str) -> Dict:
        """优化引用"""
        analysis = self.citation_optimizer.analyze_citations(content)
        
        print(f"✓ 引用分析完成")
        print(f"  - 引用总数: {analysis['total_citations']}")
        print(f"  - 统计数据: {analysis['total_statistics']} 个")
        print(f"  - 平均可信度: {analysis['avg_credibility']:.2f}")
        
        if analysis['issues']:
            print(f"\n  需要改进:")
            for issue in analysis['issues'][:2]:
                print(f"    - {issue['description']}")
        
        return {
            "total_citations": analysis['total_citations'],
            "total_statistics": analysis['total_statistics'],
            "avg_credibility": analysis['avg_credibility'],
            "issues_count": len(analysis['issues'])
        }
    
    def _plan_distribution(self, content: str) -> Dict:
        """规划分发"""
        plans = self.platform_distributor.create_distribution_plan(
            content,
            platforms=["wechat", "zhihu", "weibo", "linkedin"]
        )
        
        print(f"✓ 已创建 {len(plans)} 个平台的分发计划")
        
        total_reach = sum(plan.expected_reach for plan in plans)
        print(f"\n  预计总触达: {total_reach:,} 人")
        
        print(f"\n  分发计划:")
        for plan in plans:
            platform_config = self.platform_distributor.platforms.get(plan.platform)
            print(f"    - {platform_config.name}: {plan.expected_reach:,} 人")
        
        return {
            "platforms_count": len(plans),
            "total_reach": total_reach,
            "platforms": [plan.platform for plan in plans]
        }
    
    def _optimize_schema(self, brand_info: Dict) -> Dict:
        """优化Schema"""
        org_data = {
            "name": brand_info.get("name", "品牌名"),
            "description": brand_info.get("description", "品牌描述"),
            "url": brand_info.get("website", "https://example.com"),
            "logo": "https://example.com/logo.png",
            "founding_date": "2023-01-01",
            "expertise_areas": brand_info.get("expertise", ["GEO", "AI营销"])
        }
        
        schema = self.schema_optimizer.optimize_organization(org_data)
        markup = self.schema_optimizer.generate_schema_markup("organization", org_data)
        
        print(f"✓ Schema.org结构化数据已生成")
        print(f"  - 类型: Organization")
        print(f"  - 包含属性: {len(schema)} 个")
        
        return {
            "schema_type": "Organization",
            "properties_count": len(schema),
            "markup_length": len(markup)
        }
    
    def _predict_roi(self) -> Dict:
        """预测ROI"""
        # 添加投资
        self.roi_calculator.add_investment("content", 5000, "内容创作")
        self.roi_calculator.add_investment("promotion", 3000, "推广费用")
        
        # 添加回报
        self.roi_calculator.add_return("leads", 20000, "线索价值", 0.4)
        self.roi_calculator.add_return("brand", 10000, "品牌价值", 0.6)
        
        metrics = self.roi_calculator.calculate_roi()
        
        print(f"✓ ROI预测完成")
        print(f"  - 预计投资: ¥{metrics.total_investment:,.0f}")
        print(f"  - 预计回报: ¥{metrics.geo_attributed_return:,.0f}")
        print(f"  - ROI: {metrics.roi_ratio:.2f} ({metrics.roi_ratio * 100:.0f}%)")
        print(f"  - 回收期: {metrics.payback_period:.1f} 个月")
        
        return {
            "investment": metrics.total_investment,
            "return": metrics.geo_attributed_return,
            "roi_ratio": metrics.roi_ratio,
            "payback_period": metrics.payback_period
        }
    
    def _generate_checklist(self) -> Dict:
        """生成检查清单"""
        checklist = {
            "content_structure": [
                "标题包含核心关键词，60字以内",
                "有清晰的H1/H2/H3层级结构",
                "段落长度适中（3-8句话）",
                "使用了列表、表格等结构化元素"
            ],
            "ere_framework": [
                "明确定义了核心实体（Entity）",
                "阐述了实体之间的关系（Relation）",
                "提供了数据/案例作为证据（Evidence）"
            ],
            "citation_optimization": [
                "包含3-5个权威来源引用",
                "包含3-5个统计数据",
                "包含1-2个专家引言",
                "所有数据都有来源标注"
            ],
            "platform_optimization": [
                "已为各平台适配内容",
                "添加了适当的标签/话题",
                "选择了最佳发布时间"
            ],
            "technical_optimization": [
                "添加了Schema.org结构化数据",
                "图片有alt标签",
                "元数据完整"
            ]
        }
        
        print(f"✓ 发布检查清单已生成")
        print(f"  - 内容结构检查项: {len(checklist['content_structure'])} 个")
        print(f"  - ERE框架检查项: {len(checklist['ere_framework'])} 个")
        print(f"  - 引用优化检查项: {len(checklist['citation_optimization'])} 个")
        print(f"  - 平台优化检查项: {len(checklist['platform_optimization'])} 个")
        print(f"  - 技术优化检查项: {len(checklist['technical_optimization'])} 个")
        
        total_items = sum(len(items) for items in checklist.values())
        print(f"\n  总计: {total_items} 个检查项")
        
        return {
            "total_items": total_items,
            "categories": len(checklist),
            "checklist": checklist
        }


def main():
    """主函数"""
    workflow = GEOWorkflow()
    
    brand_info = {
        "name": "智媒科技",
        "industry": "AI营销",
        "expertise": ["GEO", "AI搜索优化", "内容营销"],
        "description": "专注于AI时代的营销技术解决方案",
        "website": "https://www.zhimei.tech"
    }
    
    results = workflow.run_full_workflow("GEO优化", brand_info)
    
    # 保存结果
    import json
    with open("geo_workflow_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 结果已保存到 geo_workflow_results.json")


if __name__ == "__main__":
    main()
