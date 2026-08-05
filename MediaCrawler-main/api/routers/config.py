# -*- coding: utf-8 -*-
"""
配置管理路由 - 意向规则与关键词库的 CRUD

支持运行时增删改查,无需重启服务即可调整评分规则。
首次访问时自动从 tasks.py 硬编码规则初始化数据库。
"""
import json
import time
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update, delete, func

from database.models import IntentRule, KeywordCategory
from database.db_session import get_session
from .auth import get_current_user

router = APIRouter(
    prefix="/config",
    tags=["配置管理"],
    responses={404: {"description": "Not found"}},
)


# ==================== Schema ====================
class IntentRuleCreate(BaseModel):
    rule_type: str = Field(..., description="规则类型: strong_intent/industry_template/nostalgia/discussion/past_purchase")
    pattern: str = Field(..., description="匹配模式,模板用 {w} 占位")
    action: str = Field(default="upgrade", description="动作: upgrade/downgrade")
    target_level: str = Field(default="high", description="目标等级: high/middle/low")
    score_delta: int = Field(default=0, description="分数调整值")
    score_cap: int = Field(default=0, description="分数上限,0=不限")
    enabled: int = Field(default=1, description="是否启用: 0/1")
    category: str = Field(default="general", description="分类")
    note: str = Field(default="", description="备注")


class IntentRuleUpdate(BaseModel):
    pattern: Optional[str] = None
    action: Optional[str] = None
    target_level: Optional[str] = None
    score_delta: Optional[int] = None
    score_cap: Optional[int] = None
    enabled: Optional[int] = None
    category: Optional[str] = None
    note: Optional[str] = None


class KeywordCategoryCreate(BaseModel):
    name: str = Field(..., description="分类名称")
    keywords: List[str] = Field(default=[], description="关键词列表")
    weight: int = Field(default=1, description="权重倍数")
    category: str = Field(default="general", description="上级分类")
    enabled: int = Field(default=1, description="是否启用")


class KeywordCategoryUpdate(BaseModel):
    name: Optional[str] = None
    keywords: Optional[List[str]] = None
    weight: Optional[int] = None
    category: Optional[str] = None
    enabled: Optional[int] = None


@router.get("/apollo-status")
async def apollo_status(current_user: dict = Depends(get_current_user)):
    """返回脱敏后的 Apollo 启动加载状态，不返回地址或配置值。"""
    from config.runtime_config import get_apollo_status

    return get_apollo_status()


# ==================== 意向规则 CRUD ====================
@router.get("/intent-rules")
async def list_intent_rules(
    rule_type: Optional[str] = Query(None, description="按规则类型筛选"),
    enabled: Optional[int] = Query(None, description="按启用状态筛选"),
    current_user: dict = Depends(get_current_user),
):
    """获取意向规则列表"""
    await _ensure_rules_seeded(str(current_user["id"]))
    async with get_session() as session:
        q = select(IntentRule).where(IntentRule.owner_user_id == str(current_user["id"]))
        if rule_type:
            q = q.where(IntentRule.rule_type == rule_type)
        if enabled is not None:
            q = q.where(IntentRule.enabled == enabled)
        q = q.order_by(IntentRule.rule_type, IntentRule.id)
        result = await session.execute(q)
        rules = result.scalars().all()
        return {
            "items": [
                {
                    "id": r.id,
                    "rule_type": r.rule_type,
                    "pattern": r.pattern,
                    "action": r.action,
                    "target_level": r.target_level,
                    "score_delta": r.score_delta,
                    "score_cap": r.score_cap,
                    "enabled": bool(r.enabled),
                    "category": r.category,
                    "note": r.note,
                }
                for r in rules
            ],
            "total": len(rules),
        }


@router.post("/intent-rules")
async def create_intent_rule(
    rule: IntentRuleCreate,
    current_user: dict = Depends(get_current_user),
):
    """创建意向规则"""
    now = int(time.time())
    new_rule = IntentRule(
        rule_type=rule.rule_type,
        pattern=rule.pattern,
        action=rule.action,
        target_level=rule.target_level,
        score_delta=rule.score_delta,
        score_cap=rule.score_cap,
        enabled=rule.enabled,
        category=rule.category,
        note=rule.note,
        owner_user_id=str(current_user["id"]),
        created_ts=now,
        updated_ts=now,
    )
    async with get_session() as session:
        session.add(new_rule)
        await session.commit()
        return {"success": True, "id": new_rule.id}


