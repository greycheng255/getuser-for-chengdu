# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/main.py

# Windows: 使用 SelectorEventLoop 替代 ProactorEventLoop
# ProactorEventLoop 不支持 create_subprocess_exec()，导致 Playwright/CDP 浏览器启动失败
import sys as _sys
if _sys.platform == "win32":
    import asyncio as _asyncio
    _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())
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
import json
import os
import sys
import subprocess
from datetime import datetime, timedelta
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

from .routers import crawler_router, data_router, websocket_router, customer_lead_router, tasks_router, cookies_router, auth_router, business_router, agent_router, external_api_router, config_router, notifications_router, plan_router, x_twitter_router, x_twitter_workbench_router, x_workbench_crawl_router, x_workbench_templates_router, x_workbench_analytics_router, x_workbench_export_router, x_workbench_notifications_router, x_workbench_auto_mode_router, x_workbench_advanced_router, x_workbench_ws_router, x_workbench_auto_pipeline_router, hotpoint_router, opennotebook_integration_router, publish_router, accounts_router, interact_router, moderation_router, scheduling_router, marketing_router, analytics_router, risk_control_router, dm_router, content_router, ai_router, workflow_router, monitoring_router, brand_router, competitor_router, keyword_router, audit_log_router, system_config_router, comment_monitor_router, local_life_router, customer_dispatch_router, ai_customer_service_router, business_profiles_router
# Phase 1-3 新增路由
from .routers.ai_pilot import router as ai_pilot_router
from .routers.task_pool import router as task_pool_router
from .routers.mixcut import router as mixcut_router
from .routers.seo import router as seo_router
from .routers.wechat import router as wechat_router
from .routers.compute import router as compute_router
from .routers.device import router as device_router
from .routers.interaction_analytics import router as interaction_analytics_router
from .routers.auto_pipeline import router as auto_pipeline_router
from .routers.talking_head import router as talking_head_router
# 阶段一 P0 扩展路由
from .routers.alert import router as alert_router
from .routers.stage1_extensions import (
    video_config_router,
    batch_video_router,
    prompt_pipeline_router,
    review_router,
    bot_account_router,
    hotpoint_filter_router,
    hotpoint_category_router,
    hotpoint_alert_router,
    hotpoint_quick_router,
    unified_pipeline_router,
)
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
    """应用启动初始化（优化版：分层并行 + 后台启动，解决启动慢阻塞端口监听问题）。

    Layer 0（await）：create_tables 主表创建，必须先完成（后续 ensure_table 依赖 DB）
    Layer 1（asyncio.gather 并行）：约 25 个 ensure_table DDL 并行执行（原串行 5s+ → 并行 1s 内）
    Layer 2（asyncio.create_task 后台）：监控/调度器/网络注册异步启动，不阻塞端口监听
    """
    import time as _time
    _t0 = _time.time()

    # ===== Layer 0: 主表创建（必须先完成）=====
    try:
        from database.db_session import create_tables
        import config
        await create_tables(config.SAVE_DATA_OPTION)
        print(f"[startup] Database tables created/verified for: {config.SAVE_DATA_OPTION}")
    except Exception as e:
        print(f"[startup] Database initialization warning: {e}")

    # ===== Layer 1: 所有 ensure_table + admin/RBAC seed 并行执行 =====
    async def _safe(name, coro):
        try:
            await coro
            print(f"[startup] {name} 已就绪")
        except Exception as e:
            print(f"[startup] {name} 失败(非致命): {e}")

    async def _t_publisher():
        from api.services.publisher.account_service import get_account_service
        await get_account_service().ensure_table()

    async def _t_admin():
        from .services.auth import ensure_default_admin
        await ensure_default_admin()

    async def _t_rbac():
        from .services.rbac import get_permission_service
        svc = get_permission_service()
        await svc.ensure_table()
        await svc.seed_default_permissions()

    async def _t_publish_scheduler_tbl():
        from api.services.scheduling.publish_scheduler import get_publish_scheduler
        await get_publish_scheduler().ensure_table()

    async def _t_marketing():
        from api.services.marketing.material_library import get_material_library
        await get_material_library().ensure_table()

    async def _t_sentiment():
        from api.services.moderation.sentiment_monitor import get_sentiment_monitor
        await get_sentiment_monitor().ensure_table()

    async def _t_account_health():
        from api.services.risk_control.account_health import get_account_health_service
        await get_account_health_service().ensure_table()

    async def _t_account_weight():
        from api.services.risk_control.account_weight import get_account_weight_service
        await get_account_weight_service().ensure_table()

    async def _t_dm_tbl():
        from api.services.dm.dm_monitor import get_dm_monitor
        await get_dm_monitor().ensure_table()

    async def _t_video_config():
        from api.services.ai.video_generation_config import get_video_gen_config_service
        await get_video_gen_config_service().ensure_table()

    async def _t_review():
        from api.services.moderation.review_workflow import get_review_workflow_service
        await get_review_workflow_service().ensure_table()

    async def _t_alert():
        from api.services.alert.alert_center import get_alert_center
        await get_alert_center().ensure_table()

    async def _t_bot_pool():
        from api.services.interactor.bot_account_pool import get_bot_account_pool
        await get_bot_account_pool().ensure_table()

    async def _t_interaction_scheduler():
        from api.services.interactor.interaction_scheduler import get_interaction_scheduler
        await get_interaction_scheduler().ensure_table()

    async def _t_script_library():
        from api.services.interactor.script_library import get_script_library
        await get_script_library().ensure_table()

    async def _t_quota():
        from api.services.risk_control.quota_config import get_quota_config_service
        await get_quota_config_service().ensure_table()

    async def _t_compliance():
        from api.services.moderation.compliance_archive import get_compliance_archive_service
        await get_compliance_archive_service().ensure_table()

    async def _t_hotpoint_filter():
        from api.services.hotpoint.hotpoint_filter_config import get_hotpoint_filter_config_service
        await get_hotpoint_filter_config_service().ensure_table()

    async def _t_hot_items():
        from api.services.hotpoint.hot_items_store import get_hot_items_store
        await get_hot_items_store().ensure_table()

    async def _t_video_assets():
        from api.services.ai.video_asset_library import get_video_asset_library
        await get_video_asset_library().ensure_table()

    async def _t_audit():
        from api.services.utils.audit_log import get_audit_log_service, get_report_scheduler
        await get_audit_log_service().ensure_table()
        await get_report_scheduler().ensure_table()

    async def _t_analytics():
        from api.services.analytics.external_metrics import get_external_metrics_collector
        from api.services.analytics.viral_review import get_viral_review_service
        await get_external_metrics_collector().ensure_table()
        await get_viral_review_service().ensure_table()

    async def _t_system_config():
        from api.services.system_config import get_system_config_service
        await get_system_config_service().ensure_table()

    async def _t_interaction_analytics():
        from api.services.analytics.interaction_analytics import get_interaction_analytics
        await get_interaction_analytics().ensure_table()

    async def _t_publish_records():
        from api.services.publisher.publish_records_store import get_publish_records_store
        await get_publish_records_store().ensure_table()

    async def _t_comment_monitor():
        from api.services.comment_monitor.comment_monitor_service import get_comment_monitor_service
        await get_comment_monitor_service().ensure_table()

    async def _t_local_life():
        from api.services.local_life.local_life_service import get_local_life_service
        await get_local_life_service().ensure_table()

    # Phase 1-3 新增服务表创建
    async def _t_ai_pilot():
        from api.services.ai_pilot.ai_pilot_service import get_ai_pilot_service
        await get_ai_pilot_service().ensure_table()

    async def _t_competitor():
        from api.services.competitor.competitor_monitor_service import get_competitor_monitor_service
        await get_competitor_monitor_service().ensure_table()

    async def _t_task_pool():
        from api.services.task_pool.task_pool_service import get_task_pool_service
        await get_task_pool_service().ensure_table()

    async def _t_seo():
        from api.services.seo.seo_service import get_seo_service
        await get_seo_service().ensure_table()

    async def _t_wechat():
        from api.services.wechat.wechat_service import get_wechat_service
        await get_wechat_service().ensure_table()

    async def _t_compute():
        from api.services.compute.compute_service import get_compute_service
        await get_compute_service().ensure_table()

    async def _t_device():
        from api.services.device.device_service import get_device_service
        await get_device_service().ensure_table()

    await asyncio.gather(*[
        _safe("publisher_accounts", _t_publisher()),
        _safe("default_admin", _t_admin()),
        _safe("RBAC(sys_permission/seed)", _t_rbac()),
        _safe("publish_scheduler 表", _t_publish_scheduler_tbl()),
        _safe("marketing_materials", _t_marketing()),
        _safe("sentiment", _t_sentiment()),
        _safe("account_anomaly_alerts", _t_account_health()),
        _safe("account_weights", _t_account_weight()),
        _safe("direct_messages", _t_dm_tbl()),
        _safe("video_generation_configs", _t_video_config()),
        _safe("video_review_tasks", _t_review()),
        _safe("alerts", _t_alert()),
        _safe("bot_accounts", _t_bot_pool()),
        _safe("interaction_schedule_tasks", _t_interaction_scheduler()),
        _safe("interaction_scripts", _t_script_library()),
        _safe("quota_configs", _t_quota()),
        _safe("compliance_archive", _t_compliance()),
        _safe("hotpoint_filter_configs", _t_hotpoint_filter()),
        _safe("hot_items", _t_hot_items()),
        _safe("video_assets", _t_video_assets()),
        _safe("audit_logs+report_summaries", _t_audit()),
        _safe("external_metrics+viral_review", _t_analytics()),
        _safe("sys_config", _t_system_config()),
        _safe("multi_interaction_records", _t_interaction_analytics()),
        _safe("publish_records", _t_publish_records()),
        _safe("comment_monitor 表", _t_comment_monitor()),
        _safe("local_business 表", _t_local_life()),
        # Phase 1-3 新增表
        _safe("ai_pilot_plan 表", _t_ai_pilot()),
        _safe("competitor_account/scan_record 表", _t_competitor()),
        _safe("task_pool/touch_record 表", _t_task_pool()),
        _safe("seo_brand/article 表", _t_seo()),
        _safe("wechat_knowledge/message_log 表", _t_wechat()),
        _safe("compute_account/transaction 表", _t_compute()),
        _safe("device 表", _t_device()),
    ])
    print(f"[startup] Layer 1 完成（ensure_table 并行），耗时 {_time.time()-_t0:.2f}s")

    # ===== Layer 2: 监控/调度器/网络注册后台启动（不阻塞端口监听）=====
    # 所有 start() 类操作改为 create_task，让 FastAPI 立即完成 startup 开始监听端口
    async def _delayed(name, coro, delay=1.0):
        """延迟启动后台服务（给 Layer 1 ensure_table 留时间完成）"""
        await asyncio.sleep(delay)
        try:
            await coro
            print(f"[startup] {name} 已启动")
        except Exception as e:
            print(f"[startup] {name} 启动失败(非致命): {e}")

    # 注册到碳硅交易平台（网络请求，可能超时 → 后台执行不阻塞端口）
    platform_url = os.environ.get("CARBON_SILICON_PLATFORM_URL", "")
    if platform_url:
        async def _bg_register():
            from .services.agent_client import register_to_platform, start_heartbeat
            base_url = os.environ.get("AGENT_BASE_URL", "http://localhost:35092")
            await register_to_platform(base_url)
            await start_heartbeat()
            print(f"[startup] Auto-registered to Carbon-Silicon platform: {platform_url}")
        asyncio.create_task(_delayed("register_to_platform", _bg_register()))
    else:
        print("[startup] CARBON_SILICON_PLATFORM_URL not set, skipping auto-registration")

    # account_pool 加载（5 平台循环，可能涉及网络验证 → 后台执行）
    async def _bg_account_pool():
        from .services.account_pool import get_account_pool, _detect_network_interfaces
        from .services.cookie_manager import get_cookie_pool, get_user_cookie_pool
        await _detect_network_interfaces()
        for platform in ("dy", "xhs", "ks", "bili", "wb"):
            pool = get_account_pool(platform)
            pool.accounts.clear()
            pool.current_account = None
            # 优先从数据库读取（有别名），回退到环境变量
            db_cookies = await get_user_cookie_pool(1, platform)  # admin user_id=1
            if db_cookies:
                for c in db_cookies:
                    await pool.add_account(
                        cookie=c["cookie"],
                        cookie_alias=c.get("alias", ""),
                        phone=c.get("phone", ""),
                        email=c.get("email", ""),
                    )
            else:
                cookie_list = get_cookie_pool(platform)
                if not cookie_list:
                    continue
                for i, cookie_str in enumerate(cookie_list):
                    await pool.add_account(cookie=cookie_str, cookie_alias=f"账号{i+1}")
            if pool.accounts:
                print(f"[startup] Loaded {len(pool.accounts)} accounts into {platform} account_pool")
    asyncio.create_task(_delayed("account_pool", _bg_account_pool()))

    # 任务调度器（daily/weekly 支持）
    async def _bg_task_scheduler():
        from api.services.task_scheduler import start_scheduler
        await start_scheduler()
    asyncio.create_task(_delayed("task_scheduler", _bg_task_scheduler()))

    # X Twitter 评论回复监控（带 watchdog 自动重启）
    async def _bg_comment_monitor():
        from api.services.comment_reply_monitor import start_monitor, is_monitor_running
        if not is_monitor_running():
            ok = await start_monitor()
            if ok:
                print("[startup] X Twitter 评论回复监控已自动启动(带 watchdog 自动重启)")
            else:
                print("[startup] X Twitter 评论回复监控自动启动失败(non-fatal)")
        else:
            print("[startup] X Twitter 评论回复监控已在运行,跳过自动启动")
    asyncio.create_task(_delayed("comment_reply_monitor", _bg_comment_monitor()))

    # 多平台统一评论监控（带 watchdog）
    async def _bg_interaction_monitor():
        from api.services.interactor.interaction_monitor import get_interaction_monitor
        monitor = get_interaction_monitor()
        if not monitor.is_running():
            await monitor.start()
            print("[startup] 多平台评论监控已自动启动(带 watchdog 自动重启)")
        else:
            print("[startup] 多平台评论监控已在运行,跳过自动启动")
    asyncio.create_task(_delayed("interaction_monitor", _bg_interaction_monitor()))

    # 评论监控任务恢复（启动时恢复 status=running 的任务）
    async def _bg_comment_monitor_restore():
        from api.services.comment_monitor.comment_monitor_service import get_comment_monitor_service
        cnt = await get_comment_monitor_service().start_all_persistent_tasks()
        if cnt:
            print(f"[startup] 评论监控已恢复 {cnt} 个任务")
    asyncio.create_task(_delayed("comment_monitor_restore", _bg_comment_monitor_restore()))

    # 定时发布调度器（带 watchdog）
    async def _bg_publish_scheduler():
        from api.services.scheduling.publish_scheduler import get_publish_scheduler
        scheduler = get_publish_scheduler()
        if not scheduler.is_running():
            await scheduler.start()
            print("[startup] 定时发布调度器已自动启动")
        else:
            print("[startup] 定时发布调度器已在运行,跳过自动启动")
    asyncio.create_task(_delayed("publish_scheduler", _bg_publish_scheduler()))

    # DM 私信监控（带 watchdog）
    async def _bg_dm_monitor():
        from api.services.dm.dm_monitor import get_dm_monitor
        from api.services.interactor.interactor_factory import InteractorFactory
        dm_monitor = get_dm_monitor()
        for plat in ("x_twitter", "douyin", "xiaohongshu"):
            if InteractorFactory.is_supported(plat):
                await dm_monitor.add_platform(plat)
        await dm_monitor.start()
        print("[startup] DM 私信监控已自启动")
    asyncio.create_task(_delayed("dm_monitor", _bg_dm_monitor()))

    # 突发热点预警后台扫描
    async def _bg_hotpoint_alert():
        from api.services.hotpoint.hotpoint_alert import get_hotpoint_alert_service
        svc = get_hotpoint_alert_service()
        if not svc.is_running():
            await svc.start()
            print("[startup] 突发热点预警扫描已自动启动")
        else:
            print("[startup] 突发热点预警扫描已在运行")
    asyncio.create_task(_delayed("hotpoint_alert", _bg_hotpoint_alert()))

    # 获客联系方式采集循环（从 getuser-canrun 迁移）
    # 每 2 分钟扫描 contact_status=pending 的线索,自动采集手机号/微信号
    async def _bg_contact_collector():
        from api.services.contact_collector import start_contact_collector_loop
        try:
            await start_contact_collector_loop()
            print("[startup] 获客联系方式采集循环已自动启动")
        except Exception as e:
            print(f"[startup] 获客联系方式采集循环启动失败(non-fatal): {e}")
    asyncio.create_task(_delayed("contact_collector", _bg_contact_collector()))

    # 抖音线索评论回复监测循环（从 getuser-canrun 迁移）
    # 每 10 分钟扫描已触达线索,回扫源视频评论区捕获新回复
    async def _bg_lead_reply_monitor():
        from api.services.lead_comment_monitor import start_reply_monitor_loop
        try:
            await start_reply_monitor_loop()
            print("[startup] 抖音线索评论回复监测循环已自动启动")
        except Exception as e:
            print(f"[startup] 抖音线索评论回复监测循环启动失败(non-fatal): {e}")
    asyncio.create_task(_delayed("lead_reply_monitor", _bg_lead_reply_monitor()))

    # 启动统一调度定时任务（P1-10）- 原本已是 create_task，保持
    try:
        asyncio.create_task(_start_scheduled_jobs())
        print("[startup] 定时任务调度器已启动（账号异常扫描/冷存储迁移/过期清理/报表生成/热点更新）")
    except Exception as e:
        print(f"[startup] 启动定时任务调度失败(非致命): {e}")

    print(f"[startup] 启动完成（后台监控/调度器异步启动中），端口已开始监听，总耗时 {_time.time()-_t0:.2f}s")


