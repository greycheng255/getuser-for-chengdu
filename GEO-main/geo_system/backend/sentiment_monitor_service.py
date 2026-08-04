"""
舆情监控系统
实现品牌舆情的实时监控、分析和预警
"""

import json
import sqlite3
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class SentimentType(Enum):
    """情感类型"""
    POSITIVE = "positive"      # 正面
    NEUTRAL = "neutral"        # 中性
    NEGATIVE = "negative"      # 负面
    CRITICAL = "critical"      # 严重负面


class SourceType(Enum):
    """舆情来源"""
    NEWS = "news"              # 新闻
    WEIBO = "weibo"            # 微博
    ZHIHU = "zhihu"            # 知乎
    XIAOHONGSHU = "xiaohongshu" # 小红书
    DOUYIN = "douyin"          # 抖音
    FORUM = "forum"            # 论坛
    COMMENT = "comment"        # 评论
    QA = "qa"                  # 问答
    VIDEO = "video"            # 视频


class AlertLevel(Enum):
    """预警级别"""
    INFO = "info"              # 信息
    WARNING = "warning"        # 警告
    DANGER = "danger"          # 危险
    CRITICAL = "critical"      # 紧急


@dataclass
class SentimentItem:
    """舆情条目"""
    id: str
    brand_name: str
    source: SourceType
    source_name: str
    title: str
    content: str
    url: str
    sentiment: SentimentType
    sentiment_score: float  # -1.0 到 1.0
    keywords: List[str]
    author: str
    publish_time: datetime
    crawl_time: datetime
    engagement: Dict  # 互动数据
    is_read: bool = False
    is_alert: bool = False


@dataclass
class SentimentAlert:
    """舆情预警"""
    id: str
    brand_name: str
    alert_level: AlertLevel
    alert_type: str
    title: str
    description: str
    related_items: List[str]  # 关联的舆情ID
    created_at: datetime
    resolved_at: datetime = None
    is_resolved: bool = False


@dataclass
class SentimentStats:
    """舆情统计"""
    brand_name: str
    total_count: int
    positive_count: int
    neutral_count: int
    negative_count: int
    critical_count: int
    sentiment_score: float  # 综合情感得分
    trend: str  # up/down/stable
    hot_topics: List[Dict]
    risk_keywords: List[str]


