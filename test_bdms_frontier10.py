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
        search_single_responses = []
        
        async def handle_response(response):
            url = response.url
            if 'search/single' in url:
                try:
                    data = await response.json()
                    search_single_responses.append({
                        'status_code': data.get('status_code'),
                        'has_data': bool(data.get('data')),
                    })
                    print(f"  [SEARCH/SINGLE] status_code={data.get('status_code')}")
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 直接导航到搜索页面（不是 jingxuan）
        print("Navigating to search page (www.douyin.com/search/...)...")
        await page.goto("https://www.douyin.com/search/gpt%20image2", wait_until="domcontentloaded", timeout=30000)
        
        # 等待搜索结果
        for i in range(10):
            await asyncio.sleep(3)
            if search_single_responses:
                break
        
        print(f"\nSearch/single responses: {len(search_single_responses)}")
        for resp in search_single_responses:
            print(f"  {resp}")
        
        # 检查页面
        page_info = await page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                img_count: document.querySelectorAll('img').length,
                body_len: document.body.innerText.length,
                body_preview: document.body.innerText.substring(0, 500),
            })
        """)
        print(f"\nPage: url={page_info['url']}, title={page_info['title']}, imgs={page_info['img_count']}")
        print(f"Body: {page_info['body_preview'][:300]}")
        
        await context.close()

asyncio.run(main())
