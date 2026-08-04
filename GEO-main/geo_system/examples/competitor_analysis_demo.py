"""
竞争对手GEO分析示例
演示如何分析竞争对手的GEO策略
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.data.competitor_analyzer import CompetitorAnalyzer
from typing import Dict, List
import json


def demo_competitor_analysis():
    """演示竞争对手分析"""
    
    print("=" * 60)
    print("竞争对手GEO分析演示")
    print("=" * 60)
    
    # 初始化分析器
    analyzer = CompetitorAnalyzer()
    
    # 定义你的品牌
    my_brand = {
        'name': '智媒科技',
        'domain': 'zhimei.tech',
        'industry': 'AI营销',
        'strengths': ['技术创新', '客户服务', '行业经验']
    }
    
    # 定义竞争对手
    competitors = [
        {
            'name': '竞品A公司',
            'domain': 'competitor-a.com',
            'industry': 'AI营销',
            'description': '老牌营销公司，客户基础广泛'
        },
        {
            'name': '竞品B科技',
            'domain': 'competitor-b.tech',
            'industry': 'AI营销',
            'description': '新兴技术公司，产品创新性强'
        },
        {
            'name': '竞品C咨询',
            'domain': 'competitor-c.com',
            'industry': 'AI营销',
            'description': '咨询公司背景，策略能力强'
        }
    ]
    
    # 模拟分析数据（实际应用中应从API或爬虫获取）
    competitor_data = {
        'competitor-a.com': {
            'ai_citation_count': 120,
            'brand_mention_count': 200,
            'content_volume': 500,
            'avg_content_quality': 75,
            'schema_adoption_rate': 0.6,
            'source_diversity': 0.7,
            'platform_presence': {
                'chatgpt': 45,
                'perplexity': 35,
                'google_ai': 40
            },
            'top_keywords': [
                '数字营销', 'AI营销', '内容策略', '品牌营销'
            ],
            'content_types': {
                'blog': 200,
                'whitepaper': 50,
                'case_study': 100,
                'video': 150
            }
        },
        'competitor-b.tech': {
            'ai_citation_count': 80,
            'brand_mention_count': 150,
            'content_volume': 300,
            'avg_content_quality': 85,
            'schema_adoption_rate': 0.8,
            'source_diversity': 0.5,
            'platform_presence': {
                'chatgpt': 30,
                'perplexity': 25,
                'google_ai': 25
            },
            'top_keywords': [
                'AI技术', '营销自动化', '数据分析', '增长黑客'
            ],
            'content_types': {
                'blog': 150,
                'whitepaper': 80,
                'case_study': 40,
                'video': 30
            }
        },
        'competitor-c.com': {
            'ai_citation_count': 150,
            'brand_mention_count': 250,
            'content_volume': 400,
            'avg_content_quality': 70,
            'schema_adoption_rate': 0.4,
            'source_diversity': 0.8,
            'platform_presence': {
                'chatgpt': 55,
                'perplexity': 45,
                'google_ai': 50
            },
            'top_keywords': [
                '营销策略', '品牌咨询', '市场研究', '数字化转型'
            ],
            'content_types': {
                'blog': 100,
                'whitepaper': 120,
                'case_study': 150,
                'video': 30
            }
        }
    }
    
    # 你的品牌数据（模拟）
    my_data = {
        'ai_citation_count': 60,
        'brand_mention_count': 100,
        'content_volume': 200,
        'avg_content_quality': 80,
        'schema_adoption_rate': 0.7,
        'source_diversity': 0.6,
        'platform_presence': {
            'chatgpt': 25,
            'perplexity': 20,
            'google_ai': 15
        },
        'top_keywords': [
            'GEO', '生成式引擎优化', 'AI搜索', '内容营销'
        ],
        'content_types': {
            'blog': 100,
            'whitepaper': 30,
            'case_study': 50,
            'video': 20
        }
    }
    
    print("\n📊 正在分析竞争对手...")
    print("-" * 60)
    
    # 分析每个竞争对手
    analysis_results = []
    for competitor in competitors:
        domain = competitor['domain']
        data = competitor_data.get(domain, {})
        
        print(f"\n分析: {competitor['name']}")
        print(f"  AI引用数: {data.get('ai_citation_count', 0)}")
        print(f"  品牌提及: {data.get('brand_mention_count', 0)}")
        print(f"  内容数量: {data.get('content_volume', 0)}")
        print(f"  平均质量: {data.get('avg_content_quality', 0)}")
        
        analysis_results.append({
            'competitor': competitor,
            'data': data
        })
    
    # 生成对比报告
    print("\n" + "=" * 60)
    print("📈 竞争对比分析")
    print("=" * 60)
    
    # 计算各项指标对比
    metrics = ['ai_citation_count', 'brand_mention_count', 'content_volume', 
               'avg_content_quality', 'schema_adoption_rate', 'source_diversity']
    
    print(f"\n{'指标':<25} {'你的品牌':<12} {'行业平均':<12} {'差距':<12}")
    print("-" * 60)
    
    for metric in metrics:
        my_value = my_data.get(metric, 0)
        
        # 计算行业平均
        competitor_values = [r['data'].get(metric, 0) for r in analysis_results]
        avg_value = sum(competitor_values) / len(competitor_values) if competitor_values else 0
        
        # 计算差距
        gap = my_value - avg_value
        gap_str = f"{gap:+.1f}"
        
        metric_name = {
            'ai_citation_count': 'AI引用数',
            'brand_mention_count': '品牌提及数',
            'content_volume': '内容数量',
            'avg_content_quality': '平均质量',
            'schema_adoption_rate': 'Schema采用率',
            'source_diversity': '信源多样性'
        }.get(metric, metric)
        
        print(f"{metric_name:<25} {my_value:<12.1f} {avg_value:<12.1f} {gap_str:<12}")
    
    # 平台覆盖对比
    print("\n" + "-" * 60)
    print("平台覆盖对比")
    print("-" * 60)
    
    platforms = ['chatgpt', 'perplexity', 'google_ai']
    platform_names = {
        'chatgpt': 'ChatGPT',
        'perplexity': 'Perplexity',
        'google_ai': 'Google AI'
    }
    
    print(f"{'平台':<20} {'你的品牌':<12} {'行业最高':<12} {'机会':<12}")
    print("-" * 60)
    
    for platform in platforms:
        my_presence = my_data.get('platform_presence', {}).get(platform, 0)
        max_presence = max([
            r['data'].get('platform_presence', {}).get(platform, 0) 
            for r in analysis_results
        ] + [my_presence])
        
        opportunity = "大" if my_presence < max_presence * 0.5 else "中" if my_presence < max_presence * 0.8 else "小"
        
        print(f"{platform_names[platform]:<20} {my_presence:<12} {max_presence:<12} {opportunity:<12}")
    
    # 生成战略建议
    print("\n" + "=" * 60)
    print("💡 战略建议")
    print("=" * 60)
    
    suggestions = []
    
    # 基于数据生成建议
    if my_data.get('ai_citation_count', 0) < avg_value:
        suggestions.append({
            'priority': '高',
            'area': 'AI引用',
            'suggestion': '增加高质量内容产出，重点优化ERE框架应用',
            'action': '每月至少发布10篇GEO优化文章'
        })
    
    if my_data.get('schema_adoption_rate', 0) < 0.8:
        suggestions.append({
            'priority': '高',
            'area': '结构化数据',
            'suggestion': '全面部署Schema.org标记',
            'action': '在官网所有关键页面添加结构化数据'
        })
    
    if my_data.get('content_volume', 0) < 300:
        suggestions.append({
            'priority': '中',
            'area': '内容产量',
            'suggestion': '建立内容生产流水线，提升产出效率',
            'action': '使用GEO系统批量生成内容大纲'
        })
    
    # 分析竞争对手的关键词策略
    all_keywords = set()
    for r in analysis_results:
        all_keywords.update(r['data'].get('top_keywords', []))
    
    my_keywords = set(my_data.get('top_keywords', []))
    missing_keywords = all_keywords - my_keywords
    
    if missing_keywords:
        suggestions.append({
            'priority': '中',
            'area': '关键词覆盖',
            'suggestion': f'覆盖竞争对手使用的关键词: {", ".join(list(missing_keywords)[:5])}',
            'action': '创建针对这些关键词的GEO内容'
        })
    
    for i, suggestion in enumerate(suggestions, 1):
        print(f"\n{i}. [{suggestion['priority']}] {suggestion['area']}")
        print(f"   建议: {suggestion['suggestion']}")
        print(f"   行动: {suggestion['action']}")
    
    # 导出分析报告
    report = {
        'my_brand': my_brand,
        'my_data': my_data,
        'competitors': analysis_results,
        'suggestions': suggestions,
        'summary': {
            'total_competitors': len(competitors),
            'avg_citation_gap': avg_value - my_data.get('ai_citation_count', 0),
            'key_opportunities': len([s for s in suggestions if s['priority'] == '高'])
        }
    }
    
    output_path = 'competitor_analysis_report.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n\n📄 详细报告已保存到: {output_path}")
    
    return report


if __name__ == '__main__':
    demo_competitor_analysis()
