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
        all_responses = []
        
        async def handle_response(response):
            url = response.url
            if response.status == 200:
                try:
                    ct = response.headers.get('content-type', '')
                    if 'json' in ct:
                        data = await response.json()
                        all_responses.append({
                            'url': url[:300],
                            'status_code': data.get('status_code'),
                            'has_data': bool(data.get('data')),
                        })
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 直接导航到搜索页面
        print("Navigating to search page...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)
        
        # 滚动
        for i in range(5):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
            await asyncio.sleep(3)
        
        print(f"\nAll JSON API responses: {len(all_responses)}")
        for resp in all_responses:
            if 'search' in resp['url'].lower() or 'aweme' in resp['url'].lower():
                print(f"  {resp}")
        
        # 检查页面内容
        page_info = await page.evaluate("""
            () => {
                const links = [...document.querySelectorAll('a[href]')].map(a => a.href).filter(h => h.includes('video') || h.includes('aweme')).slice(0, 10);
                const images = document.querySelectorAll('img').length;
                return {
                    url: window.location.href,
                    title: document.title,
                    links: links,
                    img_count: images,
                    body_len: document.body.innerText.length,
                };
            }
        """)
        print(f"\nPage info: url={page_info['url']}, title={page_info['title']}")
        print(f"Images: {page_info['img_count']}, Links: {page_info['links']}")
        
        await context.close()

asyncio.run(main())
