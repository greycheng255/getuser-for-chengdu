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
        
        # 拦截所有包含 search/single 的请求
        search_single_responses = []
        
        async def handle_response(response):
            url = response.url
            if 'search/single' in url:
                try:
                    data = await response.json()
                    search_single_responses.append({
                        'url': url[:400],
                        'status_code': data.get('status_code'),
                        'has_data': bool(data.get('data')),
                    })
                    print(f"  [SEARCH/SINGLE] status_code={data.get('status_code')}, has_data={bool(data.get('data'))}")
                except:
                    search_single_responses.append({'url': url[:400], 'error': True})
        
        page.on("response", handle_response)
        
        # 先到首页
        print("Step 1: Homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        
        # 在首页搜索
        print("Step 2: Search from homepage...")
        try:
            search_input = page.locator('input[placeholder*="搜索"]').first
            await search_input.click(timeout=5000)
            await asyncio.sleep(1)
            await search_input.fill("gpt image2")
            await asyncio.sleep(1)
            await page.keyboard.press("Enter")
            print("  Search submitted!")
        except Exception as e:
            print(f"  Error: {e}")
        
        # 等待页面跳转和搜索结果
        for i in range(15):
            await asyncio.sleep(2)
            current_url = page.url
            if 'search' in current_url:
                print(f"  Redirected to search page: {current_url}")
                break
        
        # 额外等待搜索结果
        await asyncio.sleep(10)
        
        # 滚动
        for i in range(5):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
            await asyncio.sleep(2)
        
        print(f"\nSearch/single responses: {len(search_single_responses)}")
        for resp in search_single_responses:
            print(f"  {resp}")
        
        # 检查当前页面
        page_info = await page.evaluate("""
            () => ({
                url: window.location.href,
                title: document.title,
                img_count: document.querySelectorAll('img').length,
                body_len: document.body.innerText.length,
                body_preview: document.body.innerText.substring(0, 300),
            })
        """)
        print(f"\nPage: url={page_info['url']}, title={page_info['title']}, imgs={page_info['img_count']}")
        print(f"Body: {page_info['body_preview'][:200]}")
        
        await context.close()

asyncio.run(main())
