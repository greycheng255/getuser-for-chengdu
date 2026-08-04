"""
平台账号管理服务
管理用户在各平台的账号登录状态和Cookie
"""

import sqlite3
import json
import time
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class PlatformType(Enum):
    """支持的平台类型"""
    ZHIHU = "zhihu"                    # 知乎
    XIAOHONGSHU = "xiaohongshu"        # 小红书
    WEIBO = "weibo"                    # 微博
    WECHAT_PUBLIC = "wechat_public"    # 微信公众号
    TOUTIAO = "toutiao"                # 今日头条
    BAIJIAHAO = "baijiahao"            # 百家号
    DOUYIN = "douyin"                  # 抖音
    BILIBILI = "bilibili"              # B站
    WEBSITE_BLOG = "website_blog"      # 官网博客
    WEBSITE_FAQ = "website_faq"        # 官网FAQ


class AccountStatus(Enum):
    """账号状态"""
    ACTIVE = "active"          # 正常
    EXPIRED = "expired"        # 已过期
    INVALID = "invalid"        # 无效
    NEED_LOGIN = "need_login"  # 需要重新登录


@dataclass
class PlatformAccount:
    """平台账号信息"""
    id: int = None
    user_id: int = None
    platform: str = None
    account_name: str = None
    cookies: str = None
    api_token: str = None
    refresh_token: str = None
    status: str = "active"
    is_active: bool = True
    last_login_time: datetime = None
    last_publish_time: datetime = None
    cookie_expires_at: datetime = None
    daily_limit: int = 5
    today_count: int = 0
    created_at: datetime = None
    updated_at: datetime = None


