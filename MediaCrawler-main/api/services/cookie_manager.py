# -*- coding: utf-8 -*-
"""统一的 Cookie 管理模块

所有 Cookie 的保存和获取都通过此模块，确保：
1. 保存时同时更新内存和 .env 文件
2. 获取时优先从内存读取，如果内存没有则从 .env 文件加载
3. 所有平台使用一致的格式
4. .env 文件外部修改后，内存缓存自动刷新
"""
import os
import time
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# 平台 Cookie 环境变量名映射
PLATFORM_ENV_KEYS = {
    "xhs": "XHS_COOKIES",
    "dy": "DY_COOKIES",
    "ks": "KS_COOKIES",
    "bili": "BILI_COOKIES",
    "wb": "WB_COOKIES",
    "x_twitter": "X_TWITTER_COOKIES",
}

# 内存缓存
cookie_cache: Dict[str, str] = {}

# 记录 .env 文件最后加载的修改时间（用于检测外部修改）
_env_file_mtime: float = 0.0


def _get_env_mtime() -> float:
    """获取 .env 文件修改时间"""
    if ENV_FILE.exists():
        return ENV_FILE.stat().st_mtime
    return 0.0


def _ensure_env_loaded():
    """确保 .env 文件已加载到环境变量"""
    global _env_file_mtime
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=True)
        _env_file_mtime = _get_env_mtime()


def _check_env_updated() -> bool:
    """检查 .env 文件是否被外部修改过"""
    global _env_file_mtime
    current_mtime = _get_env_mtime()
    if current_mtime > _env_file_mtime:
        return True
    return False


def get_cookie(platform: str) -> str:
    """
    获取指定平台的 Cookie

    获取逻辑：
    1. 先检查 .env 文件是否被外部修改过，如果是则重新加载
    2. 从内存缓存获取
    3. 从环境变量获取
    4. 从 .env 文件重新加载

    Args:
        platform: 平台标识，如 "dy", "xhs", "bili"

    Returns:
        Cookie 字符串，如果没有则返回空字符串
    """
    env_key = PLATFORM_ENV_KEYS.get(platform)
    if not env_key:
        return ""

    # 1. 检查 .env 文件是否被外部修改过，如果是则清空缓存重新加载
    if _check_env_updated():
        cookie_cache.clear()
        _ensure_env_loaded()

    # 2. 从内存缓存获取
    if platform in cookie_cache:
        return cookie_cache[platform]

    # 3. 从环境变量获取
    cookie = os.environ.get(env_key, "")
    if cookie:
        cookie_cache[platform] = cookie
        return cookie

    # 4. 重新加载 .env 文件并获取
    _ensure_env_loaded()
    cookie = os.environ.get(env_key, "")
    if cookie:
        cookie_cache[platform] = cookie

    return cookie


def set_cookie(platform: str, cookie_str: str) -> bool:
    """
    设置指定平台的 Cookie
    
    操作：
    1. 更新内存缓存
    2. 更新环境变量
    3. 写入 .env 文件（持久化）
    
    Args:
        platform: 平台标识，如 "dy", "xhs", "bili"
        cookie_str: Cookie 字符串
    
    Returns:
        是否成功
    """
    env_key = PLATFORM_ENV_KEYS.get(platform)
    if not env_key:
        return False
    
    # 1. 更新内存缓存
    cookie_cache[platform] = cookie_str
    
    # 2. 更新环境变量
    os.environ[env_key] = cookie_str
    
    # 3. 写入 .env 文件
    try:
        _update_env_file(env_key, cookie_str)
        # 更新文件修改时间记录，避免下次获取时误判为外部修改
        global _env_file_mtime
        _env_file_mtime = _get_env_mtime()
        return True
    except Exception as e:
        print(f"[CookieManager] Failed to write .env file: {e}")
        return False


def _update_env_file(env_key: str, value: str) -> None:
    """
    更新 .env 文件中的指定变量
    
    Args:
        env_key: 环境变量名，如 "DY_COOKIES"
        value: 新的值
    """
    lines = []
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
    
    # 构建新的内容
    new_lines = []
    found = False
    
    for line in lines:
        if line.startswith(f"{env_key}=") or line.startswith(f'{env_key}='):
            # 用双引号包裹值，避免特殊字符（如 #）导致 dotenv 解析错误
            new_lines.append(f'{env_key}="{value}"')
            found = True
        else:
            new_lines.append(line)
    
    if not found:
        new_lines.append(f'{env_key}="{value}"')
    
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")


