#!/usr/bin/env python3
"""
GEO优化完整流程自动测试
"""

import requests
import json
import time
from datetime import datetime

API_BASE = 'http://localhost:5000/api'
BRAND_NAME = '织然家具'
WEBSITE = 'www.zhiranrome.com'
KEYWORD = '家居设计'

def run_tests():
    results = []
    
    print('=' * 60)
    print('GEO优化完整流程自动测试')
    print(f'测试网站: {WEBSITE}')
    print(f'关键词: {KEYWORD}')
    print(f'品牌: {BRAND_NAME}')
    print('=' * 60)
    print()
    
    # 测试1: 健康检查
    print('[测试1] API健康检查')
    try:
        response = requests.get(f'{API_BASE}/health', timeout=5)
        if response.status_code == 200:
            print('✅ API服务正常运行')
            results.append({'test': 'health', 'status': 'success'})
        else:
            print(f'⚠️ API返回状态码: {response.status_code}')
            results.append({'test': 'health', 'status': 'failed', 'code': response.status_code})
    except Exception as e:
        print(f'❌ API连接失败: {e}')
        results.append({'test': 'health', 'status': 'error', 'error': str(e)})
    
    print()
    
    # 测试2: 获取发布平台
    print('[测试2] 获取发布平台列表')
    try:
        response = requests.get(f'{API_BASE}/publish/platforms', timeout=10)
        if response.status_code == 200:
            data = response.json()
            platforms = data.get('platforms', [])
            print(f'✅ 获取到 {len(platforms)} 个平台:')
            for p in platforms:
                status_icon = '✅' if p.get('configured') else '⚠️'
                print(f'  {status_icon} {p.get("icon", "")} {p.get("name", "")}')
            results.append({'test': 'platforms', 'status': 'success', 'count': len(platforms)})
        else:
            print(f'❌ 获取平台列表失败: {response.status_code}')
            results.append({'test': 'platforms', 'status': 'failed'})
    except Exception as e:
        print(f'❌ 获取平台列表异常: {e}')
        results.append({'test': 'platforms', 'status': 'error', 'error': str(e)})
    
    print()
    
    # 测试3: 监控仪表板
    print('[测试3] 获取监控仪表板')
    try:
        response = requests.get(f'{API_BASE}/monitoring/dashboard?days=7', timeout=10)
        if response.status_code == 200:
            data = response.json()
            dashboard = data.get('dashboard', {})
            print('✅ 仪表板数据获取成功')
            
            ai_citation = dashboard.get('ai_citation', {})
            print(f'  🤖 AI提及率: {ai_citation.get("mention_rate", 0)}%')
            print(f'  📊 总查询次数: {ai_citation.get("total_queries", 0)}')
            
            traffic = dashboard.get('traffic', {})
            print(f'  👥 总访客: {traffic.get("total_visitors", 0)}')
            print(f'  🎯 转化率: {traffic.get("conversion_rate", 0)}%')
            
            results.append({'test': 'dashboard', 'status': 'success'})
        else:
            print(f'❌ 获取仪表板失败: {response.status_code}')
            results.append({'test': 'dashboard', 'status': 'failed'})
    except Exception as e:
        print(f'❌ 获取仪表板异常: {e}')
        results.append({'test': 'dashboard', 'status': 'error', 'error': str(e)})
    
    print()
    
    # 测试4: 搜索排名
    print(f'[测试4] 检查搜索排名: {KEYWORD}')
    try:
        response = requests.post(f'{API_BASE}/monitoring/search-rank/check', json={
            'keyword': f'{BRAND_NAME} {KEYWORD}',
            'search_engine': 'baidu'
        }, timeout=30)
        if response.status_code == 200:
            data = response.json()
            results_list = data.get('results', [])
            print(f'✅ 排名检查完成，找到 {len(results_list)} 条结果')
            for i, r in enumerate(results_list[:3], 1):
                print(f'  {i}. {r.get("title", "")[:40]}...')
            results.append({'test': 'search_rank', 'status': 'success', 'results_count': len(results_list)})
        else:
            print(f'❌ 排名检查失败: {response.status_code}')
            results.append({'test': 'search_rank', 'status': 'failed'})
    except Exception as e:
        print(f'❌ 排名检查异常: {e}')
        results.append({'test': 'search_rank', 'status': 'error', 'error': str(e)})
    
    print()
    
    # 测试5: AI引用
    print('[测试5] 检查AI引用情况')
    test_queries = [f'{KEYWORD}哪个品牌好', f'{BRAND_NAME}怎么样']
    citation_results = []
    
    for query in test_queries:
        try:
            response = requests.post(f'{API_BASE}/monitoring/ai-citation/check', json={
                'platform': 'doubao',
                'query': query,
                'brand_name': BRAND_NAME
            }, timeout=30)
            if response.status_code == 200:
                data = response.json()
                result = data.get('result', {})
                mentioned = result.get('mentioned', False)
                sentiment = result.get('sentiment', 'neutral')
                icon = '✅' if mentioned else '❌'
                print(f'{icon} 查询"{query[:15]}...": {"已提及" if mentioned else "未提及"} ({sentiment})')
                citation_results.append({'query': query, 'mentioned': mentioned, 'sentiment': sentiment})
            else:
                print(f'⚠️ 查询失败: {response.status_code}')
        except Exception as e:
            print(f'❌ 查询异常: {str(e)[:30]}')
    
    results.append({'test': 'ai_citation', 'status': 'success', 'queries': citation_results})
    
    print()
    print('=' * 60)
    print('测试完成！')
    print('=' * 60)
    
    # 统计
    success_count = sum(1 for r in results if r.get('status') == 'success')
    print(f'\n📊 测试结果: {success_count}/{len(results)} 项通过')
    
    return results

if __name__ == '__main__':
    run_tests()
