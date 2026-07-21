# -*- coding: utf-8 -*-
"""
外部API路由 - 供乙方CRM系统对接使用
基于 API Key 认证，独立于内部用户认证
"""
import time
import uuid
import json
from typing import Optional, List
from fastapi import APIRouter, Header, HTTPException, Depends, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_session import get_session as async_db_session
from database.models import (
    CustomerLead, BusinessUser, LeadPackage, LeadAssignment,
    FollowUpRecord, PurchaseOrder, ApiClient
)

router = APIRouter(prefix="/v1/external", tags=["external"])

async def authenticate_api_key(api_key: str = Header(None, alias="X-API-Key")):
    if not api_key:
        raise HTTPException(status_code=401, detail="API Key missing")
    
    async with async_db_session() as session:
        client = await session.scalar(
            select(ApiClient).where(ApiClient.api_key == api_key, ApiClient.status == "active")
        )
        if not client:
            raise HTTPException(status_code=401, detail="Invalid API Key")
        
        client.last_used_ts = int(time.time() * 1000)
        await session.commit()
        
        return client

class ExternalLeadPackage(BaseModel):
    package_id: str
    name: str
    description: str
    platform: str
    level: str
    ip_location: str
    total_count: int
    available_count: int
    price_per_lead: int
    total_price: int
    expire_days: int
    status: str

class ExternalLead(BaseModel):
    lead_id: str
    package_id: str
    platform: str
    content: str
    ip_location: str
    lead_score: int
    lead_level: str
    task_id: str
    user_id: str
    user_name: str
    nickname: str
    created_at: int
    # 增强字段(客户需求:支持复制和打开链接)
    comment_url: str = ""
    profile_url: str = ""
    platform_display_id: str = ""

class PurchaseRequest(BaseModel):
    package_id: str = Field(..., description="线索包ID")
    quantity: int = Field(1, ge=1, description="购买数量")

class PurchaseResponse(BaseModel):
    success: bool
    order_id: str
    package_id: str
    purchased_count: int
    total_price: int
    balance_after: int

class PullLeadsRequest(BaseModel):
    package_id: Optional[str] = Field(None, description="线索包ID(可选,用于按包过滤)")
    task_id: Optional[str] = Field(None, description="任务ID(可选,按任务过滤)")
    platform: Optional[str] = Field(None, description="平台(可选): douyin/xhs/ks/bili/wb")
    level: Optional[str] = Field(None, description="意向等级(可选): high/medium/low")
    min_score: Optional[int] = Field(None, ge=0, le=100, description="最低意向分(可选)")
    ip_location: Optional[str] = Field(None, description="地域关键词(可选,模糊匹配)")
    keyword: Optional[str] = Field(None, description="内容关键词(可选,模糊匹配)")
    limit: int = Field(50, ge=1, le=100, description="每次拉取数量")
    offset: int = Field(0, ge=0, description="偏移量")
    only_new: bool = Field(False, description="只返回未拉取过的新线索(去重)")

class PullLeadsResponse(BaseModel):
    success: bool
    total: int
    leads: List[ExternalLead]

class CallbackRequest(BaseModel):
    lead_id: str = Field(..., description="线索ID")
    status: str = Field(..., description="跟进状态: contacted/qualified/converted/lost")
    remark: Optional[str] = Field("", description="备注信息")
    follow_up_time: Optional[int] = Field(None, description="跟进时间戳")

class CallbackResponse(BaseModel):
    success: bool
    message: str

class ListPackagesResponse(BaseModel):
    success: bool
    total: int
    packages: List[ExternalLeadPackage]

