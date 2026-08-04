"""
数据库优化工具
提供查询优化、索引管理和连接池功能
"""

import sqlite3
import functools
import time
import logging
from typing import List, Dict, Any, Optional, Callable
from contextlib import contextmanager
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionPool:
    """SQLite连接池"""
    
    def __init__(self, db_path: str, max_connections: int = 10):
        self.db_path = db_path
        self.max_connections = max_connections
        self._pool = []
        self._lock = threading.Lock()
        self._local = threading.local()
        
    def _create_connection(self) -> sqlite3.Connection:
        """创建新连接"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # 启用外键
        conn.execute("PRAGMA foreign_keys = ON")
        # 启用WAL模式提高并发性能
        conn.execute("PRAGMA journal_mode = WAL")
        # 优化同步模式
        conn.execute("PRAGMA synchronous = NORMAL")
        # 增加缓存大小
        conn.execute("PRAGMA cache_size = -64000")  # 64MB
        return conn
    
    @contextmanager
    def get_connection(self):
        """获取连接上下文管理器"""
        conn = None
        try:
            # 检查线程本地存储
            if hasattr(self._local, 'connection') and self._local.connection:
                conn = self._local.connection
            else:
                with self._lock:
                    if self._pool:
                        conn = self._pool.pop()
                    else:
                        conn = self._create_connection()
                self._local.connection = conn
            
            yield conn
            
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn and not hasattr(self._local, 'connection'):
                with self._lock:
                    if len(self._pool) < self.max_connections:
                        self._pool.append(conn)
                    else:
                        conn.close()


class QueryOptimizer:
    """查询优化器"""
    
    # 推荐的索引配置
    RECOMMENDED_INDEXES = {
        'ai_tasks': [
            'CREATE INDEX IF NOT EXISTS idx_ai_tasks_user_id ON ai_tasks(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_ai_tasks_status ON ai_tasks(status)',
            'CREATE INDEX IF NOT EXISTS idx_ai_tasks_user_status ON ai_tasks(user_id, status)',
            'CREATE INDEX IF NOT EXISTS idx_ai_tasks_created_at ON ai_tasks(created_at)',
            'CREATE INDEX IF NOT EXISTS idx_ai_tasks_task_type ON ai_tasks(task_type)',
        ],
        'platform_accounts': [
            'CREATE INDEX IF NOT EXISTS idx_platform_accounts_user_id ON platform_accounts(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_platform_accounts_platform ON platform_accounts(platform)',
            'CREATE INDEX IF NOT EXISTS idx_platform_accounts_user_platform ON platform_accounts(user_id, platform)',
            'CREATE INDEX IF NOT EXISTS idx_platform_accounts_status ON platform_accounts(status)',
        ],
        'content_calendar': [
            'CREATE INDEX IF NOT EXISTS idx_calendar_user_id ON content_calendar(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_calendar_date ON content_calendar(scheduled_date)',
            'CREATE INDEX IF NOT EXISTS idx_calendar_status ON content_calendar(status)',
        ],
        'analytics_data': [
            'CREATE INDEX IF NOT EXISTS idx_analytics_user_id ON analytics_data(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_analytics_date ON analytics_data(date)',
            'CREATE INDEX IF NOT EXISTS idx_analytics_platform ON analytics_data(platform)',
        ],
        'monitoring_alerts': [
            'CREATE INDEX IF NOT EXISTS idx_alerts_user_id ON monitoring_alerts(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_alerts_status ON monitoring_alerts(status)',
            'CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON monitoring_alerts(created_at)',
        ],
        'sentiment_data': [
            'CREATE INDEX IF NOT EXISTS idx_sentiment_user_id ON sentiment_data(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_sentiment_date ON sentiment_data(date)',
            'CREATE INDEX IF NOT EXISTS idx_sentiment_keyword ON sentiment_data(keyword)',
        ],
        'competitor_data': [
            'CREATE INDEX IF NOT EXISTS idx_competitor_user_id ON competitor_data(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_competitor_name ON competitor_data(competitor_name)',
        ],
        'keywords': [
            'CREATE INDEX IF NOT EXISTS idx_keywords_user_id ON keywords(user_id)',
            'CREATE INDEX IF NOT EXISTS idx_keywords_keyword ON keywords(keyword)',
            'CREATE INDEX IF NOT EXISTS idx_keywords_volume ON keywords(search_volume)',
        ],
    }
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection_pool = ConnectionPool(db_path)
    
    def create_indexes(self):
        """创建所有推荐索引"""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            for table, indexes in self.RECOMMENDED_INDEXES.items():
                for index_sql in indexes:
                    try:
                        cursor.execute(index_sql)
                        logger.info(f"Created index: {index_sql}")
                    except sqlite3.Error as e:
                        logger.warning(f"Failed to create index: {e}")
            
            conn.commit()
            logger.info("All indexes created successfully")
    
    def analyze_table(self, table_name: str):
        """分析表统计信息"""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"ANALYZE {table_name}")
            conn.commit()
            logger.info(f"Analyzed table: {table_name}")
    
    def vacuum_database(self):
        """清理数据库碎片"""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("VACUUM")
            conn.commit()
            logger.info("Database vacuumed successfully")
    
    def get_table_stats(self) -> List[Dict]:
        """获取表统计信息"""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    name,
                    (SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name=name) as index_count
                FROM sqlite_master 
                WHERE type='table'
            """)
            
            tables = cursor.fetchall()
            stats = []
            
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) as count FROM {table['name']}")
                row_count = cursor.fetchone()['count']
                
                stats.append({
                    'table_name': table['name'],
                    'row_count': row_count,
                    'index_count': table['index_count']
                })
            
            return stats
    
    def get_slow_queries(self, min_time: float = 0.1) -> List[Dict]:
        """获取慢查询（需要配合查询日志）"""
        # 这里可以实现查询日志分析
        pass


