# -*- coding: utf-8 -*-
"""
碳硅交易平台 Agent 对接模块

将 MediaCrawler 获客能力封装为 Agent，注册到碳硅交易平台。
支持：
- Agent Card 生成与管理
- Agent 注册/心跳/状态上报
- MCP Client 连接碳硅平台 MCP Server
- 任务接收/报价/执行/交付回传
"""
import asyncio
import hashlib
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from tools import utils


def _get_engine():
    """获取异步数据库引擎（公共方法，消除重复导入）"""
    from database.db_session import get_async_engine
    import config
    return get_async_engine(config.SAVE_DATA_OPTION)


# ==================== 配置 ====================

# 碳硅交易平台地址（从环境变量读取，默认本地开发）
CARBON_SILICON_PLATFORM_URL = os.environ.get("CARBON_SILICON_PLATFORM_URL", "http://localhost:3000")
CARBON_SILICON_MCP_URL = os.environ.get("CARBON_SILICON_MCP_URL", f"{CARBON_SILICON_PLATFORM_URL}/mcp")
CARBON_SILICON_API_TOKEN = os.environ.get("CARBON_SILICON_API_TOKEN", "")

# Agent 基础配置
AGENT_ID = os.environ.get("MEDIACRAWLER_AGENT_ID", "agent-mediacrawler-001")
AGENT_NAME = "MediaCrawler 获客智能体"
AGENT_VERSION = os.environ.get("MEDIACRAWLER_AGENT_VERSION", "1.0.0")

# 心跳配置
HEARTBEAT_INTERVAL = 30  # 秒
HEARTBEAT_TIMEOUT = 90   # 超过此时间无心跳 → degraded
HEARTBEAT_OFFLINE = 180  # 超过此时间无心跳 → offline

# MCP 配置
MCP_PROTOCOL_VERSION = "2024-11-05"


# ==================== 数据模型 ====================

class AgentCard(BaseModel):
    """Agent Card - 符合碳硅平台规范的标准格式"""
    schema_version: str = "1.0"
    agent_id: str = AGENT_ID
    name: str = AGENT_NAME
    description: str = "多平台社交媒体智能获客 Agent，支持小红书、抖音、快手、微博、知乎、贴吧、B站等7大平台的自动爬取、评论分析、意向识别和私信触达"
    version: str = AGENT_VERSION
    provider: Dict[str, str] = {
        "owner": "mediacrawler-team",
        "homepage": "https://github.com/NanmiCoder/MediaCrawler",
        "contact_email": os.environ.get("AGENT_CONTACT_EMAIL", "dev@mediacrawler.com")
    }
    endpoints: Dict[str, str] = {}
    auth: Dict[str, str] = {
        "type": "bearer",
        "key_id": ""
    }
    capabilities: Dict[str, Any] = {
        "domains": ["social_media", "customer_acquisition", "lead_generation", "marketing"],
        "skills": [
            "web_crawling", "comment_analysis", "intent_recognition",
            "private_messaging", "cookie_management", "anti_detection",
            "multi_platform_support", "sentiment_analysis"
        ],
        "tools": [
            "mcp:crawl_search", "mcp:crawl_comments", "mcp:analyze_leads",
            "mcp:send_private_message", "mcp:manage_cookies"
        ],
        "models": ["gpt-4.1", "claude-3.5"],
        "input_formats": ["text", "url", "keyword"],
        "output_formats": ["json", "csv", "excel"]
    }
    pricing: Dict[str, Any] = {
        "model": "quote",
        "currency": "CNY",
        "minimum_price": 50
    }
    limits: Dict[str, int] = {
        "max_concurrent_tasks": 3,
        "timeout_seconds": 3600
    }


class HeartbeatReport(BaseModel):
    """心跳上报数据"""
    agent_id: str = AGENT_ID
    status: str = "online"  # online | degraded | offline
    latency_ms: int = 0
    load_metric: float = 0.0
    metadata: Dict[str, Any] = {}


class TaskQuote(BaseModel):
    """报价提交"""
    task_id: str
    agent_id: str = AGENT_ID
    price: float
    plan: str = ""
    estimated_hours: int = 24
    idempotency_key: str = ""


