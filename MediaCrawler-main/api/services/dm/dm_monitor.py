# -*- coding: utf-8 -*-
"""
私信监控服务

对应 PRD 5.4 私信自动回复 - 私信监控：
1. 多平台私信列表定时检查（X/抖音/小红书）
2. 新私信入库 + 触发 AI 回复
3. watchdog 自动重启

设计：异步 + PostgreSQL，与 InteractionMonitor 风格一致。
实际的私信抓取通过各平台 Interactor 的 fetch_direct_messages 钩子（可选实现）。
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .dm_models import DirectMessage, MessageIntent, ConversationState
from .dm_replier import get_dm_replier

logger = logging.getLogger(__name__)

DEFAULT_CHECK_INTERVAL = 600  # 10 分钟轮询


class DMMonitorService:
    """私信监控服务"""

    def __init__(self, check_interval: int = DEFAULT_CHECK_INTERVAL):
        self.check_interval = check_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._monitored_platforms: List[str] = []

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self):
        if DMMonitorService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS direct_messages ("
                        "  id SERIAL PRIMARY KEY,"
                        "  platform VARCHAR(32),"
                        "  conversation_id VARCHAR(128),"
                        "  sender_id VARCHAR(128),"
                        "  sender_name VARCHAR(128),"
                        "  message_text TEXT,"
                        "  intent VARCHAR(32),"
                        "  confidence FLOAT,"
                        "  state VARCHAR(16) DEFAULT 'new',"
                        "  reply_text TEXT,"
                        "  is_replied BOOLEAN DEFAULT FALSE,"
                        "  needs_human BOOLEAN DEFAULT FALSE,"
                        "  received_at TIMESTAMP DEFAULT NOW(),"
                        "  replied_at TIMESTAMP"
                        ")"
                    )
                )
            DMMonitorService._ensured = True
        except Exception as e:
            logger.warning(f"[DM] 建表失败: {e}")

    # ==================== 监控管理 ====================

    async def add_platform(self, platform: str):
        if platform not in self._monitored_platforms:
            self._monitored_platforms.append(platform)
        return True

    async def remove_platform(self, platform: str):
        if platform in self._monitored_platforms:
            self._monitored_platforms.remove(platform)
        return True

    def list_platforms(self) -> List[str]:
        return list(self._monitored_platforms)

    # ==================== 启停 ====================

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_with_watchdog())
        logger.info("[DM] 私信监控已启动")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def _run_with_watchdog(self):
        while self._running:
            try:
                await self._monitor_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"[DM] 监控异常，10s 后重启: {e}")
                await asyncio.sleep(10)

    async def _monitor_loop(self):
        while self._running:
            try:
                for platform in self._monitored_platforms:
                    await self._check_platform_dms(platform)
            except Exception as e:
                logger.error(f"[DM] 轮询异常: {e}")
            await asyncio.sleep(self.check_interval)

    async def _check_platform_dms(self, platform: str):
        """检查单个平台的新私信

        实际抓取通过 Interactor 的 fetch_direct_messages 钩子。
        若平台未实现该钩子，则跳过。
        """
        try:
            from api.services.interactor.interactor_factory import InteractorFactory
            from api.services.publisher.account_service import get_account_service

            # 平台名归一化: "x" → "x_twitter"（与 interactor 注册名一致）
            platform_map = {"x": "x_twitter"}
            platform = platform_map.get(platform, platform)

            if not InteractorFactory.is_supported(platform):
                logger.debug(f"[DM][{platform}] 平台不受 InteractorFactory 支持，跳过")
                return
            account = await get_account_service().acquire_cookie(platform, user_id=1)
            if not account:
                logger.info(f"[DM][{platform}] 无可用 cookie，跳过私信检查")
                return
            interactor = InteractorFactory.create(platform, cookies=account.cookies, user_id=1)
            if not await interactor._init_browser():
                logger.info(f"[DM][{platform}] 浏览器初始化失败，跳过私信检查")
                await interactor._close_browser()
                return
            try:
                fetcher = getattr(interactor, "fetch_direct_messages", None)
                if not fetcher:
                    logger.debug(f"[DM][{platform}] interactor 未实现 fetch_direct_messages 钩子")
                    return
                messages = await fetcher()
                if not messages:
                    logger.info(f"[DM][{platform}] 未发现新私信")
                    return
                logger.info(f"[DM][{platform}] 发现 {len(messages)} 条新私信")
                for msg in messages:
                    await self._process_message(msg)
            finally:
                await interactor._close_browser()
        except Exception as e:
            logger.error(f"[DM][{platform}] 检查私信失败: {e}")

    async def _process_message(self, dm: DirectMessage):
        """处理单条私信：入库 + AI 回复 + 跨平台实际发送"""
        # 入库
        msg_id = await self._save_message(dm)
        if msg_id is None:
            return
        dm.id = msg_id

        # 已处理过则跳过
        if dm.state != ConversationState.NEW.value:
            return

        # AI 回复
        replier = get_dm_replier()
        dm = await replier.classify_and_reply(dm)

        # 跨平台实际发送（仅自动回复类型，转人工不自动发送）
        if dm.is_replied and dm.reply_text and not dm.needs_human:
            dm = await replier.reply_cross_platform(dm)

        # 更新数据库
        await self._update_reply(dm)

        # 若需转人工，记录日志
        if dm.needs_human:
            logger.info(
                f"[DM][{dm.platform}] 私信 #{dm.id} 需转人工"
                f"（意图={dm.intent}, 发送者={dm.sender_name}）"
            )
        elif dm.is_replied:
            logger.info(
                f"[DM][{dm.platform}] 私信 #{dm.id} 已自动回复: {dm.reply_text[:30]}"
            )

    async def _save_message(self, dm: DirectMessage) -> Optional[int]:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                # 去重：同平台同会话同内容不重复入库
                existing = await conn.execute(
                    sql_text(
                        "SELECT id FROM direct_messages "
                        "WHERE platform=:p AND conversation_id=:c AND message_text=:t LIMIT 1"
                    ),
                    {"p": dm.platform, "c": dm.conversation_id, "t": dm.message_text[:500]},
                )
                if existing.fetchone():
                    return None
                row = await conn.execute(
                    sql_text(
                        "INSERT INTO direct_messages "
                        "(platform, conversation_id, sender_id, sender_name, message_text, intent, confidence, state) "
                        "VALUES (:p, :c, :si, :sn, :m, :i, :cf, 'new') RETURNING id"
                    ),
                    {
                        "p": dm.platform,
                        "c": dm.conversation_id,
                        "si": dm.sender_id,
                        "sn": dm.sender_name,
                        "m": dm.message_text[:2000],
                        "i": dm.intent,
                        "cf": dm.confidence,
                    },
                )
                r = row.fetchone()
                return r[0] if r else None
        except Exception as e:
            logger.warning(f"[DM] 保存私信失败: {e}")
            return None

    async def _update_reply(self, dm: DirectMessage):
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE direct_messages SET "
                        "intent=:i, confidence=:cf, state=:s, reply_text=:r, "
                        "is_replied=:ir, needs_human=:nh, replied_at=NOW() "
                        "WHERE id=:id"
                    ),
                    {
                        "i": dm.intent,
                        "cf": dm.confidence,
                        "s": dm.state,
                        "r": dm.reply_text[:1000],
                        "ir": dm.is_replied,
                        "nh": dm.needs_human,
                        "id": dm.id,
                    },
                )
        except Exception as e:
            logger.warning(f"[DM] 更新回复失败: {e}")

    # ==================== 查询接口 ====================

    async def list_messages(
        self, platform: str = "", state: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            conditions = []
            params: Dict[str, Any] = {}
            if platform:
                conditions.append("platform=:p")
                params["p"] = platform
            if state:
                conditions.append("state=:s")
                params["s"] = state
            sql = (
                "SELECT id, platform, conversation_id, sender_id, sender_name, "
                "message_text, intent, confidence, state, reply_text, is_replied, "
                "needs_human, received_at, replied_at FROM direct_messages"
            )
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY id DESC LIMIT :l"
            params["l"] = limit
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                return [
                    {
                        "id": r[0],
                        "platform": r[1],
                        "conversation_id": r[2],
                        "sender_id": r[3],
                        "sender_name": r[4],
                        "message_text": r[5],
                        "intent": r[6],
                        "confidence": r[7],
                        "state": r[8],
                        "reply_text": r[9],
                        "is_replied": r[10],
                        "needs_human": r[11],
                        "received_at": str(r[12]) if r[12] else None,
                        "replied_at": str(r[13]) if r[13] else None,
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[DM] 查询私信失败: {e}")
            return []

    async def list_needs_human(self) -> List[Dict[str, Any]]:
        """列出需转人工的私信"""
        return await self.list_messages(state=ConversationState.NEEDS_HUMAN.value, limit=100)

    async def resolve_message(self, msg_id: int) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text("UPDATE direct_messages SET state='resolved' WHERE id=:i"),
                    {"i": msg_id},
                )
            return True
        except Exception:
            return False


_monitor: Optional[DMMonitorService] = None


def get_dm_monitor() -> DMMonitorService:
    global _monitor
    if _monitor is None:
        _monitor = DMMonitorService()
    return _monitor
