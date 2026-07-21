# -*- coding: utf-8 -*-
"""
X Twitter 工作台 - 评论模板管理路由

提供评论模板的 CRUD 操作:
- GET    /x-workbench/templates          列表(支持搜索/分类筛选/分页)
- POST   /x-workbench/templates          创建模板
- GET    /x-workbench/templates/{id}     获取单条
- PUT    /x-workbench/templates/{id}     更新模板
- DELETE /x-workbench/templates/{id}     删除模板(软删除)
- POST   /x-workbench/templates/{id}/use 标记为已使用(use_count+1)
- GET    /x-workbench/templates/categories 获取分类列表
- POST   /x-workbench/templates/seed     初始化内置模板(若库为空)
"""
import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, desc, update

from database.db_session import get_session
from database.models import XTwitterCommentTemplate
from api.services.auth import get_current_user
from api.utils.rate_limit import rate_limit


router = APIRouter(
    prefix="/x-workbench/templates",
    tags=["x-twitter-workbench"],
    dependencies=[
        Depends(get_current_user),
        Depends(rate_limit()),
    ],
)

logger = logging.getLogger("x_workbench_templates")


# ==================== 请求模型 ====================

class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="模板名称")
    content: str = Field(..., min_length=1, max_length=500, description="模板内容")
    category: str = Field("other", description="分类: greeting/question/insight/humor/cta/other")
    tags: str = Field("", max_length=255, description="标签,逗号分隔")


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    content: Optional[str] = Field(None, min_length=1, max_length=500)
    category: Optional[str] = None
    tags: Optional[str] = Field(None, max_length=255)
    is_active: Optional[int] = Field(None, ge=0, le=1)


# ==================== 分类定义 ====================

CATEGORIES = [
    {"value": "greeting", "label": "问候互动", "color": "blue", "desc": "打招呼、表达关注"},
    {"value": "question", "label": "提问引导", "color": "green", "desc": "用问题引发回复"},
    {"value": "insight", "label": "见解分享", "color": "purple", "desc": "分享专业见解"},
    {"value": "humor", "label": "幽默调侃", "color": "orange", "desc": "轻松幽默的内容"},
    {"value": "cta", "label": "行动号召", "color": "red", "desc": "引导关注/转发/访问"},
    {"value": "other", "label": "其他", "color": "default", "desc": "未分类"},
]


# ==================== 内置模板(首次使用时自动 seed) ====================

BUILTIN_TEMPLATES = [
    ("问候 - 关注已久", "一直在关注你的内容,{topic}这个方向太有启发了!🔥", "greeting", "关注,互动"),
    ("问候 - 内容共鸣", "看到这条推文特别有共鸣,我也是这么想的!💯", "greeting", "共鸣,认同"),
    ("提问 - 请教经验", "想请教一下,{topic}方面你有什么推荐的学习路径吗?📚", "question", "请教,学习"),
    ("提问 - 引发讨论", "你觉得{topic}未来 3 年最大的变化会是什么?🤔", "question", "讨论,趋势"),
    ("见解 - 专业分析", "从技术角度看,{topic}的核心难点在于工程化落地,不是算法本身💡", "insight", "技术,专业"),
    ("见解 - 经验总结", "做{topic}这半年,最大的体会是:工具会变,但用户需求不变🎯", "insight", "经验,总结"),
    ("幽默 - 调侃自己", "看到{topic}我第一反应是:这不就是我上周踩的坑吗😂", "humor", "调侃,踩坑"),
    ("幽默 - 轻松吐槽", "{topic}?我选择躺平(开玩笑的,马上爬起来卷)😆", "humor", "吐槽,轻松"),
    ("CTA - 邀请关注", "如果你也对{topic}感兴趣,欢迎一起交流!👉", "cta", "关注,交流"),
    ("CTA - 内容推荐", "之前整理过{topic}的资料,有需要的小伙伴可以留言📩", "cta", "推荐,资料"),
]


# ==================== 端点 ====================

@router.get("/categories")
async def list_categories():
    """获取模板分类列表(前端用于筛选和创建时的下拉选项)"""
    return {"categories": CATEGORIES}


@router.get("")
async def list_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str = Query("", description="按分类筛选"),
    keyword: str = Query("", description="搜索名称/内容/标签"),
    active_only: bool = Query(True, description="只看启用的"),
):
    """获取模板列表(分页 + 搜索 + 分类筛选)"""
    now = int(time.time())
    conditions = []
    if active_only:
        conditions.append(XTwitterCommentTemplate.is_active == 1)
    if category:
        conditions.append(XTwitterCommentTemplate.category == category)
    if keyword:
        kw = f"%{keyword}%"
        conditions.append(
            (XTwitterCommentTemplate.name.like(kw))
            | (XTwitterCommentTemplate.content.like(kw))
            | (XTwitterCommentTemplate.tags.like(kw))
        )

    async with get_session() as session:
        # 总数
        count_stmt = select(func.count(XTwitterCommentTemplate.id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await session.execute(count_stmt)).scalar() or 0

        # 列表(按使用次数倒序,常用模板在前)
        stmt = (
            select(XTwitterCommentTemplate)
            .order_by(desc(XTwitterCommentTemplate.use_count), desc(XTwitterCommentTemplate.id))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        if conditions:
            stmt = stmt.where(and_(*conditions))
        result = await session.execute(stmt)
        templates = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_template_to_dict(t) for t in templates],
    }


