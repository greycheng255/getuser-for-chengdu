import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/getuser/MediaCrawler-main/browser_data/dy_user_data_dir",
            headless=True,
        )
        
        if len(context.pages) > 0:
            page = context.pages[0]
        else:
            page = await context.new_page()
        
        # 先到首页
        print("Step 1: Navigate to homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        
        # 拦截搜索 API
        search_responses = []
        
        async def handle_response(response):
            url = response.url
            if 'search' in url and response.status == 200:
                try:
                    data = await response.json()
                    search_responses.append({
                        'url_short': url.split('?')[0],
                        'status_code': data.get('status_code'),
                        'has_data': bool(data.get('data')),
                    })
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 点击搜索框并输入
        print("Step 2: Search via input...")
        try:
            search_input = page.locator('input[placeholder*="搜索"]').first
            await search_input.click(timeout=5000)
            await asyncio.sleep(1)
            await search_input.fill("gpt image2")
            await asyncio.sleep(1)
            await page.keyboard.press("Enter")
            print("  Search submitted via Enter")
        except Exception as e:
            print(f"  Error: {e}")
        
        await asyncio.sleep(10)
        
        # 检查 URL 是否变化
        current_url = page.url
        print(f"\nCurrent URL: {current_url}")
        
        # 滚动
        for i in range(3):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/3})")
            await asyncio.sleep(2)
        
        print(f"\nSearch API responses: {len(search_responses)}")
        for resp in search_responses:
            print(f"  {resp}")
        
        # 如果没有搜索响应，尝试直接导航
        if not any('search/single' in r.get('url_short', '') for r in search_responses):
            print("\nNo search/single API found. Trying direct navigation...")
            search_responses.clear()
            await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(10)
            
            print(f"After navigation - URL: {page.url}")
            print(f"Search API responses: {len(search_responses)}")
            for resp in search_responses:
                print(f"  {resp}")
        
        await context.close()

asyncio.run(main())
