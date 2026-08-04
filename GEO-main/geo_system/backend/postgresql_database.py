"""
GEO系统数据库模块
支持PostgreSQL数据库
"""

import psycopg2
import psycopg2.pool
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
from contextlib import contextmanager
import hashlib
import secrets

# PostgreSQL配置
PG_CONFIG = {
    'user': os.environ.get('DB_USER', 'geo'),
    'password': os.environ.get('DB_PASSWORD', 'mh6CYre2S8shJYrm'),
    'host': os.environ.get('DB_HOST', '122.51.51.177'),
    'port': int(os.environ.get('DB_PORT', '15435')),
    'database': os.environ.get('DB_NAME', 'geo')
}

# 全局连接池（延迟初始化）
_connection_pool = None


def get_connection_pool():
    """获取全局连接池（懒加载）"""
    global _connection_pool
    if _connection_pool is None:
        try:
            _connection_pool = psycopg2.pool.SimpleConnectionPool(
                minconn=2,
                maxconn=10,
                **PG_CONFIG
            )
            print("✅ PostgreSQL连接池初始化成功")
        except Exception as e:
            print(f"❌ PostgreSQL连接池初始化失败: {e}")
    return _connection_pool


class PostgreSQLDatabase:
    """PostgreSQL数据库管理类"""

    def __init__(self, config: dict = None):
        self.config = config or PG_CONFIG
        self.init_database()

    @contextmanager
    def get_connection(self):
        """获取数据库连接上下文管理器（使用连接池）"""
        pool = get_connection_pool()
        if pool:
            conn = pool.getconn()
            try:
                yield conn
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                pool.putconn(conn)
        else:
            # 回退到直接连接（连接池失败时）
            conn = psycopg2.connect(**self.config)
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
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 创建网站诊断记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS website_diagnosis (
                        id SERIAL PRIMARY KEY,
                        user_id INT,
                        domain VARCHAR(255) NOT NULL,
                        url VARCHAR(500) NOT NULL,
                        brand_name VARCHAR(255) DEFAULT '',
                        overall_score DECIMAL(5,2) DEFAULT 0,
                        content_score DECIMAL(5,2) DEFAULT 0,
                        structure_score DECIMAL(5,2) DEFAULT 0,
                        authority_score DECIMAL(5,2) DEFAULT 0,
                        technical_score DECIMAL(5,2) DEFAULT 0,
                        issues_count INT DEFAULT 0,
                        issues TEXT,
                        suggestions TEXT,
                        diagnosis_result TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 创建索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_diagnosis_user_id ON website_diagnosis(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_diagnosis_domain ON website_diagnosis(domain)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_diagnosis_created_at ON website_diagnosis(created_at)')

                # 创建GEO优化方案记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS geo_optimization_plan (
                        id SERIAL PRIMARY KEY,
                        user_id INT,
                        domain VARCHAR(255) NOT NULL,
                        brand_name VARCHAR(255) NOT NULL,
                        industry VARCHAR(100) DEFAULT '',
                        location VARCHAR(100) DEFAULT '',
                        keywords TEXT,
                        plan_data TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 创建索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_plan_user_id ON geo_optimization_plan(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_plan_domain ON geo_optimization_plan(domain)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_plan_brand_name ON geo_optimization_plan(brand_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_plan_created_at ON geo_optimization_plan(created_at)')

                # 创建关键词生成记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS keyword_generation (
                        id SERIAL PRIMARY KEY,
                        user_id INT,
                        brand_name VARCHAR(255) NOT NULL,
                        industry VARCHAR(100) DEFAULT '',
                        location VARCHAR(100) DEFAULT '',
                        generated_keywords TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 创建索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_keyword_user_id ON keyword_generation(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_keyword_brand_name ON keyword_generation(brand_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_keyword_created_at ON keyword_generation(created_at)')

                # 创建用户表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(255) UNIQUE NOT NULL,
                        password VARCHAR(255) NOT NULL,
                        email VARCHAR(255) DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_login TIMESTAMP
                    )
                ''')

                # 创建内容生成历史表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS generation_history (
                        id SERIAL PRIMARY KEY,
                        user_id INT DEFAULT 1,
                        title VARCHAR(500) DEFAULT '',
                        brand_name VARCHAR(255) DEFAULT '',
                        platform VARCHAR(100) DEFAULT 'chatgpt',
                        outline_count INT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 创建索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_generation_user_id ON generation_history(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_generation_created_at ON generation_history(created_at)')

                # 创建AI任务表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS ai_tasks (
                        id SERIAL PRIMARY KEY,
                        user_id INT NOT NULL,
                        plan_id INT,
                        task_type VARCHAR(50) NOT NULL,
                        status VARCHAR(20) DEFAULT 'pending',
                        title VARCHAR(255) NOT NULL,
                        description TEXT,
                        input_data TEXT,
                        output_data TEXT,
                        result_content TEXT,
                        keywords TEXT,
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                ''')

                # 创建AI任务表索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_user_id ON ai_tasks(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_status ON ai_tasks(status)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_plan_id ON ai_tasks(plan_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_created_at ON ai_tasks(created_at)')

                # 添加可能缺失的列（兼容旧表结构）
                try:
                    cursor.execute('ALTER TABLE ai_tasks ADD COLUMN IF NOT EXISTS result_content TEXT')
                    cursor.execute('ALTER TABLE ai_tasks ADD COLUMN IF NOT EXISTS keywords TEXT')
                except Exception as e:
                    print(f"添加列时出错（可能已存在）: {e}")

                conn.commit()
                print("✅ PostgreSQL数据库表初始化完成")

        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            raise e


class DiagnosisRepository:
    """网站诊断记录仓库"""

    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def save_diagnosis(self, diagnosis_data: Dict) -> Dict:
        """保存诊断记录"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT INTO website_diagnosis
                    (user_id, domain, url, brand_name, overall_score, content_score,
                     structure_score, authority_score, technical_score, issues_count,
                     issues, suggestions, diagnosis_result)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    diagnosis_data.get('user_id'),
                    diagnosis_data.get('domain'),
                    diagnosis_data.get('url'),
                    diagnosis_data.get('brand_name', ''),
                    diagnosis_data.get('overall_score', 0),
                    diagnosis_data.get('content_score', 0),
                    diagnosis_data.get('structure_score', 0),
                    diagnosis_data.get('authority_score', 0),
                    diagnosis_data.get('technical_score', 0),
                    diagnosis_data.get('issues_count', 0),
                    json.dumps(diagnosis_data.get('issues', []), ensure_ascii=False),
                    json.dumps(diagnosis_data.get('suggestions', []), ensure_ascii=False),
                    json.dumps(diagnosis_data.get('diagnosis_result', {}), ensure_ascii=False)
                ))

                diagnosis_id = cursor.fetchone()[0]

                return {
                    'success': True,
                    'id': diagnosis_id,
                    'message': '诊断记录已保存'
                }

        except Exception as e:
            return {
                'success': False,
                'message': f'保存失败: {str(e)}'
            }

    def get_user_diagnoses(self, user_id: int, limit: int = 50) -> List[Dict]:
        """获取用户的诊断历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, domain, url, brand_name, overall_score, content_score,
                       structure_score, authority_score, technical_score, issues_count,
                       issues, suggestions, diagnosis_result, created_at
                FROM website_diagnosis
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ''', (user_id, limit))

            rows = cursor.fetchall()
            results = []
            for row in rows:
                data = {
                    'id': row[0],
                    'domain': row[1],
                    'url': row[2],
                    'brand_name': row[3],
                    'overall_score': float(row[4]) if row[4] else 0,
                    'content_score': float(row[5]) if row[5] else 0,
                    'structure_score': float(row[6]) if row[6] else 0,
                    'authority_score': float(row[7]) if row[7] else 0,
                    'technical_score': float(row[8]) if row[8] else 0,
                    'issues_count': row[9],
                    'issues': json.loads(row[10]) if row[10] else [],
                    'suggestions': json.loads(row[11]) if row[11] else [],
                    'diagnosis_result': json.loads(row[12]) if row[12] else {},
                    'created_at': row[13].isoformat() if row[13] else None
                }
                results.append(data)
            return results

    def get_diagnosis_by_id(self, diagnosis_id: int) -> Optional[Dict]:
        """根据ID获取诊断记录"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, domain, url, brand_name, overall_score, content_score,
                       structure_score, authority_score, technical_score, issues_count,
                       issues, suggestions, diagnosis_result, created_at
                FROM website_diagnosis
                WHERE id = %s
            ''', (diagnosis_id,))

            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'domain': row[1],
                    'url': row[2],
                    'brand_name': row[3],
                    'overall_score': float(row[4]) if row[4] else 0,
                    'content_score': float(row[5]) if row[5] else 0,
                    'structure_score': float(row[6]) if row[6] else 0,
                    'authority_score': float(row[7]) if row[7] else 0,
                    'technical_score': float(row[8]) if row[8] else 0,
                    'issues_count': row[9],
                    'issues': json.loads(row[10]) if row[10] else [],
                    'suggestions': json.loads(row[11]) if row[11] else [],
                    'diagnosis_result': json.loads(row[12]) if row[12] else {},
                    'created_at': row[13].isoformat() if row[13] else None
                }
            return None

    def get_diagnosis_by_domain(self, domain: str, limit: int = 10) -> List[Dict]:
        """根据域名获取诊断历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, domain, url, brand_name, overall_score, content_score,
                       structure_score, authority_score, technical_score, issues_count,
                       issues, suggestions, diagnosis_result, created_at
                FROM website_diagnosis
                WHERE domain = %s
                ORDER BY created_at DESC
                LIMIT %s
            ''', (domain, limit))

            rows = cursor.fetchall()
            results = []
            for row in rows:
                data = {
                    'id': row[0],
                    'domain': row[1],
                    'url': row[2],
                    'brand_name': row[3],
                    'overall_score': float(row[4]) if row[4] else 0,
                    'content_score': float(row[5]) if row[5] else 0,
                    'structure_score': float(row[6]) if row[6] else 0,
                    'authority_score': float(row[7]) if row[7] else 0,
                    'technical_score': float(row[8]) if row[8] else 0,
                    'issues_count': row[9],
                    'issues': json.loads(row[10]) if row[10] else [],
                    'suggestions': json.loads(row[11]) if row[11] else [],
                    'diagnosis_result': json.loads(row[12]) if row[12] else {},
                    'created_at': row[13].isoformat() if row[13] else None
                }
                results.append(data)
            return results

    def delete_diagnosis(self, diagnosis_id: int, user_id: int) -> Dict:
        """删除诊断记录"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # 验证记录属于该用户
                cursor.execute('SELECT user_id FROM website_diagnosis WHERE id = %s', (diagnosis_id,))
                row = cursor.fetchone()
                if not row:
                    return {'success': False, 'message': '记录不存在'}
                # user_id为NULL时允许任何已登录用户删除
                if row[0] is not None and row[0] != user_id:
                    return {'success': False, 'message': '无权删除此记录'}
                
                cursor.execute('DELETE FROM website_diagnosis WHERE id = %s', (diagnosis_id,))
                return {'success': True, 'message': '删除成功'}
        except Exception as e:
            return {'success': False, 'message': f'删除失败: {str(e)}'}


class OptimizationPlanRepository:
    """GEO优化方案记录仓库"""

    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def save_plan(self, plan_data: Dict) -> Dict:
        """保存优化方案记录"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT INTO geo_optimization_plan
                    (user_id, domain, brand_name, industry, location, keywords, plan_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    plan_data.get('user_id'),
                    plan_data.get('domain'),
                    plan_data.get('brand_name'),
                    plan_data.get('industry', ''),
                    plan_data.get('location', ''),
                    json.dumps(plan_data.get('keywords', []), ensure_ascii=False),
                    json.dumps(plan_data.get('plan_data', {}), ensure_ascii=False)
                ))

                plan_id = cursor.fetchone()[0]

                return {
                    'success': True,
                    'id': plan_id,
                    'message': '优化方案已保存'
                }

        except Exception as e:
            return {
                'success': False,
                'message': f'保存失败: {str(e)}'
            }

    def get_user_plans(self, user_id: int, limit: int = 50) -> List[Dict]:
        """获取用户的优化方案历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, user_id, domain, brand_name, industry, location, keywords, plan_data, created_at
                FROM geo_optimization_plan
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ''', (user_id, limit))

            rows = cursor.fetchall()
            results = []
            for row in rows:
                data = {
                    'id': row[0],
                    'user_id': row[1],
                    'domain': row[2],
                    'brand_name': row[3],
                    'industry': row[4],
                    'location': row[5],
                    'keywords': json.loads(row[6]) if row[6] else [],
                    'plan_data': json.loads(row[7]) if row[7] else {},
                    'created_at': row[8].isoformat() if row[8] else None
                }
                results.append(data)
            return results

    def get_plan_by_id(self, plan_id: int) -> Optional[Dict]:
        """根据ID获取优化方案"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, user_id, domain, brand_name, industry, location, keywords, plan_data, created_at
                FROM geo_optimization_plan
                WHERE id = %s
            ''', (plan_id,))

            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'user_id': row[1],
                    'domain': row[2],
                    'brand_name': row[3],
                    'industry': row[4],
                    'location': row[5],
                    'keywords': json.loads(row[6]) if row[6] else [],
                    'plan_data': json.loads(row[7]) if row[7] else {},
                    'created_at': row[8].isoformat() if row[8] else None
                }
            return None

    def delete_plan(self, plan_id: int, user_id: int) -> Dict:
        """删除优化方案"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # 验证记录属于该用户
                cursor.execute('SELECT user_id FROM geo_optimization_plan WHERE id = %s', (plan_id,))
                row = cursor.fetchone()
                if not row:
                    return {'success': False, 'message': '记录不存在'}
                # user_id为NULL时允许任何已登录用户删除
                if row[0] is not None and row[0] != user_id:
                    return {'success': False, 'message': '无权删除此记录'}
                
                cursor.execute('DELETE FROM geo_optimization_plan WHERE id = %s', (plan_id,))
                return {'success': True, 'message': '删除成功'}
        except Exception as e:
            return {'success': False, 'message': f'删除失败: {str(e)}'}


class KeywordRepository:
    """关键词生成记录仓库"""

    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def save_keywords(self, keyword_data: Dict) -> Dict:
        """保存关键词生成记录"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT INTO keyword_generation
                    (user_id, brand_name, industry, location, generated_keywords)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    keyword_data.get('user_id'),
                    keyword_data.get('brand_name'),
                    keyword_data.get('industry', ''),
                    keyword_data.get('location', ''),
                    json.dumps(keyword_data.get('generated_keywords', []), ensure_ascii=False)
                ))

                keyword_id = cursor.fetchone()[0]

                return {
                    'success': True,
                    'id': keyword_id,
                    'message': '关键词已保存'
                }

        except Exception as e:
            return {
                'success': False,
                'message': f'保存失败: {str(e)}'
            }


