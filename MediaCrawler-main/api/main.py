# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/main.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

"""
MediaCrawler WebUI API Server
Start command: uvicorn api.main:app --port 8080 --reload
Or: python -m api.main
"""
import asyncio
import os
import sys
import subprocess
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 加载 .env 文件中的环境变量（确保 Cookie 等配置对 Web UI 后端可用）
# 使用统一的 cookie_manager 加载，确保与其他模块一致
from .services.cookie_manager import _ensure_env_loaded
_ensure_env_loaded()
print("[main] Loaded .env via cookie_manager")

from .routers import crawler_router, data_router, websocket_router, customer_lead_router, tasks_router, cookies_router, auth_router, business_router, agent_router, external_api_router, config_router, notifications_router, plan_router, x_twitter_router, x_twitter_workbench_router, x_workbench_crawl_router, x_workbench_templates_router, x_workbench_analytics_router, x_workbench_export_router, x_workbench_notifications_router, x_workbench_auto_mode_router, x_workbench_advanced_router, x_workbench_ws_router, hotpoint_router, opennotebook_integration_router
from .utils.exceptions import register_exception_handlers

# OpenAPI 文档元数据(用于 /docs 和 /redoc 展示)
_TAGS_METADATA = [
    {"name": "auth", "description": "用户认证、登录、Token 管理"},
    {"name": "crawler", "description": "爬虫任务启动、停止、查询"},
    {"name": "cookies", "description": "各平台 Cookie 池管理"},
    {"name": "tasks", "description": "定时任务、计划任务"},
    {"name": "x-twitter-workbench", "description": "X Twitter 工作台:热点推文、视频拆解、评论发送、回复监控"},
    {"name": "x-workbench-crawl", "description": "工作台热点采集(浏览器自动化)"},
    {"name": "hotpoint", "description": "热点聚合(多平台热榜)"},
    {"name": "customer-lead", "description": "客户线索管理"},
    {"name": "business", "description": "业务数据、仪表盘"},
    {"name": "notifications", "description": "通知中心"},
    {"name": "plan", "description": "套餐订阅、计费"},
    {"name": "config", "description": "系统配置查询"},
    {"name": "external-api", "description": "对外开放 API(供第三方接入)"},
]

app = FastAPI(
    title="MediaCrawler WebUI API",
    description="""
**MediaCrawler WebUI 后端 API**

提供爬虫任务管理、X Twitter 自动评论工作台、客户线索管理等功能。

## 认证方式
所有需要授权的接口请在请求头携带:
```
Authorization: Bearer <JWT_TOKEN>
```
Token 通过 `POST /api/auth/login` 获取(默认账号 admin/admin123)。

## 错误响应格式
所有错误返回统一结构:
```json
{"code": 4040, "message": "推文不存在", "data": null, "request_id": "abc12345"}
```
常见业务码:`0=成功` `4000=参数错误` `4010=未认证` `4030=无权限` `4040=不存在` `4090=冲突` `4220=校验失败` `4290=限流` `5000=服务器错误` `5020=外部服务错误`
""",
    version="1.1.0",
    openapi_tags=_TAGS_METADATA,
    docs_url="/docs",
    redoc_url="/redoc",
)

# 注册全局异常处理器(统一错误响应格式)
register_exception_handlers(app)

