#!/usr/bin/env python3
"""
GEO系统启动脚本
一键启动后端API服务和前端页面
"""

import os
import sys
import subprocess
import webbrowser
import time
import signal
from pathlib import Path

# 配置
BACKEND_PORT = 5000
FRONTEND_PORT = 8080
BACKEND_DIR = Path(__file__).parent / "backend"
FRONTEND_DIR = Path(__file__).parent / "web"

# 全局进程
backend_process = None
frontend_process = None


def print_banner():
    """打印启动横幅"""
    print("=" * 60)
    print("🚀 GEO内容工程系统启动器")
    print("=" * 60)
    print()


def check_dependencies():
    """检查依赖"""
    print("📦 检查依赖...")
    
    required_packages = [
        'flask',
        'flask-cors',
        'flask-jwt-extended',
        'werkzeug',
        'pyyaml'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing.append(package)
    
    if missing:
        print(f"⚠️  缺少依赖: {', '.join(missing)}")
        print("📥 正在安装...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing)
            print("✅ 依赖安装完成")
        except Exception as e:
            print(f"❌ 安装失败: {e}")
            return False
    else:
        print("✅ 所有依赖已安装")
    
    print()
    return True


def start_backend():
    """启动后端服务"""
    global backend_process
    
    print(f"🔧 启动后端API服务 (端口: {BACKEND_PORT})...")
    
    backend_script = BACKEND_DIR / "app.py"
    
    if not backend_script.exists():
        print(f"❌ 后端脚本不存在: {backend_script}")
        return False
    
    try:
        # 使用Python启动后端
        backend_process = subprocess.Popen(
            [sys.executable, str(backend_script)],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        
        # 等待服务启动
        time.sleep(2)
        
        if backend_process.poll() is None:
            print(f"✅ 后端服务已启动: http://localhost:{BACKEND_PORT}/api")
            print(f"   健康检查: http://localhost:{BACKEND_PORT}/api/health")
            return True
        else:
            stdout, stderr = backend_process.communicate()
            print(f"❌ 后端启动失败")
            print(f"错误: {stderr.decode('utf-8', errors='ignore')}")
            return False
            
    except Exception as e:
        print(f"❌ 启动后端失败: {e}")
        return False


def start_frontend():
    """启动前端服务"""
    global frontend_process
    
    print(f"🌐 启动前端页面...")
    
    index_file = FRONTEND_DIR / "index.html"
    
    if not index_file.exists():
        print(f"❌ 前端页面不存在: {index_file}")
        return False
    
    try:
        # 使用Python的http.server启动前端
        frontend_process = subprocess.Popen(
            [sys.executable, '-m', 'http.server', str(FRONTEND_PORT)],
            cwd=str(FRONTEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        
        # 等待服务启动
        time.sleep(1)
        
        if frontend_process.poll() is None:
            url = f"http://localhost:{FRONTEND_PORT}"
            print(f"✅ 前端页面已启动: {url}")
            
            # 自动打开浏览器
            print("🌐 正在打开浏览器...")
            webbrowser.open(url)
            
            return True
        else:
            stdout, stderr = frontend_process.communicate()
            print(f"❌ 前端启动失败")
            print(f"错误: {stderr.decode('utf-8', errors='ignore')}")
            return False
            
    except Exception as e:
        print(f"❌ 启动前端失败: {e}")
        return False


def signal_handler(sig, frame):
    """信号处理"""
    print("\n\n🛑 正在关闭服务...")
    
    if backend_process:
        print("🔧 关闭后端服务...")
        if os.name == 'nt':
            backend_process.terminate()
        else:
            backend_process.send_signal(signal.SIGTERM)
    
    if frontend_process:
        print("🌐 关闭前端服务...")
        if os.name == 'nt':
            frontend_process.terminate()
        else:
            frontend_process.send_signal(signal.SIGTERM)
    
    print("✅ 服务已关闭")
    sys.exit(0)


def main():
    """主函数"""
    print_banner()
    
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    if os.name != 'nt':
        signal.signal(signal.SIGTERM, signal_handler)
    
    # 检查依赖
    if not check_dependencies():
        print("❌ 依赖检查失败，无法启动")
        return 1
    
    # 启动后端
    if not start_backend():
        print("❌ 后端启动失败")
        return 1
    
    print()
    
    # 启动前端
    if not start_frontend():
        print("❌ 前端启动失败")
        return 1
    
    print()
    print("=" * 60)
    print("🎉 GEO系统启动成功！")
    print("=" * 60)
    print()
    print("📍 访问地址:")
    print(f"   前端界面: http://localhost:{FRONTEND_PORT}")
    print(f"   后端API:  http://localhost:{BACKEND_PORT}/api")
    print(f"   API文档:  http://localhost:{BACKEND_PORT}/api/health")
    print()
    print("⚡ 功能模块:")
    print("   ✍️  内容生成 - 基于ERE框架生成GEO优化文章")
    print("   🔍 内容分析 - 评估内容质量和GEO合规性")
    print("   ⚡ 内容优化 - 自动优化内容结构")
    print("   📊 数据监测 - 追踪GEO关键指标")
    print("   💰 ROI计算 - 评估投资回报")
    print("   🏛️  信源建设 - 构建权威信源体系")
    print()
    print("📝 使用说明:")
    print("   1. 在浏览器中访问前端界面")
    print("   2. 使用各功能模块进行GEO优化")
    print("   3. 按 Ctrl+C 停止服务")
    print()
    print("=" * 60)
    
    # 保持运行
    try:
        while True:
            time.sleep(1)
            
            # 检查进程状态
            if backend_process and backend_process.poll() is not None:
                print("\n⚠️  后端服务已停止")
                break
                
            if frontend_process and frontend_process.poll() is not None:
                print("\n⚠️  前端服务已停止")
                break
                
    except KeyboardInterrupt:
        signal_handler(None, None)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
