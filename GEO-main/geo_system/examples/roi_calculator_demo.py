"""
GEO投资回报率计算示例
演示如何计算和预测GEO策略的ROI
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.data.roi_calculator import ROICalculator
from typing import Dict
import json


def demo_roi_calculation():
    """演示ROI计算"""
    
    print("=" * 60)
    print("GEO投资回报率(ROI)计算演示")
    print("=" * 60)
    
    # 初始化计算器
    calculator = ROICalculator()
    
    # 场景1: 基础ROI计算
    print("\n📊 场景1: 基础ROI计算")
    print("-" * 60)
    
    basic_params = {
        'content_investment': 50000,  # 内容投资
        'technology_investment': 30000,  # 技术投资
        'personnel_investment': 80000,  # 人力投资
        'ai_citation_increase': 40,  # AI引用率提升(%)
        'brand_mention_increase': 35,  # 品牌提及率提升(%)
        'conversion_rate': 2.5,  # 转化率(%)
        'avg_customer_value': 5000,  # 平均客户价值
        'time_period_months': 12  # 时间周期(月)
    }
    
    basic_roi = calculator.calculate_basic_roi(basic_params)
    
    print(f"投资明细:")
    print(f"  内容投资: ¥{basic_params['content_investment']:,}")
    print(f"  技术投资: ¥{basic_params['technology_investment']:,}")
    print(f"  人力投资: ¥{basic_params['personnel_investment']:,}")
    print(f"  总投资: ¥{basic_roi['total_investment']:,.0f}")
    
    print(f"\n收益预测:")
    print(f"  AI引用率提升: {basic_params['ai_citation_increase']}%")
    print(f"  品牌提及率提升: {basic_params['brand_mention_increase']}%")
    print(f"  预期新增客户: {basic_roi['new_customers']:.0f}")
    print(f"  预期收益: ¥{basic_roi['revenue']:,.0f}")
    
    print(f"\nROI结果:")
    print(f"  ROI: {basic_roi['roi_percentage']:.1f}%")
    print(f"  投资回收期: {basic_roi['payback_period_months']:.1f}个月")
    print(f"  净收益: ¥{basic_roi['net_profit']:,.0f}")
    
    # 场景2: 多场景对比
    print("\n\n📊 场景2: 多场景ROI对比")
    print("-" * 60)
    
    scenarios = [
        {
            'name': '保守策略',
            'investment': 100000,
            'citation_increase': 25,
            'conversion_rate': 2.0
        },
        {
            'name': '平衡策略',
            'investment': 160000,
            'citation_increase': 40,
            'conversion_rate': 2.5
        },
        {
            'name': '激进策略',
            'investment': 250000,
            'citation_increase': 60,
            'conversion_rate': 3.0
        }
    ]
    
    print(f"{'策略':<15} {'投资':<15} {'预期收益':<15} {'ROI':<12} {'回收期':<12}")
    print("-" * 70)
    
    scenario_results = []
    for scenario in scenarios:
        params = {
            'content_investment': scenario['investment'] * 0.4,
            'technology_investment': scenario['investment'] * 0.2,
            'personnel_investment': scenario['investment'] * 0.4,
            'ai_citation_increase': scenario['citation_increase'],
            'brand_mention_increase': scenario['citation_increase'] * 0.8,
            'conversion_rate': scenario['conversion_rate'],
            'avg_customer_value': 5000,
            'time_period_months': 12
        }
        
        roi = calculator.calculate_basic_roi(params)
        scenario_results.append({
            'scenario': scenario['name'],
            'roi': roi
        })
        
        print(f"{scenario['name']:<15} "
              f"¥{scenario['investment']:>12,} "
              f"¥{roi['revenue']:>12,.0f} "
              f"{roi['roi_percentage']:>10.1f}% "
              f"{roi['payback_period_months']:>10.1f}月")
    
    # 场景3: 长期价值计算
    print("\n\n📊 场景3: 长期价值(LTV)分析")
    print("-" * 60)
    
    ltv_params = {
        'avg_customer_value': 5000,
        'customer_retention_rate': 0.8,  # 年留存率
        'customer_lifespan_years': 3,  # 客户生命周期
        'gross_margin': 0.6  # 毛利率
    }
    
    ltv = calculator.calculate_ltv(ltv_params)
    
    print(f"客户生命周期价值计算:")
    print(f"  平均客户价值: ¥{ltv_params['avg_customer_value']:,}")
    print(f"  年留存率: {ltv_params['customer_retention_rate']*100:.0f}%")
    print(f"  客户生命周期: {ltv_params['customer_lifespan_years']}年")
    print(f"  毛利率: {ltv_params['gross_margin']*100:.0f}%")
    print(f"\n  客户LTV: ¥{ltv:,.0f}")
    
    # 场景4: 敏感度分析
    print("\n\n📊 场景4: 敏感度分析")
    print("-" * 60)
    
    base_params = {
        'content_investment': 50000,
        'technology_investment': 30000,
        'personnel_investment': 80000,
        'ai_citation_increase': 40,
        'brand_mention_increase': 35,
        'conversion_rate': 2.5,
        'avg_customer_value': 5000,
        'time_period_months': 12
    }
    
    # 测试不同变量对ROI的影响
    sensitivity_vars = {
        'ai_citation_increase': [20, 30, 40, 50, 60],
        'conversion_rate': [1.5, 2.0, 2.5, 3.0, 3.5],
        'avg_customer_value': [3000, 4000, 5000, 6000, 7000]
    }
    
    print("AI引用率提升对ROI的影响:")
    print(f"{'引用率提升':<15} {'ROI':<15} {'净收益':<15}")
    print("-" * 45)
    
    for citation_increase in sensitivity_vars['ai_citation_increase']:
        test_params = base_params.copy()
        test_params['ai_citation_increase'] = citation_increase
        test_params['brand_mention_increase'] = citation_increase * 0.875
        
        roi = calculator.calculate_basic_roi(test_params)
        print(f"{citation_increase:>10}%     "
              f"{roi['roi_percentage']:>10.1f}%     "
              f"¥{roi['net_profit']:>10,.0f}")
    
    # 场景5: 综合业务价值评估
    print("\n\n📊 场景5: 综合业务价值评估")
    print("-" * 60)
    
    business_params = {
        'current_monthly_traffic': 10000,  # 当前月访问量
        'current_conversion_rate': 2.0,  # 当前转化率
        'geo_traffic_increase': 30,  # GEO带来的流量提升(%)
        'geo_conversion_lift': 25,  # GEO带来的转化率提升(%)
        'avg_order_value': 3000,  # 平均订单价值
        'customer_acquisition_cost': 500,  # 客户获取成本
        'geo_cac_reduction': 20  # GEO降低的CAC(%)
    }
    
    print(f"业务指标:")
    print(f"  当前月访问量: {business_params['current_monthly_traffic']:,}")
    print(f"  当前转化率: {business_params['current_conversion_rate']}%")
    print(f"  平均订单价值: ¥{business_params['avg_order_value']:,}")
    print(f"\nGEO预期效果:")
    print(f"  流量提升: {business_params['geo_traffic_increase']}%")
    print(f"  转化率提升: {business_params['geo_conversion_lift']}%")
    print(f"  CAC降低: {business_params['geo_cac_reduction']}%")
    
    # 计算月度业务影响
    current_monthly_customers = business_params['current_monthly_traffic'] * (business_params['current_conversion_rate'] / 100)
    current_monthly_revenue = current_monthly_customers * business_params['avg_order_value']
    current_cac = business_params['customer_acquisition_cost']
    
    new_traffic = business_params['current_monthly_traffic'] * (1 + business_params['geo_traffic_increase'] / 100)
    new_conversion_rate = business_params['current_conversion_rate'] * (1 + business_params['geo_conversion_lift'] / 100)
    new_monthly_customers = new_traffic * (new_conversion_rate / 100)
    new_monthly_revenue = new_monthly_customers * business_params['avg_order_value']
    new_cac = current_cac * (1 - business_params['geo_cac_reduction'] / 100)
    
    print(f"\n月度业务影响:")
    print(f"  新客户增长: {new_monthly_customers - current_monthly_customers:.0f}")
    print(f"  收入增长: ¥{new_monthly_revenue - current_monthly_revenue:,.0f}")
    print(f"  CAC降低: ¥{current_cac - new_cac:.0f}")
    print(f"  年收入增长预测: ¥{(new_monthly_revenue - current_monthly_revenue) * 12:,.0f}")
    
    # 生成完整报告
    print("\n\n" + "=" * 60)
    print("📋 GEO ROI分析报告")
    print("=" * 60)
    
    report = {
        'basic_roi': basic_roi,
        'scenario_comparison': scenario_results,
        'customer_ltv': ltv,
        'business_impact': {
            'monthly_revenue_increase': new_monthly_revenue - current_monthly_revenue,
            'annual_revenue_increase': (new_monthly_revenue - current_monthly_revenue) * 12,
            'cac_savings': current_cac - new_cac,
            'customer_growth': new_monthly_customers - current_monthly_customers
        },
        'recommendations': [
            {
                'priority': '高',
                'recommendation': '基于ROI分析，建议采用平衡策略，预期12个月回收投资',
                'expected_roi': '150-200%'
            },
            {
                'priority': '中',
                'recommendation': '重点关注AI引用率提升，这是影响ROI的关键变量',
                'action': '每月监控引用率变化'
            },
            {
                'priority': '中',
                'recommendation': '优化客户生命周期价值，提升长期ROI',
                'action': '建立客户成功体系'
            }
        ]
    }
    
    print(f"\n核心结论:")
    print(f"  1. 基础ROI: {basic_roi['roi_percentage']:.1f}%")
    print(f"  2. 投资回收期: {basic_roi['payback_period_months']:.1f}个月")
    print(f"  3. 客户LTV: ¥{ltv:,.0f}")
    print(f"  4. 年收入增长预测: ¥{report['business_impact']['annual_revenue_increase']:,.0f}")
    
    print(f"\n战略建议:")
    for i, rec in enumerate(report['recommendations'], 1):
        print(f"  {i}. [{rec['priority']}] {rec['recommendation']}")
    
    # 保存报告
    output_path = 'geo_roi_report.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n\n📄 详细报告已保存到: {output_path}")
    
    return report


if __name__ == '__main__':
    demo_roi_calculation()