class SentimentMonitorService:
    """
    舆情监控服务
    """

    def __init__(self, db_path: str = "sentiment.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 舆情数据表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sentiment_items (
                id TEXT PRIMARY KEY,
                brand_name TEXT,
                source TEXT,
                source_name TEXT,
                title TEXT,
                content TEXT,
                url TEXT,
                sentiment TEXT,
                sentiment_score REAL,
                keywords TEXT,
                author TEXT,
                publish_time TIMESTAMP,
                crawl_time TIMESTAMP,
                engagement TEXT,
                is_read BOOLEAN DEFAULT 0,
                is_alert BOOLEAN DEFAULT 0
            )
        ''')

        # 预警表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sentiment_alerts (
                id TEXT PRIMARY KEY,
                brand_name TEXT,
                alert_level TEXT,
                alert_type TEXT,
                title TEXT,
                description TEXT,
                related_items TEXT,
                created_at TIMESTAMP,
                resolved_at TIMESTAMP,
                is_resolved BOOLEAN DEFAULT 0
            )
        ''')

        # 监控品牌表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monitored_brands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_name TEXT UNIQUE,
                keywords TEXT,
                alert_threshold REAL DEFAULT -0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')

        conn.commit()
        conn.close()

    def add_monitored_brand(self, brand_name: str, keywords: List[str] = None,
                           alert_threshold: float = -0.5):
        """添加监控品牌"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO monitored_brands (brand_name, keywords, alert_threshold, created_at)
                VALUES (?, ?, ?, ?)
            ''', (
                brand_name,
                json.dumps(keywords or [brand_name]),
                alert_threshold,
                datetime.now()
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            # 品牌已存在，更新关键词
            cursor.execute('''
                UPDATE monitored_brands 
                SET keywords = ?, alert_threshold = ?
                WHERE brand_name = ?
            ''', (json.dumps(keywords or [brand_name]), alert_threshold, brand_name))
            conn.commit()
        finally:
            conn.close()

    def get_monitored_brands(self) -> List[Dict]:
        """获取监控品牌列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM monitored_brands WHERE is_active = 1
        ''')

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'id': row[0],
                'brand_name': row[1],
                'keywords': json.loads(row[2]) if row[2] else [],
                'alert_threshold': row[3],
                'created_at': row[4]
            }
            for row in rows
        ]

    def crawl_sentiment_data(self, brand_name: str, keywords: List[str] = None,
                            days: int = 7) -> List[SentimentItem]:
        """
        爬取舆情数据（模拟）
        实际应该对接各平台的API或爬虫
        """
        items = []

        # 模拟从不同来源获取数据
        sources = [
            (SourceType.NEWS, "百度新闻", "news.baidu.com"),
            (SourceType.WEIBO, "微博", "weibo.com"),
            (SourceType.ZHIHU, "知乎", "zhihu.com"),
            (SourceType.XIAOHONGSHU, "小红书", "xiaohongshu.com"),
            (SourceType.FORUM, "百度贴吧", "tieba.baidu.com"),
            (SourceType.QA, "百度知道", "zhidao.baidu.com"),
        ]

        # 模拟生成舆情数据
        for i, (source, source_name, domain) in enumerate(sources):
            # 模拟正面舆情
            items.append(self._create_mock_item(
                brand_name, source, source_name,
                f"{brand_name}产品质量很好，服务也很到位",
                SentimentType.POSITIVE, 0.8,
                days
            ))

            # 模拟中性舆情
            items.append(self._create_mock_item(
                brand_name, source, source_name,
                f"{brand_name}的产品怎么样？有人用过吗？",
                SentimentType.NEUTRAL, 0.0,
                days
            ))

            # 模拟负面舆情（少量）
            if i % 3 == 0:
                items.append(self._create_mock_item(
                    brand_name, source, source_name,
                    f"{brand_name}售后服务太差了，投诉无门",
                    SentimentType.NEGATIVE, -0.6,
                    days
                ))

        # 保存到数据库
        for item in items:
            self._save_sentiment_item(item)

        return items

    def _create_mock_item(self, brand_name: str, source: SourceType,
                         source_name: str, content: str,
                         sentiment: SentimentType, score: float,
                         days: int) -> SentimentItem:
        """创建模拟舆情条目"""
        import uuid

        return SentimentItem(
            id=str(uuid.uuid4()),
            brand_name=brand_name,
            source=source,
            source_name=source_name,
            title=content[:30] + "..." if len(content) > 30 else content,
            content=content,
            url=f"https://example.com/{uuid.uuid4().hex[:8]}",
            sentiment=sentiment,
            sentiment_score=score,
            keywords=[brand_name],
            author=f"用户{uuid.uuid4().hex[:6]}",
            publish_time=datetime.now() - timedelta(days=days),
            crawl_time=datetime.now(),
            engagement={"views": 100, "likes": 10, "comments": 5}
        )

    def _save_sentiment_item(self, item: SentimentItem):
        """保存舆情条目到数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT OR REPLACE INTO sentiment_items
                (id, brand_name, source, source_name, title, content, url,
                 sentiment, sentiment_score, keywords, author, publish_time,
                 crawl_time, engagement, is_read, is_alert)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item.id, item.brand_name, item.source.value, item.source_name,
                item.title, item.content, item.url, item.sentiment.value,
                item.sentiment_score, json.dumps(item.keywords), item.author,
                item.publish_time, item.crawl_time, json.dumps(item.engagement),
                item.is_read, item.is_alert
            ))
            conn.commit()
        except Exception as e:
            print(f"保存舆情数据失败: {e}")
        finally:
            conn.close()

    def get_sentiment_items(self, brand_name: str = None,
                           sentiment: SentimentType = None,
                           source: SourceType = None,
                           days: int = 7,
                           limit: int = 100) -> List[SentimentItem]:
        """获取舆情列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = 'SELECT * FROM sentiment_items WHERE 1=1'
        params = []

        if brand_name:
            query += ' AND brand_name = ?'
            params.append(brand_name)

        if sentiment:
            query += ' AND sentiment = ?'
            params.append(sentiment.value)

        if source:
            query += ' AND source = ?'
            params.append(source.value)

        query += ' AND crawl_time >= ?'
        params.append(datetime.now() - timedelta(days=days))

        query += ' ORDER BY crawl_time DESC LIMIT ?'
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_item(row) for row in rows]

    def _row_to_item(self, row) -> SentimentItem:
        """数据库行转对象"""
        return SentimentItem(
            id=row[0],
            brand_name=row[1],
            source=SourceType(row[2]),
            source_name=row[3],
            title=row[4],
            content=row[5],
            url=row[6],
            sentiment=SentimentType(row[7]),
            sentiment_score=row[8],
            keywords=json.loads(row[9]) if row[9] else [],
            author=row[10],
            publish_time=row[11],
            crawl_time=row[12],
            engagement=json.loads(row[13]) if row[13] else {},
            is_read=row[14],
            is_alert=row[15]
        )

    def get_sentiment_stats(self, brand_name: str, days: int = 7) -> SentimentStats:
        """获取舆情统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 获取统计数据
        cursor.execute('''
            SELECT sentiment, COUNT(*) as count
            FROM sentiment_items
            WHERE brand_name = ? AND crawl_time >= ?
            GROUP BY sentiment
        ''', (brand_name, datetime.now() - timedelta(days=days)))

        rows = cursor.fetchall()
        conn.close()

        # 计算统计
        stats = {
            SentimentType.POSITIVE.value: 0,
            SentimentType.NEUTRAL.value: 0,
            SentimentType.NEGATIVE.value: 0,
            SentimentType.CRITICAL.value: 0
        }
        for row in rows:
            stats[row[0]] = row[1]

        total = sum(stats.values())

        # 计算情感得分 (-100 到 100)
        if total > 0:
            sentiment_score = (
                stats[SentimentType.POSITIVE.value] * 100 +
                stats[SentimentType.NEUTRAL.value] * 0 +
                stats[SentimentType.NEGATIVE.value] * (-50) +
                stats[SentimentType.CRITICAL.value] * (-100)
            ) / total
        else:
            sentiment_score = 0

        # 获取热门话题
        hot_topics = self._extract_hot_topics(brand_name, days)

        # 获取风险关键词
        risk_keywords = self._extract_risk_keywords(brand_name, days)

        return SentimentStats(
            brand_name=brand_name,
            total_count=total,
            positive_count=stats[SentimentType.POSITIVE.value],
            neutral_count=stats[SentimentType.NEUTRAL.value],
            negative_count=stats[SentimentType.NEGATIVE.value],
            critical_count=stats[SentimentType.CRITICAL.value],
            sentiment_score=sentiment_score,
            trend="stable",  # 实际应该对比历史数据
            hot_topics=hot_topics,
            risk_keywords=risk_keywords
        )

    def _extract_hot_topics(self, brand_name: str, days: int) -> List[Dict]:
        """提取热门话题"""
        # 实际应该使用NLP进行话题提取
        # 这里返回模拟数据
        return [
            {"topic": "产品质量", "count": 15, "sentiment": "positive"},
            {"topic": "售后服务", "count": 8, "sentiment": "negative"},
            {"topic": "价格", "count": 12, "sentiment": "neutral"}
        ]

    def _extract_risk_keywords(self, brand_name: str, days: int) -> List[str]:
        """提取风险关键词"""
        # 实际应该从负面舆情中提取
        return ["投诉", "质量问题", "服务差"]

    def check_alerts(self, brand_name: str) -> List[SentimentAlert]:
        """检查舆情预警"""
        alerts = []

        # 获取品牌预警阈值
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT alert_threshold FROM monitored_brands WHERE brand_name = ?',
            (brand_name,)
        )
        row = cursor.fetchone()
        threshold = row[0] if row else -0.5
        conn.close()

        # 检查负面舆情数量
        negative_items = self.get_sentiment_items(
            brand_name=brand_name,
            sentiment=SentimentType.NEGATIVE,
            days=1
        )

        if len(negative_items) >= 3:
            alert = self._create_alert(
                brand_name,
                AlertLevel.WARNING,
                "负面舆情激增",
                f"24小时内发现{len(negative_items)}条负面舆情",
                [item.id for item in negative_items]
            )
            alerts.append(alert)

        # 检查严重负面
        critical_items = self.get_sentiment_items(
            brand_name=brand_name,
            sentiment=SentimentType.CRITICAL,
            days=1
        )

        if critical_items:
            alert = self._create_alert(
                brand_name,
                AlertLevel.CRITICAL,
                "严重负面舆情",
                f"发现{len(critical_items)}条严重负面舆情，需要立即处理",
                [item.id for item in critical_items]
            )
            alerts.append(alert)

        return alerts

    def _create_alert(self, brand_name: str, level: AlertLevel,
                     alert_type: str, description: str,
                     related_items: List[str]) -> SentimentAlert:
        """创建预警"""
        import uuid

        alert = SentimentAlert(
            id=str(uuid.uuid4()),
            brand_name=brand_name,
            alert_level=level,
            alert_type=alert_type,
            title=alert_type,
            description=description,
            related_items=related_items,
            created_at=datetime.now()
        )

        # 保存到数据库
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sentiment_alerts
            (id, brand_name, alert_level, alert_type, title, description,
             related_items, created_at, is_resolved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            alert.id, alert.brand_name, alert.alert_level.value,
            alert.alert_type, alert.title, alert.description,
            json.dumps(alert.related_items), alert.created_at, alert.is_resolved
        ))
        conn.commit()
        conn.close()

        return alert

    def get_alerts(self, brand_name: str = None,
                  level: AlertLevel = None,
                  is_resolved: bool = False) -> List[SentimentAlert]:
        """获取预警列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = 'SELECT * FROM sentiment_alerts WHERE 1=1'
        params = []

        if brand_name:
            query += ' AND brand_name = ?'
            params.append(brand_name)

        if level:
            query += ' AND alert_level = ?'
            params.append(level.value)

        query += ' AND is_resolved = ?'
        params.append(is_resolved)

        query += ' ORDER BY created_at DESC'

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [
            SentimentAlert(
                id=row[0],
                brand_name=row[1],
                alert_level=AlertLevel(row[2]),
                alert_type=row[3],
                title=row[4],
                description=row[5],
                related_items=json.loads(row[6]) if row[6] else [],
                created_at=row[7],
                resolved_at=row[8],
                is_resolved=row[9]
            )
            for row in rows
        ]

    def resolve_alert(self, alert_id: str):
        """解决预警"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE sentiment_alerts
            SET is_resolved = 1, resolved_at = ?
            WHERE id = ?
        ''', (datetime.now(), alert_id))
        conn.commit()
        conn.close()

    def get_sentiment_trend(self, brand_name: str, days: int = 30) -> List[Dict]:
        """获取情感趋势"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        trend = []
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')

            cursor.execute('''
                SELECT sentiment, COUNT(*) as count
                FROM sentiment_items
                WHERE brand_name = ? AND DATE(crawl_time) = ?
                GROUP BY sentiment
            ''', (brand_name, date_str))

            rows = cursor.fetchall()
            daily_stats = {row[0]: row[1] for row in rows}

            trend.append({
                'date': date_str,
                'positive': daily_stats.get('positive', 0),
                'neutral': daily_stats.get('neutral', 0),
                'negative': daily_stats.get('negative', 0),
                'critical': daily_stats.get('critical', 0)
            })

        conn.close()
        return list(reversed(trend))


# 全局服务实例
sentiment_monitor_service = SentimentMonitorService()
