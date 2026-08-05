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
        
        # 检查 window.bdms 的完整结构
        structure = await page.evaluate("""
            () => {
                if (!window.bdms) return {error: "no bdms"};
                const bdms = window.bdms;
                return {
                    bdms_keys: Object.keys(bdms),
                    init_type: typeof bdms.init,
                    init_string: bdms.init.toString().slice(0, 200),
                };
            }
        """)
        print(f"Structure: {structure}")
        
        # 尝试不同的调用方式
        # 方式1: 直接调用 init 函数
        try:
            result1 = await page.evaluate("""
                () => {
                    try {
                        return window.bdms.init(0, 1, 8, "test=params", "", "Mozilla/5.0");
                    } catch(e) {
                        return "Error: " + e.message;
                    }
                }
            """)
            print(f"Method 1 (direct call): {result1[:50] if isinstance(result1, str) and len(result1) > 50 else result1}")
        except Exception as e:
            print(f"Method 1 error: {e}")
        
        # 方式2: 检查 bdms 的其他属性
        other_methods = await page.evaluate("""
            () => {
                const bdms = window.bdms;
                const methods = {};
                for (const key of Object.keys(bdms)) {
                    methods[key] = typeof bdms[key];
                }
                return methods;
            }
        """)
        print(f"Other methods: {other_methods}")
        
        await browser.close()

asyncio.run(main())
