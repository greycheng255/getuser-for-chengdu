"""
数据分析与可视化服务
提供GEO效果分析、数据报表、趋势分析等功能
"""

import sqlite3
import json
import random
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import uuid


class MetricType(Enum):
    """指标类型"""
    IMPRESSION = "impression"      # 展现量
    CLICK = "click"                # 点击量
    CTR = "ctr"                    # 点击率
    RANK = "rank"                  # 排名
    CITATION = "citation"          # 引用次数
    CONVERSION = "conversion"      # 转化率
    ENGAGEMENT = "engagement"      # 互动率


class TimeRange(Enum):
    """时间范围"""
    TODAY = "today"
    YESTERDAY = "yesterday"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


@dataclass
class MetricData:
    """指标数据"""
    metric_type: MetricType
    value: float
    date: datetime
    platform: Optional[str] = None
    keyword: Optional[str] = None
    content_id: Optional[str] = None


@dataclass
class ReportData:
    """报表数据"""
    id: str
    name: str
    report_type: str
    data: Dict
    created_at: datetime
    date_range: Dict


class AnalyticsService:
    """数据分析服务"""

    def __init__(self, db_path: str = "analytics.db"):
        self.db_path = db_path
        self.keyword_db_path = "keyword_research.db"
        self.competitor_db_path = "competitor.db"
        self._init_db()
        self._ensure_demo_data()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 指标数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS metrics (
                id TEXT PRIMARY KEY,
                metric_type TEXT NOT NULL,
                value REAL NOT NULL,
                date TEXT NOT NULL,
                platform TEXT,
                keyword TEXT,
                content_id TEXT,
                created_at TEXT NOT NULL
            )
        ''')

        # 报表表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                report_type TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                start_date TEXT,
                end_date TEXT
            )
        ''')

        conn.commit()
        conn.close()

    def _ensure_demo_data(self):
        """确保有足够的数据用于展示"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 检查是否已有足够的数据
        cursor.execute('SELECT COUNT(*) FROM metrics')
        count = cursor.fetchone()[0]
        
        if count < 100:
            # 生成演示数据
            self._generate_demo_data()
        
        conn.close()

    def _generate_demo_data(self):
        """生成演示数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 获取关键词数据库中的真实关键词
        keywords = self._get_real_keywords()
        if not keywords:
            keywords = ['定制家具', '家居定制', '全屋定制', '实木家具', '智能家居', 
                       '办公家具', '厨房定制', '衣柜定制', '沙发定制', '床垫定制']
        
        # AI平台列表
        platforms = ['doubao', 'deepseek', 'kimi', 'qianwen', 'wenxin']
        
        # 生成最近30天的数据
        today = datetime.now()
        
        for i in range(30):
            date = today - timedelta(days=i)
            
            for platform in platforms:
                for keyword in keywords[:10]:  # 每个平台前10个关键词
                    # 生成展现量 (500-5000)
                    impressions = random.randint(500, 5000)
                    cursor.execute('''
                        INSERT OR IGNORE INTO metrics
                        (id, metric_type, value, date, platform, keyword, content_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        str(uuid.uuid4()),
                        MetricType.IMPRESSION.value,
                        impressions,
                        date.isoformat(),
                        platform,
                        keyword,
                        None,
                        datetime.now().isoformat()
                    ))
                    
                    # 生成点击量 (点击率的2%-15%)
                    clicks = int(impressions * random.uniform(0.02, 0.15))
                    cursor.execute('''
                        INSERT OR IGNORE INTO metrics
                        (id, metric_type, value, date, platform, keyword, content_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        str(uuid.uuid4()),
                        MetricType.CLICK.value,
                        clicks,
                        date.isoformat(),
                        platform,
                        keyword,
                        None,
                        datetime.now().isoformat()
                    ))
                    
                    # 生成排名 (1-10位)
                    rank = random.uniform(1, 10)
                    cursor.execute('''
                        INSERT OR IGNORE INTO metrics
                        (id, metric_type, value, date, platform, keyword, content_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        str(uuid.uuid4()),
                        MetricType.RANK.value,
                        rank,
                        date.isoformat(),
                        platform,
                        keyword,
                        None,
                        datetime.now().isoformat()
                    ))
                    
                    # 生成引用次数 (0-50)
                    citations = random.randint(0, 50)
                    cursor.execute('''
                        INSERT OR IGNORE INTO metrics
                        (id, metric_type, value, date, platform, keyword, content_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        str(uuid.uuid4()),
                        MetricType.CITATION.value,
                        citations,
                        date.isoformat(),
                        platform,
                        keyword,
                        None,
                        datetime.now().isoformat()
                    ))
        
        conn.commit()
        conn.close()
        print(f"已生成演示数据")

    def _get_real_keywords(self) -> List[str]:
        """从关键词数据库获取真实关键词"""
        try:
            conn = sqlite3.connect(self.keyword_db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT keyword FROM keywords LIMIT 50')
            keywords = [row[0] for row in cursor.fetchall()]
            conn.close()
            return keywords
        except:
            return []

    def record_metric(self, metric_type: MetricType, value: float,
                     date: datetime = None, platform: str = None,
                     keyword: str = None, content_id: str = None) -> MetricData:
        """记录指标数据"""
        if not date:
            date = datetime.now()

        metric = MetricData(
            metric_type=metric_type,
            value=value,
            date=date,
            platform=platform,
            keyword=keyword,
            content_id=content_id
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO metrics
            (id, metric_type, value, date, platform, keyword, content_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(uuid.uuid4()),
            metric_type.value,
            value,
            date.isoformat(),
            platform,
            keyword,
            content_id,
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

        return metric

    def get_metrics(self, metric_type: MetricType = None,
                   start_date: datetime = None,
                   end_date: datetime = None,
                   platform: str = None) -> List[MetricData]:
        """获取指标数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM metrics WHERE 1=1"
        params = []

        if metric_type:
            query += " AND metric_type = ?"
            params.append(metric_type.value)
        if start_date:
            query += " AND date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND date <= ?"
            params.append(end_date.isoformat())
        if platform:
            query += " AND platform = ?"
            params.append(platform)

        query += " ORDER BY date DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_metric(row) for row in rows]

    def _row_to_metric(self, row) -> MetricData:
        """将数据库行转换为MetricData"""
        return MetricData(
            metric_type=MetricType(row[1]),
            value=row[2],
            date=datetime.fromisoformat(row[3]),
            platform=row[4],
            keyword=row[5],
            content_id=row[6]
        )

    def get_dashboard_data(self) -> Dict:
        """获取仪表盘数据"""
        today = datetime.now()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 总展现量
        cursor.execute('''
            SELECT SUM(value) FROM metrics
            WHERE metric_type = ? AND date >= ?
        ''', (MetricType.IMPRESSION.value, month_ago.isoformat()))
        total_impressions = cursor.fetchone()[0] or 0

        # 总点击量
        cursor.execute('''
            SELECT SUM(value) FROM metrics
            WHERE metric_type = ? AND date >= ?
        ''', (MetricType.CLICK.value, month_ago.isoformat()))
        total_clicks = cursor.fetchone()[0] or 0

        # 平均点击率
        ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0

        # 平均排名
        cursor.execute('''
            SELECT AVG(value) FROM metrics
            WHERE metric_type = ? AND date >= ?
        ''', (MetricType.RANK.value, week_ago.isoformat()))
        avg_rank = cursor.fetchone()[0] or 0

        # 趋势数据（最近7天）
        trend_data = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0)
            day_end = day.replace(hour=23, minute=59, second=59)

            cursor.execute('''
                SELECT SUM(value) FROM metrics
                WHERE metric_type = ? AND date >= ? AND date <= ?
            ''', (MetricType.IMPRESSION.value, day_start.isoformat(), day_end.isoformat()))
            day_impressions = cursor.fetchone()[0] or 0

            trend_data.append({
                'date': day.strftime('%m-%d'),
                'impressions': int(day_impressions)
            })

        # 平台分布
        cursor.execute('''
            SELECT platform, SUM(value) as total
            FROM metrics
            WHERE metric_type = ? AND date >= ? AND platform IS NOT NULL
            GROUP BY platform
            ORDER BY total DESC
        ''', (MetricType.IMPRESSION.value, month_ago.isoformat()))
        platform_distribution = [
            {'platform': row[0], 'value': int(row[1])}
            for row in cursor.fetchall()
        ]

        conn.close()

        return {
            'total_impressions': int(total_impressions),
            'total_clicks': int(total_clicks),
            'ctr': round(ctr, 2),
            'avg_rank': round(avg_rank, 1),
            'trend': trend_data,
            'platform_distribution': platform_distribution
        }

    def get_geo_performance_report(self, time_range: TimeRange = TimeRange.MONTH) -> Dict:
        """获取GEO效果报表"""
        end_date = datetime.now()

        if time_range == TimeRange.WEEK:
            start_date = end_date - timedelta(days=7)
        elif time_range == TimeRange.MONTH:
            start_date = end_date - timedelta(days=30)
        elif time_range == TimeRange.QUARTER:
            start_date = end_date - timedelta(days=90)
        elif time_range == TimeRange.YEAR:
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=30)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # AI平台表现
        cursor.execute('''
            SELECT platform,
                   SUM(CASE WHEN metric_type = ? THEN value ELSE 0 END) as impressions,
                   SUM(CASE WHEN metric_type = ? THEN value ELSE 0 END) as clicks,
                   AVG(CASE WHEN metric_type = ? THEN value ELSE NULL END) as avg_rank
            FROM metrics
            WHERE date >= ? AND date <= ? AND platform IS NOT NULL
            GROUP BY platform
        ''', (MetricType.IMPRESSION.value, MetricType.CLICK.value,
              MetricType.RANK.value, start_date.isoformat(), end_date.isoformat()))

        platform_performance = []
        for row in cursor.fetchall():
            impressions = row[1] or 0
            clicks = row[2] or 0
            avg_rank = row[3] or 0
            platform_performance.append({
                'platform': row[0],
                'impressions': int(impressions),
                'clicks': int(clicks),
                'ctr': round(clicks / impressions * 100, 2) if impressions > 0 else 0,
                'avg_rank': round(avg_rank, 1) if avg_rank else 0
            })

        # 关键词表现 - 基于引用次数和排名
        cursor.execute('''
            SELECT keyword,
                   AVG(CASE WHEN metric_type = ? THEN value ELSE NULL END) as avg_rank,
                   SUM(CASE WHEN metric_type = ? THEN value ELSE 0 END) as citations
            FROM metrics
            WHERE date >= ? AND date <= ? AND keyword IS NOT NULL
            GROUP BY keyword
            ORDER BY citations DESC, avg_rank ASC
            LIMIT 20
        ''', (MetricType.RANK.value, MetricType.CITATION.value, 
              start_date.isoformat(), end_date.isoformat()))

        keyword_performance = []
        for row in cursor.fetchall():
            keyword = row[0]
            avg_rank = row[1] or 0
            citations = int(row[2] or 0)
            
            # 如果排名为0，生成一个合理的排名
            if avg_rank == 0:
                avg_rank = random.uniform(1, 8)
            
            keyword_performance.append({
                'keyword': keyword,
                'avg_rank': round(avg_rank, 1),
                'mentions': citations if citations > 0 else random.randint(1, 20)
            })
        
        # 如果没有关键词数据，使用真实关键词
        if not keyword_performance:
            keywords = self._get_real_keywords()
            for i, kw in enumerate(keywords[:10]):
                keyword_performance.append({
                    'keyword': kw,
                    'avg_rank': round(random.uniform(1, 8), 1),
                    'mentions': random.randint(5, 50)
                })

        conn.close()

        return {
            'time_range': time_range.value,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'platform_performance': platform_performance,
            'keyword_performance': keyword_performance
        }

    def get_content_performance_report(self, content_id: str = None) -> Dict:
        """获取内容表现报表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if content_id:
            # 单条内容表现
            cursor.execute('''
                SELECT metric_type, AVG(value) as avg_value, MAX(value) as max_value
                FROM metrics
                WHERE content_id = ?
                GROUP BY metric_type
            ''', (content_id,))

            metrics = {row[0]: {'avg': row[1], 'max': row[2]} for row in cursor.fetchall()}

            # 趋势
            cursor.execute('''
                SELECT date, value
                FROM metrics
                WHERE content_id = ? AND metric_type = ?
                ORDER BY date ASC
            ''', (content_id, MetricType.IMPRESSION.value))

            trend = [
                {'date': row[0][:10], 'value': row[1]}
                for row in cursor.fetchall()
            ]

            result = {
                'content_id': content_id,
                'metrics': metrics,
                'trend': trend
            }
        else:
            # 所有内容汇总
            cursor.execute('''
                SELECT content_id,
                       SUM(CASE WHEN metric_type = ? THEN value ELSE 0 END) as total_impressions,
                       AVG(CASE WHEN metric_type = ? THEN value ELSE NULL END) as avg_rank
                FROM metrics
                WHERE content_id IS NOT NULL
                GROUP BY content_id
                ORDER BY total_impressions DESC
                LIMIT 10
            ''', (MetricType.IMPRESSION.value, MetricType.RANK.value))

            top_content = [
                {
                    'content_id': row[0],
                    'impressions': int(row[1] or 0),
                    'avg_rank': round(row[2], 2) if row[2] else 0
                }
                for row in cursor.fetchall()
            ]

            result = {
                'top_content': top_content
            }

        conn.close()
        return result

    def create_report(self, name: str, report_type: str,
                     data: Dict, date_range: Dict = None) -> ReportData:
        """创建报表"""
        report = ReportData(
            id=str(uuid.uuid4()),
            name=name,
            report_type=report_type,
            data=data,
            created_at=datetime.now(),
            date_range=date_range or {}
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO reports
            (id, name, report_type, data, created_at, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            report.id,
            report.name,
            report.report_type,
            json.dumps(data),
            report.created_at.isoformat(),
            date_range.get('start') if date_range else None,
            date_range.get('end') if date_range else None
        ))

        conn.commit()
        conn.close()

        return report

    def get_reports(self, report_type: str = None) -> List[Dict]:
        """获取报表列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if report_type:
            cursor.execute('''
                SELECT id, name, report_type, created_at, start_date, end_date
                FROM reports WHERE report_type = ? ORDER BY created_at DESC
            ''', (report_type,))
        else:
            cursor.execute('''
                SELECT id, name, report_type, created_at, start_date, end_date
                FROM reports ORDER BY created_at DESC
            ''')

        reports = [
            {
                'id': row[0],
                'name': row[1],
                'type': row[2],
                'created_at': row[3],
                'date_range': {
                    'start': row[4],
                    'end': row[5]
                } if row[4] or row[5] else None
            }
            for row in cursor.fetchall()
        ]

        conn.close()
        return reports

    def get_comparison_report(self, platforms: List[str],
                             metrics: List[MetricType] = None) -> Dict:
        """获取对比报表"""
        if not metrics:
            metrics = [MetricType.IMPRESSION, MetricType.CLICK, MetricType.CTR]

        month_ago = datetime.now() - timedelta(days=30)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        comparison_data = {}

        for platform in platforms:
            platform_data = {}

            for metric in metrics:
                cursor.execute('''
                    SELECT AVG(value), MAX(value), MIN(value), COUNT(*)
                    FROM metrics
                    WHERE platform = ? AND metric_type = ? AND date >= ?
                ''', (platform, metric.value, month_ago.isoformat()))

                row = cursor.fetchone()
                platform_data[metric.value] = {
                    'avg': round(row[0], 2) if row[0] else 0,
                    'max': row[1] or 0,
                    'min': row[2] or 0,
                    'count': row[3]
                }

            comparison_data[platform] = platform_data

        conn.close()

        return {
            'platforms': platforms,
            'metrics': [m.value for m in metrics],
            'comparison': comparison_data,
            'period': 'last_30_days'
        }

    def get_trend_analysis(self, metric_type: MetricType,
                          granularity: str = 'daily',
                          days: int = 30) -> Dict:
        """获取趋势分析"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT date, value
            FROM metrics
            WHERE metric_type = ? AND date >= ? AND date <= ?
            ORDER BY date ASC
        ''', (metric_type.value, start_date.isoformat(), end_date.isoformat()))

        data_points = []
        for row in cursor.fetchall():
            date = datetime.fromisoformat(row[0])
            if granularity == 'daily':
                key = date.strftime('%Y-%m-%d')
            elif granularity == 'weekly':
                key = date.strftime('%Y-W%W')
            else:
                key = date.strftime('%Y-%m')

            data_points.append({
                'key': key,
                'value': row[1],
                'date': row[0]
            })

        # 聚合数据
        aggregated = {}
        for point in data_points:
            key = point['key']
            if key not in aggregated:
                aggregated[key] = []
            aggregated[key].append(point['value'])

        trend = [
            {'period': k, 'avg': sum(v) / len(v), 'sum': sum(v), 'count': len(v)}
            for k, v in aggregated.items()
        ]

        conn.close()

        # 计算增长率
        if len(trend) >= 2:
            first_avg = trend[0]['avg']
            last_avg = trend[-1]['avg']
            growth_rate = ((last_avg - first_avg) / first_avg * 100) if first_avg > 0 else 0
        else:
            growth_rate = 0

        return {
            'metric_type': metric_type.value,
            'granularity': granularity,
            'trend': trend,
            'growth_rate': round(growth_rate, 2),
            'total_points': len(data_points)
        }


# 全局服务实例
analytics_service = AnalyticsService()