@router.get("/{template_id}")
async def get_template(template_id: int):
    """获取单条模板"""
    async with get_session() as session:
        t = await session.get(XTwitterCommentTemplate, template_id)
        if not t:
            raise HTTPException(404, "模板不存在")
        return _template_to_dict(t)


@router.post("")
async def create_template(req: TemplateCreateRequest, user: dict = Depends(get_current_user)):
    """创建模板"""
    if req.category and req.category not in [c["value"] for c in CATEGORIES]:
        raise HTTPException(400, f"无效的分类: {req.category}")

    now = int(time.time())
    async with get_session() as session:
        t = XTwitterCommentTemplate(
            name=req.name,
            content=req.content,
            category=req.category,
            tags=req.tags,
            use_count=0,
            last_used_ts=0,
            is_active=1,
            created_by=str(user.get("id", "")),
            add_ts=now,
            last_modify_ts=now,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        logger.info(f"用户 {user.get('id')} 创建模板: {t.name}(id={t.id})")
        return _template_to_dict(t)


@router.put("/{template_id}")
async def update_template(template_id: int, req: TemplateUpdateRequest):
    """更新模板(部分更新)"""
    now = int(time.time())
    async with get_session() as session:
        t = await session.get(XTwitterCommentTemplate, template_id)
        if not t:
            raise HTTPException(404, "模板不存在")

        updates = {k: v for k, v in req.dict(exclude_unset=True).items() if v is not None}
        if "category" in updates and updates["category"] not in [c["value"] for c in CATEGORIES]:
            raise HTTPException(400, f"无效的分类: {updates['category']}")

        for k, v in updates.items():
            setattr(t, k, v)
        t.last_modify_ts = now
        await session.commit()
        await session.refresh(t)
        return _template_to_dict(t)


@router.delete("/{template_id}")
async def delete_template(template_id: int):
    """删除模板(软删除:is_active=0)"""
    now = int(time.time())
    async with get_session() as session:
        t = await session.get(XTwitterCommentTemplate, template_id)
        if not t:
            raise HTTPException(404, "模板不存在")
        t.is_active = 0
        t.last_modify_ts = now
        await session.commit()
        logger.info(f"模板 {template_id} 已软删除")
        return {"success": True, "message": "模板已删除"}


@router.post("/{template_id}/use")
async def mark_template_used(template_id: int):
    """标记模板为已使用(use_count + 1,更新 last_used_ts)

    在用户选用模板时调用,用于统计热度。
    """
    now = int(time.time())
    async with get_session() as session:
        # 原子更新,避免并发计数丢失
        await session.execute(
            update(XTwitterCommentTemplate)
            .where(XTwitterCommentTemplate.id == template_id)
            .values(
                use_count=XTwitterCommentTemplate.use_count + 1,
                last_used_ts=now,
            )
        )
        await session.commit()
    return {"success": True, "message": "已记录使用", "use_count_increment": 1}


@router.post("/seed")
async def seed_builtin_templates(user: dict = Depends(get_current_user)):
    """初始化内置模板(仅当库为空时生效,避免重复)

    首次使用时调用,自动创建 10 条内置模板。
    """
    now = int(time.time())
    async with get_session() as session:
        # 检查是否已有模板
        count = (await session.execute(
            select(func.count(XTwitterCommentTemplate.id))
        )).scalar() or 0

        if count > 0:
            return {"success": True, "message": f"已有 {count} 条模板,跳过 seed", "created": 0}

        # 批量插入内置模板
        created = 0
        for name, content, category, tags in BUILTIN_TEMPLATES:
            t = XTwitterCommentTemplate(
                name=name,
                content=content,
                category=category,
                tags=tags,
                use_count=0,
                last_used_ts=0,
                is_active=1,
                created_by=str(user.get("id", "")),
                add_ts=now,
                last_modify_ts=now,
            )
            session.add(t)
            created += 1
        await session.commit()
        logger.info(f"用户 {user.get('id')} 初始化 {created} 条内置模板")
        return {"success": True, "message": f"已创建 {created} 条内置模板", "created": created}


# ==================== 工具函数 ====================

def _template_to_dict(t: XTwitterCommentTemplate) -> dict:
    """模板对象转 dict(用于 API 响应)"""
    return {
        "id": t.id,
        "name": t.name,
        "content": t.content,
        "category": t.category,
        "category_label": _get_category_label(t.category),
        "tags": t.tags or "",
        "tags_list": [tag.strip() for tag in (t.tags or "").split(",") if tag.strip()],
        "use_count": t.use_count or 0,
        "last_used_ts": t.last_used_ts or 0,
        "is_active": t.is_active,
        "created_by": t.created_by or "",
        "add_ts": t.add_ts or 0,
        "last_modify_ts": t.last_modify_ts or 0,
    }


def _get_category_label(category: str) -> str:
    """获取分类的中文标签"""
    for c in CATEGORIES:
        if c["value"] == category:
            return c["label"]
    return category
