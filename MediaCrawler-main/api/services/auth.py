# -*- coding: utf-8 -*-
"""
认证与授权服务
- 密码哈希: bcrypt
- Token: JWT (HS256)
- 依赖注入: get_current_user / require_admin
- 数据库自动初始化: 启动时若无管理员账号,创建默认 admin/admin123
"""
import os
import time
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from database.user_models import UserModel
from database.db_session import get_async_engine
import config

# ============ 配置 ============
# JWT 密钥: 优先读环境变量,否则首次启动生成并写入 .env
_JWT_SECRET_ENV = "JWT_SECRET_KEY"


def _get_or_create_jwt_secret() -> str:
    """获取或生成 JWT 密钥,确保跨重启稳定"""
    secret = os.environ.get(_JWT_SECRET_ENV, "").strip()
    if secret:
        return secret
    # 尝试从 .env 读取
    try:
        from .cookie_manager import _ensure_env_loaded
        _ensure_env_loaded()
        secret = os.environ.get(_JWT_SECRET_ENV, "").strip()
        if secret:
            return secret
    except Exception:
        pass
    # 生成新的并写入 .env
    secret = secrets.token_urlsafe(48)
    os.environ[_JWT_SECRET_ENV] = secret
    try:
        from .cookie_manager import _update_env_file
        _update_env_file(_JWT_SECRET_ENV, secret)
    except Exception as e:
        print(f"[auth] Failed to persist JWT secret to .env: {e}")
    return secret


JWT_SECRET_KEY = _get_or_create_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7  # 7 天

# 密码哈希: 直接使用 bcrypt(避免 passlib 与 bcrypt 5.x 不兼容问题)
# Bearer token 提取器
_bearer = HTTPBearer(auto_error=False)


# ============ 数据库会话 ============
def _get_session_factory():
    engine = get_async_engine(config.SAVE_DATA_OPTION)
    if not engine:
        return None
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ============ 密码工具 ============
def hash_password(plain: str) -> str:
    """使用 bcrypt 对密码进行哈希(bcrypt 限制密码最长 72 字节)"""
    pw_bytes = plain.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        pw_bytes = plain.encode("utf-8")[:72]
        hashed_bytes = hashed.encode("utf-8")
        return bcrypt.checkpw(pw_bytes, hashed_bytes)
    except Exception:
        return False


# ============ Token 工具 ============
def create_access_token(user_id: int, username: str, role: str) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "uid": user_id,
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRE_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ============ 用户操作 ============
async def get_user_by_id(user_id: int) -> Optional[dict]:
    factory = _get_session_factory()
    if not factory:
        return None
    async with factory() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == user_id))
        u = result.scalars().first()
        if not u:
            return None
        return _user_to_dict(u)


async def get_user_by_username(username: str) -> Optional[dict]:
    factory = _get_session_factory()
    if not factory:
        return None
    async with factory() as session:
        result = await session.execute(select(UserModel).where(UserModel.username == username))
        u = result.scalars().first()
        if not u:
            return None
        return _user_to_dict(u, include_hash=True)


def _user_to_dict(u: UserModel, include_hash: bool = False) -> dict:
    d = {
        "id": u.id,
        "username": u.username,
        "nickname": u.nickname or "",
        "email": u.email or "",
        "role": u.role or "operator",
        "status": u.status or "active",
        "created_ts": u.created_ts or 0,
        "last_login_ts": u.last_login_ts or 0,
        # 套餐订阅字段(v6.6 商业化)
        "plan_type": getattr(u, "plan_type", None) or "free",
        "plan_expires_ts": getattr(u, "plan_expires_ts", None) or 0,
        "plan_started_ts": getattr(u, "plan_started_ts", None) or 0,
        # 按量计费字段
        "balance": getattr(u, "balance", None) or 0,
        "total_spent": getattr(u, "total_spent", None) or 0,
        # 用量统计
        "usage_period_start_ts": getattr(u, "usage_period_start_ts", None) or 0,
        "usage_notes_count": getattr(u, "usage_notes_count", None) or 0,
        "usage_comments_count": getattr(u, "usage_comments_count", None) or 0,
        "usage_leads_count": getattr(u, "usage_leads_count", None) or 0,
    }
    if include_hash:
        d["password_hash"] = u.password_hash
    return d


async def list_all_users() -> list:
    factory = _get_session_factory()
    if not factory:
        return []
    async with factory() as session:
        result = await session.execute(select(UserModel).order_by(UserModel.id))
        return [_user_to_dict(u) for u in result.scalars().all()]


