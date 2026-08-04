# -*- coding: utf-8 -*-
"""
爆款内容识别 + 复盘报告生成

阶段三 P2 任务 3.2：补齐 PRD 5.5 爆款内容复盘。

核心能力：
1. 爆款识别：基于互动量增速、互动率、播放完成率
   - 阈值：互动率 > 平台 P90 + 增速 > 3x
2. 复盘报告：自动生成（热点溯源、内容要素、发布时机、互动节奏、AI 总结）
3. 持久化到 viral_review_reports 表
4. AI 总结调用 ai_service
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ViralContent:
    """爆款内容"""
    content_id: str = ""
    platform: str = ""
    post_url: str = ""
    title: str = ""
    published_at: Optional[str] = None
    # 互动数据
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    collects: int = 0
    # 爆款指标
    interaction_rate: float = 0.0   # 互动率
    growth_velocity: float = 0.0    # 增速（倍数）
    is_viral: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ViralReviewReport:
    """爆款复盘报告"""
    report_id: str = ""
    content_id: str = ""
    platform: str = ""
    post_url: str = ""
    title: str = ""
    # 复盘要素
    hotspot_source: str = ""         # 热点溯源
    content_elements: List[str] = field(default_factory=list)  # 内容要素
    publish_timing: str = ""          # 发布时机分析
    interaction_rhythm: str = ""      # 互动节奏分析
    ai_summary: str = ""              # AI 总结
    key_takeaways: List[str] = field(default_factory=list)  # 关键经验
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ViralDetector:
    """爆款识别器"""

    # 各平台互动率 P90 阈值（参考值，可调）
    PLATFORM_P90_THRESHOLDS = {
        "douyin": 0.08,           # 8% 互动率
        "xiaohongshu": 0.10,
        "bilibili": 0.06,
        "weibo": 0.05,
        "zhihu": 0.15,
        "kuaishou": 0.07,
        "x_twitter_publisher": 0.04,
        "tiktok": 0.10,
        "instagram": 0.07,
        "youtube": 0.05,
        "facebook": 0.04,
    }
    GROWTH_VELOCITY_THRESHOLD = 3.0   # 增速 >= 3 倍视为爆款

    def detect(
        self, content: ViralContent, platform: str = ""
    ) -> ViralContent:
        """识别爆款内容"""
        platform = platform or content.platform
        threshold = self.PLATFORM_P90_THRESHOLDS.get(platform, 0.05)
        content.is_viral = (
            content.interaction_rate >= threshold
            and content.growth_velocity >= self.GROWTH_VELOCITY_THRESHOLD
        )
        return content

    def detect_batch(
        self, contents: List[ViralContent], platform: str = ""
    ) -> List[ViralContent]:
        """批量识别爆款"""
        return [self.detect(c, platform) for c in contents]


class ViralReviewService:
    """爆款复盘服务"""

    _ensured = False  # DDL 仅首次执行一次，避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if ViralReviewService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS viral_review_reports ("
                        "  report_id VARCHAR(64) PRIMARY KEY,"
                        "  content_id VARCHAR(64),"
                        "  platform VARCHAR(32),"
                        "  post_url TEXT,"
                        "  title TEXT,"
                        "  hotspot_source TEXT,"
                        "  content_elements TEXT,"
                        "  publish_timing TEXT,"
                        "  interaction_rhythm TEXT,"
                        "  ai_summary TEXT,"
                        "  key_takeaways TEXT,"
                        "  metadata TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW())"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_viral_review_platform "
                        "ON viral_review_reports(platform, created_at)"
                    )
                )
            ViralReviewService._ensured = True
        except Exception as e:
            logger.warning(f"[ViralReview] ensure_table failed: {e}")

    async def generate_review(
        self, content: ViralContent,
        *,
        hotspot_source: str = "",
        use_ai: bool = True,
    ) -> ViralReviewReport:
        """生成爆款复盘报告"""
        report = ViralReviewReport(
            report_id=f"vr_{uuid.uuid4().hex[:12]}",
            content_id=content.content_id,
            platform=content.platform,
            post_url=content.post_url,
            title=content.title,
            hotspot_source=hotspot_source or "未知热点来源",
            content_elements=self._extract_content_elements(content),
            publish_timing=self._analyze_publish_timing(content),
            interaction_rhythm=self._analyze_interaction_rhythm(content),
            created_at=datetime.utcnow().isoformat(),
            metadata={"interaction_rate": content.interaction_rate,
                      "growth_velocity": content.growth_velocity},
        )

        # AI 总结
        if use_ai:
            try:
                report.ai_summary = await self._ai_summarize(content, report)
                report.key_takeaways = self._extract_takeaways(report.ai_summary)
            except Exception as e:
                logger.warning(f"[ViralReview] AI 总结失败: {e}")
                report.ai_summary = self._rule_based_summary(content)
                report.key_takeaways = ["（AI 总结失败，请人工补充）"]

        await self._save_report(report)
        return report

    def _extract_content_elements(self, content: ViralContent) -> List[str]:
        """提取内容要素"""
        elements = []
        if content.title:
            elements.append(f"标题：{content.title[:50]}")
        if content.views > 10000:
            elements.append(f"播放量：{content.views:,}（万级以上）")
        if content.interaction_rate > 0.1:
            elements.append(f"互动率：{content.interaction_rate:.1%}（高于平均）")
        if content.growth_velocity > 5:
            elements.append(f"增速：{content.growth_velocity:.1f}x（爆发式增长）")
        return elements

    def _analyze_publish_timing(self, content: ViralContent) -> str:
        """分析发布时机"""
        if not content.published_at:
            return "发布时间未知"
        try:
            from api.services.scheduling.peak_hours import get_peak_hours_service
            svc = get_peak_hours_service()
            dt = datetime.fromisoformat(content.published_at)
            is_peak = svc.is_peak_now(content.platform, dt)
            return (
                f"发布于 {content.published_at} "
                f"({'活跃时段' if is_peak else '非活跃时段'})"
            )
        except Exception:
            return f"发布于 {content.published_at}"

    def _analyze_interaction_rhythm(self, content: ViralContent) -> str:
        """分析互动节奏"""
        total = content.likes + content.comments + content.shares + content.collects
        if total == 0:
            return "无互动数据"
        like_ratio = content.likes / total
        comment_ratio = content.comments / total
        share_ratio = content.shares / total
        return (
            f"点赞占比 {like_ratio:.1%}，"
            f"评论占比 {comment_ratio:.1%}，"
            f"转发占比 {share_ratio:.1%}"
        )

    async def _ai_summarize(
        self, content: ViralContent, report: ViralReviewReport
    ) -> str:
        """调用 AI 生成复盘总结"""
        from api.services.ai_service import get_ai_service
        svc = get_ai_service()
        prompt = (
            "请基于以下爆款内容数据生成一份复盘总结（200-300 字）：\n"
            f"平台：{content.platform}\n"
            f"标题：{content.title}\n"
            f"播放量：{content.views}\n"
            f"互动率：{content.interaction_rate:.2%}\n"
            f"增速：{content.growth_velocity:.1f}x\n"
            f"内容要素：{', '.join(report.content_elements)}\n"
            f"发布时机：{report.publish_timing}\n"
            f"互动节奏：{report.interaction_rhythm}\n\n"
            "总结应包含：1) 为什么爆 2) 可复用的经验 3) 改进建议"
        )
        return await svc.generate_text(prompt) or ""

    def _rule_based_summary(self, content: ViralContent) -> str:
        """规则兜底总结"""
        return (
            f"该内容在 {content.platform} 平台获得 {content.views:,} 播放，"
            f"互动率 {content.interaction_rate:.1%}，"
            f"增速 {content.growth_velocity:.1f}x。"
            f"内容要素：{', '.join(self._extract_content_elements(content))}。"
            "建议复用类似内容方向。"
        )

    def _extract_takeaways(self, ai_summary: str) -> List[str]:
        """从 AI 总结提取关键经验（简单分句）"""
        if not ai_summary:
            return []
        # 按句号/换行拆分，取前 5 条
        sentences = []
        for s in ai_summary.replace("。", ".\n").replace("；", ";\n").split("\n"):
            s = s.strip()
            if s and len(s) > 5:
                sentences.append(s)
        return sentences[:5]

    # ============ 持久化 ============

    async def _save_report(self, report: ViralReviewReport) -> None:
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO viral_review_reports "
                        "(report_id, content_id, platform, post_url, title, "
                        " hotspot_source, content_elements, publish_timing, "
                        " interaction_rhythm, ai_summary, key_takeaways, "
                        " metadata, created_at) "
                        "VALUES (:rid, :cid, :pf, :pu, :t, :hs, :ce, :pt, :ir, :as, :kt, :md, :ca) "
                        "ON CONFLICT (report_id) DO UPDATE SET "
                        " ai_summary = EXCLUDED.ai_summary, "
                        " key_takeaways = EXCLUDED.key_takeaways"
                    ),
                    {
                        "rid": report.report_id,
                        "cid": report.content_id,
                        "pf": report.platform,
                        "pu": report.post_url,
                        "t": report.title,
                        "hs": report.hotspot_source,
                        "ce": json.dumps(report.content_elements, ensure_ascii=False),
                        "pt": report.publish_timing,
                        "ir": report.interaction_rhythm,
                        "as": report.ai_summary,
                        "kt": json.dumps(report.key_takeaways, ensure_ascii=False),
                        "md": json.dumps(report.metadata, ensure_ascii=False),
                        "ca": report.created_at,
                    },
                )
        except Exception as e:
            logger.warning(f"[ViralReview] _save_report failed: {e}")

    async def list_reports(
        self, platform: Optional[str] = None, days: int = 30, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return []
            async with engine.connect() as conn:
                sql = (
                    "SELECT * FROM viral_review_reports "
                    "WHERE created_at >= CURRENT_DATE - :days"
                )
                params: Dict[str, Any] = {"days": days, "limit": limit}
                if platform:
                    sql += " AND platform = :pf"
                    params["pf"] = platform
                sql += " ORDER BY created_at DESC LIMIT :limit"
                rows = await conn.execute(sql_text(sql), params)
                result = []
                for r in rows.fetchall():
                    try:
                        ce = json.loads(r[6]) if r[6] else []
                        kt = json.loads(r[10]) if r[10] else []
                        md = json.loads(r[11]) if r[11] else {}
                    except Exception:
                        ce, kt, md = [], [], {}
                    result.append({
                        "report_id": r[0], "content_id": r[1],
                        "platform": r[2], "post_url": r[3], "title": r[4],
                        "hotspot_source": r[5], "content_elements": ce,
                        "publish_timing": r[7], "interaction_rhythm": r[8],
                        "ai_summary": r[9], "key_takeaways": kt,
                        "metadata": md, "created_at": str(r[12]) if r[12] else "",
                    })
                return result
        except Exception as e:
            logger.warning(f"[ViralReview] list_reports failed: {e}")
            return []

    async def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        reports = await self.list_reports(limit=1000)
        for r in reports:
            if r.get("report_id") == report_id:
                return r
        return None


# ============ 单例 ============

_detector: Optional[ViralDetector] = None
_service: Optional[ViralReviewService] = None


def get_viral_detector() -> ViralDetector:
    global _detector
    if _detector is None:
        _detector = ViralDetector()
    return _detector


def get_viral_review_service() -> ViralReviewService:
    global _service
    if _service is None:
        _service = ViralReviewService()
    return _service
