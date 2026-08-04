"""
GEO内容生产流水线工具
自动化内容生成、优化和发布的完整流程
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.content_generator import GEOArticleGenerator
from core.content_optimizer import GEOContentOptimizer
from utils.content_analyzer import ContentAnalyzer
from modules.source.platform_distributor import PlatformDistributor
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import json


@dataclass
class ContentTask:
    """内容任务"""
    id: str
    title: str
    topic: str
    keywords: List[str]
    target_platform: str
    word_count: int
    priority: str
    status: str = 'pending'
    created_at: str = None
    completed_at: str = None
    result: Dict = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class ContentPipeline:
    """内容生产流水线"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.generator = GEOArticleGenerator()
        self.optimizer = GEOContentOptimizer()
        self.analyzer = ContentAnalyzer()
        self.distributor = PlatformDistributor()
        self.tasks: List[ContentTask] = []
        self.logs: List[Dict] = []
    
    def add_task(self, task: ContentTask) -> str:
        """添加任务到流水线"""
        self.tasks.append(task)
        self._log(f"任务已添加: {task.title}", 'info')
        return task.id
    
    def create_tasks_from_topics(self, topics: List[Dict], brand_info: Dict) -> List[str]:
        """从主题列表批量创建任务"""
        task_ids = []
        for i, topic in enumerate(topics):
            task = ContentTask(
                id=f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}",
                title=topic['title'],
                topic=topic.get('topic', topic['title']),
                keywords=topic.get('keywords', []),
                target_platform=topic.get('platform', 'chatgpt'),
                word_count=topic.get('word_count', 3000),
                priority=topic.get('priority', 'medium')
            )
            task_id = self.add_task(task)
            task_ids.append(task_id)
        return task_ids
    
    def process_task(self, task_id: str, brand_info: Dict) -> Dict:
        """处理单个任务"""
        task = self._get_task(task_id)
        if not task:
            return {'error': 'Task not found'}
        
        self._log(f"开始处理任务: {task.title}", 'info')
        task.status = 'processing'
        
        try:
            # 步骤1: 生成内容大纲
            self._log("步骤1: 生成内容大纲...", 'info')
            generation_result = self.generator.generate(
                title=task.title,
                brand_info=brand_info,
                target_platform=task.target_platform,
                word_count=task.word_count
            )
            
            # 步骤2: 分析内容质量
            self._log("步骤2: 分析内容质量...", 'info')
            content_text = self._outline_to_text(generation_result['outline'])
            analysis = self.analyzer.analyze(content_text)
            
            # 步骤3: 优化内容（如果质量不达标）
            optimized_outline = generation_result['outline']
            if analysis.overall_score < 70:
                self._log(f"内容质量得分 {analysis.overall_score:.1f}，进行优化...", 'warning')
                # 这里可以添加具体的优化逻辑
            
            # 步骤4: 生成平台适配版本
            self._log("步骤4: 生成平台适配版本...", 'info')
            platform_adaptation = self.distributor.adapt_content(
                content={'title': task.title, 'outline': optimized_outline},
                platform=task.target_platform
            )
            
            # 完成任务
            task.status = 'completed'
            task.completed_at = datetime.now().isoformat()
            task.result = {
                'outline': optimized_outline,
                'prompt': generation_result['prompt'],
                'quality_score': analysis.overall_score,
                'platform_adaptation': platform_adaptation,
                'suggestions': analysis.suggestions if analysis.suggestions else []
            }
            
            self._log(f"任务完成: {task.title} (质量得分: {analysis.overall_score:.1f})", 'success')
            
            return {
                'success': True,
                'task_id': task_id,
                'quality_score': analysis.overall_score,
                'result': task.result
            }
            
        except Exception as e:
            task.status = 'failed'
            self._log(f"任务失败: {task.title} - {str(e)}", 'error')
            return {
                'success': False,
                'task_id': task_id,
                'error': str(e)
            }
    
    def process_all_tasks(self, brand_info: Dict) -> List[Dict]:
        """处理所有待处理任务"""
        pending_tasks = [t for t in self.tasks if t.status == 'pending']
        self._log(f"开始批量处理 {len(pending_tasks)} 个任务...", 'info')
        
        results = []
        for task in pending_tasks:
            result = self.process_task(task.id, brand_info)
            results.append(result)
        
        return results
    
    def get_pipeline_status(self) -> Dict:
        """获取流水线状态"""
        total = len(self.tasks)
        pending = len([t for t in self.tasks if t.status == 'pending'])
        processing = len([t for t in self.tasks if t.status == 'processing'])
        completed = len([t for t in self.tasks if t.status == 'completed'])
        failed = len([t for t in self.tasks if t.status == 'failed'])
        
        # 计算平均质量得分
        completed_tasks = [t for t in self.tasks if t.status == 'completed' and t.result]
        avg_quality = sum(t.result.get('quality_score', 0) for t in completed_tasks) / len(completed_tasks) if completed_tasks else 0
        
        return {
            'total': total,
            'pending': pending,
            'processing': processing,
            'completed': completed,
            'failed': failed,
            'completion_rate': (completed / total * 100) if total > 0 else 0,
            'average_quality_score': avg_quality,
            'tasks': [
                {
                    'id': t.id,
                    'title': t.title,
                    'status': t.status,
                    'priority': t.priority,
                    'quality_score': t.result.get('quality_score') if t.result else None
                }
                for t in self.tasks
            ]
        }
    
    def export_results(self, output_dir: str = 'output'):
        """导出处理结果"""
        os.makedirs(output_dir, exist_ok=True)
        
        # 导出任务结果
        completed_tasks = [t for t in self.tasks if t.status == 'completed' and t.result]
        
        for task in completed_tasks:
            filename = f"{task.id}_{task.title[:30]}.json"
            filepath = os.path.join(output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({
                    'task': {
                        'id': task.id,
                        'title': task.title,
                        'topic': task.topic,
                        'keywords': task.keywords,
                        'target_platform': task.target_platform,
                        'created_at': task.created_at,
                        'completed_at': task.completed_at
                    },
                    'result': task.result
                }, f, ensure_ascii=False, indent=2)
        
        # 导出汇总报告
        report_path = os.path.join(output_dir, 'pipeline_report.json')
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                'generated_at': datetime.now().isoformat(),
                'status': self.get_pipeline_status(),
                'logs': self.logs
            }, f, ensure_ascii=False, indent=2)
        
        return output_dir
    
    def _get_task(self, task_id: str) -> Optional[ContentTask]:
        """获取任务"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
    
    def _outline_to_text(self, outline: List[Dict]) -> str:
        """将大纲转换为文本"""
        text_parts = []
        for item in outline:
            text_parts.append(item['title'])
            if 'content_points' in item:
                text_parts.extend(item['content_points'])
        return '\n'.join(text_parts)
    
    def _log(self, message: str, level: str = 'info'):
        """记录日志"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message
        }
        self.logs.append(log_entry)
        print(f"[{level.upper()}] {message}")


