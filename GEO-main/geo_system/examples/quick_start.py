"""
GEO系统快速入门示例
演示如何使用GEO内容工程系统
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.content_generator import GEOArticleGenerator
from core.content_optimizer import GEOContentOptimizer
from core.rag_engine import RAGEngine, GEOKnowledgeBuilder
from modules.source.authority_builder import AuthorityBuilder
from modules.source.schema_optimizer import SchemaOptimizer
from modules.data.metrics_tracker import GEOMetricsTracker, GEOMetrics
from utils.content_analyzer import ContentAnalyzer
from datetime import datetime


def demo_content_generation():
    """演示内容生成"""
    print("=" * 60)
    print("演示1: GEO文章生成")
    print("=" * 60)
    
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
    
    print(f"\n文章标题: {result['title']}")
    print(f"\n文章大纲:")
    for item in result['outline']:
        indent = "  " * (item['level'] - 1)
        print(f"{indent}- {item['title']}")
    
    print(f"\n生成的提示词长度: {len(result['prompt'])} 字符")
    print("\n提示词已准备就绪，可以发送给AI模型生成文章。")
    
    return result


def demo_content_optimization():
    """演示内容优化"""
    print("\n" + "=" * 60)
    print("演示2: 内容优化分析")
    print("=" * 60)
    
    optimizer = GEOContentOptimizer()
    
    sample_content = """
GEO是一种新的优化方法。它帮助企业提升在AI搜索中的可见性。

很多企业已经开始使用这种方法了。未来GEO会变得越来越重要。

