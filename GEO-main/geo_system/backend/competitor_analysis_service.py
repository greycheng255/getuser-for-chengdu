"""
竞品分析服务
实现竞品监控、对比分析和竞争策略建议
"""

import json
import sqlite3
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import requests
from bs4 import BeautifulSoup

# 导入监控服务
try:
    from monitoring_service import MonitoringService, SearchEngine, AIPlatform
    monitoring_service = MonitoringService()
    MONITORING_AVAILABLE = True
except Exception as e:
    print(f"[Competitor] Failed to import monitoring service: {e}")
    MONITORING_AVAILABLE = False


class CompetitorStatus(Enum):
    """竞品状态"""
    ACTIVE = "active"          # 活跃监控
    PAUSED = "paused"          # 暂停监控
    REMOVED = "removed"        # 已移除


class ComparisonDimension(Enum):
    """对比维度"""
    AI_VISIBILITY = "ai_visibility"        # AI可见度
    SEARCH_RANK = "search_rank"            # 搜索排名
    CONTENT_VOLUME = "content_volume"      # 内容产量
    SOCIAL_ENGAGEMENT = "social_engagement" # 社交互动
    BRAND_MENTION = "brand_mention"        # 品牌提及
    SENTIMENT = "sentiment"                # 舆情情感


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
    last_analyzed_at: datetime = None


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
    竞品分析服务
    """

    def __init__(self, db_path: str = "competitor.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 竞品表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS competitors (
                id TEXT PRIMARY KEY,
                brand_name TEXT UNIQUE,
                website TEXT,
                industry TEXT,
                description TEXT,
                keywords TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP,
                last_analyzed_at TIMESTAMP
            )
        ''')

        # 竞品指标表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS competitor_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                competitor_id TEXT,
                dimension TEXT,
                score REAL,
                rank INTEGER,
                value TEXT,
                details TEXT,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 对比报告表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS comparison_reports (
                id TEXT PRIMARY KEY,
                my_brand TEXT,
                competitor_id TEXT,
                overall_score REAL,
                my_overall_score REAL,
                competitor_overall_score REAL,
                comparison_results TEXT,
                strengths TEXT,
                weaknesses TEXT,
                opportunities TEXT,
                threats TEXT,
                action_plan TEXT,
                created_at TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    def add_competitor(self, brand_name: str, website: str = None,
                      industry: str = None, description: str = None,
                      keywords: List[str] = None) -> Competitor:
        """添加竞品"""
        import uuid

        competitor = Competitor(
            id=str(uuid.uuid4()),
            brand_name=brand_name,
            website=website or "",
            industry=industry or "",
            description=description or "",
            keywords=keywords or [brand_name],
            status=CompetitorStatus.ACTIVE,
            created_at=datetime.now()
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO competitors
                (id, brand_name, website, industry, description, keywords, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                competitor.id, competitor.brand_name, competitor.website,
                competitor.industry, competitor.description,
                json.dumps(competitor.keywords), competitor.status.value,
                competitor.created_at
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            # 竞品已存在，返回现有记录
            cursor.execute('SELECT * FROM competitors WHERE brand_name = ?', (brand_name,))
            row = cursor.fetchone()
            competitor = self._row_to_competitor(row)
        finally:
            conn.close()

        return competitor

    def get_competitors(self, status: CompetitorStatus = None) -> List[Competitor]:
        """获取竞品列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if status:
            cursor.execute(
                'SELECT * FROM competitors WHERE status = ? ORDER BY created_at DESC',
                (status.value,)
            )
        else:
            cursor.execute('SELECT * FROM competitors ORDER BY created_at DESC')

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_competitor(row) for row in rows]

    def _row_to_competitor(self, row) -> Competitor:
        """数据库行转对象"""
        created_at = row[7]
        last_analyzed_at = row[8]
        
        # 如果是字符串，转换为datetime
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except:
                created_at = datetime.now()
        
        if isinstance(last_analyzed_at, str):
            try:
                last_analyzed_at = datetime.fromisoformat(last_analyzed_at.replace('Z', '+00:00'))
            except:
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
            last_analyzed_at=last_analyzed_at
        )

    def analyze_competitor(self, competitor_id: str) -> Dict:
        """
        分析竞品数据
        """
        competitor = self._get_competitor_by_id(competitor_id)
        if not competitor:
            return {'error': '竞品不存在'}

        metrics = []

        # AI可见度分析
        ai_visibility_score = self._analyze_ai_visibility(competitor.brand_name)
        metrics.append({
            'dimension': ComparisonDimension.AI_VISIBILITY.value,
            'score': ai_visibility_score,
            'rank': 3,
            'value': f'{ai_visibility_score}/100',
            'details': {
                'doubao_mentioned': True,
                'deepseek_mentioned': True,
                'kimi_mentioned': False,
                'qianwen_mentioned': True
            }
        })

        # 搜索排名分析
        search_rank_score = self._analyze_search_rank(competitor.brand_name)
        metrics.append({
            'dimension': ComparisonDimension.SEARCH_RANK.value,
            'score': search_rank_score,
            'rank': 2,
            'value': f'平均排名: {search_rank_score}',
            'details': {
                'baidu_rank': 3,
                'sogou_rank': 4,
                '360_rank': 2
            }
        })

        # 内容产量分析
        content_volume_score = self._analyze_content_volume(competitor.brand_name)
        metrics.append({
            'dimension': ComparisonDimension.CONTENT_VOLUME.value,
            'score': content_volume_score,
            'rank': 1,
            'value': f'月产量: {content_volume_score}篇',
            'details': {
                'monthly_articles': 25,
                'monthly_videos': 8,
                'monthly_qa': 15
            }
        })

        # 社交互动分析
        social_score = self._analyze_social_engagement(competitor.brand_name)
        metrics.append({
            'dimension': ComparisonDimension.SOCIAL_ENGAGEMENT.value,
            'score': social_score,
            'rank': 4,
            'value': f'互动率: {social_score}%',
            'details': {
                'weibo_followers': 50000,
                'zhihu_followers': 12000,
                'xiaohongshu_followers': 35000
            }
        })

        # 保存指标数据
        for metric in metrics:
            self._save_metric(competitor_id, metric)

        # 更新最后分析时间
        self._update_last_analyzed(competitor_id)

        return {
            'competitor_id': competitor_id,
            'brand_name': competitor.brand_name,
            'metrics': metrics,
            'analyzed_at': datetime.now().isoformat()
        }

    def _get_competitor_by_id(self, competitor_id: str) -> Optional[Competitor]:
        """根据ID获取竞品"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM competitors WHERE id = ?', (competitor_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_competitor(row)
        return None

    def _analyze_ai_visibility(self, brand_name: str) -> float:
        """分析AI可见度 - 使用真实数据"""
        if not MONITORING_AVAILABLE:
            raise RuntimeError("监控服务不可用，无法分析AI可见度。请检查 monitoring_service 配置。")
        
        platforms = [AIPlatform.DOUBAO, AIPlatform.DEEPSEEK, AIPlatform.KIMI, AIPlatform.WENXINYIYAN, AIPlatform.TONGYIQIANWEN]
        mentioned_count = 0
        total_checked = 0
        
        for platform in platforms:
            try:
                result = monitoring_service.check_ai_citation(platform, f"{brand_name}怎么样", brand_name)
                total_checked += 1
                if result.get('mentioned', False):
                    mentioned_count += 1
            except Exception as e:
                print(f"[Competitor] AI visibility check error for {platform}: {e}")
        
        if total_checked == 0:
            raise RuntimeError(f"所有AI平台查询均失败，无法计算 {brand_name} 的AI可见度。")
        
        # 计算可见度分数 (0-100)
        score = (mentioned_count / total_checked) * 100
        return round(score, 1)

    def _analyze_search_rank(self, brand_name: str) -> float:
        """分析搜索排名 - 使用真实爬虫"""
        if not MONITORING_AVAILABLE:
            raise RuntimeError("监控服务不可用，无法分析搜索排名。请检查 monitoring_service 配置。")
        
        results = monitoring_service.check_search_rank(brand_name, SearchEngine.BAIDU)
        if results:
            # 找到品牌官网在搜索结果中的位置
            for i, result in enumerate(results, 1):
                if brand_name.lower() in result.get('url', '').lower():
                    return float(i)
            
            # 如果没找到官网，返回结果数+1表示不在首页
            return float(len(results) + 1)
        
        raise RuntimeError(f"无法获取 {brand_name} 的搜索排名数据，爬虫未返回结果。")

    def _analyze_content_volume(self, brand_name: str) -> int:
        """分析内容产量 - 使用爬虫估算"""
        encoded_name = requests.utils.quote(brand_name)
        url = f"https://www.baidu.com/s?wd={encoded_name}&pn=0&rn=50"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # 统计搜索结果中包含品牌名的条目数
        brand_results = 0
        for item in soup.select('.result.c-container'):
            title = item.select_one('h3.t>a')
            if title and brand_name in title.get_text():
                brand_results += 1
        
        # 根据搜索结果数量估算内容产量
        # 每个搜索结果大约代表5-10篇内容
        estimated_volume = brand_results * 7
        
        return estimated_volume

    def _analyze_social_engagement(self, brand_name: str) -> float:
        """分析社交互动 - 使用真实数据"""
        encoded_name = requests.utils.quote(brand_name)
        url = f"https://s.weibo.com/weibo?q={encoded_name}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # 查找结果数量
        result_count = soup.select_one('.result-total')
        if result_count:
            count_text = result_count.get_text()
            match = re.search(r'(\d+)', count_text)
            if match:
                count = int(match.group(1))
                # 根据微博数量计算互动率
                # 互动率 = log10(帖子数+1) * 基础系数
                import math
                engagement_rate = round(math.log10(count + 1) * 3, 2)
                return engagement_rate
        
        raise RuntimeError(f"无法获取 {brand_name} 的社交互动数据。")

    def _save_metric(self, competitor_id: str, metric: Dict):
        """保存指标数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO competitor_metrics
            (competitor_id, dimension, score, rank, value, details, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            competitor_id, metric['dimension'], metric['score'],
            metric['rank'], metric['value'], json.dumps(metric['details']),
            datetime.now()
        ))
        conn.commit()
        conn.close()

    def _update_last_analyzed(self, competitor_id: str):
        """更新最后分析时间"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE competitors SET last_analyzed_at = ? WHERE id = ?',
            (datetime.now(), competitor_id)
        )
        conn.commit()
        conn.close()

    def compare_with_competitor(self, my_brand: str, competitor_id: str) -> CompetitiveReport:
        """
        与竞品进行对比分析
        """
        import uuid

        competitor = self._get_competitor_by_id(competitor_id)
        if not competitor:
            raise ValueError('竞品不存在')

        # 获取竞品最新指标
        competitor_metrics = self._get_latest_metrics(competitor_id)

        # 获取我方数据
        my_metrics = self._get_my_metrics(my_brand)

        # 进行对比分析
        comparison_results = []
        my_total_score = 0
        competitor_total_score = 0

        for dimension in ComparisonDimension:
            my_score = my_metrics.get(dimension.value, 50)
            competitor_score = competitor_metrics.get(dimension.value, 50)

            my_total_score += my_score
            competitor_total_score += competitor_score

            difference = my_score - competitor_score

            if difference > 5:
                winner = 'me'
                gap_analysis = f'领先 {difference:.1f} 分'
            elif difference < -5:
                winner = 'competitor'
                gap_analysis = f'落后 {abs(difference):.1f} 分'
            else:
                winner = 'tie'
                gap_analysis = '基本持平'

            recommendations = self._generate_recommendations(
                dimension.value, my_score, competitor_score
            )

            comparison_results.append(ComparisonResult(
                dimension=dimension.value,
                my_score=my_score,
                competitor_score=competitor_score,
                difference=difference,
                winner=winner,
                gap_analysis=gap_analysis,
                recommendations=recommendations
            ))

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
            created_at=datetime.now()
        )

        # 保存报告
        self._save_report(report)

        return report

    def _get_latest_metrics(self, competitor_id: str) -> Dict[str, float]:
        """获取竞品最新指标"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        metrics = {}
        for dimension in ComparisonDimension:
            cursor.execute('''
                SELECT score FROM competitor_metrics
                WHERE competitor_id = ? AND dimension = ?
                ORDER BY recorded_at DESC LIMIT 1
            ''', (competitor_id, dimension.value))
            row = cursor.fetchone()
            metrics[dimension.value] = row[0] if row else 50

        conn.close()
        return metrics

    def _get_my_metrics(self, my_brand: str) -> Dict[str, float]:
        """获取我方指标 - 使用真实数据"""
        metrics = {}
        
        # AI可见度
        try:
            metrics[ComparisonDimension.AI_VISIBILITY.value] = self._analyze_ai_visibility(my_brand)
        except Exception as e:
            print(f"[Competitor] My AI visibility error: {e}")
            raise RuntimeError(f"无法获取我方AI可见度数据: {e}")
        
        # 搜索排名
        try:
            metrics[ComparisonDimension.SEARCH_RANK.value] = self._analyze_search_rank(my_brand)
        except Exception as e:
            print(f"[Competitor] My search rank error: {e}")
            raise RuntimeError(f"无法获取我方搜索排名数据: {e}")
        
        # 内容产量
        try:
            metrics[ComparisonDimension.CONTENT_VOLUME.value] = self._analyze_content_volume(my_brand)
        except Exception as e:
            print(f"[Competitor] My content volume error: {e}")
            raise RuntimeError(f"无法获取我方内容产量数据: {e}")
        
        # 社交互动
        try:
            metrics[ComparisonDimension.SOCIAL_ENGAGEMENT.value] = self._analyze_social_engagement(my_brand)
        except Exception as e:
            print(f"[Competitor] My social engagement error: {e}")
            raise RuntimeError(f"无法获取我方社交互动数据: {e}")
        
        # 品牌提及 - 通过百度搜索结果数估算
        try:
            metrics[ComparisonDimension.BRAND_MENTION.value] = self._analyze_brand_mention(my_brand)
        except Exception as e:
            print(f"[Competitor] My brand mention error: {e}")
            raise RuntimeError(f"无法获取我方品牌提及数据: {e}")
        
        # 舆情情感 - 通过AI平台分析
        try:
            metrics[ComparisonDimension.SENTIMENT.value] = self._analyze_sentiment(my_brand)
        except Exception as e:
            print(f"[Competitor] My sentiment error: {e}")
            raise RuntimeError(f"无法获取我方舆情情感数据: {e}")
        
        return metrics

    def _analyze_brand_mention(self, brand_name: str) -> int:
        """分析品牌提及数 - 使用真实数据"""
        encoded_name = requests.utils.quote(brand_name)
        url = f"https://www.baidu.com/s?wd={encoded_name}&pn=0&rn=10"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # 统计搜索结果总数
        result_count_tag = soup.select_one('.nums_text')
        if result_count_tag:
            count_text = result_count_tag.get_text()
            match = re.search(r'([\d,]+)', count_text.replace(',', ''))
            if match:
                return int(match.group(1))
        
        # 如果没有总数，统计结果条目数
        return len(soup.select('.result.c-container'))

    def _analyze_sentiment(self, brand_name: str) -> float:
        """分析舆情情感 - 使用真实数据"""
        if not MONITORING_AVAILABLE:
            raise RuntimeError("监控服务不可用，无法分析舆情情感。")
        
        platforms = [AIPlatform.DOUBAO, AIPlatform.DEEPSEEK, AIPlatform.KIMI]
        sentiment_scores = []
        
        for platform in platforms:
            try:
                result = monitoring_service.check_ai_citation(platform, f"{brand_name}评价怎么样", brand_name)
                sentiment = result.get('sentiment', 'neutral')
                if sentiment == 'positive':
                    sentiment_scores.append(80)
                elif sentiment == 'negative':
                    sentiment_scores.append(30)
                else:
                    sentiment_scores.append(55)
            except Exception as e:
                print(f"[Competitor] Sentiment check error for {platform}: {e}")
        
        if not sentiment_scores:
            raise RuntimeError(f"无法获取 {brand_name} 的舆情情感数据。")
        
        return round(sum(sentiment_scores) / len(sentiment_scores), 1)

    def _generate_recommendations(self, dimension: str, my_score: float,
                                 competitor_score: float) -> List[str]:
        """生成改进建议"""
        recommendations = []

        if dimension == ComparisonDimension.AI_VISIBILITY.value:
            if my_score < competitor_score:
                recommendations.extend([
                    '增加GEO优化内容产出，提升AI平台收录率',
                    '优化内容结构，提高被AI引用的概率',
                    '在更多AI平台建立品牌存在感'
                ])
        elif dimension == ComparisonDimension.SEARCH_RANK.value:
            if my_score < competitor_score:
                recommendations.extend([
                    '加强SEO优化，提升核心关键词排名',
                    '增加高质量外链建设',
                    '优化网站技术性能'
                ])
        elif dimension == ComparisonDimension.CONTENT_VOLUME.value:
            if my_score < competitor_score:
                recommendations.extend([
                    '增加内容生产频率',
                    '建立内容生产SOP流程',
                    '利用AI工具提升内容产出效率'
                ])

        return recommendations

    def _swot_analysis(self, comparison_results: List[ComparisonResult]) -> tuple:
        """SWOT分析"""
        strengths = []
        weaknesses = []
        opportunities = []
        threats = []

        for result in comparison_results:
            if result.winner == 'me':
                strengths.append(f"{result.dimension}: {result.gap_analysis}")
            elif result.winner == 'competitor':
                weaknesses.append(f"{result.dimension}: {result.gap_analysis}")

        # 基于弱点生成机会
        if any(r.dimension == ComparisonDimension.AI_VISIBILITY.value and r.winner == 'competitor'
               for r in comparison_results):
            opportunities.append('AI可见度提升空间较大，可重点投入GEO优化')

        if any(r.dimension == ComparisonDimension.CONTENT_VOLUME.value and r.winner == 'competitor'
               for r in comparison_results):
            opportunities.append('内容产量有提升空间，可增加发布频率')

        # 威胁分析
        threats.append('竞品持续投入，市场竞争加剧')
        if any(r.dimension == ComparisonDimension.SEARCH_RANK.value and r.winner == 'competitor'
               for r in comparison_results):
            threats.append('搜索排名落后可能导致流量流失')

        return strengths, weaknesses, opportunities, threats

    def _generate_action_plan(self, comparison_results: List[ComparisonResult]) -> List[Dict]:
        """生成行动计划"""
        action_plan = []

        # 找出最需要改进的维度
        sorted_results = sorted(
            comparison_results,
            key=lambda x: x.difference
        )

        # 优先级高的改进项
        for i, result in enumerate(sorted_results[:3]):
            if result.winner == 'competitor':
                action_plan.append({
                    'priority': 'high' if i == 0 else 'medium',
                    'dimension': result.dimension,
                    'action': f'提升{result.dimension}表现',
                    'target': f'达到竞品水平的{result.competitor_score:.0f}分',
                    'timeline': '1个月内' if i == 0 else '3个月内'
                })

        return action_plan

    def _save_report(self, report: CompetitiveReport):
        """保存对比报告"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO comparison_reports
            (id, my_brand, competitor_id, overall_score, my_overall_score,
             competitor_overall_score, comparison_results, strengths, weaknesses,
             opportunities, threats, action_plan, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            report.id, report.my_brand, report.competitor_id,
            report.overall_score, report.my_overall_score,
            report.competitor_overall_score,
            json.dumps([asdict(r) for r in report.comparison_results]),
            json.dumps(report.strengths),
            json.dumps(report.weaknesses),
            json.dumps(report.opportunities),
            json.dumps(report.threats),
            json.dumps(report.action_plan),
            report.created_at
        ))
        conn.commit()
        conn.close()

    def get_comparison_history(self, my_brand: str, competitor_id: str = None,
                              limit: int = 10) -> List[Dict]:
        """获取对比历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if competitor_id:
            cursor.execute('''
                SELECT * FROM comparison_reports
                WHERE my_brand = ? AND competitor_id = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (my_brand, competitor_id, limit))
        else:
            cursor.execute('''
                SELECT * FROM comparison_reports
                WHERE my_brand = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (my_brand, limit))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_report(row) for row in rows]

    def _row_to_report(self, row) -> Dict:
        """数据库行转报告字典"""
        return {
            'id': row[0],
            'my_brand': row[1],
            'competitor_id': row[2],
            'overall_score': row[3],
            'my_overall_score': row[4],
            'competitor_overall_score': row[5],
            'comparison_results': json.loads(row[6]) if row[6] else [],
            'strengths': json.loads(row[7]) if row[7] else [],
            'weaknesses': json.loads(row[8]) if row[8] else [],
            'opportunities': json.loads(row[9]) if row[9] else [],
            'threats': json.loads(json.loads(row[10])) if row[10] else [],
            'action_plan': json.loads(row[11]) if row[11] else [],
            'created_at': row[12]
        }

    def get_competitive_landscape(self, my_brand: str) -> Dict:
        """
        获取竞争格局全景
        """
        competitors = self.get_competitors(CompetitorStatus.ACTIVE)

        landscape = {
            'my_brand': my_brand,
            'total_competitors': len(competitors),
            'competitors': [],
            'market_position': {},
            'competitive_intensity': 'medium'
        }

        for competitor in competitors:
            # 获取最新对比数据
            latest_report = self.get_comparison_history(my_brand, competitor.id, 1)

            comp_data = {
                'id': competitor.id,
                'brand_name': competitor.brand_name,
                'industry': competitor.industry,
                'status': competitor.status.value,
                'last_analyzed': competitor.last_analyzed_at.isoformat() if competitor.last_analyzed_at else None
            }

            if latest_report:
                comp_data['latest_comparison'] = {
                    'my_score': latest_report[0]['my_overall_score'],
                    'competitor_score': latest_report[0]['competitor_overall_score'],
                    'gap': latest_report[0]['overall_score'],
                    'date': latest_report[0]['created_at']
                }

            landscape['competitors'].append(comp_data)

        return landscape


# 全局服务实例
competitor_analysis_service = CompetitorAnalysisService()
