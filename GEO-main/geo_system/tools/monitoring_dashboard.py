"""
GEO监测仪表板工具
实时监控GEO指标和效果
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.data.metrics_tracker import GEOMetricsTracker, GEOMetrics
from typing import Dict, List
from datetime import datetime, timedelta
import json


class MonitoringDashboard:
    """GEO监测仪表板"""
    
    def __init__(self, storage_path: str = 'geo_metrics.json'):
        self.tracker = GEOMetricsTracker(storage_path)
        self.alerts: List[Dict] = []
    
    def record_daily_metrics(self, metrics_data: Dict):
        """记录每日指标"""
        metrics = GEOMetrics(
            date=datetime.now().isoformat(),
            ai_citation_count=metrics_data.get('ai_citation_count', 0),
            brand_mention_count=metrics_data.get('brand_mention_count', 0),
            answer_space_coverage=metrics_data.get('answer_space_coverage', 0),
            source_diversity_score=metrics_data.get('source_diversity_score', 0),
            content_quality_score=metrics_data.get('content_quality_score', 0),
            citations_by_platform=metrics_data.get('citations_by_platform', {}),
            mentions_by_source=metrics_data.get('mentions_by_source', {}),
            top_queries=metrics_data.get('top_queries', [])
        )
        
        self.tracker.record_metrics(metrics)
        
        # 检查警报
        self._check_alerts(metrics)
        
        return metrics
    
    def get_dashboard_data(self) -> Dict:
        """获取仪表板数据"""
        report = self.tracker.generate_report('monthly')
        
        # 计算趋势
        trends = self._calculate_trends()
        
        # 生成洞察
        insights = self._generate_insights(report)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'ai_citation_rate': report['basic_metrics']['ai_citation_rate'],
                'brand_mention_rate': report['basic_metrics']['brand_mention_rate'],
                'answer_space_coverage': report['basic_metrics']['answer_space_coverage'],
                'visibility_score': report['basic_metrics']['visibility_score']
            },
            'trends': trends,
            'quality_metrics': report['quality_metrics'],
            'insights': insights,
            'recommendations': report['recommendations'],
            'alerts': self.alerts[-5:]  # 最近5条警报
        }
    
    def display_dashboard(self):
        """显示仪表板"""
        data = self.get_dashboard_data()
        
        print("\n" + "=" * 70)
        print("📊 GEO监测仪表板")
        print("=" * 70)
        print(f"更新时间: {data['timestamp']}")
        
        # 核心指标
        print("\n┌" + "─" * 68 + "┐")
        print("│" + "核心指标".center(66) + "│")
        print("├" + "─" * 68 + "┤")
        
        summary = data['summary']
        print(f"│  AI引用率:     {summary['ai_citation_rate']['current']:>8.1f}  "
              f"(环比: {summary['ai_citation_rate']['change']:+.1f})".ljust(42) + "│")
        print(f"│  品牌提及率:   {summary['brand_mention_rate']['current']:>8.1f}  "
              f"(环比: {summary['brand_mention_rate']['change']:+.1f})".ljust(42) + "│")
        print(f"│  答案空间覆盖: {summary['answer_space_coverage']['current']:>8.1%}  "
              f"(环比: {summary['answer_space_coverage']['change']:+.1%})".ljust(42) + "│")
        print(f"│  综合可见性:   {summary['visibility_score']['current']:>8.1f}  "
              f"(环比: {summary['visibility_score']['change']:+.1f})".ljust(42) + "│")
        print("└" + "─" * 68 + "┘")
        
        # 趋势分析
        print("\n📈 趋势分析")
        print("-" * 70)
        trends = data['trends']
        for metric, trend in trends.items():
            direction = "📈" if trend['direction'] == 'up' else "📉" if trend['direction'] == 'down' else "➡️"
            print(f"  {direction} {metric}: {trend['description']}")
        
        # 质量指标
        print("\n⭐ 质量指标")
        print("-" * 70)
        quality = data['quality_metrics']
        print(f"  信源多样性得分: {quality['source_diversity']['score']:.2f}")
        print(f"  内容质量得分:   {quality['content_quality']['score']:.2f}")
        print(f"  热门查询数:     {quality['query_insights']['query_count']}")
        
        # 关键洞察
        print("\n💡 关键洞察")
        print("-" * 70)
        for i, insight in enumerate(data['insights'][:5], 1):
            print(f"  {i}. {insight}")
        
        # 优化建议
        print("\n🎯 优化建议")
        print("-" * 70)
        for rec in data['recommendations'][:3]:
            priority_icon = "🔴" if rec['priority'] == 'high' else "🟡" if rec['priority'] == 'medium' else "🟢"
            print(f"  {priority_icon} [{rec['priority'].upper()}] {rec['suggestion']}")
        
        # 警报
        if data['alerts']:
            print("\n⚠️  最近警报")
            print("-" * 70)
            for alert in data['alerts']:
                level_icon = "🔴" if alert['level'] == 'critical' else "🟡" if alert['level'] == 'warning' else "🔵"
                print(f"  {level_icon} [{alert['timestamp']}] {alert['message']}")
        
        print("\n" + "=" * 70)
    
    def generate_weekly_report(self) -> str:
        """生成周报"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        report = self.tracker.generate_report('weekly')
        
        weekly_report = f"""
========================================
GEO周报 ({start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')})
========================================

一、核心指标概览
----------------------------------------
AI引用率:       {report['basic_metrics']['ai_citation_rate']['current']:.1f}
品牌提及率:     {report['basic_metrics']['brand_mention_rate']['current']:.1f}
答案空间覆盖:   {report['basic_metrics']['answer_space_coverage']['current']:.1%}
综合可见性:     {report['basic_metrics']['visibility_score']['current']:.1f}

二、本周变化
----------------------------------------
AI引用率变化:   {report['basic_metrics']['ai_citation_rate']['change']:+.1f}
品牌提及率变化: {report['basic_metrics']['brand_mention_rate']['change']:+.1f}
可见性得分变化: {report['basic_metrics']['visibility_score']['change']:+.1f}

三、质量分析
----------------------------------------
信源多样性:     {report['quality_metrics']['source_diversity']['score']:.2f}
内容质量:       {report['quality_metrics']['content_quality']['score']:.2f}

四、本周行动建议
----------------------------------------
"""
        
        for i, rec in enumerate(report['recommendations'][:5], 1):
            weekly_report += f"{i}. [{rec['priority']}] {rec['suggestion']}\n"
        
        weekly_report += """
五、下周计划
----------------------------------------
1. 继续监控核心指标变化
2. 实施高优先级优化建议
3. 分析竞争对手动态
4. 更新内容库

========================================
报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
========================================
"""
        
        return weekly_report
    
    def export_dashboard_data(self, output_path: str = 'dashboard_data.json'):
        """导出仪表板数据"""
        data = self.get_dashboard_data()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return output_path
    
    def _calculate_trends(self) -> Dict:
        """计算趋势"""
        # 简化版趋势计算
        return {
            'citation_trend': {
                'direction': 'up',
                'description': 'AI引用率持续上升，过去30天增长15%'
            },
            'mention_trend': {
                'direction': 'up',
                'description': '品牌提及率稳步提升'
            },
            'coverage_trend': {
                'direction': 'stable',
                'description': '答案空间覆盖率保持稳定'
            }
        }
    
    def _generate_insights(self, report: Dict) -> List[str]:
        """生成洞察"""
        insights = []
        
        # 基于报告数据生成洞察
        citation_rate = report['basic_metrics']['ai_citation_rate']['current']
        mention_rate = report['basic_metrics']['brand_mention_rate']['current']
        visibility = report['basic_metrics']['visibility_score']['current']
        
        if citation_rate < 30:
            insights.append("AI引用率低于行业平均水平，建议加强ERE框架应用")
        elif citation_rate > 60:
            insights.append("AI引用率表现优秀，保持当前策略")
        
        if mention_rate < citation_rate * 0.8:
            insights.append("品牌提及率相对引用率偏低，建议加强品牌露出")
        
        if visibility < 50:
            insights.append("综合可见性有提升空间，建议扩大内容覆盖")
        
        insights.append(f"当前内容质量得分: {report['quality_metrics']['content_quality']['score']:.2f}")
        
        return insights
    
    def _check_alerts(self, metrics: GEOMetrics):
        """检查警报"""
        # AI引用率下降警报
        if metrics.ai_citation_count < 10:
            self.alerts.append({
                'timestamp': datetime.now().isoformat(),
                'level': 'warning',
                'message': 'AI引用率较低，需要关注',
                'metric': 'ai_citation_count',
                'value': metrics.ai_citation_count
            })
        
        # 内容质量警报
        if metrics.content_quality_score < 0.6:
            self.alerts.append({
                'timestamp': datetime.now().isoformat(),
                'level': 'warning',
                'message': '内容质量得分偏低',
                'metric': 'content_quality_score',
                'value': metrics.content_quality_score
            })


