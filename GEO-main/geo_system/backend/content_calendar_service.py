"""
内容日历服务
管理内容排期、日历视图、内容计划等功能
"""

import sqlite3
import json
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
import uuid


class ContentStatus(Enum):
    """内容状态"""
    DRAFT = "draft"                # 草稿
    PLANNED = "planned"            # 已计划
    IN_PROGRESS = "in_progress"    # 进行中
    REVIEW = "review"              # 审核中
    SCHEDULED = "scheduled"        # 已排期
    PUBLISHED = "published"        # 已发布
    CANCELLED = "cancelled"        # 已取消


class ContentPriority(Enum):
    """内容优先级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ContentType(Enum):
    """内容类型"""
    ARTICLE = "article"
    VIDEO = "video"
    FAQ = "faq"
    GUIDE = "guide"
    CASE_STUDY = "case_study"
    NEWS = "news"
    COMPARISON = "comparison"
    REVIEW = "review"


@dataclass
class ContentItem:
    """内容项"""
    id: str
    title: str
    content_type: ContentType
    description: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    target_platforms: List[str] = field(default_factory=list)
    status: ContentStatus = ContentStatus.DRAFT
    priority: ContentPriority = ContentPriority.MEDIUM
    assigned_to: Optional[str] = None
    planned_date: Optional[datetime] = None
    publish_date: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    geo_optimized: bool = False
    notes: Optional[str] = None


@dataclass
class CalendarEvent:
    """日历事件"""
    id: str
    title: str
    date: datetime
    type: str
    content_id: Optional[str] = None
    description: Optional[str] = None


@dataclass
class ContentPlan:
    """内容计划"""
    id: str
    name: str
    description: Optional[str] = None
    start_date: datetime = field(default_factory=datetime.now)
    end_date: Optional[datetime] = None
    items: List[str] = field(default_factory=list)
    status: str = "active"


class ContentCalendarService:
    """内容日历服务"""

    def __init__(self, db_path: str = "content_calendar.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 内容项表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS content_items (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content_type TEXT NOT NULL,
                description TEXT,
                keywords TEXT,
                target_platforms TEXT,
                status TEXT NOT NULL,
                priority TEXT NOT NULL,
                assigned_to TEXT,
                planned_date TEXT,
                publish_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                geo_optimized INTEGER DEFAULT 0,
                notes TEXT
            )
        ''')

        # 日历事件表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS calendar_events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                content_id TEXT,
                description TEXT
            )
        ''')

        # 内容计划表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS content_plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                start_date TEXT NOT NULL,
                end_date TEXT,
                items TEXT,
                status TEXT NOT NULL
            )
        ''')

        conn.commit()
        conn.close()

    def create_content_item(self, title: str, content_type: ContentType,
                           description: str = None, keywords: List[str] = None,
                           target_platforms: List[str] = None,
                           priority: ContentPriority = ContentPriority.MEDIUM,
                           assigned_to: str = None,
                           planned_date: datetime = None,
                           geo_optimized: bool = False) -> ContentItem:
        """创建内容项"""
        item = ContentItem(
            id=str(uuid.uuid4()),
            title=title,
            content_type=content_type,
            description=description,
            keywords=keywords or [],
            target_platforms=target_platforms or [],
            priority=priority,
            assigned_to=assigned_to,
            planned_date=planned_date,
            geo_optimized=geo_optimized
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO content_items
            (id, title, content_type, description, keywords, target_platforms,
             status, priority, assigned_to, planned_date, publish_date,
             created_at, updated_at, geo_optimized, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            item.id, item.title, item.content_type.value, item.description,
            json.dumps(item.keywords), json.dumps(item.target_platforms),
            item.status.value, item.priority.value, item.assigned_to,
            item.planned_date.isoformat() if item.planned_date else None,
            item.publish_date.isoformat() if item.publish_date else None,
            item.created_at.isoformat(), item.updated_at.isoformat(),
            1 if item.geo_optimized else 0, item.notes
        ))

        conn.commit()
        conn.close()

        return item

    def get_content_items(self, status: ContentStatus = None,
                         content_type: ContentType = None,
                         priority: ContentPriority = None,
                         start_date: datetime = None,
                         end_date: datetime = None) -> List[ContentItem]:
        """获取内容项列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM content_items WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status.value)
        if content_type:
            query += " AND content_type = ?"
            params.append(content_type.value)
        if priority:
            query += " AND priority = ?"
            params.append(priority.value)
        if start_date:
            query += " AND planned_date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND planned_date <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY planned_date ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_item(row) for row in rows]

    def _row_to_item(self, row) -> ContentItem:
        """将数据库行转换为ContentItem"""
        return ContentItem(
            id=row[0],
            title=row[1],
            content_type=ContentType(row[2]),
            description=row[3],
            keywords=json.loads(row[4]) if row[4] else [],
            target_platforms=json.loads(row[5]) if row[5] else [],
            status=ContentStatus(row[6]),
            priority=ContentPriority(row[7]),
            assigned_to=row[8],
            planned_date=datetime.fromisoformat(row[9]) if row[9] else None,
            publish_date=datetime.fromisoformat(row[10]) if row[10] else None,
            created_at=datetime.fromisoformat(row[11]),
            updated_at=datetime.fromisoformat(row[12]),
            geo_optimized=bool(row[13]),
            notes=row[14]
        )

    def update_content_status(self, content_id: str, status: ContentStatus,
                             notes: str = None) -> Optional[ContentItem]:
        """更新内容状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 检查内容项是否存在
        cursor.execute("SELECT * FROM content_items WHERE id = ?", (content_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        # 更新状态
        updates = ["status = ?", "updated_at = ?"]
        params = [status.value, datetime.now().isoformat()]

        if notes:
            updates.append("notes = ?")
            params.append(notes)

        if status == ContentStatus.PUBLISHED:
            updates.append("publish_date = ?")
            params.append(datetime.now().isoformat())

        params.append(content_id)

        cursor.execute(f'''
            UPDATE content_items
            SET {', '.join(updates)}
            WHERE id = ?
        ''', params)

        conn.commit()
        conn.close()

        return self.get_content_item(content_id)

    def get_content_item(self, content_id: str) -> Optional[ContentItem]:
        """获取单个内容项"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM content_items WHERE id = ?", (content_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_item(row)
        return None

    def get_calendar_view(self, year: int, month: int) -> Dict:
        """获取日历视图"""
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)

        items = self.get_content_items(start_date=start_date, end_date=end_date)

        # 按日期分组
        calendar_days = {}
        for item in items:
            if item.planned_date:
                day = item.planned_date.day
                if day not in calendar_days:
                    calendar_days[day] = []
                calendar_days[day].append({
                    'id': item.id,
                    'title': item.title,
                    'type': item.content_type.value,
                    'status': item.status.value,
                    'priority': item.priority.value
                })

        return {
            'year': year,
            'month': month,
            'days': calendar_days
        }

    def get_weekly_plan(self, start_date: datetime = None) -> Dict:
        """获取周计划"""
        if not start_date:
            start_date = datetime.now()

        # 获取本周开始（周一）
        weekday = start_date.weekday()
        week_start = start_date - timedelta(days=weekday)
        week_end = week_start + timedelta(days=7)

        items = self.get_content_items(start_date=week_start, end_date=week_end)

        # 按天分组
        week_days = {}
        for i in range(7):
            day = week_start + timedelta(days=i)
            week_days[day.strftime('%Y-%m-%d')] = []

        for item in items:
            if item.planned_date:
                day_key = item.planned_date.strftime('%Y-%m-%d')
                if day_key in week_days:
                    week_days[day_key].append({
                        'id': item.id,
                        'title': item.title,
                        'type': item.content_type.value,
                        'status': item.status.value,
                        'priority': item.priority.value
                    })

        return {
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'days': week_days
        }

    def get_content_stats(self) -> Dict:
        """获取内容统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 总数量
        cursor.execute("SELECT COUNT(*) FROM content_items")
        total = cursor.fetchone()[0]

        # 按状态统计
        cursor.execute('''
            SELECT status, COUNT(*) FROM content_items GROUP BY status
        ''')
        status_stats = {row[0]: row[1] for row in cursor.fetchall()}

        # 按类型统计
        cursor.execute('''
            SELECT content_type, COUNT(*) FROM content_items GROUP BY content_type
        ''')
        type_stats = {row[0]: row[1] for row in cursor.fetchall()}

        # 本月计划
        month_start = datetime.now().replace(day=1)
        cursor.execute('''
            SELECT COUNT(*) FROM content_items WHERE planned_date >= ?
        ''', (month_start.isoformat(),))
        month_planned = cursor.fetchone()[0]

        # 本月已完成
        cursor.execute('''
            SELECT COUNT(*) FROM content_items
            WHERE status = ? AND publish_date >= ?
        ''', (ContentStatus.PUBLISHED.value, month_start.isoformat()))
        month_completed = cursor.fetchone()[0]

        conn.close()

        return {
            'total_items': total,
            'status_distribution': status_stats,
            'type_distribution': type_stats,
            'month_planned': month_planned,
            'month_completed': month_completed,
            'completion_rate': round(month_completed / month_planned * 100, 2) if month_planned > 0 else 0
        }

    def auto_schedule_content(self, content_items: List[Dict],
                             start_date: datetime = None,
                             frequency: str = 'weekly') -> List[ContentItem]:
        """自动排期内容"""
        if not start_date:
            start_date = datetime.now()

        scheduled_items = []

        for i, item_data in enumerate(content_items):
            if frequency == 'daily':
                planned_date = start_date + timedelta(days=i)
            elif frequency == 'weekly':
                planned_date = start_date + timedelta(weeks=i)
            elif frequency == 'biweekly':
                planned_date = start_date + timedelta(weeks=i*2)
            else:
                planned_date = start_date + timedelta(days=i*3)

            item = self.create_content_item(
                title=item_data['title'],
                content_type=ContentType(item_data.get('type', 'article')),
                description=item_data.get('description'),
                keywords=item_data.get('keywords', []),
                target_platforms=item_data.get('platforms', []),
                priority=ContentPriority(item_data.get('priority', 'medium')),
                planned_date=planned_date,
                geo_optimized=item_data.get('geo_optimized', False)
            )
            scheduled_items.append(item)

        return scheduled_items

    def get_upcoming_content(self, days: int = 7) -> List[ContentItem]:
        """获取即将到期的内容"""
        start_date = datetime.now()
        end_date = start_date + timedelta(days=days)

        return self.get_content_items(
            start_date=start_date,
            end_date=end_date,
            status=ContentStatus.PLANNED
        )


# 全局服务实例
content_calendar_service = ContentCalendarService()
