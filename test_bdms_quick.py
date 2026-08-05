import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/getuser/MediaCrawler-main/browser_data/dy_user_data_dir",
            headless=True,
            viewport={"width": 1920, "height": 1080},
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        # 拦截请求
        async def handle_request(request):
            url = request.url
            if 'search/single' in url:
                print(f"  [REQ] search/single")
        
        page.on("request", handle_request)
        
        # 导航
        print("Navigating...")
        try:
            resp = await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", timeout=15000)
            print(f"  Response status: {resp.status if resp else 'None'}")
        except Exception as e:
            print(f"  Error: {e}")
        
        await asyncio.sleep(8)
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(5)
        
        info = await page.evaluate("() => ({url: location.href, title: document.title, imgs: document.querySelectorAll('img').length})")
        print(f"Page: {info}")
        
        await context.close()

asyncio.run(main())
