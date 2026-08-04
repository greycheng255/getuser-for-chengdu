"""
GEO系统数据库模块
支持MySQL数据库
"""

import pymysql
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
from contextlib import contextmanager
import hashlib
import secrets

# MySQL配置
MYSQL_CONFIG = {
    'user': 'geo',
    'password': 'mh6CYre2S8shJYrm',
    'host': '122.51.51.177',
    'port': 15435,
    'database': 'geo',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}


class MySQLDatabase:
    """MySQL数据库管理类"""

    def __init__(self, config: dict = None):
        self.config = config or MYSQL_CONFIG
        self.init_database()

    @contextmanager
    def get_connection(self):
        """获取数据库连接上下文管理器"""
        conn = pymysql.connect(**self.config)
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
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT DEFAULT NULL,
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_user_id (user_id),
                        INDEX idx_domain (domain),
                        INDEX idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                ''')

                # 创建GEO优化方案记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS geo_optimization_plan (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT DEFAULT NULL,
                        domain VARCHAR(255) NOT NULL,
                        brand_name VARCHAR(255) NOT NULL,
                        industry VARCHAR(100) DEFAULT '',
                        location VARCHAR(100) DEFAULT '',
                        keywords TEXT,
                        plan_data TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_user_id (user_id),
                        INDEX idx_domain (domain),
                        INDEX idx_brand_name (brand_name),
                        INDEX idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                ''')

                # 创建关键词生成记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS keyword_generation (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT DEFAULT NULL,
                        brand_name VARCHAR(255) NOT NULL,
                        industry VARCHAR(100) DEFAULT '',
                        location VARCHAR(100) DEFAULT '',
                        generated_keywords TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_user_id (user_id),
                        INDEX idx_brand_name (brand_name),
                        INDEX idx_created_at (created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                ''')

                conn.commit()
                print("✅ MySQL数据库表初始化完成")

        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            raise e


class DiagnosisRepository:
    """网站诊断记录仓库"""

    def __init__(self, db: MySQLDatabase):
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

                diagnosis_id = cursor.lastrowid

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
                data = dict(row)
                data['issues'] = json.loads(data['issues']) if data['issues'] else []
                data['suggestions'] = json.loads(data['suggestions']) if data['suggestions'] else []
                data['diagnosis_result'] = json.loads(data['diagnosis_result']) if data['diagnosis_result'] else {}
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
                data = dict(row)
                data['issues'] = json.loads(data['issues']) if data['issues'] else []
                data['suggestions'] = json.loads(data['suggestions']) if data['suggestions'] else []
                data['diagnosis_result'] = json.loads(data['diagnosis_result']) if data['diagnosis_result'] else {}
                return data
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
                data = dict(row)
                data['issues'] = json.loads(data['issues']) if data['issues'] else []
                data['suggestions'] = json.loads(data['suggestions']) if data['suggestions'] else []
                data['diagnosis_result'] = json.loads(data['diagnosis_result']) if data['diagnosis_result'] else {}
                results.append(data)
            return results


class OptimizationPlanRepository:
    """GEO优化方案记录仓库"""

    def __init__(self, db: MySQLDatabase):
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
                ''', (
                    plan_data.get('user_id'),
                    plan_data.get('domain'),
                    plan_data.get('brand_name'),
                    plan_data.get('industry', ''),
                    plan_data.get('location', ''),
                    json.dumps(plan_data.get('keywords', []), ensure_ascii=False),
                    json.dumps(plan_data.get('plan_data', {}), ensure_ascii=False)
                ))

                plan_id = cursor.lastrowid

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
                SELECT id, domain, brand_name, industry, location, keywords, plan_data, created_at
                FROM geo_optimization_plan
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ''', (user_id, limit))

            rows = cursor.fetchall()
            results = []
            for row in rows:
                data = dict(row)
                data['keywords'] = json.loads(data['keywords']) if data['keywords'] else []
                data['plan_data'] = json.loads(data['plan_data']) if data['plan_data'] else {}
                results.append(data)
            return results

    def get_plan_by_id(self, plan_id: int) -> Optional[Dict]:
        """根据ID获取优化方案"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, domain, brand_name, industry, location, keywords, plan_data, created_at
                FROM geo_optimization_plan
                WHERE id = %s
            ''', (plan_id,))

            row = cursor.fetchone()
            if row:
                data = dict(row)
                data['keywords'] = json.loads(data['keywords']) if data['keywords'] else []
                data['plan_data'] = json.loads(data['plan_data']) if data['plan_data'] else {}
                return data
            return None


class KeywordRepository:
    """关键词生成记录仓库"""

    def __init__(self, db: MySQLDatabase):
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
                ''', (
                    keyword_data.get('user_id'),
                    keyword_data.get('brand_name'),
                    keyword_data.get('industry', ''),
                    keyword_data.get('location', ''),
                    json.dumps(keyword_data.get('generated_keywords', []), ensure_ascii=False)
                ))

                keyword_id = cursor.lastrowid

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


# 全局数据库实例
db = MySQLDatabase()
diagnosis_repo = DiagnosisRepository(db)
optimization_plan_repo = OptimizationPlanRepository(db)
keyword_repo = KeywordRepository(db)

print("✅ 数据库模块加载完成")
