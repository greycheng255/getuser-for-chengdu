import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()
from playwright.async_api import async_playwright

TWEET_ID = "2079779621101556052"

async def verify_tweet():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()

    # 不登录，直接看推文（公开推文应该能看到）
    print(f"打开推文: {TWEET_ID}")
    await page.goto(f"https://x.com/i/web/status/{TWEET_ID}", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(8)
    
    current_url = page.url
    print(f"当前URL: {current_url}")
    print(f"页面标题: {await page.title()}")

    # 截图
    await page.screenshot(path="/tmp/verify_tweet_public.png", full_page=True)
    print("截图已保存: /tmp/verify_tweet_public.png")

    # 数视频元素
    videos = await page.query_selector_all('video')
    print(f"页面上视频元素总数: {len(videos)}")
    
    # 看有没有报错
    body_text = await page.evaluate("() => document.body.innerText.substring(0, 500)")
    print(f"页面文本前500字:\n{body_text}")

    await browser.close()
    await p.stop()

asyncio.run(verify_tweet())