async def create_user(username: str, password: str, nickname: str = "", email: str = "", role: str = "operator") -> dict:
    factory = _get_session_factory()
    if not factory:
        raise RuntimeError("数据库不可用")
    async with factory() as session:
        # 检查用户名是否已存在
        existing = await session.execute(select(UserModel).where(UserModel.username == username))
        if existing.scalars().first():
            raise ValueError("用户名已存在")
        now = int(time.time() * 1000)
        u = UserModel(
            username=username,
            password_hash=hash_password(password),
            nickname=nickname or username,
            email=email,
            role=role if role in ("admin", "operator", "viewer") else "operator",
            status="active",
            created_ts=now,
            last_login_ts=0,
            # 套餐默认:免费版,注册即用(v6.6 商业化)
            plan_type="free",
            plan_expires_ts=0,     # 免费版永久有效
            plan_started_ts=now,
            balance=0,
            total_spent=0,
            usage_period_start_ts=now,
            usage_notes_count=0,
            usage_comments_count=0,
            usage_leads_count=0,
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return _user_to_dict(u)


async def update_user(user_id: int, **fields) -> Optional[dict]:
    factory = _get_session_factory()
    if not factory:
        return None
    allowed = {"nickname", "email", "role", "status",
               # 套餐字段(管理员可手动调整)
               "plan_type", "plan_expires_ts", "plan_started_ts",
               "balance", "total_spent",
               "usage_period_start_ts", "usage_notes_count", "usage_comments_count", "usage_leads_count"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "password" in fields and fields["password"]:
        updates["password_hash"] = hash_password(fields["password"])
    if not updates:
        return await get_user_by_id(user_id)
    async with factory() as session:
        await session.execute(update(UserModel).where(UserModel.id == user_id).values(**updates))
        await session.commit()
    return await get_user_by_id(user_id)


async def delete_user(user_id: int) -> bool:
    factory = _get_session_factory()
    if not factory:
        return False
    # Local import avoids coupling auth module initialization to OAuth config.
    from api.services.opennotebook_oauth import credential_lock, disconnect
    from database.models import XTwitterExplainerVideoTask
    from database.user_models import (
        OpenNotebookConnectionModel,
        OpenNotebookOAuthFlowModel,
    )

    owner_user_id = str(user_id)
    # Keep the owner lifecycle lock for validation, remote revoke, and every
    # local delete. The user row lock is the cross-worker fence used by OAuth
    # start/save; after this transaction commits a queued request must re-read
    # the owner and fail instead of recreating credentials for a reused ID.
    async with credential_lock(owner_user_id):
        async with factory() as session:
            result = await session.execute(
                select(UserModel)
                .where(UserModel.id == user_id)
                .with_for_update()
            )
            u = result.scalars().first()
            if not u:
                return False
            if u.role == "admin":
                # Lock the active admin set so two concurrent deletions cannot
                # both observe a count greater than one and remove the last admins.
                admin_count_result = await session.execute(
                    select(UserModel)
                    .where(
                        UserModel.role == "admin",
                        UserModel.status == "active",
                    )
                    .with_for_update()
                )
                if len(admin_count_result.scalars().all()) <= 1:
                    raise ValueError("不允许删除最后一个管理员账号")

            # Use this transaction for disconnect as well. A revoke failure
            # rolls back every local mutation and leaves an administrator a
            # consistent record to retry.
            await disconnect(
                owner_user_id,
                _lock_held=True,
                _session=session,
            )
            await session.execute(
                delete(OpenNotebookOAuthFlowModel).where(
                    OpenNotebookOAuthFlowModel.owner_user_id == owner_user_id
                )
            )
            await session.execute(
                delete(XTwitterExplainerVideoTask).where(
                    XTwitterExplainerVideoTask.owner_user_id == owner_user_id
                )
            )
            await session.execute(
                delete(OpenNotebookConnectionModel).where(
                    OpenNotebookConnectionModel.owner_user_id == owner_user_id
                )
            )
            await session.delete(u)
            await session.commit()
            return True


async def update_last_login(user_id: int):
    factory = _get_session_factory()
    if not factory:
        return
    async with factory() as session:
        await session.execute(
            update(UserModel).where(UserModel.id == user_id).values(last_login_ts=int(time.time() * 1000))
        )
        await session.commit()


# ============ 依赖注入 ============
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """从 Bearer Token 解析当前用户"""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证凭据")
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭据无效或已过期")
    user_id = payload.get("uid")
    user = await get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if user.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")
    return user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


def is_admin(user: dict) -> bool:
    return user.get("role") == "admin"


def user_scope_filter(user: dict, model_cls):
    """返回用于 where 子句的过滤条件: 管理员不过滤,其他用户只看自己的数据。

    使用方式:
        cond = user_scope_filter(user, CrawlerTaskModel)
        stmt = select(CrawlerTaskModel)
        if cond is not None:
            stmt = stmt.where(cond)
    """
    if is_admin(user):
        return None
    owner_field = getattr(model_cls, "owner_user_id", None)
    if owner_field is None:
        return None
    return owner_field == str(user["id"])


# ============ 初始化默认管理员 ============
async def ensure_default_admin():
    """启动时确保至少有一个管理员账号"""
    try:
        factory = _get_session_factory()
        if not factory:
            print("[auth] DB engine unavailable, skip admin init")
            return
        async with factory() as session:
            result = await session.execute(select(UserModel).where(UserModel.role == "admin").limit(1))
            admin = result.scalars().first()
            if admin:
                return
            # 创建默认管理员
            now = int(time.time() * 1000)
            u = UserModel(
                username="admin",
                password_hash=hash_password("admin123"),
                nickname="系统管理员",
                email="",
                role="admin",
                status="active",
                created_ts=now,
                last_login_ts=0,
            )
            session.add(u)
            await session.commit()
            print("[auth] Default admin created: admin / admin123")
    except Exception as e:
        print(f"[auth] ensure_default_admin error: {e}")
