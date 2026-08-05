"""
功能模块测试
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from datetime import datetime


class TestROICalculator(unittest.TestCase):
    """测试ROI计算器"""
    
    def setUp(self):
        from modules.data.roi_calculator import ROICalculator
        self.calculator = ROICalculator()
    
    def test_calculate_basic_roi(self):
        """测试基础ROI计算"""
        params = {
            'content_investment': 50000,
            'technology_investment': 30000,
            'personnel_investment': 80000,
            'ai_citation_increase': 40,
            'brand_mention_increase': 35,
            'conversion_rate': 2.5,
            'avg_customer_value': 5000,
            'time_period_months': 12
        }
        
        result = self.calculator.calculate_basic_roi(params)
        
        self.assertIn('total_investment', result)
        self.assertIn('revenue', result)
        self.assertIn('net_profit', result)
        self.assertIn('roi_percentage', result)
        self.assertIn('payback_period_months', result)
        
        # 验证计算
        self.assertEqual(result['total_investment'], 160000)
        self.assertGreater(result['revenue'], 0)
        self.assertGreater(result['new_customers'], 0)
    
    def test_calculate_ltv(self):
        """测试LTV计算"""
        params = {
            'avg_customer_value': 5000,
            'customer_retention_rate': 0.8,
            'customer_lifespan_years': 3,
            'gross_margin': 0.6
        }
        
        ltv = self.calculator.calculate_ltv(params)
        
        self.assertIsInstance(ltv, float)
        self.assertGreater(ltv, 0)


class TestMetricsTracker(unittest.TestCase):
    """测试指标追踪器"""
    
    def setUp(self):
        from modules.data.metrics_tracker import GEOMetricsTracker, GEOMetrics
        self.tracker = GEOMetricsTracker(storage_path='test_metrics.json')
        self.GEOMetrics = GEOMetrics
    
    def test_record_metrics(self):
        """测试记录指标"""
        metrics = self.GEOMetrics(
            date=datetime.now().isoformat(),
            ai_citation_count=100,
            brand_mention_count=150,
            answer_space_coverage=0.5,
            source_diversity_score=0.7,
            content_quality_score=0.8,
            citations_by_platform={'chatgpt': 50},
            mentions_by_source={'官网': 80},
            top_queries=['GEO']
        )
        
        self.tracker.record_metrics(metrics)
        
        # 验证记录成功
        self.assertGreater(len(self.tracker.metrics_history), 0)
    
    def test_generate_report(self):
        """测试生成报告"""
        # 先记录一些数据
        for i in range(5):
            metrics = self.GEOMetrics(
                date=datetime.now().isoformat(),
                ai_citation_count=100 + i * 10,
                brand_mention_count=150 + i * 5,
                answer_space_coverage=0.5 + i * 0.02,
                source_diversity_score=0.7,
                content_quality_score=0.8,
                citations_by_platform={'chatgpt': 50 + i},
                mentions_by_source={'官网': 80},
                top_queries=['GEO']
            )
            self.tracker.record_metrics(metrics)
        
        report = self.tracker.generate_report('monthly')
        
        self.assertIn('basic_metrics', report)
        self.assertIn('quality_metrics', report)
        self.assertIn('recommendations', report)


class TestAuthorityBuilder(unittest.TestCase):
    """测试权威建设器"""
    
    def setUp(self):
        from modules.source.authority_builder import AuthorityBuilder
        self.builder = AuthorityBuilder()
    
    def test_get_authority_pyramid(self):
        """测试获取权威金字塔"""
        pyramid = self.builder.get_authority_pyramid()
        
        self.assertIn('name', pyramid)
        self.assertIn('levels', pyramid)
        self.assertEqual(len(pyramid['levels']), 4)
    
    def test_build_official_site_authority(self):
        """测试官网权威建设"""
        brand_info = {
            'name': '测试品牌',
            'url': 'https://test.com',
            'description': '测试描述'
        }
        
        plan = self.builder.build_official_site_authority(brand_info)
        
        self.assertIn('name', plan)
        self.assertIn('components', plan)
        self.assertGreater(len(plan['components']), 0)


class TestPlatformDistributor(unittest.TestCase):
    """测试平台分发器"""
    
    def setUp(self):
        from modules.source.platform_distributor import PlatformDistributor
        self.distributor = PlatformDistributor()
    
    def test_get_platform_requirements(self):
        """测试获取平台要求"""
        requirements = self.distributor.get_platform_requirements('chatgpt')
        
        self.assertIn('name', requirements)
        self.assertIn('content_preferences', requirements)
        self.assertIn('optimization_tips', requirements)
    
    def test_adapt_content(self):
        """测试内容适配"""
        content = {
            'title': '测试标题',
            'content': '测试内容'
        }
        
        adapted = self.distributor.adapt_content(content, 'chatgpt')
        
        self.assertIn('title', adapted)
        self.assertIn('content', adapted)
        self.assertIn('platform', adapted)
        self.assertEqual(adapted['platform'], 'chatgpt')


class TestCompetitorAnalyzer(unittest.TestCase):
    """测试竞争对手分析器"""
    
    def setUp(self):
        from modules.data.competitor_analyzer import CompetitorAnalyzer
        self.analyzer = CompetitorAnalyzer()
    
    def test_analyze_competitor(self):
        """测试分析竞争对手"""
        competitor_data = {
            'ai_citation_count': 100,
            'brand_mention_count': 150,
            'content_volume': 200,
            'avg_content_quality': 75
        }
        
        result = self.analyzer.analyze_competitor('competitor.com', competitor_data)
        
        self.assertIn('domain', result)
        self.assertIn('metrics', result)
        self.assertIn('strengths', result)
        self.assertIn('weaknesses', result)
    
    def test_compare_with_competitors(self):
        """测试竞争对手对比"""
        my_data = {
            'ai_citation_count': 80,
            'brand_mention_count': 120,
            'content_volume': 150
        }
        
        competitors_data = [
            {'ai_citation_count': 100, 'brand_mention_count': 150, 'content_volume': 200},
            {'ai_citation_count': 120, 'brand_mention_count': 180, 'content_volume': 250}
        ]
        
        result = self.analyzer.compare_with_competitors(my_data, competitors_data)
        
        self.assertIn('my_data', result)
        self.assertIn('competitors_avg', result)
        self.assertIn('gaps', result)


if __name__ == '__main__':
    unittest.main()
