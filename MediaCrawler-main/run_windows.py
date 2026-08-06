# -*- coding: utf-8 -*-
"""Windows 启动入口: 确保使用 ProactorEventLoop
ProactorEventLoop 支持 create_subprocess_exec() (Playwright 依赖)。
uvicorn --reload 在 Windows 上会切换到 SelectorEventLoop (不支持子进程)，
因此禁用 reload 模式。
"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    print("[launcher] ProactorEventLoop set for subprocess support")

import uvicorn

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)
