"""
GEO内容优化器
优化现有内容以提升AI引用率
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class OptimizationResult:
    """优化结果"""
    original_text: str
    optimized_text: str
    changes: List[Dict]
    score_before: float
    score_after: float
    suggestions: List[str]


class GEOContentOptimizer:
    """
    GEO内容优化器
    
    分析和优化内容，提升被AI引用的概率
    """
    
    def __init__(self):
        self.optimization_rules = self._load_rules()
        
    def _load_rules(self) -> Dict:
        """加载优化规则"""
        return {
            "structure_rules": {
                "heading_hierarchy": True,
                "paragraph_length": {"min": 50, "max": 200},
                "sentence_length": {"max": 50}
            },
            "citation_rules": {
                "statistics_required": True,
                "source_attribution": True,
                "expert_quotes_recommended": True
            },
            "readability_rules": {
                "active_voice_preferred": True,
                "jargon_explanation": True,
                "list_usage": True
            }
        }
    
    def analyze(self, content: str) -> Dict:
        """
        分析内容的GEO质量
        
        Args:
            content: 要分析的内容
            
        Returns:
            分析报告字典
        """
        analysis = {
            "overall_score": 0,
            "structure_score": self._analyze_structure(content),
            "citation_score": self._analyze_citations(content),
            "readability_score": self._analyze_readability(content),
            "authority_score": self._analyze_authority(content),
            "issues": [],
            "strengths": []
        }
        
        # 计算总分
        analysis["overall_score"] = (
            analysis["structure_score"] * 0.25 +
            analysis["citation_score"] * 0.25 +
            analysis["readability_score"] * 0.25 +
            analysis["authority_score"] * 0.25
        )
        
        # 识别问题和优势
        analysis["issues"] = self._identify_issues(analysis)
        analysis["strengths"] = self._identify_strengths(analysis)
        
        return analysis
    
    def _analyze_structure(self, content: str) -> float:
        """分析内容结构"""
        score = 100
        
        # 检查标题层级
        h1_count = len(re.findall(r'^# [^#]', content, re.MULTILINE))
        h2_count = len(re.findall(r'^## [^#]', content, re.MULTILINE))
        h3_count = len(re.findall(r'^### [^#]', content, re.MULTILINE))
        
        if h1_count == 0:
            score -= 20
        if h2_count < 3:
            score -= 15
        if h3_count < 2:
            score -= 10
        
        # 检查段落长度
        paragraphs = content.split('\n\n')
        long_paragraphs = [p for p in paragraphs if len(p) > 300]
        if len(long_paragraphs) > len(paragraphs) * 0.3:
            score -= 15
        
        # 检查是否有列表
        if not re.search(r'^[\*\-\d]\.', content, re.MULTILINE):
            score -= 10
        
        return max(0, score)
    
    def _analyze_citations(self, content: str) -> float:
        """分析引用情况"""
        score = 100
        
        # 检查统计数据
        statistics = re.findall(r'\d+\.?\d*\s*%|\d+\.?\d*\s*倍|\d+\.?\d*\s*个', content)
        if len(statistics) < 3:
            score -= 20
        
        # 检查来源引用
        sources = re.findall(r'根据[^，。]+[研究显示|报告|数据]', content)
        if len(sources) < 2:
            score -= 20
        
        # 检查专家引言
        quotes = re.findall(r'["""][^"""]+["""]', content)
        if len(quotes) < 1:
            score -= 15
        
        # 检查是否有参考来源部分
        if '参考' not in content and '来源' not in content:
            score -= 15
        
        return max(0, score)
    
    def _analyze_readability(self, content: str) -> float:
        """分析可读性"""
        score = 100
        
        # 检查句子长度
        sentences = re.split(r'[。！？]', content)
        long_sentences = [s for s in sentences if len(s) > 100]
        if len(long_sentences) > len(sentences) * 0.2:
            score -= 20
        
        # 检查专业术语解释
        jargon_patterns = [r'即[^，。]+', r'是指[^，。]+', r'简单来说[^，。]+']
        has_explanations = any(re.search(pattern, content) for pattern in jargon_patterns)
        if not has_explanations:
            score -= 15
        
        # 检查主动语态使用（简化检查）
        passive_markers = ['被', '由', '经过']
        passive_count = sum(content.count(marker) for marker in passive_markers)
        if passive_count > len(sentences) * 0.3:
            score -= 10
        
        return max(0, score)
    
    def _analyze_authority(self, content: str) -> float:
        """分析权威性"""
        score = 100
        
        # 检查具体案例
        case_indicators = ['案例', '实例', '例如', '比如', '如']
        has_cases = any(indicator in content for indicator in case_indicators)
        if not has_cases:
            score -= 20
        
        # 检查精确数字
        precise_numbers = re.findall(r'\d{4}年|\d+\.\d{2}', content)
        if len(precise_numbers) < 2:
            score -= 15
        
        # 检查时间敏感性
        time_references = re.findall(r'20\d{2}|今年|去年|最新', content)
        if len(time_references) < 2:
            score -= 10
        
        return max(0, score)
    
    def _identify_issues(self, analysis: Dict) -> List[str]:
        """识别问题"""
        issues = []
        
        if analysis["structure_score"] < 70:
            issues.append("内容结构需要优化：建议增加标题层级，缩短段落长度")
        if analysis["citation_score"] < 70:
            issues.append("引用支撑不足：建议增加统计数据、来源引用和专家引言")
        if analysis["readability_score"] < 70:
            issues.append("可读性有待提升：建议缩短句子，解释专业术语")
        if analysis["authority_score"] < 70:
            issues.append("权威性需要加强：建议增加具体案例和精确数据")
        
        return issues
    
    def _identify_strengths(self, analysis: Dict) -> List[str]:
        """识别优势"""
        strengths = []
        
        if analysis["structure_score"] >= 80:
            strengths.append("内容结构清晰，标题层级合理")
        if analysis["citation_score"] >= 80:
            strengths.append("引用丰富，数据支撑充分")
        if analysis["readability_score"] >= 80:
            strengths.append("可读性强，表达清晰")
        if analysis["authority_score"] >= 80:
            strengths.append("内容权威，案例具体")
        
        return strengths
    
    def optimize(self, content: str, optimization_level: str = "medium") -> OptimizationResult:
        """
        优化内容
        
        Args:
            content: 原始内容
            optimization_level: 优化级别 (light, medium, heavy)
            
        Returns:
            优化结果
        """
        score_before = self.analyze(content)["overall_score"]
        changes = []
        
        optimized = content
        
        # 根据优化级别应用不同规则
        if optimization_level in ["medium", "heavy"]:
            optimized, structure_changes = self._optimize_structure(optimized)
            changes.extend(structure_changes)
        
        if optimization_level in ["light", "medium", "heavy"]:
            optimized, citation_changes = self._optimize_citations(optimized)
            changes.extend(citation_changes)
        
        if optimization_level == "heavy":
            optimized, readability_changes = self._optimize_readability(optimized)
            changes.extend(readability_changes)
        
        score_after = self.analyze(optimized)["overall_score"]
        
        suggestions = self._generate_suggestions(optimized)
        
        return OptimizationResult(
            original_text=content,
            optimized_text=optimized,
            changes=changes,
            score_before=score_before,
            score_after=score_after,
            suggestions=suggestions
        )
    
    def _optimize_structure(self, content: str) -> Tuple[str, List[Dict]]:
        """优化结构"""
        changes = []
        optimized = content
        
        # 添加或优化标题
        if not re.search(r'^# ', optimized, re.MULTILINE):
            optimized = "# 文章标题\n\n" + optimized
            changes.append({
                "type": "structure",
                "description": "添加主标题",
                "location": "开头"
            })
        
        # 优化段落长度
        paragraphs = optimized.split('\n\n')
        optimized_paragraphs = []
        for para in paragraphs:
            if len(para) > 300:
                # 尝试在合适的位置拆分
                sentences = re.split(r'([。！？])', para)
                mid = len(sentences) // 2
                para = ''.join(sentences[:mid]) + '\n\n' + ''.join(sentences[mid:])
                changes.append({
                    "type": "structure",
                    "description": "拆分过长段落",
                    "location": "正文"
                })
            optimized_paragraphs.append(para)
        
        optimized = '\n\n'.join(optimized_paragraphs)
        
        return optimized, changes
    
    def _optimize_citations(self, content: str) -> Tuple[str, List[Dict]]:
        """优化引用"""
        changes = []
        
        # 标记需要添加数据支撑的位置
        # 这里简化处理，实际应该更智能
        
        return content, changes
    
    def _optimize_readability(self, content: str) -> Tuple[str, List[Dict]]:
        """优化可读性"""
        changes = []
        
        # 简化长句
        # 这里简化处理
        
        return content, changes
    
    def _generate_suggestions(self, content: str) -> List[str]:
        """生成优化建议"""
        return [
            "考虑在关键观点后添加具体的统计数据支撑",
            "可以增加一个'常见问题'章节，提升实用性",
            "建议添加相关图表或信息图，增强可视化",
            "考虑引用行业内权威专家的引言",
            "可以在文章末尾添加'延伸阅读'推荐"
        ]
    
    def rewrite_for_platform(self, content: str, target_platform: str) -> str:
        """
        为特定平台改写内容
        
        Args:
            content: 原始内容
            target_platform: 目标平台 (chatgpt, perplexity, google_ai_overviews, gemini)
            
        Returns:
            改写后的内容
        """
        platform_rules = {
            "chatgpt": {
                "style": "深入、全面",
                "focus": "概念解释和深度分析",
                "length": "2000-4000字"
            },
            "perplexity": {
                "style": "学术化、研究型",
                "focus": "数据来源和研究引用",
                "length": "1500-3000字"
            },
            "google_ai_overviews": {
                "style": "结构化、简洁",
                "focus": "要点列表和快速答案",
                "length": "1000-2500字"
            },
            "gemini": {
                "style": "综合、多角度",
                "focus": "平衡深度和广度",
                "length": "2000-4000字"
            }
        }
        
        rules = platform_rules.get(target_platform, platform_rules["chatgpt"])
        
        # 构建改写提示词
        prompt = f"""请将以下内容改写为适合{target_platform}平台的文章。

改写要求：
- 风格：{rules['style']}
- 重点：{rules['focus']}
- 长度：{rules['length']}

原始内容：
{content}

请保持核心信息不变，但调整表达方式以适应目标平台的特性。
"""
        
        return prompt


if __name__ == "__main__":
    optimizer = GEOContentOptimizer()
    
    sample_content = """
GEO是一种新的优化方法。

它帮助企业提升在AI搜索中的可见性。很多企业已经开始使用这种方法了。

未来GEO会变得越来越重要。
"""
    
    analysis = optimizer.analyze(sample_content)
    print(f"整体评分: {analysis['overall_score']:.1f}")
    print(f"结构评分: {analysis['structure_score']:.1f}")
    print(f"引用评分: {analysis['citation_score']:.1f}")
    print(f"可读性评分: {analysis['readability_score']:.1f}")
    print(f"权威性评分: {analysis['authority_score']:.1f}")
    print(f"\n问题: {analysis['issues']}")
    print(f"优势: {analysis['strengths']}")