def get_all_cookies() -> Dict[str, Dict]:
    """
    获取所有平台的 Cookie 状态

    Returns:
        字典，键为平台标识，值为包含 has_cookie、cookie_length 等信息的字典
    """
    result = {}

    # 检查 .env 文件是否被外部修改过，如果是则重新加载
    if _check_env_updated():
        cookie_cache.clear()
        _ensure_env_loaded()

    for platform, env_key in PLATFORM_ENV_KEYS.items():
        # 优先从内存缓存获取
        cookie = cookie_cache.get(platform, "")
        if not cookie:
            cookie = os.environ.get(env_key, "")
            if cookie:
                cookie_cache[platform] = cookie

        result[platform] = {
            "platform": platform,
            "has_cookie": bool(cookie),
            "cookie_length": len(cookie),
        }

    return result


def clear_cookie_cache():
    """清空内存缓存（通常在需要重新加载时使用）"""
    cookie_cache.clear()


# ============================================================
# 多Cookie池支持（向后兼容）
# ============================================================
# .env 中配置多个Cookie，用 ||| 分隔
# 例如: DY_COOKIES_POOL="cookie1|||cookie2|||cookie3"
# 如果未配置 DY_COOKIES_POOL，则自动从 DY_COOKIES 构建（单Cookie模式）

_cookie_pool_cache: Dict[str, List[str]] = {}

# 多Cookie池环境变量名
PLATFORM_POOL_KEYS = {
    "xhs": "XHS_COOKIES_POOL",
    "dy": "DY_COOKIES_POOL",
    "ks": "KS_COOKIES_POOL",
    "bili": "BILI_COOKIES_POOL",
    "wb": "WB_COOKIES_POOL",
    "x_twitter": "X_TWITTER_COOKIES_POOL",
}

COOKIE_DELIMITER = "|||"


def get_cookie_pool(platform: str) -> List[str]:
    """获取指定平台的Cookie池（多个Cookie列表）

    获取逻辑：
    1. 先从 DY_COOKIES_POOL 等多Cookie环境变量获取
    2. 如果未配置，从 DY_COOKIES 单Cookie环境变量构建（兼容旧配置）

    Args:
        platform: 平台标识，如 "dy", "xhs", "bili"

    Returns:
        Cookie字符串列表，空列表表示没有Cookie
    """
    pool_key = PLATFORM_POOL_KEYS.get(platform)
    single_cookie = get_cookie(platform)

    # 1. 先尝试从Cookie池环境变量获取
    if pool_key:
        if _check_env_updated():
            _cookie_pool_cache.clear()
            _ensure_env_loaded()

        if platform in _cookie_pool_cache:
            return _cookie_pool_cache[platform]

        pool_str = os.environ.get(pool_key, "")
        if pool_str:
            cookies = [c.strip() for c in pool_str.split(COOKIE_DELIMITER) if c.strip()]
            if cookies:
                _cookie_pool_cache[platform] = cookies
                return cookies

    # 2. 兼容旧配置：从单Cookie构建
    if single_cookie:
        return [single_cookie]

    return []


def set_cookie_pool(platform: str, cookies: List[str]) -> bool:
    """设置指定平台的Cookie池

    Args:
        platform: 平台标识
        cookies: Cookie字符串列表

    Returns:
        是否成功
    """
    pool_key = PLATFORM_POOL_KEYS.get(platform)
    if not pool_key:
        return False

    # 更新内存缓存
    _cookie_pool_cache[platform] = cookies

    # 更新环境变量
    pool_str = COOKIE_DELIMITER.join(cookies)
    os.environ[pool_key] = pool_str

    # 写入 .env 文件
    try:
        _update_env_file(pool_key, pool_str)
        global _env_file_mtime
        _env_file_mtime = _get_env_mtime()
        return True
    except Exception as e:
        print(f"[CookieManager] Failed to write cookie pool to .env: {e}")
        return False


def add_cookie_to_pool(platform: str, cookie: str) -> bool:
    """添加单个Cookie到池中（去重）"""
    if not cookie:
        return False
    pool = get_cookie_pool(platform)
    if cookie not in pool:
        pool.append(cookie)
        return set_cookie_pool(platform, pool)
    return True