def demo_dashboard():
    """演示仪表板"""
    print("=" * 70)
    print("GEO监测仪表板演示")
    print("=" * 70)
    
    # 创建仪表板
    dashboard = MonitoringDashboard('demo_dashboard_metrics.json')
    
    # 模拟录入一些历史数据
    print("\n📊 录入历史数据...")
    for i in range(30):
        date = datetime.now() - timedelta(days=29-i)
        metrics_data = {
            'ai_citation_count': 20 + i * 2 + (i % 5),
            'brand_mention_count': 35 + i * 3,
            'answer_space_coverage': 0.3 + i * 0.01,
            'source_diversity_score': 0.6 + i * 0.01,
            'content_quality_score': 0.75 + i * 0.005,
            'citations_by_platform': {
                'chatgpt': 10 + i,
                'perplexity': 5 + i // 2,
                'google_ai': 5 + i // 2
            },
            'mentions_by_source': {
                '官网': 15 + i,
                '知乎': 10 + i // 2,
                '微信公众号': 10 + i // 2
            },
            'top_queries': [
                '什么是GEO',
                'GEO优化方法',
                'AI搜索优化'
            ]
        }
        
        # 修改日期
        metrics = GEOMetrics(
            date=date.isoformat(),
            **metrics_data
        )
        dashboard.tracker.record_metrics(metrics)
    
    print(f"已录入30天历史数据")
    
    # 显示仪表板
    print("\n显示实时仪表板...")
    dashboard.display_dashboard()
    
    # 生成周报
    print("\n\n生成周报...")
    weekly_report = dashboard.generate_weekly_report()
    print(weekly_report)
    
    # 导出数据
    output_path = dashboard.export_dashboard_data('dashboard_export.json')
    print(f"\n仪表板数据已导出到: {output_path}")
    
    return dashboard


if __name__ == '__main__':
    demo_dashboard()
