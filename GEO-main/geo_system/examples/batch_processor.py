"""
GEO批量处理示例
演示如何批量生成和优化GEO内容
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.content_generator import GEOArticleGenerator
from core.content_optimizer import GEOContentOptimizer
from utils.content_analyzer import ContentAnalyzer
from typing import List, Dict
import json
from datetime import datetime


class BatchContentProcessor:
    """批量内容处理器"""
    
    def __init__(self):
        self.generator = GEOArticleGenerator()
        self.optimizer = GEOContentOptimizer()
        self.analyzer = ContentAnalyzer()
        self.results = []
    
    def process_topics(self, topics: List[Dict], brand_info: Dict) -> List[Dict]:
        """
        批量处理多个主题
        
        Args:
            topics: 主题列表，每个主题包含title、keywords等
            brand_info: 品牌信息
        
        Returns:
            处理结果列表
        """
        print(f"开始批量处理 {len(topics)} 个主题...")
        
        for i, topic in enumerate(topics, 1):
            print(f"\n[{i}/{len(topics)}] 处理主题: {topic['title']}")
            
            try:
                result = self._process_single_topic(topic, brand_info)
                self.results.append(result)
                print(f"  ✓ 完成 - 质量得分: {result['quality_score']:.1f}")
            except Exception as e:
                print(f"  ✗ 失败 - 错误: {e}")
                self.results.append({
                    'title': topic['title'],
                    'status': 'failed',
                    'error': str(e)
                })
        
        return self.results
    
    def _process_single_topic(self, topic: Dict, brand_info: Dict) -> Dict:
        """处理单个主题"""
        # 1. 生成内容大纲
        generation_result = self.generator.generate(
            title=topic['title'],
            brand_info=brand_info,
            target_platform=topic.get('platform', 'chatgpt'),
            word_count=topic.get('word_count', 3000)
        )
        
        # 2. 分析内容质量（使用大纲进行评估）
        content_text = self._outline_to_text(generation_result['outline'])
        analysis = self.analyzer.analyze(content_text)
        
        # 3. 如果质量不达标，记录优化建议
        optimization_suggestions = []
        if analysis.overall_score < 70:
            optimization_suggestions = analysis.suggestions
        
        return {
            'title': topic['title'],
            'status': 'success',
            'outline': generation_result['outline'],
            'prompt': generation_result['prompt'],
            'quality_score': analysis.overall_score,
            'structure_score': analysis.structure_score,
            'citation_score': analysis.citation_score,
            'readability_score': analysis.readability_score,
            'authority_score': analysis.authority_score,
            'issues': analysis.issues,
            'optimization_suggestions': optimization_suggestions,
            'created_at': datetime.now().isoformat()
        }
    
    def _outline_to_text(self, outline: List[Dict]) -> str:
        """将大纲转换为文本进行分析"""
        text_parts = []
        for item in outline:
            text_parts.append(item['title'])
            if 'content_points' in item:
                text_parts.extend(item['content_points'])
        return '\n'.join(text_parts)
    
    def export_results(self, output_path: str):
        """导出处理结果"""
        report = {
            'generated_at': datetime.now().isoformat(),
            'total_topics': len(self.results),
            'successful': len([r for r in self.results if r.get('status') == 'success']),
            'failed': len([r for r in self.results if r.get('status') == 'failed']),
            'average_quality_score': sum(
                r.get('quality_score', 0) for r in self.results if r.get('status') == 'success'
            ) / max(len([r for r in self.results if r.get('status') == 'success']), 1),
            'results': self.results
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n结果已导出到: {output_path}")
        return report
    
    def generate_summary_report(self) -> str:
        """生成摘要报告"""
        successful = [r for r in self.results if r.get('status') == 'success']
        failed = [r for r in self.results if r.get('status') == 'failed']
        
        if not successful:
            return "没有成功处理的内容"
        
        avg_score = sum(r.get('quality_score', 0) for r in successful) / len(successful)
        
        report = f"""
========================================
GEO批量处理报告
========================================
处理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
----------------------------------------
总主题数: {len(self.results)}
成功: {len(successful)}
失败: {len(failed)}
----------------------------------------
平均质量得分: {avg_score:.1f}/100
----------------------------------------
得分分布:
"""
        
        # 统计得分分布
        score_ranges = {
            '优秀 (80-100)': 0,
            '良好 (60-79)': 0,
            '需改进 (<60)': 0
        }
        
        for r in successful:
            score = r.get('quality_score', 0)
            if score >= 80:
                score_ranges['优秀 (80-100)'] += 1
            elif score >= 60:
                score_ranges['良好 (60-79)'] += 1
            else:
                score_ranges['需改进 (<60)'] += 1
        
        for range_name, count in score_ranges.items():
            percentage = (count / len(successful)) * 100 if successful else 0
            report += f"  {range_name}: {count} ({percentage:.1f}%)\n"
        
        report += "----------------------------------------\n"
        report += "需要优化的内容:\n"
        
        need_optimization = [r for r in successful if r.get('quality_score', 0) < 70]
        if need_optimization:
            for r in need_optimization[:5]:
                report += f"  - {r['title']} (得分: {r['quality_score']:.1f})\n"
        else:
            report += "  所有内容质量良好\n"
        
        report += "========================================\n"
        
        return report


def demo_batch_processing():
    """演示批量处理"""
    # 示例主题列表
    topics = [
        {
            'title': '什么是生成式引擎优化（GEO）：AI搜索时代的营销新范式',
            'keywords': ['GEO', 'AI搜索', '营销'],
            'platform': 'chatgpt',
            'word_count': 3000
        },
        {
            'title': 'GEO与SEO的区别：从关键词排名到AI引用的转变',
            'keywords': ['GEO', 'SEO', '对比'],
            'platform': 'perplexity',
            'word_count': 2500
        },
        {
            'title': 'ERE框架详解：实体、关系、证据在GEO中的应用',
            'keywords': ['ERE框架', '实体', '关系', '证据'],
            'platform': 'chatgpt',
            'word_count': 3500
        },
        {
            'title': '如何构建四级信源权威体系提升AI引用率',
            'keywords': ['信源建设', '权威', '引用率'],
            'platform': 'google_ai',
            'word_count': 2800
        },
        {
            'title': 'Schema.org结构化数据在GEO中的最佳实践',
            'keywords': ['Schema.org', '结构化数据', 'GEO'],
            'platform': 'chatgpt',
            'word_count': 3200
        }
    ]
    
    brand_info = {
        'name': '智媒科技',
        'industry': 'AI营销',
        'expertise': ['GEO', 'AI搜索优化', '内容营销', '数字化转型'],
        'description': '专注于AI时代的营销技术解决方案，帮助企业提升AI搜索可见性'
    }
    
    # 创建处理器
    processor = BatchContentProcessor()
    
    # 批量处理
    results = processor.process_topics(topics, brand_info)
    
    # 打印摘要报告
    print(processor.generate_summary_report())
    
    # 导出结果
    output_path = 'batch_processing_results.json'
    processor.export_results(output_path)
    
    return results


if __name__ == '__main__':
    print("=" * 60)
    print("GEO批量处理示例")
    print("=" * 60)
    demo_batch_processing()
