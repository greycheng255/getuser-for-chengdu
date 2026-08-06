"""Reusable owner-scoped lead targeting profiles."""
import json
import time
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc

from database.db_session import get_session
from database.user_models import BusinessProfileRuleModel
from .auth import get_current_user

router = APIRouter(prefix="/business-profiles", tags=["business-profiles"])


class ProfilePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    business_intent: str = ""
    business_keywords: List[str] = []
    intent_keywords: List[str] = []
    exclude_keywords: List[str] = []
    enabled: bool = True


def _terms(values: List[str]) -> List[str]:
    return list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))


def _serialize(row: BusinessProfileRuleModel) -> dict:
    def decode(value: str) -> list:
        try:
            return json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
    business, intent, exclude = decode(row.business_keywords), decode(row.intent_keywords), decode(row.exclude_keywords)
    return {
        "id": row.id, "name": row.name, "business_intent": row.business_intent or "",
        "business_keywords": business, "intent_keywords": intent, "exclude_keywords": exclude,
        "enabled": bool(row.enabled), "created_ts": row.created_ts, "updated_ts": row.updated_ts,
        "preview": {
            "discard_when": f"命中任一排除词：{', '.join(exclude) or '无'}",
            "lead_when": f"同时命中业务词（{', '.join(business) or '任务搜索关键词'}）和意向词（{', '.join(intent) or '未设置'}）",
            "fallback": "未设置意向词时，回退到咨询意向模式",
        },
    }


@router.get("")
async def list_profiles(current_user: dict = Depends(get_current_user)):
    async with get_session() as session:
        result = await session.execute(
            select(BusinessProfileRuleModel).where(
                BusinessProfileRuleModel.owner_user_id == str(current_user["id"])
            ).order_by(desc(BusinessProfileRuleModel.updated_ts))
        )
        return {"items": [_serialize(row) for row in result.scalars().all()]}


@router.post("")
async def create_profile(payload: ProfilePayload, current_user: dict = Depends(get_current_user)):
    now = int(time.time() * 1000)
    row = BusinessProfileRuleModel(
        id=f"profile_{uuid.uuid4().hex[:12]}", owner_user_id=str(current_user["id"]),
        name=payload.name.strip(), business_intent=payload.business_intent.strip(),
        business_keywords=json.dumps(_terms(payload.business_keywords), ensure_ascii=False),
        intent_keywords=json.dumps(_terms(payload.intent_keywords), ensure_ascii=False),
        exclude_keywords=json.dumps(_terms(payload.exclude_keywords), ensure_ascii=False),
        enabled=1 if payload.enabled else 0, created_ts=now, updated_ts=now,
    )
    async with get_session() as session:
        session.add(row)
    return {"success": True, "item": _serialize(row)}


@router.put("/{profile_id}")
async def update_profile(profile_id: str, payload: ProfilePayload, current_user: dict = Depends(get_current_user)):
    async with get_session() as session:
        result = await session.execute(select(BusinessProfileRuleModel).where(
            BusinessProfileRuleModel.id == profile_id,
            BusinessProfileRuleModel.owner_user_id == str(current_user["id"]),
        ))
        row = result.scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="业务画像不存在")
        row.name, row.business_intent = payload.name.strip(), payload.business_intent.strip()
        row.business_keywords = json.dumps(_terms(payload.business_keywords), ensure_ascii=False)
        row.intent_keywords = json.dumps(_terms(payload.intent_keywords), ensure_ascii=False)
        row.exclude_keywords = json.dumps(_terms(payload.exclude_keywords), ensure_ascii=False)
        row.enabled, row.updated_ts = 1 if payload.enabled else 0, int(time.time() * 1000)
        await session.flush()
        return {"success": True, "item": _serialize(row)}


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str, current_user: dict = Depends(get_current_user)):
    async with get_session() as session:
        result = await session.execute(select(BusinessProfileRuleModel).where(
            BusinessProfileRuleModel.id == profile_id,
            BusinessProfileRuleModel.owner_user_id == str(current_user["id"]),
        ))
        row = result.scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="业务画像不存在")
        await session.delete(row)
    return {"success": True}