# ==================== 定时任务调度（P1-10） ====================

async def _start_scheduled_jobs() -> None:
    """统一启动 6 个后台定时任务循环。

    每个循环用 `while True: sleep + try/except` 模式，单次失败不退出。
    """
    # 1. 账号异常扫描：每 30 分钟一次
    asyncio.create_task(_loop_account_anomaly_scan(interval_seconds=1800))
    # 2. 冷存储迁移：每天凌晨 3 点
    asyncio.create_task(_loop_daily_at(hour=3, func=_job_migrate_cold_storage))
    # 3. 过期清理：每天凌晨 4 点
    asyncio.create_task(_loop_daily_at(hour=4, func=_job_purge_expired))
    # 4. 日报表：每天 6 点；周报：周一 6 点；月报：每月 1 号 6 点
    asyncio.create_task(_loop_daily_at(hour=6, func=_job_generate_reports))
    # 5. 热点全量更新：从 hotpoint_filter_config 读取 fetch_interval_seconds
    asyncio.create_task(_loop_hotpoint_fetch())
    # 6. 数据异常检测：每天 8 点(阶段三 P2-8)
    asyncio.create_task(_loop_daily_at(hour=8, func=_job_detect_data_anomaly))
    # 7. 账号权重刷新：每 6 小时刷新一次（F3 接入主流程，避免频繁刷新打满 CPU）
    asyncio.create_task(_loop_refresh_account_weights(interval_seconds=6 * 3600))


