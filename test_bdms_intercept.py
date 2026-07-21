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
        
        # 拦截搜索响应 - 更宽泛的匹配
        search_responses = []
        all_api_responses = []
        
        async def handle_response(response):
            url = response.url
            if response.status == 200 and 'aweme' in url:
                try:
                    data = await response.json()
                    all_api_responses.append({
                        'url': url[:200],
                        'status_code': data.get('status_code'),
                    })
                    if 'search' in url and 'single' in url:
                        search_responses.append({
                            'url': url[:200],
                            'status_code': data.get('status_code'),
                            'has_data': bool(data.get('data')),
                            'data_len': len(data.get('data', [])),
                        })
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 导航到搜索页面
        print("Navigating to Douyin search page...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(10)
        
        title = await page.title()
        print(f"Search page title: {title}")
        
        # 滚动加载更多
        for i in range(5):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
            await asyncio.sleep(3)
        
        print(f"\nAll API responses: {len(all_api_responses)}")
        for resp in all_api_responses[:10]:
            print(f"  {resp}")
        
        print(f"\nSearch-specific responses: {len(search_responses)}")
        for resp in search_responses[:5]:
            print(f"  {resp}")
        
        # 检查页面内容 - 是否有搜索结果
        page_content = await page.evaluate("""
            () => {
                const items = document.querySelectorAll('[class*="search-result"], [class*="video-card"], [class*="aweme"]');
                return {
                    item_count: items.length,
                    body_text_preview: document.body.innerText.substring(0, 500),
                };
            }
        """)
        print(f"\nPage content: items={page_content['item_count']}")
        print(f"Body preview: {page_content['body_text_preview'][:300]}")
        
        await context.close()

asyncio.run(main())
