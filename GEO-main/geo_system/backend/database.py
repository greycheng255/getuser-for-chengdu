"""
GEO系统数据库模块
使用SQLite作为默认数据库，支持MySQL配置
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import hashlib
import secrets

# 数据库文件路径
DB_PATH = os.path.join(os.path.dirname(__file__), 'geo_system.db')


class Database:
    """数据库管理类"""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接上下文管理器"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_database(self):
        """初始化数据库表结构"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 用户表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    email TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            
            # 内容生成历史表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS generation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    title TEXT NOT NULL,
                    brand_name TEXT,
                    industry TEXT,
                    platform TEXT,
                    word_count INTEGER,
                    outline TEXT,  -- JSON格式存储
                    prompt TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # 内容分析记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS analysis_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    content TEXT NOT NULL,
                    overall_score REAL,
                    structure_score REAL,
                    citation_score REAL,
                    readability_score REAL,
                    authority_score REAL,
                    geo_compliance TEXT,
                    issues TEXT,  -- JSON格式
                    suggestions TEXT,  -- JSON格式
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # 内容优化记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS optimization_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    original_content TEXT NOT NULL,
                    optimized_content TEXT NOT NULL,
                    optimization_level TEXT,
                    score_before REAL,
                    score_after REAL,
                    improvements TEXT,  -- JSON格式
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # GEO指标记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS metrics_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    record_date DATE NOT NULL,
                    ai_citation_count INTEGER DEFAULT 0,
                    brand_mention_count INTEGER DEFAULT 0,
                    answer_space_coverage REAL DEFAULT 0,
                    source_diversity_score REAL DEFAULT 0,
                    content_quality_score REAL DEFAULT 0,
                    citations_by_platform TEXT,  -- JSON格式
                    mentions_by_source TEXT,  -- JSON格式
                    top_queries TEXT,  -- JSON格式
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, record_date)
                )
            ''')
            
            # ROI计算记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS roi_calculations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    content_investment REAL,
                    technology_investment REAL,
                    personnel_investment REAL,
                    ai_citation_increase REAL,
                    brand_mention_increase REAL,
                    conversion_rate REAL,
                    avg_customer_value REAL,
                    time_period_months INTEGER,
                    total_investment REAL,
                    revenue REAL,
                    net_profit REAL,
                    roi_percentage REAL,
                    payback_period_months REAL,
                    new_customers INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # 网站诊断记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_diagnosis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    overall_score REAL,
                    content_score REAL,
                    structure_score REAL,
                    authority_score REAL,
                    technical_score REAL,
                    issues_count INTEGER DEFAULT 0,
                    diagnosis_result TEXT,  -- JSON格式存储完整结果
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # 系统配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_key TEXT UNIQUE NOT NULL,
                    config_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # AI任务表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ai_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plan_id INTEGER,
                    task_type TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    title TEXT NOT NULL,
                    description TEXT,
                    input_data TEXT,
                    output_data TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')

            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_generation_user ON generation_history(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_metrics_user_date ON metrics_records(user_id, record_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_roi_user ON roi_calculations(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_diagnosis_user ON website_diagnosis(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_diagnosis_domain ON website_diagnosis(domain)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_user ON ai_tasks(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_status ON ai_tasks(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_plan ON ai_tasks(plan_id)')

            conn.commit()
            print("✅ 数据库初始化完成")


class UserRepository:
    """用户数据仓库"""
    
    def __init__(self, db: Database):
        self.db = db
    
    @staticmethod
    def _hash_password(password: str, salt: str = None) -> tuple:
        """密码哈希"""
        if salt is None:
            salt = secrets.token_hex(16)
        pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return pwdhash.hex(), salt
    
    def create_user(self, username: str, password: str, email: str = None) -> Dict:
        """创建用户"""
        password_hash, salt = self._hash_password(password)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO users (username, password_hash, salt, email)
                    VALUES (?, ?, ?, ?)
                ''', (username, password_hash, salt, email))
                
                user_id = cursor.lastrowid
                return {
                    'success': True,
                    'user_id': user_id,
                    'username': username,
                    'message': '用户创建成功'
                }
            except sqlite3.IntegrityError:
                return {
                    'success': False,
                    'message': '用户名已存在'
                }
    
    def verify_user(self, username: str, password: str) -> Dict:
        """验证用户"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, password_hash, salt, is_active FROM users WHERE username = ?
            ''', (username,))
            
            row = cursor.fetchone()
            if not row:
                return {'success': False, 'message': '用户不存在'}
            
            if not row['is_active']:
                return {'success': False, 'message': '用户已被禁用'}
            
            password_hash, _ = self._hash_password(password, row['salt'])
            
            if password_hash != row['password_hash']:
                return {'success': False, 'message': '密码错误'}
            
            # 更新最后登录时间
            cursor.execute('''
                UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?
            ''', (row['id'],))
            
            return {
                'success': True,
                'user_id': row['id'],
                'username': username,
                'message': '登录成功'
            }
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """根据ID获取用户"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, username, email, created_at, last_login, is_active
                FROM users WHERE id = ?
            ''', (user_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """根据用户名获取用户"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, username, email, created_at, last_login, is_active
                FROM users WHERE username = ?
            ''', (username,))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None


