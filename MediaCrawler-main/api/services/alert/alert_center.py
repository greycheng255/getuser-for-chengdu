# -*- coding: utf-8 -*-
"""
统一预警中心

阶段一 P0 任务 1.4：横向能力，覆盖突发热点 + 账号异常 + 数据异常 + 内容异常四类预警。

设计：
1. AlertCenter 统一汇集所有预警源
2. AlertType 四类：HOTPOINT_BURST / ACCOUNT_ANOMALY / DATA_ANOMALY / CONTENT_VIOLATION
3. AlertSeverity 三级：INFO / WARNING / CRITICAL
4. 持久化到 alerts 表（含 owner_user_id 隔离）
5. WebSocket 实时推送 + REST API 查询
6. 预警源集成：
   - 账号异常：监听 publisher/interactor 失败事件，触发 ACCOUNT_ANOMALY
   - 数据异常：定时任务对比同期数据，触发 DATA_ANOMALY
   - 内容异常：moderation_service 拦截时触发 CONTENT_VIOLATION
   - 突发热点：hotpoint_alert 检测到突变，触发 HOTPOINT_BURST
"""

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class AlertType(str, Enum):
    """预警类型"""
    HOTPOINT_BURST = "hotpoint_burst"          # 突发热点
    ACCOUNT_ANOMALY = "account_anomaly"        # 账号异常
    DATA_ANOMALY = "data_anomaly"              # 数据异常
    CONTENT_VIOLATION = "content_violation"    # 内容违规
    PUBLISH_FAILURE = "publish_failure"        # 发布失败