async def _sleep_until_next(hour: int, minute: int = 0) -> None:
    """睡眠到下一个指定时刻（本地时间）。"""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    sleep_seconds = max((target - now).total_seconds(), 0)
    await asyncio.sleep(sleep_seconds)


async def _loop_account_anomaly_scan(interval_seconds: int) -> None:
    """账号异常扫描循环：定期调用 AccountHealthService.check_anomalies()。"""
    await asyncio.sleep(30)  # 启动延迟 30s 避开启动峰值
    while True:
        try:
            from api.services.risk_control.account_health import (
                get_account_health_service,
            )
            svc = get_account_health_service()
            alerts = await svc.check_anomalies()
            if alerts:
                print(f"[Scheduler] 账号异常扫描发现 {len(alerts)} 条异常预警")
                # check_anomalies 内部已通过 _create_alert 写入预警表；
                # 进一步触发统一预警中心事件（如已实现 emit_account_anomaly）
                try:
                    from api.services.alert.alert_center import (
                        emit_account_anomaly, AlertSeverity,
                    )
                    for a in alerts:
                        await emit_account_anomaly(
                            account_id=a.get("account_id"),
                            platform=a.get("platform", ""),
                            anomaly_type=",".join(a.get("anomalies", [])[:3]),
                            severity=AlertSeverity.WARNING.value,
                        )
                except Exception as emit_e:
                    print(f"[Scheduler] emit_account_anomaly 失败(非致命): {emit_e}")
        except Exception as e:
            print(f"[Scheduler] 账号异常扫描循环异常: {e}")
        await asyncio.sleep(interval_seconds)


