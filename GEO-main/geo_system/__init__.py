"""
GEO内容工程系统

一套面向GEO (Generative Engine Optimization) 内容工程、
AI搜索适配与自动化内容运营的开源系统。

核心功能:
- GEO内容生成: 基于ERE框架的智能内容生成
- 内容优化: 自动优化AI引用率和内容质量
- 知识库管理: RAG检索增强生成引擎
- 信源建设: 四级权威信源体系构建
- 数据监测: GEO效果追踪和ROI计算
- 多平台适配: 支持ChatGPT、Perplexity等平台

使用示例:
    >>> from geo_system.core.content_generator import GEOArticleGenerator
    >>> generator = GEOArticleGenerator()
    >>> result = generator.generate(
    ...     title="什么是GEO",
    ...     brand_info={"name": "你的品牌", "industry": "AI营销"}
    ... )
"""

__version__ = "1.0.0"
__author__ = "GEO Team"

# 核心模块
from geo_system.core.content_generator import GEOArticleGenerator
from geo_system.core.content_optimizer import GEOContentOptimizer
from geo_system.core.rag_engine import RAGEngine, GEOKnowledgeBuilder

# 工具模块
from geo_system.utils.content_analyzer import ContentAnalyzer
from geo_system.utils.citation_optimizer import CitationOptimizer
from geo_system.utils.schema_validator import SchemaValidator

# 数据模块
from geo_system.modules.data.roi_calculator import ROICalculator
from geo_system.modules.data.competitor_analyzer import CompetitorAnalyzer
from geo_system.modules.data.metrics_tracker import GEOMetricsTracker

# 信源模块
from geo_system.modules.source.authority_builder import AuthorityBuilder
from geo_system.modules.source.platform_distributor import PlatformDistributor
from geo_system.modules.source.schema_optimizer import SchemaOptimizer

__all__ = [
    # 核心
    'GEOArticleGenerator',
    'GEOContentOptimizer',
    'RAGEngine',
    'GEOKnowledgeBuilder',
    # 工具
    'ContentAnalyzer',
    'CitationOptimizer',
    'SchemaValidator',
    # 数据
    'ROICalculator',
    'CompetitorAnalyzer',
    'GEOMetricsTracker',
    # 信源
    'AuthorityBuilder',
    'PlatformDistributor',
    'SchemaOptimizer',
]