def remove_cookie_from_pool(platform: str, cookie: str) -> bool:
    """从池中移除指定Cookie"""
    pool = get_cookie_pool(platform)
    if cookie in pool:
        pool.remove(cookie)
        return set_cookie_pool(platform, pool)
    return False


def get_cookie_pool_status() -> Dict[str, Dict]:
    """获取所有平台的Cookie池状态"""
    result = {}
    for platform in PLATFORM_POOL_KEYS:
        pool = get_cookie_pool(platform)
        result[platform] = {
            "platform": platform,
            "pool_size": len(pool),
            "valid_count": sum(1 for c in pool if _check_cookie_has_session(platform, c)),
            "invalid_count": sum(1 for c in pool if not _check_cookie_has_session(platform, c)),
            "cookies": [
                {
                    "index": i,
                    "cookie_length": len(c),
                    "cookie_preview": c[:50] + "..." if len(c) > 50 else c,
                    "has_session": _check_cookie_has_session(platform, c),
                    "is_valid": _check_cookie_has_session(platform, c),
                }
                for i, c in enumerate(pool)
            ],
        }
    return result


def _check_cookie_has_session(platform: str, cookie: str) -> bool:
    """检查Cookie是否包含平台必需的登录态字段"""
    if platform == "dy":
        return "sessionid" in cookie
    elif platform == "xhs":
        return "web_session" in cookie or "customer-session-id" in cookie
    elif platform == "wb":
        return "SUB" in cookie
    elif platform == "ks":
        return "passToken" in cookie or "userId" in cookie
    elif platform == "bili":
        return "SESSDATA" in cookie
    elif platform == "x_twitter":
        return "auth_token" in cookie or "ct0" in cookie or "guest_id" in cookie
    return True


# ============================================================
# 用户级别 Cookie 管理 API (基于数据库,每个用户独立)
# ============================================================

async def _get_user_cookie_session():
    """获取数据库会话(用于用户级别 Cookie 操作)"""
    try:
        from database.db_session import get_async_engine
        import config
        engine = get_async_engine(config.SAVE_DATA_OPTION)
        if not engine:
            return None
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.ext.asyncio import AsyncSession
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        return factory
    except Exception as e:
        print(f"[cookie_manager] _get_user_cookie_session error: {e}")
        return None


async def get_user_cookie(user_id: int, platform: str) -> str:
    """获取用户指定平台的 Cookie(优先数据库,退回全局 .env)

    Args:
        user_id: 用户ID
        platform: 平台标识 dy/xhs/ks/bili/wb/x_twitter
    Returns:
        Cookie 字符串,空字符串表示无
    """
    factory = await _get_user_cookie_session()
    if factory:
        try:
            from database.user_models import UserCookieModel
            from sqlalchemy import select
            async with factory() as session:
                result = await session.execute(
                    select(UserCookieModel.cookie_str)
                    .where(UserCookieModel.user_id == user_id)
                    .where(UserCookieModel.platform == platform)
                    .where(UserCookieModel.status == "active")
                    .order_by(UserCookieModel.created_ts.desc())
                    .limit(1)
                )
                cookie = result.scalar()
                if cookie:
                    return cookie
        except Exception as e:
            print(f"[cookie_manager] get_user_cookie DB error: {e}")

    # 退回全局 .env(管理员或旧数据兼容)
    return get_cookie(platform)


async def get_user_cookie_pool(user_id: int, platform: str) -> list:
    """获取用户指定平台的 Cookie 池(数据库)"""
    factory = await _get_user_cookie_session()
    if not factory:
        return []
    try:
        from database.user_models import UserCookieModel
        from sqlalchemy import select
        async with factory() as session:
            result = await session.execute(
                select(UserCookieModel)
                .where(UserCookieModel.user_id == user_id)
                .where(UserCookieModel.platform == platform)
                .where(UserCookieModel.status == "active")
                .order_by(UserCookieModel.created_ts.asc())
            )
            rows = result.scalars().all()
            return [{"id": r.id, "cookie": r.cookie_str, "alias": r.alias,
                     "status": r.status, "created_ts": r.created_ts} for r in rows]
    except Exception as e:
        print(f"[cookie_manager] get_user_cookie_pool error: {e}")
        return []


