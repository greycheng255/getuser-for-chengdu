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
        search_single_found = False
        
        async def handle_request(request):
            nonlocal search_single_found
            url = request.url
            if 'search/single' in url:
                search_single_found = True
                print(f"  [REQ] search/single found!")
        
        page.on("request", handle_request)
        
        # 导航到搜索页面
        print("Navigating to search page...")
        try:
            await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="domcontentloaded", timeout=15000)
        except:
            print("  Navigation timeout")
        
        # 等待
        await asyncio.sleep(10)
        
        # 滚动
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(3)
        
        print(f"Search/single found: {search_single_found}")
        
        # 检查页面
        page_info = await page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                img_count: document.querySelectorAll('img').length,
                body_len: document.body.innerText.length,
            })
        """)
        print(f"Page: url={page_info['url']}, title={page_info['title']}, imgs={page_info['img_count']}, body_len={page_info['body_len']}")
        
        await context.close()

asyncio.run(main())
