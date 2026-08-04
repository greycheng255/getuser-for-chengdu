"""
竞品GEO分析器
分析竞争对手的GEO策略和表现
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import json


@dataclass
class CompetitorProfile:
    """竞品档案"""
    name: str
    website: str
    industry: str
    size: str  # startup, smb, enterprise
    geo_maturity: str  # beginner, intermediate, advanced
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    

@dataclass
class CompetitorMetrics:
    """竞品指标"""
    ai_citation_count: int
    brand_mention_count: int
    content_volume: int
    avg_content_quality: float
    source_diversity: float
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())


class CompetitorAnalyzer:
    """
    竞品GEO分析器
    
    分析竞争对手的GEO策略，包括：
    - 内容策略分析
    - 信源建设分析
    - AI引用表现
    - 优势和劣势识别
    - 机会和威胁分析
    """
    
    def __init__(self):
        self.competitors: Dict[str, CompetitorProfile] = {}
        self.metrics_history: Dict[str, List[CompetitorMetrics]] = {}
        self.analysis_cache: Dict[str, Dict] = {}
    
    def add_competitor(self, name: str, website: str, industry: str,
                       size: str = "smb", geo_maturity: str = "intermediate") -> CompetitorProfile:
        """
        添加竞品
        
        Args:
            name: 竞品名称
            website: 网站
            industry: 行业
            size: 规模
            geo_maturity: GEO成熟度
            
        Returns:
            竞品档案
        """
        profile = CompetitorProfile(
            name=name,
            website=website,
            industry=industry,
            size=size,
            geo_maturity=geo_maturity
        )
        self.competitors[name] = profile
        self.metrics_history[name] = []
        return profile
    
    def record_metrics(self, competitor_name: str, metrics: CompetitorMetrics):
        """
        记录竞品指标
        
        Args:
            competitor_name: 竞品名称
            metrics: 指标数据
        """
        if competitor_name not in self.metrics_history:
            self.metrics_history[competitor_name] = []
        self.metrics_history[competitor_name].append(metrics)
    
    def analyze_content_strategy(self, competitor_name: str,
                                  content_samples: List[Dict] = None) -> Dict:
        """
        分析内容策略
        
        Args:
            competitor_name: 竞品名称
            content_samples: 内容样本
            
        Returns:
            内容策略分析
        """
        competitor = self.competitors.get(competitor_name)
        if not competitor:
            return {"error": "竞品不存在"}
        
        analysis = {
            "competitor": competitor_name,
            "analysis_date": datetime.now().isoformat(),
            "content_themes": [],
            "content_formats": [],
            "publishing_frequency": "unknown",
            "content_quality_indicators": {},
            "geo_compliance_score": 0,
            "strengths": [],
            "weaknesses": []
        }
        
        # 分析内容主题
        if content_samples:
            themes = self._extract_themes(content_samples)
            analysis["content_themes"] = themes
            
            # 分析内容格式
            formats = self._analyze_content_formats(content_samples)
            analysis["content_formats"] = formats
            
            # 评估GEO合规性
            geo_score = self._evaluate_geo_compliance(content_samples)
            analysis["geo_compliance_score"] = geo_score
            
            # 识别优势和劣势
            analysis["strengths"] = self._identify_content_strengths(content_samples)
            analysis["weaknesses"] = self._identify_content_weaknesses(content_samples)
        
        return analysis
    
    def _extract_themes(self, content_samples: List[Dict]) -> List[Dict]:
        """提取内容主题"""
        # 简化版主题提取
        theme_keywords = {
            "教育": ["教程", "指南", "入门", "学习"],
            "趋势": ["趋势", "未来", "预测", "发展"],
            "案例": ["案例", "实例", "成功", "实践"],
            "数据": ["数据", "统计", "报告", "研究"],
            "观点": ["观点", "看法", "思考", "分析"]
        }
        
        theme_counts = {theme: 0 for theme in theme_keywords}
        
        for content in content_samples:
            text = content.get("title", "") + " " + content.get("content", "")
            for theme, keywords in theme_keywords.items():
                if any(keyword in text for keyword in keywords):
                    theme_counts[theme] += 1
        
        # 排序并返回
        sorted_themes = sorted(
            theme_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return [
            {"theme": theme, "count": count, "percentage": count / len(content_samples) * 100}
            for theme, count in sorted_themes if count > 0
        ]
    
    def _analyze_content_formats(self, content_samples: List[Dict]) -> List[Dict]:
        """分析内容格式"""
        formats = {
            "长文章": 0,
            "短文章": 0,
            "列表文章": 0,
            "问答形式": 0,
            "案例分析": 0,
            "数据报告": 0
        }
        
        for content in content_samples:
            text = content.get("content", "")
            length = len(text)
            
            if length > 2000:
                formats["长文章"] += 1
            else:
                formats["短文章"] += 1
            
            if "1." in text or "一、" in text:
                formats["列表文章"] += 1
            
            if "？" in text[:100]:
                formats["问答形式"] += 1
            
            if "案例" in text or "实例" in text:
                formats["案例分析"] += 1
            
            if "%" in text or "数据" in text:
                formats["数据报告"] += 1
        
        return [
            {"format": fmt, "count": count, "percentage": count / len(content_samples) * 100}
            for fmt, count in formats.items() if count > 0
        ]
    
    def _evaluate_geo_compliance(self, content_samples: List[Dict]) -> float:
        """评估GEO合规性"""
        scores = []
        
        for content in content_samples:
            score = 100
            text = content.get("content", "")
            
            # 检查结构
            if "##" not in text:
                score -= 20
            
            # 检查引用
            if "根据" not in text and "数据显示" not in text:
                score -= 20
            
            # 检查数据
            if "%" not in text and "个" not in text:
                score -= 15
            
            # 检查案例
            if "案例" not in text and "例如" not in text:
                score -= 15
            
            scores.append(max(0, score))
        
        return sum(scores) / len(scores) if scores else 0
    
    def _identify_content_strengths(self, content_samples: List[Dict]) -> List[str]:
        """识别内容优势"""
        strengths = []
        
        # 检查内容深度
        avg_length = sum(len(c.get("content", "")) for c in content_samples) / len(content_samples)
        if avg_length > 1500:
            strengths.append("内容深度足够，平均篇幅较长")
        
        # 检查多样性
        themes = self._extract_themes(content_samples)
        if len(themes) >= 3:
            strengths.append("内容主题多样，覆盖面广")
        
        # 检查更新频率
        if len(content_samples) >= 10:
            strengths.append("内容产出频率高")
        
        return strengths
    
    def _identify_content_weaknesses(self, content_samples: List[Dict]) -> List[str]:
        """识别内容劣势"""
        weaknesses = []
        
        # 检查内容深度
        avg_length = sum(len(c.get("content", "")) for c in content_samples) / len(content_samples)
        if avg_length < 800:
            weaknesses.append("内容深度不足，篇幅偏短")
        
        # 检查引用
        has_citations = sum(1 for c in content_samples if "根据" in c.get("content", ""))
        if has_citations < len(content_samples) * 0.5:
            weaknesses.append("引用支撑不足，权威性有待提升")
        
        return weaknesses
    
    def analyze_source_strategy(self, competitor_name: str,
                                 source_data: Dict = None) -> Dict:
        """
        分析信源策略
        
        Args:
            competitor_name: 竞品名称
            source_data: 信源数据
            
        Returns:
            信源策略分析
        """
        competitor = self.competitors.get(competitor_name)
        if not competitor:
            return {"error": "竞品不存在"}
        
        analysis = {
            "competitor": competitor_name,
            "analysis_date": datetime.now().isoformat(),
            "source_pyramid": {
                "official": {"score": 0, "strengths": [], "weaknesses": []},
                "media": {"score": 0, "sources": [], "coverage": 0},
                "community": {"score": 0, "platforms": [], "engagement": 0},
                "social": {"score": 0, "platforms": [], "followers": 0}
            },
            "authority_score": 0,
            "recommendations": []
        }
        
        if source_data:
            # 分析官网权威
            analysis["source_pyramid"]["official"] = self._analyze_official_source(source_data)
            
            # 分析媒体覆盖
            analysis["source_pyramid"]["media"] = self._analyze_media_coverage(source_data)
            
            # 分析社群影响
            analysis["source_pyramid"]["community"] = self._analyze_community_presence(source_data)
            
            # 分析社交影响
            analysis["source_pyramid"]["social"] = self._analyze_social_presence(source_data)
            
            # 计算综合权威分
            scores = [
                analysis["source_pyramid"][level]["score"]
                for level in ["official", "media", "community", "social"]
            ]
            analysis["authority_score"] = sum(scores) / len(scores)
        
        return analysis
    
    def _analyze_official_source(self, source_data: Dict) -> Dict:
        """分析官网信源"""
        website_data = source_data.get("website", {})
        
        return {
            "score": website_data.get("authority_score", 50),
            "domain_authority": website_data.get("da", 0),
            "backlinks": website_data.get("backlinks", 0),
            "strengths": [
                "官网内容丰富" if website_data.get("content_volume", 0) > 50 else None,
                "SEO优化良好" if website_data.get("seo_score", 0) > 70 else None
            ],
            "weaknesses": [
                "内容更新频率低" if website_data.get("update_frequency", 0) < 4 else None,
                "缺乏结构化数据" if not website_data.get("has_schema", False) else None
            ]
        }
    
    def _analyze_media_coverage(self, source_data: Dict) -> Dict:
        """分析媒体覆盖"""
        media_data = source_data.get("media", {})
        
        return {
            "score": min(100, media_data.get("mention_count", 0) * 5),
            "sources": media_data.get("sources", []),
            "coverage": media_data.get("mention_count", 0),
            "top_sources": media_data.get("top_sources", [])[:5]
        }
    
    def _analyze_community_presence(self, source_data: Dict) -> Dict:
        """分析社群影响"""
        community_data = source_data.get("community", {})
        
        return {
            "score": min(100, community_data.get("engagement_score", 0)),
            "platforms": community_data.get("platforms", []),
            "engagement": community_data.get("total_engagement", 0)
        }
    
    def _analyze_social_presence(self, source_data: Dict) -> Dict:
        """分析社交影响"""
        social_data = source_data.get("social", {})
        
        return {
            "score": min(100, social_data.get("total_followers", 0) / 1000),
            "platforms": social_data.get("platforms", []),
            "followers": social_data.get("total_followers", 0)
        }
    
    def compare_with_self(self, competitor_name: str,
                          self_metrics: Dict) -> Dict:
        """
        与自身对比
        
        Args:
            competitor_name: 竞品名称
            self_metrics: 自身指标
            
        Returns:
            对比分析
        """
        competitor = self.competitors.get(competitor_name)
        if not competitor:
            return {"error": "竞品不存在"}
        
        # 获取竞品最新指标
        competitor_metrics = None
        if competitor_name in self.metrics_history and self.metrics_history[competitor_name]:
            competitor_metrics = self.metrics_history[competitor_name][-1]
        
        if not competitor_metrics:
            return {"error": "没有竞品指标数据"}
        
        comparison = {
            "competitor": competitor_name,
            "analysis_date": datetime.now().isoformat(),
            "metrics_comparison": {},
            "gaps": [],
            "opportunities": []
        }
        
        # 对比各项指标
        metrics_mapping = {
            "ai_citation_count": "AI引用次数",
            "brand_mention_count": "品牌提及次数",
            "content_volume": "内容产量",
            "avg_content_quality": "内容质量",
            "source_diversity": "信源多样性"
        }
        
        for metric_key, metric_name in metrics_mapping.items():
            comp_value = getattr(competitor_metrics, metric_key, 0)
            self_value = self_metrics.get(metric_key, 0)
            
            comparison["metrics_comparison"][metric_key] = {
                "name": metric_name,
                "competitor": comp_value,
                "self": self_value,
                "difference": self_value - comp_value,
                "leader": "self" if self_value > comp_value else "competitor"
            }
            
            # 识别差距
            if self_value < comp_value * 0.8:
                comparison["gaps"].append({
                    "metric": metric_name,
                    "gap": comp_value - self_value,
                    "priority": "high" if metric_key in ["ai_citation_count", "brand_mention_count"] else "medium"
                })
            
            # 识别机会
            if self_value > comp_value * 1.2:
                comparison["opportunities"].append({
                    "metric": metric_name,
                    "advantage": self_value - comp_value,
                    "strategy": f"保持{metric_name}优势，扩大领先"
                })
        
        return comparison
    
    def identify_market_opportunities(self) -> List[Dict]:
        """
        识别市场机会
        
        Returns:
            机会列表
        """
        opportunities = []
        
        # 分析所有竞品的弱点
        all_weaknesses = []
        for name, competitor in self.competitors.items():
            all_weaknesses.extend([
                {"competitor": name, "weakness": w}
                for w in competitor.weaknesses
            ])
        
        # 统计常见弱点
        weakness_counts = {}
        for item in all_weaknesses:
            weakness = item["weakness"]
            if weakness not in weakness_counts:
                weakness_counts[weakness] = []
            weakness_counts[weakness].append(item["competitor"])
        
        # 识别机会
        for weakness, competitors in weakness_counts.items():
            if len(competitors) >= len(self.competitors) * 0.5:
                opportunities.append({
                    "type": "common_weakness",
                    "description": f"多数竞品的共同弱点: {weakness}",
                    "affected_competitors": competitors,
                    "strategy": f"强化{weakness}相关能力，形成差异化优势",
                    "priority": "high"
                })
        
        # 识别内容空白
        all_themes = set()
        for name in self.competitors:
            # 这里简化处理，实际应该分析每个竞品的内容主题
            all_themes.update(["AI趋势", "行业报告", "案例分享"])
        
        # 假设有一些未被覆盖的主题
        uncovered_themes = ["GEO实操指南", "AI搜索算法解析", "跨平台GEO策略"]
        for theme in uncovered_themes:
            opportunities.append({
                "type": "content_gap",
                "description": f"内容空白: {theme}",
                "strategy": f"率先布局{theme}内容，占领心智",
                "priority": "medium"
            })
        
        return opportunities
    
    def generate_competitive_report(self, competitor_name: str = None) -> Dict:
        """
        生成竞争分析报告
        
        Args:
            competitor_name: 特定竞品名称，None表示所有竞品
            
        Returns:
            竞争分析报告
        """
        report = {
            "report_date": datetime.now().isoformat(),
            "competitors_analyzed": len(self.competitors),
            "summary": {},
            "detailed_analysis": {},
            "recommendations": []
        }
        
        if competitor_name:
            # 分析特定竞品
            if competitor_name in self.competitors:
                report["detailed_analysis"][competitor_name] = {
                    "profile": self.competitors[competitor_name],
                    "content_strategy": self.analyze_content_strategy(competitor_name),
                    "source_strategy": self.analyze_source_strategy(competitor_name)
                }
        else:
            # 分析所有竞品
            for name in self.competitors:
                report["detailed_analysis"][name] = {
                    "profile": self.competitors[name],
                    "latest_metrics": self.metrics_history[name][-1] if self.metrics_history[name] else None
                }
            
            # 生成汇总
            report["summary"] = self._generate_summary()
            
            # 识别机会
            report["opportunities"] = self.identify_market_opportunities()
        
        # 生成建议
        report["recommendations"] = self._generate_competitive_recommendations()
        
        return report
    
    def _generate_summary(self) -> Dict:
        """生成汇总信息"""
        if not self.competitors:
            return {}
        
        # 计算平均指标
        avg_citations = 0
        avg_mentions = 0
        total_content = 0
        
        for name, history in self.metrics_history.items():
            if history:
                latest = history[-1]
                avg_citations += latest.ai_citation_count
                avg_mentions += latest.brand_mention_count
                total_content += latest.content_volume
        
        count = len(self.competitors)
        
        return {
            "avg_ai_citations": avg_citations / count if count > 0 else 0,
            "avg_brand_mentions": avg_mentions / count if count > 0 else 0,
            "total_content_analyzed": total_content,
            "most_active_competitor": self._find_most_active(),
            "highest_geo_score": self._find_highest_geo_score()
        }
    
    def _find_most_active(self) -> str:
        """找出最活跃的竞品"""
        max_content = 0
        most_active = ""
        
        for name, history in self.metrics_history.items():
            if history:
                total = sum(m.content_volume for m in history)
                if total > max_content:
                    max_content = total
                    most_active = name
        
        return most_active
    
    def _find_highest_geo_score(self) -> Dict:
        """找出GEO得分最高的竞品"""
        highest_score = 0
        best_competitor = ""
        
        for name, history in self.metrics_history.items():
            if history:
                avg_score = sum(m.avg_content_quality for m in history) / len(history)
                if avg_score > highest_score:
                    highest_score = avg_score
                    best_competitor = name
        
        return {
            "name": best_competitor,
            "score": highest_score
        }
    
    def _generate_competitive_recommendations(self) -> List[Dict]:
        """生成竞争建议"""
        return [
            {
                "priority": "high",
                "area": "content",
                "suggestion": "分析竞品高表现内容，学习其成功要素",
                "action": "建立竞品内容监测机制，定期分析"
            },
            {
                "priority": "high",
                "area": "differentiation",
                "suggestion": "避开竞品强势领域，寻找差异化定位",
                "action": "识别内容空白，率先布局"
            },
            {
                "priority": "medium",
                "area": "speed",
                "suggestion": "提高内容响应速度，抢占热点先机",
                "action": "建立快速内容生产流程"
            },
            {
                "priority": "medium",
                "area": "quality",
                "suggestion": "在内容质量上超越竞品",
                "action": "加强数据引用和案例深度"
            }
        ]
    
    def export_data(self, filepath: str):
        """导出数据"""
        data = {
            "competitors": {
                name: {
                    "name": comp.name,
                    "website": comp.website,
                    "industry": comp.industry,
                    "size": comp.size,
                    "geo_maturity": comp.geo_maturity,
                    "strengths": comp.strengths,
                    "weaknesses": comp.weaknesses
                }
                for name, comp in self.competitors.items()
            },
            "metrics_history": {
                name: [
                    {
                        "ai_citation_count": m.ai_citation_count,
                        "brand_mention_count": m.brand_mention_count,
                        "content_volume": m.content_volume,
                        "avg_content_quality": m.avg_content_quality,
                        "source_diversity": m.source_diversity,
                        "last_updated": m.last_updated
                    }
                    for m in history
                ]
                for name, history in self.metrics_history.items()
            }
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    analyzer = CompetitorAnalyzer()
    
    # 添加竞品
    analyzer.add_competitor(
        name="竞品A",
        website="https://competitor-a.com",
        industry="SaaS",
        size="enterprise",
        geo_maturity="advanced"
    )
    
    analyzer.add_competitor(
        name="竞品B",
        website="https://competitor-b.com",
        industry="SaaS",
        size="smb",
        geo_maturity="intermediate"
    )
    
    # 记录指标
    analyzer.record_metrics("竞品A", CompetitorMetrics(
        ai_citation_count=150,
        brand_mention_count=300,
        content_volume=80,
        avg_content_quality=85,
        source_diversity=0.75
    ))
    
    analyzer.record_metrics("竞品B", CompetitorMetrics(
        ai_citation_count=80,
        brand_mention_count=150,
        content_volume=50,
        avg_content_quality=70,
        source_diversity=0.60
    ))
    
    # 生成报告
    print("=" * 60)
    print("竞品分析报告")
    print("=" * 60)
    
    report = analyzer.generate_competitive_report()
    print(f"\n分析了 {report['competitors_analyzed']} 个竞品")
    print(f"平均AI引用: {report['summary']['avg_ai_citations']:.0f}")
    print(f"平均品牌提及: {report['summary']['avg_brand_mentions']:.0f}")
    
    print("\n市场机会:")
    for opp in report['opportunities'][:3]:
        print(f"  - {opp['description']}")
        print(f"    策略: {opp['strategy']}")
