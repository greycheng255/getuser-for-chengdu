# -*- coding: utf-8 -*-
"""批量截取 WebUI 全部核心页面截图，用于生成图文并茂的 Word 使用手册。"""
import os
import time
import urllib.request
import json

from playwright.sync_api import sync_playwright

BASE = "http://localhost:35174"
IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "images")
os.makedirs(IMG_DIR, exist_ok=True)

# (文件名, 路由, 页面标题)
PAGES = [
    ("00_login", "/login", "登录页"),
    ("01_dashboard", "/", "工作台"),
    ("02_leads", "/leads", "客户线索"),
    ("03_tasks", "/tasks", "获客任务管理"),
    ("04_cookies", "/cookies", "Cookie 账号管理"),
    ("05_business", "/business", "商业档案管理"),
    ("06_analytics", "/analytics", "数据分析"),
    ("07_hotpoint_library", "/hotpoint-library", "热点库"),
    ("08_publish_center", "/publish-center", "发布中心"),
    ("09_publish_schedule", "/publish-schedule", "发布计划"),
    ("10_script_library", "/script-library", "话术脚本库"),
    ("11_viral_reviews", "/viral-reviews", "爆款评论"),
    ("12_prompt_library", "/prompt-library", "提示词库"),
    ("13_interaction_config", "/interaction-config", "互动配置"),
    ("14_comment_monitor", "/comment-monitor", "评论监控"),
    ("15_dm_manager", "/dm-manager", "私信管理"),
    ("16_x_workbench", "/x-workbench", "X 平台工作台"),
    ("17_pipeline_dashboard", "/pipeline-dashboard", "获客流水线看板"),
    ("18_customer_dispatch", "/customer-dispatch", "客户分发"),
    ("19_ai_customer_service", "/ai-customer-service", "AI 智能客服"),
    ("20_local_life", "/local-life", "本地生活"),
    ("21_marketing_materials", "/marketing-materials", "营销素材库"),
    ("22_talking_head", "/talking-head", "数字人视频"),
    ("23_video_gen_config", "/video-gen-config", "视频生成配置"),
    ("24_bot_accounts", "/bot-accounts", "机器人账号"),
    ("25_review_queue", "/review-queue", "内容审核队列"),
    ("26_external_metrics", "/external-metrics", "外部数据指标"),
    ("27_alert_center", "/alert-center", "预警中心"),
    ("28_users", "/users", "用户管理"),
    ("29_system_logs", "/system-logs", "系统日志"),
    ("30_settings", "/settings", "系统设置"),
    ("31_mine", "/mine", "个人中心"),
]


def get_token():
    req = urllib.request.Request(
        "http://localhost:8080/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["token"]


def main():
    token = get_token()
    print(f"[shot] token ok, {len(PAGES)} pages")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(viewport={"width": 1600, "height": 900}, locale="zh-CN")
        page = ctx.new_page()
        # 先打开登录页注入 token
        page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=30000)
        page.evaluate(
            """([t]) => {
                localStorage.setItem('auth_token', t);
                localStorage.setItem('theme_mode', 'light');
                localStorage.setItem('onboarding_completed_v1', '1');
            }""",
            [token],
        )
        for name, route, title in PAGES:
            try:
                if name == "00_login":
                    page.evaluate("() => localStorage.removeItem('auth_token')")
                    page.goto(BASE + route, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2500)
                    page.evaluate("([t]) => localStorage.setItem('auth_token', t)", [token])
                else:
                    page.goto(BASE + route, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(5000)
                out = os.path.join(IMG_DIR, f"{name}.png")
                page.screenshot(path=out)
                print(f"[shot] ok  {name}  {title}")
            except Exception as e:
                print(f"[shot] FAIL {name}: {e}")
        browser.close()
    print("[shot] all done ->", IMG_DIR)


if __name__ == "__main__":
    main()