async def _loop_daily_at(hour: int, func) -> None:
    """每天指定时刻运行一次的循环。"""
    while True:
        try:
            await _sleep_until_next(hour)
            await func()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Scheduler] 每日任务(hour={hour})异常: {e}")
            await asyncio.sleep(60)


async def _job_migrate_cold_storage() -> None:
    """冷存储迁移：把超 90 天的热数据迁移到冷存储。"""
    from api.services.moderation.compliance_archive import (
        get_compliance_archive_service,
    )
    svc = get_compliance_archive_service()
    n = await svc.migrate_cold_storage()
    print(f"[Scheduler] 冷存储迁移完成: {n} 条记录")


async def _job_purge_expired() -> None:
    """过期清理：清理超 1 年的归档。"""
    from api.services.moderation.compliance_archive import (
        get_compliance_archive_service,
    )
    svc = get_compliance_archive_service()
    n = await svc.purge_expired()
    print(f"[Scheduler] 过期归档清理完成: {n} 条记录")


async def _job_generate_reports() -> None:
    """报表生成：每天日报；周一加周报；每月 1 号加月报。"""
    from api.services.utils.audit_log import get_report_scheduler
    svc = get_report_scheduler()

    # 日报表（覆盖最近 1 天）
    try:
        await svc.generate_report(period="daily", days=1)
        print("[Scheduler] 日报表已生成")
    except Exception as e:
        print(f"[Scheduler] 日报表生成失败: {e}")

    # 周报：每周一
    if datetime.now().weekday() == 0:
        try:
            await svc.generate_report(period="weekly", days=7)
            print("[Scheduler] 周报表已生成")
        except Exception as e:
            print(f"[Scheduler] 周报表生成失败: {e}")

    # 月报：每月 1 号
    if datetime.now().day == 1:
        try:
            await svc.generate_report(period="monthly", days=30)
            print("[Scheduler] 月报表已生成")
        except Exception as e:
            print(f"[Scheduler] 月报表生成失败: {e}")


