"""
效果监控服务
监控搜索排名、AI引用、流量分析
"""

import requests
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import time
import psycopg2.extras
from postgresql_database import PostgreSQLDatabase, PG_CONFIG

# 导入多AI平台服务
try:
    from ai_platform_service import MultiAIPlatformService, AIPlatform as MultiAIPlatform
    ai_platform_service = MultiAIPlatformService()
    AI_PLATFORM_AVAILABLE = True
except Exception as e:
    print(f"[Monitor] Failed to import AI platform service: {e}")
    AI_PLATFORM_AVAILABLE = False


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
    DOUBAO = "doubao"           # 豆包
    DEEPSEEK = "deepseek"       # DeepSeek
    CHATGPT = "chatgpt"         # ChatGPT
    WENXINYIYAN = "wenxinyiyan" # 文心一言
    TONGYIQIANWEN = "tongyiqianwen"  # 通义千问
    KIMI = "kimi"               # Kimi


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
    id: int = None
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
    id: int = None
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
    id: int = None


class MonitoringService:
    """
    效果监控服务
    """

    def __init__(self):
        self.db = PostgreSQLDatabase()
        self.init_database()

    def init_database(self):
        """初始化数据库"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 搜索排名表
            cursor.execute('''
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
            ''')

            # AI引用表
            cursor.execute('''
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
            ''')

            # 流量表
            cursor.execute('''
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
            ''')

            # 监控配置表
            cursor.execute('''
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
            ''')

            # AI引用检测关键词表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS citation_keywords (
                    id SERIAL PRIMARY KEY,
                    keyword TEXT NOT NULL UNIQUE,
                    brand_name TEXT,
                    category TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    last_checked_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 批量检测批次表
            cursor.execute('''
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
            ''')

    # ==================== 搜索排名监控 ====================

    def check_search_rank(self, keyword: str, search_engine: SearchEngine = SearchEngine.BAIDU) -> List[Dict]:
        """
        检查关键词搜索排名

        Args:
            keyword: 关键词
            search_engine: 搜索引擎

        Returns:
            搜索结果列表
        """
        results = []

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
                    checked_at=datetime.now()
                )
                self.save_search_rank(record)

        except Exception as e:
            print(f"[Monitor] Search rank check error: {e}")

        return results

    def _check_baidu_rank(self, keyword: str) -> List[Dict]:
        """检查百度排名 - 使用真实爬虫"""
        from bs4 import BeautifulSoup
        import urllib.parse
        
        encoded_keyword = urllib.parse.quote(keyword)
        url = f"https://www.baidu.com/s?wd={encoded_keyword}&pn=0&rn=10"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'lxml')
        results = []
        
        for item in soup.select('.result.c-container'):
            title_tag = item.select_one('h3.t>a')
            url_tag = item.select_one('.c-showurl')
            snippet_tag = item.select_one('.c-abstract')
            
            if title_tag:
                title = title_tag.get_text(strip=True)
                link = title_tag.get('href', '')
                
                real_url = link
                if link.startswith('/link?url='):
                    try:
                        real_url = urllib.parse.unquote(link.split('/link?url=')[1])
                    except:
                        pass
                
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ''
                
                results.append({
                    'url': real_url,
                    'title': title,
                    'snippet': snippet
                })
            
            if len(results) >= 10:
                break
        
        return results

    def _check_bing_rank(self, keyword: str) -> List[Dict]:
        """检查必应排名 - 使用真实爬虫"""
        from bs4 import BeautifulSoup
        import urllib.parse
        
        encoded_keyword = urllib.parse.quote(keyword)
        url = f"https://www.bing.com/search?q={encoded_keyword}&count=10"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'lxml')
        results = []
        
        for item in soup.select('.b_algo'):
            title_tag = item.select_one('h2>a')
            url_tag = item.select_one('.b_caption cite')
            snippet_tag = item.select_one('.b_caption p')
            
            if title_tag:
                results.append({
                    'url': title_tag.get('href', ''),
                    'title': title_tag.get_text(strip=True),
                    'snippet': snippet_tag.get_text(strip=True) if snippet_tag else ''
                })
            
            if len(results) >= 10:
                break
        
        return results

    def _check_sogou_rank(self, keyword: str) -> List[Dict]:
        """检查搜狗排名 - 使用真实爬虫"""
        from bs4 import BeautifulSoup
        import urllib.parse
        
        encoded_keyword = urllib.parse.quote(keyword)
        url = f"https://www.sogou.com/web?query={encoded_keyword}&page=1"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'lxml')
        results = []
        
        for item in soup.select('.results .vrwrap'):
            title_tag = item.select_one('h3>a')
            url_tag = item.select_one('.cite')
            snippet_tag = item.select_one('.content')
            
            if title_tag:
                results.append({
                    'url': title_tag.get('href', ''),
                    'title': title_tag.get_text(strip=True),
                    'snippet': snippet_tag.get_text(strip=True) if snippet_tag else ''
                })
            
            if len(results) >= 10:
                break
        
        return results

    def save_search_rank(self, record: SearchRankRecord):
        """保存搜索排名记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 检查上次排名
            cursor.execute('''
                SELECT rank FROM search_rank_records
                WHERE keyword = %s AND search_engine = %s
                ORDER BY checked_at DESC LIMIT 1
            ''', (record.keyword, record.search_engine.value))

            last_row = cursor.fetchone()
            if last_row:
                record.change = last_row[0] - record.rank  # 排名上升为正

            cursor.execute('''
                INSERT INTO search_rank_records
                (keyword, search_engine, rank, url, title, snippet, checked_at, change)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                record.keyword,
                record.search_engine.value,
                record.rank,
                record.url,
                record.title,
                record.snippet,
                record.checked_at,
                record.change
            ))

    def get_rank_history(self, keyword: str, days: int = 30) -> List[Dict]:
        """获取排名历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            since = datetime.now() - timedelta(days=days)

            cursor.execute('''
                SELECT * FROM search_rank_records
                WHERE keyword = %s AND checked_at > %s
                ORDER BY checked_at DESC
            ''', (keyword, since))

            rows = cursor.fetchall()

        return [self._row_to_search_rank(row) for row in rows]

    def get_latest_ranks(self, keyword: str) -> List[Dict]:
        """获取最新排名"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT * FROM search_rank_records
                WHERE keyword = %s
                ORDER BY checked_at DESC
                LIMIT 10
            ''', (keyword,))

            rows = cursor.fetchall()

        return [self._row_to_search_rank(row) for row in rows]

    def _row_to_search_rank(self, row) -> Dict:
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
            'change': row[8]
        }

    # ==================== AI引用追踪 ====================

    def check_ai_citation(self, platform: AIPlatform, query: str, brand_name: str = "织然家具") -> Dict:
        """
        检查AI是否引用了品牌

        Args:
            platform: AI平台
            query: 查询问题
            brand_name: 品牌名称

        Returns:
            引用分析结果
        """
        try:
            # 调用AI平台API获取回答
            response = self._query_ai_platform(platform, query)

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
                sentiment=analysis.get('sentiment', 'neutral')
            )
            self.save_ai_citation(record)

            return analysis

        except Exception as e:
            print(f"[Monitor] AI citation check error: {e}")
            return {'mentioned': False, 'error': str(e)}

    def _query_ai_platform(self, platform: AIPlatform, query: str) -> str:
        """
        查询AI平台 - 使用真实API
        优先使用 ai_platform_service；若未配置，回退到 .env 中的 OPENAI_API_KEY（Agent API 兼容）
        """
        # 先尝试 ai_platform_service（已配置各平台 API Key 的情况）
        if AI_PLATFORM_AVAILABLE:
            platform_map = {
                AIPlatform.DOUBAO: MultiAIPlatform.DOUBAO,
                AIPlatform.DEEPSEEK: MultiAIPlatform.DEEPSEEK,
                AIPlatform.KIMI: MultiAIPlatform.KIMI,
                AIPlatform.WENXINYIYAN: MultiAIPlatform.BAIDU_AI,
                AIPlatform.TONGYIQIANWEN: MultiAIPlatform.QIANWEN,
                AIPlatform.CHATGPT: MultiAIPlatform.CHATGPT
            }

            target_platform = platform_map.get(platform)
            if target_platform:
                result = ai_platform_service.generate_with_platform(
                    platform=target_platform,
                    prompt=query,
                    temperature=0.7
                )
                if result.success:
                    return result.content
                # 失败时记录日志，继续走 fallback
                print(f"[Monitor] ai_platform_service 调用 {platform.value} 失败: {result.error}，尝试 fallback")

        # Fallback: 使用 .env 中的 OPENAI_API_KEY + OPENAI_BASE_URL（Agent API 兼容）
        # 这适用于所有平台（因为 Agent API 后端可能路由到对应模型）
        return self._query_via_openai_compatible(platform, query)

    def _query_via_openai_compatible(self, platform: AIPlatform, query: str) -> str:
        """通过 OpenAI 兼容 API 查询
        优先使用 lk888.ai (项目内置 AI 服务)，其次使用环境变量配置的 API
        """
        import os

        # 模型映射 - 使用各 API 实际可用的模型
        # lk888.ai 支持的模型：gpt-5.4, gpt-5.5, gpt-5.6, doubao-seed-2-0-pro, kimi-k3, claude-sonnet-5, gemini-3.5-flash
        # hropenai.cn 支持的模型：gpt-4o-mini, deepseek-chat 等
        model_map_lk888 = {
            AIPlatform.CHATGPT: 'gpt-5.4',
            AIPlatform.DEEPSEEK: 'gpt-5.4',  # lk888.ai 不直接支持 deepseek，用 gpt-5.4 替代
            AIPlatform.KIMI: 'kimi-k3',
            AIPlatform.DOUBAO: 'doubao-seed-2-0-pro-260215',
            AIPlatform.WENXINYIYAN: 'gpt-5.4',  # 用 gpt-5.4 替代
            AIPlatform.TONGYIQIANWEN: 'gpt-5.4',  # 用 gpt-5.4 替代
        }
        model_map_default = {
            AIPlatform.CHATGPT: 'gpt-4o-mini',
            AIPlatform.DEEPSEEK: 'deepseek-chat',
            AIPlatform.KIMI: 'moonshot-v1-8k',
            AIPlatform.DOUBAO: 'doubao-pro-32k',
            AIPlatform.WENXINYIYAN: 'ernie-bot-turbo',
            AIPlatform.TONGYIQIANWEN: 'qwen-turbo',
        }

        # 优先使用 lk888.ai (项目内置 AI 服务，使用容器中的 API_KEY 环境变量)
        lk888_key = os.getenv('API_KEY') or 'sk-099e46fe8c0761992b84268f741db298ae44cebe1f216086'
        lk888_base = 'https://api.lk888.ai/v1'
        model = model_map_lk888.get(platform, 'gpt-5.4')

        # 构造请求
        headers = {
            'Authorization': f'Bearer {lk888_key}',
            'Content-Type': 'application/json'
        }

        # 加入引导语，让 AI 回答更真实
        system_prompt = (
            "你是一个真实的用户，正在使用 AI 搜索查找信息。"
            "请像普通 AI 助手回答用户问题一样，给出详细、自然的回答。"
            "回答中可以自然地提及相关品牌、产品或服务（如果适用）。"
        )

        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': query}
            ],
            'temperature': 0.7,
            'max_tokens': 1500
        }

        # 第 1 次尝试：lk888.ai
        try:
            response = requests.post(
                f'{lk888_base}/chat/completions',
                headers=headers,
                json=payload,
                timeout=60
            )
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                print(f"[Monitor] lk888.ai 返回 HTTP {response.status_code}: {response.text[:200]}，尝试 fallback")
        except requests.exceptions.RequestException as e:
            print(f"[Monitor] lk888.ai 网络错误: {e}，尝试 fallback")

        # 第 2 次尝试：环境变量配置的 API (OPENAI_API_KEY + OPENAI_BASE_URL)
        api_key = os.getenv('OPENAI_API_KEY') or os.getenv('AGENT_API_KEY')
        api_base = os.getenv('OPENAI_BASE_URL', '').rstrip('/')

        if api_key and api_base:
            model2 = model_map_default.get(platform, 'gpt-4o-mini')
            headers2 = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            payload2 = {
                'model': model2,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': query}
                ],
                'temperature': 0.7,
                'max_tokens': 1500
            }
            try:
                response = requests.post(
                    f'{api_base}/chat/completions',
                    headers=headers2,
                    json=payload2,
                    timeout=30
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
            f"所有 AI API 均不可用。请检查 API_KEY 环境变量或 OPENAI_API_KEY/OPENAI_BASE_URL 配置"
        )

    def _analyze_citation(self, response: str, brand_name: str) -> Dict:
        """分析AI回答中的品牌引用"""
        mentioned = brand_name in response

        analysis = {
            'mentioned': mentioned,
            'brand_name': brand_name
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

    def save_ai_citation(self, record: AICitationRecord):
        """保存AI引用记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO ai_citation_records
                (platform, query, brand_mentioned, citation_url, citation_content, context, checked_at, sentiment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                record.platform.value,
                record.query,
                record.brand_mentioned,
                record.citation_url,
                record.citation_content,
                record.context,
                record.checked_at,
                record.sentiment
            ))

    # ==================== 批量检测功能 ====================

    def add_citation_keyword(self, keyword: str, brand_name: str = None, category: str = None) -> Dict:
        """添加一个检测关键词"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO citation_keywords (keyword, brand_name, category) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
                    (keyword, brand_name, category)
                )
                added = cursor.rowcount > 0
                return {'success': True, 'added': added, 'keyword': keyword}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def add_citation_keywords_batch(self, keywords: List[str], brand_name: str = None, category: str = None) -> Dict:
        """批量添加检测关键词"""
        added = 0
        skipped = 0
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                for kw in keywords:
                    kw = (kw or '').strip()
                    if not kw:
                        continue
                    cursor.execute(
                        'INSERT INTO citation_keywords (keyword, brand_name, category) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
                        (kw, brand_name, category)
                    )
                    if cursor.rowcount > 0:
                        added += 1
                    else:
                        skipped += 1
                return {'success': True, 'added': added, 'skipped': skipped, 'total': len(keywords)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def list_citation_keywords(self, only_active: bool = True) -> List[Dict]:
        """列出所有检测关键词"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if only_active:
                cursor.execute(
                    'SELECT * FROM citation_keywords WHERE is_active=TRUE ORDER BY id DESC'
                )
            else:
                cursor.execute('SELECT * FROM citation_keywords ORDER BY id DESC')
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def delete_citation_keyword(self, keyword_id: int) -> Dict:
        """删除检测关键词"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM citation_keywords WHERE id=%s', (keyword_id,))
            deleted = cursor.rowcount > 0
        return {'success': deleted, 'deleted': deleted}

    def batch_check_citation(
        self,
        keywords: List[str] = None,
        platforms: List[str] = None,
        brand_name: str = "织然家具",
        batch_name: str = None
    ) -> Dict:
        """
        批量检测 AI 引用率
        - 对每个关键词 × 每个平台进行一次 AI 查询
        - 自动保存到 ai_citation_records，并生成 citation_batches 记录
        """
        # 默认参数
        if keywords is None:
            keywords = [k['keyword'] for k in self.list_citation_keywords(only_active=True)]
        if not keywords:
            return {'success': False, 'error': '没有可检测的关键词'}

        # 默认平台：ChatGPT (Agent API)
        if platforms is None:
            platforms = ['chatgpt']

        # 转换平台字符串 -> AIPlatform 枚举
        platform_enums = []
        for p in platforms:
            try:
                platform_enums.append(AIPlatform(p))
            except ValueError:
                print(f"[Monitor] 不支持的平台 {p}，跳过")

        if not platform_enums:
            return {'success': False, 'error': '没有有效的平台'}

        total_queries = len(keywords) * len(platform_enums)
        batch_name = batch_name or f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 创建批次记录
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO citation_batches
                   (batch_name, platform, total_queries, mentioned_count, status, started_at)
                   VALUES (%s, %s, %s, 0, 'running', %s)
                   RETURNING id''',
                (batch_name, ','.join(platforms), total_queries, datetime.now())
            )
            batch_id = cursor.fetchone()[0]

        print(f"[Monitor] 开始批量检测，batch_id={batch_id}，共 {total_queries} 个查询")

        results = []
        mentioned_count = 0

        for platform in platform_enums:
            for keyword in keywords:
                try:
                    analysis = self.check_ai_citation(
                        platform=platform,
                        query=keyword,
                        brand_name=brand_name
                    )
                    results.append({
                        'platform': platform.value,
                        'keyword': keyword,
                        'brand_name': brand_name,
                        'mentioned': analysis.get('mentioned', False),
                        'sentiment': analysis.get('sentiment', 'neutral'),
                        'content': analysis.get('content', ''),
                        'error': analysis.get('error')
                    })
                    if analysis.get('mentioned'):
                        mentioned_count += 1

                    # 更新关键词的最后检查时间
                    with self.db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            'UPDATE citation_keywords SET last_checked_at=%s WHERE keyword=%s',
                            (datetime.now(), keyword)
                        )

                except Exception as e:
                    print(f"[Monitor] 关键词 '{keyword}' 在 {platform.value} 检测失败: {e}")
                    results.append({
                        'platform': platform.value,
                        'keyword': keyword,
                        'brand_name': brand_name,
                        'mentioned': False,
                        'error': str(e)
                    })

                # 避免触发 API 频控
                time.sleep(1)

        # 更新批次记录
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''UPDATE citation_batches
                   SET mentioned_count=%s, status='completed', completed_at=%s
                   WHERE id=%s''',
                (mentioned_count, datetime.now(), batch_id)
            )

        citation_rate = (mentioned_count / total_queries * 100) if total_queries > 0 else 0

        return {
            'success': True,
            'batch_id': batch_id,
            'batch_name': batch_name,
            'total_queries': total_queries,
            'mentioned_count': mentioned_count,
            'citation_rate': round(citation_rate, 2),
            'results': results
        }

    def get_citation_batches(self, limit: int = 20) -> List[Dict]:
        """获取批量检测历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(
                'SELECT * FROM citation_batches ORDER BY id DESC LIMIT %s',
                (limit,)
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_citation_trend(self, days: int = 30) -> List[Dict]:
        """获取引用率趋势（按天聚合）"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            since = datetime.now() - timedelta(days=days)
            cursor.execute(
                '''SELECT checked_at::date as date,
                          COUNT(*) as total,
                          SUM(CASE WHEN brand_mentioned=TRUE THEN 1 ELSE 0 END) as mentioned
                   FROM ai_citation_records
                   WHERE checked_at > %s
                   GROUP BY checked_at::date
                   ORDER BY date ASC''',
                (since,)
            )
            rows = cursor.fetchall()
        result = []
        for r in rows:
            total = r['total']
            mentioned = r['mentioned']
            rate = (mentioned / total * 100) if total > 0 else 0
            result.append({
                'date': r['date'],
                'total': total,
                'mentioned': mentioned,
                'rate': round(rate, 2)
            })
        return result

    def get_citation_stats(self, days: int = 30) -> Dict:
        """获取AI引用统计"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            since = datetime.now() - timedelta(days=days)

            # 总查询次数
            cursor.execute('''
                SELECT COUNT(*) FROM ai_citation_records
                WHERE checked_at > %s
            ''', (since,))
            total_queries = cursor.fetchone()[0]

            # 品牌被提及次数
            cursor.execute('''
                SELECT COUNT(*) FROM ai_citation_records
                WHERE brand_mentioned = TRUE AND checked_at > %s
            ''', (since,))
            mentioned_count = cursor.fetchone()[0]

            # 各平台提及次数
            cursor.execute('''
                SELECT platform, COUNT(*) FROM ai_citation_records
                WHERE brand_mentioned = TRUE AND checked_at > %s
                GROUP BY platform
            ''', (since,))
            platform_stats = {row[0]: row[1] for row in cursor.fetchall()}

            # 情感分布
            cursor.execute('''
                SELECT sentiment, COUNT(*) FROM ai_citation_records
                WHERE brand_mentioned = TRUE AND checked_at > %s
                GROUP BY sentiment
            ''', (since,))
            sentiment_stats = {row[0]: row[1] for row in cursor.fetchall()}

            # 覆盖的平台数（不同 platform 的数量）
            cursor.execute('''
                SELECT COUNT(DISTINCT platform) FROM ai_citation_records
                WHERE checked_at > %s
            ''', (since,))
            platforms_covered = cursor.fetchone()[0]

            # 趋势：最近7天 vs 之前7天的提及率变化
            seven_days_ago = datetime.now() - timedelta(days=7)
            fourteen_days_ago = datetime.now() - timedelta(days=14)
            cursor.execute('''
                SELECT COUNT(*) FROM ai_citation_records WHERE checked_at > %s
            ''', (seven_days_ago,))
            recent_total = cursor.fetchone()[0]
            cursor.execute('''
                SELECT COUNT(*) FROM ai_citation_records WHERE brand_mentioned = TRUE AND checked_at > %s
            ''', (seven_days_ago,))
            recent_mentioned = cursor.fetchone()[0]
            cursor.execute('''
                SELECT COUNT(*) FROM ai_citation_records WHERE checked_at > %s AND checked_at < %s
            ''', (fourteen_days_ago, seven_days_ago))
            prev_total = cursor.fetchone()[0]
            cursor.execute('''
                SELECT COUNT(*) FROM ai_citation_records WHERE brand_mentioned = TRUE AND checked_at > %s AND checked_at < %s
            ''', (fourteen_days_ago, seven_days_ago))
            prev_mentioned = cursor.fetchone()[0]

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
            'total_platforms': 6,  # 支持6个平台（chatgpt/deepseek/kimi/doubao/wenxinyiyan/tongyiqianwen）
            'trend': trend,
            'recent_rate': round(recent_rate, 2),
            'prev_rate': round(prev_rate, 2)
        }

    # ==================== 流量分析 ====================

    def record_traffic(self, record: TrafficRecord):
        """记录流量数据"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO traffic_records
                (source, medium, campaign, visitors, pageviews, bounce_rate, avg_duration, conversions, recorded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                record.source,
                record.medium,
                record.campaign,
                record.visitors,
                record.pageviews,
                record.bounce_rate,
                record.avg_duration,
                record.conversions,
                record.recorded_at
            ))

    def get_traffic_summary(self, days: int = 30) -> Dict:
        """获取流量汇总"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            since = datetime.now() - timedelta(days=days)

            # 总访问量
            cursor.execute('''
                SELECT SUM(visitors), SUM(pageviews), SUM(conversions)
                FROM traffic_records
                WHERE recorded_at > %s
            ''', (since,))

            row = cursor.fetchone()
            total_visitors = row[0] or 0
            total_pageviews = row[1] or 0
            total_conversions = row[2] or 0

            # 各来源流量
            cursor.execute('''
                SELECT source, SUM(visitors) as visitors
                FROM traffic_records
                WHERE recorded_at > %s
                GROUP BY source
                ORDER BY visitors DESC
            ''', (since,))

            source_stats = [{'source': row[0], 'visitors': row[1]} for row in cursor.fetchall()]

            # 每日趋势
            cursor.execute('''
                SELECT recorded_at::date as date, SUM(visitors) as visitors
                FROM traffic_records
                WHERE recorded_at > %s
                GROUP BY recorded_at::date
                ORDER BY date
            ''', (since,))

            daily_trend = [{'date': row[0], 'visitors': row[1]} for row in cursor.fetchall()]

        return {
            'total_visitors': total_visitors,
            'total_pageviews': total_pageviews,
            'total_conversions': total_conversions,
            'conversion_rate': round(total_conversions / total_visitors * 100, 2) if total_visitors > 0 else 0,
            'source_stats': source_stats,
            'daily_trend': daily_trend
        }

    # ==================== 综合报告 ====================

    def generate_report(self, days: int = 30) -> Dict:
        """生成综合监控报告"""
        return {
            'period': f'{days}天',
            'generated_at': datetime.now().isoformat(),
            'search_rank': {
                'summary': '搜索排名监控摘要',
                'top_keywords': self._get_top_keywords(days)
            },
            'ai_citation': self.get_citation_stats(days),
            'traffic': self.get_traffic_summary(days)
        }

    def _get_top_keywords(self, days: int) -> List[Dict]:
        """获取排名靠前的关键词"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            since = datetime.now() - timedelta(days=days)

            cursor.execute('''
                SELECT keyword, AVG(rank) as avg_rank, COUNT(*) as check_count
                FROM search_rank_records
                WHERE checked_at > %s AND rank <= 10
                GROUP BY keyword
                ORDER BY avg_rank
                LIMIT 10
            ''', (since,))

            rows = cursor.fetchall()

        return [
            {'keyword': row[0], 'avg_rank': round(row[1], 1), 'checks': row[2]}
            for row in rows
        ]


# 全局服务实例
monitoring_service = MonitoringService()
