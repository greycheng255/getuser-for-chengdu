import asyncio
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()
import httpx
from playwright.async_api import async_playwright

VIDEO_URL = "https://cos.lingkeai.vip/uploads/2026.07/22/20260722215357_18c4a10ef1b01c9ddd07.mp4"

async def test():
    cookies_str = os.getenv("X_TWITTER_COOKIES", "")
    cookie_list = []
    for pair in cookies_str.split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, value = pair.split("=", 1)
            cookie_list.append({"name": name.strip(), "value": value.strip(), "domain": ".x.com", "path": "/"})

    async with httpx.AsyncClient() as client:
        r = await client.get(VIDEO_URL, timeout=60)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as f:
            f.write(r.content)
            video_path = f.name
    print(f"视频: {len(r.content)} 字节")

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1280, "height": 900},
    )
    await context.add_cookies(cookie_list)
    page = await context.new_page()

    await page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(8)
    print(f"当前URL: {page.url}")

    # 填文字
    textarea = await page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=15000)
    await textarea.fill("测试视频上传")
    await asyncio.sleep(2)

    # 上传前计数
    def count_media():
        return page.evaluate("""() => {
            const editor = document.querySelector('[data-testid="tweetTextarea_0"]');
            if (!editor) return { imgs: 0, vids: 0, mediaDivs: 0, allChildren: 0 };
            // 找编辑器的父容器，往上找几级
            let container = editor.closest('form, [role="dialog"], div.css-175oi2r');
            let parent = editor.parentElement;
            let mediaArea = null;
            // 找包含媒体的兄弟元素
            for (let i = 0; i < 10 && parent; i++) {
                const children = parent.querySelectorAll('img, video');
                if (children.length > 0) {
                    mediaArea = parent;
                    break;
                }
                parent = parent.parentElement;
            }
            const imgs = mediaArea ? mediaArea.querySelectorAll('img').length : 0;
            const vids = mediaArea ? mediaArea.querySelectorAll('video').length : 0;
            return { imgs, vids, mediaFound: !!mediaArea, totalImgs: document.querySelectorAll('img').length, totalVids: document.querySelectorAll('video').length };
        }""")

    before = await count_media()
    print(f"\n上传前: {before}")

    # 直接用第一个 file input 上传
    all_inputs = await page.query_selector_all('input[type="file"]')
    print(f"文件输入框: {len(all_inputs)} 个")
    
    # 看看哪个输入框在编辑器内
    for i, inp in enumerate(all_inputs):
        inside = await inp.evaluate("""(el) => {
            let p = el.parentElement;
            for (let i = 0; i < 20; i++) {
                if (!p) return false;
                if (p.getAttribute('data-testid') === 'toolBar' || p.querySelector('[data-testid="tweetTextarea_0"]')) return true;
                p = p.parentElement;
            }
            return false;
        }""")
        print(f"  输入框 {i}: 在工具栏内={inside}")

    # 点击第一个 Add photos or video 按钮，用 file_chooser
    buttons = await page.query_selector_all('button[aria-label="Add photos or video"]')
    print(f"\nAdd photos or video 按钮: {len(buttons)} 个")
    
    if buttons:
        print("点击按钮上传...")
        async with page.expect_file_chooser(timeout=10000) as fc_info:
            await buttons[0].click()
        fc = await fc_info.value
        await fc.set_files(video_path)
        print("文件已选择")
    else:
        print("没有按钮，直接用第一个输入框")
        await all_inputs[0].set_input_files(video_path)

    # 每隔几秒检测一次
    for i in range(16):
        await asyncio.sleep(5)
        stat = await count_media()
        t = (i + 1) * 5
        print(f"  第 {t}s: 编辑器内img={stat['imgs']}, video={stat['vids']}, 全页面img={stat['totalImgs']}, video={stat['totalVids']}")
        if stat['imgs'] > before.get('imgs', 0) or stat['vids'] > before.get('vids', 0):
            print("  ✅ 检测到新媒体！")
            await page.screenshot(path="/tmp/test_upload_success.png", full_page=True)
            break

    await page.screenshot(path="/tmp/test_upload_final.png", full_page=True)
    print(f"\n最终截图: /tmp/test_upload_final.png")

    # 检查发布按钮状态
    send_btns = await page.query_selector_all('[data-testid="tweetButton"]')
    for i, btn in enumerate(send_btns):
        disabled = await btn.get_attribute('aria-disabled')
        print(f"发布按钮 {i}: aria-disabled={disabled}")

    await browser.close()
    await p.stop()
    if os.path.exists(video_path):
        os.unlink(video_path)

asyncio.run(test())
