"""
引用优化器
优化内容中的引用和数据呈现
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Citation:
    """引用信息"""
    text: str
    source: str
    source_type: str  # research, expert, data, case_study
    date: Optional[str]
    credibility_score: float
    position: int  # 在内容中的位置


@dataclass
class Statistic:
    """统计数据"""
    value: str
    metric: str
    context: str
    source: Optional[str]
    year: Optional[str]


class CitationOptimizer:
    """
    引用优化器
    
    优化内容中的引用和数据呈现，提升AI引用率：
    - 识别和优化现有引用
    - 建议添加新引用
    - 优化数据呈现方式
    - 提升引用可信度
    """
    
    def __init__(self):
        self.credibility_sources = self._load_credibility_sources()
        self.citation_patterns = self._load_citation_patterns()
        
    def _load_credibility_sources(self) -> Dict[str, float]:
        """加载可信度评分"""
        return {
            # 学术机构
            "普林斯顿大学": 0.95,
            "斯坦福大学": 0.95,
            "MIT": 0.95,
            "清华大学": 0.92,
            "北京大学": 0.92,
            
            # 研究机构
            "Gartner": 0.90,
            "Forrester": 0.90,
            "艾瑞咨询": 0.85,
            "易观": 0.82,
            
            # 科技公司
            "Google": 0.88,
            "OpenAI": 0.88,
            "Microsoft": 0.87,
            
            # 媒体
            "36氪": 0.75,
            "虎嗅": 0.75,
            "钛媒体": 0.75,
            
            # 通用
            "研究显示": 0.70,
            "数据表明": 0.65,
            "专家认为": 0.60
        }
    
    def _load_citation_patterns(self) -> Dict[str, List[str]]:
        """加载引用模式"""
        return {
            "research": [
                r'根据([^，。]+)的研究',
                r'([^，。]+)的研究表明',
                r'据([^，。]+)统计',
                r'([^，。]+)数据显示'
            ],
            "expert": [
                r'([^，。]+)指出',
                r'([^，。]+)表示',
                r'([^，。]+)认为',
                r'([^，。]+)强调'
            ],
            "data": [
                r'(\d{4})年.*?(\d+\.?\d*)',
                r'(\d+\.?\d*)\s*%',
                r'(\d+\.?\d*)\s*倍',
                r'(\d+)\s*个'
            ],
            "case_study": [
                r'以([^，。]+)为例',
                r'([^，。]+)的案例',
                r'例如[^，。]+'
            ]
        }
    
    def analyze_citations(self, content: str) -> Dict:
        """
        分析内容中的引用
        
        Args:
            content: 内容文本
            
        Returns:
            引用分析报告
        """
        citations = self._extract_citations(content)
        statistics = self._extract_statistics(content)
        
        analysis = {
            "total_citations": len(citations),
            "citation_breakdown": {
                "research": len([c for c in citations if c.source_type == "research"]),
                "expert": len([c for c in citations if c.source_type == "expert"]),
                "data": len([c for c in citations if c.source_type == "data"]),
                "case_study": len([c for c in citations if c.source_type == "case_study"])
            },
            "total_statistics": len(statistics),
            "avg_credibility": sum(c.credibility_score for c in citations) / len(citations) if citations else 0,
            "citation_density": len(citations) / len(content) * 1000 if content else 0,
            "citations": citations,
            "statistics": statistics,
            "issues": [],
            "recommendations": []
        }
        
        # 识别问题
        analysis["issues"] = self._identify_citation_issues(analysis)
        
        # 生成建议
        analysis["recommendations"] = self._generate_citation_recommendations(analysis)
        
        return analysis
    
    def _extract_citations(self, content: str) -> List[Citation]:
        """提取引用"""
        citations = []
        
        for citation_type, patterns in self.citation_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    source = match.group(1) if match.groups() else "未知来源"
                    
                    # 计算可信度
                    credibility = self._calculate_credibility(source)
                    
                    citation = Citation(
                        text=match.group(0),
                        source=source,
                        source_type=citation_type,
                        date=self._extract_date(content, match.start()),
                        credibility_score=credibility,
                        position=match.start()
                    )
                    citations.append(citation)
        
        return citations
    
    def _extract_statistics(self, content: str) -> List[Statistic]:
        """提取统计数据"""
        statistics = []
        
        # 百分比
        percentage_pattern = r'(\d+\.?\d*)\s*%'
        for match in re.finditer(percentage_pattern, content):
            context = self._get_context(content, match.start(), match.end())
            stat = Statistic(
                value=match.group(1) + "%",
                metric="percentage",
                context=context,
                source=self._find_source_for_stat(content, match.start()),
                year=self._extract_year(context)
            )
            statistics.append(stat)
        
        # 年份数据
        year_data_pattern = r'(\d{4})年.*?([\d,]+\.?\d*)'
        for match in re.finditer(year_data_pattern, content):
            context = self._get_context(content, match.start(), match.end())
            stat = Statistic(
                value=match.group(2),
                metric="yearly_data",
                context=context,
                source=self._find_source_for_stat(content, match.start()),
                year=match.group(1)
            )
            statistics.append(stat)
        
        # 倍数
        multiple_pattern = r'(\d+\.?\d*)\s*倍'
        for match in re.finditer(multiple_pattern, content):
            context = self._get_context(content, match.start(), match.end())
            stat = Statistic(
                value=match.group(1) + "倍",
                metric="multiple",
                context=context,
                source=self._find_source_for_stat(content, match.start()),
                year=self._extract_year(context)
            )
            statistics.append(stat)
        
        return statistics
    
    def _calculate_credibility(self, source: str) -> float:
        """计算来源可信度"""
        # 直接匹配
        if source in self.credibility_sources:
            return self.credibility_sources[source]
        
        # 模糊匹配
        for known_source, score in self.credibility_sources.items():
            if known_source in source or source in known_source:
                return score
        
        # 默认分数
        return 0.50
    
    def _extract_date(self, content: str, position: int) -> Optional[str]:
        """提取日期"""
        # 在引用前后查找年份
        context = content[max(0, position-100):min(len(content), position+100)]
        year_match = re.search(r'(\d{4})年', context)
        if year_match:
            return year_match.group(1)
        return None
    
    def _extract_year(self, text: str) -> Optional[str]:
        """从文本中提取年份"""
        year_match = re.search(r'(\d{4})年', text)
        if year_match:
            return year_match.group(1)
        return None
    
    def _get_context(self, content: str, start: int, end: int, 
                     context_size: int = 50) -> str:
        """获取上下文"""
        context_start = max(0, start - context_size)
        context_end = min(len(content), end + context_size)
        return content[context_start:context_end].strip()
    
    def _find_source_for_stat(self, content: str, position: int) -> Optional[str]:
        """为统计数据查找来源"""
        # 在数据前后查找来源引用
        context = content[max(0, position-200):min(len(content), position+50)]
        
        source_patterns = [
            r'根据([^，。]+)',
            r'([^，。]+)数据显示',
            r'([^，。]+)统计'
        ]
        
        for pattern in source_patterns:
            match = re.search(pattern, context)
            if match:
                return match.group(1)
        
        return None
    
    def _identify_citation_issues(self, analysis: Dict) -> List[Dict]:
        """识别引用问题"""
        issues = []
        
        # 引用数量不足
        if analysis["total_citations"] < 3:
            issues.append({
                "type": "insufficient_citations",
                "severity": "high",
                "description": f"引用数量不足（{analysis['total_citations']}个），建议至少3-5个",
                "recommendation": "添加权威来源引用"
            })
        
        # 引用类型单一
        breakdown = analysis["citation_breakdown"]
        if max(breakdown.values()) == analysis["total_citations"]:
            issues.append({
                "type": "monotonous_citation_type",
                "severity": "medium",
                "description": "引用类型单一，缺乏多样性",
                "recommendation": "混合使用研究、专家、数据和案例引用"
            })
        
        # 可信度偏低
        if analysis["avg_credibility"] < 0.7:
            issues.append({
                "type": "low_credibility",
                "severity": "medium",
                "description": f"平均可信度偏低（{analysis['avg_credibility']:.2f}）",
                "recommendation": "引用更权威的来源"
            })
        
        # 统计数据无来源
        stats_without_source = [s for s in analysis["statistics"] if not s.source]
        if stats_without_source:
            issues.append({
                "type": "unsourced_statistics",
                "severity": "high",
                "description": f"有{len(stats_without_source)}个统计数据缺少来源",
                "recommendation": "为所有统计数据添加来源"
            })
        
        return issues
    
    def _generate_citation_recommendations(self, analysis: Dict) -> List[Dict]:
        """生成引用建议"""
        recommendations = []
        
        # 基于分析结果生成建议
        breakdown = analysis["citation_breakdown"]
        
        if breakdown["research"] < 1:
            recommendations.append({
                "priority": "high",
                "type": "add_research_citation",
                "suggestion": "添加学术研究引用",
                "example": "根据普林斯顿大学2024年的研究显示...",
                "benefit": "提升内容权威性"
            })
        
        if breakdown["expert"] < 1:
            recommendations.append({
                "priority": "medium",
                "type": "add_expert_quote",
                "suggestion": "添加专家引言",
                "example": '"GEO是营销的未来"——某行业专家',
                "benefit": "增强说服力"
            })
        
        if analysis["total_statistics"] < 3:
            recommendations.append({
                "priority": "high",
                "type": "add_statistics",
                "suggestion": "添加更多统计数据支撑",
                "example": "超过60%的企业已经开始使用AI搜索",
                "benefit": "提升可信度"
            })
        
        # 通用建议
        recommendations.extend([
            {
                "priority": "medium",
                "type": "improve_citation_format",
                "suggestion": "统一引用格式",
                "example": "使用'根据XX（年份）的...'格式",
                "benefit": "提升专业度"
            },
            {
                "priority": "low",
                "type": "add_case_study",
                "suggestion": "添加具体案例",
                "example": "以某知名企业为例，其实施GEO后...",
                "benefit": "增强实用性"
            }
        ])
        
        return recommendations
    
    def optimize_citations(self, content: str) -> Dict:
        """
        优化内容中的引用
        
        Args:
            content: 原始内容
            
        Returns:
            优化结果
        """
        analysis = self.analyze_citations(content)
        optimized = content
        changes = []
        
        # 优化统计数据呈现
        for stat in analysis["statistics"]:
            if not stat.source:
                # 建议添加来源
                changes.append({
                    "type": "add_source",
                    "original": stat.value,
                    "suggestion": f"{stat.value}（需添加来源）",
                    "position": content.find(stat.value)
                })
        
        # 优化引用格式
        for citation in analysis["citations"]:
            if citation.credibility_score < 0.7:
                changes.append({
                    "type": "improve_credibility",
                    "original": citation.text,
                    "suggestion": f"考虑替换为更权威的来源",
                    "current_source": citation.source,
                    "current_score": citation.credibility_score
                })
        
        return {
            "original_content": content,
            "optimized_content": optimized,
            "analysis": analysis,
            "changes": changes,
            "improvement_potential": len(changes) / max(len(analysis["citations"]), 1)
        }
    
    def suggest_citations(self, content: str, topic: str = None) -> List[Dict]:
        """
        建议添加的引用
        
        Args:
            content: 内容
            topic: 主题
            
        Returns:
            建议列表
        """
        suggestions = []
        
        # 基于主题推荐引用
        topic_citations = {
            "GEO": [
                {
                    "source": "Princeton GEO Research 2024",
                    "statistic": "实施GEO策略的企业AI引用率平均提升40%",
                    "credibility": 0.95
                },
                {
                    "source": "Gartner",
                    "statistic": "到2026年，传统搜索流量将下降25%",
                    "credibility": 0.90
                }
            ],
            "AI搜索": [
                {
                    "source": "OpenAI",
                    "statistic": "ChatGPT月活跃用户超过1亿",
                    "credibility": 0.88
                },
                {
                    "source": "Google",
                    "statistic": "AI Overviews已覆盖超过50%的搜索查询",
                    "credibility": 0.88
                }
            ],
            "内容营销": [
                {
                    "source": "Content Marketing Institute",
                    "statistic": "内容营销的成本比传统营销低62%",
                    "credibility": 0.85
                }
            ]
        }
        
        # 查找相关主题的引用建议
        if topic and topic in topic_citations:
            suggestions.extend(topic_citations[topic])
        
        # 通用建议
        suggestions.extend([
            {
                "source": "行业研究报告",
                "statistic": "建议添加最新的行业数据",
                "credibility": 0.80,
                "type": "generic"
            },
            {
                "source": "权威专家",
                "statistic": "建议引用行业专家观点",
                "credibility": 0.75,
                "type": "generic"
            }
        ])
        
        return suggestions
    
    def generate_citation_report(self, content: str) -> Dict:
        """
        生成引用分析报告
        
        Args:
            content: 内容
            
        Returns:
            完整报告
        """
        analysis = self.analyze_citations(content)
        optimization = self.optimize_citations(content)
        
        return {
            "report_date": datetime.now().isoformat(),
            "content_stats": {
                "total_length": len(content),
                "word_count": len(content.split())
            },
            "citation_analysis": analysis,
            "optimization_suggestions": optimization["changes"],
            "score": self._calculate_citation_score(analysis),
            "benchmarks": {
                "ideal_citation_count": "3-5个",
                "ideal_statistic_count": "3-5个",
                "target_credibility": ">0.75"
            }
        }
    
    def _calculate_citation_score(self, analysis: Dict) -> float:
        """计算引用得分"""
        score = 100
        
        # 数量扣分
        if analysis["total_citations"] < 3:
            score -= 20
        elif analysis["total_citations"] < 5:
            score -= 10
        
        # 可信度扣分
        if analysis["avg_credibility"] < 0.7:
            score -= 15
        
        # 统计数据扣分
        if analysis["total_statistics"] < 3:
            score -= 15
        
        # 多样性扣分
        breakdown = analysis["citation_breakdown"]
        if max(breakdown.values()) == analysis["total_citations"]:
            score -= 10
        
        return max(0, score)


if __name__ == "__main__":
    optimizer = CitationOptimizer()
    
    sample_content = """
GEO是一种新的优化方法。根据研究显示，它效果很好。

超过60%的企业开始使用AI搜索。某专家指出，GEO是未来的趋势。

以某公司为例，其实施GEO后业绩提升了2倍。
"""
    
    print("=" * 60)
    print("引用分析")
    print("=" * 60)
    
    analysis = optimizer.analyze_citations(sample_content)
    print(f"\n引用总数: {analysis['total_citations']}")
    print(f"统计数据: {analysis['total_statistics']} 个")
    print(f"平均可信度: {analysis['avg_credibility']:.2f}")
    
    print("\n引用类型分布:")
    for ctype, count in analysis['citation_breakdown'].items():
        print(f"  - {ctype}: {count}")
    
    if analysis['issues']:
        print("\n发现问题:")
        for issue in analysis['issues']:
            print(f"  [{issue['severity']}] {issue['description']}")
    
    if analysis['recommendations']:
        print("\n优化建议:")
        for rec in analysis['recommendations'][:3]:
            print(f"  - {rec['suggestion']}")
            print(f"    示例: {rec['example']}")