class UserRepository:
    """用户仓库"""

    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def create_user(self, username: str, password: str, email: str = '') -> Dict:
        """创建用户"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO users (username, password, email)
                    VALUES (%s, %s, %s)
                    RETURNING id, created_at
                ''', (username, password, email))
                row = cursor.fetchone()
                return {
                    'success': True,
                    'id': row[0],
                    'created_at': row[1].isoformat() if row[1] else None,
                    'message': '用户创建成功'
                }
        except Exception as e:
            return {
                'success': False,
                'message': f'创建用户失败: {str(e)}'
            }

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """根据用户名获取用户"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, username, password, email, created_at, last_login
                FROM users
                WHERE username = %s
            ''', (username,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'username': row[1],
                    'password': row[2],
                    'email': row[3],
                    'created_at': row[4].isoformat() if row[4] else None,
                    'last_login': row[5].isoformat() if row[5] else None
                }
            return None

    def update_last_login(self, username: str) -> bool:
        """更新最后登录时间"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users
                    SET last_login = CURRENT_TIMESTAMP
                    WHERE username = %s
                ''', (username,))
                return True
        except Exception as e:
            print(f"更新登录时间失败: {e}")
            return False

    def get_user_count(self) -> int:
        """获取用户数量"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users')
            return cursor.fetchone()[0]


class GenerationHistoryRepository:
    """内容生成历史仓库"""

    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def save_generation(self, generation_data: Dict) -> Dict:
        """保存生成记录"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO generation_history
                    (user_id, title, brand_name, platform, outline_count)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    generation_data.get('user_id', 1),
                    generation_data.get('title', ''),
                    generation_data.get('brand_name', ''),
                    generation_data.get('platform', 'chatgpt'),
                    generation_data.get('outline_count', 0)
                ))
                generation_id = cursor.fetchone()[0]
                return {
                    'success': True,
                    'id': generation_id,
                    'message': '生成记录已保存'
                }
        except Exception as e:
            return {
                'success': False,
                'message': f'保存失败: {str(e)}'
            }

    def get_user_generations(self, user_id: int, limit: int = 100) -> List[Dict]:
        """获取用户的生成历史"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, title, brand_name, platform, outline_count, created_at
                FROM generation_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ''', (user_id, limit))
            rows = cursor.fetchall()
            results = []
            for row in rows:
                results.append({
                    'id': row[0],
                    'title': row[1],
                    'brand_name': row[2],
                    'platform': row[3],
                    'outline_count': row[4],
                    'created_at': row[5].isoformat() if row[5] else None
                })
            return results

    def get_generation_count(self) -> int:
        """获取生成记录总数"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM generation_history')
            return cursor.fetchone()[0]

    def get_today_generation_count(self) -> int:
        """获取今日生成记录数"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM generation_history
                WHERE created_at >= CURRENT_DATE
            ''')
            return cursor.fetchone()[0]

    def save_ai_task(self, task_data: Dict) -> Dict:
        """保存AI任务"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO ai_tasks
                    (user_id, plan_id, task_type, status, title, description, input_data, output_data, keywords)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    task_data.get('user_id'),
                    task_data.get('plan_id'),
                    task_data.get('task_type'),
                    task_data.get('status', 'pending'),
                    task_data.get('title', ''),
                    task_data.get('description', ''),
                    json.dumps(task_data.get('input_data', {}), ensure_ascii=False),
                    json.dumps(task_data.get('output_data', {}), ensure_ascii=False),
                    json.dumps(task_data.get('keywords', []), ensure_ascii=False)
                ))
                task_id = cursor.fetchone()[0]
                return {
                    'success': True,
                    'id': task_id,
                    'message': '任务已保存'
                }
        except Exception as e:
            return {
                'success': False,
                'message': f'保存任务失败: {str(e)}'
            }

    def get_user_ai_tasks(self, user_id: int = None, status: str = None, task_type: str = None, limit: int = 50) -> List[Dict]:
        """获取AI任务列表，user_id为None时返回所有任务

        LEFT JOIN geo_optimization_plan 带出 brand_name 和 domain，
        让前端能区分每个任务属于哪个项目/品牌。
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT t.id, t.user_id, t.plan_id, t.task_type, t.status, t.title, t.description,
                       t.input_data, t.output_data, t.result_content, t.keywords,
                       t.created_at, t.updated_at, t.completed_at, t.error_message,
                       p.brand_name, p.domain
                FROM ai_tasks t
                LEFT JOIN geo_optimization_plan p ON t.plan_id = p.id
                WHERE 1=1
            '''
            params = []

            if user_id:
                query += ' AND t.user_id = %s'
                params.append(user_id)

            if status:
                query += ' AND t.status = %s'
                params.append(status)
            if task_type:
                query += ' AND t.task_type = %s'
                params.append(task_type)

            query += ' ORDER BY t.created_at DESC LIMIT %s'
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            results = []
            for row in rows:
                results.append({
                    'id': row[0],
                    'user_id': row[1],
                    'plan_id': row[2],
                    'task_type': row[3],
                    'status': row[4],
                    'title': row[5],
                    'description': row[6],
                    'input_data': json.loads(row[7]) if row[7] else {},
                    'output_data': json.loads(row[8]) if row[8] else None,
                    'result_content': row[9],
                    'keywords': json.loads(row[10]) if row[10] else [],
                    'created_at': row[11].isoformat() if row[11] else None,
                    'updated_at': row[12].isoformat() if row[12] else None,
                    'completed_at': row[13].isoformat() if row[13] else None,
                    'error_message': row[14],
                    'brand_name': row[15] or '',
                    'domain': row[16] or ''
                })
            return results

    def get_ai_task_by_id(self, task_id: int) -> Optional[Dict]:
        """根据ID获取AI任务（带 brand_name/domain）"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT t.id, t.user_id, t.plan_id, t.task_type, t.status, t.title, t.description,
                       t.input_data, t.output_data, t.result_content, t.keywords,
                       t.created_at, t.updated_at, t.completed_at, t.error_message,
                       p.brand_name, p.domain
                FROM ai_tasks t
                LEFT JOIN geo_optimization_plan p ON t.plan_id = p.id
                WHERE t.id = %s
            ''', (task_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'user_id': row[1],
                    'plan_id': row[2],
                    'task_type': row[3],
                    'status': row[4],
                    'title': row[5],
                    'description': row[6],
                    'input_data': json.loads(row[7]) if row[7] else {},
                    'output_data': json.loads(row[8]) if row[8] else None,
                    'result_content': row[9],
                    'keywords': json.loads(row[10]) if row[10] else [],
                    'created_at': row[11].isoformat() if row[11] else None,
                    'updated_at': row[12].isoformat() if row[12] else None,
                    'completed_at': row[13].isoformat() if row[13] else None,
                    'error_message': row[14],
                    'brand_name': row[15] or '',
                    'domain': row[16] or ''
                }
            return None

    def update_task_status(self, task_id: int, status: str, error_message: str = None) -> Dict:
        """更新任务状态"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                if error_message:
                    cursor.execute('''
                        UPDATE ai_tasks
                        SET status = %s, error_message = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    ''', (status, error_message, task_id))
                else:
                    cursor.execute('''
                        UPDATE ai_tasks
                        SET status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    ''', (status, task_id))
                return {'success': True, 'message': '状态更新成功'}
        except Exception as e:
            return {'success': False, 'message': f'更新失败: {str(e)}'}

    def update_task_output(self, task_id: int, output_data: Dict) -> Dict:
        """更新任务输出"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE ai_tasks
                    SET output_data = %s, status = %s, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (
                    json.dumps(output_data.get('output_data'), ensure_ascii=False),
                    output_data.get('status'),
                    task_id
                ))
                return {'success': True, 'message': '输出更新成功'}
        except Exception as e:
            return {'success': False, 'message': f'更新失败: {str(e)}'}

    def delete_ai_task(self, task_id: int, user_id: int) -> Dict:
        """删除AI任务"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # 验证任务属于该用户
                cursor.execute('SELECT user_id FROM ai_tasks WHERE id = %s', (task_id,))
                row = cursor.fetchone()
                if not row:
                    return {'success': False, 'message': '任务不存在'}
                # user_id为NULL时允许任何已登录用户删除
                if row[0] is not None and row[0] != user_id:
                    return {'success': False, 'message': '无权删除此任务'}
                
                cursor.execute('DELETE FROM ai_tasks WHERE id = %s', (task_id,))
                return {'success': True, 'message': '删除成功'}
        except Exception as e:
            return {'success': False, 'message': f'删除失败: {str(e)}'}


# 全局数据库实例
db = PostgreSQLDatabase()
diagnosis_repo = DiagnosisRepository(db)
optimization_plan_repo = OptimizationPlanRepository(db)
keyword_repo = KeywordRepository(db)
user_repo = UserRepository(db)
generation_repo = GenerationHistoryRepository(db)

print("✅ PostgreSQL数据库模块加载完成")
