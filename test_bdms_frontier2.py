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
        search_data = None
        
        async def handle_response(response):
            nonlocal search_data
            url = response.url
            if 'search/single' in url and response.status == 200:
                try:
                    data = await response.json()
                    if data.get('status_code') == 0 and data.get('data'):
                        search_data = data
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 导航到搜索页面
        print("Navigating to search page...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(15)
        
        # 滚动加载
        for i in range(5):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
            await asyncio.sleep(3)
        
        if search_data:
            print(f"Got search data! Items: {len(search_data.get('data', []))}")
            for item in search_data.get('data', [])[:3]:
                aweme = item.get('aweme_info', {})
                print(f"  - {aweme.get('desc', 'no desc')[:50]}")
        else:
            print("No search data intercepted")
            
            # 检查页面内容
            page_info = await page.evaluate("""
                () => ({
                    url: window.location.href,
                    title: document.title,
                    body_len: document.body.innerText.length,
                    body_preview: document.body.innerText.substring(0, 500),
                })
            """)
            print(f"Page URL: {page_info['url']}")
            print(f"Page title: {page_info['title']}")
            print(f"Body preview: {page_info['body_preview'][:300]}")
        
        await context.close()

asyncio.run(main())
