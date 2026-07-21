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
        
        # 拦截所有 XHR 请求，看抖音自己发请求时用了什么参数
        print("\nStep 2: Navigate to search page and intercept requests...")
        
        intercepted_search = []
        
        async def handle_request(request):
            url = request.url
            if 'search/single' in url:
                intercepted_search.append({
                    'url': url[:500],
                    'headers': dict(request.headers),
                    'method': request.method,
                })
                print(f"  [REQUEST] search/single found!")
                print(f"    URL params: {url.split('?')[1][:200] if '?' in url else 'none'}")
                # 检查是否有 a_bogus 或 X-Bogus
                if 'a_bogus' in url:
                    print(f"    Has a_bogus!")
                if 'X-Bogus' in url:
                    print(f"    Has X-Bogus!")
                if 'msToken' in url:
                    print(f"    Has msToken!")
        
        page.on("request", handle_request)
        
        # 导航到搜索页面
        await page.goto("https://www.douyin.com/search/gpt%20image2", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(15)
        
        # 滚动
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(5)
        await page.evaluate("window.scrollTo(0, 1000)")
        await asyncio.sleep(5)
        
        print(f"\nIntercepted search/single requests: {len(intercepted_search)}")
        for req in intercepted_search:
            print(f"  Method: {req['method']}")
            print(f"  URL: {req['url'][:300]}")
            # 打印关键 headers
            for key in ['cookie', 'referer', 'user-agent', 'accept']:
                if key in req['headers']:
                    print(f"  {key}: {req['headers'][key][:100]}")
        
        await context.close()

asyncio.run(main())
