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
        
        # 导航到首页
        print("Navigating to Douyin homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        
        # 先初始化 bdms
        await page.evaluate("""
            () => {
                if (window.bdms && window.bdms.init) {
                    window.bdms.init({
                        "aid": 6383,
                        "pageId": 6241,
                        "paths": [
                            "^/webcast/",
                            "^/aweme/v1/",
                            "^/aweme/v2/",
                            "/v1/message/send",
                            "^/live/",
                            "^/captcha/",
                            "^/ecom/"
                        ],
                        "boe": false,
                        "ddrt": 7
                    });
                }
            }
        """)
        await asyncio.sleep(2)
        
        # 测试 frontierSign 生成签名
        print("\n=== Testing frontierSign ===")
        test_url = "/aweme/v1/web/general/search/single/?search_channel=general&enable_history=1&keyword=gpt+image2&search_source=tab_search&query_correct_type=1&is_filter_search=0&from_group_id=7378810571505847586&offset=0&count=15&need_filter_settings=1&list_type=multi&device_platform=webapp&aid=6383&channel=channel_pc_web&version_code=190600&version_name=19.6.0"
        
        sign_result = await page.evaluate("""
            ([url]) => {
                try {
                    const result = window.byted_acrawler.frontierSign(url);
                    return {
                        result: JSON.stringify(result),
                        has_x_bogus: !!result['X-Bogus'],
                        has_a_bogus: !!result['a_bogus'],
                    };
                } catch(e) {
                    return {error: e.message};
                }
            }
        """, [test_url])
        print(f"Sign result: {sign_result}")
        
        # 使用签名发起搜索请求
        sign_data = await page.evaluate("""
            ([url]) => {
                try {
                    return window.byted_acrawler.frontierSign(url);
                } catch(e) {
                    return {error: e.message};
                }
            }
        """, [test_url])
        
        if sign_data and not sign_data.get('error'):
            x_bogus = sign_data.get('X-Bogus', '')
            a_bogus = sign_data.get('a_bogus', '')
            print(f"\nX-Bogus: {x_bogus}")
            print(f"a_bogus: {a_bogus}")
            
            # 使用浏览器 fetch 发起请求
            full_url = f"https://www.douyin.com{test_url}"
            if x_bogus:
                full_url += f"&X-Bogus={x_bogus}"
            if a_bogus:
                full_url += f"&a_bogus={a_bogus}"
            
            print(f"\n=== Testing API request with signature ===")
            fetch_result = await page.evaluate("""
                async ([url]) => {
                    try {
                        const response = await fetch(url);
                        const data = await response.json();
                        return {
                            status: response.status,
                            status_code: data.status_code,
                            has_data: !!data.data,
                            data_length: data.data ? data.data.length : 0,
                            first_item_desc: data.data && data.data[0] && data.data[0].aweme_info ? data.data[0].aweme_info.desc?.slice(0, 50) : null,
                        };
                    } catch(e) {
                        return {error: e.message};
                    }
                }
            """, [full_url])
            print(f"Fetch result: {fetch_result}")
        
        await context.close()

asyncio.run(main())
