# -*- coding: utf-8 -*-
"""
套餐与计费服务(v6.6 商业化)

混合模式:
- 套餐订阅: free / basic / pro / enterprise,按月/年订阅
- 超额按量计费: 套餐配额用尽后,从余额扣款继续采集

套餐配额:
- free:       3 任务,  1000/任务, 7 天内数据,    100 评论/任务
- basic:     10 任务, 10000/任务, 30 天内数据,   500 评论/任务
- pro:       50 任务, 50000/任务, 180 天内数据, 2000 评论/任务
- enterprise: 无限,  200000/任务, 不限时间,     5000 评论/任务

按量计费(分):
- 视频采集: 1 分/条
- 评论采集: 0.1 分/条(10 条=1 分)
- 线索捕获: 5 分/条
"""
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from database.user_models import UserModel
from database.db_session import get_async_engine
import config


# ============ 套餐配置 ============

@dataclass(frozen=True)
class PlanConfig:
    """套餐配置(不可变)"""
    name: str
    display_name: str
    # 配额限制
    max_tasks: int                # 最大任务数(0=不限)
    max_notes_per_task: int       # 每任务最大视频/笔记采集量
    max_publish_time_type: int    # 数据时效限制: 0=不限, 7=一周内, 30=一月内, 180=半年内
    min_comments_per_task: int    # 每任务最低评论保障数(确保关键数据)
    max_comments_per_task: int    # 每任务最大评论采集数(0=不限)
    # 计费(分)
    price_monthly: int            # 月订阅价格(分)
    price_yearly: int             # 年订阅价格(分)
    # 超额单价(分/条)
    overage_note_price: int       # 超额视频采集单价
    overage_comment_price: float  # 超额评论采集单价(分/条,可为小数)
    overage_lead_price: int       # 超额线索捕获单价


# 套餐配置表(冻结后不可变,避免运行时被修改)
PLAN_CONFIGS: dict = {
    "free": PlanConfig(
        name="free",
        display_name="免费版",
        max_tasks=3,
        max_notes_per_task=1000,
        max_publish_time_type=7,
        min_comments_per_task=50,
        max_comments_per_task=500,
        price_monthly=0,
        price_yearly=0,
        overage_note_price=1,
        overage_comment_price=0.1,
        overage_lead_price=5,
    ),
    "basic": PlanConfig(
        name="basic",
        display_name="基础版",
        max_tasks=10,
        max_notes_per_task=10000,
        max_publish_time_type=30,
        min_comments_per_task=200,
        max_comments_per_task=2000,
        price_monthly=9900,       # 99 元/月
        price_yearly=99000,       # 990 元/年
        overage_note_price=1,
        overage_comment_price=0.1,
        overage_lead_price=5,
    ),
    "pro": PlanConfig(
        name="pro",
        display_name="专业版",
        max_tasks=50,
        max_notes_per_task=50000,
        max_publish_time_type=180,
        min_comments_per_task=500,
        max_comments_per_task=5000,
        price_monthly=29900,      # 299 元/月
        price_yearly=299000,      # 2990 元/年
        overage_note_price=1,
        overage_comment_price=0.1,
        overage_lead_price=5,
    ),
    "enterprise": PlanConfig(
        name="enterprise",
        display_name="企业版",
        max_tasks=0,              # 0=不限
        max_notes_per_task=200000,
        max_publish_time_type=0,  # 0=不限
        min_comments_per_task=1000,
        max_comments_per_task=0,  # 0=不限
        price_monthly=99900,      # 999 元/月
        price_yearly=999000,      # 9990 元/年
        overage_note_price=1,
        overage_comment_price=0.1,
        overage_lead_price=5,
    ),
}


def get_plan_config(plan_type: str) -> PlanConfig:
    """获取套餐配置,未知类型降级为 free"""
    return PLAN_CONFIGS.get(plan_type, PLAN_CONFIGS["free"])


def is_admin_plan_unlimited(user: dict) -> bool:
    """管理员不受套餐限制"""
    return user.get("role") == "admin"


# ============ 套餐状态查询 ============

def _get_session_factory():
    engine = get_async_engine(config.SAVE_DATA_OPTION)
    if not engine:
        return None
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def is_plan_active(user: dict) -> bool:
    """检查用户套餐是否在有效期内"""
    if is_admin_plan_unlimited(user):
        return True
    expires_ts = user.get("plan_expires_ts", 0) or 0
    if expires_ts == 0:
        return True  # 永久有效
    return int(time.time() * 1000) < expires_ts