class AlertSeverity(str, Enum):
    """预警严重度"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    """预警状态"""
    UNREAD = "unread"
    READ = "read"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass
class Alert:
    """预警数据类"""
    alert_id: str = ""
    alert_type: str = AlertType.INFO.value if False else "info"
    severity: str = AlertSeverity.INFO.value
    source: str = ""                  # 预警来源（hotpoint_alert/account_health/analytics/moderation）
    title: str = ""
    content: str = ""
    action_url: str = ""              # 一键处理 URL（如热点取材 URL）
    action_label: str = ""            # 行动按钮文案（如"一键取材"）
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = AlertStatus.UNREAD.value
    owner_user_id: Optional[int] = None
    created_at: Optional[datetime] = None   # 持久化时用 datetime 对象（PG TIMESTAMP 列要求）
    read_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.alert_id:
            self.alert_id = f"alert_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # datetime 对象 → ISO 字符串（用于 WebSocket JSON 推送）
        if isinstance(d.get("created_at"), datetime):
            d["created_at"] = d["created_at"].isoformat()
        if isinstance(d.get("read_at"), datetime):
            d["read_at"] = d["read_at"].isoformat()
        return d


class AlertCenter:
    """统一预警中心"""

    def __init__(self):
        # 内存订阅者（WebSocket 连接）
        self._subscribers: Set[asyncio.Queue] = set()
        self._table_ready = False

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if AlertCenter._ensured:
            return
        if self._table_ready:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS alerts ("
                        "  alert_id VARCHAR(64) PRIMARY KEY,"
                        "  alert_type VARCHAR(32) NOT NULL,"
                        "  severity VARCHAR(16) NOT NULL,"
                        "  source VARCHAR(64),"
                        "  title VARCHAR(256),"
                        "  content TEXT,"
                        "  action_url TEXT,"
                        "  action_label VARCHAR(64),"
                        "  metadata TEXT,"
                        "  status VARCHAR(16) DEFAULT 'unread',"
                        "  owner_user_id INTEGER,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  read_at TIMESTAMP)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_alerts_owner_status "
                        "ON alerts(owner_user_id, status, created_at DESC)"
                    )
                )
            self._table_ready = True
            AlertCenter._ensured = True
        except Exception as e:
            logger.warning(f"[AlertCenter] ensure_table failed: {e}")

    async def emit_alert(self, alert: Alert) -> str:
        """发送预警（持久化 + 实时推送）"""
        await self.ensure_table()
        # 持久化
        await self._persist(alert)
        # 实时推送
        await self._broadcast(alert)
        logger.info(
            f"[AlertCenter] 预警已发送: type={alert.alert_type} severity={alert.severity} title={alert.title}"
        )
        return alert.alert_id

    async def emit(
        self,
        alert_type: str,
        severity: str,
        title: str,
        content: str,
        source: str = "",
        action_url: str = "",
        action_label: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        owner_user_id: Optional[int] = None,
    ) -> str:
        """便捷发送预警（自动构建 Alert 对象）"""
        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            source=source,
            title=title,
            content=content,
            action_url=action_url,
            action_label=action_label,
            metadata=metadata or {},
            owner_user_id=owner_user_id,
        )
        return await self.emit_alert(alert)

    async def _persist(self, alert: Alert) -> None:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO alerts "
                        "(alert_id, alert_type, severity, source, title, content, "
                        " action_url, action_label, metadata, status, owner_user_id, created_at) "
                        "VALUES (:aid, :at, :se, :src, :ti, :ct, :au, :al, :md, :st, :ouid, :ca) "
                        "ON CONFLICT (alert_id) DO NOTHING"
                    ),
                    {
                        "aid": alert.alert_id,
                        "at": alert.alert_type,
                        "se": alert.severity,
                        "src": alert.source,
                        "ti": alert.title,
                        "ct": alert.content,
                        "au": alert.action_url,
                        "al": alert.action_label,
                        "md": json.dumps(alert.metadata, ensure_ascii=False),
                        "st": alert.status,
                        "ouid": alert.owner_user_id,
                        "ca": alert.created_at,
                    },
                )
        except Exception as e:
            logger.warning(f"[AlertCenter] persist failed: {e}")

    async def _broadcast(self, alert: Alert) -> None:
        """广播给所有订阅者"""
        dead_queues = []
        for q in self._subscribers:
            try:
                q.put_nowait(alert.to_dict())
            except asyncio.QueueFull:
                dead_queues.append(q)
            except Exception:
                dead_queues.append(q)
        for q in dead_queues:
            self._subscribers.discard(q)

    def subscribe(self) -> asyncio.Queue:
        """订阅预警推送（返回 Queue，调用方 await q.get()）"""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def list_alerts(
        self,
        owner_user_id: Optional[int] = None,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询预警列表"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            sql = "SELECT * FROM alerts WHERE 1=1"
            params: Dict[str, Any] = {"limit": limit, "offset": offset}
            if owner_user_id is not None:
                sql += " AND owner_user_id = :ouid"
                params["ouid"] = owner_user_id
            if alert_type:
                sql += " AND alert_type = :at"
                params["at"] = alert_type
            if severity:
                sql += " AND severity = :se"
                params["se"] = severity
            if status:
                sql += " AND status = :st"
                params["st"] = status
            sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                items = [self._row_to_dict(r) for r in rows.fetchall()]

                # 回填热点预警的帖子 URL：对 hotpoint_burst 类型且 post_url 为空的预警，
                # 通过 metadata.hotspot_id 反查 hot_items 表补全 url（修复历史预警缺链接问题）
                hotpoint_alerts = [
                    it for it in items
                    if it.get("alert_type") == "hotpoint_burst"
                    and not (it.get("metadata", {}) or {}).get("post_url")
                    and (it.get("metadata", {}) or {}).get("hotspot_id")
                ]
                if hotpoint_alerts:
                    hotspot_ids = [it["metadata"]["hotspot_id"] for it in hotpoint_alerts]
                    # 批量查询 hot_items 表获取 url（按字符串 hot_id 匹配，兼容整数/字符串主键）
                    placeholders = ",".join(f":hid{i}" for i in range(len(hotspot_ids)))
                    url_params = {f"hid{i}": str(hid) for i, hid in enumerate(hotspot_ids)}
                    url_rows = await conn.execute(
                        sql_text(
                            f"SELECT CAST(hot_id AS TEXT), url FROM hot_items "
                            f"WHERE CAST(hot_id AS TEXT) IN ({placeholders}) AND url IS NOT NULL AND url != ''"
                        ),
                        url_params,
                    )
                    url_map = {r[0]: r[1] for r in url_rows.fetchall()}
                    for it in hotpoint_alerts:
                        hid_str = str(it["metadata"]["hotspot_id"])
                        url = url_map.get(hid_str)
                        if url:
                            it["metadata"]["post_url"] = url
                            # action_url 如果是内部路径则替换为真实帖子 URL
                            if not it.get("action_url") or it["action_url"].startswith("/api/"):
                                it["action_url"] = url

            return items
        except Exception as e:
            logger.warning(f"[AlertCenter] list_alerts failed: {e}")
            return []

    async def mark_read(self, alert_id: str, user_id: Optional[int] = None) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                if user_id is not None:
                    await conn.execute(
                        sql_text(
                            "UPDATE alerts SET status='read', read_at=:ra "
                            "WHERE alert_id=:aid AND owner_user_id=:ouid"
                        ),
                        {"ra": datetime.now(), "aid": alert_id, "ouid": user_id},
                    )
                else:
                    await conn.execute(
                        sql_text(
                            "UPDATE alerts SET status='read', read_at=:ra WHERE alert_id=:aid"
                        ),
                        {"ra": datetime.now(), "aid": alert_id},
                    )
            return True
        except Exception as e:
            logger.warning(f"[AlertCenter] mark_read failed: {e}")
            return False

    async def mark_all_read(self, user_id: Optional[int] = None) -> int:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return 0
            async with engine.begin() as conn:
                if user_id is not None:
                    result = await conn.execute(
                        sql_text(
                            "UPDATE alerts SET status='read', read_at=:ra "
                            "WHERE status='unread' AND owner_user_id=:ouid"
                        ),
                        {"ra": datetime.now(), "ouid": user_id},
                    )
                else:
                    result = await conn.execute(
                        sql_text(
                            "UPDATE alerts SET status='read', read_at=:ra WHERE status='unread'"
                        ),
                        {"ra": datetime.now()},
                    )
                return result.rowcount or 0
        except Exception as e:
            logger.warning(f"[AlertCenter] mark_all_read failed: {e}")
            return 0

    async def count_unread(self, user_id: Optional[int] = None) -> int:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return 0
            async with engine.connect() as conn:
                if user_id is not None:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) FROM alerts WHERE status='unread' AND owner_user_id=:ouid"
                        ),
                        {"ouid": user_id},
                    )
                else:
                    rows = await conn.execute(
                        sql_text("SELECT COUNT(*) FROM alerts WHERE status='unread'")
                    )
                return rows.scalar() or 0
        except Exception as e:
            logger.warning(f"[AlertCenter] count_unread failed: {e}")
            return 0

    def _row_to_dict(self, row) -> Dict[str, Any]:
        try:
            md = json.loads(row[8]) if row[8] else {}
        except Exception:
            md = {}
        return {
            "alert_id": row[0],
            "alert_type": row[1],
            "severity": row[2],
            "source": row[3],
            "title": row[4],
            "content": row[5],
            "action_url": row[6],
            "action_label": row[7],
            "metadata": md,
            "status": row[9],
            "owner_user_id": row[10],
            "created_at": str(row[11]) if row[11] else None,
            "read_at": str(row[12]) if row[12] else None,
        }


# ============ 单例 ============
_center: Optional[AlertCenter] = None


def get_alert_center() -> AlertCenter:
    global _center
    if _center is None:
        _center = AlertCenter()
    return _center


# ============ 便捷触发函数 ============

async def emit_account_anomaly(
    platform: str,
    account_label: str,
    failure_type: str,
    details: str = "",
    owner_user_id: Optional[int] = None,
) -> str:
    """触发账号异常预警"""
    severity = AlertSeverity.CRITICAL.value if failure_type in ("限流", "封禁", "登录失效") else AlertSeverity.WARNING.value
    return await get_alert_center().emit(
        alert_type=AlertType.ACCOUNT_ANOMALY.value,
        severity=severity,
        title=f"账号异常：{platform} - {account_label}",
        content=f"异常类型：{failure_type}\n详情：{details}",
        source="account_health",
        action_url=f"/api/risk-control/accounts?platform={platform}",
        action_label="查看账号",
        metadata={"platform": platform, "account_label": account_label, "failure_type": failure_type},
        owner_user_id=owner_user_id,
    )


async def emit_data_anomaly(
    metric_name: str,
    current_value: float,
    baseline_value: float,
    drop_pct: float,
    owner_user_id: Optional[int] = None,
) -> str:
    """触发数据异常预警"""
    severity = AlertSeverity.CRITICAL.value if drop_pct > 30 else AlertSeverity.WARNING.value
    return await get_alert_center().emit(
        alert_type=AlertType.DATA_ANOMALY.value,
        severity=severity,
        title=f"数据异常：{metric_name} 下降 {drop_pct:.1f}%",
        content=f"指标：{metric_name}\n当前值：{current_value}\n基线值：{baseline_value}\n下降幅度：{drop_pct:.1f}%",
        source="analytics",
        action_url="/api/analytics/trends",
        action_label="查看趋势",
        metadata={"metric_name": metric_name, "current": current_value, "baseline": baseline_value, "drop_pct": drop_pct},
        owner_user_id=owner_user_id,
    )


async def emit_content_violation(
    platform: str,
    content_preview: str,
    violation_type: str,
    severity: str = AlertSeverity.WARNING.value,
    owner_user_id: Optional[int] = None,
) -> str:
    """触发内容违规预警"""
    return await get_alert_center().emit(
        alert_type=AlertType.CONTENT_VIOLATION.value,
        severity=severity,
        title=f"内容违规：{platform} - {violation_type}",
        content=f"违规类型：{violation_type}\n内容预览：{content_preview[:200]}",
        source="moderation",
        action_url="/api/moderation/log",
        action_label="查看审核日志",
        metadata={"platform": platform, "violation_type": violation_type},
        owner_user_id=owner_user_id,
    )


async def emit_hotpoint_burst(
    hotspot_id: str,
    title: str,
    heat_value: int,
    delta: int,
    velocity: float,
    platforms: List[str],
    owner_user_id: Optional[int] = None,
    post_url: str = "",
) -> str:
    """触发突发热点预警

    Args:
        post_url: 热点帖子原始 URL，存入 metadata 供预警中心展示，
                  让用户能直接点击查看具体内容（而非仅看标题）
    """
    return await get_alert_center().emit(
        alert_type=AlertType.HOTPOINT_BURST.value,
        severity=AlertSeverity.CRITICAL.value if delta > 5000 else AlertSeverity.WARNING.value,
        title=f"突发热点：{title[:50]}",
        content=f"热度值：{heat_value}\n10分钟增量：{delta}\n增速：{velocity:.2f}x\n适配平台：{', '.join(platforms)}",
        source="hotpoint_alert",
        action_url=post_url or f"/api/hotpoint/{hotspot_id}/quick-create",
        action_label="查看原帖" if post_url else "一键取材",
        metadata={
            "hotspot_id": hotspot_id,
            "heat_value": heat_value,
            "delta": delta,
            "velocity": velocity,
            "platforms": platforms,
            "post_url": post_url,
        },
        owner_user_id=owner_user_id,
    )


async def emit_publish_failure(
    platform: str,
    account_label: str,
    error_message: str,
    content_preview: str = "",
    post_id: str = "",
    owner_user_id: Optional[int] = None,
) -> str:
    """触发发布失败预警

    适用于：
    - X 平台 GraphQL CreateTweet 失败
    - 国内平台 MultiPlatformPublisher 发布失败
    - 自动流水线 auto_pipeline 发布失败

    失败原因若包含登录失效/限流/封禁关键词则升级为 CRITICAL。
    """
    critical_keywords = ("登录失效", "限流", "封禁", "账号异常", "风控", "cookie", "unauthorized")
    severity = (
        AlertSeverity.CRITICAL.value
        if any(kw in (error_message or "").lower() for kw in critical_keywords)
        else AlertSeverity.WARNING.value
    )
    return await get_alert_center().emit(
        alert_type=AlertType.PUBLISH_FAILURE.value,
        severity=severity,
        title=f"发布失败：{platform} - {account_label}",
        content=(
            f"平台：{platform}\n"
            f"账号：{account_label}\n"
            f"失败原因：{error_message[:500]}\n"
            f"内容预览：{content_preview[:200]}"
        ),
        source="publisher",
        action_url=f"/api/publish-center?platform={platform}",
        action_label="查看发布中心",
        metadata={
            "platform": platform,
            "account_label": account_label,
            "error_message": error_message[:1000],
            "post_id": post_id,
        },
        owner_user_id=owner_user_id,
    )
