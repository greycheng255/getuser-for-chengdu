import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        # 注入 bdms.js
        js_url = "https://lf-c-flwb.bytetos.com/obj/rc-client-security/web/stable/1.0.1.18/bdms.js"
        await page.add_script_tag(url=js_url)
        await asyncio.sleep(3)
        
        # 方法1: 先 init 初始化，然后检查 byted_acrawler
        print("=== Method 1: bdms.init with config ===")
        init_result = await page.evaluate("""
            () => {
                try {
                    // 新版初始化方式
                    const result = window.bdms.init({
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
                    return {
                        init_result: typeof result,
                        init_result_keys: result ? Object.keys(result) : null,
                        has_byted_acrawler: typeof window.byted_acrawler !== 'undefined',
                        byted_keys: window.byted_acrawler ? Object.keys(window.byted_acrawler) : null,
                    };
                } catch(e) {
                    return {error: e.message, stack: e.stack?.slice(0, 200)};
                }
            }
        """)
        print(f"Init result: {init_result}")
        
        # 方法2: 检查 byted_acrawler.frontierSign
        if init_result.get('has_byted_acrawler'):
            print("\n=== Method 2: frontierSign ===")
            sign_result = await page.evaluate("""
                () => {
                    try {
                        const result = window.byted_acrawler.frontierSign('/aweme/v1/web/general/search/single/?device_platform=webapp&aid=6383&keyword=test');
                        return {
                            result: result,
                            type: typeof result,
                            keys: result ? Object.keys(result) : null,
                        };
                    } catch(e) {
                        return {error: e.message};
                    }
                }
            """)
            print(f"frontierSign result: {sign_result}")
        
        # 方法3: 检查 init 返回值
        print("\n=== Method 3: Check init return value details ===")
        init_detail = await page.evaluate("""
            () => {
                try {
                    const result = window.bdms.init({
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
                    if (result && typeof result === 'object') {
                        const detail = {};
                        for (const key of Object.keys(result)) {
                            detail[key] = typeof result[key];
                        }
                        return detail;
                    }
                    return {type: typeof result, value: String(result).slice(0, 100)};
                } catch(e) {
                    return {error: e.message};
                }
            }
        """)
        print(f"Init detail: {init_detail}")
        
        await browser.close()

asyncio.run(main())
