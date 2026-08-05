@echo off
chcp 65001 >nul
echo ============================================
echo 🚀 GEO内容工程系统启动器
echo ============================================
echo.

cd /d "%~dp0"

echo 📦 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python未安装或未添加到PATH
    pause
    exit /b 1
)
echo ✅ Python已安装

echo.
echo 🔧 启动后端API服务...
start "GEO Backend" cmd /k "cd backend && python app.py"

timeout /t 3 /nobreak >nul

echo.
echo 🌐 启动前端服务...
start "GEO Frontend" cmd /k "cd web && python -m http.server 8080"

timeout /t 2 /nobreak >nul

echo.
echo ============================================
echo 🎉 GEO系统启动成功！
echo ============================================
echo.
echo 📍 访问地址:
echo    前端界面: http://localhost:8080
echo    后端API:  http://localhost:5000/api
echo    API文档:  http://localhost:5000/api/health
echo.
echo ⚡ 功能模块:
echo    ✍️  内容生成 - 基于ERE框架生成GEO优化文章
echo    🔍 内容分析 - 评估内容质量和GEO合规性
echo    ⚡ 内容优化 - 自动优化内容结构
echo    📊 数据监测 - 追踪GEO关键指标
echo    💰 ROI计算 - 评估投资回报
echo    🏛️  信源建设 - 构建权威信源体系
echo.
echo 📝 使用说明:
echo    1. 在浏览器中访问 http://localhost:8080
echo    2. 使用各功能模块进行GEO优化
echo    3. 关闭命令窗口停止服务
echo.
echo ============================================
echo.

start http://localhost:8080

echo 按任意键关闭所有服务...
pause >nul

taskkill /FI "WINDOWTITLE eq GEO Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq GEO Frontend*" /F >nul 2>&1

echo.
echo ✅ 服务已关闭
pause