def get_user_plan_info(user: dict) -> dict:
    """获取用户套餐信息(含配额、用量、状态)"""
    if is_admin_plan_unlimited(user):
        return {
            "plan_type": "enterprise",
            "plan_name": "管理员(不限)",
            "is_active": True,
            "expires_ts": 0,
            "max_tasks": 0,
            "max_notes_per_task": 0,
            "max_publish_time_type": 0,
            "min_comments_per_task": 0,
            "max_comments_per_task": 0,
            "balance": user.get("balance", 0),
            "usage_notes_count": 0,
            "usage_comments_count": 0,
            "usage_leads_count": 0,
            "is_admin": True,
        }

    plan_type = user.get("plan_type", "free") or "free"
    plan = get_plan_config(plan_type)
    return {
        "plan_type": plan_type,
        "plan_name": plan.display_name,
        "is_active": is_plan_active(user),
        "expires_ts": user.get("plan_expires_ts", 0) or 0,
        "max_tasks": plan.max_tasks,
        "max_notes_per_task": plan.max_notes_per_task,
        "max_publish_time_type": plan.max_publish_time_type,
        "min_comments_per_task": plan.min_comments_per_task,
        "max_comments_per_task": plan.max_comments_per_task,
        "balance": user.get("balance", 0) or 0,
        "usage_notes_count": user.get("usage_notes_count", 0) or 0,
        "usage_comments_count": user.get("usage_comments_count", 0) or 0,
        "usage_leads_count": user.get("usage_leads_count", 0) or 0,
        "is_admin": False,
    }


# ============ 配额校验 ============

async def check_task_quota(user: dict, current_task_count: int) -> Tuple[bool, str]:
    """校验用户是否可创建新任务

    Args:
        user: 当前用户字典
        current_task_count: 用户当前任务总数

    Returns:
        (allowed, message)
    """
    if is_admin_plan_unlimited(user):
        return True, "管理员不受限制"

    if not is_plan_active(user):
        plan_type = user.get("plan_type", "free") or "free"
        plan = get_plan_config(plan_type)
        return False, f"套餐已过期({plan.display_name}),请续费后继续使用"

    plan_type = user.get("plan_type", "free") or "free"
    plan = get_plan_config(plan_type)

    if plan.max_tasks > 0 and current_task_count >= plan.max_tasks:
        return False, f"任务数已达上限({plan.max_tasks}),请升级套餐或删除旧任务"

    return True, "配额充足"


def _effective_plan_type(user: dict) -> str:
    """获取用户当前有效套餐类型(过期则降级为 free)"""
    if is_admin_plan_unlimited(user):
        return "enterprise"
    plan_type = user.get("plan_type", "free") or "free"
    if not is_plan_active(user):
        return "free"
    return plan_type


def clamp_max_notes(user: dict, requested_max_notes: int) -> Tuple[int, str]:
    """根据套餐限制 max_notes

    Args:
        user: 当前用户字典
        requested_max_notes: 用户请求的 max_notes

    Returns:
        (adjusted_max_notes, message)
    """
    if is_admin_plan_unlimited(user):
        return max(requested_max_notes, 50000), "管理员模式"

    plan_type = _effective_plan_type(user)
    plan = get_plan_config(plan_type)

    if requested_max_notes > plan.max_notes_per_task:
        return plan.max_notes_per_task, f"已根据套餐({plan.display_name})调整 max_notes 为 {plan.max_notes_per_task}"

    return requested_max_notes, ""


def clamp_publish_time_type(user: dict, requested_publish_time: int) -> Tuple[int, str]:
    """根据套餐限制 publish_time_type(数据时效性)

    确保低级套餐只能采集近期数据,保证数据时效性

    Args:
        user: 当前用户字典
        requested_publish_time: 用户请求的 publish_time_type

    Returns:
        (adjusted_publish_time, message)
    """
    if is_admin_plan_unlimited(user):
        return requested_publish_time, "管理员模式"

    plan_type = _effective_plan_type(user)
    plan = get_plan_config(plan_type)

    # 如果套餐有时效限制(>0),且用户请求的时效超出限制
    # publish_time_type: 0=不限, 1=一天内, 7=一周内, 30=一月内, 180=半年内
    # 数值越大表示允许越老的数据
    if plan.max_publish_time_type > 0:
        if requested_publish_time == 0 or requested_publish_time > plan.max_publish_time_type:
            return plan.max_publish_time_type, f"已根据套餐({plan.display_name})限制数据时效为 {plan.max_publish_time_type} 天内"

    return requested_publish_time, ""


