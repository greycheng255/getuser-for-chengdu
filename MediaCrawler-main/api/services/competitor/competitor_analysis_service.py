# -*- coding: utf-8 -*-
"""
竞品分析服务

迁移自 GEO-main/geo_system/backend/competitor_analysis_service.py，适配 MediaCrawler：
1. 数据库：sqlite3 同步 → PostgreSQL 异步（database.db_session.get_async_engine + sqlalchemy.text）
2. 配置：硬编码 → 环境变量读取（os.environ.get）
3. 日志：print → logging.getLogger(__name__)
4. 异步化：所有数据库操作改为 async def，新增 ensure_table() 方法负责建表（CREATE TABLE IF NOT EXISTS）
5. 保留竞品监控、对比分析、竞争策略建议全部业务逻辑（含 HTTP 抓取估算逻辑）
6. 监控服务（monitoring_service）作为可选依赖，尚未迁移到 MediaCrawler 时优雅降级

对应 PRD：竞品分析模块（竞品监控、对比分析、竞争策略建议）。
"""

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# bs4 作为软依赖：未安装时降级为基于正则的简单解析，避免模块整体不可用
try:
    from bs4 import BeautifulSoup

    BS4_AVAILABLE = True
except ImportError:
    logger.warning(
        "[Competitor] bs4 未安装，关键词扩展/相关词抓取将仅依赖基础规则与百度建议 API。"
        "建议执行 `pip install beautifulsoup4 lxml` 以获得完整功能。"
    )
    BS4_AVAILABLE = False
    BeautifulSoup = None  # type: ignore

