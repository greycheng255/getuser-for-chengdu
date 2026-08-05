import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/getuser/MediaCrawler-main/browser_data/dy_user_data_dir",
            headless=True,
            viewport={"width": 1920, "height": 1080},
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        # 拦截请求
        search_single_reqs = []
        
        async def handle_request(request):
            url = request.url
            if 'search/single' in url:
                search_single_reqs.append(url[:200])
                print(f"  [REQ] search/single found!")
        
        page.on("request", handle_request)
        
        # 导航到搜索页面
        print("Navigating to search page...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", timeout=15000)
        
        # 等待足够时间让页面完全加载
        print("Waiting for page to load...")
        await asyncio.sleep(20)
        
        # 滚动
        print("Scrolling...")
        await page.evaluate("window.scrollTo(0, 800)")
        await asyncio.sleep(5)
        await page.evaluate("window.scrollTo(0, 1600)")
        await asyncio.sleep(5)
        
        print(f"\nSearch/single requests: {len(search_single_reqs)}")
        
        # 检查页面
        info = await page.evaluate("""
            () => {
                return {
                    url: location.href,
                    title: document.title,
                    imgs: document.querySelectorAll('img').length,
                    body_len: document.body.innerText.length,
                    body: document.body.innerText.substring(0, 300),
                    has_search_input: !!document.querySelector('input'),
                    input_count: document.querySelectorAll('input').length,
                };
            }
        """)
        print(f"Page info: url={info['url']}, title={info['title']}")
        print(f"Imgs: {info['imgs']}, inputs: {info['input_count']}, body_len: {info['body_len']}")
        print(f"Body: {info['body'][:200]}")
        
        await context.close()

asyncio.run(main())
