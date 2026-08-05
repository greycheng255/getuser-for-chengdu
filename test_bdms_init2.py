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
        
        # 先导航到首页
        print("Navigating to Douyin homepage...")
        await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        
        # 检查所有可能的全局签名对象
        print("\n=== Checking global signing objects ===")
        global_check = await page.evaluate("""
            () => {
                return {
                    has_bdms: typeof window.bdms !== 'undefined',
                    has_byted_acrawler: typeof window.byted_acrawler !== 'undefined',
                    has___ac_signature: typeof window.__ac_signature !== 'undefined',
                    has___ac_nonce: typeof window.__ac_nonce !== 'undefined',
                    has_sign: typeof window.sign !== 'undefined',
                    has_webmssdk: typeof window.webmssdk !== 'undefined',
                    bdms_keys: window.bdms ? Object.keys(window.bdms) : null,
                    byted_keys: window.byted_acrawler ? Object.keys(window.byted_acrawler) : null,
                };
            }
        """)
        print(f"Global check: {global_check}")
        
        # 尝试 bdms.init 初始化
        if global_check.get('has_bdms'):
            print("\n=== Trying bdms.init with config ===")
            init_result = await page.evaluate("""
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
                        return {
                            result_type: typeof result,
                            result_value: result ? String(result).slice(0, 200) : null,
                            result_keys: result && typeof result === 'object' ? Object.keys(result) : null,
                        };
                    } catch(e) {
                        return {error: e.message};
                    }
                }
            """)
            print(f"Init result: {init_result}")
            
            # 初始化后再次检查全局对象
            post_check = await page.evaluate("""
                () => {
                    return {
                        has_byted_acrawler: typeof window.byted_acrawler !== 'undefined',
                        byted_keys: window.byted_acrawler ? Object.keys(window.byted_acrawler) : null,
                        has_webmssdk: typeof window.webmssdk !== 'undefined',
                        webmssdk_keys: window.webmssdk ? Object.keys(window.webmssdk) : null,
                    };
                }
            """)
            print(f"Post-init check: {post_check}")
            
            # 尝试 frontierSign
            if post_check.get('has_byted_acrawler'):
                print("\n=== Trying frontierSign ===")
                sign_result = await page.evaluate("""
                    () => {
                        try {
                            const result = window.byted_acrawler.frontierSign('/aweme/v1/web/general/search/single/?device_platform=webapp&aid=6383&keyword=test');
                            return {result: JSON.stringify(result)};
                        } catch(e) {
                            return {error: e.message};
                        }
                    }
                """)
                print(f"frontierSign result: {sign_result}")
        
        await context.close()

asyncio.run(main())