class GenerationRepository:
    """内容生成历史仓库"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def save_generation(self, user_id: int, title: str, brand_name: str, 
                       industry: str, platform: str, word_count: int,
                       outline: List[Dict], prompt: str) -> Dict:
        """保存生成历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO generation_history 
                (user_id, title, brand_name, industry, platform, word_count, outline, prompt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, title, brand_name, industry, platform, word_count,
                  json.dumps(outline, ensure_ascii=False), prompt))
            
            return {
                'success': True,
                'id': cursor.lastrowid,
                'message': '生成历史已保存'
            }
    
    def get_user_generations(self, user_id: int, limit: int = 50) -> List[Dict]:
        """获取用户的生成历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM generation_history 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, limit))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                data = dict(row)
                data['outline'] = json.loads(data['outline']) if data['outline'] else []
                results.append(data)
            return results
    
    def get_generation_by_id(self, generation_id: int) -> Optional[Dict]:
        """根据ID获取生成记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM generation_history WHERE id = ?
            ''', (generation_id,))
            
            row = cursor.fetchone()
            if row:
                data = dict(row)
                data['outline'] = json.loads(data['outline']) if data['outline'] else []
                return data
            return None


class AnalysisRepository:
    """内容分析记录仓库"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def save_analysis(self, user_id: int, content: str, analysis_result: Dict) -> Dict:
        """保存分析记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO analysis_records 
                (user_id, content, overall_score, structure_score, citation_score,
                 readability_score, authority_score, geo_compliance, issues, suggestions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, content,
                analysis_result.get('overall_score'),
                analysis_result.get('structure_score'),
                analysis_result.get('citation_score'),
                analysis_result.get('readability_score'),
                analysis_result.get('authority_score'),
                analysis_result.get('geo_compliance'),
                json.dumps(analysis_result.get('issues', []), ensure_ascii=False),
                json.dumps(analysis_result.get('suggestions', []), ensure_ascii=False)
            ))
            
            return {
                'success': True,
                'id': cursor.lastrowid,
                'message': '分析记录已保存'
            }
    
    def get_user_analyses(self, user_id: int, limit: int = 50) -> List[Dict]:
        """获取用户的分析历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, content, overall_score, structure_score, citation_score,
                       readability_score, authority_score, geo_compliance, 
                       issues, suggestions, created_at
                FROM analysis_records 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, limit))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                data = dict(row)
                data['issues'] = json.loads(data['issues']) if data['issues'] else []
                data['suggestions'] = json.loads(data['suggestions']) if data['suggestions'] else []
                results.append(data)
            return results


class OptimizationRepository:
    """内容优化记录仓库"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def save_optimization(self, user_id: int, original_content: str,
                         optimized_content: str, level: str, result: Dict) -> Dict:
        """保存优化记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO optimization_records 
                (user_id, original_content, optimized_content, optimization_level,
                 score_before, score_after, improvements)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, original_content, optimized_content, level,
                result.get('score_before'),
                result.get('score_after'),
                json.dumps(result.get('improvements', []), ensure_ascii=False)
            ))
            
            return {
                'success': True,
                'id': cursor.lastrowid,
                'message': '优化记录已保存'
            }
    
    def get_user_optimizations(self, user_id: int, limit: int = 50) -> List[Dict]:
        """获取用户的优化历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, original_content, optimized_content, optimization_level,
                       score_before, score_after, improvements, created_at
                FROM optimization_records 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, limit))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                data = dict(row)
                data['improvements'] = json.loads(data['improvements']) if data['improvements'] else []
                results.append(data)
            return results


class MetricsRepository:
    """GEO指标记录仓库"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def record_metrics(self, user_id: int, metrics: Dict) -> Dict:
        """记录指标"""
        record_date = metrics.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # 检查是否已存在该日期的记录
            cursor.execute('''
                SELECT id FROM metrics_records 
                WHERE user_id = ? AND record_date = ?
            ''', (user_id, record_date))
            
            existing = cursor.fetchone()
            
            if existing:
                # 更新现有记录
                cursor.execute('''
                    UPDATE metrics_records SET
                        ai_citation_count = ?,
                        brand_mention_count = ?,
                        answer_space_coverage = ?,
                        source_diversity_score = ?,
                        content_quality_score = ?,
                        citations_by_platform = ?,
                        mentions_by_source = ?,
                        top_queries = ?,
                        notes = ?
                    WHERE user_id = ? AND record_date = ?
                ''', (
                    metrics.get('ai_citation_count', 0),
                    metrics.get('brand_mention_count', 0),
                    metrics.get('answer_space_coverage', 0),
                    metrics.get('source_diversity_score', 0),
                    metrics.get('content_quality_score', 0),
                    json.dumps(metrics.get('citations_by_platform', {}), ensure_ascii=False),
                    json.dumps(metrics.get('mentions_by_source', {}), ensure_ascii=False),
                    json.dumps(metrics.get('top_queries', []), ensure_ascii=False),
                    metrics.get('notes', ''),
                    user_id, record_date
                ))
                
                return {
                    'success': True,
                    'message': '指标记录已更新'
                }
            else:
                # 插入新记录
                cursor.execute('''
                    INSERT INTO metrics_records 
                    (user_id, record_date, ai_citation_count, brand_mention_count,
                     answer_space_coverage, source_diversity_score, content_quality_score,
                     citations_by_platform, mentions_by_source, top_queries, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id, record_date,
                    metrics.get('ai_citation_count', 0),
                    metrics.get('brand_mention_count', 0),
                    metrics.get('answer_space_coverage', 0),
                    metrics.get('source_diversity_score', 0),
                    metrics.get('content_quality_score', 0),
                    json.dumps(metrics.get('citations_by_platform', {}), ensure_ascii=False),
                    json.dumps(metrics.get('mentions_by_source', {}), ensure_ascii=False),
                    json.dumps(metrics.get('top_queries', []), ensure_ascii=False),
                    metrics.get('notes', '')
                ))
                
                return {
                    'success': True,
                    'id': cursor.lastrowid,
                    'message': '指标记录已保存'
                }
    
    def get_metrics_history(self, user_id: int, days: int = 30) -> List[Dict]:
        """获取指标历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM metrics_records 
                WHERE user_id = ? 
                AND record_date >= date('now', '-{} days')
                ORDER BY record_date DESC
            '''.format(days), (user_id,))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                data = dict(row)
                data['citations_by_platform'] = json.loads(data['citations_by_platform']) if data['citations_by_platform'] else {}
                data['mentions_by_source'] = json.loads(data['mentions_by_source']) if data['mentions_by_source'] else {}
                data['top_queries'] = json.loads(data['top_queries']) if data['top_queries'] else []
                results.append(data)
            return results
    
    def get_metrics_report(self, user_id: int, report_type: str = 'monthly') -> Dict:
        """生成指标报告"""
        period_map = {
            'daily': '1 days',
            'weekly': '7 days',
            'monthly': '30 days',
            'quarterly': '90 days'
        }
        period = period_map.get(report_type, '30 days')
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # 获取当前周期数据
            cursor.execute('''
                SELECT 
                    AVG(ai_citation_count) as avg_citations,
                    AVG(brand_mention_count) as avg_mentions,
                    AVG(answer_space_coverage) as avg_coverage,
                    AVG(source_diversity_score) as avg_diversity,
                    AVG(content_quality_score) as avg_quality
                FROM metrics_records 
                WHERE user_id = ? 
                AND record_date >= date('now', '-{}')
            '''.format(period), (user_id,))
            
            current = cursor.fetchone()
            
            # 获取上一周期数据用于对比
            cursor.execute('''
                SELECT 
                    AVG(ai_citation_count) as avg_citations,
                    AVG(brand_mention_count) as avg_mentions,
                    AVG(answer_space_coverage) as avg_coverage,
                    AVG(source_diversity_score) as avg_diversity,
                    AVG(content_quality_score) as avg_quality
                FROM metrics_records 
                WHERE user_id = ? 
                AND record_date >= date('now', '-{}') 
                AND record_date < date('now', '-{}')
            '''.format(period, period), (user_id,))
            
            previous = cursor.fetchone()
            
            # 计算变化
            def calc_change(current_val, previous_val):
                if previous_val and previous_val != 0:
                    return current_val - previous_val if current_val else 0
                return 0
            
            report = {
                'basic_metrics': {
                    'ai_citation_rate': {
                        'current': current['avg_citations'] or 0,
                        'change': calc_change(current['avg_citations'], previous['avg_citations'])
                    },
                    'brand_mention_rate': {
                        'current': current['avg_mentions'] or 0,
                        'change': calc_change(current['avg_mentions'], previous['avg_mentions'])
                    },
                    'answer_space_coverage': {
                        'current': current['avg_coverage'] or 0,
                        'change': calc_change(current['avg_coverage'], previous['avg_coverage'])
                    },
                    'visibility_score': {
                        'current': (current['avg_quality'] or 0) * 100,
                        'change': calc_change(current['avg_quality'], previous['avg_quality']) * 100
                    }
                },
                'recommendations': self._generate_recommendations(current)
            }
            
            return report
    
    def _generate_recommendations(self, metrics) -> List[Dict]:
        """生成优化建议"""
        recommendations = []
        
        if metrics['avg_citations'] and metrics['avg_citations'] < 10:
            recommendations.append({
                'priority': 'high',
                'suggestion': 'AI引用次数较低，建议增加高质量内容产出'
            })
        
        if metrics['avg_coverage'] and metrics['avg_coverage'] < 0.3:
            recommendations.append({
                'priority': 'medium',
                'suggestion': '答案空间覆盖率不足，建议扩展内容覆盖范围'
            })
        
        if metrics['avg_quality'] and metrics['avg_quality'] < 0.7:
            recommendations.append({
                'priority': 'medium',
                'suggestion': '内容质量得分偏低，建议优化内容结构和表达方式'
            })
        
        if not recommendations:
            recommendations.append({
                'priority': 'low',
                'suggestion': '整体表现良好，建议持续监测并保持优化'
            })
        
        return recommendations


class ROIRepository:
    """ROI计算记录仓库"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def save_calculation(self, user_id: int, params: Dict, result: Dict) -> Dict:
        """保存ROI计算记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO roi_calculations 
                (user_id, content_investment, technology_investment, personnel_investment,
                 ai_citation_increase, brand_mention_increase, conversion_rate,
                 avg_customer_value, time_period_months, total_investment, revenue,
                 net_profit, roi_percentage, payback_period_months, new_customers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                params.get('content_investment'),
                params.get('technology_investment'),
                params.get('personnel_investment'),
                params.get('ai_citation_increase'),
                params.get('brand_mention_increase'),
                params.get('conversion_rate'),
                params.get('avg_customer_value'),
                params.get('time_period_months'),
                result.get('total_investment'),
                result.get('revenue'),
                result.get('net_profit'),
                result.get('roi_percentage'),
                result.get('payback_period_months'),
                result.get('new_customers')
            ))
            
            return {
                'success': True,
                'id': cursor.lastrowid,
                'message': 'ROI计算记录已保存'
            }
    
    def get_user_calculations(self, user_id: int, limit: int = 20) -> List[Dict]:
        """获取用户的ROI计算历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM roi_calculations 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


# 全局数据库实例
db = Database()
user_repo = UserRepository(db)
generation_repo = GenerationRepository(db)
analysis_repo = AnalysisRepository(db)
optimization_repo = OptimizationRepository(db)
metrics_repo = MetricsRepository(db)
roi_repo = ROIRepository(db)

print("✅ 数据库模块加载完成")
