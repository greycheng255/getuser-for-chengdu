"""
平台账号管理服务 - PostgreSQL版本
管理用户在各平台的账号登录状态和Cookie
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
from postgresql_database import PostgreSQLDatabase, PG_CONFIG


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


class PlatformAccountServicePostgres:
    """
    平台账号管理服务 - PostgreSQL版本
    """

    def __init__(self, db: PostgreSQLDatabase = None):
        self.db = db or PostgreSQLDatabase(PG_CONFIG)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                # 平台账号表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS platform_accounts (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        platform VARCHAR(50) NOT NULL,
                        account_name VARCHAR(255),
                        cookies TEXT,
                        api_token TEXT,
                        api_secret TEXT,
                        refresh_token TEXT,
                        status VARCHAR(20) DEFAULT 'active',
                        is_active BOOLEAN DEFAULT TRUE,
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
                        id SERIAL PRIMARY KEY,
                        account_id INTEGER,
                        login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        login_method VARCHAR(50),
                        ip_address VARCHAR(100),
                        user_agent TEXT,
                        success BOOLEAN,
                        error_message TEXT
                    )
                ''')

                # 创建索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_platform_accounts_user_id ON platform_accounts(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_platform_accounts_platform ON platform_accounts(platform)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_platform_login_history_account_id ON platform_login_history(account_id)')

                conn.commit()
                print("✅ 平台账号PostgreSQL表初始化完成")

        except Exception as e:
            print(f"❌ 平台账号数据库初始化失败: {e}")
            raise e

    def get_user_accounts(self, user_id: int) -> List[Dict]:
        """获取用户的所有平台账号"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT id, user_id, platform, account_name, status, is_active,
                           last_login_time, last_publish_time, daily_limit, today_count,
                           created_at, updated_at
                    FROM platform_accounts
                    WHERE user_id = %s
                    ORDER BY platform
                ''', (user_id,))

                rows = cursor.fetchall()

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

        except Exception as e:
            print(f"获取用户账号失败: {e}")
            return []

    def get_account(self, user_id: int, platform: str) -> Optional[Dict]:
        """获取用户的指定平台账号"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT id, user_id, platform, account_name, cookies, api_token, api_secret,
                           refresh_token, status, is_active, last_login_time,
                           last_publish_time, cookie_expires_at, daily_limit, today_count
                    FROM platform_accounts
                    WHERE user_id = %s AND platform = %s
                ''', (user_id, platform))

                row = cursor.fetchone()
                if not row:
                    return None

                return {
                    'id': row[0],
                    'user_id': row[1],
                    'platform': row[2],
                    'account_name': row[3],
                    'cookies': row[4],
                    'api_token': row[5],
                    'api_secret': row[6],
                    'refresh_token': row[7],
                    'status': row[8],
                    'is_active': bool(row[9]),
                    'last_login_time': row[10],
                    'last_publish_time': row[11],
                    'cookie_expires_at': row[12],
                    'daily_limit': row[13],
                    'today_count': row[14]
                }

        except Exception as e:
            print(f"获取账号失败: {e}")
            return None

    def save_account(self, user_id: int, platform: str, account_data: Dict) -> Dict:
        """保存或更新平台账号"""
        try:
            print(f"[PlatformAccountServicePostgres] 保存账号 - user_id: {user_id}, platform: {platform}")
            print(f"[PlatformAccountServicePostgres] 账号数据: {account_data}")
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                # 检查是否已存在
                cursor.execute('''
                    SELECT id FROM platform_accounts
                    WHERE user_id = %s AND platform = %s
                ''', (user_id, platform))

                existing = cursor.fetchone()
                print(f"[PlatformAccountServicePostgres] 是否存在现有记录: {existing is not None}")

                # 确保 is_active 是布尔值
                is_active = account_data.get('is_active', True)
                if isinstance(is_active, int):
                    is_active = bool(is_active)
                print(f"[PlatformAccountServicePostgres] is_active 值: {is_active}")

                if existing:
                    # 更新现有记录
                    cursor.execute('''
                        UPDATE platform_accounts SET
                            account_name = %s,
                            cookies = %s,
                            api_token = %s,
                            api_secret = %s,
                            refresh_token = %s,
                            status = %s,
                            is_active = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = %s AND platform = %s
                    ''', (
                        account_data.get('account_name'),
                        account_data.get('cookies'),
                        account_data.get('api_token'),
                        account_data.get('api_secret'),
                        account_data.get('refresh_token'),
                        account_data.get('status', 'active'),
                        is_active,
                        user_id,
                        platform
                    ))
                    account_id = existing[0]
                    print(f"[PlatformAccountServicePostgres] 更新现有记录, account_id: {account_id}")
                else:
                    # 创建新记录
                    cursor.execute('''
                        INSERT INTO platform_accounts
                        (user_id, platform, account_name, cookies, api_token,
                         api_secret, refresh_token, status, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (
                        user_id,
                        platform,
                        account_data.get('account_name'),
                        account_data.get('cookies'),
                        account_data.get('api_token'),
                        account_data.get('api_secret'),
                        account_data.get('refresh_token'),
                        account_data.get('status', 'active'),
                        is_active
                    ))
                    account_id = cursor.fetchone()[0]
                    print(f"[PlatformAccountServicePostgres] 创建新记录, account_id: {account_id}")

                conn.commit()
                print(f"[PlatformAccountServicePostgres] 数据库提交成功")

                return {
                    'success': True,
                    'id': account_id,
                    'message': '账号保存成功'
                }

        except Exception as e:
            import traceback
            print(f"[PlatformAccountServicePostgres] 保存账号失败: {e}")
            print(traceback.format_exc())
            return {
                'success': False,
                'error': str(e)
            }

    def delete_account(self, user_id: int, platform: str) -> Dict:
        """删除平台账号"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    DELETE FROM platform_accounts
                    WHERE user_id = %s AND platform = %s
                ''', (user_id, platform))

                conn.commit()

                return {
                    'success': True,
                    'message': '账号删除成功'
                }

        except Exception as e:
            print(f"删除账号失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def update_cookies(self, user_id: int, platform: str, cookies: str,
                       expires_at: datetime = None) -> Dict:
        """更新Cookie"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE platform_accounts SET
                        cookies = %s,
                        cookie_expires_at = %s,
                        last_login_time = CURRENT_TIMESTAMP,
                        status = 'active',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND platform = %s
                ''', (cookies, expires_at, user_id, platform))

                conn.commit()

                return {
                    'success': True,
                    'message': 'Cookie更新成功'
                }

        except Exception as e:
            print(f"更新Cookie失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def record_login_history(self, account_id: int, login_method: str,
                     success: bool, error_message: str = None,
                     ip_address: str = None, user_agent: str = None):
        """记录登录历史"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT INTO platform_login_history
                    (account_id, login_method, success, error_message, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (account_id, login_method, success, error_message, ip_address, user_agent))

                conn.commit()

        except Exception as e:
            print(f"记录登录历史失败: {e}")

    def get_login_history(self, account_id: int, limit: int = 10) -> List[Dict]:
        """获取登录历史"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT id, login_time, login_method, success, error_message
                    FROM platform_login_history
                    WHERE account_id = %s
                    ORDER BY login_time DESC
                    LIMIT %s
                ''', (account_id, limit))

                rows = cursor.fetchall()

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

        except Exception as e:
            print(f"获取登录历史失败: {e}")
            return []

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
            expires_at = account['cookie_expires_at']
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))

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
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE platform_accounts SET
                        today_count = today_count + 1,
                        last_publish_time = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND platform = %s
                ''', (user_id, platform))

                conn.commit()

        except Exception as e:
            print(f"增加发布计数失败: {e}")

    def reset_daily_count(self):
        """重置每日计数（应在每天0点执行）"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE platform_accounts SET
                        today_count = 0,
                        updated_at = CURRENT_TIMESTAMP
                ''')

                conn.commit()
                print("✅ 每日发布计数已重置")

        except Exception as e:
            print(f"重置每日计数失败: {e}")

    def get_publish_limit(self, user_id: int, platform: str) -> Dict:
        """获取发布限制信息"""
        account = self.get_account(user_id, platform)

        if not account:
            return {
                'can_publish': False,
                'reason': '未绑定账号',
                'daily_limit': 5,
                'today_count': 0,
                'remaining': 0
            }

        daily_limit = account.get('daily_limit', 5)
        today_count = account.get('today_count', 0)
        remaining = max(0, daily_limit - today_count)

        return {
            'can_publish': remaining > 0 and account.get('is_active', False),
            'reason': None if remaining > 0 else '今日发布次数已达上限',
            'daily_limit': daily_limit,
            'today_count': today_count,
            'remaining': remaining
        }


# 全局实例
platform_account_service_postgres = PlatformAccountServicePostgres()
