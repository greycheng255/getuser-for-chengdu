import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        # 先拦截 fetch，记录请求
        requests = []
        await page.evaluate("""
            () => {
                window._captured_requests = [];
                const originalFetch = window.fetch;
                window.fetch = function(url, options) {
                    window._captured_requests.push({url: String(url).slice(0, 200), time: Date.now()});
                    return originalFetch.apply(this, arguments);
                };
            }
        """)
        
        # 注入 bdms.js
        js_url = "https://lf-c-flwb.bytetos.com/obj/rc-client-security/web/stable/1.0.1.18/bdms.js"
        await page.add_script_tag(url=js_url)
        await asyncio.sleep(5)
        
        # 检查是否有请求被拦截
        captured = await page.evaluate("() => window._captured_requests")
        print(f"Captured requests after bdms.js injection: {len(captured)}")
        for req in captured[:5]:
            print(f"  {req['url']}")
        
        # 尝试手动触发一个 fetch 请求，看看 bdms.js 是否会自动添加 a_bogus
        await page.evaluate("""
            () => {
                window._test_request_url = null;
                fetch("https://www.douyin.com/aweme/v1/web/search/item/?keyword=test&search_source=normal_search")
                    .then(r => r.text())
                    .then(t => { window._test_response = t.slice(0, 100); })
                    .catch(e => { window._test_response = 'Error: ' + e.message; });
            }
        """)
        await asyncio.sleep(3)
        
        test_response = await page.evaluate("() => window._test_response")
        print(f"Test response: {test_response}")
        
        # 检查最新的请求
        captured = await page.evaluate("() => window._captured_requests")
        print(f"Total captured requests: {len(captured)}")
        for req in captured[-5:]:
            print(f"  {req['url']}")
        
        # 检查 window.bdms 是否有其他隐藏方法
        hidden = await page.evaluate("""
            () => {
                const bdms = window.bdms;
                const props = [];
                for (let key in bdms) {
                    props.push({key: key, type: typeof bdms[key]});
                }
                // 检查原型链
                let proto = Object.getPrototypeOf(bdms);
                while (proto) {
                    for (let key of Object.getOwnPropertyNames(proto)) {
                        props.push({key: key, type: typeof proto[key], proto: true});
                    }
                    proto = Object.getPrototypeOf(proto);
                }
                return props;
            }
        """)
        print(f"All properties: {hidden}")
        
        await browser.close()

asyncio.run(main())