async def _job_detect_data_anomaly() -> None:
    """数据异常检测(阶段三 P2-8)。

    对比最近 7 天与上一个 7 天的核心指标,下降超过 30% 触发预警。
    detect_data_anomaly 为 async 且无副作用(除触发预警外),可安全调用。
    """
    try:
        from api.services.analytics import get_analytics_service
        svc = get_analytics_service()
        anomalies = await svc.detect_data_anomaly(days=7)
        if anomalies:
            print(f"[Scheduler] 数据异常检测发现 {len(anomalies)} 个异常指标并已触发预警")
        else:
            print("[Scheduler] 数据异常检测: 无异常")
    except Exception as e:
        print(f"[Scheduler] 数据异常检测失败: {e}")


async def _loop_hotpoint_fetch() -> None:
    """热点全量更新循环：按 hotpoint_filter_config.fetch_interval_seconds 周期性抓取。

    间隔在每次循环开始时重新读取，确保用户修改配置后下次循环生效。
    """
    await asyncio.sleep(15)  # 启动延迟 15s 让其他服务先就绪（原 60s 过长，导致重启后首请求同步抓 15 平台超时）
    while True:
        # 读取最新配置（动态生效）
        interval = 1800  # 默认 30 分钟
        try:
            from api.services.hotpoint.hotpoint_filter_config import (
                get_hotpoint_filter_config_service,
                DEFAULT_FETCH_INTERVAL,
            )
            svc = get_hotpoint_filter_config_service()
            cfg = await svc.get_active_config()
            if cfg and cfg.get("fetch_interval_seconds"):
                interval = max(int(cfg["fetch_interval_seconds"]), 300)
            else:
                interval = DEFAULT_FETCH_INTERVAL
        except Exception as e:
            print(f"[Scheduler] 读取热点抓取间隔失败，使用默认 {interval}s: {e}")

        try:
            from api.services.hotpoint_fetcher import fetch_all
            # force_refresh=True：后台预热/刷新任务拿完整数据（不受 fetch_all 的单平台超时限制）。
            # 普通请求路径 force_refresh=False 有 10s 超时保护，快速返回部分数据。
            results = await fetch_all(force_refresh=True)
            total = sum(len(items) for items in results.values())
            print(f"[Scheduler] 热点全量更新: {len(results)} 个平台, 共 {total} 条")
            # upsert 到 hot_items 表（若表存在）
            await _upsert_hot_items(results)
        except Exception as e:
            print(f"[Scheduler] 热点全量更新异常: {e}")

        await asyncio.sleep(interval)


