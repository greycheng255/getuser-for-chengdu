import asyncio
from playwright.async_api import async_playwright

async def main():
    urls = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        def handle_route(route, request):
            url = request.url
            if 'bdms' in url.lower() or 'sign' in url.lower():
                print(f"FOUND: {url}")
            urls.append(url)
            asyncio.create_task(route.continue_())
        
        await page.route("**/*", handle_route)
        
        try:
            await page.goto("https://www.douyin.com", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Error: {e}")
        
        # 检查 window.bdms
        has_bdms = await page.evaluate("() => typeof window.bdms !== 'undefined'")
        print(f"window.bdms exists: {has_bdms}")
        
        # 检查 window 下是否有 sign 相关的对象
        sign_objs = await page.evaluate("""
            () => {
                const keys = Object.keys(window);
                return keys.filter(k => k.toLowerCase().includes('sign') || k.toLowerCase().includes('bogus') || k.toLowerCase().includes('bdms'));
            }
        """)
        print(f"Sign-related objects: {sign_objs}")
        
        await browser.close()
        
        # 打印所有包含 bdms 的 URL
        bdms_urls = [u for u in urls if 'bdms' in u.lower()]
        print(f"\nAll bdms URLs: {bdms_urls}")

asyncio.run(main())
