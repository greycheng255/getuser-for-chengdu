#!/usr/bin/env python3
"""
测试5平台发布功能
"""

import sys
sys.path.insert(0, '/app/backend')

import requests
import json
import time


def get_token():
    """获取 admin token"""
    resp = requests.post(
        'http://localhost:5000/api/auth/login',
        json={'username': 'jlz', 'password': 'jlz123456'},
        timeout=10
    )
    data = resp.json()
    return data.get('access_token')


def get_platforms(token):
    """获取平台列表"""
    resp = requests.get(
        'http://localhost:5000/api/platform-accounts',
        headers={'Authorization': f'Bearer {token}'},
        timeout=10
    )
    return resp.json()


def get_ai_tasks(token):
    """获取已完成的AI任务"""
    resp = requests.get(
        'http://localhost:5000/api/ai-tasks',
        headers={'Authorization': f'Bearer {token}'},
        timeout=10
    )
    data = resp.json()
    return [t for t in data.get('data', []) if t.get('status') == 'completed']


def publish_to_platform(token, platform, task_id=None, title=None, content=None):
    """发布到指定平台"""
    print(f"\n{'='*60}")
    print(f"测试发布到 {platform} (task_id={task_id})")
    print(f"{'='*60}")
    
    start = time.time()
    try:
        payload = {}
        if task_id:
            payload['task_id'] = task_id
        else:
            payload['title'] = title or '测试标题'
            payload['content'] = content or '测试内容'
        
        resp = requests.post(
            f'http://localhost:5000/api/platform-accounts/{platform}/publish',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            },
            json=payload,
            timeout=300
        )
        elapsed = time.time() - start
        data = resp.json()
        
        print(f"HTTP状态: {resp.status_code}")
        print(f"耗时: {elapsed:.2f}秒")
        print(f"结果: {'成功' if data.get('success') else '失败'}")
        if data.get('message'):
            print(f"消息: {data['message']}")
        if data.get('error'):
            print(f"错误: {data['error']}")
        if data.get('debug_info'):
            print(f"调试信息: {data['debug_info']}")
        if data.get('url'):
            print(f"发布链接: {data['url']}")
        
        return data.get('success', False)
    except requests.exceptions.Timeout:
        print(f"超时（{elapsed:.2f}秒）")
        return False
    except Exception as e:
        print(f"异常: {e}")
        return False


def main():
    print("=== GEO 5平台发布测试 ===")
    
    # 1. 获取token
    print("\n1. 获取认证token...")
    token = get_token()
    if not token:
        print("❌ 登录失败")
        return
    print(f"✅ 获取token成功: {token[:20]}...")
    
    # 2. 获取平台状态
    print("\n2. 获取平台账号状态...")
    platforms_data = get_platforms(token)
    platforms = platforms_data.get('data', [])
    print(f"共 {len(platforms)} 个平台:")
    for p in platforms:
        status = p.get('status', {})
        account = p.get('account', {}) or {}
        configured = status.get('configured', False)
        account_status = status.get('account_status', '未知')
        cookie_count = status.get('cookie_count', 0)
        account_name = account.get('account_name', '未命名')
        icon = '✅' if configured else '❌'
        print(f"  {icon} {p['id']}: {p['name']} - 状态:{account_status}, Cookie数:{cookie_count}, 账号:{account_name}")
    
    # 3. 测试各平台发布API（使用直接标题+内容方式）
    print("\n3. 开始测试各平台发布API...")
    print("⚠️ 注意：如果平台未配置账号，预期会返回'未配置'错误")
    
    platforms_to_test = ['zhihu', 'weibo', 'bilibili', 'douyin']
    
    # 测试内容
    test_title = '家居装修设计技巧分享'
    test_content = '在家居装修中，合理的空间规划和色彩搭配非常重要。今天分享几个实用的装修设计技巧：\n\n1. 空间布局要合理，避免浪费\n2. 色彩搭配要协调，营造舒适氛围\n3. 选择环保材料，保障家人健康\n\n希望这些技巧能帮助你打造理想的家居空间！'
    
    results = {}
    for platform in platforms_to_test:
        # 检查平台是否已配置
        p_info = next((p for p in platforms if p['id'] == platform), None)
        if p_info and not p_info.get('status', {}).get('configured', False):
            print(f"\n⚠️ {platform} 未配置账号，测试API响应...")
        
        success = publish_to_platform(token, platform, title=test_title, content=test_content)
        results[platform] = '成功' if success else '失败'
    
    # 4. 总结
    print(f"\n{'='*60}")
    print("测试结果总结:")
    print(f"{'='*60}")
    for platform, result in results.items():
        color = '\033[92m' if result == '成功' else '\033[91m'
        print(f"  {color}{platform}: {result}\033[0m")
    
    # 5. 检查日志
    print("\n5. 检查后端日志...")
    print("请手动查看后端日志了解详细错误信息")


if __name__ == '__main__':
    main()
