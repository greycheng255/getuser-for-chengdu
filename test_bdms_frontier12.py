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
        
        # 拦截搜索 API
        search_single_found = False
        
        async def handle_response(response):
            nonlocal search_single_found
            url = response.url
            if 'search/single' in url:
                search_single_found = True
                try:
                    data = await response.json()
                    print(f"  [SEARCH/SINGLE] status_code={data.get('status_code')}, has_data={bool(data.get('data'))}")
                except:
                    print(f"  [SEARCH/SINGLE] json parse error")
        
        page.on("response", handle_response)
        
        # 导航到搜索页面
        print("Navigating to search page...")
        try:
            await page.goto("https://www.douyin.com/search/gpt%20image2", wait_until="domcontentloaded", timeout=20000)
        except:
            print("  Navigation timeout, continuing...")
        
        # 等待
        await asyncio.sleep(20)
        
        # 滚动
        try:
            await page.evaluate("window.scrollTo(0, 500)")
        except:
            pass
        await asyncio.sleep(5)
        
        print(f"\nSearch/single found: {search_single_found}")
        
        # 检查页面
        try:
            page_info = await page.evaluate("""
                () => ({
                    url: window.location.href,
                    title: document.title,
                    img_count: document.querySelectorAll('img').length,
                    body_len: document.body.innerText.length,
                    body_preview: document.body.innerText.substring(0, 300),
                })
            """)
            print(f"Page: url={page_info['url']}, title={page_info['title']}, imgs={page_info['img_count']}")
            print(f"Body: {page_info['body_preview'][:200]}")
        except:
            print("Could not evaluate page")
        
        await context.close()

asyncio.run(main())