def demo_pipeline():
    """演示内容流水线"""
    print("=" * 60)
    print("GEO内容生产流水线演示")
    print("=" * 60)
    
    # 创建流水线
    pipeline = ContentPipeline()
    
    # 定义品牌信息
    brand_info = {
        'name': '智媒科技',
        'industry': 'AI营销',
        'expertise': ['GEO', 'AI搜索优化', '内容营销'],
        'description': '专注于AI时代的营销技术解决方案'
    }
    
    # 定义内容主题
    topics = [
        {
            'title': '什么是生成式引擎优化（GEO）',
            'keywords': ['GEO', 'AI搜索', '营销'],
            'platform': 'chatgpt',
            'word_count': 3000,
            'priority': 'high'
        },
        {
            'title': 'GEO与SEO的五大核心区别',
            'keywords': ['GEO', 'SEO', '对比'],
            'platform': 'perplexity',
            'word_count': 2500,
            'priority': 'high'
        },
        {
            'title': 'ERE框架实战指南',
            'keywords': ['ERE框架', '实体', '关系', '证据'],
            'platform': 'chatgpt',
            'word_count': 3500,
            'priority': 'medium'
        }
    ]
    
    # 创建任务
    print("\n📋 创建内容任务...")
    task_ids = pipeline.create_tasks_from_topics(topics, brand_info)
    print(f"已创建 {len(task_ids)} 个任务")
    
    # 处理所有任务
    print("\n🚀 开始处理任务...")
    results = pipeline.process_all_tasks(brand_info)
    
    # 显示结果
    print("\n📊 处理结果:")
    for result in results:
        if result['success']:
            print(f"  ✓ {result['task_id']}: 质量得分 {result['quality_score']:.1f}")
        else:
            print(f"  ✗ {result['task_id']}: {result.get('error', 'Unknown error')}")
    
    # 显示流水线状态
    print("\n📈 流水线状态:")
    status = pipeline.get_pipeline_status()
    print(f"  总任务: {status['total']}")
    print(f"  已完成: {status['completed']}")
    print(f"  失败: {status['failed']}")
    print(f"  完成率: {status['completion_rate']:.1f}%")
    print(f"  平均质量得分: {status['average_quality_score']:.1f}")
    
    # 导出结果
    print("\n💾 导出结果...")
    output_dir = pipeline.export_results('pipeline_output')
    print(f"结果已导出到: {output_dir}/")
    
    return pipeline


if __name__ == '__main__':
    demo_pipeline()
