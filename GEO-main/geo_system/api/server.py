"""
GEO系统API服务器
基于FastAPI的RESTful API服务
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import uvicorn

from core.content_generator import GEOArticleGenerator
from core.content_optimizer import GEOContentOptimizer
from core.rag_engine import RAGEngine, GEOKnowledgeBuilder
from utils.content_analyzer import ContentAnalyzer
from modules.data.metrics_tracker import GEOMetricsTracker
from modules.source.authority_builder import AuthorityBuilder


# 请求/响应模型
class ContentGenerationRequest(BaseModel):
    title: str
    brand_name: str
    industry: str
    expertise: List[str]
    target_platform: str = "chatgpt"
    word_count: int = 3000


class ContentGenerationResponse(BaseModel):
    success: bool
    title: str
    outline: List[Dict]
    prompt: str
    message: str = ""


class ContentOptimizationRequest(BaseModel):
    content: str
    optimization_level: str = "medium"


class ContentOptimizationResponse(BaseModel):
    success: bool
    optimized_content: str
    score_before: float
    score_after: float
    improvements: List[str]


class ContentAnalysisRequest(BaseModel):
    content: str


class ContentAnalysisResponse(BaseModel):
    success: bool
    overall_score: float
    structure_score: float
    citation_score: float
    readability_score: float
    authority_score: float
    geo_compliance: float
    issues: List[str]
    suggestions: List[str]


class MetricsRecordRequest(BaseModel):
    ai_citation_count: int
    brand_mention_count: int
    answer_space_coverage: float
    source_diversity_score: float
    content_quality_score: float
    citations_by_platform: Dict[str, int]
    mentions_by_source: Dict[str, int]
    top_queries: List[str]


class MetricsReportResponse(BaseModel):
    success: bool
    ai_citation_rate: Dict
    brand_mention_rate: Dict
    answer_space_coverage: Dict
    visibility_score: Dict
    recommendations: List[Dict]


# 创建FastAPI应用
def create_app() -> FastAPI:
    app = FastAPI(
        title="GEO内容工程系统API",
        description="提供GEO内容生成、优化、分析等功能的RESTful API",
        version="1.0.0"
    )
    
    # 配置CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 初始化组件
    generator = GEOArticleGenerator()
    optimizer = GEOContentOptimizer()
    analyzer = ContentAnalyzer()
    metrics_tracker = GEOMetricsTracker()
    authority_builder = AuthorityBuilder()
    
    @app.get("/")
    async def root():
        return {
            "message": "GEO内容工程系统API",
            "version": "1.0.0",
            "docs": "/docs"
        }
    
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "timestamp": __import__('datetime').datetime.now().isoformat()}
    
    # 内容生成API
    @app.post("/api/v1/content/generate", response_model=ContentGenerationResponse)
    async def generate_content(request: ContentGenerationRequest):
        try:
            brand_info = {
                "name": request.brand_name,
                "industry": request.industry,
                "expertise": request.expertise
            }
            
            result = generator.generate(
                title=request.title,
                brand_info=brand_info,
                target_platform=request.target_platform,
                word_count=request.word_count
            )
            
            return ContentGenerationResponse(
                success=True,
                title=result['title'],
                outline=result['outline'],
                prompt=result['prompt'],
                message="内容生成成功"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # 内容优化API
    @app.post("/api/v1/content/optimize", response_model=ContentOptimizationResponse)
    async def optimize_content(request: ContentOptimizationRequest):
        try:
            result = optimizer.optimize(
                request.content,
                optimization_level=request.optimization_level
            )
            
            return ContentOptimizationResponse(
                success=True,
                optimized_content=result.optimized_content,
                score_before=result.score_before,
                score_after=result.score_after,
                improvements=result.improvements
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # 内容分析API
    @app.post("/api/v1/content/analyze", response_model=ContentAnalysisResponse)
    async def analyze_content(request: ContentAnalysisRequest):
        try:
            result = analyzer.analyze(request.content)
            
            return ContentAnalysisResponse(
                success=True,
                overall_score=result.overall_score,
                structure_score=result.structure_score,
                citation_score=result.citation_score,
                readability_score=result.readability_score,
                authority_score=result.authority_score,
                geo_compliance=result.geo_compliance,
                issues=result.issues,
                suggestions=result.suggestions
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # 记录指标API
    @app.post("/api/v1/metrics/record")
    async def record_metrics(request: MetricsRecordRequest):
        try:
            from modules.data.metrics_tracker import GEOMetrics
            from datetime import datetime
            
            metrics = GEOMetrics(
                date=datetime.now().isoformat(),
                ai_citation_count=request.ai_citation_count,
                brand_mention_count=request.brand_mention_count,
                answer_space_coverage=request.answer_space_coverage,
                source_diversity_score=request.source_diversity_score,
                content_quality_score=request.content_quality_score,
                citations_by_platform=request.citations_by_platform,
                mentions_by_source=request.mentions_by_source,
                top_queries=request.top_queries
            )
            
            metrics_tracker.record_metrics(metrics)
            
            return {"success": True, "message": "指标记录成功"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # 获取报告API
    @app.get("/api/v1/metrics/report", response_model=MetricsReportResponse)
    async def get_metrics_report(report_type: str = "monthly"):
        try:
            report = metrics_tracker.generate_report(report_type)
            
            return MetricsReportResponse(
                success=True,
                ai_citation_rate=report['basic_metrics']['ai_citation_rate'],
                brand_mention_rate=report['basic_metrics']['brand_mention_rate'],
                answer_space_coverage=report['basic_metrics']['answer_space_coverage'],
                visibility_score=report['basic_metrics']['visibility_score'],
                recommendations=report['recommendations']
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # 信源建设API
    @app.get("/api/v1/authority/pyramid")
    async def get_authority_pyramid():
        try:
            pyramid = authority_builder.get_authority_pyramid()
            return {"success": True, "data": pyramid}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/api/v1/authority/official-site-plan")
    async def get_official_site_plan(brand_info: Dict):
        try:
            plan = authority_builder.build_official_site_authority(brand_info)
            return {"success": True, "data": plan}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    return app


def main():
    """启动API服务器"""
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
