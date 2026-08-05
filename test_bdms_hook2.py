import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        # 在注入 bdms.js 之前设置 hook
        await page.evaluate("""
            () => {
                // 拦截 window.bdms 的赋值
                let captured = null;
                Object.defineProperty(window, 'bdms', {
                    get: function() { return captured; },
                    set: function(value) {
                        captured = value;
                        console.log('BDMS set:', Object.keys(value));
                        // 记录 init 函数的源码
                        if (value && value.init) {
                            console.log('INIT source:', value.init.toString());
                        }
                    },
                    configurable: true
                });
            }
        """)
        
        # 注入 bdms.js
        js_url = "https://lf-c-flwb.bytetos.com/obj/rc-client-security/web/stable/1.0.1.18/bdms.js"
        await page.add_script_tag(url=js_url)
        await asyncio.sleep(5)
        
        # 检查 hook 是否捕获到了 bdms
        bdms_info = await page.evaluate("""
            () => {
                if (!window.bdms) return {error: "no bdms"};
                const init = window.bdms.init;
                return {
                    keys: Object.keys(window.bdms),
                    init_source: init.toString(),
                    // 尝试获取 init 内部的变量
                    init_length: init.length,
                    init_name: init.name,
                };
            }
        """)
        print(f"BDMS info: {bdms_info}")
        
        # 尝试调用 init 并获取返回值
        for test_args in [
            [0, 1, 8, "test=params", "", "Mozilla/5.0"],
            [{"0": 0, "1": 1, "2": 8, "3": "test=params", "4": "", "5": "Mozilla/5.0"}],
            ["test=params", "", "Mozilla/5.0"],
        ]:
            result = await page.evaluate(
                "(args) => { try { return window.bdms.init.apply(null, args); } catch(e) { return 'Error: ' + e.message; } }",
                test_args
            )
            print(f"Test args {test_args}: {result}")
        
        # 尝试获取 console 日志
        logs = await page.evaluate("""
            () => {
                // 获取浏览器的 console 日志（如果之前有捕获的话）
                return window._bdms_console_logs || [];
            }
        """)
        print(f"Console logs: {logs}")
        
        await browser.close()

asyncio.run(main())