class PlatformAccountService:
    """
    平台账号管理服务
    """

    def __init__(self, db_path: str = "publish.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='platform_accounts'")
        table_exists = cursor.fetchone()

        if table_exists:
            # 检查是否需要升级表结构
            cursor.execute("PRAGMA table_info(platform_accounts)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # 如果缺少user_id列，删除旧表重新创建
            if 'user_id' not in columns:
                cursor.execute("DROP TABLE platform_accounts")
                cursor.execute("DROP TABLE IF EXISTS platform_login_history")
                table_exists = False

        # 平台账号表 - 扩展版本
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS platform_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                account_name TEXT,
                cookies TEXT,
                api_token TEXT,
                refresh_token TEXT,
                status TEXT DEFAULT 'active',
                is_active BOOLEAN DEFAULT 1,
                last_login_time TIMESTAMP,
                last_publish_time TIMESTAMP,
                cookie_expires_at TIMESTAMP,
                daily_limit INTEGER DEFAULT 5,
                today_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, platform)
            )
        ''')

        # 登录历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS platform_login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                login_method TEXT,
                ip_address TEXT,
                user_agent TEXT,
                success BOOLEAN,
                error_message TEXT,
                FOREIGN KEY (account_id) REFERENCES platform_accounts(id)
            )
        ''')

        conn.commit()
        conn.close()

    def get_user_accounts(self, user_id: int) -> List[Dict]:
        """获取用户的所有平台账号"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, user_id, platform, account_name, status, is_active,
                   last_login_time, last_publish_time, daily_limit, today_count,
                   created_at, updated_at
            FROM platform_accounts
            WHERE user_id = ?
            ORDER BY platform
        ''', (user_id,))

        rows = cursor.fetchall()
        conn.close()

        accounts = []
        for row in rows:
            accounts.append({
                'id': row[0],
                'user_id': row[1],
                'platform': row[2],
                'account_name': row[3],
                'status': row[4],
                'is_active': bool(row[5]),
                'last_login_time': row[6],
                'last_publish_time': row[7],
                'daily_limit': row[8],
                'today_count': row[9],
                'created_at': row[10],
                'updated_at': row[11]
            })

        return accounts

    def get_account(self, user_id: int, platform: str) -> Optional[Dict]:
        """获取用户的指定平台账号"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM platform_accounts
            WHERE user_id = ? AND platform = ? AND is_active = 1
            LIMIT 1
        ''', (user_id, platform))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return self._row_to_dict(row)

    def save_account(self, user_id: int, platform: str, account_data: Dict) -> Dict:
        """保存或更新平台账号"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"[PlatformAccountService] 保存账号 - user_id: {user_id}, platform: {platform}")
        logger.info(f"[PlatformAccountService] 账号数据: {account_data}")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 检查是否已存在
        cursor.execute('''
            SELECT id FROM platform_accounts
            WHERE user_id = ? AND platform = ?
        ''', (user_id, platform))

        existing = cursor.fetchone()
        now = datetime.now()
        logger.info(f"[PlatformAccountService] 是否存在现有记录: {existing is not None}")

        # 确保 is_active 是整数 1 或 0
        is_active = 1 if account_data.get('is_active', True) else 0
        logger.info(f"[PlatformAccountService] is_active 值: {is_active}")
        
        if existing:
            # 更新
            cursor.execute('''
                UPDATE platform_accounts SET
                    account_name = ?,
                    cookies = ?,
                    api_token = ?,
                    refresh_token = ?,
                    status = ?,
                    is_active = ?,
                    last_login_time = ?,
                    cookie_expires_at = ?,
                    updated_at = ?
                WHERE user_id = ? AND platform = ?
            ''', (
                account_data.get('account_name'),
                account_data.get('cookies'),
                account_data.get('api_token'),
                account_data.get('refresh_token'),
                account_data.get('status', 'active'),
                is_active,
                account_data.get('last_login_time', now),
                account_data.get('cookie_expires_at'),
                now,
                user_id,
                platform
            ))
            account_id = existing[0]
        else:
            # 插入新记录
            cursor.execute('''
                INSERT INTO platform_accounts
                (user_id, platform, account_name, cookies, api_token, refresh_token,
                 status, is_active, last_login_time, cookie_expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                platform,
                account_data.get('account_name'),
                account_data.get('cookies'),
                account_data.get('api_token'),
                account_data.get('refresh_token'),
                account_data.get('status', 'active'),
                is_active,
                account_data.get('last_login_time', now),
                account_data.get('cookie_expires_at'),
                now,
                now
            ))
            account_id = cursor.lastrowid

        conn.commit()
        logger.info(f"[PlatformAccountService] 数据库提交成功, account_id: {account_id}")
        
        # 验证保存是否成功
        cursor.execute('''
            SELECT id, platform, account_name, is_active FROM platform_accounts
            WHERE id = ?
        ''', (account_id,))
        verify_row = cursor.fetchone()
        logger.info(f"[PlatformAccountService] 验证保存结果: {verify_row}")
        
        conn.close()

        return {
            'success': True,
            'account_id': account_id,
            'message': '账号保存成功'
        }

    def delete_account(self, user_id: int, platform: str) -> Dict:
        """删除平台账号"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM platform_accounts
            WHERE user_id = ? AND platform = ?
        ''', (user_id, platform))

        conn.commit()
        conn.close()

        return {
            'success': True,
            'message': '账号已删除'
        }

    def update_cookies(self, user_id: int, platform: str, cookies: str, 
                       expires_at: datetime = None) -> Dict:
        """更新Cookie"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE platform_accounts SET
                cookies = ?,
                cookie_expires_at = ?,
                status = 'active',
                updated_at = ?
            WHERE user_id = ? AND platform = ?
        ''', (cookies, expires_at, datetime.now(), user_id, platform))

        conn.commit()
        conn.close()

        return {
            'success': True,
            'message': 'Cookie已更新'
        }

    def record_login(self, account_id: int, login_method: str, 
                     success: bool, error_message: str = None,
                     ip_address: str = None, user_agent: str = None):
        """记录登录历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO platform_login_history
            (account_id, login_method, ip_address, user_agent, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (account_id, login_method, ip_address, user_agent, success, error_message))

        conn.commit()
        conn.close()

    def get_login_history(self, account_id: int, limit: int = 10) -> List[Dict]:
        """获取登录历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, login_time, login_method, success, error_message
            FROM platform_login_history
            WHERE account_id = ?
            ORDER BY login_time DESC
            LIMIT ?
        ''', (account_id, limit))

        rows = cursor.fetchall()
        conn.close()

        history = []
        for row in rows:
            history.append({
                'id': row[0],
                'login_time': row[1],
                'login_method': row[2],
                'success': bool(row[3]),
                'error_message': row[4]
            })

        return history

    def check_account_status(self, user_id: int, platform: str) -> Dict:
        """检查账号状态"""
        account = self.get_account(user_id, platform)

        if not account:
            return {
                'configured': False,
                'status': 'not_configured',
                'message': '未配置账号'
            }

        # 检查Cookie是否过期
        if account.get('cookie_expires_at'):
            expires_at = datetime.fromisoformat(account['cookie_expires_at'].replace('Z', '+00:00'))
            if expires_at < datetime.now():
                return {
                    'configured': True,
                    'status': 'expired',
                    'message': 'Cookie已过期，需要重新登录'
                }

        # 检查今日发布次数
        if account.get('today_count', 0) >= account.get('daily_limit', 5):
            return {
                'configured': True,
                'status': 'limit_reached',
                'message': '今日发布次数已达上限'
            }

        return {
            'configured': True,
            'status': account.get('status', 'active'),
            'message': '账号正常',
            'account_name': account.get('account_name'),
            'last_login_time': account.get('last_login_time'),
            'today_count': account.get('today_count', 0),
            'daily_limit': account.get('daily_limit', 5)
        }

    def increment_publish_count(self, user_id: int, platform: str):
        """增加今日发布计数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE platform_accounts SET
                today_count = today_count + 1,
                last_publish_time = ?,
                updated_at = ?
            WHERE user_id = ? AND platform = ?
        ''', (datetime.now(), datetime.now(), user_id, platform))

        conn.commit()
        conn.close()

    def reset_daily_count(self):
        """重置每日计数（应在每天0点执行）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE platform_accounts SET today_count = 0
        ''')

        conn.commit()
        conn.close()

    def _row_to_dict(self, row) -> Dict:
        """将数据库行转换为字典"""
        columns = [
            'id', 'user_id', 'platform', 'account_name', 'cookies', 'api_token',
            'refresh_token', 'status', 'is_active', 'last_login_time',
            'last_publish_time', 'cookie_expires_at', 'daily_limit', 'today_count',
            'created_at', 'updated_at'
        ]

        result = {}
        for i, col in enumerate(columns):
            if i < len(row):
                result[col] = row[i]

        return result


# 平台登录辅助工具
class PlatformLoginHelper:
    """
    平台登录辅助工具
    提供各平台的登录指导和Cookie获取方法
    """

    PLATFORM_GUIDES = {
        'zhihu': {
            'name': '知乎',
            'login_url': 'https://www.zhihu.com/signin',
            'cookie_names': ['z_c0', '_xsrf', 'q_c1'],
            'guide': '''
                知乎登录步骤：
                1. 访问 https://www.zhihu.com/signin
                2. 使用扫码或密码登录
                3. 登录成功后，按F12打开开发者工具
                4. 切换到Application/应用标签
                5. 在左侧选择Cookies -> https://www.zhihu.com
                6. 复制z_c0字段的值（这是最重要的登录凭证）
                7. 粘贴到下方输入框
            ''',
            'tips': [
                'z_c0是知乎的核心登录凭证，有效期约1个月',
                '建议定期更新Cookie以确保发布功能正常',
                '请勿泄露z_c0给他人，否则可能导致账号被盗'
            ]
        },
        'xiaohongshu': {
            'name': '小红书',
            'login_url': 'https://creator.xiaohongshu.com/',
            'cookie_names': ['web_session', 'access-token', 'x-user-id', 'customer-sso-sid', 'webId'],
            'guide': '''
                小红书登录步骤：
                1. 访问 https://creator.xiaohongshu.com/
                2. 使用手机号或扫码登录创作者平台
                3. 登录成功后，按F12打开开发者工具
                4. 切换到Application/应用标签
                5. 复制所有Cookie（推荐复制为JSON格式）
                6. 粘贴到下方输入框
            ''',
            'tips': [
                '小红书需要创作者平台权限',
                '新注册账号可能需要等待审核才能发布',
                '支持的认证字段：web_session、access-token、x-user-id、customer-sso-sid',
                '建议复制完整的Cookie JSON数组以确保兼容性'
            ]
        },
        'weibo': {
            'name': '微博',
            'login_url': 'https://weibo.com/login.php',
            'cookie_names': ['SUB', 'SUBP', 'SCF'],
            'guide': '''
                微博登录步骤：
                1. 访问 https://weibo.com/login.php
                2. 使用账号密码或扫码登录
                3. 登录成功后，按F12打开开发者工具
                4. 切换到Application/应用标签
                5. 复制SUB字段的值
                6. 粘贴到下方输入框
            ''',
            'tips': [
                'SUB是微博的核心登录凭证',
                '微博有严格的反爬虫机制，请合理控制发布频率',
                '建议使用微博开放平台API进行发布（更稳定）'
            ]
        },
        'bilibili': {
            'name': 'Bilibili',
            'login_url': 'https://passport.bilibili.com/login',
            'cookie_names': ['SESSDATA', 'bili_jct', 'DedeUserID'],
            'guide': '''
                B站登录步骤：
                1. 访问 https://passport.bilibili.com/login
                2. 使用账号密码或扫码登录
                3. 登录成功后，按F12打开开发者工具
                4. 切换到Application/应用标签
                5. 复制SESSDATA和bili_jct字段的值
                6. 粘贴到下方输入框（格式：SESSDATA=xxx; bili_jct=yyy）
            ''',
            'tips': [
                'SESSDATA是B站的核心登录凭证',
                'bili_jct用于CSRF防护',
                '建议同时提供这两个字段'
            ]
        },
        'douyin': {
            'name': '抖音',
            'login_url': 'https://creator.douyin.com/',
            'cookie_names': ['sessionid', 'sessionid_ss'],
            'guide': '''
                抖音登录步骤：
                1. 访问 https://creator.douyin.com/
                2. 使用手机号或扫码登录创作者平台
                3. 登录成功后，按F12打开开发者工具
                4. 切换到Application/应用标签
                5. 复制sessionid字段的值
                6. 粘贴到下方输入框
            ''',
            'tips': [
                '需要抖音创作者平台权限',
                'sessionid是核心登录凭证',
                '抖音对自动化发布有较严格的限制'
            ]
        }
    }

    @classmethod
    def get_login_guide(cls, platform: str) -> Dict:
        """获取平台登录指导"""
        return cls.PLATFORM_GUIDES.get(platform, {
            'name': platform,
            'guide': '暂无详细指导，请手动登录后获取Cookie',
            'tips': ['请确保登录状态有效']
        })

    @classmethod
    def get_all_platforms(cls) -> List[Dict]:
        """获取所有支持的平台列表"""
        platforms = []
        for key, value in cls.PLATFORM_GUIDES.items():
            platforms.append({
                'id': key,
                'name': value['name'],
                'login_url': value['login_url']
            })
        return platforms
