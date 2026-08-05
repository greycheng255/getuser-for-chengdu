"""
GEO系统命令行工具

Usage:
    geo generate --title "文章标题" --brand "品牌名"
    geo analyze --file content.md
    geo optimize --file content.md --output optimized.md
    geo metrics --record daily_metrics.json
    geo report --type monthly
    geo server --port 8000
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import click
import json
from datetime import datetime
from pathlib import Path

from core.content_generator import GEOArticleGenerator
from core.content_optimizer import GEOContentOptimizer
from utils.content_analyzer import ContentAnalyzer
from modules.data.metrics_tracker import GEOMetricsTracker, GEOMetrics
from modules.data.roi_calculator import ROICalculator
from modules.source.authority_builder import AuthorityBuilder


@click.group()
@click.version_option(version='1.0.0')
def cli():
    """GEO内容工程系统 - 命令行工具"""
    pass


@cli.command()
@click.option('--title', '-t', required=True, help='文章标题')
@click.option('--brand', '-b', required=True, help='品牌名称')
@click.option('--industry', '-i', default='AI营销', help='所属行业')
@click.option('--expertise', '-e', multiple=True, help='专业领域（可多次使用）')
@click.option('--platform', '-p', default='chatgpt', 
              type=click.Choice(['chatgpt', 'perplexity', 'google_ai', 'kimi', 'doubao']),
              help='目标平台')
@click.option('--word-count', '-w', default=3000, help='目标字数')
@click.option('--output', '-o', help='输出文件路径')
def generate(title, brand, industry, expertise, platform, word_count, output):
    """生成GEO优化文章大纲"""
    click.echo(f"正在生成GEO文章大纲: {title}")
    
    generator = GEOArticleGenerator()
    
    brand_info = {
        'name': brand,
        'industry': industry,
        'expertise': list(expertise) if expertise else ['GEO', 'AI营销']
    }
    
    try:
        result = generator.generate(
            title=title,
            brand_info=brand_info,
            target_platform=platform,
            word_count=word_count
        )
        
        # 显示大纲
        click.echo("\n文章大纲:")
        click.echo("-" * 60)
        for item in result['outline']:
            indent = "  " * (item['level'] - 1)
            click.echo(f"{indent}- {item['title']}")
        
        # 显示提示词长度
        click.echo(f"\n提示词长度: {len(result['prompt'])} 字符")
        
        # 保存到文件
        if output:
            output_data = {
                'title': result['title'],
                'outline': result['outline'],
                'prompt': result['prompt'],
                'brand_info': brand_info,
                'target_platform': platform,
                'generated_at': datetime.now().isoformat()
            }
            
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            click.echo(f"\n已保存到: {output}")
        else:
            # 默认保存
            default_output = f"geo_outline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(default_output, 'w', encoding='utf-8') as f:
                json.dump({
                    'title': result['title'],
                    'outline': result['outline'],
                    'prompt': result['prompt'],
                    'generated_at': datetime.now().isoformat()
                }, f, ensure_ascii=False, indent=2)
            click.echo(f"\n已保存到: {default_output}")
            
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--file', '-f', required=True, help='要分析的内容文件')
@click.option('--output', '-o', help='分析报告输出路径')
def analyze(file, output):
    """分析内容质量"""
    click.echo(f"正在分析内容: {file}")
    
    if not os.path.exists(file):
        click.echo(f"错误: 文件不存在 {file}", err=True)
        sys.exit(1)
    
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    analyzer = ContentAnalyzer()
    
    try:
        result = analyzer.analyze(content)
        
        click.echo("\n分析结果:")
        click.echo("-" * 60)
        click.echo(f"整体得分:     {result.overall_score:.1f}/100")
        click.echo(f"结构得分:     {result.structure_score:.1f}/100")
        click.echo(f"引用得分:     {result.citation_score:.1f}/100")
        click.echo(f"可读性得分:   {result.readability_score:.1f}/100")
        click.echo(f"权威性得分:   {result.authority_score:.1f}/100")
        click.echo(f"GEO合规性:    {result.geo_compliance:.1f}/100")
        
        if result.issues:
            click.echo(f"\n发现的问题 ({len(result.issues)}个):")
            for issue in result.issues[:5]:
                click.echo(f"  - {issue}")
        
        if result.suggestions:
            click.echo(f"\n优化建议 ({len(result.suggestions)}个):")
            for suggestion in result.suggestions[:5]:
                click.echo(f"  - {suggestion}")
        
        # 保存报告
        if output:
            report = {
                'file': file,
                'analysis': {
                    'overall_score': result.overall_score,
                    'structure_score': result.structure_score,
                    'citation_score': result.citation_score,
                    'readability_score': result.readability_score,
                    'authority_score': result.authority_score,
                    'geo_compliance': result.geo_compliance,
                    'issues': result.issues,
                    'suggestions': result.suggestions
                },
                'analyzed_at': datetime.now().isoformat()
            }
            
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            click.echo(f"\n报告已保存到: {output}")
            
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--file', '-f', required=True, help='要优化的内容文件')
@click.option('--level', '-l', default='medium',
              type=click.Choice(['light', 'medium', 'heavy']),
              help='优化级别')
@click.option('--output', '-o', required=True, help='优化后的输出文件')
def optimize(file, level, output):
    """优化内容质量"""
    click.echo(f"正在优化内容: {file}")
    
    if not os.path.exists(file):
        click.echo(f"错误: 文件不存在 {file}", err=True)
        sys.exit(1)
    
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    optimizer = GEOContentOptimizer()
    
    try:
        result = optimizer.optimize(content, optimization_level=level)
        
        click.echo("\n优化结果:")
        click.echo("-" * 60)
        click.echo(f"优化前得分: {result.score_before:.1f}")
        click.echo(f"优化后得分: {result.score_after:.1f}")
        click.echo(f"改进了: {result.score_after - result.score_before:.1f} 分")
        
        if result.improvements:
            click.echo(f"\n改进项 ({len(result.improvements)}个):")
            for improvement in result.improvements[:5]:
                click.echo(f"  - {improvement}")
        
        # 保存优化后的内容
        with open(output, 'w', encoding='utf-8') as f:
            f.write(result.optimized_content)
        click.echo(f"\n优化后的内容已保存到: {output}")
        
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--file', '-f', required=True, help='指标数据JSON文件')
def metrics(file):
    """记录GEO指标"""
    click.echo(f"正在记录指标: {file}")
    
    if not os.path.exists(file):
        click.echo(f"错误: 文件不存在 {file}", err=True)
        sys.exit(1)
    
    with open(file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    tracker = GEOMetricsTracker()
    
    try:
        metrics = GEOMetrics(
            date=datetime.now().isoformat(),
            **data
        )
        
        tracker.record_metrics(metrics)
        click.echo("指标记录成功！")
        
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--type', '-t', 'report_type', default='monthly',
              type=click.Choice(['daily', 'weekly', 'monthly']),
              help='报告类型')
@click.option('--output', '-o', help='报告输出文件')
def report(report_type, output):
    """生成GEO报告"""
    click.echo(f"正在生成{report_type}报告...")
    
    tracker = GEOMetricsTracker()
    
    try:
        report_data = tracker.generate_report(report_type)
        
        click.echo("\n报告概览:")
        click.echo("-" * 60)
        
        basic = report_data['basic_metrics']
        click.echo(f"AI引用率:       {basic['ai_citation_rate']['current']:.1f}")
        click.echo(f"品牌提及率:     {basic['brand_mention_rate']['current']:.1f}")
        click.echo(f"答案空间覆盖:   {basic['answer_space_coverage']['current']:.1%}")
        click.echo(f"综合可见性:     {basic['visibility_score']['current']:.1f}")
        
        quality = report_data['quality_metrics']
        click.echo(f"\n质量指标:")
        click.echo(f"信源多样性:     {quality['source_diversity']['score']:.2f}")
        click.echo(f"内容质量:       {quality['content_quality']['score']:.2f}")
        
        if report_data['recommendations']:
            click.echo(f"\n优化建议 ({len(report_data['recommendations'])}条):")
            for rec in report_data['recommendations'][:3]:
                priority = "高" if rec['priority'] == 'high' else "中" if rec['priority'] == 'medium' else "低"
                click.echo(f"  [{priority}] {rec['suggestion']}")
        
        # 保存报告
        if output:
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)
            click.echo(f"\n报告已保存到: {output}")
        
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--port', '-p', default=8000, help='服务器端口')
@click.option('--host', '-h', default='0.0.0.0', help='服务器主机')
def server(port, host):
    """启动API服务器"""
    click.echo(f"正在启动GEO API服务器...")
    click.echo(f"地址: http://{host}:{port}")
    click.echo(f"文档: http://{host}:{port}/docs")
    
    try:
        import uvicorn
        from api.server import create_app
        
        app = create_app()
        uvicorn.run(app, host=host, port=port)
        
    except ImportError:
        click.echo("错误: 请先安装依赖: pip install fastapi uvicorn", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


@cli.command()
def init():
    """初始化GEO系统"""
    click.echo("正在初始化GEO系统...")
    
    # 创建必要的目录
    dirs = [
        'output',
        'data',
        'templates',
        'logs'
    ]
    
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
        click.echo(f"  创建目录: {dir_name}/")
    
    # 创建示例配置文件
    config_file = 'geo_config.json'
    if not os.path.exists(config_file):
        config = {
            'brand_name': '你的品牌',
            'industry': 'AI营销',
            'expertise': ['GEO', '内容营销'],
            'default_platform': 'chatgpt',
            'api_settings': {
                'openai_api_key': '${OPENAI_API_KEY}',
                'anthropic_api_key': '${ANTHROPIC_API_KEY}'
            }
        }
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        click.echo(f"  创建配置: {config_file}")
    
    click.echo("\n初始化完成！")
    click.echo("\n下一步:")
    click.echo("  1. 编辑 geo_config.json 配置你的品牌信息")
    click.echo("  2. 设置API密钥环境变量")
    click.echo("  3. 运行 'geo generate --title \"你的标题\" --brand \"你的品牌\"' 开始生成内容")


@cli.command()
@click.option('--investment', '-i', default=160000, help='总投资金额')
@click.option('--citation-increase', '-c', default=40, help='AI引用率提升(%)')
@click.option('--conversion-rate', '-r', default=2.5, help='转化率(%)')
@click.option('--customer-value', '-v', default=5000, help='平均客户价值')
def roi(investment, citation_increase, conversion_rate, customer_value):
    """计算GEO投资回报率"""
    click.echo("正在计算GEO ROI...")
    
    calculator = ROICalculator()
    
    params = {
        'content_investment': investment * 0.4,
        'technology_investment': investment * 0.2,
        'personnel_investment': investment * 0.4,
        'ai_citation_increase': citation_increase,
        'brand_mention_increase': citation_increase * 0.875,
        'conversion_rate': conversion_rate,
        'avg_customer_value': customer_value,
        'time_period_months': 12
    }
    
    try:
        result = calculator.calculate_basic_roi(params)
        
        click.echo("\nROI分析结果:")
        click.echo("-" * 60)
        click.echo(f"总投资:         ¥{result['total_investment']:,.0f}")
        click.echo(f"预期收益:       ¥{result['revenue']:,.0f}")
        click.echo(f"净收益:         ¥{result['net_profit']:,.0f}")
        click.echo(f"ROI:            {result['roi_percentage']:.1f}%")
        click.echo(f"投资回收期:     {result['payback_period_months']:.1f}个月")
        click.echo(f"新客户数:       {result['new_customers']:.0f}")
        
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    cli()