# 初始化数据库表
@app.on_event("startup")
async def startup_event():
    """应用启动时创建数据库表"""
    try:
        from database.db_session import create_tables
        import config
        await create_tables(config.SAVE_DATA_OPTION)
        print(f"[startup] Database tables created/verified for: {config.SAVE_DATA_OPTION}")
    except Exception as e:
        print(f"[startup] Database initialization warning: {e}")

    # 自动注册到碳硅交易平台（如果配置了平台地址）
    platform_url = os.environ.get("CARBON_SILICON_PLATFORM_URL", "")
    if platform_url:
        try:
            from .services.agent_client import register_to_platform, start_heartbeat
            base_url = os.environ.get("AGENT_BASE_URL", "http://localhost:35092")
            await register_to_platform(base_url)
            await start_heartbeat()
            print(f"[startup] Auto-registered to Carbon-Silicon platform: {platform_url}")
        except Exception as e:
            print(f"[startup] Auto-registration to platform failed (non-fatal): {e}")
    else:
        print("[startup] CARBON_SILICON_PLATFORM_URL not set, skipping auto-registration")

    # 初始化默认管理员账号
    try:
        from .services.auth import ensure_default_admin
        await ensure_default_admin()
    except Exception as e:
        print(f"[startup] ensure_default_admin failed (non-fatal): {e}")

    # 启动时自动从 Cookie 池加载到 account_pool（内存），避免重启后账号池监控为空
    try:
        from .services.account_pool import get_account_pool, _detect_network_interfaces, get_available_interfaces
        from .services.cookie_manager import get_cookie_pool
        await _detect_network_interfaces()
        for platform in ("dy", "xhs", "ks", "bili", "wb"):
            cookie_list = get_cookie_pool(platform)
            if not cookie_list:
                continue
            pool = get_account_pool(platform)
            pool.accounts.clear()
            pool.current_account = None
            for i, cookie_str in enumerate(cookie_list):
                await pool.add_account(cookie=cookie_str, cookie_alias=f"账号{i+1}")
            print(f"[startup] Loaded {len(pool.accounts)} accounts into {platform} account_pool")
    except Exception as e:
        print(f"[startup] Auto-load account_pool failed (non-fatal): {e}")

    # 启动任务调度器(daily/weekly 支持)
    try:
        from api.services.task_scheduler import start_scheduler
        await start_scheduler()
    except Exception as e:
        print(f"[startup] Task scheduler start failed (non-fatal): {e}")

    # 自动启动 X Twitter 评论回复监控服务(保证监控始终运行)
    # 内置 watchdog:任务异常退出会自动重启,除非用户显式 stop
    try:
        from api.services.comment_reply_monitor import start_monitor, is_monitor_running
        if not is_monitor_running():
            ok = await start_monitor()
            if ok:
                print("[startup] X Twitter 评论回复监控已自动启动(带 watchdog 自动重启)")
            else:
                print("[startup] X Twitter 评论回复监控自动启动失败(non-fatal)")
        else:
            print("[startup] X Twitter 评论回复监控已在运行,跳过自动启动")
    except Exception as e:
        print(f"[startup] Auto-start comment_reply_monitor failed (non-fatal): {e}")

# Get webui static files directory
WEBUI_DIR = os.path.join(os.path.dirname(__file__), "webui")

# CORS configuration - allow frontend dev server access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Backup port
        "http://localhost:35174",  # Frontend dev server
        "http://localhost:35175",  # Frontend fallback port
        "http://localhost:35176",  # Frontend fallback port 2
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:35174",
        "http://127.0.0.1:35175",
        "http://127.0.0.1:35176",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(crawler_router, prefix="/api")