根据一些数据显示，GEO效果很好。专家建议企业应该关注这个趋势。
"""
    
    analysis = optimizer.analyze(sample_content)
    
    print(f"\n内容分析结果:")
    print(f"  整体评分: {analysis['overall_score']:.1f}/100")
    print(f"  结构评分: {analysis['structure_score']:.1f}/100")
    print(f"  引用评分: {analysis['citation_score']:.1f}/100")
    print(f"  可读性评分: {analysis['readability_score']:.1f}/100")
    print(f"  权威性评分: {analysis['authority_score']:.1f}/100")
    
    if analysis['issues']:
        print(f"\n发现的问题:")
        for issue in analysis['issues']:
            print(f"  - {issue}")
    
    if analysis['strengths']:
        print(f"\n内容优势:")
        for strength in analysis['strengths']:
            print(f"  - {strength}")
    
    # 优化内容
    print("\n正在进行内容优化...")
    optimization_result = optimizer.optimize(sample_content, optimization_level="medium")
    
    print(f"优化前得分: {optimization_result.score_before:.1f}")
    print(f"优化后得分: {optimization_result.score_after:.1f}")
    print(f"改进了: {optimization_result.score_after - optimization_result.score_before:.1f} 分")


def demo_knowledge_base():
    """演示知识库构建"""
    print("\n" + "=" * 60)
    print("演示3: 知识库构建")
    print("=" * 60)
    
    engine = RAGEngine()
    builder = GEOKnowledgeBuilder(engine)
    
    # 添加实体
    print("\n添加知识实体...")
    builder.add_entity(
        name="GEO",
        definition="生成式引擎优化（Generative Engine Optimization）",
        attributes={
            "全称": "Generative Engine Optimization",
            "提出时间": "2023年",
            "核心目标": "提升AI引用率",
            "与传统SEO的区别": "从排名优化转向答案优化"
        }
    )
    
    builder.add_entity(
        name="RAG",
        definition="检索增强生成（Retrieval-Augmented Generation）",
        attributes={
            "全称": "Retrieval-Augmented Generation",
            "核心组件": ["检索器", "生成器"],
            "应用场景": "AI搜索、问答系统"
        }
    )
    
    # 添加关系
    print("添加知识关系...")
    builder.add_relation(
        entity1="GEO",
        relation_type="基于",
        entity2="RAG",
        description="GEO的优化策略基于对RAG机制的理解"
    )
    
    # 添加证据
    print("添加数据证据...")
    builder.add_evidence(
        claim="GEO能显著提升品牌AI可见性",
        evidence="实施GEO策略的企业AI引用率平均提升40%，品牌提及率提升35%",
        source="Princeton GEO Research 2024",
        evidence_type="研究数据"
    )
    
    # 查询知识
    print("\n查询知识库...")
    knowledge = builder.query_for_article("GEO优化")
    
    print(f"找到实体: {len(knowledge['entities'])} 个")
    print(f"找到关系: {len(knowledge['relations'])} 个")
    print(f"找到证据: {len(knowledge['evidence'])} 个")
    
    if knowledge['entities']:
        print(f"\n实体示例: {knowledge['entities'][0][:100]}...")


def demo_authority_building():
    """演示信源建设"""
    print("\n" + "=" * 60)
    print("演示4: 信源权威建设")
    print("=" * 60)
    
    builder = AuthorityBuilder()
    
    # 获取信源金字塔
    pyramid = builder.get_authority_pyramid()
    print(f"\n{pyramid['name']}")
    print(f"说明: {pyramid['description']}")
    
    print("\n四级信源权威体系:")
    for level, info in pyramid['levels'].items():
        print(f"  第{level}级: {info['name']}")
        print(f"    权重: {info['weight']}")
        print(f"    说明: {info['description']}")
    
    # 官网建设方案
    print("\n官网权威化改造方案:")
    official_plan = builder.build_official_site_authority({
        "name": "智媒科技",
        "url": "https://www.zhimei.tech",
        "description": "AI营销技术解决方案提供商"
    })
    
    print(f"  方案名称: {official_plan['name']}")
    print(f"  优先级: {official_plan['priority']}")
    print(f"  包含组件: {len(official_plan['components'])}")
    
    for component_name, component in official_plan['components'].items():
        print(f"    - {component['name']}: {len(component['tasks'])} 项任务")


def demo_schema_optimization():
    """演示Schema优化"""
    print("\n" + "=" * 60)
    print("演示5: Schema.org结构化数据优化")
    print("=" * 60)
    
    optimizer = SchemaOptimizer()
    
    # 优化Organization
    org_data = {
        "name": "智媒科技",
        "alternate_name": "Zhimei Tech",
        "description": "智媒科技是一家专注于AI营销技术解决方案的创新企业，致力于帮助企业在AI搜索时代获得更好的品牌可见性。我们提供GEO优化、内容策略和数据分析等全方位服务。",
        "url": "https://www.zhimei.tech",
        "logo": "https://www.zhimei.tech/logo.png",
        "founding_date": "2023-01-15",
        "expertise_areas": ["GEO", "AI营销", "内容策略", "数据分析"],
        "social_links": [
            "https://weibo.com/zhimeitech",
            "https://www.linkedin.com/company/zhimeitech"
        ],
        "address": {
            "city": "北京",
            "country": "CN"
        }
    }
    
    optimized_org = optimizer.optimize_organization(org_data)
    
    print("\nOrganization Schema优化结果:")
    print(f"  名称: {optimized_org.get('name')}")
    print(f"  描述长度: {len(optimized_org.get('description', ''))} 字符")
    print(f"  包含属性: {len(optimized_org)} 个")
    
    # 验证Schema
    validation = optimizer.validate_schema(optimized_org)
    print(f"\nSchema验证结果:")
    print(f"  有效性: {'通过' if validation['valid'] else '未通过'}")
    print(f"  完整度得分: {validation['completeness_score']:.1f}%")
    
    if validation['missing_required']:
        print(f"  缺失必需属性: {validation['missing_required']}")
    if validation['missing_recommended']:
        print(f"  缺失推荐属性: {len(validation['missing_recommended'])} 个")


def demo_metrics_tracking():
    """演示指标追踪"""
    print("\n" + "=" * 60)
    print("演示6: GEO指标监测")
    print("=" * 60)
    
    tracker = GEOMetricsTracker(storage_path="demo_metrics.json")
    
    # 记录示例数据
    print("\n记录示例指标数据...")
    sample_metrics = GEOMetrics(
        date=datetime.now().isoformat(),
        ai_citation_count=25,
        brand_mention_count=40,
        answer_space_coverage=0.45,
        source_diversity_score=0.7,
        content_quality_score=0.85,
        citations_by_platform={
            "chatgpt": 10,
            "perplexity": 8,
            "google_ai": 7
        },
        mentions_by_source={
            "官网": 15,
            "知乎": 12,
            "微信公众号": 13
        },
        top_queries=[
            "什么是GEO",
            "GEO和SEO的区别",
            "如何优化AI搜索"
        ]
    )
    
    tracker.record_metrics(sample_metrics)
    
    # 生成报告
    print("\n生成月度报告...")
    report = tracker.generate_report("monthly")
    
    print(f"\n报告概览:")
    basic = report['basic_metrics']
    print(f"  AI引用率: {basic['ai_citation_rate']['current']:.1f}")
    print(f"  品牌提及率: {basic['brand_mention_rate']['current']:.1f}")
    print(f"  答案空间覆盖率: {basic['answer_space_coverage']['current']:.1%}")
    print(f"  综合可见性得分: {basic['visibility_score']['current']:.1f}")
    
    quality = report['quality_metrics']
    print(f"\n质量指标:")
    print(f"  信源多样性得分: {quality['source_diversity']['score']:.2f}")
    print(f"  内容质量得分: {quality['content_quality']['score']:.2f}")
    print(f"  热门查询数: {quality['query_insights']['query_count']}")
    
    print(f"\n优化建议: {len(report['recommendations'])} 条")
    for rec in report['recommendations'][:3]:
        print(f"  [{rec['priority']}] {rec['suggestion']}")


def demo_content_analysis():
    """演示内容分析"""
    print("\n" + "=" * 60)
    print("演示7: 内容质量分析")
    print("=" * 60)
    
    analyzer = ContentAnalyzer()
    
    sample_content = """