@router.put("/intent-rules/{rule_id}")
async def update_intent_rule(
    rule_id: int,
    rule: IntentRuleUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新意向规则"""
    now = int(time.time())
    values = {k: v for k, v in rule.dict().items() if v is not None}
    if not values:
        raise HTTPException(status_code=400, detail="无更新字段")
    values["updated_ts"] = now
    async with get_session() as session:
        result = await session.execute(
            update(IntentRule)
            .where(IntentRule.id == rule_id, IntentRule.owner_user_id == str(current_user["id"]))
            .values(**values)
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="规则不存在")
        return {"success": True}


@router.delete("/intent-rules/{rule_id}")
async def delete_intent_rule(
    rule_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除意向规则"""
    async with get_session() as session:
        result = await session.execute(
            delete(IntentRule)
            .where(IntentRule.id == rule_id, IntentRule.owner_user_id == str(current_user["id"]))
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="规则不存在")
        return {"success": True}


@router.post("/intent-rules/seed")
async def seed_intent_rules(current_user: dict = Depends(get_current_user)):
    """从硬编码规则初始化数据库(仅首次)"""
    count = await _ensure_rules_seeded(str(current_user["id"]))
    return {"success": True, "seeded": count}


async def _ensure_rules_seeded(owner_user_id: str) -> int:
    """若数据库为空,从 tasks.py 硬编码规则初始化"""
    from .tasks import (
        STRONG_INTENT_SIGNALS, INDUSTRY_SIGNAL_TEMPLATES,
        NOSTALGIA_PATTERNS, DISCUSSION_PATTERNS, PAST_PURCHASE_PATTERNS,
    )
    async with get_session() as session:
        count_result = await session.execute(
            select(func.count(IntentRule.id)).where(IntentRule.owner_user_id == owner_user_id)
        )
        if count_result.scalar() > 0:
            return 0

        now = int(time.time())
        rules_to_add = []
        for p in STRONG_INTENT_SIGNALS:
            rules_to_add.append(IntentRule(
                rule_type="strong_intent", pattern=p, action="upgrade",
                target_level="high", score_delta=20, enabled=1,
                category="通用强意向", owner_user_id=owner_user_id,
                created_ts=now, updated_ts=now,
            ))
        for p in INDUSTRY_SIGNAL_TEMPLATES:
            rules_to_add.append(IntentRule(
                rule_type="industry_template", pattern=p, action="upgrade",
                target_level="high", score_delta=15, enabled=1,
                category="行业模板", owner_user_id=owner_user_id,
                created_ts=now, updated_ts=now,
            ))
        for p in NOSTALGIA_PATTERNS:
            rules_to_add.append(IntentRule(
                rule_type="nostalgia", pattern=p, action="downgrade",
                target_level="low", score_cap=30, enabled=1,
                category="回忆降级", owner_user_id=owner_user_id,
                created_ts=now, updated_ts=now,
            ))
        for p in DISCUSSION_PATTERNS:
            rules_to_add.append(IntentRule(
                rule_type="discussion", pattern=p, action="downgrade",
                target_level="middle", score_cap=45, enabled=1,
                category="讨论降级", owner_user_id=owner_user_id,
                created_ts=now, updated_ts=now,
            ))
        for p in PAST_PURCHASE_PATTERNS:
            rules_to_add.append(IntentRule(
                rule_type="past_purchase", pattern=p, action="downgrade",
                target_level="middle", score_cap=45, enabled=1,
                category="过去式降级", owner_user_id=owner_user_id,
                created_ts=now, updated_ts=now,
            ))
        session.add_all(rules_to_add)
        await session.commit()
        return len(rules_to_add)


# ==================== 关键词库 CRUD ====================
@router.get("/keyword-categories")
async def list_keyword_categories(current_user: dict = Depends(get_current_user)):
    """获取关键词分类列表"""
    async with get_session() as session:
        result = await session.execute(
            select(KeywordCategory)
            .where(KeywordCategory.owner_user_id == str(current_user["id"]))
            .order_by(KeywordCategory.id)
        )
        items = result.scalars().all()
        return {
            "items": [
                {
                    "id": c.id,
                    "name": c.name,
                    "keywords": json.loads(c.keywords) if c.keywords else [],
                    "weight": c.weight,
                    "category": c.category,
                    "enabled": bool(c.enabled),
                }
                for c in items
            ],
            "total": len(items),
        }


@router.post("/keyword-categories")
async def create_keyword_category(
    cat: KeywordCategoryCreate,
    current_user: dict = Depends(get_current_user),
):
    """创建关键词分类"""
    now = int(time.time())
    new_cat = KeywordCategory(
        name=cat.name,
        keywords=json.dumps(cat.keywords, ensure_ascii=False),
        weight=cat.weight,
        category=cat.category,
        enabled=cat.enabled,
        owner_user_id=str(current_user["id"]),
        created_ts=now,
        updated_ts=now,
    )
    async with get_session() as session:
        session.add(new_cat)
        await session.commit()
        return {"success": True, "id": new_cat.id}


@router.put("/keyword-categories/{cat_id}")
async def update_keyword_category(
    cat_id: int,
    cat: KeywordCategoryUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新关键词分类"""
    now = int(time.time())
    values = {}
    if cat.name is not None: values["name"] = cat.name
    if cat.keywords is not None: values["keywords"] = json.dumps(cat.keywords, ensure_ascii=False)
    if cat.weight is not None: values["weight"] = cat.weight
    if cat.category is not None: values["category"] = cat.category
    if cat.enabled is not None: values["enabled"] = cat.enabled
    if not values:
        raise HTTPException(status_code=400, detail="无更新字段")
    values["updated_ts"] = now
    async with get_session() as session:
        result = await session.execute(
            update(KeywordCategory)
            .where(KeywordCategory.id == cat_id, KeywordCategory.owner_user_id == str(current_user["id"]))
            .values(**values)
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="分类不存在")
        return {"success": True}


@router.delete("/keyword-categories/{cat_id}")
async def delete_keyword_category(
    cat_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除关键词分类"""
    async with get_session() as session:
        result = await session.execute(
            delete(KeywordCategory)
            .where(KeywordCategory.id == cat_id, KeywordCategory.owner_user_id == str(current_user["id"]))
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="分类不存在")
        return {"success": True}
