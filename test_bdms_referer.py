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
        
        # 测试 getReferer
        referer = await page.evaluate("""
            () => {
                try {
                    return window.bdms.getReferer();
                } catch(e) {
                    return 'Error: ' + e.message;
                }
            }
        """)
        print(f"getReferer(): {referer}")
        
        # 尝试获取 bdms.js 的内部状态
        state = await page.evaluate("""
            () => {
                // 尝试通过 prototype chain 或属性描述符来获取内部状态
                const init = window.bdms.init;
                const descriptors = Object.getOwnPropertyDescriptors(window.bdms);
                return {
                    descriptors_keys: Object.keys(descriptors),
                };
            }
        """)
        print(f"State: {state}")
        
        # 尝试在页面中触发一个实际的请求，看看 bdms.init 是否会被调用
        # 通过修改 fetch 来拦截
        await page.evaluate("""
            () => {
                window._abogus_generated = null;
                const originalFetch = window.fetch;
                window.fetch = function(...args) {
                    const url = args[0];
                    if (typeof url === 'string' && url.includes('a_bogus')) {
                        window._abogus_generated = url.split('a_bogus=')[1].split('&')[0];
                    }
                    return originalFetch.apply(this, args);
                };
            }
        """)
        
        # 尝试通过页面上的搜索按钮触发请求
        try:
            await page.goto("https://www.douyin.com/search/gpt%20image2?type=video", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(10)
        except Exception as e:
            print(f"Navigation error: {e}")
        
        abogus = await page.evaluate("() => window._abogus_generated")
        print(f"a_bogus from page fetch: {abogus}")
        
        await browser.close()

asyncio.run(main())
