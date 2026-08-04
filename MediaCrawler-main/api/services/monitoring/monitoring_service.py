# -*- coding: utf-8 -*-
"""
效果监控服务（迁移自 GEO-main/geo_system/backend/monitoring_service.py）

对应 PRD 模块：效果监控（搜索排名 / AI 引用 / 流量分析）。

适配点（相对原 GEO-main 实现）：
1. 数据库层：原文件使用 psycopg2 + 同步连接（PostgreSQLDatabase.get_connection），
   现统一改为 MediaCrawler 的异步 PostgreSQL 引擎：
       from database.db_session import get_async_engine
       import config
       engine = get_async_engine(config.SAVE_DATA_OPTION)
       from sqlalchemy import text as sql_text
       async with engine.connect() as conn:
           rows = await conn.execute(sql_text("SELECT ..."), {...})
2. 全部业务方法改为 `async def`；`batch_check_citation` 中的 `time.sleep` 改为
   `asyncio.sleep`，避免阻塞事件循环。
3. 日志：`print` 全部替换为 `logging.getLogger(__name__)`。
4. 配置：原文件中硬编码的 lk888.ai / Agent API key 改为 `os.environ.get(...)`
   读取，不再写入任何明文密钥；默认品牌名等非敏感常量保留。
5. 表结构：保留原 6 张表（search_rank_records / ai_citation_records /
   traffic_records / monitoring_configs / citation_keywords / citation_batches），
   全部使用 `CREATE TABLE IF NOT EXISTS`，集中在 `ensure_table()` 方法中实现，
   在第一次访问数据库时按需调用（异步）。
6. 不创建 __init__.py / 路由文件 / main.py 修改（由调用方统一处理）。
7. 末尾提供单例：`_monitoring_service = None` + `get_monitoring_service()`。
"""

import asyncio
import json
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


# ==================== 枚举 ====================

class MonitorType(Enum):
    """监控类型"""
    SEARCH_RANK = "search_rank"      # 搜索排名
    AI_CITATION = "ai_citation"      # AI引用
    TRAFFIC = "traffic"              # 流量


class SearchEngine(Enum):
    """搜索引擎"""
    BAIDU = "baidu"
    GOOGLE = "google"
    BING = "bing"
    SOGOU = "sogou"
    WECHAT = "wechat"  # 微信搜一搜


class AIPlatform(Enum):
    """AI平台"""
    DOUBAO = "doubao"                 # 豆包
    DEEPSEEK = "deepseek"             # DeepSeek
    CHATGPT = "chatgpt"               # ChatGPT
    WENXINYIYAN = "wenxinyiyan"       # 文心一言
    TONGYIQIANWEN = "tongyiqianwen"   # 通义千问
    KIMI = "kimi"                     # Kimi


# ==================== 数据类 ====================

@dataclass
class SearchRankRecord:
    """搜索排名记录"""
    keyword: str
    search_engine: SearchEngine
    rank: int
    url: str
    title: str
    snippet: str
    checked_at: datetime
    id: Optional[int] = None
    change: int = 0  # 排名变化


@dataclass
class AICitationRecord:
    """AI引用记录"""
    platform: AIPlatform
    query: str
    brand_mentioned: bool
    citation_url: str
    citation_content: str
    context: str
    checked_at: datetime
    id: Optional[int] = None
    sentiment: str = "neutral"  # positive, neutral, negative


@dataclass
class TrafficRecord:
    """流量记录"""
    source: str
    medium: str
    campaign: str
    visitors: int
    pageviews: int
    bounce_rate: float
    avg_duration: float
    conversions: int
    recorded_at: datetime
    id: Optional[int] = None


# ==================== 配置常量（非敏感） ====================

# 默认品牌名（可通过环境变量覆盖）
DEFAULT_BRAND_NAME = os.environ.get("MONITOR_DEFAULT_BRAND", "织然家具")

# AI 查询引导 system prompt（非敏感）
_AI_SYSTEM_PROMPT = (
    "你是一个真实的用户，正在使用 AI 搜索查找信息。"
    "请像普通 AI 助手回答用户问题一样，给出详细、自然的回答。"
    "回答中可以自然地提及相关品牌、产品或服务（如果适用）。"
)

# 支持的 AI 平台数量（用于覆盖率统计）
_TOTAL_AI_PLATFORMS = 6

# 模型映射（非敏感，仅为模型选择，不含密钥）
_MODEL_MAP_PRIMARY = {
    AIPlatform.CHATGPT: "gpt-5.4",
    AIPlatform.DEEPSEEK: "gpt-5.4",         # 主 API 不直接支持 deepseek，用 gpt-5.4 替代
    AIPlatform.KIMI: "kimi-k3",
    AIPlatform.DOUBAO: "doubao-seed-2-0-pro-260215",
    AIPlatform.WENXINYIYAN: "gpt-5.4",      # 用 gpt-5.4 替代
    AIPlatform.TONGYIQIANWEN: "gpt-5.4",    # 用 gpt-5.4 替代
}
_MODEL_MAP_FALLBACK = {
    AIPlatform.CHATGPT: "gpt-4o-mini",
    AIPlatform.DEEPSEEK: "deepseek-chat",
    AIPlatform.KIMI: "moonshot-v1-8k",
    AIPlatform.DOUBAO: "doubao-pro-32k",
    AIPlatform.WENXINYIYAN: "ernie-bot-turbo",
    AIPlatform.TONGYIQIANWEN: "qwen-turbo",
}


