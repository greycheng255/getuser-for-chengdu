"""
内容生成器测试
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from core.content_generator import GEOArticleGenerator


class TestContentGenerator(unittest.TestCase):
    """测试内容生成器"""
    
    def setUp(self):
        self.generator = GEOArticleGenerator()
        self.sample_brand_info = {
            'name': '测试品牌',
            'industry': 'AI营销',
            'expertise': ['GEO', '内容营销']
        }
    
    def test_generate_basic(self):
        """测试基本生成功能"""
        result = self.generator.generate(
            title="什么是GEO",
            brand_info=self.sample_brand_info
        )
        
        self.assertIn('title', result)
        self.assertIn('outline', result)
        self.assertIn('prompt', result)
        self.assertEqual(result['title'], "什么是GEO")
        self.assertIsInstance(result['outline'], list)
        self.assertGreater(len(result['outline']), 0)
    
    def test_generate_with_platform(self):
        """测试不同平台生成"""
        platforms = ['chatgpt', 'perplexity', 'google_ai']
        
        for platform in platforms:
            result = self.generator.generate(
                title="GEO测试",
                brand_info=self.sample_brand_info,
                target_platform=platform
            )
            
            self.assertIn('outline', result)
            self.assertIsInstance(result['outline'], list)
    
    def test_generate_outline_structure(self):
        """测试大纲结构"""
        result = self.generator.generate(
            title="GEO结构测试",
            brand_info=self.sample_brand_info
        )
        
        outline = result['outline']
        self.assertGreater(len(outline), 0)
        
        # 检查大纲项结构
        for item in outline:
            self.assertIn('level', item)
            self.assertIn('title', item)
            self.assertIn(item['level'], [1, 2, 3])
            self.assertIsInstance(item['title'], str)
    
    def test_generate_prompt_content(self):
        """测试提示词内容"""
        result = self.generator.generate(
            title="GEO提示词测试",
            brand_info=self.sample_brand_info
        )
        
        prompt = result['prompt']
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 100)
        
        # 检查提示词包含关键元素
        self.assertIn('GEO', prompt)
        self.assertIn(self.sample_brand_info['name'], prompt)


class TestContentOptimizer(unittest.TestCase):
    """测试内容优化器"""
    
    def setUp(self):
        from core.content_optimizer import GEOContentOptimizer
        self.optimizer = GEOContentOptimizer()
    
    def test_analyze_content(self):
        """测试内容分析"""
        sample_content = """
# 什么是GEO

GEO是生成式引擎优化的简称。它帮助企业在AI搜索中获得更好的可见性。

根据2024年的研究显示，GEO能提升品牌AI引用率40%。

## GEO的核心要素

1. 实体定义
2. 关系建立
3. 证据支撑
"""
        
        result = self.optimizer.analyze(sample_content)
        
        self.assertIn('overall_score', result)
        self.assertIn('structure_score', result)
        self.assertIn('citation_score', result)
        self.assertIn('readability_score', result)
        self.assertIn('authority_score', result)
        
        # 检查分数范围
        self.assertGreaterEqual(result['overall_score'], 0)
        self.assertLessEqual(result['overall_score'], 100)
    
    def test_optimize_content(self):
        """测试内容优化"""
        from core.content_optimizer import OptimizationResult
        
        sample_content = "GEO是一种优化方法。它很重要。企业应该使用它。"
        
        result = self.optimizer.optimize(sample_content)
        
        self.assertIsInstance(result, OptimizationResult)
        self.assertIsInstance(result.optimized_content, str)
        self.assertIsInstance(result.score_before, float)
        self.assertIsInstance(result.score_after, float)
        
        # 优化后分数应该提高或保持不变
        self.assertGreaterEqual(result.score_after, result.score_before)


class TestContentAnalyzer(unittest.TestCase):
    """测试内容分析器"""
    
    def setUp(self):
        from utils.content_analyzer import ContentAnalyzer
        self.analyzer = ContentAnalyzer()
    
    def test_analyze_structure(self):
        """测试结构分析"""
        content = """
# 标题
## 小节1
内容1
## 小节2
内容2
"""
        
        result = self.analyzer.analyze(content)
        
        self.assertIn('structure_score', result.to_dict())
        self.assertGreater(result.structure_score, 0)
    
    def test_analyze_citations(self):
        """测试引用分析"""
        content = """
根据研究显示，GEO能提升引用率。
数据表明，优化效果显著。
"""
        
        result = self.analyzer.analyze(content)
        
        self.assertIn('citation_score', result.to_dict())
        self.assertIsInstance(result.citation_score, float)


class TestRAGEngine(unittest.TestCase):
    """测试RAG引擎"""
    
    def setUp(self):
        from core.rag_engine import RAGEngine, GEOKnowledgeBuilder
        self.engine = RAGEngine()
        self.builder = GEOKnowledgeBuilder(self.engine)
    
    def test_add_entity(self):
        """测试添加实体"""
        self.builder.add_entity(
            name="GEO",
            definition="生成式引擎优化",
            attributes={"全称": "Generative Engine Optimization"}
        )
        
        self.assertIn("GEO", self.engine.knowledge_base['entities'])
    
    def test_add_relation(self):
        """测试添加关系"""
        self.builder.add_entity("A", "实体A")
        self.builder.add_entity("B", "实体B")
        
        self.builder.add_relation("A", "关联", "B", "A和B有关联")
        
        relations = self.engine.knowledge_base['relations']
        self.assertGreater(len(relations), 0)
    
    def test_query_knowledge(self):
        """测试知识查询"""
        self.builder.add_entity("GEO", "生成式引擎优化")
        self.builder.add_evidence("GEO有效", "研究表明GEO有效", "研究", "研究数据")
        
        result = self.builder.query_for_article("GEO")
        
        self.assertIn('entities', result)
        self.assertIn('evidence', result)


if __name__ == '__main__':
    unittest.main()
