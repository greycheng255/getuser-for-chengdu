"""
GEO指标追踪器
监测和分析GEO效果数据
"""

import json
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from collections import defaultdict


@dataclass
class GEOMetrics:
    """GEO指标数据"""
    date: str
    ai_citation_count: int
    brand_mention_count: int
    answer_space_coverage: float
    source_diversity_score: float
    content_quality_score: float
    
    # 详细数据
    citations_by_platform: Dict[str, int]
    mentions_by_source: Dict[str, int]
    top_queries: List[str]


class GEOMetricsTracker:
    """
    GEO指标追踪器
    
    追踪三大指标类别：
    - 基础指标：可见性、覆盖率
    - 质量指标：引用质量、信源多样性
    - 商业指标：转化率、ROI
    """
    
    def __init__(self, storage_path: str = None):
        self.storage_path = storage_path or "geo_metrics.json"
        self.metrics_history: List[GEOMetrics] = []
        self.load_history()
        
    def load_history(self):
        """加载历史数据"""
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.metrics_history = [
                    GEOMetrics(**item) for item in data
                ]
        except FileNotFoundError:
            self.metrics_history = []
    
    def save_history(self):
        """保存历史数据"""
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(
                [asdict(m) for m in self.metrics_history],
                f,
                ensure_ascii=False,
                indent=2
            )
    
    def record_metrics(self, metrics: GEOMetrics):
        """记录指标数据"""
        self.metrics_history.append(metrics)
        self.save_history()
    
    def get_basic_metrics(self, days: int = 30) -> Dict:
        """
        获取基础指标
        
        Args:
            days: 统计天数
            
        Returns:
            基础指标数据
        """
        recent_metrics = self._get_recent_metrics(days)
        
        if not recent_metrics:
            return self._empty_basic_metrics()
        
        # 计算平均值和趋势
        avg_citations = sum(m.ai_citation_count for m in recent_metrics) / len(recent_metrics)
        avg_mentions = sum(m.brand_mention_count for m in recent_metrics) / len(recent_metrics)
        avg_coverage = sum(m.answer_space_coverage for m in recent_metrics) / len(recent_metrics)
        
        # 计算趋势
        trend = self._calculate_trend(recent_metrics)
        
        return {
            "ai_citation_rate": {
                "current": avg_citations,
                "trend": trend["citation"],
                "description": "AI引用次数"
            },
            "brand_mention_rate": {
                "current": avg_mentions,
                "trend": trend["mention"],
                "description": "品牌提及次数"
            },
            "answer_space_coverage": {
                "current": avg_coverage,
                "trend": trend["coverage"],
                "description": "答案空间覆盖率"
            },
            "visibility_score": {
                "current": (avg_citations * 0.4 + avg_mentions * 0.3 + avg_coverage * 100 * 0.3),
                "trend": trend["overall"],
                "description": "综合可见性得分"
            }
        }
    
    def get_quality_metrics(self, days: int = 30) -> Dict:
        """
        获取质量指标
        
        Args:
            days: 统计天数
            
        Returns:
            质量指标数据
        """
        recent_metrics = self._get_recent_metrics(days)
        
        if not recent_metrics:
            return self._empty_quality_metrics()
        
        avg_diversity = sum(m.source_diversity_score for m in recent_metrics) / len(recent_metrics)
        avg_quality = sum(m.content_quality_score for m in recent_metrics) / len(recent_metrics)
        
        # 聚合平台数据
        platform_stats = defaultdict(int)
        source_stats = defaultdict(int)
        all_queries = []
        
        for m in recent_metrics:
            for platform, count in m.citations_by_platform.items():
                platform_stats[platform] += count
            for source, count in m.mentions_by_source.items():
                source_stats[source] += count
            all_queries.extend(m.top_queries)
        
        # 统计查询频率
        query_freq = defaultdict(int)
        for q in all_queries:
            query_freq[q] += 1
        top_queries = sorted(query_freq.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            "source_diversity": {
                "score": avg_diversity,
                "platform_distribution": dict(platform_stats),
                "description": "信源多样性得分"
            },
            "content_quality": {
                "score": avg_quality,
                "description": "内容质量得分"
            },
            "citation_quality": {
                "top_platforms": sorted(platform_stats.items(), key=lambda x: x[1], reverse=True)[:5],
                "top_sources": sorted(source_stats.items(), key=lambda x: x[1], reverse=True)[:5],
                "description": "引用质量分析"
            },
            "query_insights": {
                "top_queries": top_queries,
                "query_count": len(set(all_queries)),
                "description": "热门查询分析"
            }
        }
    
    def get_commercial_metrics(self, conversion_data: Dict = None) -> Dict:
        """
        获取商业指标
        
        Args:
            conversion_data: 转化数据
            
        Returns:
            商业指标数据
        """
        # 这里需要接入实际的业务数据
        # 简化示例
        
        return {
            "ai_driven_traffic": {
                "estimated": conversion_data.get("ai_traffic", 0) if conversion_data else 0,
                "description": "AI驱动的流量估算"
            },
            "conversion_rate": {
                "rate": conversion_data.get("conversion_rate", 0) if conversion_data else 0,
                "description": "AI流量转化率"
            },
            "customer_acquisition": {
                "cost": conversion_data.get("cac", 0) if conversion_data else 0,
                "description": "AI渠道获客成本"
            },
            "brand_lift": {
                "score": conversion_data.get("brand_lift", 0) if conversion_data else 0,
                "description": "品牌提升度"
            }
        }
    
    def generate_report(self, period: str = "monthly") -> Dict:
        """
        生成GEO数据报告
        
        Args:
            period: 报告周期 (daily, weekly, monthly, quarterly)
            
        Returns:
            完整报告数据
        """
        days_map = {
            "daily": 1,
            "weekly": 7,
            "monthly": 30,
            "quarterly": 90
        }
        days = days_map.get(period, 30)
        
        return {
            "report_period": period,
            "generated_at": datetime.now().isoformat(),
            "basic_metrics": self.get_basic_metrics(days),
            "quality_metrics": self.get_quality_metrics(days),
            "commercial_metrics": self.get_commercial_metrics(),
            "recommendations": self._generate_recommendations(days),
            "benchmarks": self._get_benchmarks()
        }
    
    def _get_recent_metrics(self, days: int) -> List[GEOMetrics]:
        """获取最近N天的指标"""
        cutoff_date = datetime.now() - timedelta(days=days)
        return [
            m for m in self.metrics_history
            if datetime.fromisoformat(m.date) >= cutoff_date
        ]
    
    def _calculate_trend(self, metrics: List[GEOMetrics]) -> Dict:
        """计算趋势"""
        if len(metrics) < 2:
            return {
                "citation": "stable",
                "mention": "stable",
                "coverage": "stable",
                "overall": "stable"
            }
        
        # 比较最近和最早的数据
        recent = metrics[-1]
        earliest = metrics[0]
        
        def get_trend(current, previous):
            if current > previous * 1.1:
                return "up"
            elif current < previous * 0.9:
                return "down"
            return "stable"
        
        return {
            "citation": get_trend(recent.ai_citation_count, earliest.ai_citation_count),
            "mention": get_trend(recent.brand_mention_count, earliest.brand_mention_count),
            "coverage": get_trend(recent.answer_space_coverage, earliest.answer_space_coverage),
            "overall": "up"  # 简化处理
        }
    
    def _generate_recommendations(self, days: int) -> List[Dict]:
        """生成优化建议"""
        basic = self.get_basic_metrics(days)
        quality = self.get_quality_metrics(days)
        
        recommendations = []
        
        # 基于基础指标的建议
        if basic["ai_citation_rate"]["current"] < 10:
            recommendations.append({
                "priority": "high",
                "area": "citation",
                "suggestion": "AI引用率较低，建议增加权威数据引用和专家引言",
                "action": "优化内容引用策略"
            })
        
        # 基于质量指标的建议
        if quality["source_diversity"]["score"] < 0.6:
            recommendations.append({
                "priority": "medium",
                "area": "diversity",
                "suggestion": "信源多样性不足，建议拓展更多平台",
                "action": "建立多平台分发体系"
            })
        
        # 通用建议
        recommendations.extend([
            {
                "priority": "medium",
                "area": "content",
                "suggestion": "定期更新内容，保持信息时效性",
                "action": "建立内容更新日历"
            },
            {
                "priority": "low",
                "area": "monitoring",
                "suggestion": "持续监测竞争对手的GEO策略",
                "action": "设置竞品监测机制"
            }
        ])
        
        return recommendations
    
    def _get_benchmarks(self) -> Dict:
        """获取行业基准数据"""
        return {
            "ai_citation_rate": {
                "industry_avg": 15,
                "top_performer": 50,
                "description": "AI引用率行业基准"
            },
            "brand_mention_rate": {
                "industry_avg": 25,
                "top_performer": 80,
                "description": "品牌提及率行业基准"
            },
            "answer_space_coverage": {
                "industry_avg": 0.3,
                "top_performer": 0.7,
                "description": "答案空间覆盖率行业基准"
            }
        }
    
    def _empty_basic_metrics(self) -> Dict:
        """空基础指标"""
        return {
            "ai_citation_rate": {"current": 0, "trend": "stable", "description": "AI引用次数"},
            "brand_mention_rate": {"current": 0, "trend": "stable", "description": "品牌提及次数"},
            "answer_space_coverage": {"current": 0, "trend": "stable", "description": "答案空间覆盖率"},
            "visibility_score": {"current": 0, "trend": "stable", "description": "综合可见性得分"}
        }
    
    def _empty_quality_metrics(self) -> Dict:
        """空质量指标"""
        return {
            "source_diversity": {
                "score": 0,
                "platform_distribution": {},
                "description": "信源多样性得分"
            },
            "content_quality": {
                "score": 0,
                "description": "内容质量得分"
            },
            "citation_quality": {
                "top_platforms": [],
                "top_sources": [],
                "description": "引用质量分析"
            },
            "query_insights": {
                "top_queries": [],
                "query_count": 0,
                "description": "热门查询分析"
            }
        }


if __name__ == "__main__":
    tracker = GEOMetricsTracker()
    
    # 模拟记录一些数据
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
    report = tracker.generate_report("monthly")
    print("GEO月度报告：")
    print(f"基础指标: {report['basic_metrics']}")
    print(f"质量指标: {report['quality_metrics']}")
    print(f"建议数量: {len(report['recommendations'])}")