async def _upsert_hot_items(results: dict) -> None:
    """把 fetch_all 结果 upsert 到 hot_items 表（通过 HotItemsStore）。

    fetch_all 返回 {platform: [item, ...]} 字典。
    item 字段：rank, title, url, hot, author, published_at, extra

    集成热点分类器：若上游已带 category 则保留；否则调用 HotpointClassifier
    进行关键词+AI 兜底分类，并将推荐平台一并写入 hot_items 表。
    """
    try:
        from api.services.hotpoint.hot_items_store import get_hot_items_store
        from api.services.hotpoint.hotpoint_classifier import get_hotpoint_classifier
        store = get_hot_items_store()
        classifier = get_hotpoint_classifier()
        total = 0
        classified = 0
        for platform, items in results.items():
            for it in items:
                try:
                    extra = it.get("extra", {}) or {}
                    title = (it.get("title") or "")[:500]
                    content = extra.get("desc", "")

                    # 1. 上游若已带 category，直接沿用
                    category = extra.get("category", "") or ""
                    recommended_platforms = extra.get("recommended_platforms", "") or ""

                    # 2. 若没有 category，调用分类器
                    if not category and title:
                        try:
                            classification = await classifier.classify(title, content)
                            category = classification.category
                            if not recommended_platforms and classification.recommended_platforms:
                                recommended_platforms = ",".join(classification.recommended_platforms)
                            classified += 1
                        except Exception as ce:
                            print(f"[Scheduler] hotpoint classify 失败(非致命): {ce}")

                    await store.upsert({
                        "platform": platform,
                        "source_id": str(it.get("url", ""))[:128],  # 用 URL 作为 source_id
                        "title": title,
                        "content": content,
                        "url": it.get("url", ""),
                        "video_url": extra.get("video_url", ""),
                        "username": (it.get("author") or "")[:128],
                        "heat_value": _parse_int(it.get("hot", "0")),
                        "source_keyword": extra.get("source_label", ""),
                        "category": category,
                        "recommended_platforms": recommended_platforms,
                        "extra": extra,
                    })
                    total += 1
                except Exception:
                    continue
        if total:
            print(f"[Scheduler] hot_items upsert 完成: {total} 条 (其中分类器标注 {classified} 条)")
    except Exception as e:
        print(f"[Scheduler] upsert hot_items 失败(非致命): {e}")


