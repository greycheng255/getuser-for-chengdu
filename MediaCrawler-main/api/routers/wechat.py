# -*- coding: utf-8 -*-
"""
微信 AI 员工 API 路由

端点：
  POST   /knowledge           上传知识库
  GET    /knowledge           列出知识库
  POST   /reply               AI 生成回复
  POST   /auto-reply          自动回复（生成+记录）
  POST   /extract-contact     从文本提取联系方式
  GET    /messages            消息记录
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user
from ..services.wechat.wechat_service import get_wechat_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wechat", tags=["wechat"])


class UploadKnowledgeRequest(BaseModel):
    title: str = Field(..., description="资料标题")
    content: str = Field(..., description="资料内容")
    category: str = Field("", description="分类")
    file_path: str = Field("", description="文件路径（可选）")


class GenerateReplyRequest(BaseModel):
    customer_message: str = Field(..., description="客户消息")
    customer_name: str = Field("", description="客户名称")
    context: Optional[dict] = Field(None, description="上下文信息")


class AutoReplyRequest(BaseModel):
    contact_id: str = Field(..., description="联系人ID")
    contact_name: str = Field(..., description="联系人名称")
    message: str = Field(..., description="收到的消息")


class ExtractContactRequest(BaseModel):
    text: str = Field(..., description="待提取的文本")


@router.post("/knowledge")
async def upload_knowledge(
    req: UploadKnowledgeRequest,
    current_user: dict = Depends(get_current_user),
):
    """上传知识库资料"""
    svc = get_wechat_service()
    result = await svc.upload_knowledge(
        title=req.title,
        content=req.content,
        category=req.category,
        file_path=req.file_path,
        owner_user_id=str(current_user["id"]),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "上传失败"))
    return result


@router.get("/knowledge")
async def list_knowledge(current_user: dict = Depends(get_current_user)):
    """列出知识库"""
    svc = get_wechat_service()
    items = await svc.list_knowledge(owner_user_id=str(current_user["id"]))
    return {"items": items, "total": len(items)}


@router.post("/reply")
async def generate_reply(
    req: GenerateReplyRequest,
    current_user: dict = Depends(get_current_user),
):
    """AI 生成微信回复"""
    svc = get_wechat_service()
    result = await svc.generate_reply(
        customer_message=req.customer_message,
        customer_name=req.customer_name,
        context=req.context,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "生成失败"))
    return result


@router.post("/auto-reply")
async def auto_reply(
    req: AutoReplyRequest,
    current_user: dict = Depends(get_current_user),
):
    """自动回复（生成 + 记录）"""
    svc = get_wechat_service()
    result = await svc.auto_reply(
        contact_id=req.contact_id,
        contact_name=req.contact_name,
        message=req.message,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "回复失败"))
    return result


@router.post("/extract-contact")
async def extract_contact(
    req: ExtractContactRequest,
    current_user: dict = Depends(get_current_user),
):
    """从文本中提取联系方式"""
    svc = get_wechat_service()
    result = await svc.extract_contact_info(req.text)
    return result


@router.get("/messages")
async def get_messages(
    contact_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """获取消息记录"""
    svc = get_wechat_service()
    messages = await svc.get_message_log(contact_id=contact_id, limit=limit)
    return {"messages": messages, "total": len(messages)}
