# -*- coding: utf-8 -*-
"""
商业化API路由 - 线索分包销售、API对接、销售团队协作
"""
import time
import uuid
import hashlib
import secrets
import json
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_session import get_session as async_db_session
from database.models import (
    CustomerLead, BusinessUser, LeadPackage, LeadAssignment,
    FollowUpRecord, PurchaseOrder, ApiClient
)
from .auth import get_current_user

router = APIRouter(prefix="/business", tags=["business"])


# ==================== 通用工具函数 ====================

def generate_id(prefix: str = "") -> str:
    """生成唯一ID"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def hash_password(password: str) -> str:
    """密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()


def generate_api_key() -> str:
    """生成API密钥"""
    return secrets.token_urlsafe(32)


def get_timestamp() -> int:
    """获取当前时间戳(毫秒)"""
    return int(time.time() * 1000)


# ==================== Pydantic 模型定义 ====================

class BusinessUserCreate(BaseModel):
    """创建业务用户"""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    nickname: str = Field(..., min_length=1, max_length=50)
    role: str = Field(default="customer", description="customer/sales/admin")
    company_name: str = Field(default="")
    contact_phone: str = Field(default="")
    contact_email: str = Field(default="")
    sales_region: str = Field(default="", description="负责地域(销售用)")
    sales_quota: int = Field(default=100, description="每日线索配额")
    webhook_url: str = Field(default="", description="Webhook推送地址")
    auto_push: bool = Field(default=False, description="是否自动推送")


class BusinessUserUpdate(BaseModel):
    """更新业务用户"""
    nickname: Optional[str] = None
    company_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    sales_region: Optional[str] = None
    sales_quota: Optional[int] = None
    webhook_url: Optional[str] = None
    auto_push: Optional[bool] = None
    status: Optional[str] = None


class BusinessUserResponse(BaseModel):
    """业务用户响应"""
    id: str
    username: str
    nickname: str
    role: str
    company_name: str = ""
    contact_phone: str = ""
    contact_email: str = ""
    balance: int = 0
    total_spent: int = 0
    status: str
    sales_region: str = ""
    sales_quota: int = 100
    webhook_url: str = ""
    api_key: str = ""
    auto_push: bool = False
    assigned_leads_count: int = 0
    converted_leads_count: int = 0
    created_ts: int
    last_login_ts: int = 0