@router.get("/packages", response_model=ListPackagesResponse)
async def list_packages(
    client: ApiClient = Depends(authenticate_api_key),
    level: Optional[str] = Query(None, description="意向等级: high/medium/low"),
    platform: Optional[str] = Query(None, description="平台筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
):
    """获取可用线索包列表"""
    async with async_db_session() as session:
        query = select(LeadPackage).where(
            LeadPackage.owner_user_id == client.owner_user_id,
            LeadPackage.status == "active",
            LeadPackage.available_count > 0,
        )
        
        if level:
            query = query.where(LeadPackage.level == level)
        if platform:
            query = query.where(LeadPackage.platform == platform)
        if keyword:
            query = query.where(or_(
                LeadPackage.name.contains(keyword),
                LeadPackage.description.contains(keyword),
            ))
        
        query = query.order_by(desc(LeadPackage.created_ts))
        result = await session.execute(query)
        packages = result.scalars().all()
        
        total = len(packages)
        items = [
            ExternalLeadPackage(
                package_id=p.id,
                name=p.name,
                description=p.description,
                platform=p.platform or "",
                level=p.level or "",
                ip_location=p.ip_location or "",
                total_count=p.total_count,
                available_count=p.available_count,
                price_per_lead=p.price_per_lead,
                total_price=p.total_price,
                expire_days=p.expire_days,
                status=p.status,
            )
            for p in packages
        ]
        
        return ListPackagesResponse(success=True, total=total, packages=items)

@router.post("/packages/purchase", response_model=PurchaseResponse)
async def purchase_package(
    data: PurchaseRequest,
    client: ApiClient = Depends(authenticate_api_key),
):
    """购买线索包"""
    async with async_db_session() as session:
        package = await session.scalar(
            select(LeadPackage).where(LeadPackage.id == data.package_id)
        )
        if not package:
            raise HTTPException(status_code=404, detail="Package not found")
        if package.status != "active":
            raise HTTPException(status_code=400, detail="Package not available")
        if package.available_count < data.quantity:
            raise HTTPException(status_code=400, detail="Insufficient available leads")
        
        customer = await session.scalar(
            select(BusinessUser).where(BusinessUser.id == client.business_user_id)
        )
        if not customer:
            raise HTTPException(status_code=400, detail="Customer not found")
        
        total_price = data.quantity * package.price_per_lead
        if customer.balance < total_price:
            raise HTTPException(status_code=400, detail="Insufficient balance")
        
        order = PurchaseOrder(
            id=generate_id("ord"),
            business_user_id=customer.id,
            package_id=package.id,
            lead_count=data.quantity,
            total_price=total_price,
            status="paid",
            owner_user_id=package.owner_user_id,
            created_ts=int(time.time() * 1000),
        )
        session.add(order)
        
        customer.balance -= total_price
        customer.total_spent += total_price
        
        package.sold_count += data.quantity
        package.available_count -= data.quantity
        
        leads_query = select(CustomerLead).where(
            CustomerLead.owner_user_id == package.owner_user_id,
            CustomerLead.id.not_in(
                select(LeadAssignment.lead_id).where(
                    LeadAssignment.status.in_(["assigned", "used"])
                )
            )
        )
        if package.platform:
            leads_query = leads_query.where(CustomerLead.platform == package.platform)
        if package.min_score > 0:
            leads_query = leads_query.where(CustomerLead.lead_score >= package.min_score)
        if package.max_score < 100:
            leads_query = leads_query.where(CustomerLead.lead_score <= package.max_score)
        if package.level:
            lvl = package.level.lower()
            if lvl == "high":
                leads_query = leads_query.where(CustomerLead.lead_score >= 50)
            elif lvl == "medium":
                leads_query = leads_query.where(CustomerLead.lead_score >= 25, CustomerLead.lead_score < 50)
            elif lvl == "low":
                leads_query = leads_query.where(CustomerLead.lead_score < 25)
        if package.ip_location:
            leads_query = leads_query.where(CustomerLead.ip_location.contains(package.ip_location))
        if package.keyword:
            leads_query = leads_query.where(CustomerLead.content.contains(package.keyword))
        
        leads_result = await session.execute(leads_query.limit(data.quantity))
        leads = leads_result.scalars().all()
        
        for lead in leads:
            assignment = LeadAssignment(
                lead_id=lead.id,
                package_id=package.id,
                business_user_id=customer.id,
                assign_type="purchase",
                price_paid=package.price_per_lead,
                status="assigned",
                assigned_ts=int(time.time() * 1000),
                owner_user_id=package.owner_user_id,
            )
            session.add(assignment)
        
        await session.commit()
        
        return PurchaseResponse(
            success=True,
            order_id=order.id,
            package_id=package.id,
            purchased_count=data.quantity,
            total_price=total_price,
            balance_after=customer.balance,
        )

@router.post("/leads/pull", response_model=PullLeadsResponse)
async def pull_leads(
    data: PullLeadsRequest,
    client: ApiClient = Depends(authenticate_api_key),
):
    """拉取线索数据

    两种模式:
    1. 包年/付费 API 用户:直接按条件拉取 owner_user_id 名下的所有线索,无需购买
    2. 按条计费用户:先调 /packages/purchase 购买,再用 package_id 拉取已购买线索
    """
    async with async_db_session() as session:
        # 判断模式:传 package_id 且该包有购买记录 → 按购买模式拉取
        is_purchase_mode = False
        package = None
        if data.package_id:
            package = await session.scalar(
                select(LeadPackage).where(LeadPackage.id == data.package_id)
            )
            if package:
                # 检查是否有该客户的购买记录
                assignment_count = await session.scalar(
                    select(func.count()).select_from(LeadAssignment).where(
                        LeadAssignment.business_user_id == client.business_user_id,
                        LeadAssignment.package_id == data.package_id,
                        LeadAssignment.status.in_(["assigned", "used"]),
                    )
                )
                is_purchase_mode = assignment_count > 0

        if is_purchase_mode and package:
            # 购买模式:只返回已购买的线索
            query = select(LeadAssignment).where(
                LeadAssignment.business_user_id == client.business_user_id,
                LeadAssignment.package_id == data.package_id,
                LeadAssignment.status.in_(["assigned", "used"]),
            ).order_by(desc(LeadAssignment.assigned_ts))

            count_query = select(func.count()).select_from(LeadAssignment).where(
                LeadAssignment.business_user_id == client.business_user_id,
                LeadAssignment.package_id == data.package_id,
                LeadAssignment.status.in_(["assigned", "used"]),
            )
            total = await session.scalar(count_query)

            query = query.offset(data.offset).limit(data.limit)
            result = await session.execute(query)
            assignments = result.scalars().all()

            lead_ids = [a.lead_id for a in assignments]
            leads = []
            if lead_ids:
                leads_result = await session.execute(
                    select(CustomerLead).where(CustomerLead.id.in_(lead_ids))
                )
                lead_map = {l.id: l for l in leads_result.scalars().all()}
                for a in assignments:
                    lead = lead_map.get(a.lead_id)
                    if lead:
                        lvl = "high" if lead.lead_score >= 50 else "medium" if lead.lead_score >= 25 else "low"
                        leads.append(_to_external_lead(lead, a.package_id))
            return PullLeadsResponse(success=True, total=total, leads=leads)

        # 直拉模式(包年/付费 API 用户):直接从 CustomerLead 表按条件拉取
        base_query = select(CustomerLead).where(
            CustomerLead.owner_user_id == client.owner_user_id
        )

        # 条件过滤
        if data.platform:
            base_query = base_query.where(CustomerLead.platform == data.platform)
        if data.task_id:
            base_query = base_query.where(CustomerLead.task_id == data.task_id)
        if data.min_score is not None:
            base_query = base_query.where(CustomerLead.lead_score >= data.min_score)
        if data.level:
            lvl = data.level.lower()
            if lvl == "high":
                base_query = base_query.where(CustomerLead.lead_score >= 50)
            elif lvl == "medium":
                base_query = base_query.where(CustomerLead.lead_score >= 25, CustomerLead.lead_score < 50)
            elif lvl == "low":
                base_query = base_query.where(CustomerLead.lead_score < 25)
        if data.ip_location:
            base_query = base_query.where(CustomerLead.ip_location.contains(data.ip_location))
        if data.keyword:
            base_query = base_query.where(CustomerLead.content.contains(data.keyword))

        # only_new 模式:排除已拉取过的线索(用 LeadAssignment status='pulled' 标记)
        if data.only_new:
            pulled_subq = select(LeadAssignment.lead_id).where(
                LeadAssignment.business_user_id == client.business_user_id,
                LeadAssignment.status == "pulled",
            )
            base_query = base_query.where(CustomerLead.id.not_in(pulled_subq))

        # 总数
        count_query = select(func.count()).select_from(base_query.subquery())
        total = await session.scalar(count_query) or 0

        # 分页(按意向分降序,高意向优先)
        page_query = base_query.order_by(desc(CustomerLead.lead_score), desc(CustomerLead.add_ts))
        page_query = page_query.offset(data.offset).limit(data.limit)
        result = await session.execute(page_query)
        leads_rows = result.scalars().all()

        # 标记为已拉取(only_new 去重用)
        now_ms = int(time.time() * 1000)
        for lead in leads_rows:
            existing = await session.scalar(
                select(LeadAssignment).where(
                    LeadAssignment.lead_id == lead.id,
                    LeadAssignment.business_user_id == client.business_user_id,
                    LeadAssignment.status == "pulled",
                )
            )
            if not existing:
                session.add(LeadAssignment(
                    lead_id=lead.id,
                    package_id=data.package_id or "",
                    business_user_id=client.business_user_id,
                    assign_type="api_pull",
                    price_paid=0,
                    status="pulled",
                    assigned_ts=now_ms,
                    owner_user_id=client.owner_user_id,
                ))

        await session.commit()

        leads = [_to_external_lead(l, data.package_id or "") for l in leads_rows]
        return PullLeadsResponse(success=True, total=total, leads=leads)


def _to_external_lead(lead: CustomerLead, package_id: str) -> ExternalLead:
    """CustomerLead → ExternalLead 转换"""
    lvl = "high" if lead.lead_score >= 50 else "medium" if lead.lead_score >= 25 else "low"
    return ExternalLead(
        lead_id=str(lead.id),
        package_id=package_id,
        platform=lead.platform or "",
        content=lead.content or "",
        ip_location=lead.ip_location or "",
        lead_score=lead.lead_score or 0,
        lead_level=lvl,
        task_id=lead.task_id or "",
        user_id=lead.user_id or "",
        user_name=lead.nickname or "",
        nickname=lead.nickname or "",
        created_at=lead.add_ts or 0,
        # 增强字段(客户需求:支持复制和打开链接)
        comment_url=getattr(lead, "comment_url", "") or "",
        profile_url=getattr(lead, "profile_url", "") or "",
        platform_display_id=getattr(lead, "platform_display_id", "") or "",
    )

@router.post("/status/callback", response_model=CallbackResponse)
async def callback_status(
    data: CallbackRequest,
    client: ApiClient = Depends(authenticate_api_key),
):
    """回传线索跟进状态"""
    async with async_db_session() as session:
        try:
            lead_id_int = int(data.lead_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid lead_id format")
        
        assignment = await session.scalar(
            select(LeadAssignment).where(
                LeadAssignment.lead_id == lead_id_int,
                LeadAssignment.business_user_id == client.business_user_id,
            )
        )
        if not assignment:
            raise HTTPException(status_code=404, detail="Lead assignment not found")
        
        assignment.status = data.status
        assignment.updated_ts = int(time.time() * 1000)
        
        if data.status == "converted":
            customer = await session.scalar(
                select(BusinessUser).where(BusinessUser.id == client.business_user_id)
            )
            if customer:
                customer.converted_leads_count += 1
        
        follow_up = FollowUpRecord(
            lead_id=lead_id_int,
            lead_assignment_id=assignment.id if hasattr(assignment, 'id') else 0,
            business_user_id=client.business_user_id,
            action_type="call",
            action_ts=int(time.time() * 1000),
            result=data.status,
            notes=data.remark or "",
            created_ts=int(time.time() * 1000),
        )
        session.add(follow_up)
        
        if data.status == "converted":
            assignment.status = "used"
            assignment.used_ts = int(time.time() * 1000)
        elif data.status in ["lost", "failed"]:
            assignment.status = "expired"
        
        await session.commit()
        
        return CallbackResponse(success=True, message="Status updated successfully")

def generate_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:8]}"