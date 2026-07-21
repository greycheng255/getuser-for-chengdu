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
        print("Step 1: Homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)
        
        # 拦截所有请求
        print("\nStep 2: Intercepting all requests...")
        
        search_requests = []
        all_aweme_requests = []
        
        async def handle_request(request):
            url = request.url
            if 'search/single' in url:
                search_requests.append(url[:500])
                print(f"  [SEARCH/SINGLE REQUEST] {url[:200]}")
            elif 'aweme/v1/web' in url and 'search' not in url:
                all_aweme_requests.append(url.split('?')[0])
        
        page.on("request", handle_request)
        
        # 导航到搜索页面
        print("Navigating to search page...")
        try:
            await page.goto("https://www.douyin.com/search/gpt%20image2", wait_until="domcontentloaded", timeout=15000)
        except:
            print("  Navigation timeout")
        
        await asyncio.sleep(20)
        
        print(f"\nSearch/single requests: {len(search_requests)}")
        print(f"Other aweme requests: {len(all_aweme_requests)}")
        for url in all_aweme_requests[:10]:
            print(f"  {url}")
        
        # 检查页面状态
        try:
            page_info = await page.evaluate("""
                () => ({
                    url: window.location.href,
                    title: document.title,
                    img_count: document.querySelectorAll('img').length,
                    body_len: document.body.innerText.length,
                })
            """)
            print(f"\nPage: url={page_info['url']}, title={page_info['title']}, imgs={page_info['img_count']}, body_len={page_info['body_len']}")
        except:
            print("Could not evaluate page")
        
        await context.close()

asyncio.run(main())