class LeadPackageCreate(BaseModel):
    """创建线索包"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")
    platform: str = Field(default="")
    task_id: str = Field(default="")
    min_score: int = Field(default=0, ge=0, le=100)
    max_score: int = Field(default=100, ge=0, le=100)
    level: str = Field(default="", description="high/medium/low/all")
    ip_location: str = Field(default="")
    keyword: str = Field(default="")
    price_per_lead: int = Field(default=0, ge=0, description="单价(分)")
    expire_days: int = Field(default=90, ge=1, le=365)


class LeadPackageUpdate(BaseModel):
    """更新线索包"""
    name: Optional[str] = None
    description: Optional[str] = None
    price_per_lead: Optional[int] = None
    expire_days: Optional[int] = None
    status: Optional[str] = None


class LeadPackageResponse(BaseModel):
    """线索包响应"""
    id: str
    name: str
    description: str = ""
    platform: str = ""
    task_id: str = ""
    min_score: int = 0
    max_score: int = 100
    level: str = ""
    ip_location: str = ""
    total_count: int = 0
    available_count: int = 0
    sold_count: int = 0
    price_per_lead: int = 0
    total_price: int = 0
    expire_days: int = 90
    status: str
    created_ts: int
    publish_ts: int = 0


class PurchaseRequest(BaseModel):
    """购买线索包请求"""
    package_id: str
    lead_count: int = Field(..., ge=1, description="购买数量")
    payment_method: str = Field(default="balance", description="balance/offline")


class LeadAssignRequest(BaseModel):
    """手动分配线索请求"""
    lead_ids: List[int] = Field(..., min_items=1)
    business_user_id: str
    expire_days: int = Field(default=90)


class FollowUpCreate(BaseModel):
    """创建跟进记录"""
    lead_id: int
    action_type: str = Field(..., description="call/message/visit/wechat")
    result: str = Field(..., description="pending/contacted/interested/not_interested/converted/failed")
    notes: str = Field(default="")
    next_follow_ts: Optional[int] = None


class FollowUpResponse(BaseModel):
    """跟进记录响应"""
    id: int
    lead_id: int
    business_user_id: str
    action_type: str
    action_ts: int
    result: str
    notes: str
    next_follow_ts: int = 0
    created_ts: int


class ApiClientCreate(BaseModel):
    """创建API客户端"""
    name: str
    business_user_id: str = ""
    webhook_url: str = ""
    callback_url: str = ""
    filters: dict = Field(default={})
    push_mode: str = Field(default="batch", description="batch/realtime")
    push_interval: int = Field(default=300, ge=60)


class ApiClientResponse(BaseModel):
    """API客户端响应"""
    id: str
    name: str
    business_user_id: str
    api_key: str
    webhook_url: str
    callback_url: str
    filters: dict
    push_mode: str
    push_interval: int
    status: str
    last_push_ts: int = 0
    total_pushed: int = 0
    created_ts: int


class StatsResponse(BaseModel):
    """统计响应"""
    total_customers: int = 0
    total_sales: int = 0
    total_packages: int = 0
    total_leads_assigned: int = 0
    total_revenue: int = 0
    total_orders: int = 0


# ==================== 业务用户管理 ====================

@router.post("/users", response_model=BusinessUserResponse)
async def create_business_user(
    data: BusinessUserCreate,
    current_user: dict = Depends(get_current_user),
):
    """创建业务用户(客户/销售)"""
    async with async_db_session() as session:
        # 检查用户名是否已存在
        existing = await session.execute(
            select(BusinessUser).where(BusinessUser.username == data.username)
        )
        if existing.scalar():
            raise HTTPException(status_code=400, detail="用户名已存在")

        # 创建用户
        user_id = generate_id("bu")
        api_key = generate_api_key() if data.role == "customer" else ""

        user = BusinessUser(
            id=user_id,
            username=data.username,
            password_hash=hash_password(data.password),
            nickname=data.nickname,
            role=data.role,
            company_name=data.company_name,
            contact_phone=data.contact_phone,
            contact_email=data.contact_email,
            sales_region=data.sales_region,
            sales_quota=data.sales_quota,
            webhook_url=data.webhook_url,
            api_key=api_key,
            auto_push=1 if data.auto_push else 0,
            owner_user_id=str(current_user["id"]),
            created_ts=get_timestamp(),
            updated_ts=get_timestamp(),
        )
        session.add(user)
        await session.commit()

        return BusinessUserResponse(
            id=user.id,
            username=user.username,
            nickname=user.nickname,
            role=user.role,
            company_name=user.company_name,
            contact_phone=user.contact_phone,
            contact_email=user.contact_email,
            balance=user.balance,
            total_spent=user.total_spent,
            status=user.status,
            sales_region=user.sales_region,
            sales_quota=user.sales_quota,
            webhook_url=user.webhook_url,
            api_key=user.api_key,
            auto_push=bool(user.auto_push),
            assigned_leads_count=user.assigned_leads_count,
            converted_leads_count=user.converted_leads_count,
            created_ts=user.created_ts,
            last_login_ts=user.last_login_ts,
        )


@router.get("/users", response_model=dict)
async def list_business_users(
    role: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取业务用户列表"""
    async with async_db_session() as session:
        query = select(BusinessUser).where(
            BusinessUser.owner_user_id == str(current_user["id"])
        )
        if role:
            query = query.where(BusinessUser.role == role)
        if status:
            query = query.where(BusinessUser.status == status)
        if keyword:
            query = query.where(
                or_(
                    BusinessUser.nickname.contains(keyword),
                    BusinessUser.company_name.contains(keyword),
                    BusinessUser.username.contains(keyword),
                )
            )

        # 总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)

        # 分页
        query = query.order_by(desc(BusinessUser.created_ts))
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(query)
        users = result.scalars().all()

        items = [
            BusinessUserResponse(
                id=u.id,
                username=u.username,
                nickname=u.nickname,
                role=u.role,
                company_name=u.company_name,
                contact_phone=u.contact_phone,
                contact_email=u.contact_email,
                balance=u.balance,
                total_spent=u.total_spent,
                status=u.status,
                sales_region=u.sales_region,
                sales_quota=u.sales_quota,
                webhook_url=u.webhook_url,
                api_key=u.api_key,
                auto_push=bool(u.auto_push),
                assigned_leads_count=u.assigned_leads_count,
                converted_leads_count=u.converted_leads_count,
                created_ts=u.created_ts,
                last_login_ts=u.last_login_ts,
            )
            for u in users
        ]

        return {"total": total, "items": items, "page": page, "page_size": page_size}


@router.get("/users/{user_id}", response_model=BusinessUserResponse)
async def get_business_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取业务用户详情"""
    async with async_db_session() as session:
        result = await session.execute(
            select(BusinessUser).where(
                BusinessUser.id == user_id,
                BusinessUser.owner_user_id == str(current_user["id"]),
            )
        )
        user = result.scalar()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        return BusinessUserResponse(
            id=user.id,
            username=user.username,
            nickname=user.nickname,
            role=user.role,
            company_name=user.company_name,
            contact_phone=user.contact_phone,
            contact_email=user.contact_email,
            balance=user.balance,
            total_spent=user.total_spent,
            status=user.status,
            sales_region=user.sales_region,
            sales_quota=user.sales_quota,
            webhook_url=user.webhook_url,
            api_key=user.api_key,
            auto_push=bool(user.auto_push),
            assigned_leads_count=user.assigned_leads_count,
            converted_leads_count=user.converted_leads_count,
            created_ts=user.created_ts,
            last_login_ts=user.last_login_ts,
        )


@router.patch("/users/{user_id}", response_model=BusinessUserResponse)
async def update_business_user(
    user_id: str,
    data: BusinessUserUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新业务用户"""
    async with async_db_session() as session:
        result = await session.execute(
            select(BusinessUser).where(
                BusinessUser.id == user_id,
                BusinessUser.owner_user_id == str(current_user["id"]),
            )
        )
        user = result.scalar()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 更新字段
        if data.nickname is not None:
            user.nickname = data.nickname
        if data.company_name is not None:
            user.company_name = data.company_name
        if data.contact_phone is not None:
            user.contact_phone = data.contact_phone
        if data.contact_email is not None:
            user.contact_email = data.contact_email
        if data.sales_region is not None:
            user.sales_region = data.sales_region
        if data.sales_quota is not None:
            user.sales_quota = data.sales_quota
        if data.webhook_url is not None:
            user.webhook_url = data.webhook_url
        if data.auto_push is not None:
            user.auto_push = 1 if data.auto_push else 0
        if data.status is not None:
            user.status = data.status

        user.updated_ts = get_timestamp()
        await session.commit()

        return BusinessUserResponse(
            id=user.id,
            username=user.username,
            nickname=user.nickname,
            role=user.role,
            company_name=user.company_name,
            contact_phone=user.contact_phone,
            contact_email=user.contact_email,
            balance=user.balance,
            total_spent=user.total_spent,
            status=user.status,
            sales_region=user.sales_region,
            sales_quota=user.sales_quota,
            webhook_url=user.webhook_url,
            api_key=user.api_key,
            auto_push=bool(user.auto_push),
            assigned_leads_count=user.assigned_leads_count,
            converted_leads_count=user.converted_leads_count,
            created_ts=user.created_ts,
            last_login_ts=user.last_login_ts,
        )


