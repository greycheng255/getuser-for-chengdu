# -*- coding: utf-8 -*-
"""
认证与用户管理路由
- POST   /api/auth/register   注册(首个用户自动成为管理员,后续默认 operator)
- POST   /api/auth/login      登录
- GET    /api/auth/me         获取当前用户信息
- GET    /api/auth/users      用户列表(管理员)
- POST   /api/auth/users      创建用户(管理员)
- PUT    /api/auth/users/{id} 更新用户(管理员)
- DELETE /api/auth/users/{id} 删除用户(管理员)
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..services.auth import (
    create_access_token,
    create_user,
    decode_token,
    delete_user,
    get_current_user,
    get_user_by_id,
    get_user_by_username,
    hash_password,
    list_all_users,
    require_admin,
    update_last_login,
    update_user,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ============ 请求模型 ============
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    nickname: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=128)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    nickname: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=128)
    role: str = Field(default="operator")


class UpdateUserRequest(BaseModel):
    nickname: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    password: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


# ============ 路由 ============
@router.post("/login")
async def login(req: LoginRequest):
    """登录,返回 JWT token 和用户信息"""
    user = await get_user_by_username(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(req.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.get("status") != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token = create_access_token(user["id"], user["username"], user["role"])
    await update_last_login(user["id"])

    # 返回给前端时去掉密码哈希
    safe_user = {k: v for k, v in user.items() if k != "password_hash"}
    return {
        "token": token,
        "user": safe_user,
    }


@router.post("/register")
async def register(req: RegisterRequest):
    """用户注册。

    首次注册(系统无任何用户时)自动成为管理员;
    后续注册默认为 operator。
    """
    from sqlalchemy import select
    from database.user_models import UserModel
    from ..services.auth import _get_session_factory

    factory = _get_session_factory()
    if not factory:
        raise HTTPException(status_code=500, detail="数据库不可用")

    # 判断是否首个用户
    async with factory() as session:
        result = await session.execute(select(UserModel).limit(1))
        first_user = result.scalars().first()
    role = "admin" if first_user is None else "operator"

    try:
        user = await create_user(
            username=req.username,
            password=req.password,
            nickname=req.nickname,
            email=req.email,
            role=role,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    token = create_access_token(user["id"], user["username"], user["role"])
    return {"token": token, "user": user, "message": f"注册成功,角色: {role}"}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return {"user": current_user}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """修改自己的密码"""
    user = await get_user_by_username(current_user["username"])
    if not user or not verify_password(req.old_password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="原密码错误")
    await update_user(current_user["id"], password=req.new_password)
    return {"message": "密码修改成功"}


# ============ 管理员:用户管理 ============
@router.get("/users")
async def get_users(admin: dict = Depends(require_admin)):
    """获取所有用户列表(管理员)"""
    users = await list_all_users()
    return {"users": users, "total": len(users)}


@router.post("/users")
async def create_user_api(
    req: CreateUserRequest,
    admin: dict = Depends(require_admin),
):
    """创建用户(管理员)"""
    try:
        user = await create_user(
            username=req.username,
            password=req.password,
            nickname=req.nickname,
            email=req.email,
            role=req.role,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"user": user, "message": "用户创建成功"}


@router.put("/users/{user_id}")
async def update_user_api(
    user_id: int,
    req: UpdateUserRequest,
    admin: dict = Depends(require_admin),
):
    """更新用户(管理员)"""
    target = await get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 防止取消最后一个管理员
    if target["role"] == "admin" and req.role and req.role != "admin":
        from sqlalchemy import select
        from database.user_models import UserModel
        from ..services.auth import _get_session_factory
        factory = _get_session_factory()
        if factory:
            async with factory() as session:
                result = await session.execute(
                    select(UserModel).where(UserModel.role == "admin", UserModel.status == "active")
                )
                admins = result.scalars().all()
                if len(admins) <= 1:
                    raise HTTPException(status_code=400, detail="不允许取消最后一个管理员的角色")

    try:
        user = await update_user(
            user_id,
            nickname=req.nickname,
            email=req.email,
            role=req.role,
            status=req.status,
            password=req.password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"user": user, "message": "用户更新成功"}


@router.delete("/users/{user_id}")
async def delete_user_api(
    user_id: int,
    admin: dict = Depends(require_admin),
):
    """删除用户(管理员)"""
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不允许删除自己")
    from ..services.opennotebook_oauth import OpenNotebookOAuthError

    try:
        ok = await delete_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OpenNotebookOAuthError as e:
        # OAuth revoke is deliberately fail-closed: do not delete a user while
        # its remote OpenNotebook grant may still be active.
        raise HTTPException(status_code=502, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": "用户已删除"}


@router.get("/check")
async def check_auth_status(current_user: dict = Depends(get_current_user)):
    """前端用于校验 token 是否有效"""
    return {"valid": True, "user": current_user}
