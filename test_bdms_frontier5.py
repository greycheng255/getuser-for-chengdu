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
        print("Step 1: Navigate to homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        
        # 拦截搜索 API
        search_ok = False
        search_data = None
        
        async def handle_response(response):
            nonlocal search_ok, search_data
            url = response.url
            if 'search/single' in url and response.status == 200:
                try:
                    data = await response.json()
                    if data.get('status_code') == 0:
                        search_ok = True
                        search_data = data
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 点击搜索框
        print("Step 2: Click search box...")
        try:
            # 尝试多种搜索框选择器
            selectors = [
                'input[placeholder*="搜索"]',
                'input[type="search"]',
                '.search-input input',
                '[class*="search"] input',
            ]
            clicked = False
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        await el.click(timeout=3000)
                        clicked = True
                        print(f"  Clicked: {sel}")
                        break
                except:
                    continue
            
            if not clicked:
                print("  Could not find search input, trying navigation...")
                await page.goto("https://www.douyin.com/search/gpt%20image2", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  Error: {e}")
            await page.goto("https://www.douyin.com/search/gpt%20image2", wait_until="domcontentloaded", timeout=30000)
        
        await asyncio.sleep(8)
        
        # 检查当前 URL
        current_url = page.url
        print(f"\nCurrent URL: {current_url}")
        
        if search_ok:
            print(f"\nSearch SUCCESS! Got data with {len(search_data.get('data', []))} items")
            for item in search_data.get('data', [])[:3]:
                aweme = item.get('aweme_info', {})
                print(f"  - {aweme.get('desc', 'no desc')[:60]}")
        else:
            print("\nSearch still failing (2483)")
            # 检查是否在搜索页面
            page_text = await page.evaluate("() => document.body.innerText.substring(0, 500)")
            print(f"Page text: {page_text[:300]}")
        
        await context.close()

asyncio.run(main())