@router.post("/users/{user_id}/recharge")
async def recharge_user_balance(
    user_id: str,
    amount: int = Query(..., ge=1, description="充值金额(分)"),
    current_user: dict = Depends(get_current_user),
):
    """为用户充值"""
    async with async_db_session() as session:
        result = await session.execute(
            select(BusinessUser).where(
                BusinessUser.id == user_id,
                BusinessUser.owner_user_id == str(current_user["id"]),
            )
        )
        user = result.scalar()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        user.balance += amount
        user.updated_ts = get_timestamp()
        await session.commit()

        return {"success": True, "balance": user.balance}


@router.post("/users/{user_id}/reset-api-key")
async def reset_user_api_key(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """重置用户API密钥"""
    async with async_db_session() as session:
        result = await session.execute(
            select(BusinessUser).where(
                BusinessUser.id == user_id,
                BusinessUser.owner_user_id == str(current_user["id"]),
            )
        )
        user = result.scalar()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        user.api_key = generate_api_key()
        user.updated_ts = get_timestamp()
        await session.commit()

        return {"success": True, "api_key": user.api_key}


# ==================== 线索包管理 ====================

@router.post("/packages", response_model=LeadPackageResponse)
async def create_lead_package(
    data: LeadPackageCreate,
    current_user: dict = Depends(get_current_user),
):
    """创建线索包"""
    async with async_db_session() as session:
        # 计算符合条件的线索数量
        query = select(func.count()).select_from(CustomerLead).where(
            CustomerLead.owner_user_id == str(current_user["id"])
        )
        if data.platform:
            query = query.where(CustomerLead.platform == data.platform)
        if data.task_id:
            query = query.where(CustomerLead.task_id == data.task_id)
        if data.min_score > 0:
            query = query.where(CustomerLead.lead_score >= data.min_score)
        if data.max_score < 100:
            query = query.where(CustomerLead.lead_score <= data.max_score)
        if data.level:
            lvl = data.level.lower()
            if lvl == "high":
                query = query.where(CustomerLead.lead_score >= 50)
            elif lvl == "medium":
                query = query.where(CustomerLead.lead_score >= 25, CustomerLead.lead_score < 50)
            elif lvl == "low":
                query = query.where(CustomerLead.lead_score < 25)
        if data.ip_location:
            query = query.where(CustomerLead.ip_location.contains(data.ip_location))
        if data.keyword:
            query = query.where(CustomerLead.content.contains(data.keyword))

        total_count = await session.scalar(query)

        # 排除已分配的线索
        assigned_query = select(LeadAssignment.lead_id).where(
            LeadAssignment.owner_user_id == str(current_user["id"]),
            LeadAssignment.status.in_(["assigned", "used"]),
        )
        assigned_result = await session.execute(assigned_query)
        assigned_ids = [row[0] for row in assigned_result.fetchall()]

        # 只计算当前筛选条件下的已分配线索
        if assigned_ids:
            assigned_in_query = select(func.count()).select_from(CustomerLead).where(
                CustomerLead.id.in_(assigned_ids)
            )
            # 应用相同的筛选条件
            if data.platform:
                assigned_in_query = assigned_in_query.where(CustomerLead.platform == data.platform)
            if data.task_id:
                assigned_in_query = assigned_in_query.where(CustomerLead.task_id == data.task_id)
            if data.min_score > 0:
                assigned_in_query = assigned_in_query.where(CustomerLead.lead_score >= data.min_score)
            if data.max_score < 100:
                assigned_in_query = assigned_in_query.where(CustomerLead.lead_score <= data.max_score)
            if data.level:
                lvl = data.level.lower()
                if lvl == "high":
                    assigned_in_query = assigned_in_query.where(CustomerLead.lead_score >= 50)
                elif lvl == "medium":
                    assigned_in_query = assigned_in_query.where(CustomerLead.lead_score >= 25, CustomerLead.lead_score < 50)
                elif lvl == "low":
                    assigned_in_query = assigned_in_query.where(CustomerLead.lead_score < 25)
            if data.ip_location:
                assigned_in_query = assigned_in_query.where(CustomerLead.ip_location.contains(data.ip_location))
            if data.keyword:
                assigned_in_query = assigned_in_query.where(CustomerLead.content.contains(data.keyword))
            assigned_in_count = await session.scalar(assigned_in_query)
        else:
            assigned_in_count = 0

        available_count = total_count - assigned_in_count
        total_price = available_count * data.price_per_lead

        package = LeadPackage(
            id=generate_id("pkg"),
            name=data.name,
            description=data.description,
            platform=data.platform,
            task_id=data.task_id,
            min_score=data.min_score,
            max_score=data.max_score,
            level=data.level,
            ip_location=data.ip_location,
            keyword=data.keyword,
            total_count=total_count,
            available_count=available_count,
            price_per_lead=data.price_per_lead,
            total_price=total_price,
            expire_days=data.expire_days,
            status="draft",
            owner_user_id=str(current_user["id"]),
            created_ts=get_timestamp(),
            updated_ts=get_timestamp(),
        )
        session.add(package)
        await session.commit()

        return LeadPackageResponse(
            id=package.id,
            name=package.name,
            description=package.description,
            platform=package.platform,
            task_id=package.task_id,
            min_score=package.min_score,
            max_score=package.max_score,
            level=package.level,
            ip_location=package.ip_location,
            total_count=package.total_count,
            available_count=package.available_count,
            sold_count=package.sold_count,
            price_per_lead=package.price_per_lead,
            total_price=package.total_price,
            expire_days=package.expire_days,
            status=package.status,
            created_ts=package.created_ts,
            publish_ts=package.publish_ts,
        )


@router.put("/packages/{package_id}", response_model=LeadPackageResponse)
async def update_lead_package(
    package_id: str,
    data: LeadPackageUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新线索包"""
    async with async_db_session() as session:
        package = await session.scalar(
            select(LeadPackage).where(
                LeadPackage.id == package_id,
                LeadPackage.owner_user_id == str(current_user["id"]),
            )
        )
        if not package:
            raise HTTPException(status_code=404, detail="Package not found")

        # 更新字段
        if data.name is not None:
            package.name = data.name
        if data.description is not None:
            package.description = data.description
        if data.price_per_lead is not None:
            package.price_per_lead = data.price_per_lead
            package.total_price = package.available_count * data.price_per_lead
        if data.expire_days is not None:
            package.expire_days = data.expire_days
        if data.status is not None:
            package.status = data.status
            if data.status == "published" and not package.publish_ts:
                package.publish_ts = get_timestamp()

        package.updated_ts = get_timestamp()
        await session.commit()

        return LeadPackageResponse(
            id=package.id,
            name=package.name,
            description=package.description,
            platform=package.platform,
            task_id=package.task_id,
            min_score=package.min_score,
            max_score=package.max_score,
            level=package.level,
            ip_location=package.ip_location,
            total_count=package.total_count,
            available_count=package.available_count,
            sold_count=package.sold_count,
            price_per_lead=package.price_per_lead,
            total_price=package.total_price,
            expire_days=package.expire_days,
            status=package.status,
            created_ts=package.created_ts,
            publish_ts=package.publish_ts,
        )

@router.delete("/packages/{package_id}")
async def delete_lead_package(
    package_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除线索包"""
    async with async_db_session() as session:
        package = await session.scalar(
            select(LeadPackage).where(
                LeadPackage.id == package_id,
                LeadPackage.owner_user_id == str(current_user["id"]),
            )
        )
        if not package:
            raise HTTPException(status_code=404, detail="Package not found")
        
        # 检查是否有已分配的线索
        assigned = await session.scalar(
            select(func.count()).select_from(LeadAssignment).where(
                LeadAssignment.package_id == package_id,
                LeadAssignment.status.in_(["assigned", "used"])
            )
        )
        if assigned > 0:
            raise HTTPException(status_code=400, detail="Cannot delete package with assigned leads")
        
        await session.delete(package)
        await session.commit()
        
        return {"success": True, "message": "Package deleted"}


@router.get("/packages", response_model=dict)
async def list_lead_packages(
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取线索包列表"""
    async with async_db_session() as session:
        query = select(LeadPackage).where(
            LeadPackage.owner_user_id == str(current_user["id"])
        )
        if status:
            query = query.where(LeadPackage.status == status)
        if keyword:
            query = query.where(LeadPackage.name.contains(keyword))

        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        query = query.order_by(desc(LeadPackage.created_ts))
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(query)
        packages = result.scalars().all()

        items = [
            LeadPackageResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                platform=p.platform,
                task_id=p.task_id,
                min_score=p.min_score,
                max_score=p.max_score,
                level=p.level,
                ip_location=p.ip_location,
                total_count=p.total_count,
                available_count=p.available_count,
                sold_count=p.sold_count,
                price_per_lead=p.price_per_lead,
                total_price=p.total_price,
                expire_days=p.expire_days,
                status=p.status,
                created_ts=p.created_ts,
                publish_ts=p.publish_ts,
            )
            for p in packages
        ]

        return {"total": total, "items": items, "page": page, "page_size": page_size}


@router.post("/packages/{package_id}/publish")
async def publish_lead_package(
    package_id: str,
    current_user: dict = Depends(get_current_user),
):
    """发布线索包(上架)"""
    async with async_db_session() as session:
        result = await session.execute(
            select(LeadPackage).where(
                LeadPackage.id == package_id,
                LeadPackage.owner_user_id == str(current_user["id"]),
            )
        )
        package = result.scalar()
        if not package:
            raise HTTPException(status_code=404, detail="线索包不存在")

        if package.status != "draft":
            raise HTTPException(status_code=400, detail="只有草稿状态的线索包可以发布")

        if package.available_count <= 0:
            raise HTTPException(status_code=400, detail="没有可售线索")

        package.status = "active"
        package.publish_ts = get_timestamp()
        package.updated_ts = get_timestamp()
        await session.commit()

        return {"success": True, "status": package.status}


@router.post("/packages/{package_id}/discontinue")
async def discontinue_lead_package(
    package_id: str,
    current_user: dict = Depends(get_current_user),
):
    """下架线索包"""
    async with async_db_session() as session:
        result = await session.execute(
            select(LeadPackage).where(
                LeadPackage.id == package_id,
                LeadPackage.owner_user_id == str(current_user["id"]),
            )
        )
        package = result.scalar()
        if not package:
            raise HTTPException(status_code=404, detail="线索包不存在")

        package.status = "discontinued"
        package.updated_ts = get_timestamp()
        await session.commit()

        return {"success": True}


# ==================== 购买流程 ====================

@router.post("/purchase", response_model=dict)
async def purchase_lead_package(
    data: PurchaseRequest,
    current_user: dict = Depends(get_current_user),
):
    """购买线索包"""
    async with async_db_session() as session:
        # 获取线索包
        pkg_result = await session.execute(
            select(LeadPackage).where(
                LeadPackage.id == data.package_id,
                LeadPackage.owner_user_id == str(current_user["id"]),
                LeadPackage.status == "active",
            )
        )
        package = pkg_result.scalar()
        if not package:
            raise HTTPException(status_code=404, detail="线索包不存在或未上架")

        if data.lead_count > package.available_count:
            raise HTTPException(status_code=400, detail="购买数量超过可售数量")

        # 获取买家(业务用户)
        # 这里假设前端传入的是业务用户ID，需要验证归属
        # 简化逻辑：买家必须是当前系统用户下的业务用户
        buyer_result = await session.execute(
            select(BusinessUser).where(
                BusinessUser.owner_user_id == str(current_user["id"]),
                BusinessUser.status == "active",
            ).limit(1)
        )
        buyer = buyer_result.scalar()
        if not buyer:
            raise HTTPException(status_code=400, detail="未找到有效的业务用户，请先创建客户账号")

        # 计算总价
        total_price = data.lead_count * package.price_per_lead

        # 检查余额
        if data.payment_method == "balance" and buyer.balance < total_price:
            raise HTTPException(status_code=400, detail=f"余额不足，当前余额{buyer.balance}分，需要{total_price}分")

        # 创建订单
        order = PurchaseOrder(
            id=generate_id("ord"),
            package_id=package.id,
            business_user_id=buyer.id,
            lead_count=data.lead_count,
            total_price=total_price,
            payment_method=data.payment_method,
            status="pending",
            created_ts=get_timestamp(),
            owner_user_id=str(current_user["id"]),
        )
        session.add(order)

        # 执行扣款
        if data.payment_method == "balance":
            buyer.balance -= total_price
            buyer.total_spent += total_price
            order.status = "paid"
            order.paid_ts = get_timestamp()

        # 分配线索
        # 查询符合条件的线索
        lead_query = select(CustomerLead).where(
            CustomerLead.owner_user_id == str(current_user["id"])
        )
        if package.platform:
            lead_query = lead_query.where(CustomerLead.platform == package.platform)
        if package.task_id:
            lead_query = lead_query.where(CustomerLead.task_id == package.task_id)
        if package.min_score > 0:
            lead_query = lead_query.where(CustomerLead.lead_score >= package.min_score)
        if package.max_score < 100:
            lead_query = lead_query.where(CustomerLead.lead_score <= package.max_score)
        if package.level:
            lvl = package.level.lower()
            if lvl == "high":
                lead_query = lead_query.where(CustomerLead.lead_score >= 50)
            elif lvl == "medium":
                lead_query = lead_query.where(CustomerLead.lead_score >= 25, CustomerLead.lead_score < 50)
            elif lvl == "low":
                lead_query = lead_query.where(CustomerLead.lead_score < 25)
        if package.ip_location:
            lead_query = lead_query.where(CustomerLead.ip_location.contains(package.ip_location))
        if package.keyword:
            lead_query = lead_query.where(CustomerLead.content.contains(package.keyword))

        # 排除已分配的线索
        assigned_ids_result = await session.execute(
            select(LeadAssignment.lead_id).where(
                LeadAssignment.owner_user_id == str(current_user["id"]),
                LeadAssignment.status.in_(["assigned", "used"]),
            )
        )
        assigned_ids = [row[0] for row in assigned_ids_result.fetchall()]
        if assigned_ids:
            lead_query = lead_query.where(CustomerLead.id.notin_(assigned_ids))

        lead_query = lead_query.order_by(desc(CustomerLead.lead_score)).limit(data.lead_count)
        leads_result = await session.execute(lead_query)
        leads = leads_result.scalars().all()

        # 创建分配记录
        now_ts = get_timestamp()
        expire_ts = now_ts + package.expire_days * 24 * 60 * 60 * 1000

        for lead in leads:
            assignment = LeadAssignment(
                lead_id=lead.id,
                package_id=package.id,
                business_user_id=buyer.id,
                assign_type="purchase",
                price_paid=package.price_per_lead,
                status="assigned",
                expire_ts=expire_ts,
                assigned_ts=now_ts,
                owner_user_id=str(current_user["id"]),
            )
            session.add(assignment)

        # 更新统计
        package.sold_count += data.lead_count
        package.available_count -= data.lead_count
        buyer.assigned_leads_count += len(leads)

        if package.available_count <= 0:
            package.status = "sold_out"

        order.status = "completed"
        order.completed_ts = get_timestamp()

        await session.commit()

        return {
            "success": True,
            "order_id": order.id,
            "assigned_count": len(leads),
            "total_price": total_price,
            "expire_ts": expire_ts,
        }


# ==================== 线索分配 ====================

@router.post("/assign", response_model=dict)
async def assign_leads(
    data: LeadAssignRequest,
    current_user: dict = Depends(get_current_user),
):
    """手动分配线索给业务用户"""
    async with async_db_session() as session:
        # 验证业务用户
        bu_result = await session.execute(
            select(BusinessUser).where(
                BusinessUser.id == data.business_user_id,
                BusinessUser.owner_user_id == str(current_user["id"]),
                BusinessUser.status == "active",
            )
        )
        bu = bu_result.scalar()
        if not bu:
            raise HTTPException(status_code=404, detail="业务用户不存在")

        # 验证线索
        now_ts = get_timestamp()
        expire_ts = now_ts + data.expire_days * 24 * 60 * 60 * 1000
        assigned_count = 0

        for lead_id in data.lead_ids:
            # 检查线索是否存在且未分配
            lead_result = await session.execute(
                select(CustomerLead).where(
                    CustomerLead.id == lead_id,
                    CustomerLead.owner_user_id == str(current_user["id"]),
                )
            )
            lead = lead_result.scalar()
            if not lead:
                continue

            # 检查是否已分配给其他用户
            existing_assign = await session.execute(
                select(LeadAssignment).where(
                    LeadAssignment.lead_id == lead_id,
                    LeadAssignment.status.in_(["assigned", "used"]),
                )
            )
            if existing_assign.scalar():
                continue

            # 创建分配记录
            assignment = LeadAssignment(
                lead_id=lead_id,
                business_user_id=data.business_user_id,
                assign_type="manual",
                status="assigned",
                expire_ts=expire_ts,
                assigned_ts=now_ts,
                owner_user_id=str(current_user["id"]),
            )
            session.add(assignment)
            assigned_count += 1

        bu.assigned_leads_count += assigned_count
        await session.commit()

        return {"success": True, "assigned_count": assigned_count}


@router.get("/assigned-leads", response_model=dict)
async def list_assigned_leads(
    business_user_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取已分配的线索列表"""
    async with async_db_session() as session:
        query = select(LeadAssignment).where(
            LeadAssignment.owner_user_id == str(current_user["id"])
        )
        # 排除 API 直拉的去重标记记录(assign_type='api_pull'),这些不是真正的"分配"
        query = query.where(LeadAssignment.assign_type != "api_pull")
        if business_user_id:
            query = query.where(LeadAssignment.business_user_id == business_user_id)
        if status:
            query = query.where(LeadAssignment.status == status)

        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        query = query.order_by(desc(LeadAssignment.assigned_ts))
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(query)
        assignments = result.scalars().all()

        # 获取线索详情
        items = []
        for a in assignments:
            lead_result = await session.execute(
                select(CustomerLead).where(CustomerLead.id == a.lead_id)
            )
            lead = lead_result.scalar()
            if lead:
                items.append({
                    "assignment_id": a.id,
                    "lead_id": lead.id,
                    "nickname": lead.nickname,
                    "content": lead.content[:100] if lead.content else "",
                    "lead_score": lead.lead_score,
                    "ip_location": lead.ip_location,
                    "platform": lead.platform,
                    "status": a.status,
                    "assigned_ts": a.assigned_ts,
                    "expire_ts": a.expire_ts,
                    "business_user_id": a.business_user_id,
                })

        return {"total": total, "items": items, "page": page, "page_size": page_size}


# ==================== 跟进记录 ====================

@router.post("/follow-ups", response_model=FollowUpResponse)
async def create_follow_up(
    data: FollowUpCreate,
    current_user: dict = Depends(get_current_user),
):
    """创建跟进记录"""
    async with async_db_session() as session:
        # 验证线索分配
        assign_result = await session.execute(
            select(LeadAssignment).where(
                LeadAssignment.lead_id == data.lead_id,
                LeadAssignment.owner_user_id == str(current_user["id"]),
                LeadAssignment.status == "assigned",
            )
        )
        assignment = assign_result.scalar()
        if not assignment:
            raise HTTPException(status_code=400, detail="线索未分配给您")

        # 创建跟进记录
        follow_up = FollowUpRecord(
            lead_id=data.lead_id,
            lead_assignment_id=assignment.id,
            business_user_id=assignment.business_user_id,
            action_type=data.action_type,
            action_ts=get_timestamp(),
            result=data.result,
            notes=data.notes,
            next_follow_ts=data.next_follow_ts or 0,
            created_ts=get_timestamp(),
            owner_user_id=str(current_user["id"]),
        )
        session.add(follow_up)

        # 更新线索状态
        if data.result == "converted":
            assignment.status = "used"
            assignment.used_ts = get_timestamp()
            # 更新业务用户转化数
            bu_result = await session.execute(
                select(BusinessUser).where(BusinessUser.id == assignment.business_user_id)
            )
            bu = bu_result.scalar()
            if bu:
                bu.converted_leads_count += 1

        await session.commit()

        return FollowUpResponse(
            id=follow_up.id,
            lead_id=follow_up.lead_id,
            business_user_id=follow_up.business_user_id,
            action_type=follow_up.action_type,
            action_ts=follow_up.action_ts,
            result=follow_up.result,
            notes=follow_up.notes,
            next_follow_ts=follow_up.next_follow_ts,
            created_ts=follow_up.created_ts,
        )


@router.get("/follow-ups", response_model=dict)
async def list_follow_ups(
    lead_id: Optional[int] = None,
    business_user_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取跟进记录列表"""
    async with async_db_session() as session:
        query = select(FollowUpRecord).where(
            FollowUpRecord.owner_user_id == str(current_user["id"])
        )
        if lead_id:
            query = query.where(FollowUpRecord.lead_id == lead_id)
        if business_user_id:
            query = query.where(FollowUpRecord.business_user_id == business_user_id)

        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        query = query.order_by(desc(FollowUpRecord.action_ts))
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(query)
        records = result.scalars().all()

        items = [
            FollowUpResponse(
                id=r.id,
                lead_id=r.lead_id,
                business_user_id=r.business_user_id,
                action_type=r.action_type,
                action_ts=r.action_ts,
                result=r.result,
                notes=r.notes,
                next_follow_ts=r.next_follow_ts,
                created_ts=r.created_ts,
            )
            for r in records
        ]

        return {"total": total, "items": items, "page": page, "page_size": page_size}


# ==================== API客户端管理 ====================

@router.post("/api-clients", response_model=ApiClientResponse)
async def create_api_client(
    data: ApiClientCreate,
    current_user: dict = Depends(get_current_user),
):
    """创建API客户端"""
    async with async_db_session() as session:
        client = ApiClient(
            id=generate_id("api"),
            name=data.name,
            business_user_id=data.business_user_id,
            api_key=generate_api_key(),
            api_secret=secrets.token_urlsafe(32),
            webhook_url=data.webhook_url,
            callback_url=data.callback_url,
            filters=json.dumps(data.filters),
            push_mode=data.push_mode,
            push_interval=data.push_interval,
            status="active",
            created_ts=get_timestamp(),
            updated_ts=get_timestamp(),
            owner_user_id=str(current_user["id"]),
        )
        session.add(client)
        await session.commit()

        return ApiClientResponse(
            id=client.id,
            name=client.name,
            business_user_id=client.business_user_id,
            api_key=client.api_key,
            webhook_url=client.webhook_url,
            callback_url=client.callback_url,
            filters=json.loads(client.filters),
            push_mode=client.push_mode,
            push_interval=client.push_interval,
            status=client.status,
            last_push_ts=client.last_push_ts,
            total_pushed=client.total_pushed,
            created_ts=client.created_ts,
        )


@router.get("/api-clients", response_model=dict)
async def list_api_clients(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取API客户端列表"""
    async with async_db_session() as session:
        query = select(ApiClient).where(
            ApiClient.owner_user_id == str(current_user["id"])
        )
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        query = query.order_by(desc(ApiClient.created_ts))
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(query)
        clients = result.scalars().all()

        items = [
            ApiClientResponse(
                id=c.id,
                name=c.name,
                business_user_id=c.business_user_id,
                api_key=c.api_key,
                webhook_url=c.webhook_url,
                callback_url=c.callback_url,
                filters=json.loads(c.filters),
                push_mode=c.push_mode,
                push_interval=c.push_interval,
                status=c.status,
                last_push_ts=c.last_push_ts,
                total_pushed=c.total_pushed,
                created_ts=c.created_ts,
            )
            for c in clients
        ]

        return {"total": total, "items": items, "page": page, "page_size": page_size}


@router.put("/api-clients/{client_id}", response_model=ApiClientResponse)
async def update_api_client(
    client_id: str,
    data: ApiClientCreate,
    current_user: dict = Depends(get_current_user),
):
    """更新API客户端"""
    async with async_db_session() as session:
        client = await session.scalar(
            select(ApiClient).where(
                ApiClient.id == client_id,
                ApiClient.owner_user_id == str(current_user["id"]),
            )
        )
        if not client:
            raise HTTPException(status_code=404, detail="API client not found")

        client.name = data.name
        client.business_user_id = data.business_user_id
        client.webhook_url = data.webhook_url
        client.callback_url = data.callback_url
        client.filters = json.dumps(data.filters)
        client.push_mode = data.push_mode
        client.push_interval = data.push_interval
        client.updated_ts = get_timestamp()

        await session.commit()

        return ApiClientResponse(
            id=client.id,
            name=client.name,
            business_user_id=client.business_user_id,
            api_key=client.api_key,
            webhook_url=client.webhook_url,
            callback_url=client.callback_url,
            filters=json.loads(client.filters),
            push_mode=client.push_mode,
            push_interval=client.push_interval,
            status=client.status,
            last_push_ts=client.last_push_ts,
            total_pushed=client.total_pushed,
            created_ts=client.created_ts,
        )


@router.post("/api-clients/{client_id}/toggle", response_model=dict)
async def toggle_api_client(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """切换API客户端状态(启用/禁用)"""
    async with async_db_session() as session:
        client = await session.scalar(
            select(ApiClient).where(
                ApiClient.id == client_id,
                ApiClient.owner_user_id == str(current_user["id"]),
            )
        )
        if not client:
            raise HTTPException(status_code=404, detail="API client not found")

        client.status = "active" if client.status != "active" else "disabled"
        client.updated_ts = get_timestamp()
        await session.commit()

        return {"success": True, "status": client.status}


# ==================== 统计报表 ====================

@router.get("/stats", response_model=StatsResponse)
async def get_business_stats(
    current_user: dict = Depends(get_current_user),
):
    """获取商业化统计"""
    async with async_db_session() as session:
        owner_id = str(current_user["id"])

        total_customers = await session.scalar(
            select(func.count()).select_from(
                select(BusinessUser).where(
                    BusinessUser.owner_user_id == owner_id,
                    BusinessUser.role == "customer",
                ).subquery()
            )
        ) or 0

        total_sales = await session.scalar(
            select(func.count()).select_from(
                select(BusinessUser).where(
                    BusinessUser.owner_user_id == owner_id,
                    BusinessUser.role == "sales",
                ).subquery()
            )
        ) or 0

        total_packages = await session.scalar(
            select(func.count()).select_from(
                select(LeadPackage).where(
                    LeadPackage.owner_user_id == owner_id,
                ).subquery()
            )
        ) or 0

        total_leads_assigned = await session.scalar(
            select(func.count()).select_from(
                select(LeadAssignment)
                .join(CustomerLead, LeadAssignment.lead_id == CustomerLead.id)
                .where(CustomerLead.owner_user_id == owner_id)
                .subquery()
            )
        ) or 0

        total_revenue = await session.scalar(
            select(func.sum(PurchaseOrder.total_price)).where(
                PurchaseOrder.owner_user_id == owner_id,
                PurchaseOrder.status == "completed",
            )
        ) or 0

        total_orders = await session.scalar(
            select(func.count()).select_from(
                select(PurchaseOrder).where(
                    PurchaseOrder.owner_user_id == owner_id,
                    PurchaseOrder.status == "completed",
                ).subquery()
            )
        ) or 0

        return StatsResponse(
            total_customers=total_customers,
            total_sales=total_sales,
            total_packages=total_packages,
            total_leads_assigned=total_leads_assigned,
            total_revenue=total_revenue,
            total_orders=total_orders,
        )


# ==================== Webhook推送(后台任务) ====================

async def push_leads_to_webhook(webhook_url: str, leads_data: list, api_key: str):
    """推送线索到Webhook"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json={"leads": leads_data, "api_key": api_key},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                return resp.status == 200
    except Exception as e:
        print(f"[Webhook推送失败] {webhook_url}: {e}")
        return False


@router.post("/api-clients/{client_id}/push")
async def trigger_push_to_client(
    client_id: str,
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """手动触发推送线索到API客户端"""
    async with async_db_session() as session:
        result = await session.execute(
            select(ApiClient).where(
                ApiClient.id == client_id,
                ApiClient.owner_user_id == str(current_user["id"]),
                ApiClient.status == "active",
            )
        )
        client = result.scalar()
        if not client:
            raise HTTPException(status_code=404, detail="API客户端不存在")

        if not client.webhook_url:
            raise HTTPException(status_code=400, detail="未配置Webhook地址")

        # 解析筛选条件
        filters = json.loads(client.filters) if client.filters else {}

        # 查询符合条件的未分配线索
        query = select(CustomerLead).where(
            CustomerLead.owner_user_id == str(current_user["id"])
        )
        if filters.get("platform"):
            query = query.where(CustomerLead.platform == filters["platform"])
        if filters.get("min_score"):
            query = query.where(CustomerLead.lead_score >= filters["min_score"])
        if filters.get("ip_location"):
            query = query.where(CustomerLead.ip_location.contains(filters["ip_location"]))

        # 排除已推送的
        assigned_ids_result = await session.execute(
            select(LeadAssignment.lead_id).where(
                LeadAssignment.owner_user_id == str(current_user["id"]),
            )
        )
        assigned_ids = [row[0] for row in assigned_ids_result.fetchall()]
        if assigned_ids:
            query = query.where(CustomerLead.id.notin_(assigned_ids))

        query = query.order_by(desc(CustomerLead.lead_score)).limit(limit)
        leads_result = await session.execute(query)
        leads = leads_result.scalars().all()

        if not leads:
            return {"success": True, "pushed_count": 0, "message": "没有待推送线索"}

        # 构建推送数据
        leads_data = [
            {
                "lead_id": lead.id,
                "nickname": lead.nickname,
                "user_id": lead.user_id,
                "sec_uid": lead.sec_uid,
                "content": lead.content,
                "lead_score": lead.lead_score,
                "ip_location": lead.ip_location,
                "platform": lead.platform,
                "source_video_title": lead.source_video_title,
                "source_video_url": lead.source_video_url,
                "matched_keywords": lead.matched_keywords,
            }
            for lead in leads
        ]

        # 后台推送
        background_tasks.add_task(
            push_leads_to_webhook,
            client.webhook_url,
            leads_data,
            client.api_key,
        )

        # 更新统计
        client.last_push_ts = get_timestamp()
        client.total_pushed += len(leads)
        await session.commit()

        return {"success": True, "pushed_count": len(leads), "message": "推送任务已启动"}