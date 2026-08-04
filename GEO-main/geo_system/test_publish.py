#!/usr/bin/env python3
"""
测试5平台发布功能
"""

import requests
import json
import time


def get_token():
    resp = requests.post(
        'http://localhost:5001/api/auth/login',
        json={'username': 'jlz', 'password': 'jlz123456'},
        timeout=30
    )
    data = resp.json()
    return data.get('access_token')


def test_platform_publish(token, platform, title, content):
    print(f"\n{'='*60}")
    print(f"测试发布到 {platform}")
    print(f"{'='*60}")
    
    start = time.time()
    try:
        resp = requests.post(
            f'http://localhost:5001/api/platform-accounts/{platform}/publish',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            },
            json={'title': title, 'content': content},
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
        
        return data.get('success', False)
    except requests.exceptions.Timeout:
        print(f"超时（{elapsed:.2f}秒）")
        return False
    except Exception as e:
        print(f"异常: {e}")
        return False


def main():
    print("=== GEO 5平台发布测试 ===")
    
    print("\n1. 获取认证token...")
    token = get_token()
    if not token:
        print("❌ 登录失败")
        return
    print(f"✅ 获取token成功")
    
    test_title = '家居装修设计技巧分享'
    test_content = '在家居装修中，合理的空间规划和色彩搭配非常重要。今天分享几个实用的装修设计技巧：\n\n1. 空间布局要合理，避免浪费\n2. 色彩搭配要协调，营造舒适氛围\n3. 选择环保材料，保障家人健康\n\n希望这些技巧能帮助你打造理想的家居空间！'
    
    platforms = ['zhihu', 'weibo', 'bilibili', 'douyin']
    results = {}
    
    for platform in platforms:
        success = test_platform_publish(token, platform, test_title, test_content)
        results[platform] = '成功' if success else '失败'
    
    print(f"\n{'='*60}")
    print("测试结果总结:")
    print(f"{'='*60}")
    for platform, result in results.items():
        color = '\033[92m' if result == '成功' else '\033[91m'
        print(f"  {color}{platform}: {result}\033[0m")


if __name__ == '__main__':
    main()
