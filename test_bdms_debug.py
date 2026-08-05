import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/getuser/MediaCrawler-main/browser_data/dy_user_data_dir",
            headless=True,
            viewport={"width": 1920, "height": 1080},
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        # 收集控制台消息
        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(f"[{msg.type}] {msg.text[:200]}"))
        
        # 收集页面错误
        page_errors = []
        page.on("pageerror", lambda err: page_errors.append(str(err)[:200]))
        
        # 导航到搜索页面
        print("Navigating to search page...")
        await page.goto("https://www.douyin.com/search/gpt%20image2?type=general", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(10)
        
        # 检查登录状态
        login_info = await page.evaluate("""
            () => {
                const cookies = document.cookie.split(';').reduce((acc, c) => {
                    const [k, v] = c.trim().split('=');
                    acc[k] = v;
                    return acc;
                }, {});
                return {
                    has_sessionid: !!cookies['sessionid'],
                    has_sessionid_ss: !!cookies['sessionid_ss'],
                    has_ttwid: !!cookies['ttwid'],
                    has_odin_tt: !!cookies['odin_tt'],
                    has_passport_csrf_token: !!cookies['passport_csrf_token'],
                    has_is_login_user: !!cookies['is_login_user'],
                    HasUserLogin: localStorage.getItem('HasUserLogin'),
                    cookie_count: document.cookie.split(';').length,
                };
            }
        """)
        print(f"\nLogin info: {login_info}")
        
        # 检查控制台错误
        print(f"\nConsole messages: {len(console_msgs)}")
        error_msgs = [m for m in console_msgs if 'error' in m.lower() or 'Error' in m]
        for msg in error_msgs[:10]:
            print(f"  {msg}")
        
        print(f"\nPage errors: {len(page_errors)}")
        for err in page_errors[:5]:
            print(f"  {err}")
        
        # 检查页面 DOM 结构
        dom_info = await page.evaluate("""
            () => {
                const root = document.getElementById('root') || document.getElementById('app');
                return {
                    has_root: !!root,
                    root_children: root ? root.children.length : 0,
                    root_innerHTML_len: root ? root.innerHTML.length : 0,
                    root_text: root ? root.innerText.substring(0, 300) : '',
                    body_children: document.body.children.length,
                    all_scripts: document.querySelectorAll('script').length,
                };
            }
        """)
        print(f"\nDOM info: {dom_info}")
        
        # 检查是否有 React/Vue 渲染
        render_info = await page.evaluate("""
            () => ({
                has_react: typeof window.__REACT_DEVTOOLS_GLOBAL_HOOK__ !== 'undefined',
                has_next: typeof window.__NEXT_DATA__ !== 'undefined',
                has___NEXT_DATA__: typeof window.__NEXT_DATA__ !== 'undefined',
                react_root: !!document.getElementById('__next'),
            })
        """)
        print(f"Render info: {render_info}")
        
        await context.close()

asyncio.run(main())
