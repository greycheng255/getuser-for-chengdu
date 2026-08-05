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
        
        # 拦截所有 aweme 相关响应
        all_aweme_responses = []
        
        async def handle_response(response):
            url = response.url
            if response.status == 200 and 'aweme' in url:
                try:
                    data = await response.json()
                    all_aweme_responses.append({
                        'url': url[:200],
                        'status_code': data.get('status_code'),
                    })
                except:
                    pass
        
        page.on("response", handle_response)
        
        # 直接导航到搜索页面（不通过首页搜索框）
        print("Navigating directly to search page...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(15)
        
        # 检查页面
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
        
        # 滚动
        for i in range(5):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
            await asyncio.sleep(3)
        
        print(f"\nAll aweme responses: {len(all_aweme_responses)}")
        for resp in all_aweme_responses[:10]:
            print(f"  {resp}")
        
        # 检查是否有验证码
        has_captcha = await page.evaluate("""
            () => {
                const captcha = document.querySelector('[class*="captcha"], [class*="verify"], [class*="slider"]');
                return captcha ? true : false;
            }
        """)
        print(f"\nHas captcha: {has_captcha}")
        
        await context.close()

asyncio.run(main())
