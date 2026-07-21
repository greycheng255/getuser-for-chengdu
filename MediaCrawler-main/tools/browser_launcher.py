# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/browser_launcher.py
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


import os
import platform
import subprocess
import time
import socket
import signal
from typing import Optional, List, Tuple
import asyncio
from pathlib import Path

from tools import utils


class BrowserLauncher:
    """
    Browser launcher for detecting and launching user's Chrome/Edge browser
    Supports Windows and macOS systems
    """

    def __init__(self):
        self.system = platform.system()
        self.browser_process = None
        self.debug_port = None

    def detect_browser_paths(self) -> List[str]:
        """
        Detect available browser paths in system
        Returns list of browser paths sorted by priority
        """
        paths = []

        if self.system == "Windows":
            # Common Chrome/Edge installation paths on Windows
            possible_paths = [
                # Chrome paths
                os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                # Edge paths
                os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
                # Chrome Beta/Dev/Canary
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome Beta\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome Dev\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome SxS\Application\chrome.exe"),
            ]
        elif self.system == "Darwin":  # macOS
            # Common Chrome/Edge installation paths on macOS
            possible_paths = [
                # Chrome paths
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
                "/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev",
                "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
                # Edge paths
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta",
                "/Applications/Microsoft Edge Dev.app/Contents/MacOS/Microsoft Edge Dev",
                "/Applications/Microsoft Edge Canary.app/Contents/MacOS/Microsoft Edge Canary",
            ]
        else:
            # Linux and other systems
            possible_paths = [
                # Direct binary first — wrapper scripts use bash process substitution
                # (>(exec cat)) which fails under sandboxed environments
                "/opt/google/chrome/chrome",
                "/opt/google/chrome-beta/chrome",
                "/opt/google/chrome-unstable/chrome",
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/google-chrome-beta",
                "/usr/bin/google-chrome-unstable",
                "/usr/bin/chromium-browser",
                "/usr/bin/chromium",
                "/snap/bin/chromium",
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
                "/usr/bin/microsoft-edge-beta",
                "/usr/bin/microsoft-edge-dev",
            ]

        # Check if path exists and is executable
        for path in possible_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                paths.append(path)

        return paths

    def find_available_port(self, start_port: int = 9222) -> int:
        """
        Find available port
        """
        port = start_port
        while port < start_port + 100:  # Try up to 100 ports
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('localhost', port))
                    return port
            except OSError:
                port += 1

        raise RuntimeError(f"Cannot find available port, tried {start_port} to {port-1}")

    def launch_browser(self, browser_path: str, debug_port: int, headless: bool = False,
                      user_data_dir: Optional[str] = None) -> subprocess.Popen:
        """
        Launch browser process
        """
        # Basic launch arguments
        args = [
            browser_path,
            f"--remote-debugging-port={debug_port}",
            "--remote-debugging-address=0.0.0.0",  # Allow remote access
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=TranslateUI",
            "--disable-ipc-flooding-protection",
            "--disable-hang-monitor",
            "--disable-prompt-on-repost",
            "--disable-sync",
            "--disable-dev-shm-usage",  # Avoid shared memory issues
            "--no-sandbox",  # Disable sandbox in CDP mode
            "--disable-gpu-sandbox",  # Disable GPU sandbox (needed on servers)
            "--no-zygote",  # Disable zygote (avoids sandbox-related crashes)
            "--disable-crash-reporter",  # Avoid crash report dir permission issues
            "--disable-crashpad",
            # Key anti-detection arguments
            "--disable-blink-features=AutomationControlled",  # Disable automation control flag
            "--exclude-switches=enable-automation",  # Exclude automation switch
            "--disable-infobars",  # Disable info bars
        ]

        # Headless mode
        if headless:
            args.extend([
                "--headless=new",  # Use new headless mode
                "--disable-gpu",
                "--disable-gpu-compositing",  # Avoid GPU process crash on servers without GPU
                "--disable-software-rasterizer",  # Disable software rasterizer
                "--disable-features=VizDisplayCompositor",  # Disable display compositor
            ])
        else:
            # Extra arguments for non-headless mode
            args.extend([
                "--start-maximized",  # Maximize window, more like real user
                "--window-size=1920,1080",  # Explicit window size for Xvfb environments
                # On servers without GPU, must disable GPU even in non-headless mode
                # (Xvfb provides virtual display, but GPU process still fails without real GPU)
                "--disable-gpu",
                "--disable-gpu-compositing",
                "--disable-software-rasterizer",
                "--disable-features=VizDisplayCompositor",
            ])

        # User data directory
        if user_data_dir:
            args.append(f"--user-data-dir={user_data_dir}")
            # 清理残留的 Singleton 锁文件(上次 Chrome 被强杀后会残留,
            # 导致新 Chrome 认为目录被占用而立即退出,端口无法监听)
            self._cleanup_singleton_locks(user_data_dir)

        utils.logger.info(f"[BrowserLauncher] Launching browser: {browser_path}")
        utils.logger.info(f"[BrowserLauncher] Debug port: {debug_port}")
        utils.logger.info(f"[BrowserLauncher] Headless mode: {headless}")

        try:
            # Fix: build a minimal clean environment to avoid IDE sandbox (Trae/VSCode)
            # injecting variables that cause Chrome GPU process to crash
            # (e.g. TRAE_SANDBOX_*, ICUBE_*, VSCODE_*, PYDEVD_*, etc.)
            clean_env = {
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/tmp",
                "DISPLAY": os.environ.get("DISPLAY", ":0"),
                "LD_LIBRARY_PATH": "/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu",
                "LANG": os.environ.get("LANG", "en_US.UTF-8"),
                "TERM": os.environ.get("TERM", "xterm-256color"),
            }
            # Preserve DBUS_SESSION_BUS_ADDRESS if set (needed for some Chrome features)
            if "DBUS_SESSION_BUS_ADDRESS" in os.environ:
                clean_env["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
            utils.logger.info(f"[BrowserLauncher] Using minimal env ({len(clean_env)} vars) to avoid IDE sandbox pollution")

            # On Windows, use CREATE_NEW_PROCESS_GROUP to prevent Ctrl+C from affecting subprocess
            if self.system == "Windows":
                process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=clean_env,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=clean_env,
                    preexec_fn=os.setsid  # Create new process group
                )

            self.browser_process = process
            utils.logger.info(f"[BrowserLauncher] Chrome PID={process.pid}, env vars={len(clean_env)}")
            return process

        except Exception as e:
            utils.logger.error(f"[BrowserLauncher] Failed to launch browser: {e}")
            raise

    def wait_for_browser_ready(self, debug_port: int, timeout: int = 30) -> bool:
        """
        Wait for browser to be ready
        """
        utils.logger.info(f"[BrowserLauncher] Waiting for browser to be ready on port {debug_port}...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    result = s.connect_ex(('localhost', debug_port))
                    if result == 0:
                        utils.logger.info(f"[BrowserLauncher] Browser is ready on port {debug_port}")
                        return True
            except Exception:
                pass

            # 进程已退出则无需继续等待
            if self.browser_process and self.browser_process.poll() is not None:
                utils.logger.error(
                    f"[BrowserLauncher] Browser process exited early (code={self.browser_process.returncode}) "
                    f"before port {debug_port} was ready. Likely caused by stale SingletonLock, "
                    f"corrupted user-data-dir, or missing system libs."
                )
                return False

            time.sleep(0.5)

        utils.logger.error(f"[BrowserLauncher] Browser failed to be ready within {timeout} seconds")
        return False

    def get_browser_info(self, browser_path: str) -> Tuple[str, str]:
        """
        Get browser info (name and version)
        """
        try:
            if "chrome" in browser_path.lower():
                name = "Google Chrome"
            elif "edge" in browser_path.lower() or "msedge" in browser_path.lower():
                name = "Microsoft Edge"
            elif "chromium" in browser_path.lower():
                name = "Chromium"
            else:
                name = "Unknown Browser"

            # Try to get version info
            try:
                ver_env = os.environ.copy()
                ver_env["LD_LIBRARY_PATH"] = "/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu"
                result = subprocess.run([browser_path, "--version"],
                                      capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=5,
                                      env=ver_env)
                version = result.stdout.strip() if result.stdout else "Unknown Version"
            except:
                version = "Unknown Version"

            return name, version

        except Exception:
            return "Unknown Browser", "Unknown Version"

    def _cleanup_singleton_locks(self, user_data_dir: str):
        """
        清理 Chrome user_data_dir 中残留的 Singleton 锁文件。
        当 Chrome 进程被强杀(SIGKILL/崩溃)后,这些锁文件不会自动清除,
        会导致下次 Chrome 启动时认为该 profile 已被占用而立即退出,
        端口无法监听,任务卡在 "Waiting for browser to be ready"。
        """
        if not user_data_dir or not os.path.isdir(user_data_dir):
            return
        lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
        removed = []
        for name in lock_files:
            path = os.path.join(user_data_dir, name)
            if os.path.lexists(path):
                try:
                    os.remove(path)
                    removed.append(name)
                except OSError:
                    pass
        if removed:
            utils.logger.info(f"[BrowserLauncher] Cleaned stale Singleton locks in {user_data_dir}: {removed}")

    def cleanup(self):
        """
        Cleanup resources, close browser process
        """
        if not self.browser_process:
            return

        process = self.browser_process

        if process.poll() is not None:
            utils.logger.info("[BrowserLauncher] Browser process already exited, no cleanup needed")
            self.browser_process = None
            return

        utils.logger.info("[BrowserLauncher] Closing browser process...")

        try:
            if self.system == "Windows":
                # First try normal termination
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    utils.logger.warning("[BrowserLauncher] Normal termination timeout, using taskkill to force kill")
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True,
                        check=False,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    process.wait(timeout=5)
            else:
                pgid = os.getpgid(process.pid)
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    utils.logger.info("[BrowserLauncher] Browser process group does not exist, may have exited")
                else:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        utils.logger.warning("[BrowserLauncher] Graceful shutdown timeout, sending SIGKILL")
                        os.killpg(pgid, signal.SIGKILL)
                        process.wait(timeout=5)

            utils.logger.info("[BrowserLauncher] Browser process closed")
        except Exception as e:
            utils.logger.warning(f"[BrowserLauncher] Error closing browser process: {e}")
        finally:
            self.browser_process = None
