# -*- coding: utf-8 -*-
"""
品牌诊断服务

迁移自 GEO-main/geo_system/backend/brand_diagnosis_service.py，适配 MediaCrawler。
快速扫描品牌在 AI 平台的收录情况、识别可见度盲点、评估舆情风险。

适配点：
1. 数据库：原 sqlite3 同步 → PostgreSQL 异步（database.db_session.get_async_engine）
2. 配置：原硬编码 db_path → 复用 config.SAVE_DATA_OPTION；AI 平台/搜索引擎清单
   通过环境变量注入，避免硬编码
3. 日志：原 print → logging.getLogger(__name__)
4. 异步化：所有诊断与持久化方法改为 async def
5. 建表：原 init_database() → ensure_table()，使用 CREATE TABLE IF NOT EXISTS
6. 单例：提供 get_brand_diagnosis_service() 工厂函数

对应 PRD 5.3 品牌诊断 - AI 平台收录检测 / 可见度盲点识别 / 舆情风险评估。
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# 可配置的 AI 平台清单（环境变量逗号分隔），默认覆盖豆包/DeepSeek/Kimi/通义千问
DEFAULT_AI_PLATFORMS = "豆包,DeepSeek,Kimi,通义千问"
# 可配置的搜索引擎清单
DEFAULT_SEARCH_ENGINES = "百度,搜狗,360搜索"


class DiagnosisDimension(str, Enum):
    """诊断维度"""
    AI_VISIBILITY = "ai_visibility"        # AI可见度
    SEARCH_PRESENCE = "search_presence"    # 搜索表现
    CONTENT_QUALITY = "content_quality"    # 内容质量
    SENTIMENT = "sentiment"                # 舆情情感
    COMPETITIVE = "competitive"            # 竞争态势


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"           # 低风险
    MEDIUM = "medium"     # 中风险
    HIGH = "high"         # 高风险
    CRITICAL = "critical" # 严重


@dataclass
class DiagnosisItem:
    """诊断项"""
    dimension: str
    name: str
    score: int                    # 0-100
    status: str                   # good/warning/danger
    findings: List[str] = field(default_factory=list)           # 发现的问题
    recommendations: List[str] = field(default_factory=list)    # 改进建议
    risk_level: str = RiskLevel.LOW.value                        # low/medium/high/critical


@dataclass
class BrandDiagnosisReport:
    """品牌诊断报告"""
    id: Optional[int]
    brand_name: str
    website: Optional[str]
    industry: Optional[str]
    overall_score: int            # 综合得分
    ai_visibility_score: int      # AI可见度得分
    search_score: int             # 搜索得分
    content_score: int            # 内容得分
    sentiment_score: int          # 舆情得分
    competitive_score: int        # 竞争得分
    diagnosis_items: List[DiagnosisItem] = field(default_factory=list)
    blind_spots: List[str] = field(default_factory=list)         # 可见度盲点
    risk_areas: List[str] = field(default_factory=list)          # 风险区域
    opportunities: List[str] = field(default_factory=list)       # 机会点
    action_plan: List[Dict[str, Any]] = field(default_factory=list)  # 行动计划
    created_at: Optional[datetime] = None


class BrandDiagnosisService:
    """品牌诊断服务（异步，PostgreSQL）"""

    def __init__(self):
        # 配置通过环境变量注入，避免硬编码
        self._ai_platforms = [
            p.strip() for p in os.environ.get(
                "BRAND_DIAGNOSIS_AI_PLATFORMS", DEFAULT_AI_PLATFORMS
            ).split(",") if p.strip()
        ]
        self._search_engines = [
            e.strip() for e in os.environ.get(
                "BRAND_DIAGNOSIS_SEARCH_ENGINES", DEFAULT_SEARCH_ENGINES
            ).split(",") if e.strip()
        ]

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    # ------------------------------------------------------------------
    # 基础设施层
    # ------------------------------------------------------------------
    def _get_engine(self):
        """获取异步数据库 engine（复用 MediaCrawler 的连接池）"""
        try:
            from database.db_session import get_async_engine
            import config
            return get_async_engine(config.SAVE_DATA_OPTION)
        except Exception as e:
            logger.warning(f"[BrandDiagnosis] 获取 engine 失败: {e}")
            return None

    async def ensure_table(self):
        """确保诊断相关表存在（PostgreSQL，CREATE TABLE IF NOT EXISTS）"""
        if BrandDiagnosisService._ensured:
            return
        engine = self._get_engine()
        if engine is None:
            return
        try:
            from sqlalchemy import text as sql_text
            async with engine.begin() as conn:
                # 诊断报告表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS diagnosis_reports ("
                        "  id SERIAL PRIMARY KEY,"
                        "  brand_name VARCHAR(128) NOT NULL,"
                        "  website VARCHAR(256),"
                        "  industry VARCHAR(128),"
                        "  overall_score INTEGER,"
                        "  ai_visibility_score INTEGER,"
                        "  search_score INTEGER,"
                        "  content_score INTEGER,"
                        "  sentiment_score INTEGER,"
                        "  competitive_score INTEGER,"
                        "  report_data TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
                # 诊断历史表（按维度记录，便于趋势分析）
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS diagnosis_history ("
                        "  id SERIAL PRIMARY KEY,"
                        "  brand_name VARCHAR(128) NOT NULL,"
                        "  dimension VARCHAR(32),"
                        "  score INTEGER,"
                        "  findings TEXT,"
                        "  created_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
                # 常用查询索引
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS ix_diagnosis_reports_brand_name "
                        "ON diagnosis_reports (brand_name)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS ix_diagnosis_reports_created_at "
                        "ON diagnosis_reports (created_at)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS ix_diagnosis_history_brand_name "
                        "ON diagnosis_history (brand_name)"
                    )
                )
            BrandDiagnosisService._ensured = True
        except Exception as e:
            logger.warning(f"[BrandDiagnosis] 建表失败: {e}")

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    async def run_full_diagnosis(
        self,
        brand_name: str,
        website: Optional[str] = None,
        industry: Optional[str] = None,
        keywords: Optional[List[str]] = None,
    ) -> BrandDiagnosisReport:
        """运行完整品牌诊断

        Args:
            brand_name: 品牌名称
            website: 品牌官网
            industry: 所属行业
            keywords: 诊断关键词列表（为空时使用默认推荐词）
        """
        if not brand_name:
            raise ValueError("brand_name 不能为空")

        if keywords is None:
            keywords = [f"{brand_name}怎么样", f"{brand_name}好不好", f"{brand_name}推荐"]

        # 执行各维度诊断
        ai_visibility = await self._diagnose_ai_visibility(brand_name, keywords)
        search_presence = await self._diagnose_search_presence(brand_name, website, keywords)
        content_quality = await self._diagnose_content_quality(brand_name, website)
        sentiment = await self._diagnose_sentiment(brand_name, keywords)
        competitive = await self._diagnose_competitive(brand_name, industry)

        # 计算综合得分
        scores = [
            ai_visibility.score,
            search_presence.score,
            content_quality.score,
            sentiment.score,
            competitive.score,
        ]
        overall_score = sum(scores) // len(scores) if scores else 0

        # 识别盲点 / 风险 / 机会
        blind_spots = self._identify_blind_spots(ai_visibility, search_presence)
        risk_areas = self._identify_risks(sentiment, competitive)
        opportunities = self._identify_opportunities(ai_visibility, competitive)
        action_plan = self._generate_action_plan(
            ai_visibility, search_presence, content_quality, sentiment, competitive
        )

        report = BrandDiagnosisReport(
            id=None,
            brand_name=brand_name,
            website=website,
            industry=industry,
            overall_score=overall_score,
            ai_visibility_score=ai_visibility.score,
            search_score=search_presence.score,
            content_score=content_quality.score,
            sentiment_score=sentiment.score,
            competitive_score=competitive.score,
            diagnosis_items=[ai_visibility, search_presence, content_quality, sentiment, competitive],
            blind_spots=blind_spots,
            risk_areas=risk_areas,
            opportunities=opportunities,
            action_plan=action_plan,
            created_at=datetime.utcnow(),
        )

        # 持久化报告
        await self._save_report(report)

        return report

    # ------------------------------------------------------------------
    # 各维度诊断（保留原逻辑：AI 收录检测 / 搜索表现 / 内容质量 / 舆情 / 竞争）
    # ------------------------------------------------------------------
    async def _diagnose_ai_visibility(
        self, brand_name: str, keywords: List[str]
    ) -> DiagnosisItem:
        """诊断 AI 可见度：检查品牌在各 AI 平台的收录情况"""
        findings: List[str] = []
        recommendations: List[str] = []

        platforms = self._ai_platforms or ["豆包", "DeepSeek", "Kimi", "通义千问"]
        mentioned_count = 0

        for platform in platforms:
            # TODO: 此处应接入真实 AI 平台 API 检查品牌收录情况
            # 目前使用启发式规则：前两个平台默认已收录，便于演示
            if platform in platforms[:2]:
                mentioned_count += 1
                findings.append(f"✅ {platform}: 已收录品牌信息")
            else:
                findings.append(f"⚠️ {platform}: 品牌提及较少")

        mention_rate = (mentioned_count / len(platforms)) * 100 if platforms else 0

        if mention_rate >= 75:
            score = 80 + (mention_rate - 75) // 5
            status = "good"
            risk = RiskLevel.LOW
        elif mention_rate >= 50:
            score = 60 + (mention_rate - 50) // 2
            status = "warning"
            risk = RiskLevel.MEDIUM
            recommendations.append("增加在 Kimi 和通义千问平台的内容投放")
        else:
            score = mention_rate
            status = "danger"
            risk = RiskLevel.HIGH
            recommendations.append("urgently 需要加强 AI 平台内容建设")
            recommendations.append("创建更多 GEO 优化内容")

        score = min(100, max(0, int(score)))

        return DiagnosisItem(
            dimension=DiagnosisDimension.AI_VISIBILITY.value,
            name="AI可见度",
            score=score,
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value,
        )

    async def _diagnose_search_presence(
        self, brand_name: str, website: Optional[str], keywords: List[str]
    ) -> DiagnosisItem:
        """诊断搜索表现：检查品牌在主流搜索引擎的排名"""
        findings: List[str] = []
        recommendations: List[str] = []

        search_engines = self._search_engines or ["百度", "搜狗", "360搜索"]
        avg_rank = 0

        for engine in search_engines:
            # TODO: 此处应接入真实搜索排名抓取
            # 目前使用启发式占位值
            rank = 5
            avg_rank += rank
            if rank <= 3:
                findings.append(f"✅ {engine}: 排名靠前(第{rank}位)")
            elif rank <= 10:
                findings.append(f"⚠️ {engine}: 排名中等(第{rank}位)")
            else:
                findings.append(f"❌ {engine}: 排名靠后(第{rank}位)")

        avg_rank = avg_rank / len(search_engines) if search_engines else 0

        if avg_rank <= 3:
            score = 90
            status = "good"
            risk = RiskLevel.LOW
        elif avg_rank <= 8:
            score = 70
            status = "warning"
            risk = RiskLevel.MEDIUM
            recommendations.append("优化 SEO，提升核心关键词排名")
        else:
            score = 50
            status = "danger"
            risk = RiskLevel.HIGH
            recommendations.append("urgently 需要 SEO 优化")
            recommendations.append("增加高质量外链建设")

        return DiagnosisItem(
            dimension=DiagnosisDimension.SEARCH_PRESENCE.value,
            name="搜索表现",
            score=score,
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value,
        )

    async def _diagnose_content_quality(
        self, brand_name: str, website: Optional[str]
    ) -> DiagnosisItem:
        """诊断内容质量：检查文章数量、字数、Schema 标记、FAQ、新鲜度"""
        findings: List[str] = []
        recommendations: List[str] = []

        # TODO: 接入真实内容审计（如抓取官网 sitemap、解析 Schema）
        content_metrics = {
            "total_articles": 15,
            "avg_length": 1800,
            "schema_markup": False,
            "faq_count": 5,
            "freshness": "3个月前更新",
        }

        findings.append(f"📄 现有内容: {content_metrics['total_articles']} 篇文章")
        findings.append(f"✍️ 平均字数: {content_metrics['avg_length']} 字")

        if content_metrics["avg_length"] >= 1500:
            score = 70
        else:
            score = 50
            recommendations.append("增加文章深度，建议每篇 1500 字以上")

        if not content_metrics["schema_markup"]:
            findings.append("❌ 缺少 Schema 结构化标记")
            recommendations.append("添加 Schema.org 结构化数据")
            score -= 10
        else:
            findings.append("✅ 已配置 Schema 标记")

        if content_metrics["faq_count"] < 10:
            findings.append(f"⚠️ FAQ 数量较少({content_metrics['faq_count']}个)")
            recommendations.append("扩充 FAQ 内容至 20 个以上")
            score -= 10

        if "3个月" in content_metrics["freshness"]:
            findings.append("⚠️ 内容更新不够及时")
            recommendations.append("建立内容更新机制，保持每周更新")
            score -= 10

        score = max(0, min(100, score))
        status = "good" if score >= 70 else "warning" if score >= 50 else "danger"
        risk = (
            RiskLevel.LOW if score >= 70
            else RiskLevel.MEDIUM if score >= 50
            else RiskLevel.HIGH
        )

        return DiagnosisItem(
            dimension=DiagnosisDimension.CONTENT_QUALITY.value,
            name="内容质量",
            score=score,
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value,
        )

    async def _diagnose_sentiment(
        self, brand_name: str, keywords: List[str]
    ) -> DiagnosisItem:
        """诊断舆情情感：分析正/中/负面评价占比"""
        findings: List[str] = []
        recommendations: List[str] = []

        # TODO: 接入真实舆情数据（如 moderation 服务、第三方舆情 API）
        sentiment_data = {
            "positive": 65,
            "neutral": 25,
            "negative": 10,
        }

        findings.append(f"😊 正面评价: {sentiment_data['positive']}%")
        findings.append(f"😐 中性评价: {sentiment_data['neutral']}%")
        findings.append(f"😟 负面评价: {sentiment_data['negative']}%")

        score = sentiment_data["positive"] + sentiment_data["neutral"] * 0.5

        if sentiment_data["negative"] > 20:
            status = "danger"
            risk = RiskLevel.HIGH
            recommendations.append("urgently 需要舆情危机处理")
            findings.append("❌ 负面舆情占比较高，需关注")
        elif sentiment_data["negative"] > 10:
            status = "warning"
            risk = RiskLevel.MEDIUM
            recommendations.append("监控负面评价，及时回应")
        else:
            status = "good"
            risk = RiskLevel.LOW
            findings.append("✅ 品牌舆情整体健康")

        return DiagnosisItem(
            dimension=DiagnosisDimension.SENTIMENT.value,
            name="舆情情感",
            score=int(score),
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value,
        )

    async def _diagnose_competitive(
        self, brand_name: str, industry: Optional[str]
    ) -> DiagnosisItem:
        """诊断竞争态势：分析市场份额与主要竞品"""
        findings: List[str] = []
        recommendations: List[str] = []

        # TODO: 接入真实竞品分析数据源
        competitors = ["欧派", "索菲亚", "尚品宅配"]
        findings.append(f"🏆 主要竞品: {', '.join(competitors)}")

        market_share = 8  # 启发式占位：假设市场份额 8%
        findings.append(f"📊 预估市场份额: {market_share}%")

        if market_share >= 15:
            score = 85
            status = "good"
            risk = RiskLevel.LOW
            findings.append("✅ 市场地位稳固")
        elif market_share >= 8:
            score = 65
            status = "warning"
            risk = RiskLevel.MEDIUM
            findings.append("⚠️ 市场份额有待提升")
            recommendations.append("加强差异化定位")
            recommendations.append("增加品牌曝光度")
        else:
            score = 40
            status = "danger"
            risk = RiskLevel.HIGH
            findings.append("❌ 市场份额较低")
            recommendations.append("urgently 需要市场突破策略")
            recommendations.append("考虑价格战或差异化竞争")

        return DiagnosisItem(
            dimension=DiagnosisDimension.COMPETITIVE.value,
            name="竞争态势",
            score=score,
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value,
        )

    # ------------------------------------------------------------------
    # 报告组装辅助方法（纯函数，保留原逻辑）
    # ------------------------------------------------------------------
    def _identify_blind_spots(
        self, ai_visibility: DiagnosisItem, search_presence: DiagnosisItem
    ) -> List[str]:
        """识别可见度盲点"""
        blind_spots: List[str] = []
        if ai_visibility.score < 70:
            blind_spots.append("AI平台覆盖不足，豆包、DeepSeek等平台缺乏品牌内容")
            blind_spots.append("GEO优化内容缺失，AI难以引用品牌信息")
        if search_presence.score < 70:
            blind_spots.append("长尾关键词覆盖不足")
            blind_spots.append("本地搜索优化缺失")
        return blind_spots

    def _identify_risks(
        self, sentiment: DiagnosisItem, competitive: DiagnosisItem
    ) -> List[str]:
        """识别风险区域"""
        risks: List[str] = []
        if sentiment.risk_level in (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value):
            risks.append("负面舆情风险：存在较多负面评价")
        if competitive.risk_level in (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value):
            risks.append("竞争风险：市场份额较低，面临被边缘化风险")
        return risks

    def _identify_opportunities(
        self, ai_visibility: DiagnosisItem, competitive: DiagnosisItem
    ) -> List[str]:
        """发现机会点"""
        opportunities: List[str] = []
        if ai_visibility.score < 60:
            opportunities.append("AI搜索红利期：抢先布局GEO优化，建立AI推荐优势")
            opportunities.append("内容空白领域：竞品在AI平台内容较少，有超车机会")
        if competitive.score < 70:
            opportunities.append("差异化定位：避开头部竞品正面竞争")
            opportunities.append("细分市场：专注特定人群或场景")
        return opportunities

    def _generate_action_plan(
        self,
        ai_visibility: DiagnosisItem,
        search_presence: DiagnosisItem,
        content_quality: DiagnosisItem,
        sentiment: DiagnosisItem,
        competitive: DiagnosisItem,
    ) -> List[Dict[str, Any]]:
        """生成行动计划"""
        actions: List[Dict[str, Any]] = []

        # 紧急行动
        if sentiment.risk_level == RiskLevel.HIGH.value:
            actions.append({
                "priority": "urgent",
                "action": "舆情危机处理",
                "description": "回应负面评价，发布正面内容",
                "timeline": "1周内",
            })

        # 高优先级
        if ai_visibility.score < 70:
            actions.append({
                "priority": "high",
                "action": "GEO内容建设",
                "description": "创建20篇GEO优化文章和FAQ",
                "timeline": "2周内",
            })

        if content_quality.score < 70:
            actions.append({
                "priority": "high",
                "action": "内容质量提升",
                "description": "添加Schema标记，扩充FAQ，优化现有内容",
                "timeline": "3周内",
            })

        # 中优先级
        if search_presence.score < 70:
            actions.append({
                "priority": "medium",
                "action": "SEO优化",
                "description": "关键词优化，外链建设",
                "timeline": "1个月内",
            })

        # 长期行动
        actions.append({
            "priority": "low",
            "action": "持续监测",
            "description": "建立品牌监测体系，定期诊断",
            "timeline": "持续进行",
        })

        return actions

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    async def _save_report(self, report: BrandDiagnosisReport) -> None:
        """保存诊断报告到 PostgreSQL"""
        await self.ensure_table()
        engine = self._get_engine()
        if engine is None:
            logger.warning("[BrandDiagnosis] engine 不可用，跳过保存")
            return

        from sqlalchemy import text as sql_text

        report_data = json.dumps({
            "diagnosis_items": [asdict(item) for item in report.diagnosis_items],
            "blind_spots": report.blind_spots,
            "risk_areas": report.risk_areas,
            "opportunities": report.opportunities,
            "action_plan": report.action_plan,
        }, ensure_ascii=False)

        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    sql_text(
                        "INSERT INTO diagnosis_reports "
                        "(brand_name, website, industry, overall_score, "
                        " ai_visibility_score, search_score, content_score, "
                        " sentiment_score, competitive_score, report_data) "
                        "VALUES (:brand_name, :website, :industry, :overall_score, "
                        " :ai_visibility_score, :search_score, :content_score, "
                        " :sentiment_score, :competitive_score, :report_data) "
                        "RETURNING id"
                    ),
                    {
                        "brand_name": report.brand_name,
                        "website": report.website,
                        "industry": report.industry,
                        "overall_score": report.overall_score,
                        "ai_visibility_score": report.ai_visibility_score,
                        "search_score": report.search_score,
                        "content_score": report.content_score,
                        "sentiment_score": report.sentiment_score,
                        "competitive_score": report.competitive_score,
                        "report_data": report_data,
                    },
                )
                row = result.fetchone()
                if row:
                    report.id = row[0]

                # 同步写入维度历史，便于趋势分析
                for item in report.diagnosis_items:
                    await conn.execute(
                        sql_text(
                            "INSERT INTO diagnosis_history "
                            "(brand_name, dimension, score, findings) "
                            "VALUES (:brand_name, :dimension, :score, :findings)"
                        ),
                        {
                            "brand_name": report.brand_name,
                            "dimension": item.dimension,
                            "score": item.score,
                            "findings": json.dumps(item.findings, ensure_ascii=False),
                        },
                    )
        except Exception as e:
            logger.warning(f"[BrandDiagnosis] 保存报告失败: {e}")

    async def get_report_history(
        self, brand_name: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取诊断历史"""
        await self.ensure_table()
        engine = self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, brand_name, website, industry, overall_score, "
                        "       ai_visibility_score, search_score, content_score, "
                        "       sentiment_score, competitive_score, report_data, created_at "
                        "FROM diagnosis_reports "
                        "WHERE brand_name = :brand_name "
                        "ORDER BY created_at DESC "
                        "LIMIT :limit"
                    ),
                    {"brand_name": brand_name, "limit": limit},
                )
                columns = list(rows.keys())
                reports: List[Dict[str, Any]] = []
                for row in rows.fetchall():
                    report_dict = dict(zip(columns, row))
                    if report_dict.get("report_data"):
                        try:
                            report_dict["report_data"] = json.loads(
                                report_dict["report_data"]
                            )
                        except (TypeError, ValueError):
                            pass
                    if report_dict.get("created_at"):
                        report_dict["created_at"] = str(report_dict["created_at"])
                    reports.append(report_dict)
                return reports
        except Exception as e:
            logger.warning(f"[BrandDiagnosis] 获取历史失败: {e}")
            return []

    async def get_score_trend(
        self, brand_name: str, days: int = 30
    ) -> List[Dict[str, Any]]:
        """获取得分趋势

        原实现使用 SQLite 的 datetime('now', '-X days')，已替换为
        Python 端计算时间窗口并参数化传入，兼容 PostgreSQL。
        """
        await self.ensure_table()
        engine = self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        since = datetime.utcnow() - timedelta(days=days)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT created_at, overall_score, ai_visibility_score "
                        "FROM diagnosis_reports "
                        "WHERE brand_name = :brand_name AND created_at >= :since "
                        "ORDER BY created_at ASC"
                    ),
                    {"brand_name": brand_name, "since": since},
                )
                trends: List[Dict[str, Any]] = []
                for row in rows.fetchall():
                    trends.append({
                        "date": str(row[0]) if row[0] else None,
                        "overall": row[1],
                        "ai_visibility": row[2],
                    })
                return trends
        except Exception as e:
            logger.warning(f"[BrandDiagnosis] 获取趋势失败: {e}")
            return []


# ----------------------------------------------------------------------
# 单例
# ----------------------------------------------------------------------
_brand_diagnosis_service: Optional[BrandDiagnosisService] = None


def get_brand_diagnosis_service() -> BrandDiagnosisService:
    """获取品牌诊断服务单例"""
    global _brand_diagnosis_service
    if _brand_diagnosis_service is None:
        _brand_diagnosis_service = BrandDiagnosisService()
    return _brand_diagnosis_service
