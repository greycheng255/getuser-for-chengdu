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
        
        # 拦截所有请求和响应
        search_requests = []
        search_responses = []
        
        async def handle_request(request):
            url = request.url
            if 'search' in url and 'aweme' in url:
                search_requests.append({
                    'url': url[:500],
                    'method': request.method,
                    'has_a_bogus': 'a_bogus' in url,
                    'has_X_Bogus': 'X-Bogus' in url,
                    'has_msToken': 'msToken' in url,
                })
        
        async def handle_response(response):
            url = response.url
            if 'search' in url and 'aweme' in url and response.status == 200:
                try:
                    data = await response.json()
                    search_responses.append({
                        'url': url[:300],
                        'status_code': data.get('status_code'),
                        'has_data': bool(data.get('data')),
                    })
                except:
                    pass
        
        page.on("request", handle_request)
        page.on("response", handle_response)
        
        # 直接导航到搜索页面
        print("Navigating to search page...")
        try:
            await page.goto("https://www.douyin.com/search/gpt%20image2", wait_until="domcontentloaded", timeout=15000)
        except:
            print("  Navigation timeout")
        
        await asyncio.sleep(10)
        
        # 滚动多次
        for i in range(10):
            await page.evaluate(f"window.scrollTo(0, {(i+1) * 500})")
            await asyncio.sleep(2)
        
        print(f"\nSearch requests: {len(search_requests)}")
        for req in search_requests:
            print(f"  {req}")
        
        print(f"\nSearch responses: {len(search_responses)}")
        for resp in search_responses:
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
