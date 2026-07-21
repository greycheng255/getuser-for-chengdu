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
        
        # 拦截搜索 API
        search_ok = False
        search_items = []
        
        async def handle_response(response):
            nonlocal search_ok, search_items
            url = response.url
            if 'aweme/v1/web' in url and 'search' in url and response.status == 200:
                try:
                    data = await response.json()
                    sc = data.get('status_code')
                    print(f"  [INTERCEPT] {url.split('?')[0]} status_code={sc}")
                    if sc == 0 and data.get('data'):
                        search_ok = True
                        if isinstance(data['data'], list):
                            search_items = data['data']
                        elif isinstance(data['data'], dict):
                            search_items = data['data'].get('list', data['data'].get('items', []))
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 导航到搜索页面
        print("Navigating to search page...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="domcontentloaded", timeout=30000)
        
        # 等待更长时间
        for i in range(10):
            await asyncio.sleep(3)
            if search_ok:
                break
        
        print(f"\nSearch OK: {search_ok}, Items: {len(search_items)}")
        
        if search_items:
            for item in search_items[:5]:
                aweme = item.get('aweme_info', item)
                desc = aweme.get('desc', 'no desc')[:60]
                print(f"  - {desc}")
        else:
            # 检查页面 DOM
            page_info = await page.evaluate("""
                () => {
                    const all_imgs = document.querySelectorAll('img[src*="douyinpic"], img[src*="byteimg"]').length;
                    const all_links = [...document.querySelectorAll('a[href*="video"], a[href*="aweme"]')].length;
                    const body_text = document.body.innerText.substring(0, 500);
                    return {imgs: all_imgs, links: all_links, text: body_text};
                }
            """)
            print(f"Page: imgs={page_info['imgs']}, links={page_info['links']}")
            print(f"Text: {page_info['text'][:300]}")
        
        await context.close()

asyncio.run(main())