def query_timer(func: Callable) -> Callable:
    """查询计时装饰器"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        elapsed_time = time.time() - start_time
        
        if elapsed_time > 0.1:  # 记录慢查询
            logger.warning(f"Slow query detected: {func.__name__} took {elapsed_time:.3f}s")
        
        return result
    return wrapper


class OptimizedQuery:
    """优化查询构建器"""
    
    def __init__(self, connection_pool: ConnectionPool):
        self.connection_pool = connection_pool
    
    @query_timer
    def fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict]:
        """执行查询并返回单行结果"""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
    
    @query_timer
    def fetch_all(self, query: str, params: tuple = ()) -> List[Dict]:
        """执行查询并返回所有结果"""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    @query_timer
    def fetch_paginated(
        self, 
        query: str, 
        params: tuple = (),
        page: int = 1, 
        page_size: int = 20
    ) -> Dict[str, Any]:
        """分页查询"""
        offset = (page - 1) * page_size
        
        # 添加LIMIT和OFFSET
        paginated_query = f"{query} LIMIT ? OFFSET ?"
        params_with_pagination = params + (page_size, offset)
        
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # 获取总数
            count_query = f"SELECT COUNT(*) as total FROM ({query})"
            cursor.execute(count_query, params)
            total = cursor.fetchone()['total']
            
            # 获取分页数据
            cursor.execute(paginated_query, params_with_pagination)
            rows = cursor.fetchall()
            
            return {
                'data': [dict(row) for row in rows],
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total': total,
                    'total_pages': (total + page_size - 1) // page_size
                }
            }
    
    @query_timer
    def execute(self, query: str, params: tuple = ()) -> int:
        """执行更新/插入/删除操作"""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount
    
    @query_timer
    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """批量执行操作"""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
            return cursor.rowcount
    
    @query_timer
    def insert_or_update(
        self, 
        table: str, 
        data: Dict[str, Any], 
        unique_keys: List[str]
    ) -> int:
        """插入或更新（UPSERT）"""
        columns = list(data.keys())
        values = list(data.values())
        
        # 构建INSERT语句
        placeholders = ', '.join(['?' for _ in columns])
        columns_str = ', '.join(columns)
        
        # 构建UPDATE部分
        update_columns = [c for c in columns if c not in unique_keys]
        if update_columns:
            update_str = ', '.join([f"{c}=excluded.{c}" for c in update_columns])
            query = f"""
                INSERT INTO {table} ({columns_str}) VALUES ({placeholders})
                ON CONFLICT({', '.join(unique_keys)}) DO UPDATE SET {update_str}
            """
        else:
            query = f"""
                INSERT INTO {table} ({columns_str}) VALUES ({placeholders})
                ON CONFLICT({', '.join(unique_keys)}) DO NOTHING
            """
        
        with self.connection_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, values)
            conn.commit()
            return cursor.lastrowid or cursor.rowcount


# 全局优化器实例
_db_optimizer = None

def get_db_optimizer(db_path: str = "geo_optimization.db") -> QueryOptimizer:
    """获取数据库优化器实例"""
    global _db_optimizer
    if _db_optimizer is None:
        _db_optimizer = QueryOptimizer(db_path)
    return _db_optimizer


def optimize_database(db_path: str = "geo_optimization.db"):
    """优化数据库"""
    optimizer = get_db_optimizer(db_path)
    
    logger.info("Starting database optimization...")
    
    # 创建索引
    optimizer.create_indexes()
    
    # 分析表
    stats = optimizer.get_table_stats()
    for stat in stats:
        if stat['row_count'] > 1000:  # 只分析大表
            optimizer.analyze_table(stat['table_name'])
    
    # 清理碎片
    optimizer.vacuum_database()
    
    logger.info("Database optimization completed")
    
    return stats


if __name__ == "__main__":
    # 测试优化
    stats = optimize_database()
    print("\nTable Statistics:")
    for stat in stats:
        print(f"  {stat['table_name']}: {stat['row_count']} rows, {stat['index_count']} indexes")
