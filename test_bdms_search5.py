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
        
        # 拦截所有搜索相关响应
        search_responses = []
        
        async def handle_response(response):
            url = response.url
            if response.status == 200 and ('search' in url or 'general/search' in url):
                try:
                    data = await response.json()
                    search_responses.append({
                        'url': url[:300],
                        'status_code': data.get('status_code'),
                        'has_data': bool(data.get('data')),
                    })
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 先导航到首页
        print("Step 1: Navigate to homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(8)
        
        # 在搜索框中输入并搜索
        print("Step 2: Click search box and type...")
        try:
            # 使用更精确的选择器
            search_input = page.locator('input[placeholder*="搜索"]').first
            await search_input.click(timeout=5000)
            await asyncio.sleep(1)
            
            # 清空并输入关键词
            await search_input.fill("")
            await search_input.type("gpt image2", delay=50)
            await asyncio.sleep(1)
            
            # 按 Enter 搜索
            await page.keyboard.press("Enter")
            print("Step 3: Search submitted, waiting for results...")
            await asyncio.sleep(15)
            
            # 检查当前 URL
            current_url = page.url
            print(f"Current URL: {current_url}")
            
            # 滚动加载更多
            for i in range(5):
                await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
                await asyncio.sleep(3)
            
        except Exception as e:
            print(f"Search error: {e}")
        
        print(f"\nSearch responses: {len(search_responses)}")
        for resp in search_responses[:10]:
            print(f"  {resp}")
        
        # 检查页面内容
        page_info = await page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                body_len: document.body.innerText.length,
                body_preview: document.body.innerText.substring(0, 800),
            })
        """)
        print(f"\nPage URL: {page_info['url']}")
        print(f"Page title: {page_info['title']}")
        print(f"Body preview: {page_info['body_preview']}")
        
        await context.close()

asyncio.run(main())
