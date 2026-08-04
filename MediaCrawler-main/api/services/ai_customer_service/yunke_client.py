# -*- coding: utf-8 -*-
"""
云客智能客服系统 HTTP 客户端

对接服务：http://122.51.51.177:8063/api/*
后端实际监听 18080，8063 为前端入口；docs 提示直接调 18080/api/* 更稳。
本客户端默认使用 8063（前端入口），可通过环境变量 YUNKE_BASE_URL 覆盖。

认证机制（无 JWT/Session）：
- POST /api/login 拿 user_id + ws_token
- 后续请求统一带请求头 X-User-Id: <user_id>

核心对接流程：
1. login() → 缓存 user_id + ws_token
2. conversation_init() → 创建/恢复会话拿 conversation_id
3. send_message() → 发送消息（访客身份，触发 AI 回复）
4. get_messages() → 拉取消息列表（含 AI 回复）

集成场景：
- 评论监控自动回复时，调用本客户端让 yunke AI 生成回复内容
- 客户分配调度时，将客户咨询转给 yunke AI 客服处理
"""
import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class YunkeClient:
    """云客智能客服 HTTP 客户端"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        # 默认 8063（前端入口），可通过 .env YUNKE_BASE_URL 覆盖为 18080
        self.base_url = (
            base_url
            or os.getenv("YUNKE_BASE_URL", "http://122.51.51.177:8063").rstrip("/")
        )
        self.username = username or os.getenv("YUNKE_USERNAME", "admin")
        self.password = password or os.getenv("YUNKE_PASSWORD", "admin123456")

        # 登录态缓存
        self._user_id: Optional[int] = None
        self._ws_token: str = ""
        self._login_exp: float = 0  # 登录过期时间（秒级时间戳）
        self._visitor_seq: int = int(time.time()) % 100000  # 访客 ID 自增序列

    # ==================== 内部 HTTP ====================

    async def _request(
        self, method: str, path: str, *,
        json_body: Optional[Dict] = None,
        params: Optional[Dict] = None,
        require_auth: bool = True,
        timeout: float = 15.0,
    ) -> Dict:
        """异步 HTTP 请求（httpx 优先，兜底 requests+to_thread）"""
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if require_auth:
            if not self._ensure_logged_in():
                # 登录失败也尝试发请求（部分接口无需鉴权）
                pass
            if self._user_id:
                headers["X-User-Id"] = str(self._user_id)

        try:
            import httpx
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(
                    method, url, json=json_body, params=params, headers=headers,
                )
                # yunke 失败返回 {"error": "..."}
                if resp.status_code >= 400:
                    try:
                        err_body = resp.json()
                    except Exception:
                        err_body = {"raw": resp.text}
                    return {
                        "ok": False,
                        "status_code": resp.status_code,
                        "error": err_body.get("error") or err_body,
                    }
                return {"ok": True, "status_code": resp.status_code, "data": resp.json()}
        except ImportError:
            return await self._request_via_requests(
                method, url, json_body, params, headers, timeout
            )
        except Exception as e:
            logger.warning(f"[YunkeClient] {method} {path} 失败: {e}")
            return {"ok": False, "error": f"http_error: {e}"}

    async def _request_via_requests(
        self, method: str, url: str, json_body, params, headers, timeout,
    ) -> Dict:
        import requests

        def _do():
            try:
                r = requests.request(
                    method, url, json=json_body, params=params,
                    headers=headers, timeout=timeout,
                )
                if r.status_code >= 400:
                    try:
                        return {"ok": False, "status_code": r.status_code, "error": r.json().get("error")}
                    except Exception:
                        return {"ok": False, "status_code": r.status_code, "error": r.text}
                return {"ok": True, "status_code": r.status_code, "data": r.json()}
            except Exception as e:
                return {"ok": False, "error": f"http_error: {e}"}

        return await asyncio.to_thread(_do)

    # ==================== 登录 ====================

    def _ensure_logged_in(self) -> bool:
        """检查登录态，过期则下次请求前会重新登录"""
        if self._user_id and time.time() < self._login_exp:
            return True
        return False  # 调用方应在请求前 await login()

    async def login(self, force: bool = False) -> bool:
        """登录云客系统，缓存 user_id + ws_token（24h 有效）"""
        if not force and self._ensure_logged_in():
            return True
        result = await self._request(
            "POST", "/api/login",
            json_body={"username": self.username, "password": self.password},
            require_auth=False,
        )
        if not result.get("ok"):
            logger.error(f"[YunkeClient] 登录失败: {result.get('error')}")
            return False
        data = result["data"]
        self._user_id = int(data.get("user_id", 0))
        self._ws_token = data.get("ws_token", "")
        # ws_token 24h 有效，缓存 23h
        self._login_exp = time.time() + 23 * 3600
        logger.info(
            f"[YunkeClient] 登录成功 user_id={self._user_id} "
            f"role={data.get('role')}"
        )
        return self._user_id > 0

    async def health(self) -> Dict:
        """健康检查（无需鉴权）"""
        return await self._request("GET", "/api/health", require_auth=False)

    # ==================== 会话管理 ====================

    async def conversation_init(
        self, visitor_id: Optional[int] = None,
        ai_config_id: Optional[int] = None,
        website: str = "", chat_mode: str = "ai",
    ) -> Dict:
        """访客初始化/恢复会话，返回 conversation_id"""
        await self.login()
        if visitor_id is None:
            self._visitor_seq += 1
            visitor_id = self._visitor_seq
        body: Dict[str, Any] = {
            "visitor_id": visitor_id,
            "website": website or "https://mediacrawler.local/comment-monitor",
            "chat_mode": chat_mode,
        }
        if ai_config_id is not None:
            body["ai_config_id"] = ai_config_id
        result = await self._request("POST", "/api/conversation/init", json_body=body)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error")}
        return {
            "ok": True,
            "conversation_id": result["data"].get("conversation_id"),
            "status": result["data"].get("status"),
            "visitor_id": visitor_id,
        }

    async def list_conversations(
        self, *, conv_type: str = "visitor", status_filter: str = "open",
        user_id: Optional[int] = None,
    ) -> Dict:
        """会话列表"""
        await self.login()
        params = {
            "type": conv_type, "status": status_filter,
            "user_id": user_id or self._user_id or 0,
        }
        result = await self._request("GET", "/api/conversations", params=params)
        return result if result.get("ok") else {"ok": False, "error": result.get("error"), "items": []}

    # ==================== 消息收发 ====================

    async def send_message(
        self, conversation_id: int, content: str,
        sender_is_agent: bool = False, sender_id: Optional[int] = None,
        use_knowledge_base: bool = True, use_llm: bool = True,
    ) -> Dict:
        """发送消息

        - 客服发送：sender_is_agent=True, sender_id=客服ID（后端覆写为 X-User-Id）
        - 访客发送：sender_is_agent=False, sender_id=0（触发 AI 自动回复）
        """
        await self.login()
        body = {
            "conversation_id": conversation_id,
            "content": content,
            "sender_is_agent": sender_is_agent,
            "sender_id": sender_id if sender_id is not None else (self._user_id or 0),
            "use_knowledge_base": use_knowledge_base,
            "use_llm": use_llm,
            "use_web_search": False,
            "need_web_search": False,
        }
        result = await self._request("POST", "/api/messages", json_body=body)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error")}
        return {"ok": True, "message": result["data"]}

    async def get_messages(
        self, conversation_id: int, include_ai_messages: bool = True,
    ) -> Dict:
        """拉取消息列表（含 AI 回复）"""
        await self.login()
        params = {
            "conversation_id": conversation_id,
            "include_ai_messages": "true" if include_ai_messages else "false",
        }
        result = await self._request("GET", "/api/messages", params=params)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error"), "messages": []}
        data = result["data"]
        # data 可能是数组或 {messages: [...]}
        if isinstance(data, list):
            messages = data
        else:
            messages = data.get("messages", data) if isinstance(data, dict) else []
        return {"ok": True, "messages": messages}

    async def mark_read(self, conversation_id: int, reader_is_agent: bool = False) -> Dict:
        """标记已读"""
        await self.login()
        body = {"conversation_id": conversation_id, "reader_is_agent": reader_is_agent}
        result = await self._request("PUT", "/api/messages/read", json_body=body)
        return result if result.get("ok") else {"ok": False, "error": result.get("error")}

    # ==================== 高层封装：咨询 AI 客服 ====================

    async def ask(
        self, question: str, *,
        visitor_id: Optional[int] = None,
        ai_config_id: Optional[int] = None,
        timeout_seconds: float = 30.0,
        max_poll_seconds: float = 30.0,
    ) -> Dict:
        """
        一站式咨询 AI 客服：
        1. 初始化会话
        2. 访客身份发送问题（触发 AI 回复）
        3. 轮询消息列表，提取 AI 最新回复
        4. 返回 {ok, answer, conversation_id}

        适用于评论自动回复场景：把评论作为 question，拿到 AI 回复后发出。
        """
        # 1. 初始化会话
        init = await self.conversation_init(
            visitor_id=visitor_id, ai_config_id=ai_config_id,
        )
        if not init.get("ok"):
            return init
        conversation_id = init["conversation_id"]
        if not conversation_id:
            return {"ok": False, "error": "未拿到 conversation_id"}

        # 2. 发送问题（访客身份）
        sent = await self.send_message(
            conversation_id=conversation_id,
            content=question,
            sender_is_agent=False,
            sender_id=0,
        )
        if not sent.get("ok"):
            return sent

        # 3. 轮询消息列表，等 AI 回复
        sent_msg_id = sent.get("message", {}).get("id", 0)
        deadline = time.time() + max_poll_seconds
        last_answer = ""
        while time.time() < deadline:
            await asyncio.sleep(1.5)
            msgs_result = await self.get_messages(conversation_id)
            if not msgs_result.get("ok"):
                continue
            messages = msgs_result["messages"]
            # 找 sent_msg_id 之后的客服/AI 消息
            for m in messages:
                if not isinstance(m, dict):
                    continue
                # AI 回复：sender_is_agent=True 或 message_type=system_message
                if (m.get("sender_is_agent") is True
                        or m.get("message_type") == "system_message"):
                    mid = m.get("id", 0)
                    if mid and sent_msg_id and mid <= sent_msg_id:
                        continue
                    content = m.get("content", "").strip()
                    if content:
                        last_answer = content
                        return {
                            "ok": True,
                            "answer": last_answer,
                            "conversation_id": conversation_id,
                            "message_id": mid,
                        }

        # 超时兜底：返回最新 AI 回复（若有）
        if last_answer:
            return {
                "ok": True, "answer": last_answer,
                "conversation_id": conversation_id,
                "timeout": True,
            }
        return {
            "ok": False, "error": "AI 客服未在超时内回复",
            "conversation_id": conversation_id,
            "timeout": True,
        }

    # ==================== 知识库 / FAQ（可选对接） ====================

    async def search_knowledge(self, query: str, top_k: int = 5) -> Dict:
        """向量检索知识库"""
        await self.login()
        params = {"query": query, "top_k": top_k}
        result = await self._request("GET", "/api/documents/search", params=params)
        return result if result.get("ok") else {"ok": False, "error": result.get("error"), "documents": []}

    async def list_faqs(self, query: str = "") -> Dict:
        """FAQ 列表"""
        await self.login()
        params = {"query": query} if query else {}
        result = await self._request("GET", "/api/faqs", params=params)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error"), "faqs": []}
        data = result["data"]
        return {"ok": True, "faqs": data.get("faqs", []) if isinstance(data, dict) else data}

    # ==================== 状态查询 ====================

    def is_configured(self) -> bool:
        """检查是否配置（base_url 非空）"""
        return bool(self.base_url) and bool(self.username)

    def get_login_status(self) -> Dict:
        return {
            "logged_in": self._user_id is not None and time.time() < self._login_exp,
            "user_id": self._user_id,
            "ws_token_present": bool(self._ws_token),
            "login_exp": self._login_exp,
            "base_url": self.base_url,
        }


# ============ 单例 ============
_yunke_client: Optional[YunkeClient] = None


def get_yunke_client() -> YunkeClient:
    global _yunke_client
    if _yunke_client is None:
        _yunke_client = YunkeClient()
    return _yunke_client
