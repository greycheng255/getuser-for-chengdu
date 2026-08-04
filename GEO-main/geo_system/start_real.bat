@echo off
chcp 65001 >nul
echo ============================================
echo 🚀 GEO内容工程系统启动器（真实数据版）
echo ============================================
echo.

cd /d "%~dp0"

echo 📦 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python未安装或未添加到PATH
    echo 请访问 https://www.python.org/downloads/ 下载安装Python 3.8+
    pause
    exit /b 1
)
echo ✅ Python已安装

echo.
echo 📦 检查依赖...
cd backend
python -c "import flask, flask_cors, flask_jwt_extended" >nul 2>&1
if errorlevel 1 (
    echo 📥 正在安装依赖...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ❌ 依赖安装失败
        pause
        exit /b 1
    )
)
echo ✅ 依赖检查完成
cd ..

echo.
echo 🗄️ 初始化数据库...
cd backend
python -c "from database import db; print('✅ 数据库初始化完成')" >nul 2>&1
if errorlevel 1 (
    echo ⚠️ 数据库初始化可能需要首次运行时完成
cd ..

echo.
echo 🔧 启动后端API服务...
start "GEO Backend" cmd /k "cd backend && python app_real.py"

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
echo    前端界面: http://localhost:8080/index_real.html
echo    后端API:  http://localhost:5000/api
echo    API文档:  http://localhost:5000/api/health
echo.
echo 💾 数据库: SQLite (backend/geo_system.db)
echo 🔐 用户认证: 已启用
echo.
start http://localhost:8080/index_real.html

echo 按任意键关闭所有服务...
pause >nul

taskkill /FI "WINDOWTITLE eq GEO Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq GEO Frontend*" /F >nul 2>&1

echo.
echo ✅ 服务已关闭
pause