# ============ 配置（环境变量读取，避免硬编码敏感信息） ============
COMPETITOR_HTTP_TIMEOUT = int(os.environ.get("COMPETITOR_HTTP_TIMEOUT", "15"))
COMPETITOR_USER_AGENT = os.environ.get(
    "COMPETITOR_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)

# ============ 监控服务（可选依赖，尚未迁移时优雅降级） ============
try:
    from api.services.monitoring.monitoring_service import (  # type: ignore
        AIPlatform,
        MonitoringService,
        SearchEngine,
    )

    monitoring_service = MonitoringService()
    MONITORING_AVAILABLE = True
except Exception as e:
    logger.warning(f"[Competitor] monitoring service unavailable: {e}")
    MONITORING_AVAILABLE = False


class CompetitorStatus(Enum):
    """竞品状态"""

    ACTIVE = "active"          # 活跃监控
    PAUSED = "paused"          # 暂停监控
    REMOVED = "removed"        # 已移除


class ComparisonDimension(Enum):
    """对比维度"""

    AI_VISIBILITY = "ai_visibility"            # AI可见度
    SEARCH_RANK = "search_rank"                # 搜索排名
    CONTENT_VOLUME = "content_volume"          # 内容产量
    SOCIAL_ENGAGEMENT = "social_engagement"    # 社交互动
    BRAND_MENTION = "brand_mention"            # 品牌提及
    SENTIMENT = "sentiment"                    # 舆情情感


@dataclass
class Competitor:
    """竞品信息"""

    id: str
    brand_name: str
    website: str
    industry: str
    description: str
    keywords: List[str]
    status: CompetitorStatus
    created_at: datetime
    last_analyzed_at: Optional[datetime] = None


@dataclass
class CompetitorMetrics:
    """竞品指标数据"""

    competitor_id: str
    dimension: str
    score: float
    rank: int
    value: str
    details: Dict
    recorded_at: datetime


@dataclass
class ComparisonResult:
    """对比结果"""

    dimension: str
    my_score: float
    competitor_score: float
    difference: float
    winner: str  # 'me', 'competitor', 'tie'
    gap_analysis: str
    recommendations: List[str]


@dataclass
class CompetitiveReport:
    """竞争分析报告"""

    id: str
    my_brand: str
    competitor_id: str
    overall_score: float
    my_overall_score: float
    competitor_overall_score: float
    comparison_results: List[ComparisonResult]
    strengths: List[str]
    weaknesses: List[str]
    opportunities: List[str]
    threats: List[str]
    action_plan: List[Dict]
    created_at: datetime


class CompetitorAnalysisService:
    """
    竞品分析服务（异步，PostgreSQL）
    """

    _ensured = False  # DDL 仅首次执行一次，避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    # --------------------------------------------------------------
    # 基础设施：建表
    # --------------------------------------------------------------
    async def ensure_table(self) -> None:
        """确保所需数据表存在（CREATE TABLE IF NOT EXISTS）"""
        if CompetitorAnalysisService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return

            async with engine.begin() as conn:
                # 竞品表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS competitors ("
                        "  id VARCHAR(64) PRIMARY KEY,"
                        "  brand_name VARCHAR(128) UNIQUE,"
                        "  website TEXT,"
                        "  industry VARCHAR(128),"
                        "  description TEXT,"
                        "  keywords TEXT,"
                        "  status VARCHAR(32) DEFAULT 'active',"
                        "  created_at TIMESTAMP,"
                        "  last_analyzed_at TIMESTAMP"
                        ")"
                    )
                )
                # 竞品指标表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS competitor_metrics ("
                        "  id SERIAL PRIMARY KEY,"
                        "  competitor_id VARCHAR(64),"
                        "  dimension VARCHAR(64),"
                        "  score FLOAT,"
                        "  rank INTEGER,"
                        "  value TEXT,"
                        "  details TEXT,"
                        "  recorded_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
                # 对比报告表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS comparison_reports ("
                        "  id VARCHAR(64) PRIMARY KEY,"
                        "  my_brand VARCHAR(128),"
                        "  competitor_id VARCHAR(64),"
                        "  overall_score FLOAT,"
                        "  my_overall_score FLOAT,"
                        "  competitor_overall_score FLOAT,"
                        "  comparison_results TEXT,"
                        "  strengths TEXT,"
                        "  weaknesses TEXT,"
                        "  opportunities TEXT,"
                        "  threats TEXT,"
                        "  action_plan TEXT,"
                        "  created_at TIMESTAMP"
                        ")"
                    )
                )
        except Exception as e:
            logger.warning(f"[Competitor] ensure_table failed: {e}")

    # --------------------------------------------------------------
    # 竞品管理
    # --------------------------------------------------------------
    async def add_competitor(
        self,
        brand_name: str,
        website: Optional[str] = None,
        industry: Optional[str] = None,
        description: Optional[str] = None,
        keywords: Optional[List[str]] = None,
    ) -> Competitor:
        """添加竞品（若已存在同名竞品，则返回现有记录）"""
        competitor = Competitor(
            id=str(uuid.uuid4()),
            brand_name=brand_name,
            website=website or "",
            industry=industry or "",
            description=description or "",
            keywords=keywords or [brand_name],
            status=CompetitorStatus.ACTIVE,
            created_at=datetime.now(),
        )

        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return competitor

            async with engine.begin() as conn:
                result = await conn.execute(
                    sql_text(
                        "INSERT INTO competitors "
                        "(id, brand_name, website, industry, description, keywords, status, created_at) "
                        "VALUES (:id, :bn, :ws, :ind, :desc, :kw, :st, :ca) "
                        "ON CONFLICT (brand_name) DO NOTHING"
                    ),
                    {
                        "id": competitor.id,
                        "bn": competitor.brand_name,
                        "ws": competitor.website,
                        "ind": competitor.industry,
                        "desc": competitor.description,
                        "kw": json.dumps(competitor.keywords, ensure_ascii=False),
                        "st": competitor.status.value,
                        "ca": competitor.created_at,
                    },
                )
                if result.rowcount == 0:
                    # 竞品已存在，返回现有记录
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM competitors WHERE brand_name = :bn"
                        ),
                        {"bn": brand_name},
                    )
                    row = rows.fetchone()
                    if row:
                        competitor = self._row_to_competitor(row)
        except Exception as e:
            logger.warning(f"[Competitor] add_competitor failed: {e}")

        return competitor

    async def get_competitors(
        self, status: Optional[CompetitorStatus] = None
    ) -> List[Competitor]:
        """获取竞品列表"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []

            async with engine.connect() as conn:
                if status:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM competitors WHERE status = :st "
                            "ORDER BY created_at DESC"
                        ),
                        {"st": status.value},
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM competitors ORDER BY created_at DESC"
                        )
                    )
                return [self._row_to_competitor(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[Competitor] get_competitors failed: {e}")
            return []

    def _row_to_competitor(self, row) -> Competitor:
        """数据库行转对象"""
        created_at = row[7]
        last_analyzed_at = row[8]

        # 字符串时间 → datetime（PostgreSQL 通常直接返回 datetime，保留兜底）
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except Exception:
                created_at = datetime.now()

        if isinstance(last_analyzed_at, str):
            try:
                last_analyzed_at = datetime.fromisoformat(
                    last_analyzed_at.replace("Z", "+00:00")
                )
            except Exception:
                last_analyzed_at = None

        return Competitor(
            id=row[0],
            brand_name=row[1],
            website=row[2],
            industry=row[3],
            description=row[4],
            keywords=json.loads(row[5]) if row[5] else [],
            status=CompetitorStatus(row[6]),
            created_at=created_at,
            last_analyzed_at=last_analyzed_at,
        )

    async def _get_competitor_by_id(
        self, competitor_id: str
    ) -> Optional[Competitor]:
        """根据ID获取竞品"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None

            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM competitors WHERE id = :cid"),
                    {"cid": competitor_id},
                )
                row = rows.fetchone()
                if row:
                    return self._row_to_competitor(row)
        except Exception as e:
            logger.warning(f"[Competitor] _get_competitor_by_id failed: {e}")
        return None

    # --------------------------------------------------------------
    # 竞品分析
    # --------------------------------------------------------------
    async def analyze_competitor(self, competitor_id: str) -> Dict:
        """分析竞品数据"""
        competitor = await self._get_competitor_by_id(competitor_id)
        if not competitor:
            return {"error": "竞品不存在"}

        metrics: List[Dict] = []

        # AI可见度分析
        ai_visibility_score = await self._analyze_ai_visibility(competitor.brand_name)
        metrics.append({
            "dimension": ComparisonDimension.AI_VISIBILITY.value,
            "score": ai_visibility_score,
            "rank": 3,
            "value": f"{ai_visibility_score}/100",
            "details": {
                "doubao_mentioned": True,
                "deepseek_mentioned": True,
                "kimi_mentioned": False,
                "qianwen_mentioned": True,
            },
        })

        # 搜索排名分析
        search_rank_score = await self._analyze_search_rank(competitor.brand_name)
        metrics.append({
            "dimension": ComparisonDimension.SEARCH_RANK.value,
            "score": search_rank_score,
            "rank": 2,
            "value": f"平均排名: {search_rank_score}",
            "details": {
                "baidu_rank": 3,
                "sogou_rank": 4,
                "360_rank": 2,
            },
        })

        # 内容产量分析
        content_volume_score = await self._analyze_content_volume(competitor.brand_name)
        metrics.append({
            "dimension": ComparisonDimension.CONTENT_VOLUME.value,
            "score": content_volume_score,
            "rank": 1,
            "value": f"月产量: {content_volume_score}篇",
            "details": {
                "monthly_articles": 25,
                "monthly_videos": 8,
                "monthly_qa": 15,
            },
        })

        # 社交互动分析
        social_score = await self._analyze_social_engagement(competitor.brand_name)
        metrics.append({
            "dimension": ComparisonDimension.SOCIAL_ENGAGEMENT.value,
            "score": social_score,
            "rank": 4,
            "value": f"互动率: {social_score}%",
            "details": {
                "weibo_followers": 50000,
                "zhihu_followers": 12000,
                "xiaohongshu_followers": 35000,
            },
        })

        # 保存指标数据
        for metric in metrics:
            await self._save_metric(competitor_id, metric)

        # 更新最后分析时间
        await self._update_last_analyzed(competitor_id)

        return {
            "competitor_id": competitor_id,
            "brand_name": competitor.brand_name,
            "metrics": metrics,
            "analyzed_at": datetime.now().isoformat(),
        }

    async def _analyze_ai_visibility(self, brand_name: str) -> float:
        """分析AI可见度 - 使用真实数据"""
        if not MONITORING_AVAILABLE:
            raise RuntimeError(
                "监控服务不可用，无法分析AI可见度。请检查 monitoring_service 配置。"
            )

        platforms = [
            AIPlatform.DOUBAO,
            AIPlatform.DEEPSEEK,
            AIPlatform.KIMI,
            AIPlatform.WENXINYIYAN,
            AIPlatform.TONGYIQIANWEN,
        ]
        mentioned_count = 0
        total_checked = 0

        for platform in platforms:
            try:
                result = monitoring_service.check_ai_citation(
                    platform, f"{brand_name}怎么样", brand_name
                )
                total_checked += 1
                if result.get("mentioned", False):
                    mentioned_count += 1
            except Exception as e:
                logger.warning(
                    f"[Competitor] AI visibility check error for {platform}: {e}"
                )

        if total_checked == 0:
            raise RuntimeError(
                f"所有AI平台查询均失败，无法计算 {brand_name} 的AI可见度。"
            )

        # 计算可见度分数 (0-100)
        score = (mentioned_count / total_checked) * 100
        return round(score, 1)

    async def _analyze_search_rank(self, brand_name: str) -> float:
        """分析搜索排名 - 使用真实爬虫"""
        if not MONITORING_AVAILABLE:
            raise RuntimeError(
                "监控服务不可用，无法分析搜索排名。请检查 monitoring_service 配置。"
            )

        results = monitoring_service.check_search_rank(brand_name, SearchEngine.BAIDU)
        if results:
            # 找到品牌官网在搜索结果中的位置
            for i, result in enumerate(results, 1):
                if brand_name.lower() in result.get("url", "").lower():
                    return float(i)
            # 如果没找到官网，返回结果数+1表示不在首页
            return float(len(results) + 1)

        raise RuntimeError(
            f"无法获取 {brand_name} 的搜索排名数据，爬虫未返回结果。"
        )

    async def _analyze_content_volume(self, brand_name: str) -> int:
        """分析内容产量 - 使用爬虫估算"""
        encoded_name = requests.utils.quote(brand_name)
        url = f"https://www.baidu.com/s?wd={encoded_name}&pn=0&rn=50"

        headers = {"User-Agent": COMPETITOR_USER_AGENT}

        # 在线程中执行同步 requests.get，避免阻塞事件循环
        response = await asyncio.to_thread(
            requests.get, url, headers=headers, timeout=COMPETITOR_HTTP_TIMEOUT
        )
        response.encoding = "utf-8"

        # 统计搜索结果中包含品牌名的条目数
        brand_results = 0
        if BS4_AVAILABLE:
            soup = BeautifulSoup(response.text, "lxml")
            for item in soup.select(".result.c-container"):
                title = item.select_one("h3.t>a")
                if title and brand_name in title.get_text():
                    brand_results += 1
        else:
            # 降级：用正则粗略统计 h3 标题中包含品牌名的条目数
            brand_results = len(re.findall(r"<h3[^>]*>[^<]*" + re.escape(brand_name), response.text))

        # 根据搜索结果数量估算内容产量
        # 每个搜索结果大约代表5-10篇内容
        estimated_volume = brand_results * 7

        return estimated_volume

    async def _analyze_social_engagement(self, brand_name: str) -> float:
        """分析社交互动 - 使用真实数据"""
        import math

        encoded_name = requests.utils.quote(brand_name)
        url = f"https://s.weibo.com/weibo?q={encoded_name}"

        headers = {"User-Agent": COMPETITOR_USER_AGENT}

        # 在线程中执行同步 requests.get，避免阻塞事件循环
        response = await asyncio.to_thread(
            requests.get, url, headers=headers, timeout=COMPETITOR_HTTP_TIMEOUT
        )
        response.encoding = "utf-8"

        count_text = ""
        if BS4_AVAILABLE:
            soup = BeautifulSoup(response.text, "lxml")
            result_count = soup.select_one(".result-total")
            if result_count:
                count_text = result_count.get_text()
        else:
            # 降级：在 HTML 文本中查找“找到...条结果”这类模式
            m = re.search(r"找到[^<\d]{0,10}([\d,]+)\s*条", response.text)
            if m:
                count_text = m.group(1)

        if count_text:
            match = re.search(r"(\d+)", count_text.replace(",", ""))
            if match:
                count = int(match.group(1))
                # 根据微博数量计算互动率
                # 互动率 = log10(帖子数+1) * 基础系数
                engagement_rate = round(math.log10(count + 1) * 3, 2)
                return engagement_rate

        raise RuntimeError(f"无法获取 {brand_name} 的社交互动数据。")

    async def _save_metric(self, competitor_id: str, metric: Dict) -> None:
        """保存指标数据"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return

            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO competitor_metrics "
                        "(competitor_id, dimension, score, rank, value, details, recorded_at) "
                        "VALUES (:cid, :dim, :sc, :rk, :val, :det, :ra)"
                    ),
                    {
                        "cid": competitor_id,
                        "dim": metric["dimension"],
                        "sc": metric["score"],
                        "rk": metric["rank"],
                        "val": metric["value"],
                        "det": json.dumps(metric["details"], ensure_ascii=False),
                        "ra": datetime.now(),
                    },
                )
        except Exception as e:
            logger.warning(f"[Competitor] _save_metric failed: {e}")

    async def _update_last_analyzed(self, competitor_id: str) -> None:
        """更新最后分析时间"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return

            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE competitors SET last_analyzed_at = :t "
                        "WHERE id = :cid"
                    ),
                    {"t": datetime.now(), "cid": competitor_id},
                )
        except Exception as e:
            logger.warning(f"[Competitor] _update_last_analyzed failed: {e}")

    # --------------------------------------------------------------
    # 对比分析
    # --------------------------------------------------------------
    async def compare_with_competitor(
        self, my_brand: str, competitor_id: str
    ) -> CompetitiveReport:
        """与竞品进行对比分析"""
        competitor = await self._get_competitor_by_id(competitor_id)
        if not competitor:
            raise ValueError("竞品不存在")

        # 获取竞品最新指标
        competitor_metrics = await self._get_latest_metrics(competitor_id)

        # 获取我方数据
        my_metrics = await self._get_my_metrics(my_brand)

        # 进行对比分析
        comparison_results: List[ComparisonResult] = []
        my_total_score = 0.0
        competitor_total_score = 0.0

        for dimension in ComparisonDimension:
            my_score = my_metrics.get(dimension.value, 50)
            competitor_score = competitor_metrics.get(dimension.value, 50)

            my_total_score += my_score
            competitor_total_score += competitor_score

            difference = my_score - competitor_score

            if difference > 5:
                winner = "me"
                gap_analysis = f"领先 {difference:.1f} 分"
            elif difference < -5:
                winner = "competitor"
                gap_analysis = f"落后 {abs(difference):.1f} 分"
            else:
                winner = "tie"
                gap_analysis = "基本持平"

            recommendations = self._generate_recommendations(
                dimension.value, my_score, competitor_score
            )

            comparison_results.append(
                ComparisonResult(
                    dimension=dimension.value,
                    my_score=my_score,
                    competitor_score=competitor_score,
                    difference=difference,
                    winner=winner,
                    gap_analysis=gap_analysis,
                    recommendations=recommendations,
                )
            )

        # 计算综合得分
        my_overall = my_total_score / len(ComparisonDimension)
        competitor_overall = competitor_total_score / len(ComparisonDimension)

        # SWOT分析
        strengths, weaknesses, opportunities, threats = self._swot_analysis(
            comparison_results
        )

        # 生成行动计划
        action_plan = self._generate_action_plan(comparison_results)

        report = CompetitiveReport(
            id=str(uuid.uuid4()),
            my_brand=my_brand,
            competitor_id=competitor_id,
            overall_score=competitor_overall - my_overall,
            my_overall_score=my_overall,
            competitor_overall_score=competitor_overall,
            comparison_results=comparison_results,
            strengths=strengths,
            weaknesses=weaknesses,
            opportunities=opportunities,
            threats=threats,
            action_plan=action_plan,
            created_at=datetime.now(),
        )

        # 保存报告
        await self._save_report(report)

        return report

    async def _get_latest_metrics(self, competitor_id: str) -> Dict[str, float]:
        """获取竞品最新指标"""
        await self.ensure_table()
        metrics: Dict[str, float] = {}
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return {d.value: 50 for d in ComparisonDimension}

            async with engine.connect() as conn:
                for dimension in ComparisonDimension:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT score FROM competitor_metrics "
                            "WHERE competitor_id = :cid AND dimension = :dim "
                            "ORDER BY recorded_at DESC LIMIT 1"
                        ),
                        {"cid": competitor_id, "dim": dimension.value},
                    )
                    row = rows.fetchone()
                    metrics[dimension.value] = row[0] if row else 50
        except Exception as e:
            logger.warning(f"[Competitor] _get_latest_metrics failed: {e}")
            for dimension in ComparisonDimension:
                metrics.setdefault(dimension.value, 50)
        return metrics

    async def _get_my_metrics(self, my_brand: str) -> Dict[str, float]:
        """获取我方指标 - 使用真实数据"""
        metrics: Dict[str, float] = {}

        # AI可见度
        try:
            metrics[ComparisonDimension.AI_VISIBILITY.value] = (
                await self._analyze_ai_visibility(my_brand)
            )
        except Exception as e:
            logger.warning(f"[Competitor] My AI visibility error: {e}")
            raise RuntimeError(f"无法获取我方AI可见度数据: {e}")

        # 搜索排名
        try:
            metrics[ComparisonDimension.SEARCH_RANK.value] = (
                await self._analyze_search_rank(my_brand)
            )
        except Exception as e:
            logger.warning(f"[Competitor] My search rank error: {e}")
            raise RuntimeError(f"无法获取我方搜索排名数据: {e}")

        # 内容产量
        try:
            metrics[ComparisonDimension.CONTENT_VOLUME.value] = (
                await self._analyze_content_volume(my_brand)
            )
        except Exception as e:
            logger.warning(f"[Competitor] My content volume error: {e}")
            raise RuntimeError(f"无法获取我方内容产量数据: {e}")

        # 社交互动
        try:
            metrics[ComparisonDimension.SOCIAL_ENGAGEMENT.value] = (
                await self._analyze_social_engagement(my_brand)
            )
        except Exception as e:
            logger.warning(f"[Competitor] My social engagement error: {e}")
            raise RuntimeError(f"无法获取我方社交互动数据: {e}")

        # 品牌提及 - 通过百度搜索结果数估算
        try:
            metrics[ComparisonDimension.BRAND_MENTION.value] = (
                await self._analyze_brand_mention(my_brand)
            )
        except Exception as e:
            logger.warning(f"[Competitor] My brand mention error: {e}")
            raise RuntimeError(f"无法获取我方品牌提及数据: {e}")

        # 舆情情感 - 通过AI平台分析
        try:
            metrics[ComparisonDimension.SENTIMENT.value] = (
                await self._analyze_sentiment(my_brand)
            )
        except Exception as e:
            logger.warning(f"[Competitor] My sentiment error: {e}")
            raise RuntimeError(f"无法获取我方舆情情感数据: {e}")

        return metrics

    async def _analyze_brand_mention(self, brand_name: str) -> int:
        """分析品牌提及数 - 使用真实数据"""
        encoded_name = requests.utils.quote(brand_name)
        url = f"https://www.baidu.com/s?wd={encoded_name}&pn=0&rn=10"

        headers = {"User-Agent": COMPETITOR_USER_AGENT}

        response = requests.get(
            url, headers=headers, timeout=COMPETITOR_HTTP_TIMEOUT
        )
        response.encoding = "utf-8"

        if BS4_AVAILABLE:
            soup = BeautifulSoup(response.text, "lxml")

            # 统计搜索结果总数
            result_count_tag = soup.select_one(".nums_text")
            if result_count_tag:
                count_text = result_count_tag.get_text()
                match = re.search(r"([\d,]+)", count_text.replace(",", ""))
                if match:
                    return int(match.group(1))

            # 如果没有总数，统计结果条目数
            return len(soup.select(".result.c-container"))
        else:
            # 降级：在 HTML 中查找百度结果数模式，如“百度为您找到相关结果约 100,000,000 个”
            m = re.search(r"找到[^<\d]{0,10}([\d,]+)\s*个", response.text)
            if m:
                return int(m.group(1).replace(",", ""))
            # 退而求其次：统计结果块数量
            return len(re.findall(r"class=\"result c-container\"", response.text))

    async def _analyze_sentiment(self, brand_name: str) -> float:
        """分析舆情情感 - 使用真实数据"""
        if not MONITORING_AVAILABLE:
            raise RuntimeError("监控服务不可用，无法分析舆情情感。")

        platforms = [AIPlatform.DOUBAO, AIPlatform.DEEPSEEK, AIPlatform.KIMI]
        sentiment_scores: List[float] = []

        for platform in platforms:
            try:
                result = monitoring_service.check_ai_citation(
                    platform, f"{brand_name}评价怎么样", brand_name
                )
                sentiment = result.get("sentiment", "neutral")
                if sentiment == "positive":
                    sentiment_scores.append(80)
                elif sentiment == "negative":
                    sentiment_scores.append(30)
                else:
                    sentiment_scores.append(55)
            except Exception as e:
                logger.warning(
                    f"[Competitor] Sentiment check error for {platform}: {e}"
                )

        if not sentiment_scores:
            raise RuntimeError(f"无法获取 {brand_name} 的舆情情感数据。")

        return round(sum(sentiment_scores) / len(sentiment_scores), 1)

    def _generate_recommendations(
        self, dimension: str, my_score: float, competitor_score: float
    ) -> List[str]:
        """生成改进建议"""
        recommendations: List[str] = []

        if dimension == ComparisonDimension.AI_VISIBILITY.value:
            if my_score < competitor_score:
                recommendations.extend([
                    "增加GEO优化内容产出，提升AI平台收录率",
                    "优化内容结构，提高被AI引用的概率",
                    "在更多AI平台建立品牌存在感",
                ])
        elif dimension == ComparisonDimension.SEARCH_RANK.value:
            if my_score < competitor_score:
                recommendations.extend([
                    "加强SEO优化，提升核心关键词排名",
                    "增加高质量外链建设",
                    "优化网站技术性能",
                ])
        elif dimension == ComparisonDimension.CONTENT_VOLUME.value:
            if my_score < competitor_score:
                recommendations.extend([
                    "增加内容生产频率",
                    "建立内容生产SOP流程",
                    "利用AI工具提升内容产出效率",
                ])

        return recommendations

    def _swot_analysis(
        self, comparison_results: List[ComparisonResult]
    ) -> Tuple[List[str], List[str], List[str], List[str]]:
        """SWOT分析"""
        strengths: List[str] = []
        weaknesses: List[str] = []
        opportunities: List[str] = []
        threats: List[str] = []

        for result in comparison_results:
            if result.winner == "me":
                strengths.append(f"{result.dimension}: {result.gap_analysis}")
            elif result.winner == "competitor":
                weaknesses.append(f"{result.dimension}: {result.gap_analysis}")

        # 基于弱点生成机会
        if any(
            r.dimension == ComparisonDimension.AI_VISIBILITY.value
            and r.winner == "competitor"
            for r in comparison_results
        ):
            opportunities.append("AI可见度提升空间较大，可重点投入GEO优化")

        if any(
            r.dimension == ComparisonDimension.CONTENT_VOLUME.value
            and r.winner == "competitor"
            for r in comparison_results
        ):
            opportunities.append("内容产量有提升空间，可增加发布频率")

        # 威胁分析
        threats.append("竞品持续投入，市场竞争加剧")
        if any(
            r.dimension == ComparisonDimension.SEARCH_RANK.value
            and r.winner == "competitor"
            for r in comparison_results
        ):
            threats.append("搜索排名落后可能导致流量流失")

        return strengths, weaknesses, opportunities, threats

    def _generate_action_plan(
        self, comparison_results: List[ComparisonResult]
    ) -> List[Dict]:
        """生成行动计划"""
        action_plan: List[Dict] = []

        # 找出最需要改进的维度
        sorted_results = sorted(comparison_results, key=lambda x: x.difference)

        # 优先级高的改进项
        for i, result in enumerate(sorted_results[:3]):
            if result.winner == "competitor":
                action_plan.append({
                    "priority": "high" if i == 0 else "medium",
                    "dimension": result.dimension,
                    "action": f"提升{result.dimension}表现",
                    "target": f"达到竞品水平的{result.competitor_score:.0f}分",
                    "timeline": "1个月内" if i == 0 else "3个月内",
                })

        return action_plan

    async def _save_report(self, report: CompetitiveReport) -> None:
        """保存对比报告"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return

            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO comparison_reports "
                        "(id, my_brand, competitor_id, overall_score, my_overall_score, "
                        " competitor_overall_score, comparison_results, strengths, "
                        " weaknesses, opportunities, threats, action_plan, created_at) "
                        "VALUES (:id, :mb, :cid, :os, :mos, :cos, :cr, :st, :we, :op, :th, :ap, :ca)"
                    ),
                    {
                        "id": report.id,
                        "mb": report.my_brand,
                        "cid": report.competitor_id,
                        "os": report.overall_score,
                        "mos": report.my_overall_score,
                        "cos": report.competitor_overall_score,
                        "cr": json.dumps(
                            [asdict(r) for r in report.comparison_results],
                            ensure_ascii=False,
                        ),
                        "st": json.dumps(report.strengths, ensure_ascii=False),
                        "we": json.dumps(report.weaknesses, ensure_ascii=False),
                        "op": json.dumps(report.opportunities, ensure_ascii=False),
                        "th": json.dumps(report.threats, ensure_ascii=False),
                        "ap": json.dumps(report.action_plan, ensure_ascii=False),
                        "ca": report.created_at,
                    },
                )
        except Exception as e:
            logger.warning(f"[Competitor] _save_report failed: {e}")

    async def get_comparison_history(
        self,
        my_brand: str,
        competitor_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """获取对比历史"""
        # competitor_id 在 DB 中为 varchar，asyncpg 严格要求类型匹配，统一转 str
        if competitor_id is not None:
            competitor_id = str(competitor_id)
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []

            async with engine.connect() as conn:
                if competitor_id:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM comparison_reports "
                            "WHERE my_brand = :mb AND competitor_id = :cid "
                            "ORDER BY created_at DESC LIMIT :lmt"
                        ),
                        {"mb": my_brand, "cid": competitor_id, "lmt": limit},
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT * FROM comparison_reports "
                            "WHERE my_brand = :mb "
                            "ORDER BY created_at DESC LIMIT :lmt"
                        ),
                        {"mb": my_brand, "lmt": limit},
                    )
                return [self._row_to_report(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[Competitor] get_comparison_history failed: {e}")
            return []

    def _row_to_report(self, row) -> Dict:
        """数据库行转报告字典"""
        return {
            "id": row[0],
            "my_brand": row[1],
            "competitor_id": row[2],
            "overall_score": row[3],
            "my_overall_score": row[4],
            "competitor_overall_score": row[5],
            "comparison_results": json.loads(row[6]) if row[6] else [],
            "strengths": json.loads(row[7]) if row[7] else [],
            "weaknesses": json.loads(row[8]) if row[8] else [],
            "opportunities": json.loads(row[9]) if row[9] else [],
            # 注：原 GEO-main 此处为 json.loads(json.loads(row[10])) 双重解码会抛异常，
            # 迁移时修正为单次解码，避免运行时崩溃
            "threats": json.loads(row[10]) if row[10] else [],
            "action_plan": json.loads(row[11]) if row[11] else [],
            "created_at": row[12],
        }

    async def get_competitive_landscape(self, my_brand: str) -> Dict:
        """获取竞争格局全景"""
        competitors = await self.get_competitors(CompetitorStatus.ACTIVE)

        landscape = {
            "my_brand": my_brand,
            "total_competitors": len(competitors),
            "competitors": [],
            "market_position": {},
            "competitive_intensity": "medium",
        }

        for competitor in competitors:
            # 获取最新对比数据
            latest_report = await self.get_comparison_history(
                my_brand, competitor.id, 1
            )

            comp_data = {
                "id": competitor.id,
                "brand_name": competitor.brand_name,
                "industry": competitor.industry,
                "status": competitor.status.value,
                "last_analyzed": (
                    competitor.last_analyzed_at.isoformat()
                    if competitor.last_analyzed_at
                    else None
                ),
            }

            if latest_report:
                comp_data["latest_comparison"] = {
                    "my_score": latest_report[0]["my_overall_score"],
                    "competitor_score": latest_report[0][
                        "competitor_overall_score"
                    ],
                    "gap": latest_report[0]["overall_score"],
                    "date": latest_report[0]["created_at"],
                }

            landscape["competitors"].append(comp_data)

        return landscape


# ============ 单例 ============
_competitor_analysis_service: Optional[CompetitorAnalysisService] = None


def get_competitor_analysis_service() -> CompetitorAnalysisService:
    """获取竞品分析服务单例"""
    global _competitor_analysis_service
    if _competitor_analysis_service is None:
        _competitor_analysis_service = CompetitorAnalysisService()
    return _competitor_analysis_service
