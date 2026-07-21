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
        
        # 拦截搜索 API 响应
        search_responses = []
        
        async def handle_response(response):
            url = response.url
            if 'search' in url and response.status == 200:
                try:
                    data = await response.json()
                    search_responses.append({
                        'url': url[:300],
                        'status_code': data.get('status_code'),
                        'has_data': bool(data.get('data')),
                        'data_len': len(data.get('data', [])) if isinstance(data.get('data'), list) else 'not_list',
                    })
                except:
                    search_responses.append({
                        'url': url[:300],
                        'error': 'json_parse_error',
                    })
        
        page.on("response", handle_response)
        
        # 直接导航到搜索页面
        print("Navigating to search page directly...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(10)
        
        # 滚动加载
        for i in range(5):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
            await asyncio.sleep(3)
        
        print(f"\nSearch API responses: {len(search_responses)}")
        for resp in search_responses:
            print(f"  {resp}")
        
        # 检查页面是否有视频卡片
        video_count = await page.evaluate("""
            () => {
                const cards = document.querySelectorAll('[class*="video"], [class*="aweme"], [class*="search-result"], [class*="card"]');
                return {
                    video_cards: cards.length,
                    all_classes: [...new Set([...document.querySelectorAll('div[class]')].map(d => d.className).filter(c => c.includes('search') || c.includes('video') || c.includes('card')))].slice(0, 20),
                };
            }
        """)
        print(f"\nVideo elements: {video_count}")
        
        await context.close()

asyncio.run(main())
