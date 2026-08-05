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
        
        # 拦截搜索响应
        search_responses = []
        
        async def handle_response(response):
            url = response.url
            if response.status == 200 and ('search/single' in url or 'search/item' in url):
                try:
                    data = await response.json()
                    search_responses.append({
                        'url': url[:300],
                        'status_code': data.get('status_code'),
                        'has_data': bool(data.get('data')),
                        'data_len': len(data.get('data', [])),
                    })
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 先导航到首页
        print("Navigating to Douyin homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        
        # 在首页找到搜索框并搜索
        print("Finding search box...")
        try:
            # 尝试多种选择器
            selectors = [
                'input[placeholder*="搜索"]',
                'input[type="text"]',
                '[class*="search-input"]',
                'input[data-e2e="search-input"]',
            ]
            
            search_input = None
            for selector in selectors:
                try:
                    element = page.locator(selector).first
                    if await element.is_visible(timeout=2000):
                        search_input = element
                        print(f"Found search input with selector: {selector}")
                        break
                except:
                    continue
            
            if search_input:
                await search_input.click()
                await asyncio.sleep(1)
                await search_input.fill("gpt image2")
                await asyncio.sleep(1)
                await page.keyboard.press("Enter")
                print("Search submitted, waiting for results...")
                await asyncio.sleep(10)
            else:
                print("Search input not found, trying direct navigation...")
                await page.goto("https://www.douyin.com/search/gpt%20image2", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(10)
        except Exception as e:
            print(f"Search interaction error: {e}")
            await page.goto("https://www.douyin.com/search/gpt%20image2", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(10)
        
        # 滚动加载更多
        for i in range(5):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
            await asyncio.sleep(3)
        
        print(f"\nSearch responses: {len(search_responses)}")
        for resp in search_responses[:5]:
            print(f"  {resp}")
        
        # 检查页面内容
        page_info = await page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                body_len: document.body.innerText.length,
                body_preview: document.body.innerText.substring(0, 500),
            })
        """)
        print(f"\nPage URL: {page_info['url']}")
        print(f"Page title: {page_info['title']}")
        print(f"Body length: {page_info['body_len']}")
        print(f"Body preview: {page_info['body_preview'][:300]}")
        
        await context.close()

asyncio.run(main())