class ExecutionUpdate(BaseModel):
    """执行状态更新"""
    order_id: str
    phase: str = "executing"  # pending | executing | completed | failed
    status: str = "running"
    progress: float = 0.0
    message: str = ""
    idempotency_key: str = ""


class ArtifactAttach(BaseModel):
    """交付物附件"""
    order_id: str
    artifacts: List[Dict[str, Any]] = []
    idempotency_key: str = ""


# ==================== Agent 状态管理 ====================

@dataclass
class AgentState:
    """Agent 运行时状态"""
    registered: bool = False
    agent_id: str = AGENT_ID
    approval_status: str = "draft"  # draft | pending_review | approved | rejected | disabled
    runtime_status: str = "unknown"  # online | degraded | offline | unknown
    last_heartbeat: float = 0
    current_tasks: List[str] = field(default_factory=list)
    completed_tasks: int = 0
    failed_tasks: int = 0
    api_key: str = ""
    platform_url: str = CARBON_SILICON_PLATFORM_URL


_agent_state = AgentState()
_heartbeat_task: Optional[asyncio.Task] = None


def get_agent_state() -> AgentState:
    """获取当前 Agent 状态"""
    return _agent_state


def get_agent_card(base_url: str = "") -> Dict[str, Any]:
    """生成 Agent Card JSON"""
    # 动态设置端点地址
    host = base_url or os.environ.get("AGENT_BASE_URL", "http://localhost:35092")
    card = AgentCard()
    card.endpoints = {
        "task": f"{host}/api/agent/task",
        "health": f"{host}/api/agent/health",
        "callback": f"{host}/api/agent/callback",
        "card": f"{host}/api/agent/card"
    }
    card.auth["key_id"] = f"ak_{AGENT_ID}"
    return card.model_dump()


# ==================== 碳硅平台 API 客户端 ====================

