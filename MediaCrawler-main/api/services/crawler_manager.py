# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/services/crawler_manager.py
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

import asyncio
import subprocess
import signal
import sys
import os
from typing import Optional, List, Dict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from ..schemas import CrawlerStartRequest, LogEntry
from .cookie_manager import get_cookie, PLATFORM_ENV_KEYS


class CrawlerManager:
    """Crawler process manager - supports multiple concurrent tasks"""

    def __init__(self):
        self._lock = asyncio.Lock()
        # Per-task process storage
        self._processes: Dict[str, subprocess.Popen] = {}
        self._statuses: Dict[str, str] = {}
        self._started_ats: Dict[str, datetime] = {}
        self._configs: Dict[str, CrawlerStartRequest] = {}
        self._log_ids: Dict[str, int] = {}
        self._task_logs: Dict[str, List[LogEntry]] = {}
        self._read_tasks: Dict[str, asyncio.Task] = {}
        self._log_queues: Dict[str, asyncio.Queue] = {}
        # Global log queue for WebSocket broadcast
        self._global_log_queue: asyncio.Queue = asyncio.Queue()
        # Project root directory
        self._project_root = Path(__file__).parent.parent.parent
        # 任务归属用户(用于通知推送)
        self._owner_user_ids: Dict[str, str] = {}
        # cookie_invalid 通知去重(避免同一任务短时间内重复通知)
        self._cookie_invalid_notified: Dict[str, float] = {}

    def logs(self, task_id: Optional[str] = None) -> List[LogEntry]:
        if task_id:
            return self._task_logs.get(task_id, [])
        # Backward compatibility: return all logs merged
        all_logs = []
        for logs in self._task_logs.values():
            all_logs.extend(logs)
        return sorted(all_logs, key=lambda x: x.id)

    def get_log_queue(self, task_id: Optional[str] = None) -> asyncio.Queue:
        """Get or create log queue for a task. If task_id is None, return global queue for WebSocket broadcast."""
        if task_id is None:
            return self._global_log_queue
        if task_id not in self._log_queues:
            self._log_queues[task_id] = asyncio.Queue()
        return self._log_queues[task_id]

    def _create_log_entry(self, task_id: str, message: str, level: str = "info") -> LogEntry:
        """Create log entry for a specific task"""
        self._log_ids[task_id] = self._log_ids.get(task_id, 0) + 1
        entry = LogEntry(
            id=self._log_ids[task_id],
            timestamp=datetime.now().strftime("%H:%M:%S"),
            level=level,
            message=message,
            task_id=task_id,
        )
        if task_id not in self._task_logs:
            self._task_logs[task_id] = []
        self._task_logs[task_id].append(entry)
        # Keep last 500 logs per task
        if len(self._task_logs[task_id]) > 500:
            self._task_logs[task_id] = self._task_logs[task_id][-500:]
        return entry

    async def _push_log(self, task_id: str, entry: LogEntry):
        """Push log to task queue and global queue for broadcast"""
        # Push to task-specific queue
        task_queue = self.get_log_queue(task_id)
        try:
            task_queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass
        # Push to global queue for WebSocket broadcast
        try:
            self._global_log_queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass

    def _parse_log_level(self, line: str) -> str:
        """Parse log level"""
        line_upper = line.upper()
        # CAPTCHA and retry errors are recoverable, treat as warning
        if "CAPTCHA" in line_upper or "RETRY ERROR" in line_upper:
            return "warning"
        if "ERROR" in line_upper or "FAILED" in line_upper:
            return "error"
        elif "WARNING" in line_upper or "WARN" in line_upper:
            return "warning"
        elif "SUCCESS" in line_upper or "完成" in line or "成功" in line:
            return "success"
        elif "DEBUG" in line_upper:
            return "debug"
        return "info"

    async def start(self, config: CrawlerStartRequest, task_id: Optional[str] = None, owner_user_id: Optional[int] = None) -> tuple:
        """Start crawler process for a specific task

        Returns:
            (success: bool, message: str)
        """
        if task_id is None:
            task_id = "default"

        async with self._lock:
            # Check if this specific task is already running
            if task_id in self._processes and self._processes[task_id].poll() is None:
                return (False, "Crawler already running for this task")

            # Clear old logs and reset state for this task
            self._task_logs[task_id] = []
            self._log_ids[task_id] = 0

            # Clear pending queue
            if task_id in self._log_queues:
                try:
                    while True:
                        self._log_queues[task_id].get_nowait()
                except asyncio.QueueEmpty:
                    pass
            else:
                self._log_queues[task_id] = asyncio.Queue()

            # Build command line arguments
            cmd = self._build_command(config)

            # Log start information
            entry = self._create_log_entry(task_id, f"Starting crawler: {' '.join(cmd)}", "info")
            await self._push_log(task_id, entry)

            try:
                # 使用统一的 cookie_manager 获取 Cookie,优先使用任务创建者的用户级别 Cookie
                platform = config.platform.value
                crawler_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
                # Fix: force system library path to avoid IDE sandbox injecting outdated glib
                crawler_env["LD_LIBRARY_PATH"] = "/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu"

                # 从 cookie_manager 获取该平台对应的 Cookie 环境变量名
                env_key = PLATFORM_ENV_KEYS.get(platform)
                if env_key:
                    # 优先从用户级别数据库获取(实现用户隔离),失败退回全局 .env
                    cookie_value = ""
                    try:
                        from .cookie_manager import get_user_cookie
                        if owner_user_id:
                            cookie_value = await get_user_cookie(owner_user_id, platform)
                    except Exception as e:
                        entry = self._create_log_entry(task_id, f"Warning: Failed to load user cookie (user_id={owner_user_id}): {e}", "warning")
                        await self._push_log(task_id, entry)

                    # 退回全局 .env(管理员或老任务)
                    if not cookie_value:
                        cookie_value = get_cookie(platform)

                    if cookie_value:
                        crawler_env[env_key] = cookie_value
                        entry = self._create_log_entry(task_id, f"Loaded {platform} cookie ({len(cookie_value)} chars, user_id={owner_user_id or 'global'})", "info")
                        await self._push_log(task_id, entry)
                    else:
                        entry = self._create_log_entry(task_id, f"Warning: No cookie found for platform {platform} (user_id={owner_user_id or 'global'})", "warning")
                        await self._push_log(task_id, entry)
                
                # 同时加载 .env 文件作为补充（确保其他配置变量也传递给子进程）
                env_path = self._project_root / ".env"
                if env_path.exists():
                    with open(env_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith('#'):
                                continue
                            if '=' in line:
                                key, value = line.split('=', 1)
                                key = key.strip()
                                value = value.strip().strip('"').strip("'")
                                if key and value and key not in crawler_env:
                                    crawler_env[key] = value

                # Start subprocess
                self._processes[task_id] = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                    cwd=str(self._project_root),
                    env=crawler_env
                )

                self._statuses[task_id] = "running"
                self._started_ats[task_id] = datetime.now()
                self._configs[task_id] = config
                self._owner_user_ids[task_id] = str(owner_user_id) if owner_user_id else ""

                entry = self._create_log_entry(
                    task_id,
                    f"Crawler started on platform: {config.platform.value}, type: {config.crawler_type.value}",
                    "success"
                )
                await self._push_log(task_id, entry)

                # Start log reading task for this process
                self._read_tasks[task_id] = asyncio.create_task(self._read_output(task_id))

                return (True, "Crawler started")
            except Exception as e:
                self._statuses[task_id] = "error"
                error_msg = f"Failed to start crawler: {str(e)}"
                entry = self._create_log_entry(task_id, error_msg, "error")
                await self._push_log(task_id, entry)
                return (False, error_msg)

    async def stop(self, task_id: Optional[str] = None) -> tuple:
        """Stop crawler process for a specific task

        Returns:
            (success: bool, message: str)
        """
        if task_id is None:
            task_id = "default"

        async with self._lock:
            if task_id not in self._processes or self._processes[task_id].poll() is not None:
                return (True, "No running process to stop")

            self._statuses[task_id] = "stopping"
            entry = self._create_log_entry(task_id, "Sending SIGTERM to crawler process...", "warning")
            await self._push_log(task_id, entry)

            try:
                if sys.platform == "win32":
                    # Windows: use taskkill
                    pid = self._processes[task_id].pid
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
                else:
                    self._processes[task_id].send_signal(signal.SIGTERM)

                    # Wait for graceful exit (up to 15 seconds)
                    for _ in range(30):
                        if self._processes[task_id].poll() is not None:
                            break
                        await asyncio.sleep(0.5)

                    # If still not exited, force kill
                    if self._processes[task_id].poll() is None:
                        entry = self._create_log_entry(task_id, "Process not responding, sending SIGKILL...", "warning")
                        await self._push_log(task_id, entry)
                        self._processes[task_id].kill()

                entry = self._create_log_entry(task_id, "Crawler process terminated", "info")
                await self._push_log(task_id, entry)

            except Exception as e:
                entry = self._create_log_entry(task_id, f"Error stopping crawler: {str(e)}", "error")
                await self._push_log(task_id, entry)

            self._statuses[task_id] = "idle"
            self._configs[task_id] = None

            # Cancel log reading task
            if task_id in self._read_tasks:
                self._read_tasks[task_id].cancel()
                del self._read_tasks[task_id]

            return (True, "Crawler process terminated")

    def get_status(self, task_id: Optional[str] = None) -> dict:
        """Get current status for a specific task"""
        if task_id is None:
            task_id = "default"
        config = self._configs.get(task_id)
        return {
            "status": self._statuses.get(task_id, "idle"),
            "platform": config.platform.value if config else None,
            "crawler_type": config.crawler_type.value if config else None,
            "started_at": self._started_ats[task_id].isoformat() if task_id in self._started_ats and self._started_ats[task_id] else None,
            "error_message": None
        }

    def get_all_statuses(self) -> Dict[str, dict]:
        """Get status for all tasks"""
        return {tid: self.get_status(tid) for tid in self._processes.keys()}

    def is_running(self, task_id: Optional[str] = None) -> bool:
        """Check if a specific task is running"""
        if task_id is None:
            # Check if any task is running
            return any(
                p.poll() is None for p in self._processes.values()
            )
        return task_id in self._processes and self._processes[task_id].poll() is None

    def _build_command(self, config: CrawlerStartRequest) -> list:
        """Build main.py command line arguments"""
        import shutil
        # 优先使用 uv，不可用时回退到系统 Python
        if shutil.which("uv"):
            cmd = ["uv", "run", "python", "main.py"]
        else:
            cmd = [sys.executable, "main.py"]

        cmd.extend(["--platform", config.platform.value])
        cmd.extend(["--lt", config.login_type.value])
        cmd.extend(["--type", config.crawler_type.value])
        cmd.extend(["--save_data_option", config.save_option.value])

        # Pass different arguments based on crawler type
        if config.crawler_type.value == "search" and config.keywords:
            cmd.extend(["--keywords", config.keywords])
        elif config.crawler_type.value == "detail" and config.specified_ids:
            cmd.extend(["--specified_id", config.specified_ids])
        elif config.crawler_type.value == "creator" and config.creator_ids:
            cmd.extend(["--creator_id", config.creator_ids])

        if config.start_page != 1:
            cmd.extend(["--start", str(config.start_page)])

        cmd.extend(["--get_comment", "true" if config.enable_comments else "false"])
        cmd.extend(["--get_sub_comment", "true" if config.enable_sub_comments else "false"])

        if config.max_notes_count is not None:
            cmd.extend(["--crawler_max_notes_count", str(config.max_notes_count)])

        if config.max_comments_count is not None:
            cmd.extend(["--max_comments_count_singlenotes", str(config.max_comments_count)])

        if config.cookies:
            cmd.extend(["--cookies", config.cookies])

        cmd.extend(["--headless", "true" if config.headless else "false"])

        # 传入发布时间过滤
        if hasattr(config, "publish_time_type") and config.publish_time_type:
            cmd.extend(["--publish_time_type", str(config.publish_time_type)])

        # 传入任务ID用于数据归属
        if hasattr(config, "task_id") and config.task_id:
            cmd.extend(["--task_id", config.task_id])

        return cmd

    async def _read_output(self, task_id: str):
        """Asynchronously read process output for a specific task"""
        loop = asyncio.get_event_loop()

        try:
            while task_id in self._processes and self._processes[task_id].poll() is None:
                # Read a line in thread pool
                line = await loop.run_in_executor(
                    None, self._processes[task_id].stdout.readline
                )
                if line:
                    line = line.strip()
                    if line:
                        level = self._parse_log_level(line)
                        entry = self._create_log_entry(task_id, line, level)
                        await self._push_log(task_id, entry)
                        # 检测 cookie_invalid 事件，在主进程中触发通知
                        await self._check_cookie_invalid(task_id, line)

            # Read remaining output
            if task_id in self._processes and self._processes[task_id].stdout:
                remaining = await loop.run_in_executor(
                    None, self._processes[task_id].stdout.read
                )
                if remaining:
                    for line in remaining.strip().split('\n'):
                        if line.strip():
                            level = self._parse_log_level(line)
                            entry = self._create_log_entry(task_id, line.strip(), level)
                            await self._push_log(task_id, entry)
                            await self._check_cookie_invalid(task_id, line.strip())

            # Process ended
            if self._statuses.get(task_id) == "running":
                process = self._processes.get(task_id)
                exit_code = process.returncode if process else -1
                if exit_code == 0 or exit_code == -15 or exit_code == 15:
                    # 0 = normal exit, -15/15 = SIGTERM (graceful shutdown or timeout)
                    entry = self._create_log_entry(task_id, "Crawler completed successfully", "success")
                else:
                    entry = self._create_log_entry(task_id, f"Crawler exited with code: {exit_code}", "warning")
                await self._push_log(task_id, entry)
                self._statuses[task_id] = "idle"

        except asyncio.CancelledError:
            pass
        except Exception as e:
            entry = self._create_log_entry(task_id, f"Error reading output: {str(e)}", "error")
            await self._push_log(task_id, entry)

    async def _check_cookie_invalid(self, task_id: str, line: str):
        """检测子进程日志中的 cookie_invalid 事件，在主进程中触发通知(写站内消息 + WebSocket 推送)"""
        # 匹配: [AccountPool] Account acc_xxx (别名) marked DEAD (cookie invalid)
        if "marked DEAD" not in line or "cookie invalid" not in line:
            return

        import time as _time
        # 去重: 同一任务 5 分钟内只通知一次
        now = _time.time()
        last_ts = self._cookie_invalid_notified.get(task_id, 0)
        if now - last_ts < 300:
            return
        self._cookie_invalid_notified[task_id] = now

        # 提取账号别名: "Account acc_xxx (别名) marked DEAD"
        import re
        m = re.search(r'marked DEAD.*?\(([^)]+)\)\s+marked DEAD', line)
        if not m:
            # 简单匹配括号内容
            m = re.search(r'Account\s+\S+\s+\(([^)]+)\)\s+marked DEAD', line)
        cookie_alias = m.group(1) if m else "未知账号"

        # 获取 platform 和 owner_user_id
        config = self._configs.get(task_id)
        platform = config.platform.value if config else "unknown"
        owner_user_id = self._owner_user_ids.get(task_id, "")

        # 平台标签
        platform_labels = {"dy": "抖音", "xhs": "小红书", "bili": "B站", "douyin": "抖音"}
        platform_label = platform_labels.get(platform, platform)

        title = f"{platform_label} Cookie 失效提醒"
        content = (
            f"您的{platform_label}账号「{cookie_alias}」Cookie 已失效（登录态过期），"
            f"相关采集任务已暂停使用该账号。\n"
            f"请前往「Cookie 管理」页面重新登录或更新 Cookie，更新后任务将自动恢复。"
        )

        # 1. 写入站内消息(持久化)
        try:
            import json as _json
            from database.db_session import get_session
            from api.services.notification_service import send_in_app_message
            async with get_session() as session:
                await send_in_app_message(
                    session=session,
                    owner_user_id=owner_user_id,
                    title=title,
                    content=content,
                    msg_type="warning",
                    extra=_json.dumps(
                        {"platform": platform, "cookie_alias": cookie_alias, "task_id": task_id},
                        ensure_ascii=False,
                    ),
                )
        except Exception as e:
            print(f"[CrawlerManager] 写入 Cookie 失效站内消息失败: {e}")

        # 2. WebSocket 实时推送(用户在线时立即弹出)
        try:
            from api.routers.websocket import notify_user
            await notify_user(
                owner_user_id=owner_user_id,
                title=title,
                content=content,
                msg_type="warning",
                extra={"platform": platform, "cookie_alias": cookie_alias, "task_id": task_id},
            )
        except Exception as e:
            print(f"[CrawlerManager] WebSocket 推送 Cookie 失效通知失败: {e}")


# Global singleton
crawler_manager = CrawlerManager()
