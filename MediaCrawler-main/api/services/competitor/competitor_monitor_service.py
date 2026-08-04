# -*- coding: utf-8 -*-
"""
白名单同行监控服务

核心职责：
1. 录入同行账号ID（抖音/快手/小红书/视频号）
2. 定期扫描同行最新视频的评论
3. 识别意向客户评论（复用 lead_extractor）
4. 秒级触达：发现意向评论立即加入任务池
5. 支持配置扫描范围（最新N条视频）和评论时间筛选

参考：知了系统的白名单获客功能
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = ["douyin", "xiaohongshu", "kuaishou", "video_number"]


class CompetitorMonitorService:
    """白名单同行监控服务（单例）"""

    _ensured = False
    _instance = None

    def __init__(self):
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "CompetitorMonitorService":
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
        """创建 competitor_account / competitor_scan_record 表"""
        if CompetitorMonitorService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                # 同行账号表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS competitor_account ("
                        "  id SERIAL PRIMARY KEY,"
                        "  account_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  platform VARCHAR(20) NOT NULL,"
                        "  account_name VARCHAR(255) DEFAULT '',"
                        "  account_url VARCHAR(500) DEFAULT '',"
                        "  scan_range INTEGER DEFAULT 10,"
                        "  comment_days INTEGER DEFAULT 7,"
                        "  status VARCHAR(20) DEFAULT 'active',"
                        "  last_scan_at BIGINT DEFAULT 0,"
                        "  owner_user_id VARCHAR(64) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_competitor_platform "
                        "ON competitor_account(platform, status)"
                    )
                )

                # 扫描记录表（同行视频评论）
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS competitor_scan_record ("
                        "  id SERIAL PRIMARY KEY,"
                        "  record_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  competitor_account_id VARCHAR(64) NOT NULL,"
                        "  platform VARCHAR(20) NOT NULL,"
                        "  video_id VARCHAR(255) DEFAULT '',"
                        "  video_title TEXT DEFAULT '',"
                        "  comment_id VARCHAR(255) DEFAULT '',"
                        "  comment_text TEXT DEFAULT '',"
                        "  commenter_id VARCHAR(255) DEFAULT '',"
                        "  commenter_name VARCHAR(255) DEFAULT '',"
                        "  commenter_url VARCHAR(500) DEFAULT '',"
                        "  is_lead BOOLEAN DEFAULT FALSE,"
                        "  lead_score INTEGER DEFAULT 0,"
                        "  intent_type VARCHAR(50) DEFAULT '',"
                        "  matched_keywords TEXT DEFAULT '',"
                        "  processed BOOLEAN DEFAULT FALSE,"
                        "  created_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_scan_competitor "
                        "ON competitor_scan_record(competitor_account_id, processed)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_scan_lead "
                        "ON competitor_scan_record(is_lead, processed)"
                    )
                )

            CompetitorMonitorService._ensured = True
            logger.info("[CompetitorMonitor] 表创建完成")
        except Exception as e:
            logger.warning(f"[CompetitorMonitor] 建表失败(非致命): {e}")

    async def add_competitor(
        self,
        platform: str,
        account_url: str,
        account_name: str = "",
        scan_range: int = 10,
        comment_days: int = 7,
        owner_user_id: str = "",
    ) -> Dict[str, Any]:
        """添加同行监控账号"""
        if platform not in SUPPORTED_PLATFORMS:
            return {"ok": False, "reason": f"不支持的平台: {platform}，支持 {SUPPORTED_PLATFORMS}"}

        account_id = f"comp_{uuid.uuid4().hex[:12]}"
        now = int(time.time())

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO competitor_account "
                        "(account_id, platform, account_name, account_url, scan_range, comment_days, "
                        "status, owner_user_id, created_at, updated_at) "
                        "VALUES (:aid, :plat, :name, :url, :range, :days, 'active', :owner, :now, :now)"
                    ),
                    {
                        "aid": account_id,
                        "plat": platform,
                        "name": account_name,
                        "url": account_url,
                        "range": scan_range,
                        "days": comment_days,
                        "owner": owner_user_id,
                        "now": now,
                    },
                )

            logger.info(f"[CompetitorMonitor] 添加同行: {account_id} ({platform}) {account_name}")
            return {"ok": True, "account_id": account_id}
        except Exception as e:
            logger.warning(f"[CompetitorMonitor] 添加同行失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def list_competitors(
        self,
        platform: Optional[str] = None,
        status: str = "active",
        owner_user_id: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """列出同行监控账号"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return {"accounts": [], "total": 0}

            conditions = ["status = :status"]
            params: Dict[str, Any] = {"status": status}

            if platform:
                conditions.append("platform = :platform")
                params["platform"] = platform
            if owner_user_id:
                conditions.append("owner_user_id = :owner")
                params["owner"] = owner_user_id

            where = " AND ".join(conditions)
            params["limit"] = page_size
            params["offset"] = (page - 1) * page_size

            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT * FROM competitor_account WHERE {where} "
                        "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                    ),
                    params,
                )
                total = await conn.execute(
                    sql_text(
                        f"SELECT count(*) FROM competitor_account WHERE {where}"
                    ),
                    {k: v for k, v in params.items() if k not in ("limit", "offset")},
                )

            accounts = [dict(r._mapping) for r in rows.fetchall()]
            return {"accounts": accounts, "total": total.scalar()}
        except Exception as e:
            logger.warning(f"[CompetitorMonitor] 列出同行失败: {e}")
            return {"accounts": [], "total": 0}

    async def remove_competitor(self, account_id: str) -> bool:
        """删除同行监控"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE competitor_account SET status = 'removed', updated_at = :now "
                        "WHERE account_id = :aid"
                    ),
                    {"now": int(time.time()), "aid": account_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[CompetitorMonitor] 删除同行失败: {e}")
            return False

    async def scan_competitor(self, account_id: str) -> Dict[str, Any]:
        """扫描单个同行账号的最新视频评论"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                row = await conn.execute(
                    sql_text("SELECT * FROM competitor_account WHERE account_id = :aid"),
                    {"aid": account_id},
                )
                account = row.fetchone()
                if not account:
                    return {"ok": False, "reason": "同行账号不存在"}

                account_data = dict(account._mapping)

            platform = account_data["platform"]
            scan_range = account_data.get("scan_range", 10)
            comment_days = account_data.get("comment_days", 7)

            # 调用对应平台的 fetcher 获取同行最新视频
            comments_found = await self._fetch_competitor_comments(
                platform=platform,
                account_url=account_data["account_url"],
                scan_range=scan_range,
                comment_days=comment_days,
            )

            # 识别意向客户并批量入库（优化：单事务批量插入）
            new_leads = 0
            now = int(time.time())
            records_to_insert = []

            for comment in comments_found:
                record_id = f"scan_{uuid.uuid4().hex[:12]}"
                is_lead = comment.get("is_lead", False)
                if is_lead:
                    new_leads += 1

                records_to_insert.append({
                    "rid": record_id,
                    "caid": account_id,
                    "plat": platform,
                    "vid": comment.get("video_id", ""),
                    "vtitle": comment.get("video_title", ""),
                    "cid": comment.get("comment_id", ""),
                    "ctext": comment.get("comment_text", ""),
                    "uid": comment.get("commenter_id", ""),
                    "uname": comment.get("commenter_name", ""),
                    "uurl": comment.get("commenter_url", ""),
                    "is_lead": is_lead,
                    "score": comment.get("lead_score", 0),
                    "intent": comment.get("intent_type", ""),
                    "kw": comment.get("matched_keywords", ""),
                    "now": now,
                })

            # 批量插入（单事务）
            if records_to_insert:
                async with engine.begin() as conn:
                    for record in records_to_insert:
                        try:
                            await conn.execute(
                                sql_text(
                                    "INSERT INTO competitor_scan_record "
                                    "(record_id, competitor_account_id, platform, video_id, video_title, "
                                    "comment_id, comment_text, commenter_id, commenter_name, commenter_url, "
                                    "is_lead, lead_score, intent_type, matched_keywords, created_at) "
                                    "VALUES (:rid, :caid, :plat, :vid, :vtitle, :cid, :ctext, "
                                    ":uid, :uname, :uurl, :is_lead, :score, :intent, :kw, :now)"
                                ),
                                record,
                            )
                        except Exception:
                            pass  # 去重冲突等

                    # 更新最后扫描时间（同一事务）
                    await conn.execute(
                        sql_text(
                            "UPDATE competitor_account SET last_scan_at = :now, updated_at = :now "
                            "WHERE account_id = :aid"
                        ),
                        {"now": now, "aid": account_id},
                    )

            logger.info(f"[CompetitorMonitor] 扫描完成: {account_id}, 发现 {len(comments_found)} 条评论, {new_leads} 个意向")
            return {"ok": True, "comments_found": len(comments_found), "new_leads": new_leads}
        except Exception as e:
            logger.warning(f"[CompetitorMonitor] 扫描失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def _fetch_competitor_comments(
        self,
        platform: str,
        account_url: str,
        scan_range: int,
        comment_days: int,
    ) -> List[Dict]:
        """抓取同行账号最新视频的评论（复用 CommentFetcherFactory）"""
        try:
            from api.services.comment_monitor.platform_comment_fetcher import CommentFetcherFactory
            from api.services.comment_monitor.lead_extractor import get_lead_extractor

            fetcher = CommentFetcherFactory.create(platform)
            if not fetcher:
                logger.warning(f"[CompetitorMonitor] 平台 {platform} 无可用 fetcher")
                return []

            # 获取同行最新视频
            posts = await fetcher.fetch_user_posts(account_url)
            if not posts:
                return []

            # 只取最新 N 条
            posts = posts[:scan_range]

            all_comments = []
            cutoff_ts = int(time.time()) - comment_days * 86400

            for post in posts:
                post_id = post.get("post_id", "")
                if not post_id:
                    continue

                # 抓取该视频的评论
                result = await fetcher.fetch_comments(post_id, max_count=200)
                for comment in result.comments:
                    if comment.created_ts < cutoff_ts:
                        continue

                    # 意向识别
                    lead_result = await get_lead_extractor().extract(comment)
                    all_comments.append({
                        "video_id": post_id,
                        "video_title": post.get("title", ""),
                        "comment_id": comment.comment_id,
                        "comment_text": comment.comment_text,
                        "commenter_id": comment.author_id,
                        "commenter_name": comment.author_nickname,
                        "commenter_url": "",
                        "is_lead": lead_result.is_lead,
                        "lead_score": lead_result.lead_score,
                        "intent_type": lead_result.intent_type,
                        "matched_keywords": ",".join(lead_result.matched_keywords),
                    })

            return all_comments
        except Exception as e:
            logger.warning(f"[CompetitorMonitor] 抓取评论失败: {e}")
            return []

    async def get_scan_records(
        self,
        account_id: Optional[str] = None,
        is_lead: Optional[bool] = None,
        processed: Optional[bool] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """获取扫描记录"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return {"records": [], "total": 0}

            conditions = []
            params: Dict[str, Any] = {}

            if account_id:
                conditions.append("competitor_account_id = :caid")
                params["caid"] = account_id
            if is_lead is not None:
                conditions.append("is_lead = :is_lead")
                params["is_lead"] = is_lead
            if processed is not None:
                conditions.append("processed = :processed")
                params["processed"] = processed

            where = " AND ".join(conditions) if conditions else "1=1"
            params["limit"] = page_size
            params["offset"] = (page - 1) * page_size

            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT * FROM competitor_scan_record WHERE {where} "
                        "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                    ),
                    params,
                )
                total = await conn.execute(
                    sql_text(
                        f"SELECT count(*) FROM competitor_scan_record WHERE {where}"
                    ),
                    {k: v for k, v in params.items() if k not in ("limit", "offset")},
                )

            records = [dict(r._mapping) for r in rows.fetchall()]
            return {"records": records, "total": total.scalar()}
        except Exception as e:
            logger.warning(f"[CompetitorMonitor] 获取记录失败: {e}")
            return {"records": [], "total": 0}

    async def get_stats(self, owner_user_id: str = "") -> Dict[str, Any]:
        """获取统计信息"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return {}

            params: Dict[str, Any] = {}
            owner_clause = ""
            if owner_user_id:
                owner_clause = " AND owner_user_id = :owner"
                params["owner"] = owner_user_id

            async with engine.connect() as conn:
                total_accounts = await conn.execute(
                    sql_text(f"SELECT count(*) FROM competitor_account WHERE status='active'{owner_clause}"),
                    params,
                )
                total_leads = await conn.execute(
                    sql_text("SELECT count(*) FROM competitor_scan_record WHERE is_lead=TRUE"),
                )
                unprocessed = await conn.execute(
                    sql_text("SELECT count(*) FROM competitor_scan_record WHERE is_lead=TRUE AND processed=FALSE"),
                )

            return {
                "total_competitors": total_accounts.scalar(),
                "total_leads_found": total_leads.scalar(),
                "unprocessed_leads": unprocessed.scalar(),
            }
        except Exception as e:
            logger.warning(f"[CompetitorMonitor] 统计失败: {e}")
            return {}


def get_competitor_monitor_service() -> CompetitorMonitorService:
    return CompetitorMonitorService.get_instance()