async def _loop_refresh_account_weights(interval_seconds: int = 3600) -> None:
    """每小时刷新所有账号权重（F3 接入主流程）

    AccountWeightService.refresh_all 会遍历 publisher_accounts，
    基于成功率/健康分/违规数/互动效果重新计算权重并持久化到 account_weights 表。
    acquire_cookie 选号时会读取该表的权重排序。
    """
    while True:
        try:
            from api.services.risk_control.account_weight import get_account_weight_service
            count = await get_account_weight_service().refresh_all()
            print(f"[Scheduler] 账号权重刷新完成: {count} 个账号")
        except Exception as e:
            print(f"[Scheduler] 账号权重刷新失败(非致命): {e}")
        await asyncio.sleep(interval_seconds)


def _parse_int(v) -> int:
    """把热度值字符串解析为整数（兼容 '1.2K' / '3M' / 纯数字 / 浮点）。"""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace(",", "").strip()
    if not s:
        return 0
    try:
        suffix = s[-1].lower()
        if suffix in ("k", "m", "b"):
            num = float(s[:-1])
            mult = {"k": 1000, "m": 1_000_000, "b": 1_000_000_000}[suffix]
            return int(num * mult)
        return int(float(s))
    except Exception:
        return 0


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
app.include_router(x_workbench_auto_pipeline_router, prefix="/api")
# 注意：hotpoint 的子路由（filter-config/categories/alerts）前缀为 /hotpoint/xxx，
# 必须在 hotpoint_router（含宽泛路由 GET /{platform}）之前注册，否则会被 /{platform} 覆盖。
app.include_router(hotpoint_filter_router, prefix="/api")
app.include_router(hotpoint_category_router, prefix="/api")
app.include_router(hotpoint_alert_router, prefix="/api")
app.include_router(hotpoint_router, prefix="/api")
app.include_router(opennotebook_integration_router, prefix="/api")
app.include_router(publish_router, prefix="/api")
app.include_router(accounts_router, prefix="/api")
app.include_router(interact_router, prefix="/api")
app.include_router(interaction_analytics_router, prefix="/api")
app.include_router(auto_pipeline_router, prefix="/api")
app.include_router(moderation_router, prefix="/api")
app.include_router(scheduling_router, prefix="/api")
app.include_router(marketing_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(risk_control_router, prefix="/api")
app.include_router(dm_router, prefix="/api")
app.include_router(content_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(workflow_router, prefix="/api")
app.include_router(monitoring_router, prefix="/api")
app.include_router(brand_router, prefix="/api")
app.include_router(competitor_router, prefix="/api")
app.include_router(keyword_router, prefix="/api")
app.include_router(audit_log_router, prefix="/api")
app.include_router(talking_head_router, prefix="/api")
# 阶段一 P0 扩展路由
app.include_router(alert_router, prefix="/api")
app.include_router(video_config_router, prefix="/api")
app.include_router(batch_video_router, prefix="/api")
app.include_router(prompt_pipeline_router, prefix="/api")
app.include_router(review_router, prefix="/api")
app.include_router(bot_account_router, prefix="/api")
app.include_router(unified_pipeline_router, prefix="/api")
# 阶段三 P2-7 系统配置(评分规则/通知设置后端持久化)
app.include_router(system_config_router, prefix="/api")
# 评论监控 + 本地生活
app.include_router(comment_monitor_router, prefix="/api")
app.include_router(local_life_router, prefix="/api")
app.include_router(customer_dispatch_router, prefix="/api")
app.include_router(ai_customer_service_router, prefix="/api")
# Phase 1-3 新增路由注册
app.include_router(ai_pilot_router, prefix="/api")
app.include_router(task_pool_router, prefix="/api")
app.include_router(mixcut_router, prefix="/api")
app.include_router(seo_router, prefix="/api")
app.include_router(wechat_router, prefix="/api")
app.include_router(compute_router, prefix="/api")
app.include_router(device_router, prefix="/api")
# 业务画像路由(获客配置复用)
app.include_router(business_profiles_router, prefix="/api")

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

# Mount talking_head generated files directory (videos/covers/audio)
# 让前端能通过 /api/talking-head/files/xxx.mp4 直接访问 /tmp/talking_head/xxx.mp4
talking_head_dir = "/tmp/talking_head"
os.makedirs(talking_head_dir, exist_ok=True)
app.mount("/api/talking-head/files", StaticFiles(directory=talking_head_dir), name="talking-head-files")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


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
