# -*- coding: utf-8 -*-
"""
关键词研究服务（P0：关键词挖掘 / 分析 / 推荐 / 趋势追踪）

迁移自 GEO-main geo_system/backend/keyword_research_service.py，适配 MediaCrawler：

适配点：
1. 数据库：原 sqlite3 同步操作改为 PostgreSQL 异步（基于 database.db_session.get_async_engine + sqlalchemy text），
   建表逻辑收敛到 ensure_table() 方法，使用 CREATE TABLE IF NOT EXISTS。
2. 配置：HTTP 超时 / User-Agent / 扩展数量等均通过 os.environ.get 读取，禁止硬编码敏感信息。
3. 日志：print 全部替换为 logging.getLogger(__name__)。
4. HTTP：原 requests 同步调用改为 httpx.AsyncClient 异步调用，适配 MediaCrawler 异步架构。
5. 单例：文件末尾提供 get_keyword_research_service()，符合 MediaCrawler 服务规范。

保留原逻辑：
- 关键词挖掘（百度搜索建议 + 搜索结果相关词扩展）
- 关键词分析（搜索量/难度/CPC/竞争度估算、意图识别、类型识别、趋势生成）
- 关键词推荐（高机会 / GEO 优化 / 长尾三类策略）
- 内容空白发现
- 关键词分组

对应 PRD：GEO 关键词研究模块。
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ==================== 配置（环境变量优先） ====================

KEYWORD_RESEARCH_HTTP_TIMEOUT = int(os.environ.get("KEYWORD_RESEARCH_HTTP_TIMEOUT", "15"))
KEYWORD_RESEARCH_USER_AGENT = os.environ.get(
    "KEYWORD_RESEARCH_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
KEYWORD_RESEARCH_MAX_SUGGESTIONS = int(os.environ.get("KEYWORD_RESEARCH_MAX_SUGGESTIONS", "10"))
KEYWORD_RESEARCH_MAX_RELATED = int(os.environ.get("KEYWORD_RESEARCH_MAX_RELATED", "8"))

# BeautifulSoup 为可选依赖（用于解析百度搜索结果页 HTML）
try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - 环境未安装 bs4 时降级
    BeautifulSoup = None
    logger.warning("bs4 未安装，关键词扩展/相关词抓取将仅依赖基础规则与百度建议 API")


# ==================== 枚举 ====================


class KeywordIntent(Enum):
    """搜索意图"""
    INFORMATIONAL = "informational"    # 信息型
    NAVIGATIONAL = "navigational"      # 导航型
    COMMERCIAL = "commercial"          # 商业型
    TRANSACTIONAL = "transactional"    # 交易型


class KeywordDifficulty(Enum):
    """关键词难度"""
    EASY = "easy"           # 容易 (0-30)
    MEDIUM = "medium"       # 中等 (31-60)
    HARD = "hard"           # 困难 (61-80)
    VERY_HARD = "very_hard"  # 非常困难 (81-100)


class KeywordType(Enum):
    """关键词类型"""
    BRAND = "brand"            # 品牌词
    PRODUCT = "product"        # 产品词
    INDUSTRY = "industry"      # 行业词
    LONG_TAIL = "long_tail"    # 长尾词
    QUESTION = "question"      # 问题词
    COMPETITOR = "competitor"  # 竞品词
    GEO = "geo"                # GEO优化词


# ==================== 数据类 ====================


@dataclass
class Keyword:
    """关键词数据"""
    id: str
    keyword: str
    search_volume: int           # 月搜索量
    difficulty: float            # 难度 0-100
    cpc: float                   # 单次点击成本
    intent: KeywordIntent
    keyword_type: KeywordType
    related_keywords: List[str]
    questions: List[str]         # 相关问题
    trend: List[Dict]            # 趋势数据
    competition_score: float     # 竞争度
    opportunity_score: float     # 机会得分
    geo_relevance: float         # GEO相关度
    created_at: datetime
    last_updated: datetime


@dataclass
class KeywordGroup:
    """关键词分组"""
    id: str
    name: str
    description: str
    keywords: List[str]
    total_volume: int
    avg_difficulty: float
    created_at: datetime


@dataclass
class KeywordResearchReport:
    """关键词研究报告"""
    id: str
    seed_keyword: str
    industry: str
    discovered_keywords: List[Keyword]
    recommendations: List[Dict]
    content_gaps: List[Dict]
    created_at: datetime


# ==================== 服务实现 ====================


class KeywordResearchService:
    """关键词研究服务（PostgreSQL 异步）"""

    def __init__(self):
        # 建表延迟到首次调用 ensure_table()，避免在模块导入时触发数据库连接
        self._table_ensured = False

    # ---------- 数据库 ----------

    async def ensure_table(self) -> None:
        """确保关键词研究所需的表存在（CREATE TABLE IF NOT EXISTS）。

        幂等：多次调用安全。
        """
        if self._table_ensured:
            return
        from database.db_session import get_async_engine
        from sqlalchemy import text as sql_text
        import config

        engine = get_async_engine(config.SAVE_DATA_OPTION)
        if engine is None:
            logger.warning("[KeywordResearch] 数据库引擎不可用（可能为 csv/json 存储），跳过建表")
            return

        # 关键词表
        ddl_keywords = """
        CREATE TABLE IF NOT EXISTS keyword_research_keywords (
            id VARCHAR(64) PRIMARY KEY,
            keyword TEXT UNIQUE,
            search_volume INTEGER,
            difficulty DOUBLE PRECISION,
            cpc DOUBLE PRECISION,
            intent VARCHAR(32),
            keyword_type VARCHAR(32),
            related_keywords TEXT,
            questions TEXT,
            trend TEXT,
            competition_score DOUBLE PRECISION,
            opportunity_score DOUBLE PRECISION,
            geo_relevance DOUBLE PRECISION,
            created_at TIMESTAMP,
            last_updated TIMESTAMP
        )
        """

        # 关键词分组表
        ddl_groups = """
        CREATE TABLE IF NOT EXISTS keyword_research_groups (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(255),
            description TEXT,
            keywords TEXT,
            total_volume INTEGER,
            avg_difficulty DOUBLE PRECISION,
            created_at TIMESTAMP
        )
        """

        # 研究报告表
        ddl_reports = """
        CREATE TABLE IF NOT EXISTS keyword_research_reports (
            id VARCHAR(64) PRIMARY KEY,
            seed_keyword TEXT,
            industry VARCHAR(255),
            discovered_keywords TEXT,
            recommendations TEXT,
            content_gaps TEXT,
            created_at TIMESTAMP
        )
        """

        async with engine.begin() as conn:
            await conn.execute(sql_text(ddl_keywords))
            await conn.execute(sql_text(ddl_groups))
            await conn.execute(sql_text(ddl_reports))

        self._table_ensured = True
        logger.info("[KeywordResearch] 数据库表已就绪（keyword_research_keywords/groups/reports）")

    @staticmethod
    def _get_engine():
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    # ---------- 主流程 ----------

    async def research_keywords(self, seed_keyword: str, industry: str = None,
                                depth: int = 2) -> KeywordResearchReport:
        """关键词研究主函数

        Args:
            seed_keyword: 种子关键词
            industry: 行业（可选）
            depth: 扩展深度（1=仅种子词层，2=两层扩展）

        Returns:
            KeywordResearchReport
        """
        await self.ensure_table()

        discovered_keywords: List[Keyword] = []

        # 第1层：基于种子词扩展
        layer1_keywords = await self._expand_keywords(seed_keyword)
        for kw in layer1_keywords:
            keyword_data = await self._analyze_keyword(kw, industry)
            discovered_keywords.append(keyword_data)
            await self._save_keyword(keyword_data)

        # 第2层：基于相关词进一步扩展
        if depth >= 2:
            for kw in layer1_keywords[:5]:  # 限制扩展数量
                layer2_keywords = await self._expand_keywords(kw)
                for kw2 in layer2_keywords[:3]:
                    if kw2 not in [k.keyword for k in discovered_keywords]:
                        keyword_data = await self._analyze_keyword(kw2, industry)
                        discovered_keywords.append(keyword_data)
                        await self._save_keyword(keyword_data)

        # 生成推荐
        recommendations = self._generate_recommendations(discovered_keywords)

        # 发现内容空白
        content_gaps = self._find_content_gaps(discovered_keywords)

        report = KeywordResearchReport(
            id=str(uuid.uuid4()),
            seed_keyword=seed_keyword,
            industry=industry,
            discovered_keywords=discovered_keywords,
            recommendations=recommendations,
            content_gaps=content_gaps,
            created_at=datetime.now(),
        )

        # 保存报告
        await self._save_report(report)

        return report

    # ---------- 关键词扩展 ----------

    async def _expand_keywords(self, seed_keyword: str) -> List[str]:
        """扩展关键词 - 基础规则 + 百度搜索建议 + 百度搜索结果相关词"""
        expansions: List[str] = []

        # 基础规则扩展
        prefixes = ['什么是', '怎么样', '哪家好', '推荐', '评测', '价格', '多少钱']
        suffixes = ['品牌', '厂家', '定制', '设计', '效果图', '案例', '口碑']
        questions = [
            f'{seed_keyword}怎么样', f'{seed_keyword}好不好', f'{seed_keyword}推荐',
            f'{seed_keyword}排名', f'{seed_keyword}哪个好',
        ]
        long_tails = [
            f'2026年{seed_keyword}推荐', f'{seed_keyword}十大品牌',
            f'{seed_keyword}选购指南', f'{seed_keyword}避坑指南',
        ]

        expansions.extend([f'{prefix}{seed_keyword}' for prefix in prefixes])
        expansions.extend([f'{seed_keyword}{suffix}' for suffix in suffixes])
        expansions.extend(questions)
        expansions.extend(long_tails)

        # 百度搜索建议 API
        try:
            encoded_keyword = httpx.URL("", params={"wd": seed_keyword}).params.get("wd", seed_keyword)
            url = f"http://suggestion.baidu.com/su?wd={encoded_keyword}&json=1&p=3"
            headers = {"User-Agent": KEYWORD_RESEARCH_USER_AGENT}

            async with httpx.AsyncClient(timeout=KEYWORD_RESEARCH_HTTP_TIMEOUT) as client:
                response = await client.get(url, headers=headers)

            # 百度建议返回非标准 JSON：window.baidu.sug({...})
            content = response.text
            if 'window.baidu.sug' in content:
                json_str = content.split('window.baidu.sug(')[1].rstrip(')')
                suggestion_data = json.loads(json_str)
                if 's' in suggestion_data:
                    expansions.extend(suggestion_data['s'][:KEYWORD_RESEARCH_MAX_SUGGESTIONS])

        except Exception as e:
            logger.warning("[Keyword] Baidu suggestion error: %s", e)

        # 百度搜索结果页相关词
        if BeautifulSoup is not None:
            try:
                encoded_keyword = httpx.URL("", params={"wd": seed_keyword}).params.get("wd", seed_keyword)
                url = f"https://www.baidu.com/s?wd={encoded_keyword}&pn=0&rn=10"
                headers = {"User-Agent": KEYWORD_RESEARCH_USER_AGENT}

                async with httpx.AsyncClient(timeout=KEYWORD_RESEARCH_HTTP_TIMEOUT) as client:
                    response = await client.get(url, headers=headers)

                soup = BeautifulSoup(response.text, 'lxml')

                # 提取相关搜索
                for item in soup.select('.rs_related_word a'):
                    related_keyword = item.get_text(strip=True)
                    if related_keyword:
                        expansions.append(related_keyword)

                # 提取搜索结果标题中的相关词
                for item in soup.select('.result.c-container'):
                    title = item.select_one('h3.t>a')
                    if title:
                        text = title.get_text()
                        for word in ['品牌', '推荐', '评测', '对比', '价格', '怎么样']:
                            if word in text and seed_keyword in text:
                                parts = text.split(seed_keyword)
                                if len(parts) > 1:
                                    expansions.append(f'{seed_keyword}{parts[1].strip()[:10]}')

            except Exception as e:
                logger.warning("[Keyword] Baidu search error: %s", e)

        return list(set(expansions))

    # ---------- 关键词分析 ----------

    async def _analyze_keyword(self, keyword: str, industry: str = None) -> Keyword:
        """分析单个关键词 - 综合搜索量/难度/意图/类型/趋势/机会/GEO相关度"""
        # 估算搜索量与难度
        volume_and_difficulty = await self._estimate_volume_and_difficulty(keyword)
        search_volume = volume_and_difficulty['volume']
        difficulty = volume_and_difficulty['difficulty']

        # 意图 / 类型（纯规则，无需异步）
        intent = self._detect_intent(keyword)
        keyword_type = self._detect_type(keyword)

        # 相关问题（规则生成）
        questions = self._generate_questions(keyword)

        # 趋势（规则 + 季节因子）
        trend = self._generate_trend(keyword)

        # 机会得分 / GEO相关度
        opportunity_score = self._calculate_opportunity(search_volume, difficulty, keyword_type)
        geo_relevance = self._calculate_geo_relevance(keyword, intent)

        # 相关关键词（异步 HTTP）
        related_keywords = await self._find_related_keywords(keyword)

        # 竞争度（异步 HTTP）
        competition_score = await self._estimate_competition(keyword)

        now = datetime.now()
        return Keyword(
            id=str(uuid.uuid4()),
            keyword=keyword,
            search_volume=search_volume,
            difficulty=difficulty,
            cpc=self._estimate_cpc(search_volume, difficulty),
            intent=intent,
            keyword_type=keyword_type,
            related_keywords=related_keywords,
            questions=questions,
            trend=trend,
            competition_score=competition_score,
            opportunity_score=opportunity_score,
            geo_relevance=geo_relevance,
            created_at=now,
            last_updated=now,
        )

    async def _estimate_volume_and_difficulty(self, keyword: str) -> Dict:
        """使用百度搜索结果估算搜索量与难度

        规则：搜索结果中权威站点越多 -> 搜索量越大、难度越高。
        """
        encoded_keyword = httpx.URL("", params={"wd": keyword}).params.get("wd", keyword)
        url = f"https://www.baidu.com/s?wd={encoded_keyword}&pn=0&rn=10"
        headers = {"User-Agent": KEYWORD_RESEARCH_USER_AGENT}

        top_domain_count = 0
        results_count = 0

        if BeautifulSoup is not None:
            try:
                async with httpx.AsyncClient(timeout=KEYWORD_RESEARCH_HTTP_TIMEOUT) as client:
                    response = await client.get(url, headers=headers)
                soup = BeautifulSoup(response.text, 'lxml')

                results_count = len(soup.select('.result.c-container'))
                for item in soup.select('.result.c-container'):
                    url_tag = item.select_one('.c-showurl')
                    if url_tag:
                        domain = url_tag.get_text()
                        if any(d in domain for d in ['baidu.com', 'zhihu.com', 'weibo.com', 'jd.com', 'taobao.com']):
                            top_domain_count += 1
            except Exception as e:
                logger.warning("[Keyword] estimate_volume_and_difficulty error: %s", e)

        # 根据权威站点数量估算搜索量
        if top_domain_count >= 5:
            base_volume = 5000
        elif top_domain_count >= 3:
            base_volume = 2000
        else:
            base_volume = 500

        # 难度：权威站点越多难度越高
        difficulty = min(95, 30 + top_domain_count * 10)

        return {
            'volume': int(base_volume),
            'difficulty': round(difficulty, 1),
        }

    def _estimate_cpc(self, volume: int, difficulty: float) -> float:
        """估算CPC价格：高搜索量 + 高难度 = 高CPC"""
        base_cpc = min(volume / 1000, 20)
        difficulty_multiplier = 1 + (difficulty / 100)
        return round(base_cpc * difficulty_multiplier, 2)

    async def _estimate_competition(self, keyword: str) -> float:
        """估算竞争度：统计百度搜索结果中的广告数量"""
        encoded_keyword = httpx.URL("", params={"wd": keyword}).params.get("wd", keyword)
        url = f"https://www.baidu.com/s?wd={encoded_keyword}&pn=0&rn=50"
        headers = {"User-Agent": KEYWORD_RESEARCH_USER_AGENT}

        ad_count = 0

        if BeautifulSoup is not None:
            try:
                async with httpx.AsyncClient(timeout=KEYWORD_RESEARCH_HTTP_TIMEOUT) as client:
                    response = await client.get(url, headers=headers)
                soup = BeautifulSoup(response.text, 'lxml')
                ad_count = len(soup.select('.ec_wise_ad'))
            except Exception as e:
                logger.warning("[Keyword] estimate_competition error: %s", e)

        # 广告越多，竞争越激烈
        if ad_count >= 5:
            return round(70 + ad_count * 3, 1)
        elif ad_count >= 3:
            return round(50 + ad_count * 5, 1)
        else:
            return round(20 + ad_count * 8, 1)

    async def _find_related_keywords(self, keyword: str) -> List[str]:
        """查找相关关键词：百度搜索结果相关搜索 + 百度建议 API"""
        related: List[str] = []

        try:
            encoded_keyword = httpx.URL("", params={"wd": keyword}).params.get("wd", keyword)
            url = f"https://www.baidu.com/s?wd={encoded_keyword}&pn=0&rn=10"
            headers = {"User-Agent": KEYWORD_RESEARCH_USER_AGENT}

            async with httpx.AsyncClient(timeout=KEYWORD_RESEARCH_HTTP_TIMEOUT) as client:
                response = await client.get(url, headers=headers)

            if BeautifulSoup is not None:
                soup = BeautifulSoup(response.text, 'lxml')
                for item in soup.select('.rs_related_word a'):
                    related_word = item.get_text(strip=True)
                    if related_word and related_word != keyword:
                        related.append(related_word)

            # 百度建议 API
            sug_url = f"http://suggestion.baidu.com/su?wd={encoded_keyword}&json=1&p=3"
            async with httpx.AsyncClient(timeout=KEYWORD_RESEARCH_HTTP_TIMEOUT) as client:
                sug_response = await client.get(sug_url, headers=headers)
            if 'window.baidu.sug' in sug_response.text:
                json_str = sug_response.text.split('window.baidu.sug(')[1].rstrip(')')
                suggestion_data = json.loads(json_str)
                if 's' in suggestion_data:
                    for sug in suggestion_data['s'][:5]:
                        if sug != keyword and sug not in related:
                            related.append(sug)

        except Exception as e:
            logger.warning("[Keyword] Related keywords error: %s", e)

        return list(set(related))[:KEYWORD_RESEARCH_MAX_RELATED]

    # ---------- 纯规则方法（无需异步） ----------

    def _detect_intent(self, keyword: str) -> KeywordIntent:
        """检测搜索意图"""
        informational_patterns = ['是什么', '怎么样', '为什么', '如何', '教程', '指南']
        transactional_patterns = ['购买', '价格', '多少钱', '优惠', '折扣', '下单']
        commercial_patterns = ['推荐', '排名', '对比', '评测', '哪个好', '品牌']

        for pattern in transactional_patterns:
            if pattern in keyword:
                return KeywordIntent.TRANSACTIONAL

        for pattern in commercial_patterns:
            if pattern in keyword:
                return KeywordIntent.COMMERCIAL

        for pattern in informational_patterns:
            if pattern in keyword:
                return KeywordIntent.INFORMATIONAL

        return KeywordIntent.INFORMATIONAL

    def _detect_type(self, keyword: str) -> KeywordType:
        """检测关键词类型"""
        if '怎么样' in keyword or '好不好' in keyword or '是什么' in keyword:
            return KeywordType.QUESTION

        if len(keyword) > 10:
            return KeywordType.LONG_TAIL

        if '品牌' in keyword or '排名' in keyword:
            return KeywordType.BRAND

        if '价格' in keyword or '多少钱' in keyword or '购买' in keyword:
            return KeywordType.PRODUCT

        return KeywordType.INDUSTRY

    def _generate_questions(self, keyword: str) -> List[str]:
        """生成相关问题"""
        base_word = keyword.replace('怎么样', '').replace('好不好', '').replace('是什么', '')
        return [
            f'{base_word}哪个牌子好？',
            f'{base_word}一般多少钱？',
            f'{base_word}怎么选？',
            f'{base_word}有什么优缺点？',
        ]

    def _generate_trend(self, keyword: str = None) -> List[Dict]:
        """生成趋势数据 - 结合季节因素"""
        trend = []
        now = datetime.now()

        seasonal_keywords = ['空调', '取暖', '羽绒服', '凉席', '火锅', '冰淇淋']
        is_seasonal = any(kw in keyword for kw in seasonal_keywords) if keyword else False

        for i in range(12):
            month_date = now - timedelta(days=30 * i)
            month = month_date.strftime('%Y-%m')
            month_num = month_date.month

            base_value = 100

            if is_seasonal:
                if '空调' in keyword or '凉席' in keyword or '冰淇淋' in keyword:
                    if month_num in [6, 7, 8]:
                        base_value = 180
                    elif month_num in [5, 9]:
                        base_value = 140
                    elif month_num in [12, 1, 2]:
                        base_value = 50
                elif '取暖' in keyword or '羽绒服' in keyword or '火锅' in keyword:
                    if month_num in [12, 1, 2]:
                        base_value = 180
                    elif month_num in [11, 3]:
                        base_value = 140
                    elif month_num in [6, 7, 8]:
                        base_value = 50

            trend.append({
                'month': month,
                'volume': base_value,
            })

        return list(reversed(trend))

    def _calculate_opportunity(self, volume: int, difficulty: float,
                               keyword_type: KeywordType) -> float:
        """计算机会得分：高搜索量 + 低难度 = 高机会"""
        volume_score = min(volume / 10000, 10)
        difficulty_score = (100 - difficulty) / 10

        # 长尾词加权
        type_multiplier = 1.5 if keyword_type == KeywordType.LONG_TAIL else 1.0

        return round((volume_score + difficulty_score) * type_multiplier, 2)

    def _calculate_geo_relevance(self, keyword: str, intent: KeywordIntent) -> float:
        """计算GEO相关度"""
        if intent == KeywordIntent.INFORMATIONAL:
            base_score = 0.8
        elif intent == KeywordIntent.COMMERCIAL:
            base_score = 0.6
        else:
            base_score = 0.4

        geo_boost_words = ['怎么样', '推荐', '排名', '对比', '评测', '是什么']
        for word in geo_boost_words:
            if word in keyword:
                base_score += 0.1

        return min(base_score, 1.0)

    # ---------- 数据库持久化 ----------

    async def _save_keyword(self, keyword: Keyword) -> None:
        """保存关键词到数据库（upsert：keyword 唯一时更新）"""
        engine = self._get_engine()
        if engine is None:
            return

        from sqlalchemy import text as sql_text

        upsert_sql = """
        INSERT INTO keyword_research_keywords
            (id, keyword, search_volume, difficulty, cpc, intent, keyword_type,
             related_keywords, questions, trend, competition_score,
             opportunity_score, geo_relevance, created_at, last_updated)
        VALUES
            (:id, :keyword, :search_volume, :difficulty, :cpc, :intent, :keyword_type,
             :related_keywords, :questions, :trend, :competition_score,
             :opportunity_score, :geo_relevance, :created_at, :last_updated)
        ON CONFLICT (keyword) DO UPDATE SET
            search_volume = EXCLUDED.search_volume,
            difficulty = EXCLUDED.difficulty,
            cpc = EXCLUDED.cpc,
            intent = EXCLUDED.intent,
            keyword_type = EXCLUDED.keyword_type,
            related_keywords = EXCLUDED.related_keywords,
            questions = EXCLUDED.questions,
            trend = EXCLUDED.trend,
            competition_score = EXCLUDED.competition_score,
            opportunity_score = EXCLUDED.opportunity_score,
            geo_relevance = EXCLUDED.geo_relevance,
            last_updated = EXCLUDED.last_updated
        """

        params = {
            'id': keyword.id,
            'keyword': keyword.keyword,
            'search_volume': keyword.search_volume,
            'difficulty': keyword.difficulty,
            'cpc': keyword.cpc,
            'intent': keyword.intent.value,
            'keyword_type': keyword.keyword_type.value,
            'related_keywords': json.dumps(keyword.related_keywords, ensure_ascii=False),
            'questions': json.dumps(keyword.questions, ensure_ascii=False),
            'trend': json.dumps(keyword.trend, ensure_ascii=False),
            'competition_score': keyword.competition_score,
            'opportunity_score': keyword.opportunity_score,
            'geo_relevance': keyword.geo_relevance,
            'created_at': keyword.created_at,
            'last_updated': keyword.last_updated,
        }

        try:
            async with engine.begin() as conn:
                await conn.execute(sql_text(upsert_sql), params)
        except Exception as e:
            logger.error("[KeywordResearch] 保存关键词失败: %s", e)

    async def _save_report(self, report: KeywordResearchReport) -> None:
        """保存研究报告"""
        engine = self._get_engine()
        if engine is None:
            return

        from sqlalchemy import text as sql_text

        insert_sql = """
        INSERT INTO keyword_research_reports
            (id, seed_keyword, industry, discovered_keywords, recommendations,
             content_gaps, created_at)
        VALUES
            (:id, :seed_keyword, :industry, :discovered_keywords, :recommendations,
             :content_gaps, :created_at)
        """

        params = {
            'id': report.id,
            'seed_keyword': report.seed_keyword,
            'industry': report.industry,
            'discovered_keywords': json.dumps(
                [self._keyword_to_dict(k) for k in report.discovered_keywords],
                ensure_ascii=False,
            ),
            'recommendations': json.dumps(report.recommendations, ensure_ascii=False),
            'content_gaps': json.dumps(report.content_gaps, ensure_ascii=False),
            'created_at': report.created_at,
        }

        try:
            async with engine.begin() as conn:
                await conn.execute(sql_text(insert_sql), params)
        except Exception as e:
            logger.error("[KeywordResearch] 保存研究报告失败: %s", e)

    # ---------- 推荐与内容空白 ----------

    def _generate_recommendations(self, keywords: List[Keyword]) -> List[Dict]:
        """生成关键词推荐策略：高机会 / GEO优化 / 长尾 三类"""
        recommendations = []

        # 按机会得分排序
        sorted_keywords = sorted(keywords, key=lambda x: x.opportunity_score, reverse=True)

        # 高机会关键词
        high_opportunity = sorted_keywords[:5]
        recommendations.append({
            'type': 'high_opportunity',
            'title': '高机会关键词',
            'description': '这些关键词搜索量高、竞争度低，建议优先布局',
            'keywords': [
                {'keyword': k.keyword, 'volume': k.search_volume,
                 'difficulty': k.difficulty, 'opportunity': k.opportunity_score}
                for k in high_opportunity
            ],
        })

        # GEO优化关键词
        geo_keywords = [k for k in keywords if k.geo_relevance > 0.7]
        geo_keywords.sort(key=lambda x: x.geo_relevance, reverse=True)
        recommendations.append({
            'type': 'geo_optimized',
            'title': 'GEO优化关键词',
            'description': '这些关键词容易被AI引用，适合GEO优化',
            'keywords': [
                {'keyword': k.keyword, 'geo_relevance': k.geo_relevance,
                 'intent': k.intent.value}
                for k in geo_keywords[:5]
            ],
        })

        # 长尾关键词
        long_tail = [k for k in keywords if k.keyword_type == KeywordType.LONG_TAIL]
        long_tail.sort(key=lambda x: x.search_volume, reverse=True)
        recommendations.append({
            'type': 'long_tail',
            'title': '长尾关键词',
            'description': '长尾关键词竞争度低，转化率高',
            'keywords': [
                {'keyword': k.keyword, 'volume': k.search_volume}
                for k in long_tail[:5]
            ],
        })

        return recommendations

    def _find_content_gaps(self, keywords: List[Keyword]) -> List[Dict]:
        """发现内容空白：高搜索量但低GEO相关度的关键词"""
        gaps = []
        for keyword in keywords:
            if keyword.search_volume > 5000 and keyword.geo_relevance < 0.5:
                gaps.append({
                    'keyword': keyword.keyword,
                    'type': 'geo_opportunity',
                    'description': f'该关键词搜索量高({keyword.search_volume})，但GEO优化不足',
                    'suggestion': '创建GEO优化内容，提升AI引用概率',
                })
        return gaps[:5]

    # ---------- 序列化辅助 ----------

    def _keyword_to_dict(self, keyword: Keyword) -> Dict:
        """将 Keyword 对象转换为字典"""
        return {
            'id': keyword.id,
            'keyword': keyword.keyword,
            'search_volume': keyword.search_volume,
            'difficulty': keyword.difficulty,
            'cpc': keyword.cpc,
            'intent': keyword.intent.value,
            'keyword_type': keyword.keyword_type.value,
            'related_keywords': keyword.related_keywords,
            'questions': keyword.questions,
            'trend': keyword.trend,
            'competition_score': keyword.competition_score,
            'opportunity_score': keyword.opportunity_score,
            'geo_relevance': keyword.geo_relevance,
            'created_at': keyword.created_at.isoformat() if keyword.created_at else None,
            'last_updated': keyword.last_updated.isoformat() if keyword.last_updated else None,
        }

    @staticmethod
    def _row_to_keyword_dict(row) -> Dict:
        """数据库行转字典（按字典顺序访问，避免依赖位置下标）"""
        mapping = row._mapping if hasattr(row, '_mapping') else {}
        if mapping:
            return {
                'id': mapping.get('id'),
                'keyword': mapping.get('keyword'),
                'search_volume': mapping.get('search_volume'),
                'difficulty': mapping.get('difficulty'),
                'cpc': mapping.get('cpc'),
                'intent': mapping.get('intent'),
                'keyword_type': mapping.get('keyword_type'),
                'opportunity_score': mapping.get('opportunity_score'),
                'geo_relevance': mapping.get('geo_relevance'),
            }
        # 回退：位置下标（与建表列顺序保持一致）
        return {
            'id': row[0],
            'keyword': row[1],
            'search_volume': row[2],
            'difficulty': row[3],
            'cpc': row[4],
            'intent': row[5],
            'keyword_type': row[6],
            'opportunity_score': row[11],
            'geo_relevance': row[12],
        }

    # ---------- 查询接口 ----------

    async def get_keyword_suggestions(self, query: str, limit: int = 10) -> List[Dict]:
        """获取关键词建议（按搜索量倒序，模糊匹配）"""
        await self.ensure_table()
        engine = self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        sql = """
        SELECT id, keyword, search_volume, difficulty, cpc, intent, keyword_type,
               related_keywords, questions, trend, competition_score,
               opportunity_score, geo_relevance, created_at, last_updated
        FROM keyword_research_keywords
        WHERE keyword LIKE :query
        ORDER BY search_volume DESC
        LIMIT :limit
        """

        try:
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), {'query': f'%{query}%', 'limit': limit})
                result = rows.fetchall()
        except Exception as e:
            logger.error("[KeywordResearch] get_keyword_suggestions error: %s", e)
            return []

        return [self._row_to_keyword_dict(row) for row in result]

    async def get_geo_keywords(self, industry: str = None, limit: int = 50) -> List[Dict]:
        """获取GEO优化关键词（geo_relevance >= 0.7）"""
        await self.ensure_table()
        engine = self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        sql = """
        SELECT id, keyword, search_volume, difficulty, cpc, intent, keyword_type,
               related_keywords, questions, trend, competition_score,
               opportunity_score, geo_relevance, created_at, last_updated
        FROM keyword_research_keywords
        WHERE geo_relevance >= 0.7
        ORDER BY geo_relevance DESC, search_volume DESC
        LIMIT :limit
        """

        try:
            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), {'limit': limit})
                result = rows.fetchall()
        except Exception as e:
            logger.error("[KeywordResearch] get_geo_keywords error: %s", e)
            return []

        return [self._row_to_keyword_dict(row) for row in result]

    async def create_keyword_group(self, name: str, description: str,
                                   keywords: List[str]) -> KeywordGroup:
        """创建关键词分组，并计算分组统计（总搜索量 / 平均难度）"""
        await self.ensure_table()
        engine = self._get_engine()

        total_volume = 0
        difficulties: List[float] = []

        if engine is not None:
            from sqlalchemy import text as sql_text

            select_sql = """
            SELECT search_volume, difficulty
            FROM keyword_research_keywords
            WHERE keyword = :kw
            """
            try:
                async with engine.connect() as conn:
                    for kw in keywords:
                        rows = await conn.execute(sql_text(select_sql), {'kw': kw})
                        row = rows.fetchone()
                        if row:
                            mapping = row._mapping if hasattr(row, '_mapping') else {}
                            if mapping:
                                total_volume += mapping.get('search_volume') or 0
                                diff = mapping.get('difficulty')
                            else:
                                total_volume += row[0] or 0
                                diff = row[1]
                            if diff is not None:
                                difficulties.append(diff)
            except Exception as e:
                logger.error("[KeywordResearch] create_keyword_group select error: %s", e)

        avg_difficulty = sum(difficulties) / len(difficulties) if difficulties else 50

        group = KeywordGroup(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            keywords=keywords,
            total_volume=total_volume,
            avg_difficulty=avg_difficulty,
            created_at=datetime.now(),
        )

        # 保存分组
        if engine is not None:
            from sqlalchemy import text as sql_text

            insert_sql = """
            INSERT INTO keyword_research_groups
                (id, name, description, keywords, total_volume, avg_difficulty, created_at)
            VALUES
                (:id, :name, :description, :keywords, :total_volume, :avg_difficulty, :created_at)
            """
            params = {
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'keywords': json.dumps(group.keywords, ensure_ascii=False),
                'total_volume': group.total_volume,
                'avg_difficulty': group.avg_difficulty,
                'created_at': group.created_at,
            }
            try:
                async with engine.begin() as conn:
                    await conn.execute(sql_text(insert_sql), params)
            except Exception as e:
                logger.error("[KeywordResearch] 保存关键词分组失败: %s", e)

        return group


# ==================== 单例 ====================

_keyword_research_service: Optional[KeywordResearchService] = None


def get_keyword_research_service() -> KeywordResearchService:
    """获取关键词研究服务单例"""
    global _keyword_research_service
    if _keyword_research_service is None:
        _keyword_research_service = KeywordResearchService()
    return _keyword_research_service
