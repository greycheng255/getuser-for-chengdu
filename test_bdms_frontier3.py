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
        
        # 拦截所有 API 响应
        all_api_data = []
        
        async def handle_response(response):
            url = response.url
            if response.status == 200 and 'aweme' in url:
                try:
                    data = await response.json()
                    all_api_data.append({
                        'url': url[:200],
                        'status_code': data.get('status_code'),
                        'has_data': bool(data.get('data')),
                    })
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 导航到首页
        print("Step 1: Navigate to homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        
        # 检查首页是否有内容加载
        home_info = await page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                body_len: document.body.innerText.length,
                body_preview: document.body.innerText.substring(0, 300),
            })
        """)
        print(f"Homepage: url={home_info['url']}, title={home_info['title']}, body_len={home_info['body_len']}")
        print(f"Body preview: {home_info['body_preview'][:200]}")
        
        # 在首页搜索
        print("\nStep 2: Search from homepage...")
        try:
            search_input = page.locator('input[placeholder*="搜索"]').first
            await search_input.click(timeout=5000)
            await asyncio.sleep(1)
            await search_input.fill("gpt image2")
            await asyncio.sleep(1)
            await page.keyboard.press("Enter")
            print("Search submitted!")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"Search error: {e}")
        
        # 检查当前页面
        current_info = await page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                body_len: document.body.innerText.length,
            })
        """)
        print(f"\nCurrent page: url={current_info['url']}, title={current_info['title']}, body_len={current_info['body_len']}")
        
        # 滚动
        for i in range(5):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
            await asyncio.sleep(2)
        
        print(f"\nAll API responses: {len(all_api_data)}")
        for resp in all_api_data[:10]:
            print(f"  {resp}")
        
        await context.close()

asyncio.run(main())
