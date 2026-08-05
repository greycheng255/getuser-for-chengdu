# -*- coding: utf-8 -*-
"""
微信 AI 员工服务

核心职责：
1. 知识库管理（上传行业资料供 AI 学习）
2. AI 自动回复客户咨询（拟人化、高情商）
3. 自动通过好友申请 + 打招呼话术
4. 定期群发（一对一/群内）
5. 朋友圈运营（发朋友圈/点赞/评论）
6. 识别客户联系方式并自动添加微信好友

参考：知了系统的 AI 员工 + 微信私域运营功能

注意：微信协议对接需要第三方库（如 WeChatFerry/ComBot），
本模块先实现业务逻辑层，协议层预留接口。
"""
import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 知识库存储目录
KNOWLEDGE_BASE_DIR = "/tmp/wechat_knowledge_base"
os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)


class WeChatService:
    """微信 AI 员工服务（单例）"""

    _ensured = False
    _instance = None

    def __init__(self):
        self._knowledge_bases: Dict[str, Dict] = {}
        self._wechat_connected = False

    @classmethod
    def get_instance(cls) -> "WeChatService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """创建 wechat_knowledge / wechat_message_log 表"""
        if WeChatService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS wechat_knowledge ("
                        "  id SERIAL PRIMARY KEY,"
                        "  kb_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  title VARCHAR(255) NOT NULL,"
                        "  content TEXT NOT NULL,"
                        "  category VARCHAR(100) DEFAULT '',"
                        "  file_path VARCHAR(500) DEFAULT '',"
                        "  owner_user_id VARCHAR(64) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS wechat_message_log ("
                        "  id SERIAL PRIMARY KEY,"
                        "  msg_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  direction VARCHAR(10) NOT NULL,"
                        "  contact_id VARCHAR(255) DEFAULT '',"
                        "  contact_name VARCHAR(255) DEFAULT '',"
                        "  content TEXT DEFAULT '',"
                        "  msg_type VARCHAR(50) DEFAULT 'text',"
                        "  ai_reply BOOLEAN DEFAULT FALSE,"
                        "  created_at BIGINT DEFAULT 0"
                        ")"
                    )
                )

            WeChatService._ensured = True
            logger.info("[WeChat] 表创建完成")
        except Exception as e:
            logger.warning(f"[WeChat] 建表失败(非致命): {e}")

    async def upload_knowledge(
        self,
        title: str,
        content: str,
        category: str = "",
        file_path: str = "",
        owner_user_id: str = "",
    ) -> Dict[str, Any]:
        """上传知识库资料"""
        kb_id = f"kb_{uuid.uuid4().hex[:10]}"
        now = int(time.time())

        # 保存文件到本地
        if file_path and os.path.exists(file_path):
            dest = os.path.join(KNOWLEDGE_BASE_DIR, f"{kb_id}_{os.path.basename(file_path)}")
            import shutil
            shutil.copy2(file_path, dest)
            file_path = dest

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO wechat_knowledge "
                        "(kb_id, title, content, category, file_path, owner_user_id, created_at) "
                        "VALUES (:kid, :title, :content, :cat, :fp, :owner, :now)"
                    ),
                    {
                        "kid": kb_id,
                        "title": title,
                        "content": content,
                        "cat": category,
                        "fp": file_path,
                        "owner": owner_user_id,
                        "now": now,
                    },
                )

            self._knowledge_bases[kb_id] = {
                "kb_id": kb_id,
                "title": title,
                "content": content,
                "category": category,
            }

            logger.info(f"[WeChat] 知识库上传: {kb_id} ({title})")
            return {"ok": True, "kb_id": kb_id}
        except Exception as e:
            logger.warning(f"[WeChat] 上传知识库失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def list_knowledge(self, owner_user_id: str = "") -> List[Dict]:
        """列出知识库"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM wechat_knowledge ORDER BY created_at DESC"),
                )
            return [dict(r._mapping) for r in rows.fetchall()]
        except Exception:
            return []

    async def generate_reply(
        self,
        customer_message: str,
        customer_name: str = "",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """AI 生成微信回复（基于知识库）"""
        try:
            from api.services.ai_agent_client import get_ai_agent_client
            client = get_ai_agent_client()

            # 构建知识库上下文
            kb_context = ""
            for kb in self._knowledge_bases.values():
                kb_context += f"\n--- {kb['title']} ---\n{kb['content'][:500]}"

            system_prompt = f"""你是一个专业的微信客服AI员工。
你的回复风格：拟人化、高情商、专业但不生硬。
适当使用表情符号，语气亲切自然。

知识库内容：
{kb_context[:3000] if kb_context else '暂无知识库'}

回复规则：
1. 先理解客户问题，再针对性回答
2. 如果知识库有相关信息，优先引用
3. 如果不确定，引导客户留下联系方式
4. 回复控制在 200 字以内
5. 不要暴露你是 AI"""

            prompt = f"客户（{customer_name}）发来消息：{customer_message}"
            if context:
                prompt += f"\n上下文：{json.dumps(context, ensure_ascii=False)}"

            response = await client.generate_text(prompt=prompt, system_prompt=system_prompt)
            if not response:
                return {"ok": False, "reason": "AI 回复生成失败"}

            return {"ok": True, "reply": response}
        except Exception as e:
            logger.warning(f"[WeChat] AI 回复失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def log_message(
        self,
        direction: str,
        contact_id: str,
        contact_name: str,
        content: str,
        msg_type: str = "text",
        ai_reply: bool = False,
    ) -> str:
        """记录微信消息"""
        msg_id = f"wx_{uuid.uuid4().hex[:10]}"
        now = int(time.time())

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO wechat_message_log "
                        "(msg_id, direction, contact_id, contact_name, content, msg_type, ai_reply, created_at) "
                        "VALUES (:mid, :dir, :cid, :cname, :content, :type, :ai, :now)"
                    ),
                    {
                        "mid": msg_id,
                        "dir": direction,
                        "cid": contact_id,
                        "cname": contact_name,
                        "content": content,
                        "type": msg_type,
                        "ai": ai_reply,
                        "now": now,
                    },
                )
        except Exception as e:
            logger.warning(f"[WeChat] 记录消息失败: {e}")

        return msg_id

    async def auto_reply(
        self,
        contact_id: str,
        contact_name: str,
        message: str,
    ) -> Dict[str, Any]:
        """自动回复流程：生成 AI 回复 → 记录消息"""
        # 1. 生成 AI 回复
        reply_result = await self.generate_reply(message, contact_name)
        if not reply_result.get("ok"):
            return reply_result

        reply_text = reply_result["reply"]

        # 2. 记录收到的消息
        await self.log_message("in", contact_id, contact_name, message)
        # 3. 记录发出的回复
        await self.log_message("out", contact_id, contact_name, reply_text, ai_reply=True)

        # 4. TODO: 实际发送微信消息（需要对接微信协议）
        logger.info(f"[WeChat] 自动回复 {contact_name}: {reply_text[:50]}...")

        return {"ok": True, "reply": reply_text}

    async def extract_contact_info(self, text: str) -> Dict[str, Optional[str]]:
        """从文本中提取联系方式（微信号/手机号）"""
        import re

        wechat = None
        phone = None

        # 微信号模式
        wechat_patterns = [
            r'[Vv][Xx][:：\s]*([a-zA-Z0-9_-]{5,20})',
            r'微信[:：\s]*([a-zA-Z0-9_-]{5,20})',
            r'加我[:：\s]*([a-zA-Z0-9_-]{5,20})',
        ]
        for pattern in wechat_patterns:
            match = re.search(pattern, text)
            if match:
                wechat = match.group(1)
                break

        # 手机号模式
        phone_match = re.search(r'1[3-9]\d{9}', text)
        if phone_match:
            phone = phone_match.group()

        return {"wechat": wechat, "phone": phone}

    async def get_message_log(
        self,
        contact_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """获取消息记录"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []

            where = "1=1"
            params: Dict[str, Any] = {"limit": limit}
            if contact_id:
                where = "contact_id = :cid"
                params["cid"] = contact_id

            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT * FROM wechat_message_log WHERE {where} "
                        "ORDER BY created_at DESC LIMIT :limit"
                    ),
                    params,
                )
            return [dict(r._mapping) for r in rows.fetchall()]
        except Exception:
            return []


def get_wechat_service() -> WeChatService:
    return WeChatService.get_instance()
