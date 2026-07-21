# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/x_twitter/login.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1


import asyncio
import json
import os
from typing import Optional

from playwright.async_api import BrowserContext, Page

from base.base_crawler import AbstractLogin
from tools import utils


class XTwitterLogin(AbstractLogin):

    def __init__(
        self,
        login_type: str = "cookie",
        login_phone: str = "",
        browser_context: BrowserContext = None,
        context_page: Page = None,
        cookie_str: str = "",
    ):
        self.login_type = login_type
        self.login_phone = login_phone
        self.browser_context = browser_context
        self.context_page = context_page
        self.cookie_str = cookie_str
        self.logger = utils.logger

    async def begin(self):
        if self.login_type == "cookie":
            await self.login_by_cookies()
        elif self.login_type == "qrcode":
            await self.login_by_qrcode()
        elif self.login_type == "phone":
            await self.login_by_mobile()
        else:
            self.logger.error(f"[XTwitterLogin] Unsupported login type: {self.login_type}")
            raise ValueError(f"Unsupported login type: {self.login_type}")

    async def login_by_qrcode(self):
        self.logger.info("[XTwitterLogin] Starting QR code login...")
        await self.context_page.goto("https://x.com/i/flow/login", wait_until="networkidle", timeout=30000)
        
        await asyncio.sleep(2)
        
        try:
            qr_code_selector = 'div[data-testid="QRCode"]'
            await self.context_page.wait_for_selector(qr_code_selector, timeout=10000)
            self.logger.info("[XTwitterLogin] QR code displayed, please scan to login")
            
            logged_in = False
            for _ in range(60):
                try:
                    await self.context_page.wait_for_selector('div[data-testid="SideNav_NewTweet_Button"]', timeout=3000)
                    logged_in = True
                    break
                except:
                    await asyncio.sleep(2)
            
            if logged_in:
                self.logger.info("[XTwitterLogin] QR code login successful")
            else:
                self.logger.error("[XTwitterLogin] QR code login timeout")
                raise Exception("QR code login timeout")
        except Exception as e:
            self.logger.error(f"[XTwitterLogin] QR code login failed: {e}")
            raise

    async def login_by_mobile(self):
        self.logger.info("[XTwitterLogin] Starting mobile login...")
        await self.context_page.goto("https://x.com/i/flow/login", wait_until="networkidle", timeout=30000)
        
        await asyncio.sleep(2)
        
        try:
            phone_input = await self.context_page.wait_for_selector('input[name="text"]', timeout=10000)
            await phone_input.fill(self.login_phone)
            
            next_btn = await self.context_page.wait_for_selector('div[data-testid="LoginForm_Login_Button"]', timeout=5000)
            await next_btn.click()
            
            await asyncio.sleep(3)
            
            self.logger.info("[XTwitterLogin] Please enter verification code manually")
            
            for _ in range(120):
                try:
                    await self.context_page.wait_for_selector('div[data-testid="SideNav_NewTweet_Button"]', timeout=3000)
                    self.logger.info("[XTwitterLogin] Mobile login successful")
                    return
                except:
                    await asyncio.sleep(2)
            
            self.logger.error("[XTwitterLogin] Mobile login timeout")
            raise Exception("Mobile login timeout")
        except Exception as e:
            self.logger.error(f"[XTwitterLogin] Mobile login failed: {e}")
            raise

    async def login_by_cookies(self):
        self.logger.info("[XTwitterLogin] Starting cookie login...")
        
        if not self.cookie_str:
            self.logger.warning("[XTwitterLogin] No cookies provided, skipping")
            return
        
        try:
            cookie_list = []
            for cookie_pair in self.cookie_str.split(";"):
                cookie_pair = cookie_pair.strip()
                if "=" in cookie_pair:
                    key, value = cookie_pair.split("=", 1)
                    cookie_list.append({
                        "name": key.strip(),
                        "value": value.strip(),
                        "domain": ".x.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                    })
            
            await self.browser_context.add_cookies(cookie_list)
            self.logger.info(f"[XTwitterLogin] Added {len(cookie_list)} cookies")
            
            await self.context_page.goto("https://x.com/home", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
            
            if await self._is_logged_in():
                self.logger.info("[XTwitterLogin] Cookie login successful")
            else:
                self.logger.warning("[XTwitterLogin] Cookie login may have failed, checking again...")
                await asyncio.sleep(5)
                if await self._is_logged_in():
                    self.logger.info("[XTwitterLogin] Cookie login successful after refresh")
                else:
                    self.logger.warning("[XTwitterLogin] Cookie login verification failed")
                    
        except Exception as e:
            self.logger.error(f"[XTwitterLogin] Cookie login failed: {e}")
            raise

    async def _is_logged_in(self) -> bool:
        try:
            await self.context_page.wait_for_selector('div[data-testid="SideNav_NewTweet_Button"]', timeout=5000)
            return True
        except:
            try:
                await self.context_page.wait_for_selector('a[href="/compose/tweet"]', timeout=3000)
                return True
            except:
                return False