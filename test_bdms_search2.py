import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # 拦截所有请求，查找包含 a_bogus 的请求
        requests_with_abogus = []
        def handle_route(route, request):
            url = request.url
            if 'a_bogus' in url:
                requests_with_abogus.append({
                    'url': url[:300],
                    'abogus': url.split('a_bogus=')[1].split('&')[0][:50] if 'a_bogus=' in url else None
                })
            asyncio.create_task(route.continue_())
        
        await page.route("**/*", handle_route)
        
        # 直接访问搜索页面（不需要点击搜索框）
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=video", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(10)
        
        # 滚动页面加载更多
        for i in range(3):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(3)
        
        print(f"Requests with a_bogus: {len(requests_with_abogus)}")
        for req in requests_with_abogus[:5]:
            print(f"URL: {req['url'][:150]}")
            print(f"a_bogus: {req['abogus']}")
            print()
        
        # 检查页面上的 window.bdms
        bdms_info = await page.evaluate("""
            () => {
                if (!window.bdms) return {error: "no bdms"};
                return {
                    keys: Object.keys(window.bdms),
                    init_exists: typeof window.bdms.init !== 'undefined',
                };
            }
        """)
        print(f"BDMS info: {bdms_info}")
        
        await browser.close()

asyncio.run(main())