class CarbonSiliconClient:
    """碳硅交易平台 API 客户端"""

    def __init__(self, platform_url: str = "", api_token: str = ""):
        self.platform_url = platform_url or CARBON_SILICON_PLATFORM_URL
        self.api_token = api_token or CARBON_SILICON_API_TOKEN
        self.client = httpx.AsyncClient(timeout=30.0)

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def register_agent(self, agent_card: Dict[str, Any]) -> Dict[str, Any]:
        """注册 Agent 到碳硅平台"""
        url = f"{self.platform_url}/api/agents"
        try:
            resp = await self.client.post(url, json=agent_card, headers=self._headers())
            resp.raise_for_status()
            result = resp.json()
            utils.logger.info(f"[AgentClient] Agent registered successfully: {result.get('id', 'unknown')}")
            return result
        except httpx.HTTPStatusError as e:
            utils.logger.error(f"[AgentClient] Register failed: {e.response.status_code} {e.response.text}")
            raise
        except Exception as e:
            utils.logger.error(f"[AgentClient] Register error: {e}")
            raise

    async def submit_heartbeat(self, heartbeat: Dict[str, Any]) -> bool:
        """上报心跳"""
        url = f"{self.platform_url}/api/agents/{heartbeat['agent_id']}/heartbeat"
        try:
            resp = await self.client.post(url, json=heartbeat, headers=self._headers())
            resp.raise_for_status()
            return True
        except Exception as e:
            utils.logger.warning(f"[AgentClient] Heartbeat failed: {e}")
            return False

    async def submit_quote(self, quote: Dict[str, Any]) -> Dict[str, Any]:
        """提交报价"""
        url = f"{self.platform_url}/api/bids"
        try:
            resp = await self.client.post(url, json=quote, headers=self._headers())
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            utils.logger.error(f"[AgentClient] Submit quote failed: {e}")
            raise

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务详情"""
        url = f"{self.platform_url}/api/tasks/{task_id}"
        try:
            resp = await self.client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            utils.logger.error(f"[AgentClient] Get task failed: {e}")
            return None

    async def list_open_tasks(self, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """获取开放任务列表"""
        url = f"{self.platform_url}/api/tasks"
        try:
            resp = await self.client.get(
                url,
                params={"limit": limit, "offset": offset, "status": "open"},
                headers=self._headers()
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            utils.logger.error(f"[AgentClient] List tasks failed: {e}")
            return []

    async def close(self):
        await self.client.aclose()


# ==================== MCP Client ====================

class MCPClient:
    """MCP Client - 连接碳硅平台 MCP Server"""

    def __init__(self, mcp_url: str = "", token: str = ""):
        self.mcp_url = mcp_url or CARBON_SILICON_MCP_URL
        self.token = token or CARBON_SILICON_API_TOKEN
        self.client = httpx.AsyncClient(timeout=30.0)
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-MCP-Version": MCP_PROTOCOL_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any],
                        idempotency_key: str = "") -> Dict[str, Any]:
        """调用 MCP Tool"""
        request_id = self._next_id()
        params = {
            "name": tool_name,
            "arguments": arguments,
        }
        if idempotency_key:
            params["idempotency_key"] = idempotency_key

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": params
        }

        try:
            resp = await self.client.post(self.mcp_url, json=payload, headers=self._headers())
            resp.raise_for_status()
            result = resp.json()

            if "error" in result:
                utils.logger.error(f"[MCPClient] Tool call error: {result['error']}")
                return {"success": False, "error": result["error"]}

            return result.get("result", {})
        except Exception as e:
            utils.logger.error(f"[MCPClient] Tool call failed: {e}")
            return {"success": False, "error": str(e)}

    # ===== 便捷方法 =====

    async def search_agents(self, query: str = "", tags: List[str] = None,
                            filters: Dict = None, top_k: int = 10) -> Dict[str, Any]:
        """搜索 Agent"""
        args = {"query": query, "topK": top_k}
        if tags:
            args["tags"] = tags
        if filters:
            args["filters"] = filters
        return await self.call_tool("platform.agent.search", args)

    async def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """获取 Agent 详情"""
        return await self.call_tool("platform.agent.get", {"agent_id": agent_id})

    async def get_task(self, task_id: str) -> Dict[str, Any]:
        """获取任务详情"""
        return await self.call_tool("platform.task.get", {"task_id": task_id})

    async def list_open_tasks(self, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        """获取开放任务列表"""
        return await self.call_tool("platform.task.list_open", {
            "limit": limit, "offset": offset
        })

    async def create_order(self, task_id: str, agent_id: str, bid_id: str = "",
                           idempotency_key: str = "") -> Dict[str, Any]:
        """创建订单"""
        args = {"task_id": task_id, "agent_id": agent_id}
        if bid_id:
            args["bid_id"] = bid_id
        if not idempotency_key:
            idempotency_key = f"mc_{uuid.uuid4()}"
        return await self.call_tool("platform.order.create", args, idempotency_key)

    async def update_execution(self, order_id: str, phase: str, status: str,
                               progress: float = 0.0, message: str = "",
                               idempotency_key: str = "") -> Dict[str, Any]:
        """更新执行状态"""
        args = {
            "order_id": order_id,
            "phase": phase,
            "status": status,
            "progress": progress,
        }
        if message:
            args["message"] = message
        if not idempotency_key:
            idempotency_key = f"mc_{uuid.uuid4()}"
        return await self.call_tool("platform.order.update_execution", args, idempotency_key)

    async def attach_artifact(self, order_id: str, artifacts: List[Dict],
                              idempotency_key: str = "") -> Dict[str, Any]:
        """附加交付物"""
        args = {"order_id": order_id, "artifact": artifacts}
        if not idempotency_key:
            idempotency_key = f"mc_{uuid.uuid4()}"
        return await self.call_tool("platform.artifact.attach", args, idempotency_key)

    async def submit_quote(self, task_id: str, agent_id: str, price: float,
                           plan: str = "", idempotency_key: str = "") -> Dict[str, Any]:
        """提交报价"""
        args = {
            "task_id": task_id,
            "agent_id": agent_id,
            "price": price,
        }
        if plan:
            args["plan"] = plan
        if not idempotency_key:
            idempotency_key = f"mc_{uuid.uuid4()}"
        return await self.call_tool("platform.quote.submit", args, idempotency_key)

    async def report_health(self, agent_id: str, status: str,
                            latency_ms: int = 0, load: float = 0.0) -> Dict[str, Any]:
        """上报健康状态"""
        args = {
            "agent_id": agent_id,
            "status": status,
            "latency_ms": latency_ms,
            "load": load,
        }
        return await self.call_tool("platform.agent.report_health", args)

    async def close(self):
        await self.client.aclose()


# ==================== 心跳服务 ====================

async def _heartbeat_loop():
    """心跳循环 - 每30秒向碳硅平台上报一次"""
    client = CarbonSiliconClient()
    mcp_client = MCPClient()

    while True:
        try:
            state = get_agent_state()
            if not state.registered:
                utils.logger.debug("[Heartbeat] Agent not registered, skipping heartbeat")
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                continue

            # 计算负载指标
            load = len(state.current_tasks) / 3.0 * 100  # max_concurrent_tasks = 3
            load = min(load, 100.0)

            heartbeat = {
                "agent_id": state.agent_id,
                "status": "online",
                "latency_ms": 0,
                "load_metric": round(load, 2),
                "metadata": {
                    "completed_tasks": state.completed_tasks,
                    "failed_tasks": state.failed_tasks,
                    "current_tasks": len(state.current_tasks),
                    "uptime_seconds": int(time.time() - (state.last_heartbeat or time.time())),
                }
            }

            # 通过 REST API 上报
            ok = await client.submit_heartbeat(heartbeat)

            # 也通过 MCP 上报
            if ok:
                await mcp_client.report_health(
                    agent_id=state.agent_id,
                    status="online",
                    latency_ms=0,
                    load=load
                )

            state.last_heartbeat = time.time()
            utils.logger.debug(f"[Heartbeat] Reported: status=online, load={load:.1f}%")

        except Exception as e:
            utils.logger.warning(f"[Heartbeat] Error: {e}")

        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def start_heartbeat():
    """启动心跳服务"""
    global _heartbeat_task
    if _heartbeat_task and not _heartbeat_task.done():
        return
    _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    utils.logger.info("[Agent] Heartbeat service started")


async def stop_heartbeat():
    """停止心跳服务"""
    global _heartbeat_task
    if _heartbeat_task and not _heartbeat_task.done():
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass
    utils.logger.info("[Agent] Heartbeat service stopped")


# ==================== Agent 注册 ====================

async def register_to_platform(base_url: str = "") -> Dict[str, Any]:
    """注册 Agent 到碳硅交易平台"""
    state = get_agent_state()
    client = CarbonSiliconClient()

    try:
        # 生成 Agent Card
        card = get_agent_card(base_url)

        # 调用注册 API
        result = await client.register_agent(card)

        # 更新状态
        state.registered = True
        state.approval_status = "pending_review"
        state.last_heartbeat = time.time()

        # 启动心跳
        await start_heartbeat()

        utils.logger.info(f"[Agent] Registered to platform: {result.get('id', 'unknown')}")
        return result

    except Exception as e:
        utils.logger.error(f"[Agent] Registration failed: {e}")
        raise
    finally:
        await client.close()


# ==================== 任务执行桥接 ====================

async def execute_platform_task(task_id: str, order_id: str, task_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    执行碳硅平台下发的获客任务

    将平台任务转换为 MediaCrawler 内部的爬取+触达流程
    """
    mcp_client = MCPClient()
    state = get_agent_state()

    try:
        # 更新执行状态：开始
        state.current_tasks.append(task_id)
        await mcp_client.update_execution(
            order_id=order_id,
            phase="executing",
            status="running",
            progress=0.0,
            message="开始执行获客任务",
            idempotency_key=f"exec_start_{task_id}"
        )

        # 解析任务配置
        platform = task_config.get("platform", "dy")
        keywords = task_config.get("keywords", [])
        max_leads = task_config.get("max_leads", 10)
        message_template = task_config.get("message_template", "")

        utils.logger.info(f"[Agent] Executing task: platform={platform}, keywords={keywords}")

        # 更新进度：爬取阶段
        await mcp_client.update_execution(
            order_id=order_id,
            phase="executing",
            status="running",
            progress=20.0,
            message="正在爬取目标平台数据...",
            idempotency_key=f"exec_crawl_{task_id}"
        )

        # 调用 MediaCrawler 爬取服务
        from .crawler_manager import start_crawl
        crawl_result = await start_crawl(
            platform=platform,
            crawl_type="search",
            keywords=keywords,
            max_notes=max_leads * 3  # 爬取更多数据以筛选
        )

        # 更新进度：分析阶段
        await mcp_client.update_execution(
            order_id=order_id,
            phase="executing",
            status="running",
            progress=50.0,
            message="正在分析评论意向...",
            idempotency_key=f"exec_analyze_{task_id}"
        )

        # 获取高意向客户
        from database.models import CustomerLead
        from sqlalchemy import select, desc
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        engine = _get_engine()
        leads = []
        if engine:
            AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    select(CustomerLead)
                    .where(CustomerLead.platform == platform)
                    .where(CustomerLead.lead_score >= 60)
                    .order_by(desc(CustomerLead.lead_score))
                    .limit(max_leads)
                )
                leads = result.scalars().all()

        # 更新进度：触达阶段
        await mcp_client.update_execution(
            order_id=order_id,
            phase="executing",
            status="running",
            progress=80.0,
            message=f"正在发送私信，共{len(leads)}个高意向客户...",
            idempotency_key=f"exec_outreach_{task_id}"
        )

        # 执行私信触达（如果有消息模板）
        outreach_results = []
        if message_template and leads:
            from .outreach_automation import send_outreach_message
            for lead in leads[:max_leads]:
                try:
                    result = await send_outreach_message(
                        platform=platform,
                        sec_uid=lead.sec_uid or "",
                        user_id=lead.user_id or "",
                        nickname=lead.nickname or "",
                        content=message_template,
                    )
                    outreach_results.append({
                        "user_id": lead.user_id,
                        "nickname": lead.nickname,
                        "status": "success" if result else "failed"
                    })
                except Exception as e:
                    outreach_results.append({
                        "user_id": lead.user_id,
                        "nickname": lead.nickname,
                        "status": "failed",
                        "error": str(e)
                    })

        # 准备交付物
        artifacts = [{
            "type": "application/json",
            "name": f"acquisition_result_{task_id}.json",
            "description": f"获客结果：{len(leads)}个高意向客户，{len([r for r in outreach_results if r['status']=='success'])}个成功触达",
            "content": json.dumps({
                "task_id": task_id,
                "platform": platform,
                "total_leads": len(leads),
                "high_intent_leads": [
                    {
                        "user_id": l.user_id,
                        "nickname": l.nickname,
                        "lead_score": l.lead_score,
                        "intent_type": l.intent_type,
                        "content": l.content,
                    }
                    for l in leads
                ],
                "outreach_results": outreach_results,
            }, ensure_ascii=False)
        }]

        # 附加交付物
        await mcp_client.attach_artifact(
            order_id=order_id,
            artifacts=artifacts,
            idempotency_key=f"artifact_{task_id}"
        )

        # 更新执行状态：完成
        success_count = len([r for r in outreach_results if r["status"] == "success"])
        await mcp_client.update_execution(
            order_id=order_id,
            phase="completed",
            status="success",
            progress=100.0,
            message=f"任务完成：{len(leads)}个高意向客户，{success_count}个成功触达",
            idempotency_key=f"exec_done_{task_id}"
        )

        # 更新 Agent 状态
        state.completed_tasks += 1
        if task_id in state.current_tasks:
            state.current_tasks.remove(task_id)

        return {
            "success": True,
            "task_id": task_id,
            "leads_count": len(leads),
            "outreach_success": success_count,
        }

    except Exception as e:
        utils.logger.error(f"[Agent] Task execution failed: {e}")

        # 更新执行状态：失败
        try:
            await mcp_client.update_execution(
                order_id=order_id,
                phase="failed",
                status="error",
                progress=0.0,
                message=f"任务执行失败: {str(e)[:200]}",
                idempotency_key=f"exec_fail_{task_id}"
            )
        except Exception:
            pass

        state.failed_tasks += 1
        if task_id in state.current_tasks:
            state.current_tasks.remove(task_id)

        return {"success": False, "error": str(e)}

    finally:
        await mcp_client.close()


