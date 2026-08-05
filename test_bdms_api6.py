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
        search_single_responses = []
        
        async def handle_request(request):
            url = request.url
            if 'search/single' in url:
                search_single_requests.append(url[:500])
                print(f"  [REQ] search/single a_bogus={'a_bogus' in url}")
        
        async def handle_response(response):
            url = response.url
            if 'search/single' in url and response.status == 200:
                try:
                    data = await response.json()
                    search_single_responses.append({
                        'status_code': data.get('status_code'),
                        'has_data': bool(data.get('data')),
                    })
                    print(f"  [RESP] search/single status_code={data.get('status_code')}")
                except:
                    pass
        
        page.on("request", handle_request)
        page.on("response", handle_response)
        
        # 直接导航到搜索页面（带 type=general）
        print("Navigating to search page with type=general...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(15)
        
        # 滚动
        for i in range(5):
            await page.evaluate(f"window.scrollTo(0, {(i+1) * 800})")
            await asyncio.sleep(3)
        
        print(f"\nSearch/single requests: {len(search_single_requests)}")
        print(f"Search/single responses: {len(search_single_responses)}")
        
        # 检查页面
        page_info = await page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                img_count: document.querySelectorAll('img').length,
                body_len: document.body.innerText.length,
                body_preview: document.body.innerText.substring(0, 500),
                all_div_classes: [...new Set([...document.querySelectorAll('div[class]')].map(d => d.className).filter(c => c.length < 50))].slice(0, 30),
            })
        """)
        print(f"\nPage: url={page_info['url']}, title={page_info['title']}")
        print(f"Imgs: {page_info['img_count']}, Body len: {page_info['body_len']}")
        print(f"Div classes: {page_info['all_div_classes']}")
        print(f"Body: {page_info['body_preview'][:300]}")
        
        await context.close()

asyncio.run(main())
