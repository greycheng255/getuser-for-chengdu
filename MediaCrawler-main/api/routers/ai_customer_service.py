# -*- coding: utf-8 -*-
"""
AI 客服 API 路由（对接云客智能客服系统 122.51.51.177:8063）

端点：
  GET    /status                客服系统连接状态 + 登录态
  GET    /health                健康检查（直连后端 /api/health）
  POST   /login                 强制重新登录
  POST   /ask                   一站式咨询：问 AI 客服拿回复
  POST   /conversation/init     初始化/恢复会话
  GET    /conversations         会话列表
  GET    /messages              拉取会话消息列表
  POST   /messages              发送消息（客服/访客身份）
  GET    /faqs                  FAQ 列表（事件管理）
  GET    /knowledge/search      知识库向量检索
  POST   /auto-reply/preview    预览：根据评论生成 AI 回复（不发出，仅返回文本）
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.auth import get_current_user, is_admin
from ..services.ai_customer_service.yunke_client import get_yunke_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-customer-service", tags=["ai-customer-service"])


# ============ 请求模型 ============

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000, description="访客问题/评论文本")
    visitor_id: Optional[int] = Field(None, description="访客ID（不传则自动生成）")
    ai_config_id: Optional[int] = Field(None, description="指定AI配置ID")
    max_poll_seconds: float = Field(30.0, ge=5, le=120, description="AI回复轮询超时秒数")


class ConversationInitRequest(BaseModel):
    visitor_id: Optional[int] = None
    ai_config_id: Optional[int] = None
    website: str = ""
    chat_mode: str = Field("ai", description="ai / human")


class SendMessageRequest(BaseModel):
    conversation_id: int = Field(..., description="会话ID")
    content: str = Field(..., min_length=1, max_length=4000)
    sender_is_agent: bool = Field(False, description="True=客服身份；False=访客身份（触发AI回复）")
    sender_id: Optional[int] = None
    use_knowledge_base: bool = True
    use_llm: bool = True


class AutoReplyPreviewRequest(BaseModel):
    """评论自动回复预览：输入评论文本，输出 AI 建议的回复内容（不真正发出）"""
    comment_text: str = Field(..., min_length=1, max_length=4000)
    platform: str = Field("douyin", description="评论所在平台，附在 visitor 上下文")
    post_summary: str = Field("", description="视频/笔记摘要（可选，帮助 AI 理解上下文）")
    ai_config_id: Optional[int] = None
    max_poll_seconds: float = Field(30.0, ge=5, le=120)


# ============ 工具 ============

def _client():
    return get_yunke_client()


def _err(result: Dict) -> HTTPException:
    return HTTPException(status_code=502, detail=f"云客客服调用失败: {result.get('error', 'unknown')}")


# ============ 端点 ============

@router.get("/status")
async def get_status(current_user: dict = Depends(get_current_user)):
    """获取云客客服连接状态 + 登录态"""
    client = _client()
    configured = client.is_configured()
    login_status = client.get_login_status()
    return {
        "configured": configured,
        "base_url": client.base_url,
        "username": client.username,
        "logged_in": login_status["logged_in"],
        "user_id": login_status["user_id"],
    }


@router.get("/health")
async def health_check(current_user: dict = Depends(get_current_user)):
    """健康检查（直连云客后端 /api/health，无需鉴权）"""
    client = _client()
    result = await client.health()
    if not result.get("ok"):
        raise _err(result)
    return {"ok": True, "upstream": result.get("data")}


@router.post("/login")
async def force_login(current_user: dict = Depends(get_current_user)):
    """强制重新登录云客系统"""
    client = _client()
    ok = await client.login(force=True)
    if not ok:
        raise HTTPException(status_code=401, detail="云客客服登录失败，请检查 YUNKE_USERNAME/YUNKE_PASSWORD")
    return {"ok": True, **client.get_login_status()}


@router.post("/ask")
async def ask(req: AskRequest, current_user: dict = Depends(get_current_user)):
    """一站式咨询 AI 客服：发送问题 → 轮询 → 返回 AI 回复"""
    client = _client()
    result = await client.ask(
        question=req.question,
        visitor_id=req.visitor_id,
        ai_config_id=req.ai_config_id,
        max_poll_seconds=req.max_poll_seconds,
    )
    if not result.get("ok"):
        # 超时也算业务结果，返回 200 让前端按 timeout 字段处理
        if result.get("timeout"):
            return {"ok": False, "timeout": True, "error": result.get("error", "AI 客服未在超时内回复")}
        raise _err(result)
    return result


@router.post("/conversation/init")
async def conversation_init(req: ConversationInitRequest, current_user: dict = Depends(get_current_user)):
    """初始化/恢复会话"""
    client = _client()
    result = await client.conversation_init(
        visitor_id=req.visitor_id,
        ai_config_id=req.ai_config_id,
        website=req.website,
        chat_mode=req.chat_mode,
    )
    if not result.get("ok"):
        raise _err(result)
    return result


@router.get("/conversations")
async def list_conversations(
    conv_type: str = Query("visitor", description="visitor / internal"),
    status_filter: str = Query("open", alias="status", description="open / closed"),
    user_id: Optional[int] = Query(None, description="客服ID，默认用登录账号"),
    current_user: dict = Depends(get_current_user),
):
    """会话列表"""
    client = _client()
    result = await client.list_conversations(
        conv_type=conv_type, status_filter=status_filter, user_id=user_id,
    )
    if not result.get("ok"):
        raise _err(result)
    data = result.get("data", result)
    items = data if isinstance(data, list) else data.get("items", data if isinstance(data, list) else [])
    return {"ok": True, "items": items}


@router.get("/messages")
async def get_messages(
    conversation_id: int = Query(..., description="会话ID"),
    include_ai_messages: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    """拉取会话消息列表"""
    client = _client()
    result = await client.get_messages(
        conversation_id=conversation_id, include_ai_messages=include_ai_messages,
    )
    if not result.get("ok"):
        raise _err(result)
    return {"ok": True, "messages": result["messages"]}


@router.post("/messages")
async def send_message(req: SendMessageRequest, current_user: dict = Depends(get_current_user)):
    """发送消息（客服或访客身份）"""
    client = _client()
    result = await client.send_message(
        conversation_id=req.conversation_id,
        content=req.content,
        sender_is_agent=req.sender_is_agent,
        sender_id=req.sender_id,
        use_knowledge_base=req.use_knowledge_base,
        use_llm=req.use_llm,
    )
    if not result.get("ok"):
        raise _err(result)
    return {"ok": True, "message": result["message"]}


@router.get("/faqs")
async def list_faqs(
    query: str = Query("", description="关键词搜索"),
    current_user: dict = Depends(get_current_user),
):
    """FAQ/事件管理列表"""
    client = _client()
    result = await client.list_faqs(query=query)
    if not result.get("ok"):
        raise _err(result)
    return {"ok": True, "faqs": result["faqs"]}


@router.get("/knowledge/search")
async def knowledge_search(
    q: str = Query(..., alias="query", description="检索关键词"),
    top_k: int = Query(5, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
):
    """知识库向量检索"""
    client = _client()
    result = await client.search_knowledge(query=q, top_k=top_k)
    if not result.get("ok"):
        raise _err(result)
    data = result.get("data", result)
    docs = data.get("documents", []) if isinstance(data, dict) else data
    return {"ok": True, "documents": docs, "count": len(docs) if isinstance(docs, list) else 0}


@router.post("/auto-reply/preview")
async def auto_reply_preview(req: AutoReplyPreviewRequest, current_user: dict = Depends(get_current_user)):
    """评论自动回复预览：根据评论文本生成 AI 建议回复（不真正发出）

    内部拼装上下文 prompt 提交给云客 AI，返回 reply 字段供调用方决定是否发出。
    """
    client = _client()
    # 拼装上下文，让 AI 客服知道这是评论场景
    context_lines = [
        f"【场景】我方在 {req.platform} 平台发布视频/笔记，收到一条用户评论，请帮我生成一条简短、礼貌、有针对性的回复（不超过150字，不要带 emoji 之外的特殊符号）。",
    ]
    if req.post_summary:
        context_lines.append(f"【内容摘要】{req.post_summary}")
    context_lines.append(f"【用户评论】{req.comment_text}")
    context_lines.append("【要求】回复要点：1) 礼貌友好 2) 针对评论内容回应 3) 可适当引导关注/私信 4) 不要出现'我是AI'之类的话术")
    question = "\n".join(context_lines)

    result = await client.ask(
        question=question,
        ai_config_id=req.ai_config_id,
        max_poll_seconds=req.max_poll_seconds,
    )
    if not result.get("ok"):
        if result.get("timeout"):
            return {"ok": False, "timeout": True, "error": result.get("error", "AI 回复超时")}
        raise _err(result)

    return {
        "ok": True,
        "reply": result.get("answer", ""),
        "conversation_id": result.get("conversation_id"),
        "raw_answer": result.get("answer", ""),
    }