def get_min_comments_target(user: dict) -> int:
    """获取用户套餐的最低评论保障数

    确保每个任务能采集到足够的评论数据用于线索分析
    """
    if is_admin_plan_unlimited(user):
        return 1000

    plan_type = _effective_plan_type(user)
    plan = get_plan_config(plan_type)
    return plan.min_comments_per_task


def get_max_comments_limit(user: dict) -> int:
    """获取用户套餐的最大评论采集数限制"""
    if is_admin_plan_unlimited(user):
        return 0  # 不限

    plan_type = _effective_plan_type(user)
    plan = get_plan_config(plan_type)
    return plan.max_comments_per_task


# ============ 用量统计与计费 ============

async def record_usage(
    user_id: int,
    notes_count: int = 0,
    comments_count: int = 0,
    leads_count: int = 0,
) -> dict:
    """记录用户用量并扣费(超额部分从余额扣除)

    Args:
        user_id: 用户ID
        notes_count: 本次采集的视频/笔记数
        comments_count: 本次采集的评论数
        leads_count: 本次捕获的线索数

    Returns:
        {"success": bool, "message": str, "charged": int, "balance": int}
    """
    factory = _get_session_factory()
    if not factory:
        return {"success": False, "message": "数据库不可用", "charged": 0, "balance": 0}

    async with factory() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == user_id))
        u = result.scalars().first()
        if not u:
            return {"success": False, "message": "用户不存在", "charged": 0, "balance": 0}

        # 管理员不计费
        if u.role == "admin":
            return {"success": True, "message": "管理员不计费", "charged": 0, "balance": 0}

        plan_type = u.plan_type or "free"
        plan = get_plan_config(plan_type)

        # 累加用量
        new_notes = (u.usage_notes_count or 0) + notes_count
        new_comments = (u.usage_comments_count or 0) + comments_count
        new_leads = (u.usage_leads_count or 0) + leads_count

        # 计算超额费用(分)
        charged = 0
        if plan.max_notes_per_task > 0 and new_notes > plan.max_notes_per_task:
            # 简化:超额部分按单价计费(实际可按周期配额计算)
            overage_notes = max(0, notes_count)  # 本次采集量计费
            charged += int(overage_notes * plan.overage_note_price)

        if plan.max_comments_per_task > 0 and new_comments > plan.max_comments_per_task:
            overage_comments = max(0, comments_count)
            charged += int(overage_comments * plan.overage_comment_price)

        charged += int(max(0, leads_count) * plan.overage_lead_price)

        # 扣费
        new_balance = (u.balance or 0) - charged
        new_total_spent = (u.total_spent or 0) + charged

        # 初始化计费周期(首次记录)
        now_ms = int(time.time() * 1000)
        period_start = u.usage_period_start_ts or now_ms

        await session.execute(
            update(UserModel).where(UserModel.id == user_id).values(
                usage_notes_count=new_notes,
                usage_comments_count=new_comments,
                usage_leads_count=new_leads,
                balance=new_balance,
                total_spent=new_total_spent,
                usage_period_start_ts=period_start,
            )
        )
        await session.commit()

        return {
            "success": True,
            "message": f"用量已记录(视频+{notes_count}, 评论+{comments_count}, 线索+{leads_count})",
            "charged": charged,
            "balance": new_balance,
        }


async def reset_usage_period(user_id: int) -> bool:
    """重置用户计费周期(订阅续期时调用)"""
    factory = _get_session_factory()
    if not factory:
        return False

    async with factory() as session:
        now_ms = int(time.time() * 1000)
        await session.execute(
            update(UserModel).where(UserModel.id == user_id).values(
                usage_period_start_ts=now_ms,
                usage_notes_count=0,
                usage_comments_count=0,
                usage_leads_count=0,
            )
        )
        await session.commit()
        return True


# ============ 套餐升级 ============

