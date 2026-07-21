import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/getuser/MediaCrawler-main/browser_data/dy_user_data_dir",
            headless=True,
            viewport={"width": 1920, "height": 1080},
        )
        
        if len(context.pages) > 0:
            page = context.pages[0]
        else:
            page = await context.new_page()
        
        # 拦截请求
        search_single_requests = []
        
        async def handle_request(request):
            url = request.url
            if 'search/single' in url or ('search' in url and 'aweme' in url and 'hot' not in url):
                search_single_requests.append({
                    'url': url[:500],
                    'has_a_bogus': 'a_bogus' in url,
                })
                print(f"  [REQ] {url.split('?')[0]} a_bogus={'a_bogus' in url}")
        
        page.on("request", handle_request)
        
        # 先到首页
        print("Step 1: Homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)
        
        # 在首页搜索
        print("\nStep 2: Search from homepage...")
        try:
            # 点击搜索框
            search_btn = page.locator('[class*="search"]').first
            await search_btn.click(timeout=5000)
            await asyncio.sleep(2)
            
            # 输入搜索词
            search_input = page.locator('input[type="text"], input[placeholder*="搜索"]').first
            await search_input.fill("gpt image2")
            await asyncio.sleep(1)
            await page.keyboard.press("Enter")
            print("  Search submitted!")
        except Exception as e:
            print(f"  Search error: {e}")
        
        # 等待页面跳转
        await asyncio.sleep(15)
        
        # 检查当前 URL
        print(f"\nCurrent URL: {page.url}")
        
        # 滚动
        for i in range(10):
            await page.evaluate(f"window.scrollTo(0, {(i+1) * 500})")
            await asyncio.sleep(2)
        
        print(f"\nSearch/single requests: {len(search_single_requests)}")
        for req in search_single_requests:
            print(f"  {req}")
        
        # 截图
        await page.screenshot(path="/tmp/douyin_search.png")
        print("\nScreenshot saved to /tmp/douyin_search.png")
        
        # 检查页面
        page_info = await page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                img_count: document.querySelectorAll('img').length,
                body_len: document.body.innerText.length,
                body_preview: document.body.innerText.substring(0, 500),
                has_search_input: !!document.querySelector('input[placeholder*="搜索"]'),
                search_input_value: document.querySelector('input[placeholder*="搜索"]')?.value,
            })
        """)
        print(f"\nPage: url={page_info['url']}, title={page_info['title']}")
        print(f"Has search input: {page_info['has_search_input']}, value: {page_info['search_input_value']}")
        print(f"Imgs: {page_info['img_count']}, Body len: {page_info['body_len']}")
        print(f"Body: {page_info['body_preview'][:300]}")
        
        await context.close()

asyncio.run(main())