async def get_all_user_cookies(user_id: int) -> dict:
    """获取用户所有平台的 Cookie 状态(用于首页展示)"""
    result = {}
    for platform_id, _ in PLATFORM_ENV_KEYS.items():
        pool = await get_user_cookie_pool(user_id, platform_id)
        cookie_str = pool[0]["cookie"] if pool else ""
        result[platform_id] = {
            "has_cookie": bool(cookie_str),
            "cookie_length": len(cookie_str),
            "pool_size": len(pool),
        }
    return result


async def set_user_cookie(user_id: int, platform: str, cookie_str: str, alias: str = "") -> bool:
    """保存用户的 Cookie 到 Cookie 池(持久化,不会清空池里其他 Cookie)

    语义:更新或插入
    - 如果该用户该平台已有相同 cookie_str,更新其 alias/status/last_check_ts
    - 如果没有,插入新的(加入池)
    - 不会删除池里其他 Cookie — 只有 clear_user_cookie_pool 才会清空

    这样确保用户填写的 Cookie 都会持久化保留,只有手动"清空Cookie池"才能删除。
    """
    factory = await _get_user_cookie_session()
    if not factory:
        return False
    try:
        import time
        from database.user_models import UserCookieModel
        from sqlalchemy import delete, select, update
        async with factory() as session:
            # 查询该用户该平台是否已有相同 cookie_str
            existing = await session.execute(
                select(UserCookieModel)
                .where(UserCookieModel.user_id == user_id)
                .where(UserCookieModel.platform == platform)
                .where(UserCookieModel.cookie_str == cookie_str)
                .limit(1)
            )
            existing_row = existing.scalars().first()
            now_ms = int(time.time() * 1000)
            if existing_row:
                # 已存在相同 cookie,更新 alias 和状态(重新激活)
                await session.execute(
                    update(UserCookieModel)
                    .where(UserCookieModel.id == existing_row.id)
                    .values(
                        alias=alias or existing_row.alias or f"{platform}_cookie",
                        status="active",
                        last_check_ts=now_ms,
                    )
                )
            else:
                # 不存在,插入新的(加入池,不清空其他)
                new_cookie = UserCookieModel(
                    user_id=user_id,
                    platform=platform,
                    cookie_str=cookie_str,
                    alias=alias or f"{platform}_cookie_{now_ms}",
                    status="active",
                    created_ts=now_ms,
                )
                session.add(new_cookie)
            await session.commit()
        return True
    except Exception as e:
        print(f"[cookie_manager] set_user_cookie error: {e}")
        return False


async def add_user_cookie_to_pool(user_id: int, platform: str, cookie_str: str, alias: str = "") -> bool:
    """添加 Cookie 到用户的 Cookie 池"""
    factory = await _get_user_cookie_session()
    if not factory:
        return False
    try:
        import time
        from database.user_models import UserCookieModel
        async with factory() as session:
            new_cookie = UserCookieModel(
                user_id=user_id,
                platform=platform,
                cookie_str=cookie_str,
                alias=alias or f"{platform}_cookie_{int(time.time())}",
                status="active",
                created_ts=int(time.time() * 1000),
            )
            session.add(new_cookie)
            await session.commit()
        return True
    except Exception as e:
        print(f"[cookie_manager] add_user_cookie_to_pool error: {e}")
        return False


async def remove_user_cookie(user_id: int, cookie_id: int) -> bool:
    """从用户 Cookie 池删除指定 Cookie(by id)"""
    factory = await _get_user_cookie_session()
    if not factory:
        return False
    try:
        from database.user_models import UserCookieModel
        from sqlalchemy import delete
        async with factory() as session:
            await session.execute(
                delete(UserCookieModel)
                .where(UserCookieModel.id == cookie_id)
                .where(UserCookieModel.user_id == user_id)
            )
            await session.commit()
        return True
    except Exception as e:
        print(f"[cookie_manager] remove_user_cookie error: {e}")
        return False


async def clear_user_cookie_pool(user_id: int, platform: str) -> bool:
    """清空用户指定平台的 Cookie 池"""
    factory = await _get_user_cookie_session()
    if not factory:
        return False
    try:
        from database.user_models import UserCookieModel
        from sqlalchemy import delete
        async with factory() as session:
            await session.execute(
                delete(UserCookieModel)
                .where(UserCookieModel.user_id == user_id)
                .where(UserCookieModel.platform == platform)
            )
            await session.commit()
        return True
    except Exception as e:
        print(f"[cookie_manager] clear_user_cookie_pool error: {e}")
        return False
