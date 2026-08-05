import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # 拦截所有请求，记录包含 a_bogus 的请求
        abogus_requests = []
        def handle_response(response):
            url = response.url
            if 'a_bogus=' in url and 'aweme' in url:
                abogus_requests.append(url[:300])
        
        page.on("response", handle_response)
        
        # 导航到抖音搜索页面
        print("Navigating to Douyin search page...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)
        
        # 检查是否有验证码
        title = await page.title()
        print(f"Page title: {title}")
        
        # 滚动加载更多
        for i in range(3):
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/4})")
            await asyncio.sleep(2)
        
        print(f"\nRequests with a_bogus: {len(abogus_requests)}")
        for url in abogus_requests[:5]:
            print(f"  {url}")
        
        # 检查 window.bdms
        bdms_info = await page.evaluate("""
            () => {
                if (!window.bdms) return {error: "no bdms"};
                return {
                    keys: Object.keys(window.bdms),
                    init_type: typeof window.bdms.init,
                };
            }
        """)
        print(f"\nBDMS info: {bdms_info}")
        
        # 如果 bdms 存在，尝试通过浏览器 fetch 发起请求
        if not bdms_info.get('error'):
            print("\nTrying browser-based fetch...")
            fetch_result = await page.evaluate("""
                async () => {
                    try {
                        const url = 'https://www.douyin.com/aweme/v1/web/general/search/single/?search_channel=general&enable_history=1&keyword=gpt+image2&search_source=tab_search&query_correct_type=1&is_filter_search=0&from_group_id=7378810571505847586&offset=0&count=15&need_filter_settings=1&list_type=multi&device_platform=webapp&aid=6383&channel=channel_pc_web&version_code=190600&version_name=19.6.0';
                        const response = await fetch(url);
                        const data = await response.json();
                        return {
                            status: response.status,
                            status_code: data.status_code,
                            has_data: !!data.data,
                            data_length: data.data ? data.data.length : 0,
                            first_item: data.data && data.data[0] ? JSON.stringify(data.data[0]).slice(0, 200) : null,
                        };
                    } catch(e) {
                        return {error: e.message};
                    }
                }
            """)
            print(f"Fetch result: {fetch_result}")
        
        await browser.close()

asyncio.run(main())
