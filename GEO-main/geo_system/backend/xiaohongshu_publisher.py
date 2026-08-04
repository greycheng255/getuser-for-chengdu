"""
小红书自动发布模块
使用Playwright模拟浏览器操作实现自动发布
"""

import asyncio
import json
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class XiaohongshuPublisher:
    """小红书发布器"""

    def __init__(self, cookies: str):
        self.cookies = cookies
        self.web_session = cookies

    async def publish_note(self, title: str, content: str, keywords: list = None) -> Dict:
        """
        发布小红书笔记

        由于小红书API有签名验证，这里提供手动发布指导
        """
        try:
            # 检查Cookie是否有效（仅用于提示，不阻止发布）
            is_valid = await self._check_cookie_valid()
            
            cookie_status = "有效" if is_valid else "可能已过期"
            logger.info(f"Cookie状态: {cookie_status}")

            # 由于小红书有严格的反爬虫机制和签名验证
            # 无法实现真正的API自动发布
            # 返回手动发布指导
            
            # 格式化内容
            formatted_content = content[:500] + "..." if len(content) > 500 else content
            
            # 添加话题标签
            tags = ""
            if keywords:
                tags = " ".join([f"#{kw}" for kw in keywords[:5]])
            
            return {
                'success': False,
                'error': '小红书暂不支持API自动发布',
                'platform': 'xiaohongshu',
                'cookie_status': cookie_status,
                'manual_guide': f'''
📱 小红书手动发布指南

由于小红书有严格的反爬虫保护，请手动发布：

1️⃣ 访问 https://creator.xiaohongshu.com/
2️⃣ 点击"发布笔记"
3️⃣ 填写以下内容：

━━━━━━━━━━━━━━━━━━━━
📌 标题：{title[:20]}

📝 内容：
{formatted_content}

🏷️ 话题：{tags}
━━━━━━━━━━━━━━━━━━━━

💡 提示：{cookie_status}，如无法登录请重新获取Cookie
                '''.strip(),
                'suggestion': '如需自动发布，建议使用Playwright浏览器自动化方案'
            }

        except Exception as e:
            logger.error(f"小红书发布失败: {str(e)}")
            return {
                'success': False,
                'error': f'发布异常: {str(e)}',
                'platform': 'xiaohongshu'
            }

    async def _check_cookie_valid(self) -> bool:
        """检查Cookie是否有效"""
        try:
            import aiohttp

            # 如果Cookie为空或太短，直接返回False
            if not self.web_session or len(self.web_session) < 10:
                logger.warning("Cookie为空或太短")
                return False

            async with aiohttp.ClientSession() as session:
                cookies = {'web_session': self.web_session}
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'zh-CN,zh;q=0.9',
                    'Referer': 'https://creator.xiaohongshu.com/',
                    'Origin': 'https://creator.xiaohongshu.com',
                }

                # 访问创作者中心检查登录状态
                async with session.get(
                    'https://creator.xiaohongshu.com/api/user/info',
                    cookies=cookies,
                    headers=headers,
                    timeout=10,
                    ssl=False  # 忽略SSL证书验证
                ) as response:
                    logger.info(f"检查Cookie响应状态: {response.status}")
                    response_text = await response.text()
                    logger.info(f"检查Cookie响应内容: {response_text[:200]}")
                    
                    if response.status == 200:
                        try:
                            data = json.loads(response_text)
                            is_valid = data.get('success') or data.get('data') is not None
                            logger.info(f"Cookie有效性: {is_valid}")
                            return is_valid
                        except:
                            logger.warning(f"解析响应失败: {response_text[:100]}")
                            return False
                    else:
                        logger.warning(f"Cookie检查返回非200状态码: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"检查Cookie有效性失败: {str(e)}")
            return False

    async def get_user_info(self) -> Dict:
        """获取用户信息"""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                cookies = {'web_session': self.web_session}
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://creator.xiaohongshu.com/',
                }

                async with session.get(
                    'https://creator.xiaohongshu.com/api/user/info',
                    cookies=cookies,
                    headers=headers,
                    timeout=10
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return {'success': False, 'error': f'HTTP {response.status}'}

        except Exception as e:
            return {'success': False, 'error': str(e)}


# 同步包装函数
def publish_to_xiaohongshu_sync(title: str, content: str, cookies: str, keywords: list = None) -> Dict:
    """同步方式发布到小红书"""
    publisher = XiaohongshuPublisher(cookies)
    return asyncio.run(publisher.publish_note(title, content, keywords))


def check_xiaohongshu_cookie(cookies: str) -> bool:
    """检查小红书Cookie是否有效"""
    publisher = XiaohongshuPublisher(cookies)
    return asyncio.run(publisher._check_cookie_valid())
