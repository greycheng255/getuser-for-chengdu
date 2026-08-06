# -*- coding: utf-8 -*-
"""
数据分析服务

迁移自 GEO-main analytics_service.py，适配 MediaCrawler：
从业务表（x_twitter_sent_comment / scheduled_publish_tasks / moderation_log /
sentiment_items / publisher_accounts）实时聚合统计。

对应 PRD 5.5 数据统计 - 全链路数据统计 + 数据可视化。
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from api.services.account_feature_flags import unified_account_read_enabled

logger = logging.getLogger(__name__)

# 简单内存缓存: (key) -> (timestamp, data)
_dashboard_cache: Dict[str, tuple] = {}
_CACHE_TTL = 300  # 5 分钟缓存


class AnalyticsService:
    """数据分析服务（异步，多源聚合）"""

    @staticmethod
    async def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        try:
            from database.db_session import get_async_engine
            import config
            return get_async_engine(config.SAVE_DATA_OPTION)
        except Exception:
            return None

    async def get_dashboard(self, days: int = 7) -> Dict[str, Any]:
        """仪表盘汇总数据（带 5 分钟缓存）"""
        cache_key = f"dashboard_{days}"
        cached = _dashboard_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            logger.info("[Analytics] 命中缓存")
            return cached[1]

        result = await self._get_dashboard_uncached(days)
        _dashboard_cache[cache_key] = (time.time(), result)
        return result

    async def _get_dashboard_uncached(self, days: int = 7) -> Dict[str, Any]:
        """仪表盘汇总数据（无缓存）"""
        engine = await self._get_engine()
        if engine is None:
            return {"summary": {}, "trends": [], "platform_distribution": []}

        from sqlalchemy import text as sql_text

        now = datetime.utcnow()
        since = now - timedelta(days=days)
        summary = {}

        try:
            async with engine.connect() as conn:
                # 发布量（x_twitter_sent_comment 表，X 平台已发评论）
                # 注意：sent_at 是 BigInteger 秒级时间戳，需转 timestamp 比较
                since_ts = int(since.timestamp())
                rows = await conn.execute(
                    sql_text(
                        "SELECT COUNT(*) FROM x_twitter_sent_comment WHERE sent_at>=:s"
                    ),
                    {"s": since_ts},
                )
                summary["publish_count"] = rows.scalar() or 0

                # 发布成功率（sent_status='success' 或有 post_id 的视为成功）
                rows = await conn.execute(
                    sql_text(
                        "SELECT COUNT(*) FROM x_twitter_sent_comment "
                        "WHERE sent_at>=:s AND (sent_status='success' OR "
                        "(post_id IS NOT NULL AND post_id!=''))"
                    ),
                    {"s": since_ts},
                )
                success_count = rows.scalar() or 0
                summary["publish_success"] = success_count
                summary["publish_success_rate"] = (
                    round(success_count / summary["publish_count"] * 100, 1)
                    if summary["publish_count"]
                    else 0.0
                )

                # 定时发布任务数
                try:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT COUNT(*), "
                            "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) "
                            "FROM scheduled_publish_tasks WHERE created_at>=:s"
                        ),
                        {"s": since},
                    )
                    r = rows.fetchone()
                    summary["scheduled_count"] = r[0] or 0
                    summary["scheduled_success"] = r[1] or 0
                except Exception:
                    summary["scheduled_count"] = 0
                    summary["scheduled_success"] = 0

                # 审核统计
                try:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT COUNT(*), "
                            "SUM(CASE WHEN decision='approved' THEN 1 ELSE 0 END), "
                            "SUM(CASE WHEN decision='rejected' THEN 1 ELSE 0 END) "
                            "FROM moderation_log WHERE created_at>=:s"
                        ),
                        {"s": since},
                    )
                    r = rows.fetchone()
                    summary["moderation_total"] = r[0] or 0
                    summary["moderation_approved"] = r[1] or 0
                    summary["moderation_rejected"] = r[2] or 0
                    summary["moderation_pass_rate"] = (
                        round(summary["moderation_approved"] / summary["moderation_total"] * 100, 1)
                        if summary["moderation_total"]
                        else 0.0
                    )
                except Exception:
                    summary["moderation_total"] = 0
                    summary["moderation_approved"] = 0
                    summary["moderation_rejected"] = 0
                    summary["moderation_pass_rate"] = 0.0

                # 舆情预警数
                try:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) FROM sentiment_alerts "
                            "WHERE created_at>=:s AND is_resolved=FALSE"
                        ),
                        {"s": since},
                    )
                    summary["sentiment_alerts"] = rows.scalar() or 0
                except Exception:
                    summary["sentiment_alerts"] = 0

                # 账号池状态
                try:
                    account_sql = (
                        "SELECT platform, COUNT(*), "
                        "SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) "
                        "FROM unified_accounts WHERE role IN ('publisher','both') GROUP BY platform"
                        if unified_account_read_enabled()
                        else
                        "SELECT platform, COUNT(*), "
                        "SUM(CASE WHEN status='active' AND is_active=1 THEN 1 ELSE 0 END) "
                        "FROM publisher_accounts GROUP BY platform"
                    )
                    rows = await conn.execute(
                        sql_text(account_sql)
                    )
                    account_stats = [
                        {"platform": r[0], "total": r[1], "active": r[2]}
                        for r in rows.fetchall()
                    ]
                    summary["accounts"] = account_stats
                except Exception:
                    summary["accounts"] = []
        except Exception as e:
            logger.warning(f"[Analytics] 仪表盘查询失败: {e}")

        # 趋势数据（按天）
        trends = await self._get_trends(days)

        # 平台分布
        platform_dist = await self._get_platform_distribution(days)

        return {
            "summary": summary,
            "trends": trends,
            "platform_distribution": platform_dist,
            "days": days,
        }

    async def _get_trends(self, days: int) -> List[Dict[str, Any]]:
        """按天趋势(增强版: 含 7 日移动平均 / 环比 / 同比)

        Returns:
            [
                {
                    "date": "2025-01-01",
                    "publish_count": 10,
                    "moving_avg_7d": 8.5,    # 7 日移动平均(含当日)
                    "mom_ratio": 0.25,        # 环比(与前一天比,0.25=+25%)
                    "yoy_ratio": -0.1,        # 同比(与 30 天前比,-0.1=-10%)
                },
                ...
            ]

        说明:
        - moving_avg_7d: 当天与前 6 天(共 7 天)的算术平均
        - mom_ratio: (当天 - 前一天) / max(前一天, 1)
        - yoy_ratio: (当天 - 30天前) / max(30天前, 1), 数据不足时为 None
        """
        engine = await self._get_engine()
        if engine is None:
            return []
        from sqlalchemy import text as sql_text

        # 采集窗口需要多取 30 天,以支持同比计算
        # days=趋势展示天数; extra=30 用于同比前置数据
        total_lookback = days + 30
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today_start - timedelta(days=total_lookback - 1)

        # 按天聚合每日发布量（单次 GROUP BY 查询，替代 N+1 循环）
        daily_counts: List[Dict[str, Any]] = []
        try:
            async with engine.connect() as conn:
                # 一次查询拿到所有天的数据
                window_start_ts = int(window_start.timestamp())
                rows = await conn.execute(
                    sql_text(
                        "SELECT to_timestamp(sent_at)::date as day, COUNT(*) as cnt "
                        "FROM x_twitter_sent_comment "
                        "WHERE sent_at >= :start_ts "
                        "GROUP BY to_timestamp(sent_at)::date "
                        "ORDER BY day"
                    ),
                    {"start_ts": window_start_ts},
                )
                # 构建日期→计数映射
                db_counts = {}
                for r in rows.fetchall():
                    db_counts[r[0].strftime("%Y-%m-%d")] = r[1]

                # 填充每天的数据（包括没有数据的日期）
                for i in range(total_lookback - 1, -1, -1):
                    day = today_start - timedelta(days=i)
                    day_str = day.strftime("%Y-%m-%d")
                    pub_count = db_counts.get(day_str, 0)
                    daily_counts.append(
                        {
                            "date": day_str,
                            "publish_count": pub_count,
                            "_idx": i,  # 距今天数(0=今天)
                        }
                    )
        except Exception as e:
            logger.warning(f"[Analytics] 趋势查询失败: {e}")
            return []

        # 计算移动平均 / 环比 / 同比
        # daily_counts 顺序: 从最早(total_lookback-1 天前)到今天(_idx=0)
        # 我们只需要返回最近 days 天的数据
        trends: List[Dict[str, Any]] = []
        for j, item in enumerate(daily_counts):
            if item["_idx"] >= days:
                continue  # 只返回最近 days 天
            # 7 日移动平均: 当前 j 及前 6 天(共 7 天)
            window_start_j = max(0, j - 6)
            window_items = daily_counts[window_start_j : j + 1]
            window_vals = [w["publish_count"] for w in window_items]
            moving_avg_7d = round(sum(window_vals) / len(window_vals), 2) if window_vals else 0.0

            # 环比: 与前一天比
            mom_ratio: Optional[float] = None
            if j > 0:
                prev_val = daily_counts[j - 1]["publish_count"]
                cur_val = item["publish_count"]
                if prev_val > 0:
                    mom_ratio = round((cur_val - prev_val) / prev_val, 4)
                elif cur_val > 0:
                    mom_ratio = 1.0  # 从 0 增长到非 0 视为 +100%
                else:
                    mom_ratio = 0.0

            # 同比: 与 30 天前比
            yoy_ratio: Optional[float] = None
            if j >= 30:
                prev_val = daily_counts[j - 30]["publish_count"]
                cur_val = item["publish_count"]
                if prev_val > 0:
                    yoy_ratio = round((cur_val - prev_val) / prev_val, 4)
                elif cur_val > 0:
                    yoy_ratio = 1.0
                else:
                    yoy_ratio = 0.0

            trends.append(
                {
                    "date": item["date"],
                    "publish_count": item["publish_count"],
                    "moving_avg_7d": moving_avg_7d,
                    "mom_ratio": mom_ratio,
                    "yoy_ratio": yoy_ratio,
                }
            )
        return trends

    async def get_advanced_trends(self, days: int = 30) -> Dict[str, Any]:
        """高级趋势分析(暴露给 /api/analytics/trends/advanced)

        在 _get_trends 基础上补充汇总信息: 7 日均值/环比变化趋势/异常点标记。
        """
        trends = await self._get_trends(days)
        if not trends:
            return {"trends": [], "summary": {}, "days": days}

        # 汇总: 最近 7 天 vs 上一个 7 天
        last_7 = trends[-7:] if len(trends) >= 7 else trends
        prev_7 = trends[-14:-7] if len(trends) >= 14 else []
        last_7_sum = sum(t["publish_count"] for t in last_7)
        prev_7_sum = sum(t["publish_count"] for t in prev_7) if prev_7 else 0
        week_over_week = (
            round((last_7_sum - prev_7_sum) / prev_7_sum, 4) if prev_7_sum > 0 else None
        )

        # 异常点: mom_ratio 下降超过 50% 或上升超过 200%
        anomalies = [
            {
                "date": t["date"],
                "publish_count": t["publish_count"],
                "mom_ratio": t["mom_ratio"],
                "type": "drop" if (t["mom_ratio"] or 0) < -0.5 else "spike",
            }
            for t in trends
            if t["mom_ratio"] is not None and (t["mom_ratio"] < -0.5 or t["mom_ratio"] > 2.0)
        ]

        return {
            "trends": trends,
            "summary": {
                "last_7d_total": last_7_sum,
                "prev_7d_total": prev_7_sum,
                "week_over_week": week_over_week,
                "anomaly_count": len(anomalies),
            },
            "anomalies": anomalies,
            "days": days,
        }

    async def detect_data_anomaly(self, days: int = 7) -> List[Dict[str, Any]]:
        """数据异常检测: 对比最近 N 天与上一个 N 天的核心指标

        如果某指标环比下降超过 30%,调用 alert_center.emit_data_anomaly 触发预警。
        该方法为 async 且无副作用(除触发预警外),可被定时任务安全调用(P1-10)。

        Args:
            days: 对比窗口天数(默认 7)
        Returns:
            检测到的异常列表 [{metric_name, current_value, baseline_value, drop_pct}, ...]
        """
        engine = await self._get_engine()
        if engine is None:
            return []
        from sqlalchemy import text as sql_text

        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # 当前窗口: [today - days + 1, today]
        cur_start = today_start - timedelta(days=days - 1)
        cur_end = today_start + timedelta(days=1)
        # 基线窗口: [today - 2*days + 1, today - days]
        prev_start = today_start - timedelta(days=2 * days - 1)
        prev_end = cur_start

        # 核心指标定义: (metric_name, sql_template)
        # 每个 sql_template 接收 :s 和 :e 参数(均为秒级时间戳),返回一个标量值
        metrics: List[Dict[str, Any]] = []
        try:
            async with engine.connect() as conn:
                # 1. publish_count: x_twitter_sent_comment 发布量
                for metric_name, sql in [
                    (
                        "publish_count",
                        "SELECT COUNT(*) FROM x_twitter_sent_comment WHERE sent_at>=:s AND sent_at<:e",
                    ),
                    (
                        "interaction_count",
                        "SELECT COUNT(*) FROM x_twitter_sent_comment WHERE sent_at>=:s AND sent_at<:e "
                        "AND (sent_status='success' OR (post_id IS NOT NULL AND post_id!=''))",
                    ),
                ]:
                    try:
                        cur_rows = await conn.execute(
                            sql_text(sql),
                            {"s": int(cur_start.timestamp()), "e": int(cur_end.timestamp())}
                        )
                        cur_val = float(cur_rows.scalar() or 0)
                    except Exception:
                        cur_val = 0.0
                    try:
                        prev_rows = await conn.execute(
                            sql_text(sql),
                            {"s": int(prev_start.timestamp()), "e": int(prev_end.timestamp())}
                        )
                        prev_val = float(prev_rows.scalar() or 0)
                    except Exception:
                        prev_val = 0.0
                    metrics.append({
                        "metric_name": metric_name,
                        "current_value": cur_val,
                        "baseline_value": prev_val,
                    })

                # 3. followers_delta: 粉丝净增量(从 external_metrics 表,如果存在)
                try:
                    cur_rows = await conn.execute(
                        sql_text(
                            "SELECT COALESCE(SUM(followers_delta), 0) FROM external_metrics "
                            "WHERE created_at>=:s AND created_at<:e"
                        ),
                        {"s": cur_start, "e": cur_end},
                    )
                    cur_val = float(cur_rows.scalar() or 0)
                    prev_rows = await conn.execute(
                        sql_text(
                            "SELECT COALESCE(SUM(followers_delta), 0) FROM external_metrics "
                            "WHERE created_at>=:s AND created_at<:e"
                        ),
                        {"s": prev_start, "e": prev_end},
                    )
                    prev_val = float(prev_rows.scalar() or 0)
                    metrics.append({
                        "metric_name": "followers_delta",
                        "current_value": cur_val,
                        "baseline_value": prev_val,
                    })
                except Exception:
                    # external_metrics 表不存在或无 followers_delta 字段,跳过
                    pass
        except Exception as e:
            logger.warning(f"[Analytics] detect_data_anomaly 查询失败: {e}")
            return []

        # 计算环比下降幅度,筛选下降超过 30% 的指标
        anomalies: List[Dict[str, Any]] = []
        for m in metrics:
            cur_val = m["current_value"]
            prev_val = m["baseline_value"]
            if prev_val <= 0:
                # 基线为 0,无法计算百分比下降;若当前也为 0 则无异常,否则视为增长不算下降
                continue
            drop_pct = round((prev_val - cur_val) / prev_val * 100, 1)
            if drop_pct >= 30.0:
                anomaly = {
                    "metric_name": m["metric_name"],
                    "current_value": cur_val,
                    "baseline_value": prev_val,
                    "drop_pct": drop_pct,
                }
                anomalies.append(anomaly)
                # 触发数据异常预警
                try:
                    from ..alert.alert_center import emit_data_anomaly
                    await emit_data_anomaly(
                        metric_name=m["metric_name"],
                        current_value=cur_val,
                        baseline_value=prev_val,
                        drop_pct=drop_pct,
                    )
                    logger.info(
                        f"[Analytics] 数据异常预警已触发: {m['metric_name']} 下降 {drop_pct}%"
                    )
                except Exception as e:
                    logger.warning(f"[Analytics] emit_data_anomaly 调用失败: {e}")

        if anomalies:
            logger.info(f"[Analytics] detect_data_anomaly 检测到 {len(anomalies)} 个异常指标")
        return anomalies

    async def _get_platform_distribution(self, days: int) -> List[Dict[str, Any]]:
        """平台分布"""
        engine = await self._get_engine()
        if engine is None:
            return []
        from sqlalchemy import text as sql_text

        now = datetime.utcnow()
        since = now - timedelta(days=days)
        since_ts = int(since.timestamp())
        try:
            async with engine.connect() as conn:
                # x_twitter_sent_comment 表（X 平台固定，platform='x_twitter'）
                try:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) as cnt FROM x_twitter_sent_comment "
                            "WHERE sent_at>=:s"
                        ),
                        {"s": since_ts},
                    )
                    cnt = rows.scalar() or 0
                    return [{"platform": "x_twitter", "count": cnt}]
                except Exception:
                    return []
        except Exception:
            return []

    async def get_platform_comparison(self, days: int = 30) -> Dict[str, Any]:
        """平台对比分析"""
        engine = await self._get_engine()
        if engine is None:
            return {}
        from sqlalchemy import text as sql_text

        now = datetime.utcnow()
        since = now - timedelta(days=days)
        since_ts = int(since.timestamp())
        try:
            async with engine.connect() as conn:
                try:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) as total, "
                            "SUM(CASE WHEN sent_status='success' OR "
                            "(post_id IS NOT NULL AND post_id!='') THEN 1 ELSE 0 END) as success "
                            "FROM x_twitter_sent_comment WHERE sent_at>=:s"
                        ),
                        {"s": since_ts},
                    )
                    platforms = []
                    r = rows.fetchone()
                    if r:
                        total = r[0] or 0
                        success = r[1] or 0
                        platforms.append(
                            {
                                "platform": "x_twitter",
                                "total": total,
                                "success": success,
                                "success_rate": round(success / total * 100, 1) if total else 0.0,
                            }
                        )
                    return {"platforms": platforms, "days": days}
                except Exception:
                    return {"platforms": [], "days": days}
        except Exception:
            return {"platforms": [], "days": days}

    async def get_content_performance(self, limit: int = 20) -> Dict[str, Any]:
        """内容表现排行"""
        engine = await self._get_engine()
        if engine is None:
            return {}
        from sqlalchemy import text as sql_text

        try:
            async with engine.connect() as conn:
                try:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, comment_content, post_id, sent_at, reply_count, auto_replied_count "
                            "FROM x_twitter_sent_comment "
                            "WHERE comment_content IS NOT NULL AND comment_content != '' "
                            "ORDER BY id DESC LIMIT :l"
                        ),
                        {"l": limit},
                    )
                    items = [
                        {
                            "id": r[0],
                            "content_preview": (r[1] or "")[:80],
                            "tweet_id": r[2],
                            "created_at": str(r[3]) if r[3] else None,
                            "reply_count": r[4] or 0,
                            "auto_replied_count": r[5] or 0,
                        }
                        for r in rows.fetchall()
                    ]
                    return {"items": items, "count": len(items)}
                except Exception:
                    return {"items": [], "count": 0}
        except Exception:
            return {"items": [], "count": 0}


_analytics: Optional[AnalyticsService] = None


def get_analytics_service() -> AnalyticsService:
    global _analytics
    if _analytics is None:
        _analytics = AnalyticsService()
    return _analytics
