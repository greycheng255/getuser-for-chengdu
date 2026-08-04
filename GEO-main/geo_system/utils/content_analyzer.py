"""
内容分析器
分析内容的GEO质量和优化建议
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class ContentAnalysisResult:
    """内容分析结果"""
    overall_score: float
    structure_score: float
    citation_score: float
    readability_score: float
    authority_score: float
    geo_compliance: float
    issues: List[str]
    suggestions: List[str]


class ContentAnalyzer:
    """
    内容分析器
    
    全面分析内容的GEO质量，包括：
    - 结构分析
    - 引用分析
    - 可读性分析
    - 权威性分析
    - GEO合规性分析
    """
    
    def __init__(self):
        self.weights = {
            "structure": 0.25,
            "citation": 0.25,
            "readability": 0.20,
            "authority": 0.20,
            "geo_compliance": 0.10
        }
    
    def analyze(self, content: str) -> ContentAnalysisResult:
        """
        全面分析内容
        
        Args:
            content: 要分析的内容
            
        Returns:
            分析结果
        """
        structure_score = self._analyze_structure(content)
        citation_score = self._analyze_citations(content)
        readability_score = self._analyze_readability(content)
        authority_score = self._analyze_authority(content)
        geo_compliance = self._analyze_geo_compliance(content)
        
        # 计算总分
        overall_score = (
            structure_score * self.weights["structure"] +
            citation_score * self.weights["citation"] +
            readability_score * self.weights["readability"] +
            authority_score * self.weights["authority"] +
            geo_compliance * self.weights["geo_compliance"]
        )
        
        # 生成问题和建议
        issues = self._collect_issues(
            structure_score, citation_score, readability_score, 
            authority_score, geo_compliance, content
        )
        suggestions = self._generate_suggestions(content, issues)
        
        return ContentAnalysisResult(
            overall_score=round(overall_score, 1),
            structure_score=round(structure_score, 1),
            citation_score=round(citation_score, 1),
            readability_score=round(readability_score, 1),
            authority_score=round(authority_score, 1),
            geo_compliance=round(geo_compliance, 1),
            issues=issues,
            suggestions=suggestions
        )
    
    def _analyze_structure(self, content: str) -> float:
        """分析内容结构"""
        score = 100
        
        # 检查标题层级
        h1_matches = len(re.findall(r'^# [^#]', content, re.MULTILINE))
        h2_matches = len(re.findall(r'^## [^#]', content, re.MULTILINE))
        h3_matches = len(re.findall(r'^### [^#]', content, re.MULTILINE))
        
        if h1_matches == 0:
            score -= 15
        if h2_matches < 3:
            score -= 10
        if h3_matches < 2:
            score -= 5
        
        # 检查段落长度
        paragraphs = [p for p in content.split('\n\n') if p.strip()]
        long_paragraphs = [p for p in paragraphs if len(p) > 300]
        if len(long_paragraphs) > len(paragraphs) * 0.3:
            score -= 15
        
        # 检查列表使用
        has_lists = bool(re.search(r'^[\*\-\d]\.', content, re.MULTILINE))
        if not has_lists:
            score -= 10
        
        # 检查引言/引用块
        has_quotes = bool(re.search(r'^>', content, re.MULTILINE))
        if not has_quotes:
            score -= 5
        
        return max(0, score)
    
    def _analyze_citations(self, content: str) -> float:
        """分析引用情况"""
        score = 100
        
        # 统计数据引用
        statistics = re.findall(r'\d+\.?\d*\s*%|\d+\.?\d*\s*倍|\d+\.?\d*\s*个|\d{4}年', content)
        if len(statistics) < 3:
            score -= 20
        elif len(statistics) < 5:
            score -= 10
        
        # 检查来源引用
        source_patterns = [
            r'根据[^，。]+[研究显示|报告|数据]',
            r'[^，。]+[指出|表示|认为]',
            r'《[^》]+》',
            r'https?://[^\s]+'
        ]
        source_count = sum(len(re.findall(pattern, content)) for pattern in source_patterns)
        if source_count < 2:
            score -= 20
        elif source_count < 4:
            score -= 10
        
        # 检查专家引言
        quotes = re.findall(r'["""][^"""]+["""]', content)
        if len(quotes) < 1:
            score -= 15
        
        # 检查参考来源部分
        has_references = '参考' in content or '来源' in content or '引用' in content
        if not has_references:
            score -= 10
        
        return max(0, score)
    
    def _analyze_readability(self, content: str) -> float:
        """分析可读性"""
        score = 100
        
        # 检查句子长度
        sentences = re.split(r'[。！？]', content)
        sentences = [s for s in sentences if s.strip()]
        
        if sentences:
            avg_length = sum(len(s) for s in sentences) / len(sentences)
            if avg_length > 80:
                score -= 15
            elif avg_length > 60:
                score -= 5
        
        long_sentences = [s for s in sentences if len(s) > 100]
        if len(long_sentences) > len(sentences) * 0.2:
            score -= 15
        
        # 检查专业术语解释
        jargon_indicators = ['即', '是指', '简单来说', '换句话说', '例如']
        has_explanations = any(indicator in content for indicator in jargon_indicators)
        if not has_explanations:
            score -= 10
        
        # 检查过渡词使用
        transition_words = ['首先', '其次', '此外', '因此', '然而', '总之', '综上所述']
        transition_count = sum(content.count(word) for word in transition_words)
        if transition_count < 3:
            score -= 10
        
        # 检查被动语态（简化检查）
        passive_markers = ['被', '由', '经过', '受到']
        passive_count = sum(content.count(marker) for marker in passive_markers)
        if len(sentences) > 0 and passive_count > len(sentences) * 0.3:
            score -= 10
        
        return max(0, score)
    
    def _analyze_authority(self, content: str) -> float:
        """分析权威性"""
        score = 100
        
        # 检查具体案例
        case_indicators = ['案例', '实例', '例如', '比如', '如', '以.*为例']
        case_count = sum(len(re.findall(indicator, content)) for indicator in case_indicators)
        if case_count < 2:
            score -= 20
        elif case_count < 4:
            score -= 10
        
        # 检查精确数字
        precise_numbers = re.findall(r'\d{4}年|\d+\.\d{2}|\d+\.\d+%', content)
        if len(precise_numbers) < 2:
            score -= 15
        
        # 检查时间敏感性
        time_references = re.findall(r'20\d{2}|今年|去年|最新|近期|当前', content)
        if len(time_references) < 2:
            score -= 10
        
        # 检查权威来源引用
        authority_sources = ['研究', '报告', '数据', '调查', '分析']
        authority_count = sum(content.count(source) for source in authority_sources)
        if authority_count < 3:
            score -= 15
        
        # 检查深度分析
        analysis_indicators = ['原因', '影响', '结果', '意义', '价值', '挑战', '机遇']
        analysis_count = sum(content.count(indicator) for indicator in analysis_indicators)
        if analysis_count < 5:
            score -= 10
        
        return max(0, score)
    
    def _analyze_geo_compliance(self, content: str) -> float:
        """分析GEO合规性"""
        score = 100
        
        # 检查ERE框架应用
        # Entity检查
        entity_indicators = ['是', '称为', '指的是', '即']
        entity_count = sum(content.count(indicator) for indicator in entity_indicators)
        if entity_count < 5:
            score -= 15
        
        # Relation检查
        relation_indicators = ['导致', '影响', '相关', '关联', '因为', '所以', '从而']
        relation_count = sum(content.count(indicator) for indicator in relation_indicators)
        if relation_count < 5:
            score -= 15
        
        # Evidence检查
        evidence_indicators = ['数据显示', '研究表明', '根据', '统计', '调查']
        evidence_count = sum(content.count(indicator) for indicator in evidence_indicators)
        if evidence_count < 3:
            score -= 20
        
        # 检查答案友好性
        # 是否有直接回答问题的结构
        answer_patterns = [r'.*是.*', r'.*指的是.*', r'.*意味着.*']
        has_answer_structure = any(re.search(pattern, content) for pattern in answer_patterns)
        if not has_answer_structure:
            score -= 10
        
        # 检查结构化数据友好性
        # 是否有清晰的层次结构
        structure_score = len(re.findall(r'^##?#? ', content, re.MULTILINE))
        if structure_score < 5:
            score -= 10
        
        return max(0, score)
    
    def _collect_issues(self, structure: float, citation: float, 
                       readability: float, authority: float, 
                       geo: float, content: str) -> List[str]:
        """收集问题"""
        issues = []
        
        if structure < 70:
            issues.append("内容结构需要优化：建议增加标题层级，使用更多列表和引用")
        if citation < 70:
            issues.append("引用支撑不足：建议增加统计数据、来源引用和专家引言")
        if readability < 70:
            issues.append("可读性有待提升：建议缩短句子，增加过渡词，解释专业术语")
        if authority < 70:
            issues.append("权威性需要加强：建议增加具体案例、精确数据和深度分析")
        if geo < 70:
            issues.append("GEO合规性不足：建议强化ERE框架应用，优化答案友好性")
        
        return issues
    
    def _generate_suggestions(self, content: str, issues: List[str]) -> List[str]:
        """生成优化建议"""
        suggestions = []
        
        # 基于内容长度的建议
        word_count = len(content)
        if word_count < 1000:
            suggestions.append("文章篇幅较短，建议扩展到1500-3000字以获得更好的AI引用效果")
        elif word_count > 5000:
            suggestions.append("文章篇幅较长，建议添加更多小标题和列表来提升可读性")
        
        # 基于问题的建议
        if "引用支撑不足" in str(issues):
            suggestions.append("在每个关键观点后添加具体的统计数据或研究引用")
        
        if "权威性" in str(issues):
            suggestions.append("添加2-3个具体的客户案例或成功故事")
        
        # 通用建议
        suggestions.extend([
            "在文章开头添加一个简洁的摘要段落，方便AI提取核心观点",
            "使用更多H2/H3标题来组织内容，提升结构化程度",
            "考虑添加FAQ部分，直接回答常见问题",
            "在文章末尾添加相关文章推荐，增加内容关联性",
            "定期更新文章中的数据和案例，保持内容时效性"
        ])
        
        return suggestions[:8]  # 限制建议数量
    
    def compare_contents(self, content1: str, content2: str) -> Dict:
        """
        比较两篇内容
        
        Args:
            content1: 第一篇内容
            content2: 第二篇内容
            
        Returns:
            比较结果
        """
        analysis1 = self.analyze(content1)
        analysis2 = self.analyze(content2)
        
        return {
            "content1_score": analysis1.overall_score,
            "content2_score": analysis2.overall_score,
            "winner": "content1" if analysis1.overall_score > analysis2.overall_score else "content2",
            "score_difference": abs(analysis1.overall_score - analysis2.overall_score),
            "content1_strengths": self._get_strengths(analysis1),
            "content2_strengths": self._get_strengths(analysis2),
            "detailed_comparison": {
                "structure": {
                    "content1": analysis1.structure_score,
                    "content2": analysis2.structure_score
                },
                "citation": {
                    "content1": analysis1.citation_score,
                    "content2": analysis2.citation_score
                },
                "readability": {
                    "content1": analysis1.readability_score,
                    "content2": analysis2.readability_score
                },
                "authority": {
                    "content1": analysis1.authority_score,
                    "content2": analysis2.authority_score
                }
            }
        }
    
    def _get_strengths(self, result: ContentAnalysisResult) -> List[str]:
        """获取优势项"""
        strengths = []
        if result.structure_score >= 80:
            strengths.append("结构清晰")
        if result.citation_score >= 80:
            strengths.append("引用丰富")
        if result.readability_score >= 80:
            strengths.append("可读性强")
        if result.authority_score >= 80:
            strengths.append("内容权威")
        if result.geo_compliance >= 80:
            strengths.append("GEO合规")
        return strengths


if __name__ == "__main__":
    analyzer = ContentAnalyzer()
    
    sample_content = """
# 什么是GEO

GEO（生成式引擎优化）是一种针对AI搜索引擎的内容优化方法。

## 为什么GEO很重要

根据2024年的研究显示，超过60%的用户开始使用AI搜索。这意味着传统的SEO方法已经不够了。

## 如何实施GEO

首先，你需要理解ERE框架。其次，优化你的内容结构。此外，建立权威信源也很重要。

## 总结

GEO是未来的趋势。
"""
    
    result = analyzer.analyze(sample_content)
    print(f"整体得分: {result.overall_score}")
    print(f"结构得分: {result.structure_score}")
    print(f"引用得分: {result.citation_score}")
    print(f"可读性得分: {result.readability_score}")
    print(f"权威性得分: {result.authority_score}")
    print(f"GEO合规性: {result.geo_compliance}")
    print(f"\n问题: {result.issues}")
    print(f"\n建议: {result.suggestions[:3]}")
