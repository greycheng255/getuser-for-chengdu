# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/login.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。


import asyncio
import functools
import json
import os
import random
import sys
from typing import Optional

from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from tenacity import (RetryError, retry, retry_if_result, stop_after_attempt,
                      wait_fixed)

import config
from base.base_crawler import AbstractLogin
from cache.cache_factory import CacheFactory
from tools import utils


class DouYinLogin(AbstractLogin):

    def __init__(self,
                 login_type: str,
                 browser_context: BrowserContext, # type: ignore
                 context_page: Page, # type: ignore
                 login_phone: Optional[str] = "",
                 cookie_str: Optional[str] = ""
                 ):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.scan_qrcode_time = 60
        self.cookie_str = cookie_str

    async def begin(self):
        """
            Start login douyin website
            The verification accuracy of the slider verification is not very good... If there are no special requirements, it is recommended not to use Douyin login, or use cookie login
        """

        # select login type
        if config.LOGIN_TYPE == "qrcode":
            # popup login dialog
            await self.popup_login_dialog()
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            # popup login dialog
            await self.popup_login_dialog()
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            # Cookie 登录不需要弹出登录框，直接添加 Cookie
            await self.login_by_cookies()
        else:
            raise ValueError("[DouYinLogin.begin] Invalid Login Type Currently only supported qrcode or phone or cookie ...")

        # If the page redirects to the slider verification page, need to slide again
        await asyncio.sleep(6)
        current_page_title = await self.context_page.title()
        if "验证码中间页" in current_page_title:
            await self.check_page_display_slider(move_step=3, slider_level="hard")

        # check login state
        utils.logger.info(f"[DouYinLogin.begin] login finished then check login state ...")
        try:
            login_success = await self.check_login_state()
            if login_success:
                utils.logger.info("[DouYinLogin.begin] Login state check passed")
            else:
                utils.logger.warning("[DouYinLogin.begin] Login state check failed, but continuing...")
        except RetryError:
            utils.logger.warning("[DouYinLogin.begin] Login state check timeout, but continuing with available cookies...")
        except Exception as e:
            utils.logger.warning(f"[DouYinLogin.begin] Login state check error: {e}, but continuing...")

        # wait for redirect
        wait_redirect_seconds = 5
        utils.logger.info(f"[DouYinLogin.begin] Wait for {wait_redirect_seconds} seconds redirect ...")
        await asyncio.sleep(wait_redirect_seconds)

    @retry(stop=stop_after_attempt(30), wait=wait_fixed(2), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self):
        """Check if the current login status is successful and return True otherwise return False"""
        try:
            current_cookie = await self.browser_context.cookies()
            _, cookie_dict = utils.convert_cookies(current_cookie)
        except Exception as e:
            utils.logger.warning(f"[DouYinLogin.check_login_state] Failed to get cookies: {e}")
            cookie_dict = {}

        # 检查 localStorage
        for page in self.browser_context.pages:
            try:
                local_storage = await page.evaluate("() => window.localStorage")
                if local_storage.get("HasUserLogin", "") == "1":
                    utils.logger.info("[DouYinLogin.check_login_state] Login confirmed via localStorage")
                    return True
            except Exception as e:
                await asyncio.sleep(0.1)

        # 检查 LOGIN_STATUS cookie
        if cookie_dict.get("LOGIN_STATUS") == "1":
            utils.logger.info("[DouYinLogin.check_login_state] Login confirmed via LOGIN_STATUS cookie")
            return True
        
        # 检查 sessionid cookie（抖音登录的关键 cookie）
        if cookie_dict.get("sessionid"):
            utils.logger.info("[DouYinLogin.check_login_state] Login confirmed via sessionid cookie")
            return True
        
        # 检查 sid_guard 或 sid_tt cookie
        if cookie_dict.get("sid_guard") or cookie_dict.get("sid_tt"):
            utils.logger.info("[DouYinLogin.check_login_state] Login confirmed via sid cookies")
            return True

        utils.logger.info(f"[DouYinLogin.check_login_state] Login not confirmed yet, cookies: {list(cookie_dict.keys())}")
        return False

    async def popup_login_dialog(self):
        """If the login dialog box does not pop up automatically, we will manually click the login button"""
        dialog_selector = "xpath=//div[@id='login-panel-new']"
        try:
            # check dialog box is auto popup and wait for 10 seconds
            await self.context_page.wait_for_selector(dialog_selector, timeout=1000 * 10)
        except Exception as e:
            utils.logger.error(f"[DouYinLogin.popup_login_dialog] login dialog box does not pop up automatically, error: {e}")
            utils.logger.info("[DouYinLogin.popup_login_dialog] login dialog box does not pop up automatically, we will manually click the login button")
            login_button_ele = self.context_page.locator("xpath=//p[text() = '登录']")
            await login_button_ele.click()
            await asyncio.sleep(0.5)

    async def login_by_qrcode(self):
        utils.logger.info("[DouYinLogin.login_by_qrcode] Begin login douyin by qrcode...")
        qrcode_img_selector = "xpath=//div[@id='animate_qrcode_container']//img"
        base64_qrcode_img = await utils.find_login_qrcode(
            self.context_page,
            selector=qrcode_img_selector
        )
        if not base64_qrcode_img:
            utils.logger.info("[DouYinLogin.login_by_qrcode] login qrcode not found please confirm ...")
            sys.exit()

        partial_show_qrcode = functools.partial(utils.show_qrcode, base64_qrcode_img)
        asyncio.get_running_loop().run_in_executor(executor=None, func=partial_show_qrcode)
        await asyncio.sleep(2)

    async def login_by_mobile(self):
        utils.logger.info("[DouYinLogin.login_by_mobile] Begin login douyin by mobile ...")
        mobile_tap_ele = self.context_page.locator("xpath=//li[text() = '验证码登录']")
        await mobile_tap_ele.click()
        await self.context_page.wait_for_selector("xpath=//article[@class='web-login-mobile-code']")
        mobile_input_ele = self.context_page.locator("xpath=//input[@placeholder='手机号']")
        await mobile_input_ele.fill(self.login_phone)
        await asyncio.sleep(0.5)
        send_sms_code_btn = self.context_page.locator("xpath=//span[text() = '获取验证码']")
        await send_sms_code_btn.click()

        # Check if there is slider verification
        await self.check_page_display_slider(move_step=10, slider_level="easy")
        cache_client = CacheFactory.create_cache(config.CACHE_TYPE_MEMORY)
        max_get_sms_code_time = 60 * 2  # Maximum time to get verification code is 2 minutes
        while max_get_sms_code_time > 0:
            utils.logger.info(f"[DouYinLogin.login_by_mobile] get douyin sms code from redis remaining time {max_get_sms_code_time}s ...")
            await asyncio.sleep(1)
            sms_code_key = f"dy_{self.login_phone}"
            sms_code_value = cache_client.get(sms_code_key)
            if not sms_code_value:
                max_get_sms_code_time -= 1
                continue

            sms_code_input_ele = self.context_page.locator("xpath=//input[@placeholder='请输入验证码']")
            await sms_code_input_ele.fill(value=sms_code_value.decode())
            await asyncio.sleep(0.5)
            submit_btn_ele = self.context_page.locator("xpath=//button[@class='web-login-button']")
            await submit_btn_ele.click()  # Click login
            # todo ... should also check the correctness of the verification code, it may be incorrect
            break

    async def check_page_display_slider(self, move_step: int = 10, slider_level: str = "easy"):
        """
        Check if slider verification appears on the page (including iframes)
        :return:
        """
        # 首先检查主页面是否有滑块
        back_selector = "#captcha-verify-image"
        try:
            await self.context_page.wait_for_selector(selector=back_selector, state="visible", timeout=10 * 1000)
            utils.logger.info("[DouYinLogin.check_page_display_slider] Found slider on main page")
            await self._solve_slider_on_page(self.context_page, back_selector, 'xpath=//*[@id="captcha_container"]/div/div[2]/img[2]', move_step, slider_level)
            return
        except PlaywrightTimeoutError:
            pass

        # 检查 iframe 中是否有滑块（新型验证码）
        utils.logger.info("[DouYinLogin.check_page_display_slider] Checking iframes for captcha...")
        for frame in self.context_page.frames:
            if frame == self.context_page.main_frame:
                continue
            try:
                await frame.wait_for_selector("#captcha_verify_image", state="visible", timeout=5 * 1000)
                utils.logger.info(f"[DouYinLogin.check_page_display_slider] Found slider in iframe: {frame.url[:80]}")
                await self._solve_slider_on_page(frame, "#captcha_verify_image", "#captcha-verify_img_slide", move_step, slider_level, is_iframe=True)
                return
            except PlaywrightTimeoutError:
                continue
        
        utils.logger.info("[DouYinLogin.check_page_display_slider] No slider found on page or iframes")

    async def _solve_slider_on_page(self, page_or_frame, back_selector: str, gap_selector: str, move_step: int, slider_level: str, is_iframe: bool = False):
        """在指定页面或 iframe 中解决滑块验证码"""
        max_slider_try_times = 30
        slider_verify_success = False
        distance_offset = 0  # 距离补偿：每次失败后微调
        img_not_loaded_streak = 0  # 图片加载失败连续计数器
        IMG_NOT_LOADED_LIMIT = 5  # 连续 5 次图片加载失败就放弃，避免卡在验证码循环
        slider_still_visible_streak = 0  # 滑块仍可见连续计数器（距离不对）
        SLIDER_STILL_VISIBLE_LIMIT = 8  # 连续 8 次滑块仍可见就放弃
        last_raw_distance = -1  # 上次的识别距离，用于检测图片是否刷新
        same_distance_count = 0  # 相同距离连续出现次数
        while not slider_verify_success:
            if max_slider_try_times <= 0:
                utils.logger.error("[DouYinLogin._solve_slider_on_page] slider verify failed after max retries, skipping ...")
                break
            try:
                # 如果是 iframe 模式，每次重新查找 frame（刷新后 frame 引用可能失效）
                current_frame = page_or_frame
                if is_iframe:
                    for frame in self.context_page.frames:
                        if frame == self.context_page.main_frame:
                            continue
                        try:
                            await frame.wait_for_selector("#captcha_verify_image", state="visible", timeout=3000)
                            current_frame = frame
                            break
                        except:
                            continue
                
                await self.move_slider_on_page(current_frame, back_selector, gap_selector, move_step, slider_level, is_iframe, distance_offset)
                await asyncio.sleep(2)

                # 检查是否出现"操作过慢"等提示
                try:
                    page_content = await current_frame.content()
                except Exception:
                    page_content = ""
                if "操作过慢" in page_content or "提示重新操作" in page_content:
                    utils.logger.info("[DouYinLogin._solve_slider_on_page] slider verify failed (too slow), retry ...")
                    for selector in [".secsdk_captcha_refresh", "#captcha_reload_img", "[class*='refresh']"]:
                        try:
                            refresh_btn = await current_frame.query_selector(selector)
                            if refresh_btn:
                                await refresh_btn.click()
                                break
                        except:
                            pass
                    await asyncio.sleep(1.5)
                    continue

                # 检查验证码是否消失（验证成功）
                try:
                    await current_frame.wait_for_selector(selector=back_selector, state="hidden", timeout=8000)
                    # 元素隐藏了，但要确认不是验证码组件加载失败导致的隐藏
                    # 检查页面 URL 是否还在验证中心（如果在验证中心说明验证没通过）
                    try:
                        current_url = self.context_page.url
                        if "verifycenter" in current_url or "captcha" in current_url.lower():
                            utils.logger.warning(f"[DouYinLogin._solve_slider_on_page] element hidden but still on verify page: {current_url[:100]}, treating as NOT solved")
                            # 不标记成功，继续重试
                            raise Exception("element hidden but still on verify page")
                    except Exception as url_check_err:
                        if "still on verify page" in str(url_check_err):
                            raise
                        # URL 检查失败，忽略
                    utils.logger.info("[DouYinLogin._solve_slider_on_page] slider verify success (element hidden) ...")
                    slider_verify_success = True
                except Exception as e:
                    err_msg = str(e).lower()
                    if "still on verify page" in err_msg:
                        # 验证码组件加载失败导致元素隐藏，但实际没通过验证
                        # 刷新验证码重试
                        utils.logger.info("[DouYinLogin._solve_slider_on_page] captcha component may have failed, refreshing ...")
                        for refresh_sel in [".secsdk_captcha_refresh", "#captcha_reload_img", ".captcha-refresh-btn", "[class*='refresh']"]:
                            try:
                                refresh_btn = await current_frame.query_selector(refresh_sel)
                                if refresh_btn:
                                    await refresh_btn.click()
                                    utils.logger.info(f"[DouYinLogin._solve_slider_on_page] refreshed via click: {refresh_sel}")
                                    break
                            except Exception:
                                pass
                        await asyncio.sleep(2)
                        max_slider_try_times -= 1
                        continue
                    if "detached" in err_msg:
                        utils.logger.info("[DouYinLogin._solve_slider_on_page] slider verify success (iframe detached) ...")
                        slider_verify_success = True
                    else:
                        # 额外检查：验证码可能已经不在DOM中了
                        try:
                            img_visible = await current_frame.evaluate("""
                                () => {
                                    const img = document.querySelector('#captcha_verify_image');
                                    if (!img) return false;
                                    const rect = img.getBoundingClientRect();
                                    return rect.width > 0 && rect.height > 0;
                                }
                            """)
                            if not img_visible:
                                # 再次检查 URL 是否还在验证中心
                                try:
                                    current_url = self.context_page.url
                                    if "verifycenter" in current_url or "captcha" in current_url.lower():
                                        utils.logger.warning(f"[DouYinLogin._solve_slider_on_page] image not visible but still on verify page, NOT solved")
                                        for refresh_sel in [".secsdk_captcha_refresh", "#captcha_reload_img", ".captcha-refresh-btn", "[class*='refresh']"]:
                                            try:
                                                refresh_btn = await current_frame.query_selector(refresh_sel)
                                                if refresh_btn:
                                                    await refresh_btn.click()
                                                    utils.logger.info(f"[DouYinLogin._solve_slider_on_page] refreshed via click: {refresh_sel}")
                                                    break
                                            except Exception:
                                                pass
                                        await asyncio.sleep(2)
                                        max_slider_try_times -= 1
                                        continue
                                except Exception:
                                    pass
                                utils.logger.info("[DouYinLogin._solve_slider_on_page] slider verify success (image not visible) ...")
                                slider_verify_success = True
                                continue
                        except Exception:
                            # iframe可能已销毁，说明验证通过
                            utils.logger.info("[DouYinLogin._solve_slider_on_page] slider verify success (frame destroyed) ...")
                            slider_verify_success = True
                            continue

                        # 检查是否有验证成功的提示
                        try:
                            success_text = await current_frame.evaluate("""
                                () => {
                                    const text = document.body?.innerText || '';
                                    return text.includes('验证成功') || text.includes('验证通过');
                                }
                            """)
                            if success_text:
                                utils.logger.info("[DouYinLogin._solve_slider_on_page] slider verify success (success text found) ...")
                                slider_verify_success = True
                                continue
                        except Exception:
                            pass

                        # 验证码还在，可能拖动位置不对，刷新后重试
                        slider_still_visible_streak += 1
                        if slider_still_visible_streak >= SLIDER_STILL_VISIBLE_LIMIT:
                            utils.logger.error(f"[DouYinLogin._solve_slider_on_page] slider still visible {slider_still_visible_streak} times in a row, giving up (distance may be consistently wrong) ...")
                            break
                        utils.logger.info(f"[DouYinLogin._solve_slider_on_page] slider still visible (streak {slider_still_visible_streak}/{SLIDER_STILL_VISIBLE_LIMIT}), refreshing and retrying ...")
                        refreshed = False
                        # 方式1: 点击刷新按钮
                        for selector in [".secsdk_captcha_refresh", "#captcha_reload_img", ".captcha-refresh-btn", "[class*='refresh']"]:
                            try:
                                refresh_btn = await current_frame.query_selector(selector)
                                if refresh_btn:
                                    await refresh_btn.click()
                                    refreshed = True
                                    break
                            except:
                                pass
                        # 方式2: JS 触发刷新
                        if not refreshed:
                            try:
                                await current_frame.evaluate("""() => {
                                    const btn = document.querySelector('.secsdk_captcha_refresh') 
                                        || document.querySelector('#captcha_reload_img')
                                        || document.querySelector('[class*="refresh"]');
                                    if (btn) btn.click();
                                }""")
                                refreshed = True
                            except:
                                pass
                        # 方式3: 重新加载 iframe
                        if not refreshed and is_iframe:
                            try:
                                await self.context_page.evaluate("""() => {
                                    const iframe = document.querySelector('iframe[src*="captcha"]');
                                    if (iframe) {
                                        const src = iframe.src;
                                        iframe.src = '';
                                        setTimeout(() => { iframe.src = src; }, 500);
                                    }
                                }""")
                            except:
                                pass
                        
                        await asyncio.sleep(1.5)
                        # 随机微调 slider_level 增加成功率
                        slider_level = random.choice(["easy", "medium", "hard"])
                        # distance_offset 由外层 except 统一调整，此处不再重复
                        raise
            except Exception as e:
                err_str = str(e)
                utils.logger.error(f"[DouYinLogin._solve_slider_on_page] slider verify failed, error: {err_str}")
                await asyncio.sleep(2)
                max_slider_try_times -= 1

                # 如果是图片未加载的问题(src 空/文件过小),不调整 distance_offset(跟距离无关)
                # 刷新验证码获取新图片
                if "not loaded" in err_str or "src empty" in err_str or "file_size=0" in err_str:
                    img_not_loaded_streak += 1
                    if img_not_loaded_streak >= IMG_NOT_LOADED_LIMIT:
                        utils.logger.error(f"[DouYinLogin._solve_slider_on_page] image not loaded {img_not_loaded_streak} times in a row, giving up (captcha component may be broken) ...")
                        break
                    utils.logger.info(f"[DouYinLogin._solve_slider_on_page] image not loaded (streak {img_not_loaded_streak}/{IMG_NOT_LOADED_LIMIT}), refreshing captcha ...")
                    refreshed = False
                    # 方式1: 点击刷新按钮
                    for refresh_sel in [".secsdk_captcha_refresh", "#captcha_reload_img", ".captcha-refresh-btn", "[class*='refresh']"]:
                        try:
                            refresh_btn = await current_frame.query_selector(refresh_sel)
                            if refresh_btn:
                                await refresh_btn.click()
                                refreshed = True
                                utils.logger.info(f"[DouYinLogin._solve_slider_on_page] refreshed via click: {refresh_sel}")
                                break
                        except Exception:
                            pass
                    # 方式2: JS 触发刷新
                    if not refreshed:
                        try:
                            await current_frame.evaluate("""() => {
                                const btn = document.querySelector('.secsdk_captcha_refresh')
                                    || document.querySelector('#captcha_reload_img')
                                    || document.querySelector('[class*="refresh"]');
                                if (btn) btn.click();
                            }""")
                            refreshed = True
                        except Exception:
                            pass
                    # 方式3: 重新加载 iframe
                    if not refreshed and is_iframe:
                        try:
                            await self.context_page.evaluate("""() => {
                                const iframe = document.querySelector('iframe[src*="captcha"]');
                                if (iframe) {
                                    const src = iframe.src;
                                    iframe.src = '';
                                    setTimeout(() => { iframe.src = src; }, 500);
                                }
                            }""")
                        except Exception:
                            pass
                    await asyncio.sleep(3)  # 等新图片加载（增至3秒确保加载完成）
                else:
                    # 非图片加载问题（距离不对等），才调整 distance_offset
                    # 注意: 不要持续累加，否则距离会越来越偏离正确位置
                    # 每次用小的随机扰动，让识别距离有微小变化
                    distance_offset = random.uniform(-5, 5)
                    img_not_loaded_streak = 0  # 非图片问题，重置计数器

                utils.logger.info(f"[DouYinLogin._solve_slider_on_page] remaining slider try times: {max_slider_try_times}, distance_offset: {distance_offset:.1f}")
                continue

    async def move_slider(self, back_selector: str, gap_selector: str, move_step: int = 10, slider_level="easy"):
        """兼容旧调用，委托给 move_slider_on_page"""
        await self.move_slider_on_page(self.context_page, back_selector, gap_selector, move_step, slider_level, is_iframe=False)

    async def move_slider_on_page(self, page_or_frame, back_selector: str, gap_selector: str, move_step: int = 10, slider_level="easy", is_iframe: bool = False, distance_offset: float = 0):
        """
        Move the slider to the right to complete the verification
        Supports both main page and iframe
        使用 JS 在 iframe 内直接触发拖动事件，避免坐标转换问题
        """

        # ===== 等待验证码图片真正加载完成(src 非空 + naturalWidth > 0) =====
        # 日志显示 <img src=""> 元素可见但 src 为空,直接截图只会得到空白图。
        # 必须等 JS 把图片 URL 写入 src 且浏览器解码完成(naturalWidth>0)才能识别。
        _wait_img_js = """
        (selector) => {
            const img = document.querySelector(selector);
            if (!img) return {exists: false};
            return {
                exists: true,
                src: img.src || '',
                complete: img.complete,
                naturalWidth: img.naturalWidth || 0,
                clientWidth: img.clientWidth || 0
            };
        }
        """
        img_ready = False
        last_bg_info = None
        # 判断 src 是否为真正的图片 URL（而非验证中心 iframe URL）
        # 抖音验证码组件初始化时 img.src 会临时是 rmc.bytedance.com/verifycenter URL，
        # 等组件 JS 加载完图片后 src 会变成 p6-catpcha.byteimg.com 或 data:image
        def _is_real_image_url(url: str) -> bool:
            if not url:
                return False
            if url.startswith("data:image"):
                return True
            # 真正的图片 CDN 域名
            if any(d in url for d in ["byteimg.com", "bytecdn", "tos-cn", "ibytedtos", "lf3-static", "lf-cdn"]):
                return True
            return False

        for attempt in range(10):  # 最多等 5 秒（缩短等待时间，快速失败）
            try:
                bg_info = await page_or_frame.evaluate(_wait_img_js, back_selector)
                last_bg_info = bg_info
                if (bg_info and bg_info.get("exists") and bg_info.get("src")
                        and bg_info.get("naturalWidth", 0) > 0):
                    img_ready = True
                    utils.logger.info(
                        f"[DouYinLogin.move_slider] bg image ready after {attempt*0.5:.1f}s, "
                        f"src_len={len(bg_info['src'])}, naturalWidth={bg_info['naturalWidth']}"
                    )
                    break
                # 检查 src 是否为验证中心 URL（说明验证码组件没正确加载图片）
                if bg_info and bg_info.get("src") and "verifycenter" in bg_info.get("src", ""):
                    if attempt % 4 == 0:
                        utils.logger.warning(
                            f"[DouYinLogin.move_slider] bg src is verifycenter URL (not image), "
                            f"captcha component may not have loaded image yet, attempt={attempt}"
                        )
                # 每 2 秒打印一次详细状态，帮助诊断
                elif attempt % 4 == 0 and bg_info:
                    utils.logger.info(
                        f"[DouYinLogin.move_slider] waiting bg image... attempt={attempt}, "
                        f"exists={bg_info.get('exists')}, src_len={len(bg_info.get('src',''))}, "
                        f"complete={bg_info.get('complete')}, naturalWidth={bg_info.get('naturalWidth')}, "
                        f"clientWidth={bg_info.get('clientWidth')}"
                    )
            except Exception as e:
                if attempt % 4 == 0:
                    utils.logger.warning(f"[DouYinLogin.move_slider] evaluate failed attempt={attempt}: {e}")
            await asyncio.sleep(0.5)

        if not img_ready:
            # naturalWidth=0 但 src 非空且元素有显示尺寸时,图片可能因 CORS/网络错误加载失败,
            # 但浏览器仍会用已解码的缓存渲染元素。尝试元素截图作为回退方案。
            # 元素截图直接抓取渲染后的像素,不依赖 naturalWidth。
            # 注意: 如果 src 是验证中心 URL(rmc.bytedance.com/verifycenter),说明
            # 验证码组件没正确加载图片,截图只会得到空白图,不能用作识别
            src_is_verifycenter = (
                last_bg_info and last_bg_info.get("src")
                and "verifycenter" in last_bg_info.get("src", "")
            )
            try_screenshot = (
                last_bg_info and last_bg_info.get("src")
                and last_bg_info.get("clientWidth", 0) > 10
                and not src_is_verifycenter  # 验证中心 URL 时截图无意义
            )
            if try_screenshot:
                utils.logger.info(
                    "[DouYinLogin.move_slider] naturalWidth=0 but src present, "
                    "trying element screenshot fallback"
                )
                try:
                    el = await page_or_frame.query_selector(back_selector)
                    if el:
                        box = await el.bounding_box()
                        if box and box["width"] > 10 and box["height"] > 10:
                            shot = await el.screenshot()
                            if shot and len(shot) > 500:
                                img_ready = True
                                utils.logger.info(
                                    f"[DouYinLogin.move_slider] screenshot fallback OK, "
                                    f"bytes={len(shot)}, bbox={box['width']:.0f}x{box['height']:.0f}"
                                )
                except Exception as e:
                    utils.logger.warning(f"[DouYinLogin.move_slider] screenshot fallback failed: {e}")
            elif src_is_verifycenter:
                utils.logger.warning(
                    "[DouYinLogin.move_slider] bg src is verifycenter URL, "
                    "captcha component failed to load image, skipping screenshot fallback"
                )

        if not img_ready:
            # 图片 src 为空或未加载完成,继续执行只会截到空白图→识别距离为0→拖动无效
            # 直接抛错触发上层重试,上层会刷新验证码获取新图片
            utils.logger.warning(
                "[DouYinLogin.move_slider] bg image NOT ready (src empty or not loaded) after 10s, "
                "aborting this attempt to trigger captcha refresh"
            )
            raise Exception("bg image not loaded (src empty or naturalWidth=0) after 10s")

        # get slider background image
        slider_back_elements = await page_or_frame.wait_for_selector(
            selector=back_selector,
            timeout=1000 * 10,
        )
        slide_back = str(await slider_back_elements.get_property("src")) # type: ignore

        # get slider gap image
        gap_elements = await page_or_frame.wait_for_selector(
            selector=gap_selector,
            timeout=1000 * 10,
        )
        gap_src = str(await gap_elements.get_property("src")) # type: ignore

        # 获取背景图实际显示尺寸（用于比例换算）
        back_bbox = await slider_back_elements.bounding_box()
        img_display_width = back_bbox["width"] if back_bbox else 340

        # 在浏览器上下文内用 fetch 获取图片(带完整 Cookie/指纹,避免 httpx 被风控返回 HTML)
        slide_back_path = await self._fetch_image_via_browser(page_or_frame, slide_back, "bg")
        gap_src_path = await self._fetch_image_via_browser(page_or_frame, gap_src, "gap")

        # 识别前校验:如果背景图文件无效(空白或过小),说明图片没加载,直接抛错触发重试
        import os as _os_chk
        if (not _os_chk.path.exists(slide_back_path)
                or _os_chk.path.getsize(slide_back_path) < 500):
            raise Exception(
                f"bg image not loaded properly (src_len={len(slide_back)}, "
                f"file_size={_os_chk.path.getsize(slide_back_path) if _os_chk.path.exists(slide_back_path) else 0})"
            )

        # Identify slider position
        slide_app = utils.Slide(gap=gap_src_path, bg=slide_back_path)
        distance = slide_app.discern()

        utils.logger.info(f"[DouYinLogin.move_slider] bg_src_last40={slide_back[-40:]}, gap_src_last40={gap_src[-40:]}, discern_distance={distance}")
        # 额外诊断：打印完整 src 的前 200 字符，帮助判断 src 是否为有效图片 URL
        utils.logger.info(f"[DouYinLogin.move_slider] bg_src_full_preview={slide_back[:200]}, gap_src_full_preview={gap_src[:200]}")

        # 按比例换算：识别是在 340px 宽的图上做的，需要换算到实际显示宽度
        scale = img_display_width / 340
        distance_scaled = int(distance * scale)
        
        # 随机微调距离，避免每次精确到像素
        distance_final = distance_scaled + random.uniform(-2, 2) + distance_offset

        utils.logger.info(f"[DouYinLogin.move_slider] raw_distance={distance}, scale={scale:.2f}, display_width={img_display_width}, scaled_distance={distance_scaled}, final_distance={distance_final:.1f}")

        # 如果识别距离为0或异常小，说明图片识别失败（空白图/纯色图）
        # 抛出异常触发上层刷新验证码获取新图片，而不是用随机距离浪费尝试次数
        if distance_scaled < 20:
            utils.logger.warning(f"[DouYinLogin.move_slider] discern distance too small ({distance_scaled}), image may be blank, aborting to trigger captcha refresh")
            raise Exception(f"bg image not loaded (discern distance={distance_scaled} too small, image may be blank)")

        # 生成拟人轨迹
        tracks = utils.get_tracks(int(distance_final), slider_level)
        new_1 = tracks[-1] - (sum(tracks) - int(distance_final))
        tracks.pop()
        tracks.append(new_1)

        # ===== 优先使用 Playwright mouse API（模拟真实浏览器输入） =====
        # 查找拖动按钮（不是滑块图片，是底部的拖动条按钮）
        drag_btn_selectors = [
            ".secsdk_captcha_drag_icon",  # 抖音滑块拖动按钮
            "#captcha_slide_icon",         # 备选
            ".captcha-slider-btn",         # 备选
            gap_selector,                   # 最后回退到滑块图片
        ]
        drag_element = None
        for sel in drag_btn_selectors:
            try:
                el = await page_or_frame.query_selector(sel)
                if el:
                    drag_element = el
                    utils.logger.info(f"[DouYinLogin.move_slider] Found drag element with selector: {sel}")
                    break
            except:
                continue
        
        if not drag_element:
            drag_element = await page_or_frame.query_selector(gap_selector)
        
        bounding_box = await drag_element.bounding_box()
        
        if bounding_box:
            start_x = bounding_box["x"] + bounding_box["width"] / 2
            start_y = bounding_box["y"] + bounding_box["height"] / 2
            start_y = start_y + random.uniform(-2, 2)

            # 不再减去 drag offset —— 识别距离已经是滑块需要移动的相对距离
            # 之前错误地减去了按钮中心相对于背景图左边的偏移(约34px)，导致移动不足
            utils.logger.info(f"[DouYinLogin.move_slider] slider bbox: x={bounding_box['x']:.1f}, y={bounding_box['y']:.1f}, w={bounding_box['width']:.1f}, h={bounding_box['height']:.1f}")
            utils.logger.info(f"[DouYinLogin.move_slider] start_pos=({start_x:.1f}, {start_y:.1f}), total_tracks={len(tracks)}, sum_tracks={sum(tracks)}")

            await self.context_page.mouse.move(start_x, start_y)
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await drag_element.hover()
            await self.context_page.mouse.down()
            await asyncio.sleep(random.uniform(0.05, 0.15))

            x = start_x
            y = start_y
            for i, track in enumerate(tracks):
                y_offset = random.uniform(-1.5, 1.5)
                await self.context_page.mouse.move(x + track, y + y_offset, steps=move_step)
                x += track
                # 随机微停顿：模拟人手犹豫
                if random.random() < 0.08:
                    await asyncio.sleep(random.uniform(0.02, 0.08))
                # 在减速段（后半段）增加更多停顿
                if i > len(tracks) * 0.7 and random.random() < 0.15:
                    await asyncio.sleep(random.uniform(0.03, 0.1))

            # 释放前短暂停顿，模拟人手确认位置
            await asyncio.sleep(random.uniform(0.15, 0.35))
            await self.context_page.mouse.up()
            utils.logger.info(f"[DouYinLogin.move_slider] mouse drag completed, moved {x - start_x:.1f}px")
        else:
            # Fallback: 使用 JS 在 iframe 内触发拖动事件
            utils.logger.warning("[DouYinLogin.move_slider] no bounding_box, trying JS drag")
            tracks_js = json.dumps(tracks)
            js_code = f"""
            (async () => {{
                const slider = document.querySelector('{gap_selector}')
                    || document.querySelector('#captcha-verify_img_slide')
                    || document.querySelector('.secsdk_captcha_drag_icon');
                if (!slider) return 'slider not found';
                
                const rect = slider.getBoundingClientRect();
                const startX = rect.left + rect.width / 2;
                const startY = rect.top + rect.height / 2;
                const tracks = {tracks_js};
                
                slider.dispatchEvent(new PointerEvent('pointerdown', {{
                    pointerId: 1, pointerType: 'mouse', clientX: startX, clientY: startY, bubbles: true
                }}));
                slider.dispatchEvent(new MouseEvent('mousedown', {{ clientX: startX, clientY: startY, bubbles: true }}));
                
                let currentX = startX;
                let currentY = startY;
                
                for (let i = 0; i < tracks.length; i++) {{
                    currentX += tracks[i];
                    currentY += (Math.random() - 0.5) * 3;
                    document.dispatchEvent(new PointerEvent('pointermove', {{
                        pointerId: 1, pointerType: 'mouse', clientX: currentX, clientY: currentY, bubbles: true
                    }}));
                    document.dispatchEvent(new MouseEvent('mousemove', {{ clientX: currentX, clientY: currentY, bubbles: true }}));
                    if (i % 3 === 0) await new Promise(r => setTimeout(r, 15));
                }}
                
                await new Promise(r => setTimeout(r, 100));
                document.dispatchEvent(new PointerEvent('pointerup', {{
                    pointerId: 1, pointerType: 'mouse', clientX: currentX, clientY: currentY, bubbles: true
                }}));
                document.dispatchEvent(new MouseEvent('mouseup', {{ clientX: currentX, clientY: currentY, bubbles: true }}));
                
                return 'dragged ' + Math.round(currentX - startX) + 'px';
            }})()
            """
            try:
                result = await page_or_frame.evaluate(js_code)
                utils.logger.info(f"[DouYinLogin.move_slider] JS drag result: {result}")
            except Exception as e:
                utils.logger.error(f"[DouYinLogin.move_slider] JS drag also failed: {e}")

    async def _fetch_image_via_browser(self, page_or_frame, img_url: str, img_type: str) -> str:
        """
        获取滑块图片并保存为本地文件。
        首选方案: 元素截图(直接抓取浏览器渲染后的像素,完全绕过 URL/Cookie/风控/CORS)
        回退方案: iframe fetch → 主页面 fetch → httpx 下载
        元素截图最可靠,因为不依赖 URL 是否有效(data URI/blob URL/已失效签名 URL 都能截到)。
        """
        import base64 as _b64
        import os as _os
        import cv2 as _cv2
        import numpy as _np
        import httpx as _httpx

        img_dir = _os.path.join(_os.getcwd(), 'temp_image')
        _os.makedirs(img_dir, exist_ok=True)
        local_path = _os.path.join(img_dir, f'{img_type}.jpg')

        # ===== 首选方案: 元素截图(直接抓取渲染后的 DOM 像素) =====
        # 这是唯一可靠的方法:无论 src 是 http/data URI/blob URL/已失效签名,
        # 只要元素在浏览器里渲染出来了,截图就能拿到真实图片像素。
        sel_map = {
            "bg": ["#captcha_verify_image", "#captcha-verify-image", "img.captcha_verify_img"],
            "gap": ["#captcha-verify_img_slide", "#captcha-verify-img-slide", "img.captcha_verify_img_slide"],
        }
        selectors = sel_map.get(img_type, [f"#captcha_verify_image"])
        for sel in selectors:
            try:
                el = await page_or_frame.query_selector(sel)
                if el:
                    # 确保元素可见且有尺寸
                    box = await el.bounding_box()
                    if box and box["width"] > 10 and box["height"] > 10:
                        shot_bytes = await el.screenshot()
                        if shot_bytes and len(shot_bytes) > 100:
                            image = _np.asarray(bytearray(shot_bytes), dtype="uint8")
                            image = _cv2.imdecode(image, _cv2.IMREAD_COLOR)
                            if image is not None and image.size > 0:
                                _cv2.imwrite(local_path, image)
                                utils.logger.info(
                                    f"[DouYinLogin._fetch_image] {img_type} got via element screenshot "
                                    f"(sel={sel}), shape={image.shape}, bytes={len(shot_bytes)}"
                                )
                                return local_path
                    utils.logger.warning(f"[DouYinLogin._fetch_image] {img_type} element found but invalid bbox: {box}")
            except Exception as e:
                utils.logger.warning(f"[DouYinLogin._fetch_image] {img_type} screenshot(sel={sel}) failed: {e}")

        # ===== 回退方案1: iframe 内 fetch(带浏览器 Cookie) =====
        _fetch_js = """
        async (url) => {
            try {
                const resp = await fetch(url, {credentials: 'include', cache: 'no-cache'});
                if (!resp.ok) return {error: 'HTTP ' + resp.status};
                const ct = resp.headers.get('content-type') || '';
                if (ct.indexOf('image') === -1) return {error: 'not image, ct=' + ct};
                const blob = await resp.blob();
                return new Promise((resolve) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve({data: reader.result, ct: ct});
                    reader.onerror = () => resolve({error: 'FileReader error'});
                    reader.readAsDataURL(blob);
                });
            } catch (e) {
                return {error: String(e)};
            }
        }
        """
        b64_data = None
        for attempt_ctx, label in [(page_or_frame, 'frame'), (self.context_page, 'main')]:
            try:
                result = await attempt_ctx.evaluate(_fetch_js, img_url)
                if isinstance(result, dict) and result.get('data'):
                    b64_data = result['data']
                    utils.logger.info(f"[DouYinLogin._fetch_image] {img_type} fetched via {label} browser ctx, ct={result.get('ct','')}")
                    break
                elif isinstance(result, dict) and result.get('error'):
                    utils.logger.warning(f"[DouYinLogin._fetch_image] {img_type} {label} fetch error: {result['error']}")
            except Exception as e:
                utils.logger.warning(f"[DouYinLogin._fetch_image] {img_type} {label} evaluate failed: {e}")

        # ===== 回退方案2: httpx 下载(仅在 content-type 为 image 时接受) =====
        if not b64_data and img_url and img_url.startswith('http'):
            try:
                headers = {
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": "https://rmc.bytedance.com/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
                img_res = _httpx.get(img_url, headers=headers, follow_redirects=True, timeout=10)
                ct = img_res.headers.get('content-type', '')
                utils.logger.info(f"[DouYinLogin._fetch_image] {img_type} httpx fallback: HTTP {img_res.status_code}, ct={ct}, len={len(img_res.content)}")
                if img_res.status_code == 200 and 'image' in ct:
                    b64_data = "data:" + ct + ";base64," + _b64.b64encode(img_res.content).decode('ascii')
            except Exception as e:
                utils.logger.warning(f"[DouYinLogin._fetch_image] {img_type} httpx fallback failed: {e}")

        if not b64_data:
            utils.logger.error(f"[DouYinLogin._fetch_image] {img_type} ALL methods failed (screenshot + fetch + httpx)")
            return local_path

        # 解析 base64 并保存为本地 jpg
        try:
            header, b64part = b64_data.split(',', 1)
            img_bytes = _b64.b64decode(b64part)
            image = _np.asarray(bytearray(img_bytes), dtype="uint8")
            image = _cv2.imdecode(image, _cv2.IMREAD_COLOR)
            if image is None:
                utils.logger.error(f"[DouYinLogin._fetch_image] {img_type} decoded but imdecode returned None")
                return local_path
            _cv2.imwrite(local_path, image)
            utils.logger.info(f"[DouYinLogin._fetch_image] {img_type} saved to {local_path}, shape={image.shape}")
            return local_path
        except Exception as e:
            utils.logger.error(f"[DouYinLogin._fetch_image] {img_type} save failed: {e}")
            return local_path

    async def login_by_cookies(self):
        utils.logger.info("[DouYinLogin.login_by_cookies] Begin login douyin by cookie ...")
        # 优先从 cookie_manager 获取最新 cookie（确保 Web UI 更新的 cookie 能被使用）
        try:
            from api.services.cookie_manager import get_cookie
            cookie_str = get_cookie("dy")
            utils.logger.info(f"[DouYinLogin.login_by_cookies] Got cookie from cookie_manager, length={len(cookie_str)}")
        except ImportError:
            cookie_str = ""
        
        if not cookie_str:
            # 回退：从环境变量 DY_COOKIES 加载抖音 Cookie
            dy_cookies_env = os.getenv("DY_COOKIES", "")
            cookie_str = dy_cookies_env if dy_cookies_env else self.cookie_str
        
        cookie_dict = utils.convert_str_cookie_to_dict(cookie_str)
        utils.logger.info(f"[DouYinLogin.login_by_cookies] Parsed {len(cookie_dict)} cookies")

        # Step 1: 先访问目标域名，确保页面上下文在 douyin.com 下
        utils.logger.info("[DouYinLogin.login_by_cookies] Navigating to douyin.com before adding cookies...")
        try:
            await self.context_page.goto("https://www.douyin.com", wait_until="domcontentloaded")
            await asyncio.sleep(1)
        except Exception as e:
            utils.logger.warning(f"[DouYinLogin.login_by_cookies] Initial goto failed: {e}")

        # Step 2: 清除旧的 cookie，然后设置新的 cookie
        # 即使使用持久化上下文，也要确保使用最新的 .env cookie
        is_persistent = config.SAVE_LOGIN_STATE
        utils.logger.info("[DouYinLogin.login_by_cookies] Clearing existing cookies before setting new ones...")
        try:
            await self.browser_context.clear_cookies()
            utils.logger.info("[DouYinLogin.login_by_cookies] Existing cookies cleared")
        except Exception as e:
            utils.logger.warning(f"[DouYinLogin.login_by_cookies] Failed to clear cookies: {e}")

        # Step 3: 使用 JavaScript document.cookie 设置 Cookie（更可靠，绕过 Playwright 的 Cookie 验证）
        utils.logger.info("[DouYinLogin.login_by_cookies] Setting cookies via JavaScript...")
        cookie_js_lines = []
        for key, value in cookie_dict.items():
            cleaned_value = value.replace('\n', '').replace('\r', '').strip()
            if not cleaned_value:
                continue
            # 对值进行编码，避免特殊字符破坏 JS 语法
            safe_value = cleaned_value.replace('\\', '\\\\').replace('"', '\\"')
            cookie_js_lines.append(f"document.cookie = '{key}={safe_value}; domain=.douyin.com; path=/';")

        js_code = "\n".join(cookie_js_lines)
        try:
            await self.context_page.evaluate(f"() => {{\n{js_code}\n}}")
            utils.logger.info(f"[DouYinLogin.login_by_cookies] JavaScript cookie setting executed")
        except Exception as e:
            utils.logger.warning(f"[DouYinLogin.login_by_cookies] JS cookie setting failed: {e}, falling back to add_cookies...")
            # Fallback: 使用 Playwright 的 add_cookies
            for key, value in cookie_dict.items():
                cleaned_value = value.replace('\n', '').replace('\r', '').strip()
                if not cleaned_value:
                    continue
                try:
                    await self.browser_context.add_cookies([{
                        'name': key,
                        'value': cleaned_value,
                        'domain': ".douyin.com",
                        'path': "/"
                    }])
                except Exception as e2:
                    utils.logger.warning(f"[DouYinLogin.login_by_cookies] Failed to add cookie {key}: {e2}, skipping...")

        # Step 4: 验证 Cookie 是否添加成功
        current_cookies = await self.browser_context.cookies()
        utils.logger.info(f"[DouYinLogin.login_by_cookies] Current browser cookies count: {len(current_cookies)}")
        for cookie in current_cookies:
            utils.logger.info(f"[DouYinLogin.login_by_cookies] Browser cookie: {cookie.get('name')}={cookie.get('value', '')[:20]}...")

        # Step 5: 刷新页面使 Cookie 生效
        utils.logger.info("[DouYinLogin.login_by_cookies] Reloading page to activate cookies...")
        try:
            await self.context_page.reload(wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            utils.logger.warning(f"[DouYinLogin.login_by_cookies] reload failed: {e}, trying goto...")
            try:
                await self.context_page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=60000)
            except Exception as e2:
                utils.logger.warning(f"[DouYinLogin.login_by_cookies] goto also failed: {e2}, continuing anyway...")

        # 等待页面完全加载稳定
        await asyncio.sleep(3)

        # Step 5.5: 检查是否遇到验证码页面 —— 优先绕过，实在绕不过才解滑块
        try:
            page_title = await self.context_page.title()
            page_url = self.context_page.url
            utils.logger.info(f"[DouYinLogin.login_by_cookies] After reload title: {page_title}, url: {page_url}")

            captcha_bypassed = False
            if "验证码" in page_title or "captcha" in page_url.lower():
                utils.logger.warning("[DouYinLogin.login_by_cookies] Captcha page detected, trying to bypass first...")

                # 策略1: 只尝试1次重新导航(多次反而触发更严风控)
                utils.logger.info("[DouYinLogin.login_by_cookies] Bypass attempt 1/1: re-navigating to douyin.com...")
                try:
                    await asyncio.sleep(random.uniform(3, 5))
                    await self.context_page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                    new_title = await self.context_page.title()
                    new_url = self.context_page.url
                    utils.logger.info(f"[DouYinLogin.login_by_cookies] Bypass result: title={new_title}, url={new_url}")
                    if "验证码" not in new_title and "captcha" not in new_url.lower():
                        captcha_bypassed = True
                        utils.logger.info("[DouYinLogin.login_by_cookies] Captcha bypassed via re-navigation!")
                except Exception as e:
                    utils.logger.warning(f"[DouYinLogin.login_by_cookies] Bypass attempt failed: {e}")

                # 策略2: 尝试通过抖音子页面绕过（有时首页触发验证码，子页面不会）
                if not captcha_bypassed:
                    bypass_urls = [
                        "https://www.douyin.com/foryou",
                        "https://www.douyin.com/discover",
                        "https://www.douyin.com/hot",
                    ]
                    for bypass_url in bypass_urls:
                        utils.logger.info(f"[DouYinLogin.login_by_cookies] Trying bypass via sub-page: {bypass_url}")
                        try:
                            await asyncio.sleep(random.uniform(2, 4))
                            await self.context_page.goto(bypass_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(3)
                            new_title = await self.context_page.title()
                            new_url = self.context_page.url
                            if "验证码" not in new_title and "captcha" not in new_url.lower():
                                captcha_bypassed = True
                                utils.logger.info(f"[DouYinLogin.login_by_cookies] Captcha bypassed via sub-page: {bypass_url}!")
                                break
                        except Exception as e:
                            utils.logger.warning(f"[DouYinLogin.login_by_cookies] Sub-page bypass failed: {e}")

                # 策略3: 实在绕不过，才尝试解滑块
                if not captcha_bypassed:
                    utils.logger.warning("[DouYinLogin.login_by_cookies] All bypass strategies failed, falling back to slider solving...")
                    try:
                        await self.check_page_display_slider(move_step=3, slider_level="hard")
                        utils.logger.info("[DouYinLogin.login_by_cookies] Captcha solved via slider, reloading...")
                        # 验证码通过后重新刷新页面
                        await self.context_page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=60000)
                        await asyncio.sleep(3)
                        page_title = await self.context_page.title()
                        utils.logger.info(f"[DouYinLogin.login_by_cookies] After captcha solve title: {page_title}")

                        # 检查是否还需要二次验证（短信/邮箱验证）
                        if "验证码" in page_title or "验证" in page_title:
                            utils.logger.error("[DouYinLogin.login_by_cookies] SECONDARY VERIFICATION REQUIRED!")
                            utils.logger.error("[DouYinLogin.login_by_cookies] 账号需要二次验证（短信/邮箱），请按以下步骤操作：")
                            utils.logger.error("[DouYinLogin.login_by_cookies] 1. 在本地有GUI的环境中运行：python3 -m media_platform.douyin.verify")
                            utils.logger.error("[DouYinLogin.login_by_cookies] 2. 或手动打开 https://www.douyin.com 完成验证")
                            utils.logger.error("[DouYinLogin.login_by_cookies] 3. 完成验证后更新cookie，再重新运行爬虫")
                            # 保存当前浏览器状态（即使未完全验证）
                            utils.logger.info("[DouYinLogin.login_by_cookies] Saving current browser state before exit...")
                            raise Exception("二次验证 Required: 请完成短信/邮箱验证后重试")
                    except Exception as e:
                        if "二次验证" in str(e):
                            raise
                        utils.logger.error(f"[DouYinLogin.login_by_cookies] Captcha solve failed: {e}")

                # 即使验证码中间页未绕过,也继续任务
                # 因为 HTTP API 请求使用 Cookie 直接调用,不依赖浏览器页面状态
                # (Cookie 有效时 API 能成功,浏览器首页风控不影响 API 请求)
                if not captcha_bypassed:
                    utils.logger.warning(
                        "[DouYinLogin.login_by_cookies] 验证码中间页未绕过,但继续任务 "
                        "(HTTP API 使用 Cookie 直接调用,不依赖浏览器页面状态)"
                    )
                    captcha_bypassed = True  # 标记为已处理,继续流程
            else:
                captcha_bypassed = True
        except Exception as e:
            if "二次验证" in str(e):
                raise
            utils.logger.warning(f"[DouYinLogin.login_by_cookies] Failed to check page title: {e}")

        # Step 6: 再次检查 Cookie
        try:
            current_cookies = await self.browser_context.cookies()
            utils.logger.info(f"[DouYinLogin.login_by_cookies] After reload cookies count: {len(current_cookies)}")
            cookie_names = [c.get('name') for c in current_cookies]
            utils.logger.info(f"[DouYinLogin.login_by_cookies] After reload cookie names: {cookie_names}")

            # 检查关键 Cookie
            cookie_dict_after = {c.get('name'): c.get('value') for c in current_cookies}
            utils.logger.info(f"[DouYinLogin.login_by_cookies] sessionid after reload: {'PRESENT' if cookie_dict_after.get('sessionid') else 'MISSING'}")
            utils.logger.info(f"[DouYinLogin.login_by_cookies] sid_guard after reload: {'PRESENT' if cookie_dict_after.get('sid_guard') else 'MISSING'}")
        except Exception as e:
            utils.logger.warning(f"[DouYinLogin.login_by_cookies] Failed to get cookies after reload: {e}")

        utils.logger.info("[DouYinLogin.login_by_cookies] Homepage loaded and stable")
