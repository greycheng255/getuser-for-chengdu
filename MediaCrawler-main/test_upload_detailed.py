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

    # 下载视频
    async with httpx.AsyncClient() as client:
        r = await client.get(VIDEO_URL, timeout=60)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as f:
            f.write(r.content)
            video_path = f.name
    print(f"视频已下载: {video_path}, {len(r.content)} 字节")

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1280, "height": 900},
    )
    await context.add_cookies(cookie_list)
    page = await context.new_page()

    # 打开编辑器
    await page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)
    print(f"当前URL: {page.url}")

    # 找所有文件输入框，打印详细信息
    all_inputs = await page.query_selector_all('input[type="file"]')
    print(f"\n共有 {len(all_inputs)} 个文件输入框:")
    for i, inp in enumerate(all_inputs):
        accept = await inp.get_attribute('accept') or ''
        name = await inp.get_attribute('name') or ''
        data_testid = await inp.get_attribute('data-testid') or ''
        # 看父元素
        parent_html = await inp.evaluate('(el) => el.parentElement ? el.parentElement.outerHTML.substring(0, 200) : "no parent"')
        print(f"\n  输入框 {i}:")
        print(f"    accept={accept}")
        print(f"    name={name}")
        print(f"    data-testid={data_testid}")
        print(f"    父元素: {parent_html[:150]}...")

    # 先填文字
    textarea = await page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=5000)
    await textarea.fill("测试视频上传")
    await asyncio.sleep(2)

    # 找 fileInput data-testid
    file_input_el = await page.query_selector('[data-testid="fileInput"]')
    print(f"\n  [data-testid='fileInput'] 元素: {file_input_el is not None}")
    if file_input_el:
        tag = await file_input_el.evaluate('(el) => el.tagName')
        print(f"    标签: {tag}")
        if tag == 'INPUT':
            accept = await file_input_el.get_attribute('accept')
            print(f"    accept: {accept}")

    # 尝试用第二个文件输入框上传（因为有两个）
    print("\n--- 测试用第1个文件输入框上传 ---")
    if len(all_inputs) >= 1:
        await all_inputs[0].set_input_files(video_path)
        await asyncio.sleep(8)
        videos = await page.query_selector_all('video')
        print(f"  上传后 video 元素数: {len(videos)}")
        await page.screenshot(path="/tmp/test_input0.png", full_page=True)
        print("  截图: /tmp/test_input0.png")

    await browser.close()
    await p.stop()
    if os.path.exists(video_path):
        os.unlink(video_path)

asyncio.run(test())