# ==================== 服务 ====================

class MonitoringService:
    """效果监控服务（异步，基于 MediaCrawler PostgreSQL 引擎）"""

    def __init__(self):
        # 不在 __init__ 中连接数据库（避免同步构造时 IO）；首次访问时 ensure_table()
        self._tables_ready = False

    # ---------------- 数据库基础设施 ----------------

    async def _get_engine(self):
        """获取 MediaCrawler 异步引擎"""
        try:
            from database.db_session import get_async_engine
            import config
            return get_async_engine(config.SAVE_DATA_OPTION)
        except Exception as e:
            logger.error(f"[Monitor] 获取数据库引擎失败: {e}")
            return None

    async def ensure_table(self) -> bool:
        """确保所有监控相关表存在（幂等）。

        使用 `CREATE TABLE IF NOT EXISTS`，安全可重复执行。
        """
        if self._tables_ready:
            return True

        engine = await self._get_engine()
        if engine is None:
            return False

        from sqlalchemy import text as sql_text

        statements = [
            # 搜索排名表
            '''
            CREATE TABLE IF NOT EXISTS search_rank_records (
                id SERIAL PRIMARY KEY,
                keyword TEXT,
                search_engine TEXT,
                rank INTEGER,
                url TEXT,
                title TEXT,
                snippet TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                change INTEGER DEFAULT 0
            )
            ''',
            # AI引用表
            '''
            CREATE TABLE IF NOT EXISTS ai_citation_records (
                id SERIAL PRIMARY KEY,
                platform TEXT,
                query TEXT,
                brand_mentioned BOOLEAN,
                citation_url TEXT,
                citation_content TEXT,
                context TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sentiment TEXT DEFAULT 'neutral'
            )
            ''',
            # 流量表
            '''
            CREATE TABLE IF NOT EXISTS traffic_records (
                id SERIAL PRIMARY KEY,
                source TEXT,
                medium TEXT,
                campaign TEXT,
                visitors INTEGER,
                pageviews INTEGER,
                bounce_rate REAL,
                avg_duration REAL,
                conversions INTEGER,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
            # 监控配置表
            '''
            CREATE TABLE IF NOT EXISTS monitoring_configs (
                id SERIAL PRIMARY KEY,
                monitor_type TEXT,
                target TEXT,
                search_engine TEXT,
                platform TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                check_interval INTEGER DEFAULT 3600,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
            # AI引用检测关键词表
            '''
            CREATE TABLE IF NOT EXISTS citation_keywords (
                id SERIAL PRIMARY KEY,
                keyword TEXT NOT NULL UNIQUE,
                brand_name TEXT,
                category TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                last_checked_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
            # 批量检测批次表
            '''
            CREATE TABLE IF NOT EXISTS citation_batches (
                id SERIAL PRIMARY KEY,
                batch_name TEXT,
                platform TEXT,
                total_queries INTEGER DEFAULT 0,
                mentioned_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
        ]

        try:
            async with engine.begin() as conn:
                for stmt in statements:
                    await conn.execute(sql_text(stmt))
            self._tables_ready = True
            return True
        except Exception as e:
            logger.error(f"[Monitor] ensure_table 失败: {e}")
            return False

    # ==================== 搜索排名监控 ====================

    async def check_search_rank(
        self,
        keyword: str,
        search_engine: Any = SearchEngine.BAIDU,
        brand_name: str = "",
    ) -> List[Dict[str, Any]]:
        """
        检查关键词搜索排名

        Args:
            keyword: 关键词
            search_engine: 搜索引擎（接受 SearchEngine 枚举或字符串，如 "baidu"）
            brand_name: 品牌名（用于上下文，不影响排名查询本身）

        Returns:
            搜索结果列表
        """
        # 兼容字符串入参（router 传字符串），统一转为枚举
        if isinstance(search_engine, str):
            try:
                search_engine = SearchEngine(search_engine.lower())
            except ValueError:
                logger.warning(f"[Monitor] 不支持的搜索引擎 {search_engine}，回退到百度")
                search_engine = SearchEngine.BAIDU

        results: List[Dict[str, Any]] = []

        try:
            if search_engine == SearchEngine.BAIDU:
                results = self._check_baidu_rank(keyword)
            elif search_engine == SearchEngine.BING:
                results = self._check_bing_rank(keyword)
            elif search_engine == SearchEngine.SOGOU:
                results = self._check_sogou_rank(keyword)

            # 保存到数据库
            for i, result in enumerate(results[:10], 1):
                record = SearchRankRecord(
                    keyword=keyword,
                    search_engine=search_engine,
                    rank=i,
                    url=result.get('url', ''),
                    title=result.get('title', ''),
                    snippet=result.get('snippet', ''),
                    checked_at=datetime.now(),
                )
                await self.save_search_rank(record)

        except Exception as e:
            logger.warning(f"[Monitor] 搜索排名检查失败 keyword={keyword}: {e}")

        return results

    def _check_baidu_rank(self, keyword: str) -> List[Dict[str, Any]]:
        """检查百度排名 - 使用真实爬虫"""
        from bs4 import BeautifulSoup

        encoded_keyword = urllib.parse.quote(keyword)
        url = f"https://www.baidu.com/s?wd={encoded_keyword}&pn=0&rn=10"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'

        soup = BeautifulSoup(response.text, 'lxml')
        results: List[Dict[str, Any]] = []

        for item in soup.select('.result.c-container'):
            title_tag = item.select_one('h3.t>a')
            snippet_tag = item.select_one('.c-abstract')

            if title_tag:
                title = title_tag.get_text(strip=True)
                link = title_tag.get('href', '')

                real_url = link
                if link.startswith('/link?url='):
                    try:
                        real_url = urllib.parse.unquote(link.split('/link?url=')[1])
                    except Exception:
                        pass

                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ''

                results.append({
                    'url': real_url,
                    'title': title,
                    'snippet': snippet,
                })

            if len(results) >= 10:
                break

        return results

    def _check_bing_rank(self, keyword: str) -> List[Dict[str, Any]]:
        """检查必应排名 - 使用真实爬虫"""
        from bs4 import BeautifulSoup

        encoded_keyword = urllib.parse.quote(keyword)
        url = f"https://www.bing.com/search?q={encoded_keyword}&count=10"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'

        soup = BeautifulSoup(response.text, 'lxml')
        results: List[Dict[str, Any]] = []

        for item in soup.select('.b_algo'):
            title_tag = item.select_one('h2>a')
            snippet_tag = item.select_one('.b_caption p')

            if title_tag:
                results.append({
                    'url': title_tag.get('href', ''),
                    'title': title_tag.get_text(strip=True),
                    'snippet': snippet_tag.get_text(strip=True) if snippet_tag else '',
                })

            if len(results) >= 10:
                break

        return results

    def _check_sogou_rank(self, keyword: str) -> List[Dict[str, Any]]:
        """检查搜狗排名 - 使用真实爬虫"""
        from bs4 import BeautifulSoup

        encoded_keyword = urllib.parse.quote(keyword)
        url = f"https://www.sogou.com/web?query={encoded_keyword}&page=1"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'

        soup = BeautifulSoup(response.text, 'lxml')
        results: List[Dict[str, Any]] = []

        for item in soup.select('.results .vrwrap'):
            title_tag = item.select_one('h3>a')
            snippet_tag = item.select_one('.content')

            if title_tag:
                results.append({
                    'url': title_tag.get('href', ''),
                    'title': title_tag.get_text(strip=True),
                    'snippet': snippet_tag.get_text(strip=True) if snippet_tag else '',
                })

            if len(results) >= 10:
                break

        return results

    async def save_search_rank(self, record: SearchRankRecord) -> None:
        """保存搜索排名记录"""
        if not await self.ensure_table():
            return

        engine = await self._get_engine()
        if engine is None:
            return

        from sqlalchemy import text as sql_text

        try:
            async with engine.begin() as conn:
                # 检查上次排名
                last_row = await conn.execute(
                    sql_text(
                        "SELECT rank FROM search_rank_records "
                        "WHERE keyword = :keyword AND search_engine = :engine "
                        "ORDER BY checked_at DESC LIMIT 1"
                    ),
                    {"keyword": record.keyword, "engine": record.search_engine.value},
                )
                last_rank = last_row.scalar()
                if last_rank is not None:
                    record.change = last_rank - record.rank  # 排名上升为正

                await conn.execute(
                    sql_text(
                        "INSERT INTO search_rank_records "
                        "(keyword, search_engine, rank, url, title, snippet, checked_at, change) "
                        "VALUES (:keyword, :engine, :rank, :url, :title, :snippet, :checked_at, :change)"
                    ),
                    {
                        "keyword": record.keyword,
                        "engine": record.search_engine.value,
                        "rank": record.rank,
                        "url": record.url,
                        "title": record.title,
                        "snippet": record.snippet,
                        "checked_at": record.checked_at,
                        "change": record.change,
                    },
                )
        except Exception as e:
            logger.error(f"[Monitor] save_search_rank 失败: {e}")

    async def get_rank_history(self, keyword: str, search_engine: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """获取排名历史（按关键词+搜索引擎过滤，倒序取最近 limit 条）。

        供 /api/monitoring/search-rank 端点使用。
        """
        if not await self.ensure_table():
            return []

        engine = await self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        try:
            async with engine.connect() as conn:
                if search_engine:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, keyword, search_engine, rank, url, title, snippet, checked_at, change "
                            "FROM search_rank_records "
                            "WHERE keyword = :keyword AND search_engine = :se "
                            "ORDER BY checked_at DESC LIMIT :l"
                        ),
                        {"keyword": keyword, "se": search_engine, "l": limit},
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, keyword, search_engine, rank, url, title, snippet, checked_at, change "
                            "FROM search_rank_records "
                            "WHERE keyword = :keyword "
                            "ORDER BY checked_at DESC LIMIT :l"
                        ),
                        {"keyword": keyword, "l": limit},
                    )
                return [self._row_to_search_rank(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[Monitor] get_rank_history 失败: {e}")
            return []

    async def get_latest_ranks(self, keyword: str) -> List[Dict[str, Any]]:
        """获取最新排名"""
        if not await self.ensure_table():
            return []

        engine = await self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, keyword, search_engine, rank, url, title, snippet, checked_at, change "
                        "FROM search_rank_records "
                        "WHERE keyword = :keyword "
                        "ORDER BY checked_at DESC LIMIT 10"
                    ),
                    {"keyword": keyword},
                )
                return [self._row_to_search_rank(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[Monitor] get_latest_ranks 失败: {e}")
            return []

    @staticmethod
    def _row_to_search_rank(row) -> Dict[str, Any]:
        """数据库行转字典"""
        return {
            'id': row[0],
            'keyword': row[1],
            'search_engine': row[2],
            'rank': row[3],
            'url': row[4],
            'title': row[5],
            'snippet': row[6],
            'checked_at': row[7],
            'change': row[8],
        }

    # ==================== AI 引用追踪 ====================

    async def check_ai_citation(
        self,
        platform: Any,
        query: str,
        brand_name: str = DEFAULT_BRAND_NAME,
    ) -> Dict[str, Any]:
        """
        检查 AI 是否引用了品牌

        Args:
            platform: AI 平台（接受 AIPlatform 枚举或字符串，如 "chatgpt"）
            query: 查询问题
            brand_name: 品牌名称

        Returns:
            引用分析结果
        """
        # 兼容字符串入参（router 传字符串），统一转为枚举
        if isinstance(platform, str):
            try:
                platform = AIPlatform(platform.lower())
            except ValueError:
                return {'mentioned': False, 'error': f'不支持的 AI 平台: {platform}'}

        try:
            # 调用 AI 平台 API 获取回答（同步网络请求，放到默认线程池避免阻塞事件循环）
            response = await asyncio.to_thread(self._query_ai_platform, platform, query)

            # 分析回答中是否提及品牌
            analysis = self._analyze_citation(response, brand_name)

            # 保存记录
            record = AICitationRecord(
                platform=platform,
                query=query,
                brand_mentioned=analysis['mentioned'],
                citation_url=analysis.get('url', ''),
                citation_content=analysis.get('content', ''),
                context=response,
                checked_at=datetime.now(),
                sentiment=analysis.get('sentiment', 'neutral'),
            )
            await self.save_ai_citation(record)

            return analysis

        except Exception as e:
            logger.warning(f"[Monitor] AI 引用检查失败 platform={platform.value}: {e}")
            return {'mentioned': False, 'error': str(e)}

    def _query_ai_platform(self, platform: AIPlatform, query: str) -> str:
        """
        查询 AI 平台 - 使用 OpenAI 兼容 API。

        优先使用环境变量 `MONITOR_AI_PRIMARY_BASE` + `MONITOR_AI_PRIMARY_KEY`；
        若失败回退到 `OPENAI_API_KEY` + `OPENAI_BASE_URL`。

        所有密钥均来自环境变量，不在代码中硬编码。
        """
        system_prompt = _AI_SYSTEM_PROMPT

        # 第 1 次尝试：主 API（默认指向项目内置 AI 服务，可通过环境变量覆盖）
        primary_base = os.environ.get("MONITOR_AI_PRIMARY_BASE", "").rstrip('/')
        primary_key = os.environ.get("MONITOR_AI_PRIMARY_KEY", "")

        if primary_base and primary_key:
            model = _MODEL_MAP_PRIMARY.get(platform, 'gpt-5.4')
            headers = {
                'Authorization': f'Bearer {primary_key}',
                'Content-Type': 'application/json',
            }
            payload = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': query},
                ],
                'temperature': 0.7,
                'max_tokens': 1500,
            }
            try:
                response = requests.post(
                    f'{primary_base}/chat/completions',
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                if response.status_code == 200:
                    result = response.json()
                    return result['choices'][0]['message']['content']
                logger.warning(
                    f"[Monitor] 主 AI API 返回 HTTP {response.status_code}: "
                    f"{response.text[:200]}，尝试 fallback"
                )
            except requests.exceptions.RequestException as e:
                logger.warning(f"[Monitor] 主 AI API 网络错误: {e}，尝试 fallback")

        # 第 2 次尝试：环境变量配置的兼容 API (OPENAI_API_KEY + OPENAI_BASE_URL)
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("AGENT_API_KEY")
        api_base = os.environ.get("OPENAI_BASE_URL", "").rstrip('/')

        if api_key and api_base:
            model2 = _MODEL_MAP_FALLBACK.get(platform, 'gpt-4o-mini')
            headers2 = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            }
            payload2 = {
                'model': model2,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': query},
                ],
                'temperature': 0.7,
                'max_tokens': 1500,
            }
            try:
                response = requests.post(
                    f'{api_base}/chat/completions',
                    headers=headers2,
                    json=payload2,
                    timeout=30,
                )
                if response.status_code == 200:
                    result = response.json()
                    return result['choices'][0]['message']['content']
                raise RuntimeError(
                    f"Agent API 返回 HTTP {response.status_code}: {response.text[:200]}"
                )
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"Agent API 网络错误: {e}")

        raise RuntimeError(
            "所有 AI API 均不可用。请检查环境变量 MONITOR_AI_PRIMARY_KEY/MONITOR_AI_PRIMARY_BASE "
            "或 OPENAI_API_KEY/OPENAI_BASE_URL 配置"
        )

    def _analyze_citation(self, response: str, brand_name: str) -> Dict[str, Any]:
        """分析 AI 回答中的品牌引用"""
        mentioned = brand_name in response

        analysis: Dict[str, Any] = {
            'mentioned': mentioned,
            'brand_name': brand_name,
        }

        if mentioned:
            # 提取引用内容上下文
            sentences = response.split('。')
            for sentence in sentences:
                if brand_name in sentence:
                    analysis['content'] = sentence.strip()
                    break

            # 简单情感分析
            positive_words = ['好', '优秀', '推荐', '专业', '不错', '受欢迎']
            negative_words = ['差', '不好', '问题', '投诉']

            content = analysis.get('content', '')
            pos_count = sum(1 for w in positive_words if w in content)
            neg_count = sum(1 for w in negative_words if w in content)

            if pos_count > neg_count:
                analysis['sentiment'] = 'positive'
            elif neg_count > pos_count:
                analysis['sentiment'] = 'negative'
            else:
                analysis['sentiment'] = 'neutral'

        return analysis

    async def save_ai_citation(self, record: AICitationRecord) -> None:
        """保存 AI 引用记录"""
        if not await self.ensure_table():
            return

        engine = await self._get_engine()
        if engine is None:
            return

        from sqlalchemy import text as sql_text

        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO ai_citation_records "
                        "(platform, query, brand_mentioned, citation_url, citation_content, "
                        " context, checked_at, sentiment) "
                        "VALUES (:platform, :query, :mentioned, :url, :content, "
                        "        :context, :checked_at, :sentiment)"
                    ),
                    {
                        "platform": record.platform.value,
                        "query": record.query,
                        "mentioned": record.brand_mentioned,
                        "url": record.citation_url,
                        "content": record.citation_content,
                        "context": record.context,
                        "checked_at": record.checked_at,
                        "sentiment": record.sentiment,
                    },
                )
        except Exception as e:
            logger.error(f"[Monitor] save_ai_citation 失败: {e}")

    # ==================== 批量检测功能 ====================

    async def add_citation_keyword(
        self,
        keyword: str,
        brand_name: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """添加一个检测关键词"""
        if not await self.ensure_table():
            return {'success': False, 'error': '数据库不可用'}

        engine = await self._get_engine()
        if engine is None:
            return {'success': False, 'error': '数据库不可用'}

        from sqlalchemy import text as sql_text

        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    sql_text(
                        "INSERT INTO citation_keywords (keyword, brand_name, category) "
                        "VALUES (:keyword, :brand_name, :category) ON CONFLICT DO NOTHING"
                    ),
                    {"keyword": keyword, "brand_name": brand_name, "category": category},
                )
                added = (result.rowcount or 0) > 0
                return {'success': True, 'added': added, 'keyword': keyword}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def add_citation_keywords_batch(
        self,
        keywords: List[str],
        brand_name: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """批量添加检测关键词"""
        if not await self.ensure_table():
            return {'success': False, 'error': '数据库不可用'}

        engine = await self._get_engine()
        if engine is None:
            return {'success': False, 'error': '数据库不可用'}

        from sqlalchemy import text as sql_text

        added = 0
        skipped = 0
        try:
            async with engine.begin() as conn:
                for kw in keywords:
                    kw = (kw or '').strip()
                    if not kw:
                        continue
                    result = await conn.execute(
                        sql_text(
                            "INSERT INTO citation_keywords (keyword, brand_name, category) "
                            "VALUES (:keyword, :brand_name, :category) ON CONFLICT DO NOTHING"
                        ),
                        {"keyword": kw, "brand_name": brand_name, "category": category},
                    )
                    if (result.rowcount or 0) > 0:
                        added += 1
                    else:
                        skipped += 1
                return {
                    'success': True,
                    'added': added,
                    'skipped': skipped,
                    'total': len(keywords),
                }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def list_citation_keywords(self, only_active: bool = True) -> List[Dict[str, Any]]:
        """列出所有检测关键词"""
        if not await self.ensure_table():
            return []

        engine = await self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        try:
            async with engine.connect() as conn:
                if only_active:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, keyword, brand_name, category, is_active, "
                            "       last_checked_at, created_at "
                            "FROM citation_keywords WHERE is_active=TRUE ORDER BY id DESC"
                        ),
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, keyword, brand_name, category, is_active, "
                            "       last_checked_at, created_at "
                            "FROM citation_keywords ORDER BY id DESC"
                        ),
                    )
                result = []
                for r in rows.fetchall():
                    result.append({
                        'id': r[0],
                        'keyword': r[1],
                        'brand_name': r[2],
                        'category': r[3],
                        'is_active': r[4],
                        'last_checked_at': r[5],
                        'created_at': r[6],
                    })
                return result
        except Exception as e:
            logger.warning(f"[Monitor] list_citation_keywords 失败: {e}")
            return []

    async def delete_citation_keyword(self, keyword_id: int) -> Dict[str, Any]:
        """删除检测关键词"""
        if not await self.ensure_table():
            return {'success': False, 'deleted': False}

        engine = await self._get_engine()
        if engine is None:
            return {'success': False, 'deleted': False}

        from sqlalchemy import text as sql_text

        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    sql_text("DELETE FROM citation_keywords WHERE id=:id"),
                    {"id": keyword_id},
                )
                deleted = (result.rowcount or 0) > 0
                return {'success': deleted, 'deleted': deleted}
        except Exception as e:
            logger.warning(f"[Monitor] delete_citation_keyword 失败: {e}")
            return {'success': False, 'deleted': False}

    async def batch_check_citation(
        self,
        keywords: Optional[List[str]] = None,
        platforms: Optional[List[str]] = None,
        brand_name: str = DEFAULT_BRAND_NAME,
        batch_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        批量检测 AI 引用率

        - 对每个关键词 × 每个平台进行一次 AI 查询
        - 自动保存到 ai_citation_records，并生成 citation_batches 记录
        """
        if not await self.ensure_table():
            return {'success': False, 'error': '数据库不可用'}

        # 默认参数
        if keywords is None:
            keywords = [k['keyword'] for k in await self.list_citation_keywords(only_active=True)]
        if not keywords:
            return {'success': False, 'error': '没有可检测的关键词'}

        # 默认平台：ChatGPT
        if platforms is None:
            platforms = ['chatgpt']

        # 转换平台字符串 -> AIPlatform 枚举
        platform_enums: List[AIPlatform] = []
        for p in platforms:
            try:
                platform_enums.append(AIPlatform(p))
            except ValueError:
                logger.warning(f"[Monitor] 不支持的平台 {p}，跳过")

        if not platform_enums:
            return {'success': False, 'error': '没有有效的平台'}

        total_queries = len(keywords) * len(platform_enums)
        batch_name = batch_name or f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        engine = await self._get_engine()
        if engine is None:
            return {'success': False, 'error': '数据库不可用'}

        from sqlalchemy import text as sql_text

        # 创建批次记录
        try:
            async with engine.begin() as conn:
                row = await conn.execute(
                    sql_text(
                        "INSERT INTO citation_batches "
                        "(batch_name, platform, total_queries, mentioned_count, status, started_at) "
                        "VALUES (:name, :platform, :total, 0, 'running', :started) "
                        "RETURNING id"
                    ),
                    {
                        "name": batch_name,
                        "platform": ','.join(platforms),
                        "total": total_queries,
                        "started": datetime.now(),
                    },
                )
                batch_id = row.scalar()
        except Exception as e:
            logger.error(f"[Monitor] 创建批次记录失败: {e}")
            return {'success': False, 'error': str(e)}

        logger.info(f"[Monitor] 开始批量检测 batch_id={batch_id} 共 {total_queries} 个查询")

        results: List[Dict[str, Any]] = []
        mentioned_count = 0

        for platform in platform_enums:
            for keyword in keywords:
                try:
                    analysis = await self.check_ai_citation(
                        platform=platform,
                        query=keyword,
                        brand_name=brand_name,
                    )
                    results.append({
                        'platform': platform.value,
                        'keyword': keyword,
                        'brand_name': brand_name,
                        'mentioned': analysis.get('mentioned', False),
                        'sentiment': analysis.get('sentiment', 'neutral'),
                        'content': analysis.get('content', ''),
                        'error': analysis.get('error'),
                    })
                    if analysis.get('mentioned'):
                        mentioned_count += 1

                    # 更新关键词的最后检查时间
                    try:
                        async with engine.begin() as conn:
                            await conn.execute(
                                sql_text(
                                    "UPDATE citation_keywords SET last_checked_at=:ts "
                                    "WHERE keyword=:keyword"
                                ),
                                {"ts": datetime.now(), "keyword": keyword},
                            )
                    except Exception as e:
                        logger.warning(f"[Monitor] 更新关键词 last_checked_at 失败: {e}")

                except Exception as e:
                    logger.warning(
                        f"[Monitor] 关键词 '{keyword}' 在 {platform.value} 检测失败: {e}"
                    )
                    results.append({
                        'platform': platform.value,
                        'keyword': keyword,
                        'brand_name': brand_name,
                        'mentioned': False,
                        'error': str(e),
                    })

                # 避免触发 API 频控（异步 sleep，不阻塞事件循环）
                await asyncio.sleep(1)

        # 更新批次记录
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE citation_batches "
                        "SET mentioned_count=:mc, status='completed', completed_at=:ct "
                        "WHERE id=:id"
                    ),
                    {
                        "mc": mentioned_count,
                        "ct": datetime.now(),
                        "id": batch_id,
                    },
                )
        except Exception as e:
            logger.error(f"[Monitor] 更新批次记录失败: {e}")

        citation_rate = (mentioned_count / total_queries * 100) if total_queries > 0 else 0

        return {
            'success': True,
            'batch_id': batch_id,
            'batch_name': batch_name,
            'total_queries': total_queries,
            'mentioned_count': mentioned_count,
            'citation_rate': round(citation_rate, 2),
            'results': results,
        }

    async def get_citation_batches(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取批量检测历史"""
        if not await self.ensure_table():
            return []

        engine = await self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT id, batch_name, platform, total_queries, mentioned_count, "
                        "       status, started_at, completed_at, created_at "
                        "FROM citation_batches ORDER BY id DESC LIMIT :limit"
                    ),
                    {"limit": limit},
                )
                result = []
                for r in rows.fetchall():
                    result.append({
                        'id': r[0],
                        'batch_name': r[1],
                        'platform': r[2],
                        'total_queries': r[3],
                        'mentioned_count': r[4],
                        'status': r[5],
                        'started_at': r[6],
                        'completed_at': r[7],
                        'created_at': r[8],
                    })
                return result
        except Exception as e:
            logger.warning(f"[Monitor] get_citation_batches 失败: {e}")
            return []

    async def get_citation_trend(self, days: int = 30) -> List[Dict[str, Any]]:
        """获取引用率趋势（按天聚合）"""
        if not await self.ensure_table():
            return []

        engine = await self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        since = datetime.now() - timedelta(days=days)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT checked_at::date as date, "
                        "       COUNT(*) as total, "
                        "       SUM(CASE WHEN brand_mentioned=TRUE THEN 1 ELSE 0 END) as mentioned "
                        "FROM ai_citation_records "
                        "WHERE checked_at > :since "
                        "GROUP BY checked_at::date "
                        "ORDER BY date ASC"
                    ),
                    {"since": since},
                )
                result = []
                for r in rows.fetchall():
                    total = r[1] or 0
                    mentioned = r[2] or 0
                    rate = (mentioned / total * 100) if total > 0 else 0
                    result.append({
                        'date': r[0],
                        'total': total,
                        'mentioned': mentioned,
                        'rate': round(rate, 2),
                    })
                return result
        except Exception as e:
            logger.warning(f"[Monitor] get_citation_trend 失败: {e}")
            return []

    async def get_citation_records(self, platform: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """获取 AI 引用记录列表（可按平台过滤，按时间倒序）。

        供 /api/monitoring/ai-citation 端点使用。
        注意：get_citation_trend 是按天聚合的引用率趋势，本方法返回原始记录列表。
        """
        if not await self.ensure_table():
            return []

        engine = await self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        try:
            async with engine.connect() as conn:
                if platform:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, platform, query, brand_mentioned, citation_url, "
                            "       citation_content, context, checked_at, sentiment "
                            "FROM ai_citation_records "
                            "WHERE platform=:p ORDER BY checked_at DESC LIMIT :l"
                        ),
                        {"p": platform, "l": limit},
                    )
                else:
                    rows = await conn.execute(
                        sql_text(
                            "SELECT id, platform, query, brand_mentioned, citation_url, "
                            "       citation_content, context, checked_at, sentiment "
                            "FROM ai_citation_records "
                            "ORDER BY checked_at DESC LIMIT :l"
                        ),
                        {"l": limit},
                    )
                result = []
                for r in rows.fetchall():
                    result.append({
                        'id': r[0],
                        'platform': r[1],
                        'query': r[2],
                        'brand_mentioned': r[3],
                        'citation_url': r[4],
                        'citation_content': r[5],
                        'context': r[6],
                        'checked_at': str(r[7]) if r[7] else None,
                        'sentiment': r[8],
                    })
                return result
        except Exception as e:
            logger.warning(f"[Monitor] get_citation_records 失败: {e}")
            return []

    async def get_citation_stats(self, days: int = 30) -> Dict[str, Any]:
        """获取 AI 引用统计"""
        if not await self.ensure_table():
            return {}

        engine = await self._get_engine()
        if engine is None:
            return {}

        from sqlalchemy import text as sql_text

        since = datetime.now() - timedelta(days=days)
        seven_days_ago = datetime.now() - timedelta(days=7)
        fourteen_days_ago = datetime.now() - timedelta(days=14)

        try:
            async with engine.connect() as conn:
                # 总查询次数
                total_queries = (
                    await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) FROM ai_citation_records WHERE checked_at > :since"
                        ),
                        {"since": since},
                    )
                ).scalar() or 0

                # 品牌被提及次数
                mentioned_count = (
                    await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) FROM ai_citation_records "
                            "WHERE brand_mentioned = TRUE AND checked_at > :since"
                        ),
                        {"since": since},
                    )
                ).scalar() or 0

                # 各平台提及次数
                platform_rows = (
                    await conn.execute(
                        sql_text(
                            "SELECT platform, COUNT(*) FROM ai_citation_records "
                            "WHERE brand_mentioned = TRUE AND checked_at > :since "
                            "GROUP BY platform"
                        ),
                        {"since": since},
                    )
                ).fetchall()
                platform_stats = {row[0]: row[1] for row in platform_rows}

                # 情感分布
                sentiment_rows = (
                    await conn.execute(
                        sql_text(
                            "SELECT sentiment, COUNT(*) FROM ai_citation_records "
                            "WHERE brand_mentioned = TRUE AND checked_at > :since "
                            "GROUP BY sentiment"
                        ),
                        {"since": since},
                    )
                ).fetchall()
                sentiment_stats = {row[0]: row[1] for row in sentiment_rows}

                # 覆盖的平台数
                platforms_covered = (
                    await conn.execute(
                        sql_text(
                            "SELECT COUNT(DISTINCT platform) FROM ai_citation_records "
                            "WHERE checked_at > :since"
                        ),
                        {"since": since},
                    )
                ).scalar() or 0

                # 趋势：最近 7 天 vs 之前 7 天
                recent_total = (
                    await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) FROM ai_citation_records WHERE checked_at > :s"
                        ),
                        {"s": seven_days_ago},
                    )
                ).scalar() or 0

                recent_mentioned = (
                    await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) FROM ai_citation_records "
                            "WHERE brand_mentioned = TRUE AND checked_at > :s"
                        ),
                        {"s": seven_days_ago},
                    )
                ).scalar() or 0

                prev_total = (
                    await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) FROM ai_citation_records "
                            "WHERE checked_at > :s AND checked_at < :e"
                        ),
                        {"s": fourteen_days_ago, "e": seven_days_ago},
                    )
                ).scalar() or 0

                prev_mentioned = (
                    await conn.execute(
                        sql_text(
                            "SELECT COUNT(*) FROM ai_citation_records "
                            "WHERE brand_mentioned = TRUE AND checked_at > :s AND checked_at < :e"
                        ),
                        {"s": fourteen_days_ago, "e": seven_days_ago},
                    )
                ).scalar() or 0
        except Exception as e:
            logger.warning(f"[Monitor] get_citation_stats 失败: {e}")
            return {}

        recent_rate = (recent_mentioned / recent_total * 100) if recent_total > 0 else 0
        prev_rate = (prev_mentioned / prev_total * 100) if prev_total > 0 else 0
        trend = round(recent_rate - prev_rate, 2)

        return {
            'total_queries': total_queries,
            'mentioned_count': mentioned_count,
            'mention_rate': round(mentioned_count / total_queries * 100, 2) if total_queries > 0 else 0,
            'platform_stats': platform_stats,
            'sentiment_stats': sentiment_stats,
            'platforms_covered': platforms_covered,
            'total_platforms': _TOTAL_AI_PLATFORMS,
            'trend': trend,
            'recent_rate': round(recent_rate, 2),
            'prev_rate': round(prev_rate, 2),
        }

    # ==================== 流量分析 ====================

    async def record_traffic(self, record: TrafficRecord) -> None:
        """记录流量数据"""
        if not await self.ensure_table():
            return

        engine = await self._get_engine()
        if engine is None:
            return

        from sqlalchemy import text as sql_text

        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO traffic_records "
                        "(source, medium, campaign, visitors, pageviews, bounce_rate, "
                        " avg_duration, conversions, recorded_at) "
                        "VALUES (:source, :medium, :campaign, :visitors, :pageviews, "
                        "        :bounce_rate, :avg_duration, :conversions, :recorded_at)"
                    ),
                    {
                        "source": record.source,
                        "medium": record.medium,
                        "campaign": record.campaign,
                        "visitors": record.visitors,
                        "pageviews": record.pageviews,
                        "bounce_rate": record.bounce_rate,
                        "avg_duration": record.avg_duration,
                        "conversions": record.conversions,
                        "recorded_at": record.recorded_at,
                    },
                )
        except Exception as e:
            logger.error(f"[Monitor] record_traffic 失败: {e}")

    async def get_traffic_summary(self, days: int = 30) -> Dict[str, Any]:
        """获取流量汇总"""
        if not await self.ensure_table():
            return {}

        engine = await self._get_engine()
        if engine is None:
            return {}

        from sqlalchemy import text as sql_text

        since = datetime.now() - timedelta(days=days)

        try:
            async with engine.connect() as conn:
                # 总访问量
                row = (
                    await conn.execute(
                        sql_text(
                            "SELECT SUM(visitors), SUM(pageviews), SUM(conversions) "
                            "FROM traffic_records WHERE recorded_at > :since"
                        ),
                        {"since": since},
                    )
                ).fetchone()
                total_visitors = row[0] or 0
                total_pageviews = row[1] or 0
                total_conversions = row[2] or 0

                # 各来源流量
                source_rows = (
                    await conn.execute(
                        sql_text(
                            "SELECT source, SUM(visitors) as visitors "
                            "FROM traffic_records WHERE recorded_at > :since "
                            "GROUP BY source ORDER BY visitors DESC"
                        ),
                        {"since": since},
                    )
                ).fetchall()
                source_stats = [{'source': r[0], 'visitors': r[1]} for r in source_rows]

                # 每日趋势
                daily_rows = (
                    await conn.execute(
                        sql_text(
                            "SELECT recorded_at::date as date, SUM(visitors) as visitors "
                            "FROM traffic_records WHERE recorded_at > :since "
                            "GROUP BY recorded_at::date ORDER BY date"
                        ),
                        {"since": since},
                    )
                ).fetchall()
                daily_trend = [{'date': r[0], 'visitors': r[1]} for r in daily_rows]
        except Exception as e:
            logger.warning(f"[Monitor] get_traffic_summary 失败: {e}")
            return {}

        return {
            'total_visitors': total_visitors,
            'total_pageviews': total_pageviews,
            'total_conversions': total_conversions,
            'conversion_rate': round(total_conversions / total_visitors * 100, 2) if total_visitors > 0 else 0,
            'source_stats': source_stats,
            'daily_trend': daily_trend,
        }

    # ==================== 综合报告 ====================

    async def generate_report(self, brand_name: str = "", days: int = 30) -> Dict[str, Any]:
        """生成综合监控报告

        Args:
            brand_name: 品牌名称（用于报告标识，空则使用默认）
            days: 统计窗口天数
        """
        return {
            'brand_name': brand_name or '默认品牌',
            'period': f'{days}天',
            'generated_at': datetime.now().isoformat(),
            'search_rank': {
                'summary': '搜索排名监控摘要',
                'top_keywords': await self._get_top_keywords(days),
            },
            'ai_citation': await self.get_citation_stats(days),
            'traffic': await self.get_traffic_summary(days),
        }

    async def _get_top_keywords(self, days: int) -> List[Dict[str, Any]]:
        """获取排名靠前的关键词"""
        if not await self.ensure_table():
            return []

        engine = await self._get_engine()
        if engine is None:
            return []

        from sqlalchemy import text as sql_text

        since = datetime.now() - timedelta(days=days)

        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT keyword, AVG(rank) as avg_rank, COUNT(*) as check_count "
                        "FROM search_rank_records "
                        "WHERE checked_at > :since AND rank <= 10 "
                        "GROUP BY keyword "
                        "ORDER BY avg_rank LIMIT 10"
                    ),
                    {"since": since},
                )
                return [
                    {'keyword': r[0], 'avg_rank': round(r[1], 1), 'checks': r[2]}
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[Monitor] _get_top_keywords 失败: {e}")
            return []


# ==================== 单例 ====================

_monitoring_service: Optional[MonitoringService] = None


def get_monitoring_service() -> MonitoringService:
    """获取 MonitoringService 单例"""
    global _monitoring_service
    if _monitoring_service is None:
        _monitoring_service = MonitoringService()
    return _monitoring_service
