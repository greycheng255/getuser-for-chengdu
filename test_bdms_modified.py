import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # 监听 console 日志
        console_logs = []
        def handle_console(msg):
            text = msg.text
            if 'Q_CALL' in text:
                console_logs.append(text)
            print(f"[Console] {text[:200]}")
        
        page.on("console", handle_console)
        
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        # 读取修改后的 bdms.js 并注入
        with open('/tmp/bdms_modified.js', 'r') as f:
            js_content = f.read()
        
        await page.add_script_tag(content=js_content)
        await asyncio.sleep(5)
        
        # 调用 init 函数
        result = await page.evaluate("""
            () => {
                try {
                    return window.bdms.init(0, 1, 8, "test=params", "", "Mozilla/5.0");
                } catch(e) {
                    return 'Error: ' + e.message;
                }
            }
        """)
        print(f"\nInit result: {result}")
        
        # 检查 console 日志
        print(f"\nQ_CALL logs ({len(console_logs)}):")
        for log in console_logs:
            print(log)
        
        await browser.close()

asyncio.run(main())
