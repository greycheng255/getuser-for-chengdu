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
    textarea = None
    for sel in ['[data-testid="tweetTextarea_0"]', 'div[contenteditable="true"][role="textbox"]']:
        try:
            textarea = await page.wait_for_selector(sel, timeout=8000)
            if textarea:
                break
        except:
            continue
    if not textarea:
        print("找不到输入框，截图看看...")
        await page.screenshot(path="/tmp/test_no_textarea.png", full_page=True)
        raise RuntimeError("找不到输入框")
    await textarea.fill("测试视频上传")
    await asyncio.sleep(2)

    # 找 "Add photos or video" 按钮
    buttons = await page.query_selector_all('button[aria-label="Add photos or video"]')
    print(f"\n找到 {len(buttons)} 个 'Add photos or video' 按钮")

    # 方法1：用 file_chooser 事件 + 点击按钮
    print("\n--- 方法1: file_chooser + 点击按钮 ---")
    async with page.expect_file_chooser(timeout=10000) as fc_info:
        # 点击第一个按钮
        if buttons:
            await buttons[0].click()
        else:
            # 点击附件按钮所在区域
            await page.click('[data-testid="toolBar"] [data-testid="fileInput"]')
    file_chooser = await fc_info.value
    print(f"  文件选择器出现了!")
    await file_chooser.set_files(video_path)
    print(f"  已选择文件")

    # 等待上传完成
    for i in range(12):
        await asyncio.sleep(5)
        videos = await page.query_selector_all('video')
        print(f"  第 {(i+1)*5}s: {len(videos)} 个video")
        if len(videos) > 0:
            print("  ✅ 视频上传成功！")
            break

    await page.screenshot(path="/tmp/test_method1.png", full_page=True)

    # 不真发，直接结束
    await browser.close()
    await p.stop()
    if os.path.exists(video_path):
        os.unlink(video_path)
    print("\n测试完成")

asyncio.run(test())
