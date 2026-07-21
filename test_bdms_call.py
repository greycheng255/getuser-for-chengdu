import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        # 注入 bdms.js
        js_url = "https://lf-c-flwb.bytetos.com/obj/rc-client-security/web/stable/1.0.1.18/bdms.js"
        await page.add_script_tag(url=js_url)
        await asyncio.sleep(3)
        
        # 尝试不同的调用方式
        test_cases = [
            # 方式1: 直接调用，绑定到 window
            "window.bdms.init.call(window, 0, 1, 8, 'test=params', '', 'Mozilla/5.0')",
            # 方式2: 直接调用，不绑定
            "window.bdms.init(0, 1, 8, 'test=params', '', 'Mozilla/5.0')",
            # 方式3: 使用 apply
            "window.bdms.init.apply(null, [0, 1, 8, 'test=params', '', 'Mozilla/5.0'])",
            # 方式4: 传入对象
            "window.bdms.init({0: 0, 1: 1, 2: 8, 3: 'test=params', 4: '', 5: 'Mozilla/5.0'})",
            # 方式5: 不传入任何参数
            "window.bdms.init()",
            # 方式6: 传入字符串
            "window.bdms.init('test=params')",
            # 方式7: 传入数字
            "window.bdms.init(0)",
            # 方式8: 传入多个字符串
            "window.bdms.init('test=params', '', 'Mozilla/5.0')",
            # 方式9: 传入数组
            "window.bdms.init([0, 1, 8, 'test=params', '', 'Mozilla/5.0'])",
            # 方式10: 使用 new
            "new window.bdms.init(0, 1, 8, 'test=params', '', 'Mozilla/5.0')",
        ]
        
        for i, code in enumerate(test_cases):
            try:
                result = await page.evaluate(f"""
                    () => {{
                        try {{
                            return {code};
                        }} catch(e) {{
                            return 'Error: ' + e.message;
                        }}
                    }}
                """)
                print(f"Test {i+1}: {result if result is None else str(result)[:50]}")
            except Exception as e:
                print(f"Test {i+1} error: {e}")
        
        # 尝试获取 init 函数的内部状态
        init_state = await page.evaluate("""
            () => {
                const init = window.bdms.init;
                return {
                    source: init.toString(),
                    length: init.length,
                    name: init.name,
                    // 尝试获取闭包变量（可能失败）
                    has_r: false,
                    has_e: false,
                };
            }
        """)
        print(f"\nInit state: {init_state}")
        
        await browser.close()

asyncio.run(main())