app.include_router(data_router, prefix="/api")
app.include_router(websocket_router, prefix="/api")
app.include_router(customer_lead_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(cookies_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(business_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(external_api_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(plan_router, prefix="/api")
app.include_router(x_twitter_router, prefix="/api")
app.include_router(x_twitter_workbench_router, prefix="/api")
app.include_router(x_workbench_crawl_router, prefix="/api")
app.include_router(x_workbench_templates_router, prefix="/api")
app.include_router(x_workbench_analytics_router, prefix="/api")
app.include_router(x_workbench_export_router, prefix="/api")
app.include_router(x_workbench_notifications_router, prefix="/api")
app.include_router(x_workbench_auto_mode_router, prefix="/api")
app.include_router(x_workbench_advanced_router, prefix="/api")
app.include_router(x_workbench_ws_router, prefix="/api")
app.include_router(hotpoint_router, prefix="/api")
app.include_router(opennotebook_integration_router, prefix="/api")

# 添加 /api/dashboard 别名（从数据库获取数据）
@app.get("/api/dashboard")
async def dashboard_alias():
    """Dashboard数据聚合 - 使用真实数据库数据"""
    from datetime import datetime, timedelta
    from sqlalchemy import select, func, and_
    from database.db_session import get_async_engine
    from database.models import CrawlerTaskModel, CustomerLead
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    import config

    engine = get_async_engine(config.SAVE_DATA_OPTION)
    total_leads = 0
    today_new = 0
    pending_count = 0
    converted_count = 0
    recent_leads = []
    trends = []

    today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

    if engine:
        try:
            AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            session = AsyncSessionFactory()

            # 总线索数
            result = await session.execute(select(func.count()).select_from(CustomerLead))
            total_leads = result.scalar() or 0

            # 今日新线索
            result = await session.execute(
                select(func.count()).select_from(CustomerLead).where(CustomerLead.add_ts >= today_start)
            )
            today_new = result.scalar() or 0

            # 待处理线索（状态为new）
            result = await session.execute(
                select(func.count()).select_from(CustomerLead).where(CustomerLead.status == "new")
            )
            pending_count = result.scalar() or 0

            # 已转化线索
            result = await session.execute(
                select(func.count()).select_from(CustomerLead).where(CustomerLead.status == "converted")
            )
            converted_count = result.scalar() or 0

            # 最近5条线索
            result = await session.execute(
                select(CustomerLead).order_by(CustomerLead.add_ts.desc()).limit(5)
            )
            leads = result.scalars().all()
            recent_leads = [
                {
                    "id": l.id,
                    "nickname": l.nickname or "未知用户",
                    "platform": l.platform or "dy",
                    "content": l.content or "",
                    "lead_score": l.lead_score or 0,
                    "intent_type": l.intent_type or "inquiry",
                    "add_ts": l.add_ts or 0,
                    "status": l.status or "new",
                }
                for l in leads
            ]

            # 近7天趋势（按天统计线索数）
            for i in range(6, -1, -1):
                day = datetime.now() - timedelta(days=i)
                day_start = int(day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
                day_end = int((day + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
                result = await session.execute(
                    select(func.count()).select_from(CustomerLead).where(
                        and_(CustomerLead.add_ts >= day_start, CustomerLead.add_ts < day_end)
                    )
                )
                count = result.scalar() or 0
                trends.append({"date": day.strftime("%Y-%m-%d"), "leads": count})

            await session.close()
        except Exception as e:
            print(f"[dashboard] Database query error: {e}")

    # 如果没有趋势数据，填充空数据
    if not trends:
        for i in range(6, -1, -1):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            trends.append({"date": date, "leads": 0})

    # 计算转化率
    conversion_rate = round((converted_count / total_leads * 100), 1) if total_leads > 0 else 0.0

    return {
        "summary": {
            "today_new": today_new,
            "total_leads": total_leads,
            "pending_count": pending_count,
            "converted_count": converted_count,
            "conversion_rate": conversion_rate,
        },
        "trends": trends,
        "recent_leads": recent_leads,
    }


@app.get("/")
async def serve_frontend():
    """Return frontend page"""
    index_path = os.path.join(WEBUI_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": "MediaCrawler WebUI API",
        "version": "1.0.0",
        "docs": "/docs",
        "note": "WebUI not found, please build it first: cd webui && npm run build"
    }


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# ==================== Prometheus 指标端点 ====================
try:
    from prometheus_client import (
        generate_latest, Counter, Gauge, Histogram,
        CONTENT_TYPE_LATEST, CollectorRegistry, REGISTRY
    )
    # 业务指标定义
    LEADS_TOTAL = Counter("mediacrawler_leads_total", "Total leads captured", ["platform", "level"])
    TASKS_RUNNING = Gauge("mediacrawler_task_running", "Currently running tasks")
    TASK_DURATION = Histogram("mediacrawler_task_duration_seconds", "Task execution duration")
    ACCOUNT_POOL_AVAILABLE = Gauge("mediacrawler_account_pool_available", "Available accounts in pool", ["platform"])
    API_REQUESTS = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])

    @app.get("/metrics")
    async def metrics():
        """Prometheus 指标暴露端点"""
        return generate_latest(REGISTRY), {"Content-Type": CONTENT_TYPE_LATEST}

    print("[main] Prometheus metrics endpoint enabled at /metrics")
except ImportError:
    print("[main] prometheus_client not installed, /metrics endpoint disabled")
    LEADS_TOTAL = None
    TASKS_RUNNING = None
    TASK_DURATION = None
    ACCOUNT_POOL_AVAILABLE = None
    API_REQUESTS = None


@app.get("/api/analytics/trends")
async def get_analytics_trends(days: int = 30):
    """获取趋势数据 - 按天统计线索数"""
    from datetime import datetime, timedelta
    from sqlalchemy import select, func, and_
    from database.db_session import get_async_engine
    from database.models import CustomerLead
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    import config

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    trends = []
    engine = get_async_engine(config.SAVE_DATA_OPTION)

    if engine:
        try:
            AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            session = AsyncSessionFactory()
            for i in range(days - 1, -1, -1):
                date = today - timedelta(days=i)
                date_ts = int(date.timestamp() * 1000)
                next_date_ts = int((date + timedelta(days=1)).timestamp() * 1000)
                result = await session.execute(
                    select(func.count()).select_from(CustomerLead)
                    .where(CustomerLead.add_ts >= date_ts)
                    .where(CustomerLead.add_ts < next_date_ts)
                )
                leads_count = result.scalar() or 0
                trends.append({"date": date.strftime("%m-%d"), "leads": leads_count})
            await session.close()
        except Exception as e:
            print(f"[analytics/trends] error: {e}")

    if not trends:
        for i in range(days - 1, -1, -1):
            date = (today - timedelta(days=i)).strftime("%m-%d")
            trends.append({"date": date, "leads": 0})

    return {"trends": trends}


@app.get("/api/analytics/platform")
async def get_platform_analytics():
    """获取平台分析数据 - 平台分布 + 平均评分"""
    from sqlalchemy import select, func
    from database.db_session import get_async_engine
    from database.models import CustomerLead
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    import config

    engine = get_async_engine(config.SAVE_DATA_OPTION)
    platform_data = []
    avg_scores = {}

    if engine:
        try:
            AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            session = AsyncSessionFactory()
            # 平台分布
            result = await session.execute(
                select(CustomerLead.platform, func.count()).group_by(CustomerLead.platform)
            )
            platform_data = [
                {"platform": row[0] or "unknown", "count": row[1]}
                for row in result.all()
            ]
            # 平台平均评分
            result = await session.execute(
                select(CustomerLead.platform, func.avg(CustomerLead.lead_score))
                .group_by(CustomerLead.platform)
            )
            avg_scores = {row[0] or "unknown": round(float(row[1] or 0), 1) for row in result.all()}
            await session.close()
        except Exception as e:
            print(f"[analytics/platform] error: {e}")

    return {"platform_distribution": platform_data, "avg_scores": avg_scores}


@app.get("/api/analytics/funnel")
async def get_funnel_data():
    """获取转化漏斗数据 - 按状态统计"""
    from sqlalchemy import select, func
    from database.db_session import get_async_engine
    from database.models import CustomerLead
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    import config

    engine = get_async_engine(config.SAVE_DATA_OPTION)
    funnel = []
    statuses = ["new", "contacted", "qualified", "converted"]

    if engine:
        try:
            AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            session = AsyncSessionFactory()
            for status in statuses:
                result = await session.execute(
                    select(func.count()).select_from(CustomerLead).where(CustomerLead.status == status)
                )
                count = result.scalar() or 0
                funnel.append({"status": status, "count": count})
            await session.close()
        except Exception as e:
            print(f"[analytics/funnel] error: {e}")

    if not funnel:
        funnel = [{"status": s, "count": 0} for s in statuses]

    return {"funnel": funnel}


@app.get("/api/env/check")
async def check_environment():
    """Check if MediaCrawler environment is configured correctly"""
    try:
        # Run uv run main.py --help command to check environment
        if sys.platform == "win32":
            loop = asyncio.get_running_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["uv", "run", "main.py", "--help"],
                    capture_output=True,
                    timeout=30.0,
                    cwd="."
                )
            )
            stdout, stderr = process.stdout, process.stderr  # bytes
        else:
            process = await asyncio.create_subprocess_exec(
                "uv", "run", "main.py", "--help",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd="."  # Project root directory
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30.0  # 30 seconds timeout
            )
        if process.returncode == 0:
            return {
                "success": True,
                "message": "MediaCrawler environment configured correctly",
                "output": stdout.decode("utf-8", errors="ignore")[:500]  # Truncate to first 500 characters
            }
        else:
            error_msg = stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")
            return {
                "success": False,
                "message": "Environment check failed",
                "error": error_msg[:500]
            }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": "Environment check timeout",
            "error": "Command execution exceeded 30 seconds"
        }
    except FileNotFoundError:
        return {
            "success": False,
            "message": "uv command not found",
            "error": "Please ensure uv is installed and configured in system PATH"
        }
    except Exception as e:
        return {
            "success": False,
            "message": "Environment check error",
            "error": f"{type(e).__name__}: {str(e) or 'Unknown'}"
        }


@app.get("/api/config/platforms")
async def get_platforms():
    """Get list of supported platforms"""
    return {
        "platforms": [
            {"value": "xhs", "label": "Xiaohongshu", "icon": "book-open"},
            {"value": "dy", "label": "Douyin", "icon": "music"},
            {"value": "ks", "label": "Kuaishou", "icon": "video"},
            {"value": "bili", "label": "Bilibili", "icon": "tv"},
            {"value": "wb", "label": "Weibo", "icon": "message-circle"},
            {"value": "tieba", "label": "Baidu Tieba", "icon": "messages-square"},
            {"value": "zhihu", "label": "Zhihu", "icon": "help-circle"},
        ]
    }


@app.get("/api/config/options")
async def get_config_options():
    """Get all configuration options"""
    return {
        "login_types": [
            {"value": "qrcode", "label": "QR Code Login"},
            {"value": "cookie", "label": "Cookie Login"},
        ],
        "crawler_types": [
            {"value": "search", "label": "Search Mode"},
            {"value": "detail", "label": "Detail Mode"},
            {"value": "creator", "label": "Creator Mode"},
        ],
        "save_options": [
            {"value": "jsonl", "label": "JSONL File"},
            {"value": "json", "label": "JSON File"},
            {"value": "csv", "label": "CSV File"},
            {"value": "excel", "label": "Excel File"},
            {"value": "sqlite", "label": "SQLite Database"},
            {"value": "db", "label": "MySQL Database"},
            {"value": "mongodb", "label": "MongoDB Database"},
        ],
    }


# Mount static resources - must be placed after all routes
if os.path.exists(WEBUI_DIR):
    assets_dir = os.path.join(WEBUI_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    # Mount logos directory
    logos_dir = os.path.join(WEBUI_DIR, "logos")
    if os.path.exists(logos_dir):
        app.mount("/logos", StaticFiles(directory=logos_dir), name="logos")
    # Mount other static files (e.g., vite.svg)
    app.mount("/static", StaticFiles(directory=WEBUI_DIR), name="webui-static")

# Mount outreach screenshots directory
screenshots_dir = os.path.join(os.getcwd(), "data", "outreach_screenshots")
if os.path.exists(screenshots_dir):
    app.mount("/api/screenshots", StaticFiles(directory=screenshots_dir), name="screenshots")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=35092)


# SPA catch-all route — must be after all API routes and static mounts
# Returns index.html for any frontend route (e.g., /tasks, /leads, /dashboard)
@app.get("/{path:path}")
async def serve_spa(path: str):
    """Catch-all route for SPA — return index.html for any non-API, non-static path"""
    from fastapi.responses import JSONResponse
    # Skip API routes and static assets
    if path.startswith("api/") or path.startswith("assets/") or path.startswith("static/") or path.startswith("docs") or "." in path.split("/")[-1]:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    index_path = os.path.join(WEBUI_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})