async def upgrade_plan(
    user_id: int,
    new_plan_type: str,
    duration: str = "monthly",
    admin_override: bool = False,
) -> dict:
    """升级用户套餐

    Args:
        user_id: 用户ID
        new_plan_type: 新套餐类型 (free/basic/pro/enterprise)
        duration: 订阅周期 (monthly/yearly)
        admin_override: 管理员操作(不扣费)

    Returns:
        {"success": bool, "message": str, "plan_type": str, "expires_ts": int}
    """
    if new_plan_type not in PLAN_CONFIGS:
        return {"success": False, "message": f"未知套餐类型: {new_plan_type}"}

    plan = PLAN_CONFIGS[new_plan_type]
    factory = _get_session_factory()
    if not factory:
        return {"success": False, "message": "数据库不可用"}

    async with factory() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == user_id))
        u = result.scalars().first()
        if not u:
            return {"success": False, "message": "用户不存在"}

        now_ms = int(time.time() * 1000)

        # 计算价格和有效期
        if duration == "yearly":
            price = plan.price_yearly
            expires = now_ms + 365 * 24 * 3600 * 1000
        else:
            price = plan.price_monthly
            expires = now_ms + 30 * 24 * 3600 * 1000

        # 免费套餐不扣费
        if new_plan_type == "free":
            price = 0
            expires = 0  # 永久

        # 扣费(管理员操作不扣费)
        charged = 0
        if price > 0 and not admin_override:
            if (u.balance or 0) < price:
                return {
                    "success": False,
                    "message": f"余额不足,需 {price / 100:.2f} 元,当前余额 {(u.balance or 0) / 100:.2f} 元",
                }
            charged = price

        new_balance = (u.balance or 0) - charged
        new_total_spent = (u.total_spent or 0) + charged

        await session.execute(
            update(UserModel).where(UserModel.id == user_id).values(
                plan_type=new_plan_type,
                plan_started_ts=now_ms,
                plan_expires_ts=expires,
                balance=new_balance,
                total_spent=new_total_spent,
                # 重置用量周期
                usage_period_start_ts=now_ms,
                usage_notes_count=0,
                usage_comments_count=0,
                usage_leads_count=0,
            )
        )
        await session.commit()

        return {
            "success": True,
            "message": f"套餐已升级为 {plan.display_name}({duration}),扣费 {charged / 100:.2f} 元",
            "plan_type": new_plan_type,
            "expires_ts": expires,
            "charged": charged,
            "balance": new_balance,
        }


async def recharge_balance(user_id: int, amount_cents: int) -> dict:
    """用户余额充值

    Args:
        user_id: 用户ID
        amount_cents: 充值金额(分)

    Returns:
        {"success": bool, "message": str, "balance": int}
    """
    if amount_cents <= 0:
        return {"success": False, "message": "充值金额必须大于 0"}

    factory = _get_session_factory()
    if not factory:
        return {"success": False, "message": "数据库不可用"}

    async with factory() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == user_id))
        u = result.scalars().first()
        if not u:
            return {"success": False, "message": "用户不存在"}

        new_balance = (u.balance or 0) + amount_cents
        await session.execute(
            update(UserModel).where(UserModel.id == user_id).values(balance=new_balance)
        )
        await session.commit()

        return {
            "success": True,
            "message": f"充值成功 {amount_cents / 100:.2f} 元,当前余额 {new_balance / 100:.2f} 元",
            "balance": new_balance,
        }


def list_all_plans() -> list:
    """列出所有套餐配置(供前端展示)"""
    plans = []
    for key, plan in PLAN_CONFIGS.items():
        plans.append({
            "name": plan.name,
            "display_name": plan.display_name,
            "max_tasks": plan.max_tasks,
            "max_notes_per_task": plan.max_notes_per_task,
            "max_publish_time_type": plan.max_publish_time_type,
            "min_comments_per_task": plan.min_comments_per_task,
            "max_comments_per_task": plan.max_comments_per_task,
            "price_monthly": plan.price_monthly,
            "price_yearly": plan.price_yearly,
            "price_monthly_yuan": plan.price_monthly / 100,
            "price_yearly_yuan": plan.price_yearly / 100,
            "overage_note_price": plan.overage_note_price,
            "overage_comment_price": plan.overage_comment_price,
            "overage_lead_price": plan.overage_lead_price,
        })
    return plans