# ==================== FastAPI 路由 ====================

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/card")
async def agent_card():
    """返回 Agent Card JSON"""
    return get_agent_card()


@router.get("/health")
async def agent_health():
    """健康检查端点"""
    state = get_agent_state()
    return {
        "status": "online" if state.registered else "unregistered",
        "agent_id": state.agent_id,
        "approval_status": state.approval_status,
        "runtime_status": state.runtime_status,
        "last_heartbeat": state.last_heartbeat,
        "current_tasks": len(state.current_tasks),
        "completed_tasks": state.completed_tasks,
        "failed_tasks": state.failed_tasks,
    }


@router.post("/task")
async def receive_task(request: Request):
    """接收碳硅平台下发的任务"""
    body = await request.json()
    task_id = body.get("task_id", "")
    order_id = body.get("order_id", "")
    task_config = body.get("config", {})

    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")

    utils.logger.info(f"[Agent] Received task: task_id={task_id}, order_id={order_id}")

    # 异步执行任务
    asyncio.create_task(execute_platform_task(task_id, order_id, task_config))

    return {
        "success": True,
        "message": "Task accepted and started",
        "task_id": task_id,
        "agent_id": AGENT_ID,
    }


@router.post("/callback")
async def agent_callback(request: Request):
    """接收碳硅平台回调"""
    body = await request.json()
    event = body.get("event", "")
    data = body.get("data", {})

    utils.logger.info(f"[Agent] Callback received: event={event}")

    if event == "task.assigned":
        # 任务分配回调
        task_id = data.get("task_id", "")
        order_id = data.get("order_id", "")
        task_config = data.get("config", {})
        asyncio.create_task(execute_platform_task(task_id, order_id, task_config))
    elif event == "task.cancelled":
        # 任务取消回调
        utils.logger.info(f"[Agent] Task cancelled: {data.get('task_id', '')}")
    elif event == "order.paid":
        # 订单支付回调
        utils.logger.info(f"[Agent] Order paid: {data.get('order_id', '')}")

    return {"success": True, "event": event}