# 什么是生成式引擎优化（GEO）

生成式引擎优化（GEO）是一种针对AI搜索引擎的内容优化方法。它与传统SEO有着本质的区别。

## GEO与传统SEO的区别

传统SEO关注的是关键词排名，而GEO关注的是成为AI答案的一部分。根据2024年普林斯顿大学的研究显示，实施GEO策略的企业AI引用率平均提升了40%。

这意味着什么？意味着用户不再需要通过点击链接来获取信息，而是直接从AI的回答中了解你的品牌。

## 如何开始GEO

首先，你需要理解ERE框架：
- Entity（实体）：明确你的品牌和产品
- Relation（关系）：建立与相关概念的联系
- Evidence（证据）：用数据支撑你的观点

其次，优化你的内容结构。AI更喜欢结构清晰、逻辑严密的内容。

## 成功案例

某B2B软件公司在实施GEO策略6个月后，其品牌在ChatGPT回答中的提及率从5%提升到了35%。

## 总结

GEO不是未来，而是现在。越早开始，越能抢占先机。
"""
    
    print("\n分析示例内容...")
    result = analyzer.analyze(sample_content)
    
    print(f"\n分析结果:")
    print(f"  整体得分: {result.overall_score}/100")
    print(f"  结构得分: {result.structure_score}/100")
    print(f"  引用得分: {result.citation_score}/100")
    print(f"  可读性得分: {result.readability_score}/100")
    print(f"  权威性得分: {result.authority_score}/100")
    print(f"  GEO合规性: {result.geo_compliance}/100")
    
    if result.issues:
        print(f"\n发现的问题 ({len(result.issues)}个):")
        for issue in result.issues[:3]:
            print(f"  - {issue}")
    
    if result.suggestions:
        print(f"\n优化建议 ({len(result.suggestions)}个):")
        for suggestion in result.suggestions[:5]:
            print(f"  - {suggestion}")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("GEO内容工程系统 - 快速入门演示")
    print("=" * 60)
    print("\n本演示将展示GEO系统的核心功能：")
    print("1. GEO文章生成")
    print("2. 内容优化分析")
    print("3. 知识库构建")
    print("4. 信源权威建设")
    print("5. Schema结构化数据优化")
    print("6. GEO指标监测")
    print("7. 内容质量分析")
    print("\n" + "=" * 60)
    
    try:
        # 运行所有演示
        demo_content_generation()
        demo_content_optimization()
        demo_knowledge_base()
        demo_authority_building()
        demo_schema_optimization()
        demo_metrics_tracking()
        demo_content_analysis()
        
        print("\n" + "=" * 60)
        print("所有演示完成！")
        print("=" * 60)
        print("\n下一步建议:")
        print("1. 根据生成的提示词，使用AI模型生成第一篇GEO文章")
        print("2. 使用内容分析器评估现有内容质量")
        print("3. 按照信源金字塔建设四级权威体系")
        print("4. 部署Schema.org结构化数据")
        print("5. 建立GEO指标监测体系")
        print("\n记住GEO的核心理念：不要争排名，要争引用。")
        
    except Exception as e:
        print(f"\n演示过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
