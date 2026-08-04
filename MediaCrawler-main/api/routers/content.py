# -*- coding: utf-8 -*-
"""
内容模板 API 路由（P0：内容模板服务）

提供：
1. GET /api/content/templates - 获取所有模板列表
2. GET /api/content/templates/{template_id} - 获取指定模板详情
3. GET /api/content/templates/type/{type} - 按类型筛选模板
4. GET /api/content/templates/industry/{industry} - 按行业筛选模板
5. POST /api/content/templates/{template_id}/prompt - 根据模板生成 AI 提示词
6. POST /api/content/templates/custom - 创建自定义模板
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.content import get_content_template_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["content"])


class GeneratePromptRequest(BaseModel):
    """生成提示词请求"""
    variables: dict = Field(default_factory=dict, description="模板变量")


class CreateTemplateRequest(BaseModel):
    """创建自定义模板请求"""
    id: str
    name: str
    type: str
    description: str
    structure: list
    prompt_template: str
    example: str = ""
    tags: list = []
    industry: list = []
    tone: str = "professional"
    min_length: int = 1000
    max_length: int = 3000
    seo_keywords: list = []
    schema_type: str = "Article"


@router.get("/templates")
async def list_templates():
    """获取所有模板列表"""
    svc = get_content_template_service()
    return {"templates": svc.get_all_templates()}


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """获取指定模板详情"""
    svc = get_content_template_service()
    t = svc.get_template(template_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"模板 {template_id} 不存在")
    return svc._template_to_dict(t)


@router.get("/templates/type/{template_type}")
async def get_templates_by_type(template_type: str):
    """按类型筛选模板"""
    svc = get_content_template_service()
    return {"templates": svc.get_templates_by_type(template_type)}


@router.get("/templates/industry/{industry}")
async def get_templates_by_industry(industry: str):
    """按行业筛选模板"""
    svc = get_content_template_service()
    return {"templates": svc.get_templates_by_industry(industry)}


@router.post("/templates/{template_id}/prompt")
async def generate_prompt(template_id: str, req: GeneratePromptRequest):
    """根据模板和变量生成 AI 提示词"""
    svc = get_content_template_service()
    try:
        result = svc.generate_prompt(template_id, req.variables)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/templates/custom")
async def create_custom_template(req: CreateTemplateRequest):
    """创建自定义模板（仅内存，重启后失效）"""
    svc = get_content_template_service()
    try:
        return svc.create_custom_template(req.dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