@router.post("/register")
async def register_agent(request: Request):
    """手动触发注册到碳硅平台"""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    base_url = body.get("base_url", "")

    try:
        result = await register_to_platform(base_url)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/heartbeat")
async def trigger_heartbeat():
    """手动触发心跳"""
    client = CarbonSiliconClient()
    state = get_agent_state()

    heartbeat = {
        "agent_id": state.agent_id,
        "status": "online",
        "latency_ms": 0,
        "load_metric": len(state.current_tasks) / 3.0 * 100,
        "metadata": {
            "completed_tasks": state.completed_tasks,
            "failed_tasks": state.failed_tasks,
        }
    }

    ok = await client.submit_heartbeat(heartbeat)
    await client.close()

    if ok:
        state.last_heartbeat = time.time()
        return {"success": True, "heartbeat": heartbeat}
    else:
        raise HTTPException(status_code=502, detail="Heartbeat submission failed")


@router.get("/status")
async def agent_status():
    """获取 Agent 完整状态"""
    state = get_agent_state()
    return {
        "agent_id": state.agent_id,
        "registered": state.registered,
        "approval_status": state.approval_status,
        "runtime_status": state.runtime_status,
        "last_heartbeat": state.last_heartbeat,
        "current_tasks": state.current_tasks,
        "completed_tasks": state.completed_tasks,
        "failed_tasks": state.failed_tasks,
        "platform_url": state.platform_url,
        "card": get_agent_card(),
    }


@router.post("/quote")
async def submit_quote(quote: TaskQuote):
    """提交报价"""
    mcp_client = MCPClient()
    try:
        if not quote.idempotency_key:
            quote.idempotency_key = f"mc_quote_{uuid.uuid4()}"

        result = await mcp_client.submit_quote(
            task_id=quote.task_id,
            agent_id=quote.agent_id,
            price=quote.price,
            plan=quote.plan,
            idempotency_key=quote.idempotency_key
        )
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await mcp_client.close()


@router.get("/tasks/open")
async def list_open_tasks(limit: int = 20, offset: int = 0):
    """获取碳硅平台开放任务列表"""
    mcp_client = MCPClient()
    try:
        result = await mcp_client.list_open_tasks(limit, offset)
        return {"success": True, "tasks": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await mcp_client.close()
