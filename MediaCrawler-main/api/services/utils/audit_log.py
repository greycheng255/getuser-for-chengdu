# -*- coding: utf-8 -*-
"""
操作日志服务 + 定时报表生成

阶段三 P2 任务 3.5：补齐 PRD 5.5 操作日志 + 日/周/月报表。

核心能力：
1. 统一记录所有用户操作（发布/互动/配置变更/账号管理）
2. 持久化到 audit_logs 表
3. 多维度查询（用户/操作类型/时间范围）
4. 定时报表生成（每日/每周/每月）
5. 自动调用 export_service 导出 CSV/Excel
6. 通过邮件/Webhook 推送（留扩展点）
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AuditActionType(str, Enum):
    """操作类型"""
    PUBLISH = "publish"               # 发布
    INTERACTION = "interaction"       # 互动
    CONFIG_CHANGE = "config_change"   # 配置变更
    ACCOUNT_MGMT = "account_mgmt"     # 账号管理
    LOGIN = "login"                   # 登录
    EXPORT = "export"                 # 数据导出
    OTHER = "other"


@dataclass
class AuditLog:
    """操作日志"""
    log_id: str = ""
    action_type: str = AuditActionType.OTHER.value
    user_id: Optional[int] = None
    platform: str = ""
    target: str = ""               # 操作目标（如帖子 URL、账号 ID）
    description: str = ""          # 操作描述
    request_data: Dict[str, Any] = field(default_factory=dict)
    response_data: Dict[str, Any] = field(default_factory=dict)
    ip_address: str = ""
    user_agent: str = ""
    status: str = "success"        # success / failed
    error_message: str = ""
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AuditLogService:
    """操作日志服务"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if AuditLogService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS audit_logs ("
                        "  log_id VARCHAR(64) PRIMARY KEY,"
                        "  action_type VARCHAR(32) NOT NULL,"
                        "  user_id INTEGER,"
                        "  platform VARCHAR(32),"
                        "  target TEXT,"
                        "  description TEXT,"
                        "  request_data TEXT,"
                        "  response_data TEXT,"
                        "  ip_address VARCHAR(64),"
                        "  user_agent TEXT,"
                        "  status VARCHAR(16),"
                        "  error_message TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW())"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_audit_logs_lookup "
                        "ON audit_logs(action_type, user_id, created_at)"
                    )
                )
            AuditLogService._ensured = True
        except Exception as e:
            logger.warning(f"[AuditLog] ensure_table failed: {e}")

    async def log(
        self,
        action_type: str,
        user_id: Optional[int] = None,
        platform: str = "",
        target: str = "",
        description: str = "",
        request_data: Optional[Dict] = None,
        response_data: Optional[Dict] = None,
        ip_address: str = "",
        user_agent: str = "",
        status: str = "success",
        error_message: str = "",
    ) -> str:
        """记录操作日志"""
        await self.ensure_table()
        # 注意：TIMESTAMP 列需要 datetime 对象，asyncpg 不接受 isoformat 字符串
        now_dt = datetime.utcnow()
        log = AuditLog(
            log_id=f"audit_{uuid.uuid4().hex[:12]}",
            action_type=action_type,
            user_id=user_id,
            platform=platform,
            target=target,
            description=description,
            request_data=request_data or {},
            response_data=response_data or {},
            ip_address=ip_address,
            user_agent=user_agent,
            status=status,
            error_message=error_message,
            created_at=now_dt.isoformat(),
        )
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return log.log_id
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO audit_logs "
                        "(log_id, action_type, user_id, platform, target, description, "
                        " request_data, response_data, ip_address, user_agent, "
                        " status, error_message, created_at) "
                        "VALUES (:lid, :at, :uid, :pf, :tg, :desc, :req, :resp, :ip, :ua, :st, :em, :ca)"
                    ),
                    {
                        "lid": log.log_id, "at": log.action_type, "uid": log.user_id,
                        "pf": log.platform, "tg": log.target, "desc": log.description,
                        "req": json.dumps(log.request_data, ensure_ascii=False),
                        "resp": json.dumps(log.response_data, ensure_ascii=False),
                        "ip": log.ip_address, "ua": log.user_agent,
                        "st": log.status, "em": log.error_message, "ca": now_dt,
                    },
                )
        except Exception as e:
            logger.warning(f"[AuditLog] log failed: {e}")
        return log.log_id

    async def list_logs(
        self,
        action_type: Optional[str] = None,
        user_id: Optional[int] = None,
        platform: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询操作日志"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                sql = "SELECT * FROM audit_logs WHERE 1=1"
                params: Dict[str, Any] = {"limit": limit, "offset": offset}
                if action_type:
                    sql += " AND action_type = :at"
                    params["at"] = action_type
                if user_id is not None:
                    sql += " AND user_id = :uid"
                    params["uid"] = user_id
                if platform:
                    sql += " AND platform = :pf"
                    params["pf"] = platform
                if start_date:
                    sql += " AND created_at >= :sd"
                    params["sd"] = start_date
                if end_date:
                    sql += " AND created_at <= :ed"
                    params["ed"] = end_date
                sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                rows = await conn.execute(sql_text(sql), params)
                result = []
                for r in rows.fetchall():
                    try:
                        req = json.loads(r[6]) if r[6] else {}
                        resp = json.loads(r[7]) if r[7] else {}
                    except Exception:
                        req, resp = {}, {}
                    result.append({
                        "log_id": r[0], "action_type": r[1], "user_id": r[2],
                        "platform": r[3], "target": r[4], "description": r[5],
                        "request_data": req, "response_data": resp,
                        "ip_address": r[8], "user_agent": r[9],
                        "status": r[10], "error_message": r[11],
                        "created_at": str(r[12]) if r[12] else "",
                    })
                return result
        except Exception as e:
            logger.warning(f"[AuditLog] list_logs failed: {e}")
            return []


@dataclass
class ReportSummary:
    """报表摘要"""
    report_id: str = ""
    period: str = ""           # daily / weekly / monthly
    start_date: str = ""
    end_date: str = ""
    # 核心指标
    total_publishes: int = 0
    success_publishes: int = 0
    failed_publishes: int = 0
    total_interactions: int = 0
    total_followers_gained: int = 0
    total_views: int = 0
    # 平台维度
    platform_breakdown: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # 文件路径
    export_file_path: str = ""
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReportScheduler:
    """定时报表生成器"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if ReportScheduler._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS report_summaries ("
                        "  report_id VARCHAR(64) PRIMARY KEY,"
                        "  period VARCHAR(16),"
                        "  start_date DATE,"
                        "  end_date DATE,"
                        "  total_publishes INTEGER,"
                        "  success_publishes INTEGER,"
                        "  failed_publishes INTEGER,"
                        "  total_interactions INTEGER,"
                        "  total_followers_gained INTEGER,"
                        "  total_views INTEGER,"
                        "  platform_breakdown TEXT,"
                        "  export_file_path TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW())"
                    )
                )
            ReportScheduler._ensured = True
        except Exception as e:
            logger.warning(f"[ReportScheduler] ensure_table failed: {e}")

    async def generate_report(
        self, period: str = "daily", days: int = 1,
    ) -> ReportSummary:
        """生成报表

        Args:
            period: daily / weekly / monthly
            days: 报表覆盖天数
        """
        await self.ensure_table()
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=days)
        # 注意：TIMESTAMP 列需要 datetime 对象，asyncpg 不接受 isoformat 字符串
        report_now_dt = datetime.utcnow()
        report = ReportSummary(
            report_id=f"rpt_{uuid.uuid4().hex[:12]}",
            period=period,
            start_date=str(start_date),
            end_date=str(end_date),
            created_at=report_now_dt.isoformat(),
        )

        # 汇总发布数据
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is not None:
                async with engine.connect() as conn:
                    # 发布统计
                    rows = await conn.execute(
                        sql_text(
                            "SELECT platform, status, COUNT(*) FROM audit_logs "
                            "WHERE action_type = 'publish' "
                            "AND created_at >= :sd AND created_at <= :ed "
                            "GROUP BY platform, status"
                        ),
                        {"sd": str(start_date), "ed": str(end_date)},
                    )
                    platform_breakdown: Dict[str, Dict[str, int]] = {}
                    for r in rows.fetchall():
                        pf = r[0] or "unknown"
                        st = r[1] or "unknown"
                        cnt = int(r[2] or 0)
                        if pf not in platform_breakdown:
                            platform_breakdown[pf] = {}
                        platform_breakdown[pf][st] = cnt
                        report.total_publishes += cnt
                        if st == "success":
                            report.success_publishes += cnt
                        elif st == "failed":
                            report.failed_publishes += cnt
                    report.platform_breakdown = platform_breakdown
                    # 互动统计
                    rows = await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) FROM audit_logs "
                            "WHERE action_type = 'interaction' "
                            "AND created_at >= :sd AND created_at <= :ed"
                        ),
                        {"sd": str(start_date), "ed": str(end_date)},
                    )
                    report.total_interactions = int(rows.fetchone()[0] or 0)
                    # 外部数据
                    try:
                        rows = await conn.execute(
                            sql_text(
                                "SELECT "
                                "  COALESCE(SUM(followers_delta), 0), "
                                "  COALESCE(SUM(views_count), 0) "
                                "FROM external_metrics "
                                "WHERE metric_date >= :sd AND metric_date <= :ed"
                            ),
                            {"sd": str(start_date), "ed": str(end_date)},
                        )
                        row = rows.fetchone()
                        if row:
                            report.total_followers_gained = int(row[0] or 0)
                            report.total_views = int(row[1] or 0)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[ReportScheduler] 查询数据失败: {e}")

        # 导出 CSV
        report.export_file_path = await self._export_csv(report)
        # 持久化
        await self._save_report(report, report_now_dt)
        return report

    async def _export_csv(self, report: ReportSummary) -> str:
        """导出 CSV 文件"""
        try:
            import csv
            import os
            export_dir = os.environ.get(
                "REPORT_EXPORT_DIR", "/tmp/mediacrawler_reports"
            )
            os.makedirs(export_dir, exist_ok=True)
            file_path = os.path.join(export_dir, f"{report.report_id}.csv")
            with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["指标", "数值"])
                writer.writerow(["报表周期", report.period])
                writer.writerow(["开始日期", report.start_date])
                writer.writerow(["结束日期", report.end_date])
                writer.writerow(["总发布数", report.total_publishes])
                writer.writerow(["成功发布", report.success_publishes])
                writer.writerow(["失败发布", report.failed_publishes])
                writer.writerow(["总互动数", report.total_interactions])
                writer.writerow(["新增粉丝", report.total_followers_gained])
                writer.writerow(["总播放量", report.total_views])
                writer.writerow([])
                writer.writerow(["平台", "成功", "失败"])
                for pf, stats in report.platform_breakdown.items():
                    writer.writerow([
                        pf, stats.get("success", 0), stats.get("failed", 0),
                    ])
            return file_path
        except Exception as e:
            logger.warning(f"[ReportScheduler] _export_csv failed: {e}")
            return ""

    async def _save_report(self, report: ReportSummary, now_dt: Optional[datetime] = None) -> None:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            # TIMESTAMP 列需要 datetime 对象
            ca_dt = now_dt if now_dt is not None else datetime.utcnow()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO report_summaries "
                        "(report_id, period, start_date, end_date, total_publishes, "
                        " success_publishes, failed_publishes, total_interactions, "
                        " total_followers_gained, total_views, platform_breakdown, "
                        " export_file_path, created_at) "
                        "VALUES (:rid, :pd, :sd, :ed, :tp, :sp, :fp, :ti, :tf, :tv, :pb, :efp, :ca)"
                    ),
                    {
                        "rid": report.report_id, "pd": report.period,
                        "sd": report.start_date, "ed": report.end_date,
                        "tp": report.total_publishes, "sp": report.success_publishes,
                        "fp": report.failed_publishes, "ti": report.total_interactions,
                        "tf": report.total_followers_gained, "tv": report.total_views,
                        "pb": json.dumps(report.platform_breakdown, ensure_ascii=False),
                        "efp": report.export_file_path, "ca": ca_dt,
                    },
                )
        except Exception as e:
            logger.warning(f"[ReportScheduler] _save_report failed: {e}")

    async def list_reports(
        self, period: Optional[str] = None, limit: int = 30,
    ) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                sql = "SELECT * FROM report_summaries"
                params: Dict[str, Any] = {"limit": limit}
                if period:
                    sql += " WHERE period = :pd"
                    params["pd"] = period
                sql += " ORDER BY created_at DESC LIMIT :limit"
                rows = await conn.execute(sql_text(sql), params)
                result = []
                for r in rows.fetchall():
                    try:
                        pb = json.loads(r[10]) if r[10] else {}
                    except Exception:
                        pb = {}
                    result.append({
                        "report_id": r[0], "period": r[1],
                        "start_date": str(r[2]) if r[2] else "",
                        "end_date": str(r[3]) if r[3] else "",
                        "total_publishes": int(r[4] or 0),
                        "success_publishes": int(r[5] or 0),
                        "failed_publishes": int(r[6] or 0),
                        "total_interactions": int(r[7] or 0),
                        "total_followers_gained": int(r[8] or 0),
                        "total_views": int(r[9] or 0),
                        "platform_breakdown": pb,
                        "export_file_path": r[11] or "",
                        "created_at": str(r[12]) if r[12] else "",
                    })
                return result
        except Exception as e:
            logger.warning(f"[ReportScheduler] list_reports failed: {e}")
            return []


# ============ 单例 ============

_audit_svc: Optional[AuditLogService] = None
_report_svc: Optional[ReportScheduler] = None


def get_audit_log_service() -> AuditLogService:
    global _audit_svc
    if _audit_svc is None:
        _audit_svc = AuditLogService()
    return _audit_svc


def get_report_scheduler() -> ReportScheduler:
    global _report_svc
    if _report_svc is None:
        _report_svc = ReportScheduler()
    return _report_svc
