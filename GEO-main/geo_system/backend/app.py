"""
GEO系统后端API服务
使用Flask构建，提供完整的RESTful API
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity, verify_jwt_in_request
from datetime import datetime, timedelta
import json
import os
import sys
import logging
from functools import wraps
from io import BytesIO
from typing import Dict

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.content_generator import GEOArticleGenerator
from core.content_optimizer import GEOContentOptimizer
from utils.content_analyzer import ContentAnalyzer
from modules.data.metrics_tracker import GEOMetricsTracker, GEOMetrics
from modules.data.roi_calculator import ROICalculator
from modules.source.authority_builder import AuthorityBuilder
from modules.source.platform_distributor import PlatformDistributor
from modules.source.schema_optimizer import SchemaOptimizer
from backend.modules.website_analyzer import GEODiagnostician
from postgresql_database import db, diagnosis_repo, optimization_plan_repo, keyword_repo, user_repo, generation_repo
from ai_task_manager import ai_task_manager, AITaskManager, TaskStatus, TaskType
from ai_service import ai_service
from publish_service import publish_service, PublishTask, PublishStatus, PlatformType, quick_publish
from monitoring_service import monitoring_service, SearchEngine, AIPlatform
from db_optimizer import get_db_optimizer, optimize_database, query_timer
from platform_account_service import PlatformAccountService, PlatformLoginHelper
from xiaohongshu_qr_login import qr_login_manager
from xhs_auth_manager import init_xhs_auth_manager, xhs_auth_manager as _xhs_auth_mgr_placeholder
from cookie_refresher import init_cookie_refresher, cookie_refresher as _cookie_refresher_placeholder
from ai_citation_scheduler import ai_citation_scheduler
from workflow_engine import workflow_engine, WORKFLOW_STAGES
from export_service import export_service
from error_handler import (
    register_error_handlers, log_request, validate_json, validate_params,
    APIError, ValidationError, AuthenticationError, NotFoundError,
    error_logger, performance_monitor
)

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 'geo-system-secret-key-change-in-production'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# 更宽松的CORS配置 - 只使用Flask-CORS，移除手动添加的CORS头
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept"],
        "supports_credentials": False
    }
})

jwt = JWTManager(app)

# 注册错误处理器
register_error_handlers(app)

# PostgreSQL 数据库实例别名（部分模块使用 postgres_db 命名）
postgres_db = db

# 小红书认证管理器延迟初始化（需要等待 platform_account_service 就绪，见文件末尾）
_xhs_auth_initialized = False

def _init_xhs_auth():
    """延迟初始化小红书认证管理器 + Cookie 自动刷新器"""
    global _xhs_auth_initialized
    if _xhs_auth_initialized:
        return
    try:
        init_xhs_auth_manager(postgres_db, platform_account_service)
        init_cookie_refresher()
        # 注入 auth_manager 到 cookie_refresher
        from xhs_auth_manager import xhs_auth_manager as _xhs_mgr
        from cookie_refresher import cookie_refresher as _cr
        if _xhs_mgr and _cr:
            _cr.set_auth_manager(_xhs_mgr)
        logger.info("[App] 小红书认证管理器和 Cookie 刷新器已初始化")
        _xhs_auth_initialized = True

        # 启动 AI 引用率定时检测调度器
        try:
            ai_citation_scheduler.set_monitoring_service(monitoring_service)
            ai_citation_scheduler.start()
            logger.info("[App] AI 引用率定时检测调度器已启动")
        except Exception as e:
            logger.error(f"[App] 启动 AI 引用率调度器失败: {e}")

        # 初始化工作流引擎服务账号 token（在 Flask app 上下文中）
        try:
            with app.app_context():
                token = workflow_engine._ensure_service_account()
                if token:
                    logger.info("[App] 工作流引擎服务账号已就绪")
                else:
                    logger.warning("[App] 工作流引擎服务账号初始化失败")
        except Exception as e:
            logger.error(f"[App] 工作流引擎服务账号初始化失败: {e}")
    except Exception as e:
        logger.error(f"[App] 初始化小红书认证管理器失败: {e}")

# 初始化组件
content_generator = GEOArticleGenerator()
content_optimizer = GEOContentOptimizer()
content_analyzer = ContentAnalyzer()
metrics_tracker = GEOMetricsTracker()
roi_calculator = ROICalculator()
authority_builder = AuthorityBuilder()
platform_distributor = PlatformDistributor()
schema_optimizer = SchemaOptimizer()

# 用户数据库已迁移到PostgreSQL

# 简单的内存缓存
cache = {}

def cached(timeout=300):
    """简单的缓存装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            cache_key = f.__name__ + str(args) + str(kwargs)
            if cache_key in cache:
                result, timestamp = cache[cache_key]
                if datetime.now().timestamp() - timestamp < timeout:
                    return result
            
            result = f(*args, **kwargs)
            cache[cache_key] = (result, datetime.now().timestamp())
            return result
        return decorated_function
    return decorator


# ==================== 认证相关 ====================

@app.route('/api/auth/register', methods=['POST'])
def register():
    """用户注册"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400
        
        if len(password) < 6:
            return jsonify({'success': False, 'message': '密码长度至少6位'}), 400
        
        existing_user = user_repo.get_user_by_username(username)
        if existing_user:
            return jsonify({'success': False, 'message': '用户名已存在'}), 400
        
        result = user_repo.create_user(username, password)
        if result['success']:
            return jsonify({'success': True, 'message': '注册成功'})
        else:
            return jsonify({'success': False, 'message': result['message']}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'注册失败: {str(e)}'}), 500


@app.route('/api/auth/login', methods=['POST'])
def login():
    """用户登录"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400
        
        user = user_repo.get_user_by_username(username)
        if not user or user['password'] != password:
            return jsonify({'success': False, 'message': '用户名或密码错误'}), 401
        
        # 更新最后登录时间
        user_repo.update_last_login(username)
        
        access_token = create_access_token(identity=username)
        
        return jsonify({
            'success': True,
            'access_token': access_token,
            'username': username,
            'message': '登录成功'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'登录失败: {str(e)}'}), 500


@app.route('/api/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    """用户登出（前端删除token即可）"""
    return jsonify({'success': True, 'message': '登出成功'})


@app.route('/api/auth/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """获取用户信息"""
    try:
        current_user = get_jwt_identity()
        user_info = user_repo.get_user_by_username(current_user)
        
        return jsonify({
            'success': True,
            'data': {
                'username': current_user,
                'created_at': user_info.get('created_at') if user_info else None,
                'last_login': user_info.get('last_login') if user_info else None
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== 内容生成 ====================

@app.route('/api/content/generate', methods=['POST', 'OPTIONS'])
def generate_content():
    """生成GEO优化内容"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        
        title = data.get('title')
        brand_info = data.get('brand_info', {})
        target_platform = data.get('target_platform', 'chatgpt')
        word_count = data.get('word_count', 3000)
        
        if not title:
            return jsonify({
                'success': False,
                'message': '标题不能为空'
            }), 400
        
        if not brand_info or not brand_info.get('name'):
            return jsonify({
                'success': False,
                'message': '品牌信息不能为空'
            }), 400
        
        # 验证平台
        valid_platforms = ['chatgpt', 'perplexity', 'google_ai', 'kimi', 'doubao']
        if target_platform not in valid_platforms:
            target_platform = 'chatgpt'
        
        result = content_generator.generate(
            title=title,
            brand_info=brand_info,
            target_platform=target_platform,
            word_count=word_count
        )
        
        # 保存生成历史到数据库
        try:
            generation_repo.save_generation({
                'user_id': 1,
                'title': result.get('title', ''),
                'brand_name': brand_info.get('name', ''),
                'platform': target_platform,
                'outline_count': len(result.get('outline', []))
            })
        except Exception as e:
            print(f"保存生成历史失败: {e}")
        
        return jsonify({
            'success': True,
            'data': result,
            'message': '内容生成成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'生成失败: {str(e)}'
        }), 500


@app.route('/api/content/analyze', methods=['POST', 'OPTIONS'])
def analyze_content():
    """分析内容质量"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        content = data.get('content', '')
        
        if not content or len(content.strip()) < 50:
            return jsonify({
                'success': False,
                'message': '内容不能为空且至少50个字符'
            }), 400
        
        result = content_analyzer.analyze(content)
        
        return jsonify({
            'success': True,
            'data': {
                'overall_score': result.overall_score,
                'structure_score': result.structure_score,
                'citation_score': result.citation_score,
                'readability_score': result.readability_score,
                'authority_score': result.authority_score,
                'geo_compliance': result.geo_compliance,
                'issues': result.issues,
                'suggestions': result.suggestions
            },
            'message': '分析完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'分析失败: {str(e)}'
        }), 500


@app.route('/api/content/optimize', methods=['POST', 'OPTIONS'])
def optimize_content():
    """优化内容"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        content = data.get('content', '')
        optimization_level = data.get('optimization_level', 'medium')
        
        if not content or len(content.strip()) < 50:
            return jsonify({
                'success': False,
                'message': '内容不能为空且至少50个字符'
            }), 400
        
        # 验证优化级别
        valid_levels = ['light', 'medium', 'heavy']
        if optimization_level not in valid_levels:
            optimization_level = 'medium'
        
        result = content_optimizer.optimize(content, optimization_level)

        return jsonify({
            'success': True,
            'data': {
                'optimized_content': result.optimized_text,
                'optimized_text': result.optimized_text,
                'score_before': result.score_before,
                'score_after': result.score_after,
                'improvements': result.changes,
                'changes': result.changes,
                'suggestions': result.suggestions
            },
            'message': '优化完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'优化失败: {str(e)}'
        }), 500


# ==================== 批量处理 ====================

@app.route('/api/content/batch-generate', methods=['POST', 'OPTIONS'])
@jwt_required()
def batch_generate():
    """批量生成内容 - 使用真实AI服务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        data = request.get_json()
        topics = data.get('topics', [])
        brand_info = data.get('brand_info', {})
        keywords = data.get('keywords', [])
        
        if not topics or len(topics) > 10:
            return jsonify({
                'success': False,
                'message': '主题列表不能为空且最多10个'
            }), 400
        
        results = []
        for i, topic in enumerate(topics):
            try:
                # 使用真实AI服务生成文章
                ai_result = ai_service.generate_geo_article(
                    title=topic.get('title', ''),
                    brand_info=brand_info,
                    keywords=keywords or topic.get('keywords', []),
                    target_platform=topic.get('platform', 'chatgpt'),
                    word_count=topic.get('word_count', 2500)
                )
                
                if ai_result['success']:
                    # 分析质量
                    content_text = ai_result['content'][:2000]  # 分析前2000字符
                    analysis = content_analyzer.analyze(content_text)
                    
                    results.append({
                        'title': topic.get('title'),
                        'content': ai_result['content'],
                        'model': ai_result.get('model', 'unknown'),
                        'usage': ai_result.get('usage', {}),
                        'quality_score': analysis.overall_score,
                        'success': True
                    })
                else:
                    results.append({
                        'title': topic.get('title'),
                        'error': ai_result.get('error', 'AI生成失败'),
                        'success': False
                    })
            except Exception as e:
                results.append({
                    'title': topic.get('title'),
                    'error': str(e),
                    'success': False
                })
        
        successful = [r for r in results if r.get('success')]
        
        return jsonify({
            'success': True,
            'data': {
                'total': len(results),
                'successful': len(successful),
                'failed': len(results) - len(successful),
                'results': results,
                'average_score': sum(r['quality_score'] for r in successful) / len(successful) if successful else 0
            },
            'message': f'成功生成 {len(successful)}/{len(results)} 篇文章'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'批量生成失败: {str(e)}'
        }), 500


# ==================== 数据监测 ====================

@app.route('/api/metrics/record', methods=['POST', 'OPTIONS'])
def record_metrics():
    """记录指标"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        
        metrics = GEOMetrics(
            date=datetime.now().isoformat(),
            ai_citation_count=data.get('ai_citation_count', 0),
            brand_mention_count=data.get('brand_mention_count', 0),
            answer_space_coverage=data.get('answer_space_coverage', 0),
            source_diversity_score=data.get('source_diversity_score', 0),
            content_quality_score=data.get('content_quality_score', 0),
            citations_by_platform=data.get('citations_by_platform', {}),
            mentions_by_source=data.get('mentions_by_source', {}),
            top_queries=data.get('top_queries', [])
        )
        
        metrics_tracker.record_metrics(metrics)
        
        return jsonify({
            'success': True,
            'message': '指标记录成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'记录失败: {str(e)}'
        }), 500


@app.route('/api/metrics/report', methods=['GET'])
@cached(timeout=60)
def get_metrics_report():
    """获取指标报告"""
    try:
        report_type = request.args.get('type', 'monthly')
        
        valid_types = ['daily', 'weekly', 'monthly', 'quarterly']
        if report_type not in valid_types:
            report_type = 'monthly'
        
        report = metrics_tracker.generate_report(report_type)
        
        return jsonify({
            'success': True,
            'data': report,
            'message': '报告生成成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'报告生成失败: {str(e)}'
        }), 500


@app.route('/api/metrics/history', methods=['GET'])
def get_metrics_history():
    """获取历史指标"""
    try:
        days = request.args.get('days', 30, type=int)
        days = min(days, 365)  # 最多365天
        
        # 获取最近N天的数据
        history = metrics_tracker.metrics_history[-days:] if len(metrics_tracker.metrics_history) > days else metrics_tracker.metrics_history
        
        return jsonify({
            'success': True,
            'data': [
                {
                    'date': m.date,
                    'ai_citation_count': m.ai_citation_count,
                    'brand_mention_count': m.brand_mention_count,
                    'answer_space_coverage': m.answer_space_coverage,
                    'content_quality_score': m.content_quality_score
                }
                for m in history
            ],
            'message': '历史数据获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取历史数据失败: {str(e)}'
        }), 500


# ==================== ROI计算 ====================

@app.route('/api/roi/calculate', methods=['POST', 'OPTIONS'])
def calculate_roi():
    """计算ROI"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        
        params = {
            'content_investment': max(0, data.get('content_investment', 50000)),
            'technology_investment': max(0, data.get('technology_investment', 30000)),
            'personnel_investment': max(0, data.get('personnel_investment', 80000)),
            'ai_citation_increase': max(0, min(100, data.get('ai_citation_increase', 40))),
            'brand_mention_increase': max(0, min(100, data.get('brand_mention_increase', 35))),
            'conversion_rate': max(0, min(100, data.get('conversion_rate', 2.5))),
            'avg_customer_value': max(0, data.get('avg_customer_value', 5000)),
            'time_period_months': max(1, data.get('time_period_months', 12))
        }
        
        result = roi_calculator.calculate_basic_roi(params)
        
        return jsonify({
            'success': True,
            'data': result,
            'message': 'ROI计算完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'计算失败: {str(e)}'
        }), 500


@app.route('/api/roi/scenarios', methods=['POST', 'OPTIONS'])
def calculate_roi_scenarios():
    """计算多场景ROI"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        base_params = data.get('base_params', {})
        
        scenarios = [
            {'name': '保守策略', 'investment_multiplier': 0.6, 'citation_multiplier': 0.6},
            {'name': '平衡策略', 'investment_multiplier': 1.0, 'citation_multiplier': 1.0},
            {'name': '激进策略', 'investment_multiplier': 1.5, 'citation_multiplier': 1.5}
        ]
        
        results = []
        for scenario in scenarios:
            params = {
                'content_investment': max(0, base_params.get('content_investment', 50000) * scenario['investment_multiplier']),
                'technology_investment': max(0, base_params.get('technology_investment', 30000) * scenario['investment_multiplier']),
                'personnel_investment': max(0, base_params.get('personnel_investment', 80000) * scenario['investment_multiplier']),
                'ai_citation_increase': max(0, min(100, base_params.get('ai_citation_increase', 40) * scenario['citation_multiplier'])),
                'brand_mention_increase': max(0, min(100, base_params.get('brand_mention_increase', 35) * scenario['citation_multiplier'])),
                'conversion_rate': max(0, min(100, base_params.get('conversion_rate', 2.5))),
                'avg_customer_value': max(0, base_params.get('avg_customer_value', 5000)),
                'time_period_months': max(1, base_params.get('time_period_months', 12))
            }
            
            result = roi_calculator.calculate_basic_roi(params)
            results.append({
                'scenario': scenario['name'],
                'result': result
            })
        
        return jsonify({
            'success': True,
            'data': results,
            'message': '多场景ROI计算完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'计算失败: {str(e)}'
        }), 500


# ==================== 信源建设 ====================

@app.route('/api/authority/pyramid', methods=['GET'])
@cached(timeout=3600)
def get_authority_pyramid():
    """获取信源金字塔"""
    try:
        pyramid = authority_builder.get_authority_pyramid()
        
        return jsonify({
            'success': True,
            'data': pyramid,
            'message': '获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }), 500


@app.route('/api/authority/official-site-plan', methods=['POST', 'OPTIONS'])
def get_official_site_plan():
    """获取官网建设方案"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        brand_info = data.get('brand_info', {})
        
        if not brand_info.get('name'):
            return jsonify({
                'success': False,
                'message': '品牌名称不能为空'
            }), 400
        
        plan = authority_builder.build_official_site_authority(brand_info)
        
        return jsonify({
            'success': True,
            'data': plan,
            'message': '方案生成成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'生成失败: {str(e)}'
        }), 500


@app.route('/api/authority/schema/optimize', methods=['POST', 'OPTIONS'])
def optimize_schema():
    """优化Schema.org结构化数据"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        org_data = data.get('organization', {})
        
        if not org_data.get('name'):
            return jsonify({
                'success': False,
                'message': '组织名称不能为空'
            }), 400
        
        optimized = schema_optimizer.optimize_organization(org_data)
        validation = schema_optimizer.validate_schema(optimized)
        
        return jsonify({
            'success': True,
            'data': {
                'optimized_schema': optimized,
                'validation': validation
            },
            'message': 'Schema优化完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'优化失败: {str(e)}'
        }), 500


# ==================== 平台分发 ====================

@app.route('/api/platform/requirements', methods=['GET'])
@cached(timeout=3600)
def get_platform_requirements():
    """获取平台要求"""
    try:
        platform = request.args.get('platform', 'chatgpt')
        
        valid_platforms = ['chatgpt', 'perplexity', 'google_ai', 'kimi', 'doubao']
        if platform not in valid_platforms:
            platform = 'chatgpt'
        
        requirements = platform_distributor.get_platform_requirements(platform)
        
        return jsonify({
            'success': True,
            'data': requirements,
            'message': '获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }), 500


@app.route('/api/platform/adapt', methods=['POST', 'OPTIONS'])
def adapt_content_for_platform():
    """为平台适配内容"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        content = data.get('content', {})
        platform = data.get('platform', 'chatgpt')
        
        if not content:
            return jsonify({
                'success': False,
                'message': '内容不能为空'
            }), 400
        
        adapted = platform_distributor.adapt_content(content, platform)
        
        return jsonify({
            'success': True,
            'data': adapted,
            'message': '内容适配完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'适配失败: {str(e)}'
        }), 500


@app.route('/api/platforms', methods=['GET'])
def get_platforms():
    """获取所有支持的平台列表"""
    try:
        platforms = [
            {'id': 'chatgpt', 'name': 'ChatGPT', 'icon': '🤖', 'description': 'OpenAI的对话AI'},
            {'id': 'perplexity', 'name': 'Perplexity', 'icon': '🔍', 'description': 'AI搜索引擎'},
            {'id': 'google_ai', 'name': 'Google AI', 'icon': '🌐', 'description': 'Google AI搜索'},
            {'id': 'kimi', 'name': 'Kimi', 'icon': '🌙', 'description': '月之暗面AI助手'},
            {'id': 'doubao', 'name': '豆包', 'icon': '📦', 'description': '字节跳动AI助手'}
        ]
        
        return jsonify({
            'success': True,
            'data': platforms,
            'message': '获取成功'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }), 500


# ==================== 知识库 ====================

@app.route('/api/knowledge/entities', methods=['GET'])
@cached(timeout=3600)
def get_knowledge_entities():
    """获取知识库实体"""
    try:
        from core.rag_engine import RAGEngine
        engine = RAGEngine()
        
        entities = list(engine.knowledge_base['entities'].keys())
        
        return jsonify({
            'success': True,
            'data': entities,
            'message': '获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }), 500


# ==================== 模板管理 ====================

@app.route('/api/templates', methods=['GET'])
@cached(timeout=3600)
def get_templates():
    """获取内容模板"""
    try:
        templates = [
            {
                'id': 'how_to',
                'name': 'How-to教程',
                'description': '步骤式教学指南',
                'structure': ['问题定义', '解决方案概述', '详细步骤', '常见错误', '进阶技巧']
            },
            {
                'id': 'comparison',
                'name': '对比评测',
                'description': '产品或方案对比',
                'structure': ['评测背景', '对比维度', '详细对比', '选择建议', '结论']
            },
            {
                'id': 'case_study',
                'name': '案例研究',
                'description': '成功案例分析',
                'structure': ['背景介绍', '面临挑战', '解决方案', '实施过程', '成果展示', '经验总结']
            },
            {
                'id': 'industry_report',
                'name': '行业报告',
                'description': '深度行业分析',
                'structure': ['行业概览', '市场数据', '趋势分析', '竞争格局', '未来展望']
            }
        ]
        
        return jsonify({
            'success': True,
            'data': templates,
            'message': '获取成功'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }), 500


# ==================== 辅助函数 ====================

# 生成历史已迁移到PostgreSQL数据库


# ==================== 系统状态 ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
        'services': {
            'content_generator': 'ok',
            'content_optimizer': 'ok',
            'content_analyzer': 'ok',
            'metrics_tracker': 'ok',
            'roi_calculator': 'ok',
            'authority_builder': 'ok',
            'platform_distributor': 'ok',
            'schema_optimizer': 'ok'
        }
    })


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取系统统计"""
    try:
        # 从数据库获取统计数据
        generation_count = generation_repo.get_generation_count()
        today_count = generation_repo.get_today_generation_count()
        user_count = user_repo.get_user_count()
        
        return jsonify({
            'success': True,
            'data': {
                'total_generations': generation_count,
                'today_generations': today_count,
                'total_metrics_records': len(metrics_tracker.metrics_history),
                'registered_users': user_count,
                'system_status': 'running',
                'uptime': 'running'
            },
            'message': '统计信息获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取统计信息失败: {str(e)}'
        }), 500


# ==================== 数据库优化 ====================

@app.route('/api/admin/db/optimize', methods=['POST', 'OPTIONS'])
@jwt_required()
def optimize_db():
    """优化数据库"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        
        # 检查是否是管理员（简单检查）
        if user.get('role') != 'admin':
            return jsonify({
                'success': False,
                'message': '权限不足'
            }), 403
        
        # 执行优化
        stats = optimize_database()
        
        return jsonify({
            'success': True,
            'data': {
                'tables': stats,
                'message': '数据库优化完成'
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/admin/db/stats', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_db_stats():
    """获取数据库统计"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        optimizer = get_db_optimizer()
        stats = optimizer.get_table_stats()
        
        return jsonify({
            'success': True,
            'data': stats
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/admin/cache/clear', methods=['POST', 'OPTIONS'])
@jwt_required()
def clear_cache():
    """清除系统缓存"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        # 清除内存缓存
        cache.clear()
        
        return jsonify({
            'success': True,
            'message': '缓存已清除'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/admin/performance', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_performance_stats():
    """获取性能统计"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        stats = performance_monitor.get_stats()
        error_stats = error_logger.get_error_stats()
        
        return jsonify({
            'success': True,
            'data': {
                'performance': stats,
                'errors': error_stats
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 网站诊断 ====================

@app.route('/api/website/diagnose', methods=['POST', 'OPTIONS'])
def diagnose_website():
    """诊断网站GEO状态"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据不能为空'
            }), 400
        
        url = data.get('url', '')
        brand_name = data.get('brand_name', '')
        
        # 尝试获取当前用户ID
        current_user_id = None
        try:
            verify_jwt_in_request(optional=True)
            current_user = get_jwt_identity()
            if current_user:
                user = user_repo.get_user_by_username(current_user)
                if user:
                    current_user_id = user['id']
        except:
            pass
        
        if not url:
            return jsonify({
                'success': False,
                'message': '网址不能为空'
            }), 400
        
        diagnostician = GEODiagnostician()
        result = diagnostician.diagnose(url)
        
        # 检查是否返回错误信息
        if result.get('success') is False:
            return jsonify(result), 400
        
        if not result:
            return jsonify({
                'success': False,
                'message': '无法访问该网站或网站分析失败'
            }), 500
        
        # 保存到数据库
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc or url
            
            diagnosis_record = {
                'user_id': current_user_id,
                'domain': domain,
                'url': url,
                'brand_name': brand_name,
                'overall_score': result.get('overall_score', 0),
                'content_score': result.get('content_score', 0),
                'structure_score': result.get('structure_score', 0),
                'authority_score': result.get('authority_score', 0),
                'technical_score': result.get('technical_score', 0),
                'issues_count': len(result.get('issues', [])),
                'issues': result.get('issues', []),
                'suggestions': result.get('suggestions', []),
                'diagnosis_result': result
            }
            
            save_result = diagnosis_repo.save_diagnosis(diagnosis_record)
            if save_result['success']:
                result['id'] = save_result['id']
                print(f"✅ 诊断记录已保存到数据库, ID: {save_result['id']}")
        except Exception as db_err:
            print(f"⚠️ 保存诊断记录失败: {db_err}")
        
        return jsonify({
            'success': True,
            'data': result,
            'message': '诊断完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'诊断失败: {str(e)}'
        }), 500


@app.route('/api/website/compare', methods=['POST', 'OPTIONS'])
def compare_websites():
    """对比多个网站"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        urls = data.get('urls', [])
        
        if not urls or len(urls) < 2:
            return jsonify({
                'success': False,
                'message': '至少需要对比2个网站'
            }), 400
        
        if len(urls) > 5:
            return jsonify({
                'success': False,
                'message': '最多支持5个网站对比'
            }), 400
        
        diagnostician = GEODiagnostician()
        results = []
        
        for url in urls:
            try:
                result = diagnostician.diagnose(url)
                if result:
                    results.append(result)
            except Exception as e:
                print(f"诊断失败 {url}: {str(e)}")
        
        if len(results) < 2:
            return jsonify({
                'success': False,
                'message': '至少需要成功诊断2个网站'
            }), 500
        
        # 按综合评分排序
        results.sort(key=lambda x: x['scores']['overall'], reverse=True)
        
        # 计算最佳实践
        best_practices = []
        aspects = ['content', 'structure', 'authority', 'technical']
        aspect_names = {'content': '内容质量', 'structure': '结构优化', 'authority': '权威性', 'technical': '技术性能'}
        
        for aspect in aspects:
            leader = max(results, key=lambda x: x['scores'][aspect])
            best_practices.append({
                'aspect': aspect_names[aspect],
                'leader': leader['domain'],
                'score': leader['scores'][aspect],
                'tip': get_best_practice_tip(aspect, leader['scores'][aspect])
            })
        
        # 差距分析
        scores = [r['scores']['overall'] for r in results]
        avg_score = round(sum(scores) / len(scores), 1)
        score_range = f"{min(scores)}-{max(scores)}"
        improvement_potential = round((max(scores) - avg_score) / max(scores) * 100, 1)
        
        return jsonify({
            'success': True,
            'data': {
                'ranking': results,
                'best_practices': best_practices,
                'gaps_analysis': {
                    'average_score': avg_score,
                    'score_range': score_range,
                    'improvement_potential': improvement_potential
                }
            },
            'message': '对比分析完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'对比失败: {str(e)}'
        }), 500


def get_best_practice_tip(aspect, score):
    """获取最佳实践建议"""
    tips = {
        'content': {
            'high': '内容丰富且深度足够，建议持续保持内容更新频率',
            'medium': '内容基础较好，建议增加更多细节和实例',
            'low': '内容量不足，需要大幅扩充内容深度和广度'
        },
        'structure': {
            'high': '页面结构清晰，标题层级合理，建议保持',
            'medium': '结构有基础，建议优化标题层级和内部链接',
            'low': '页面结构混乱，需要重新规划内容组织方式'
        },
        'authority': {
            'high': '信源权威性强，Schema标记完善',
            'medium': '有一定权威性基础，建议增加更多结构化数据',
            'low': '权威性不足，需要建立完善的Schema和信源体系'
        },
        'technical': {
            'high': '技术性能优秀，加载速度快',
            'medium': '技术基础尚可，建议优化加载速度',
            'low': '技术层面有较大优化空间，建议优先处理'
        }
    }
    
    if score >= 80:
        level = 'high'
    elif score >= 60:
        level = 'medium'
    else:
        level = 'low'
    
    return tips[aspect][level]


@app.route('/api/website/history', methods=['GET'])
def get_website_history():
    """获取网站诊断历史"""
    try:
        limit = request.args.get('limit', 10, type=int)
        limit = min(limit, 50)
        
        # 从数据库获取诊断历史
        try:
            diagnoses = diagnosis_repo.get_user_diagnoses(1, limit)
            return jsonify({
                'success': True,
                'data': diagnoses,
                'message': f'获取到{len(diagnoses)}条记录'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'获取失败: {str(e)}'
            }), 500
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }), 500


# ==================== GEO优化方案生成 ====================

@app.route('/api/geo/optimization-plan', methods=['POST', 'OPTIONS'])
@jwt_required()
def generate_optimization_plan():
    """生成GEO优化方案"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        # 获取当前用户
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        data = request.get_json()
        domain = data.get('domain', '')
        brand_name = data.get('brand_name', '')
        industry = data.get('industry', '')
        keywords = data.get('keywords', [])
        location = data.get('location', '')
        
        if not domain or not brand_name:
            return jsonify({
                'success': False,
                'message': '域名和品牌名称不能为空'
            }), 400
        
        # 生成优化方案
        plan = generate_geo_plan(domain, brand_name, industry, keywords, location)
        
        # 保存到数据库
        try:
            plan_record = {
                'user_id': user['id'],
                'domain': domain,
                'brand_name': brand_name,
                'industry': industry,
                'location': location,
                'keywords': keywords,
                'plan_data': plan
            }
            
            save_result = optimization_plan_repo.save_plan(plan_record)
            if save_result['success']:
                plan['id'] = save_result['id']
                plan['user_id'] = user['id']
                print(f"✅ 优化方案已保存到数据库, ID: {save_result['id']}, 用户: {user['username']}")
        except Exception as db_err:
            print(f"⚠️ 保存优化方案失败: {db_err}")
        
        return jsonify({
            'success': True,
            'data': plan,
            'message': '优化方案生成成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'生成失败: {str(e)}'
        }), 500


def generate_geo_plan(domain, brand_name, industry, keywords, location):
    """生成GEO优化方案 - 使用AI服务生成详细方案"""
    
    # 使用AI服务生成详细优化方案
    system_prompt = """你是一位资深的GEO（生成式引擎优化）专家，拥有10年以上的SEO和AI优化经验。
你的任务是为客户生成一份专业、详细、可执行的GEO优化方案。
方案必须包含以下核心要素：

1. 品牌定位分析 - 深入分析品牌在AI搜索中的定位
2. 关键词策略 - 核心词、长尾词、地域词的完整矩阵
3. 词条投入计划 - 每个关键词的具体投入策略、预算分配、内容要求
4. 数据喂养策略 - 如何训练AI认识品牌，建立知识图谱
5. 内容策略 - 具体的内容类型、主题、发布计划
6. 信源建设 - 权威平台布局策略
7. 执行路线图 - 分阶段的具体执行步骤
8. 效果预期 - 量化的KPI指标

要求：
- 内容必须具体、可执行，避免空泛的描述
- 每个策略都要有具体的执行步骤和预期效果
- 使用专业的GEO术语和框架（如ERE框架）
- 输出格式为JSON，便于前端展示"""

    prompt = f"""请为以下品牌生成一份详细的GEO优化方案：

【品牌信息】
- 品牌名称: {brand_name}
- 网站域名: {domain}
- 所属行业: {industry}
- 目标地域: {location or '全国'}
- 核心关键词: {', '.join(keywords) if keywords else '待分析'}

请生成一份完整的GEO优化方案，包含：

1. **品牌定位分析**
   - 品牌在AI搜索中的当前定位
   - 目标用户画像（详细描述）
   - GEO优化核心策略

2. **关键词矩阵**
   - 核心关键词（3-5个）及竞争分析
   - 长尾关键词（10-15个）及搜索意图
   - 地域关键词（如适用）

3. **词条投入计划**（详细到每个关键词）
   - 每个关键词的优先级和预算分配
   - 内容类型和字数要求
   - 发布平台和频率
   - 预期排名和引用率

4. **数据喂养策略**
   - 如何建立品牌知识图谱
   - Schema标记部署方案
   - 多平台数据同步策略
   - AI训练数据源建设

5. **内容策略**
   - 内容类型规划（博客、问答、案例等）
   - 具体的内容主题建议（至少10个）
   - 内容发布日历（月度计划）
   - ERE框架应用（实体、关系、证据）

6. **信源建设**
   - 官方渠道建设（官网、百科、地图）
   - 第三方平台布局（知乎、小红书、公众号）
   - 行业权威认证获取
   - 媒体关系建设

7. **执行路线图**
   - 第1个月：基础搭建（具体任务清单）
   - 第2-3个月：内容生产（具体数量和类型）
   - 第4-6个月：推广优化（具体渠道和方式）
   - 持续运营：维护更新计划

8. **效果预期**
   - AI引用率提升目标（具体百分比）
   - 搜索排名目标（具体位置）
   - 流量和转化预期
   - ROI预估

请以JSON格式输出，确保所有字段都有具体的值，不要有空泛的描述。"""

    # 调用AI服务生成方案
    ai_result = ai_service.generate_content(prompt, system_prompt, temperature=0.7, max_tokens=8000)
    
    if ai_result['success']:
        try:
            # 尝试解析AI返回的JSON
            import json
            content = ai_result['content']
            
            # 提取JSON部分（AI可能在JSON前后添加了说明文字）
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                ai_plan = json.loads(json_str)
            else:
                ai_plan = json.loads(content)
            
            # 构建完整的方案结构
            plan = {
                'id': 1,
                'title': f'{brand_name} GEO优化方案',
                'description': f'针对{brand_name}（{domain}）的{industry}行业GEO优化策略，提升AI搜索引用率和品牌曝光度。',
                'expected_effect': ai_plan.get('效果预期', {}).get('AI引用率提升目标', '预计AI引用率提升150%'),
                'expected_score': 85,
                'domain': domain,
                'brand_name': brand_name,
                'industry': industry,
                'location': location,
                'generated_at': datetime.now().isoformat(),
                
                # AI生成的详细内容
                'brand_positioning': ai_plan.get('品牌定位分析', {
                    'brand_name': brand_name,
                    'industry': industry,
                    'target_users': f'{industry}行业目标客户',
                    'geo_strategy': f'建立{brand_name}在AI搜索中的权威性'
                }),
                
                'keyword_matrix': ai_plan.get('关键词矩阵', {
                    'core_keywords': keywords[:5] if keywords else [f'{brand_name}', f'{industry}'],
                    'long_tail_keywords': [],
                    'location_keywords': []
                }),
                
                'keyword_investment': ai_plan.get('词条投入计划', {}),
                'data_feeding': ai_plan.get('数据喂养策略', {}),
                'content_strategy': ai_plan.get('内容策略', {}),
                'authority_building': ai_plan.get('信源建设', {}),
                'execution_roadmap': ai_plan.get('执行路线图', {}),
                'expected_results': ai_plan.get('效果预期', {}),
                
                # 执行步骤（适配前端）
                'steps': [
                    {
                        'title': '基础搭建',
                        'description': ai_plan.get('执行路线图', {}).get('第1个月', '统一NAP信息，部署Schema标记，完善地图商家信息'),
                        'duration': '第1个月'
                    },
                    {
                        'title': '内容生产',
                        'description': ai_plan.get('执行路线图', {}).get('第2-3个月', f'产出深度文章，创作案例拆解，建立内容矩阵'),
                        'duration': '第2-3个月'
                    },
                    {
                        'title': '推广优化',
                        'description': ai_plan.get('执行路线图', {}).get('第4-6个月', '多平台分发，信源建设，数据监测优化'),
                        'duration': '第4-6个月'
                    },
                    {
                        'title': '持续运营',
                        'description': ai_plan.get('执行路线图', {}).get('持续运营', '月度更新，季度优化，保持竞争优势'),
                        'duration': '持续进行'
                    }
                ],
                
                # Schema优化建议
                'schema_optimization': {
                    'organization': {
                        'name': brand_name,
                        'description': f"{brand_name}专注{industry}领域，为用户提供专业服务",
                        'url': f"https://www.{domain}",
                        'services': get_services_list(industry)
                    },
                    'faq': generate_faq(industry),
                    'markup_code': generate_schema_markup(brand_name, domain, industry)
                },
                
                # 原始AI生成内容（用于详情页展示）
                'ai_generated_content': content
            }
            
            return plan
            
        except Exception as e:
            print(f"AI方案解析失败，使用默认方案: {e}")
    
    # AI生成失败或解析失败，使用默认方案
    return generate_default_geo_plan(domain, brand_name, industry, keywords, location)


def generate_default_geo_plan(domain, brand_name, industry, keywords, location):
    """生成默认GEO优化方案（当AI生成失败时使用）"""
    
    # 生成长尾关键词
    long_tail = generate_long_tail_keywords(brand_name, industry, location)
    core_keywords = keywords[:3] if keywords else [f'{brand_name}服务', f'{industry}解决方案', f'{location}{brand_name}']
    location_keywords = [f'{location}{brand_name}', f'{location}{industry}'] if location else [f'{brand_name}本地服务']
    
    # 生成详细词条投入计划
    keyword_investment_plan = generate_keyword_investment_plan(brand_name, industry, location, core_keywords, long_tail, location_keywords)
    
    # 生成数据喂养策略
    data_feeding_strategy = generate_data_feeding_strategy(brand_name, industry, domain, location)
    
    plan = {
        'id': 1,
        'title': f'{brand_name} GEO优化方案',
        'description': f'针对{brand_name}（{domain}）的{industry}行业GEO优化策略，提升AI搜索引用率和品牌曝光度。',
        'expected_effect': f'预计AI引用率提升150%，本地搜索排名进入Top 3，线索转化率提升30%',
        'expected_score': 85,
        'domain': domain,
        'brand_name': brand_name,
        'industry': industry,
        'location': location,
        'generated_at': datetime.now().isoformat(),
        
        # 品牌定位分析 - 适配前端
        'brand_positioning': {
            'brand_name': brand_name,
            'industry': industry,
            'target_users': f'新中产家庭、{industry}行业客户等目标群体',
            'geo_strategy': f"强化'{brand_name}'品牌词在AI搜索中的识别度，建立{industry}领域权威性"
        },
        
        # 关键词矩阵 - 适配前端
        'keyword_matrix': {
            'core_keywords': core_keywords,
            'long_tail_keywords': long_tail,
            'location_keywords': location_keywords
        },
        
        # 详细词条投入计划
        'keyword_investment': keyword_investment_plan,
        
        # 数据喂养策略
        'data_feeding': data_feeding_strategy,
        
        # 执行步骤 - 适配前端
        'steps': [
            {
                'title': '基础搭建',
                'description': '统一NAP信息，部署Schema标记，完善地图商家信息，建立品牌基础数据',
                'duration': '第1个月'
            },
            {
                'title': '内容生产',
                'description': f'产出3-5篇{industry}深度文章，创作案例拆解，建立内容矩阵',
                'duration': '第2-3个月'
            },
            {
                'title': '多平台分发',
                'description': '在官网、知乎、小红书、微信公众号等平台分发内容，扩大品牌影响力',
                'duration': '第4个月'
            },
            {
                'title': '信源建设',
                'description': '完善百度百科、百度地图、行业媒体认证，建立权威信源体系',
                'duration': '第5个月'
            },
            {
                'title': '持续运营',
                'description': '月度地图动态更新，季度案例更新，数据监测优化，保持竞争优势',
                'duration': '持续进行'
            }
        ],
        
        # Schema优化建议
        'schema_optimization': {
            'organization': {
                'name': brand_name,
                'description': f"{brand_name}专注{industry}领域，为用户提供专业服务",
                'url': f"https://www.{domain}",
                'services': get_services_list(industry)
            },
            'faq': generate_faq(industry),
            'markup_code': generate_schema_markup(brand_name, domain, industry)
        },
        
        # 内容优化策略
        'content_strategy': {
            'content_types': ['行业洞察', '产品评测', '使用指南', '案例分析'],
            'content_topics': generate_content_topics(brand_name, industry, location),
            'platform_distribution': ['官网', '知乎', '小红书', '微信公众号']
        },
        
        # 信源建设
        'authority_building': {
            'official_site': ['完善产品页面', '建立案例库', '添加FAQ'],
            'search_ecosystem': ['百度百科', '百度地图', '百度知道'],
            'industry_media': ['行业媒体报道', '协会认证'],
            'content_platforms': ['知乎专栏', '行业垂直平台']
        },
        
        # 执行路线图
        'execution_roadmap': {
            'month_1': ['统一NAP信息', '部署Schema标记', '完善地图商家信息'],
            'month_2_3': ['产出3-5篇深度文章', '创作案例拆解', '多平台分发'],
            'ongoing': ['月度地图动态更新', '季度案例更新', '数据监测优化']
        },
        
        # 效果预期
        'expected_results': {
            'ai_citation_increase': '+150%',
            'local_rank_improvement': 'Top 3',
            'conversion_rate_increase': '+30%',
            'monitoring_period': '6个月'
        }
    }
    
    return plan


def generate_keyword_investment_plan(brand_name, industry, location, core_keywords, long_tail_keywords, location_keywords):
    """生成详细词条投入计划"""
    
    # 核心词条投入（高优先级，高投入）
    core_investment = {
        'priority': '高',
        'budget_allocation': '40%',
        'keywords': core_keywords,
        'strategy': f'围绕"{brand_name}"品牌词和"{industry}"核心词建立权威内容',
        'content_requirements': [
            '每篇内容1500-3000字',
            '包含品牌词密度2-3%',
            '添加Schema.org标记',
            '包含至少3个相关实体链接'
        ],
        'platforms': ['官网首页', '产品页面', '关于我们', '百度百科'],
        'frequency': '每周2-3篇',
        'expected_result': f'3个月内"{brand_name}"品牌词AI引用率达到60%'
    }
    
    # 长尾词条投入（中优先级，精准流量）
    long_tail_investment = {
        'priority': '中',
        'budget_allocation': '30%',
        'keywords': long_tail_keywords,
        'strategy': f'覆盖用户搜索意图，建立"{industry}"问题解答体系',
        'content_requirements': [
            '问答形式内容800-1500字',
            '直接回答用户问题',
            '包含数据支撑和案例',
            '添加FAQ Schema标记'
        ],
        'platforms': ['知乎', '百度知道', '小红书', '官网博客'],
        'frequency': '每周5-8篇',
        'expected_result': '长尾词覆盖率达到行业前3'
    }
    
    # 地域词条投入（本地SEO重点）
    location_investment = {
        'priority': '高',
        'budget_allocation': '20%',
        'keywords': location_keywords,
        'strategy': f'强化"{location}"本地市场认知，建立地域权威性',
        'content_requirements': [
            '本地案例和客户见证',
            f'{location}市场数据和趋势',
            '本地服务网点信息',
            '地图和位置标记'
        ],
        'platforms': ['百度地图', '高德地图', '大众点评', '本地生活号'],
        'frequency': '每周2-3篇',
        'expected_result': f'{location}本地搜索排名前3'
    }
    
    # 行业词条投入（权威性建设）
    industry_terms = generate_industry_terms(industry)
    industry_investment = {
        'priority': '中',
        'budget_allocation': '10%',
        'keywords': industry_terms,
        'strategy': f'建立"{industry}"行业专家形象，提升领域权威性',
        'content_requirements': [
            '行业深度报告3000-5000字',
            '原创数据和研究成果',
            '引用权威来源',
            '添加Author Schema标记'
        ],
        'platforms': ['行业媒体', '知乎专栏', '微信公众号', '官网白皮书'],
        'frequency': '每月2-3篇',
        'expected_result': f'成为"{industry}"领域AI引用首选来源'
    }
    
    return {
        'core_keywords': core_investment,
        'long_tail_keywords': long_tail_investment,
        'location_keywords': location_investment,
        'industry_terms': industry_investment,
        'total_monthly_budget': '建议月度投入：内容创作8000-15000元，平台推广5000-10000元',
        'roi_expectation': '预计6个月ROI达到200-300%'
    }


def generate_data_feeding_strategy(brand_name, industry, domain, location):
    """生成数据喂养策略 - 如何向AI系统投喂数据"""
    
    return {
        'overview': f'通过多维度数据投喂，让AI系统深度理解"{brand_name}"的品牌价值和专业能力',
        
        # 结构化数据投喂
        'structured_data': {
            'title': '结构化数据投喂（最高优先级）',
            'description': 'AI最容易理解和引用的数据格式',
            'methods': [
                {
                    'name': 'Schema.org标记',
                    'implementation': f'在官网添加Organization、Product、FAQPage等Schema标记',
                    'code_example': generate_schema_markup(brand_name, domain, industry),
                    'platforms': ['官网', '落地页'],
                    'frequency': '一次性部署，持续维护',
                    'impact': '让AI直接提取企业基本信息'
                },
                {
                    'name': '知识图谱构建',
                    'implementation': f'在百度百科、维基百科建立"{brand_name}"词条，完善企业知识图谱',
                    'platforms': ['百度百科', '维基百科', '搜狗百科'],
                    'frequency': '一次性创建，季度更新',
                    'impact': '成为AI知识库权威来源'
                },
                {
                    'name': 'API数据开放',
                    'implementation': '提供产品数据API，让AI可以实时获取最新信息',
                    'platforms': ['官网API', '开放平台'],
                    'frequency': '持续维护',
                    'impact': 'AI获取实时、准确数据'
                }
            ]
        },
        
        # 内容数据投喂
        'content_data': {
            'title': '内容数据投喂',
            'description': '通过高质量内容训练AI对品牌的认知',
            'methods': [
                {
                    'name': '权威内容生产',
                    'content_types': [
                        f'{industry}行业白皮书（5000字+）',
                        f'{brand_name}案例研究（3000字+）',
                        f'{industry}趋势分析报告',
                        '客户成功故事和见证'
                    ],
                    'requirements': [
                        '原创度>80%',
                        '包含数据支撑',
                        '引用权威来源',
                        '定期更新维护'
                    ],
                    'platforms': ['官网', '知乎', '行业媒体'],
                    'frequency': '每周2-3篇',
                    'impact': '建立内容权威性'
                },
                {
                    'name': '问答内容布局',
                    'content_types': [
                        f'{industry}常见问题解答',
                        f'{brand_name}产品使用指南',
                        f'{location}{industry}选购建议'
                    ],
                    'requirements': [
                        '直接回答用户问题',
                        '答案简洁明了',
                        '包含品牌信息',
                        '添加FAQ Schema'
                    ],
                    'platforms': ['百度知道', '知乎', '官网FAQ'],
                    'frequency': '每周5-10个问答',
                    'impact': '覆盖用户搜索意图'
                }
            ]
        },
        
        # 社交信号投喂
        'social_signals': {
            'title': '社交信号投喂',
            'description': '通过社交媒体验证品牌真实性和活跃度',
            'methods': [
                {
                    'name': '官方账号运营',
                    'platforms': ['微信公众号', '知乎机构号', '微博企业号', '小红书品牌号'],
                    'content_strategy': [
                        '每日发布行业资讯',
                        '每周发布专业知识',
                        '每月发布案例分享',
                        '及时回复用户评论'
                    ],
                    'frequency': '每日更新',
                    'impact': '证明品牌活跃度和真实性'
                },
                {
                    'name': '用户UGC激励',
                    'strategy': '鼓励用户分享使用体验',
                    'methods': [
                        '好评返现活动',
                        '案例征集奖励',
                        '用户故事征集',
                        '社交媒体话题营销'
                    ],
                    'frequency': '持续进行',
                    'impact': '增加品牌提及和口碑'
                }
            ]
        },
        
        # 技术数据投喂
        'technical_data': {
            'title': '技术数据投喂',
            'description': '通过技术手段提升AI抓取和理解效率',
            'methods': [
                {
                    'name': '网站技术优化',
                    'items': [
                        '确保网站响应速度<3秒',
                        '实现HTTPS全站加密',
                        '优化移动端体验',
                        '添加XML网站地图',
                        '配置robots.txt'
                    ],
                    'impact': '提升AI爬虫抓取效率'
                },
                {
                    'name': '数据标记优化',
                    'items': [
                        '添加Open Graph标记',
                        '配置Twitter Cards',
                        '实现JSON-LD结构化数据',
                        '添加Breadcrumb导航',
                        '优化URL结构'
                    ],
                    'impact': '让AI更好理解页面内容'
                }
            ]
        },
        
        # 投喂时间表
        'feeding_schedule': {
            'week_1_2': [
                '部署Schema.org标记',
                '创建百度百科词条',
                '完善官网基础信息',
                '提交网站地图'
            ],
            'week_3_4': [
                '发布首批权威内容（5篇）',
                '建立社交媒体账号',
                '开始问答内容布局',
                '优化网站技术性能'
            ],
            'month_2_3': [
                '持续内容生产（每周3篇）',
                '扩大问答覆盖（每周10个）',
                '启动UGC激励计划',
                '监测AI引用情况'
            ],
            'ongoing': [
                '月度内容更新',
                '季度数据刷新',
                '年度权威报告发布',
                '持续监测和优化'
            ]
        },
        
        'success_metrics': [
            'AI引用率提升150%',
            '品牌词搜索量增长200%',
            '官网流量增长100%',
            '线索转化率提升30%',
            '品牌知名度提升50%'
        ]
    }


def generate_industry_terms(industry):
    """生成行业专业词条"""
    industry_terms_map = {
        '家具家居': [
            '全屋定制', '整体衣柜', '橱柜设计', '智能家居', 
            '环保板材', '空间规划', '软装搭配', '定制家具'
        ],
        '教育培训': [
            '在线教育', '职业培训', '技能提升', '课程设计',
            '学习路径', '认证考试', '企业培训', '知识付费'
        ],
        '医疗健康': [
            '健康管理', '慢病管理', '体检服务', '康复护理',
            '营养咨询', '心理健康', '远程医疗', '健康大数据'
        ],
        '电商零售': [
            '新零售', '社交电商', '直播带货', '私域流量',
            '供应链管理', '用户体验', '数据分析', '精准营销'
        ],
        '科技软件': [
            'SaaS服务', '云计算', '人工智能', '大数据分析',
            '系统集成', '数字化转型', '敏捷开发', 'DevOps'
        ]
    }
    return industry_terms_map.get(industry, ['行业解决方案', '专业服务', '技术创新'])


def generate_long_tail_keywords(brand_name, industry, location):
    """生成长尾关键词"""
    templates = [
        f"{location}{brand_name}{industry}推荐",
        f"{brand_name}{industry}怎么样",
        f"{location}{industry}哪家好",
        f"{brand_name}{industry}价格",
        f"{brand_name}{industry}对比"
    ]
    return templates


def get_services_list(industry):
    """获取服务列表"""
    services_map = {
        '家具家居': ['全屋定制', '衣柜定制', '橱柜定制', '家具设计'],
        '教育培训': ['课程培训', '在线教育', '职业培训', '考试辅导'],
        '医疗健康': ['健康咨询', '体检服务', '专科诊疗', '康复护理'],
        '电商零售': ['商品销售', '售后服务', '物流配送', '会员服务'],
        '科技软件': ['软件开发', '技术咨询', '系统集成', '运维服务']
    }
    return services_map.get(industry, ['服务1', '服务2', '服务3'])


def generate_faq(industry):
    """生成FAQ"""
    faq_map = {
        '家具家居': [
            {'question': '定制周期是多久？', 'answer': '标准定制周期为25-30天'},
            {'question': '是否提供免费上门量尺？', 'answer': '是的，提供免费上门量尺服务'},
            {'question': '使用什么材质？', 'answer': '采用E0级环保板材'},
            {'question': '售后服务如何？', 'answer': '提供5年质保，终身维护'}
        ],
        '教育培训': [
            {'question': '课程时长是多少？', 'answer': '根据课程类型从几小时到数月不等'},
            {'question': '是否有试听课程？', 'answer': '是的，提供免费试听课程'},
            {'question': '师资力量如何？', 'answer': '全部为行业资深讲师'},
            {'question': '学习效果有保障吗？', 'answer': '提供学习效果承诺和退款保障'}
        ],
        '医疗健康': [
            {'question': '如何预约挂号？', 'answer': '可通过官网、电话或APP预约'},
            {'question': '支持医保吗？', 'answer': '支持医保结算'},
            {'question': '就诊需要带什么？', 'answer': '请携带身份证和医保卡'},
            {'question': '有在线问诊吗？', 'answer': '提供在线问诊服务'}
        ]
    }
    return faq_map.get(industry, [
        {'question': '服务流程是怎样的？', 'answer': '请联系客服了解详细流程'},
        {'question': '收费标准是什么？', 'answer': '根据服务类型有所不同'}
    ])


def generate_schema_markup(brand_name, domain, industry):
    """生成Schema标记代码"""
    schema = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": brand_name,
        "description": f"{brand_name}专注{industry}领域，为用户提供优质服务",
        "url": f"https://www.{domain}",
        "sameAs": [
            f"https://weibo.com/{brand_name}",
            f"https://www.zhihu.com/people/{brand_name}"
        ]
    }
    return json.dumps(schema, ensure_ascii=False, indent=2)


def generate_content_topics(brand_name, industry, location):
    """生成内容主题"""
    topics = [
        f"{location}{industry}趋势分析",
        f"{brand_name}{industry}案例分享",
        f"{industry}选购指南",
        f"{location}{industry}市场调研"
    ]
    return topics


# ==================== 历史记录查询 ====================

@app.route('/api/diagnosis/history', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_diagnosis_history():
    """获取诊断历史记录"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        user_id = user['id']
        limit = request.args.get('limit', 50, type=int)
        
        diagnoses = diagnosis_repo.get_user_diagnoses(user_id, limit)
        
        return jsonify({
            'success': True,
            'data': diagnoses,
            'message': f'获取到{len(diagnoses)}条记录'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取历史记录失败: {str(e)}'
        }), 500


@app.route('/api/optimization/plans', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_plan_history():
    """获取优化方案历史记录"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        user_id = user['id']
        limit = request.args.get('limit', 50, type=int)
        
        plans = optimization_plan_repo.get_user_plans(user_id, limit)
        
        return jsonify({
            'success': True,
            'data': plans,
            'message': f'获取到{len(plans)}条记录'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取历史记录失败: {str(e)}'
        }), 500


@app.route('/api/diagnosis/<int:diagnosis_id>', methods=['GET', 'OPTIONS'])
def get_diagnosis_by_id(diagnosis_id):
    """根据ID获取诊断记录"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        diagnosis = diagnosis_repo.get_diagnosis_by_id(diagnosis_id)
        
        if not diagnosis:
            return jsonify({
                'success': False,
                'message': '诊断记录不存在'
            }), 404
        
        return jsonify({
            'success': True,
            'data': diagnosis,
            'message': '获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取诊断记录失败: {str(e)}'
        }), 500


@app.route('/api/plan/<int:plan_id>', methods=['GET', 'OPTIONS'])
def get_plan_by_id(plan_id):
    """根据ID获取优化方案"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        plan = optimization_plan_repo.get_plan_by_id(plan_id)
        
        if not plan:
            return jsonify({
                'success': False,
                'message': '优化方案不存在'
            }), 404
        
        return jsonify({
            'success': True,
            'data': plan,
            'message': '获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取优化方案失败: {str(e)}'
        }), 500


@app.route('/api/plan/<int:plan_id>/export', methods=['GET', 'OPTIONS'])
@jwt_required()
def export_plan(plan_id):
    """导出优化方案为 Word 文档"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        # 获取方案
        plan = optimization_plan_repo.get_plan_by_id(plan_id)
        if not plan:
            return jsonify({'success': False, 'message': '优化方案不存在'}), 404

        # 验证权限
        if plan.get('user_id') != user['id']:
            return jsonify({'success': False, 'message': '无权访问此方案'}), 403

        # 生成 Word 文档
        docx_data = export_service.export_plan_to_docx(plan)

        # 生成文件名
        brand_name = plan.get('brand_name', '未命名品牌')
        filename = f"{brand_name}_GEO优化方案.docx"

        # 返回文件
        from flask import send_file
        return send_file(
            BytesIO(docx_data),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'导出方案失败: {str(e)}'
        }), 500


# ==================== 删除项目 ====================

@app.route('/api/diagnosis/<int:diagnosis_id>', methods=['DELETE', 'OPTIONS'])
@jwt_required()
def delete_diagnosis(diagnosis_id):
    """删除诊断记录"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        # 验证记录属于当前用户
        diagnosis = diagnosis_repo.get_diagnosis_by_id(diagnosis_id)
        if not diagnosis:
            return jsonify({'success': False, 'message': '记录不存在'}), 404
        
        # 执行删除
        result = diagnosis_repo.delete_diagnosis(diagnosis_id, user['id'])
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': '删除成功'
            })
        else:
            return jsonify({
                'success': False,
                'message': result.get('message', '删除失败')
            }), 400
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }), 500


@app.route('/api/optimization/plans/<int:plan_id>', methods=['DELETE', 'OPTIONS'])
@jwt_required()
def delete_plan(plan_id):
    """删除优化方案"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        # 验证记录属于当前用户
        plan = optimization_plan_repo.get_plan_by_id(plan_id)
        if not plan:
            return jsonify({'success': False, 'message': '记录不存在'}), 404
        
        # 执行删除
        result = optimization_plan_repo.delete_plan(plan_id, user['id'])
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': '删除成功'
            })
        else:
            return jsonify({
                'success': False,
                'message': result.get('message', '删除失败')
            }), 400
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }), 500


# ==================== AI任务管理 ====================

@app.route('/api/ai-tasks/create-from-plan', methods=['POST', 'OPTIONS'])
@jwt_required()
def create_ai_tasks_from_plan():
    """从优化方案创建AI任务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        data = request.get_json()
        plan_id = data.get('plan_id')
        
        if not plan_id:
            return jsonify({'success': False, 'message': '请提供方案ID'}), 400
        
        # 获取方案详情
        plan = optimization_plan_repo.get_plan_by_id(plan_id)
        if not plan:
            return jsonify({'success': False, 'message': '方案不存在'}), 404
        
        # 验证方案属于当前用户
        # TODO: 添加方案的用户关联验证
        
        # 创建AI任务
        tasks = ai_task_manager.create_tasks_from_plan(plan, user['id'])
        
        # 保存任务到数据库
        saved_tasks = []
        for task_data in tasks:
            result = generation_repo.save_ai_task(task_data)
            if result['success']:
                saved_tasks.append({
                    'id': result['id'],
                    'title': task_data['title'],
                    'task_type': task_data['task_type'],
                    'status': task_data['status']
                })
        
        return jsonify({
            'success': True,
            'data': {
                'tasks': saved_tasks,
                'count': len(saved_tasks)
            },
            'message': f'成功创建{len(saved_tasks)}个AI任务'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'创建任务失败: {str(e)}'
        }), 500


@app.route('/api/ai-tasks', methods=['GET', 'POST', 'OPTIONS'])
@jwt_required()
def get_ai_tasks():
    """获取用户的AI任务列表 / 创建新任务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    if request.method == 'POST':
        # 创建新任务
        try:
            current_user = get_jwt_identity()
            user = user_repo.get_user_by_username(current_user)
            if not user:
                return jsonify({'success': False, 'message': '用户不存在'}), 404
            
            data = request.get_json()
            task_data = {
                'user_id': user['id'],
                'task_type': data.get('task_type', 'xiaohongshu'),
                'status': 'pending',
                'title': data.get('title', ''),
                'description': data.get('description', ''),
                'input_data': data.get('input_data', {}),
                'output_data': {},
                'keywords': data.get('input_data', {}).get('keywords', [])
            }
            
            result = generation_repo.save_ai_task(task_data)
            if result.get('success'):
                task_id = result['id']
                return jsonify({
                    'success': True,
                    'data': {'id': task_id},
                    'message': '任务创建成功'
                })
            else:
                return jsonify({'success': False, 'message': result.get('message', '创建失败')}), 500
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'message': f'创建任务失败: {str(e)}'}), 500
    
    # GET - 获取任务列表
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        user_id = user['id']
        status = request.args.get('status')
        task_type = request.args.get('type')
        limit = request.args.get('limit', 50, type=int)
        
        # 管理员可以看到所有任务
        if user.get('username') == 'admin':
            tasks = generation_repo.get_user_ai_tasks(None, status, task_type, limit)
        else:
            tasks = generation_repo.get_user_ai_tasks(user_id, status, task_type, limit)
        
        return jsonify({
            'success': True,
            'data': tasks,
            'message': f'获取到{len(tasks)}个任务'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取任务失败: {str(e)}'
        }), 500


@app.route('/api/ai-tasks/<int:task_id>', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_ai_task_detail(task_id):
    """获取AI任务详情"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        task = generation_repo.get_ai_task_by_id(task_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        # 验证任务属于当前用户（管理员跳过权限检查）
        if task['user_id'] != user['id'] and user.get('username') != 'admin':
            return jsonify({'success': False, 'message': '无权访问此任务'}), 403
        
        # 生成AI提示词
        prompt = ai_task_manager.generate_content_prompt(task)
        task['ai_prompt'] = prompt
        
        return jsonify({
            'success': True,
            'data': task,
            'message': '获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取任务详情失败: {str(e)}'
        }), 500


@app.route('/api/ai-tasks/<int:task_id>/execute', methods=['POST', 'OPTIONS'])
@jwt_required()
def execute_ai_task(task_id):
    """执行AI任务（生成内容）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        task = generation_repo.get_ai_task_by_id(task_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        # 验证任务属于当前用户（管理员跳过权限检查）
        if task['user_id'] != user['id'] and user.get('username') != 'admin':
            return jsonify({'success': False, 'message': '无权执行此任务'}), 403
        
        # 更新任务状态为生成中
        generation_repo.update_task_status(task_id, TaskStatus.GENERATING.value)
        
        # 获取任务输入数据
        input_data = task.get('input_data', {})
        task_type = task.get('task_type')
        
        # 调用真实AI服务生成内容
        if task_type == TaskType.ARTICLE.value:
            # 使用真实AI服务生成文章
            ai_result = ai_service.generate_geo_article(
                title=task.get('title', ''),
                brand_info={
                    'name': input_data.get('brand_name', ''),
                    'industry': input_data.get('industry', ''),
                    'expertise': input_data.get('keywords', [])
                },
                keywords=input_data.get('keywords', []),
                target_platform=input_data.get('target_platform', 'chatgpt'),
                word_count=input_data.get('target_word_count', 2500)
            )

            if ai_result['success']:
                result = {
                    'content': ai_result['content'],
                    'model': ai_result.get('model', 'unknown'),
                    'usage': ai_result.get('usage', {}),
                    'type': 'article',
                    'generated_at': datetime.now().isoformat()
                }
            else:
                # AI生成失败，返回错误
                generation_repo.update_task_status(task_id, TaskStatus.FAILED.value, ai_result.get('error', 'AI生成失败'))
                return jsonify({
                    'success': False,
                    'message': f'AI生成失败: {ai_result.get("error", "未知错误")}'
                }), 500
        elif task_type == TaskType.XIAOHONGSHU.value:
            # 小红书任务：优先使用AI生成真实内容，模板只作为fallback
            brand_name = input_data.get('brand_name', '')
            domain = input_data.get('domain', '')
            industry = input_data.get('industry', '')
            keywords = input_data.get('keywords', [])
            target_keyword = input_data.get('target_keyword', '')
            
            if target_keyword:
                keywords = [target_keyword] + keywords
            
            try:
                system_prompt = f"""你是一位资深小红书家居博主，擅长写真实自然的种草笔记。
你的任务是为品牌「{brand_name}」（{industry}行业）写一篇小红书笔记。

写作要求：
1. 真实分享感：像朋友聊天一样，口语化，避免营销感
2. 具体细节：有具体的使用场景、感受、细节描述
3. 结构清晰：开头引入痛点/场景 → 主体分点分享 → 结尾互动
4. 个人化：加入个人经历和真实感受
5. 价值输出：读者能获得实用信息或情感共鸣
6. 字数500-800字，分段清晰，每段不超过3行
7. 话题标签3-5个，放在文末，格式#标签#

禁止内容：
- 绝对化用语（最好、第一、顶级等）
- 诱导性用语（不看后悔、必买等）
- 直接放网址、联系方式、价格
- 硬广式推销

输出格式：JSON格式，包含 title、content、keywords 三个字段
- title: 20字以内的标题
- content: 正文内容
- keywords: 标签列表（3-5个）"""

                user_prompt = f"""请为品牌「{brand_name}」写一篇小红书笔记。

【品牌信息】
- 品牌：{brand_name}
- 行业：{industry}
- 网站：{domain}
- 核心关键词：{', '.join(keywords[:5])}

【风格参考】
- 真实分享感，像普通人的装修日记
- 有具体的场景和细节，不要空泛
- 亲切的语气，像和朋友聊天

请直接输出JSON，不要输出其他内容。"""

                ai_result = ai_service.generate_content(user_prompt, system_prompt, temperature=0.8, max_tokens=1500)
                
                if ai_result.get('success'):
                    content_text = ai_result.get('content', '').strip()
                    # 尝试解析JSON输出
                    import json as _json
                    xhs_title = ''
                    xhs_content = ''
                    xhs_keywords = []
                    
                    try:
                        # 提取JSON部分
                        json_start = content_text.find('{')
                        json_end = content_text.rfind('}') + 1
                        if json_start >= 0 and json_end > json_start:
                            json_str = content_text[json_start:json_end]
                            parsed = _json.loads(json_str)
                            xhs_title = str(parsed.get('title', ''))[:20] or brand_name + '分享'
                            xhs_content = str(parsed.get('content', ''))
                            xhs_keywords = parsed.get('keywords', [])[:5]
                            if isinstance(xhs_keywords, str):
                                xhs_keywords = [xhs_keywords]
                    except Exception as parse_e:
                        logger.warning(f"小红书AI内容JSON解析失败，使用原始内容: {parse_e}")
                        # 解析失败时，用前20字做标题，全部内容做正文
                        xhs_title = content_text[:20]
                        xhs_content = content_text
                        xhs_keywords = keywords[:5]
                    
                    if not xhs_title:
                        xhs_title = f'{brand_name}装修分享'
                    if not xhs_content:
                        xhs_content = content_text
                    
                    logger.info(f"小红书AI内容生成成功: {xhs_title}")
                    result = {
                        'title': xhs_title[:20],
                        'content': xhs_content,
                        'keywords': xhs_keywords,
                        'platform': 'xiaohongshu',
                        'type': 'xiaohongshu',
                        'model': ai_result.get('model', 'unknown'),
                        'generated_at': datetime.now().isoformat()
                    }
                else:
                    raise Exception(f"AI生成失败: {ai_result.get('error', '未知错误')}")
            except Exception as e:
                logger.warning(f"小红书AI内容生成失败，使用模板fallback: {e}")
                # Fallback：使用内容策略模板
                try:
                    from xiaohongshu_content_strategy import content_strategy
                    brand_info = {
                        "style": input_data.get('style', '简约自然'),
                        "features": input_data.get('features', ['品质', '实用', '值得推荐']),
                        "website": domain
                    }
                    generated = content_strategy.generate_content(brand_info, keywords)
                    xhs_title = generated["title"][:20]
                    xhs_content = generated["content"]
                    xhs_keywords = generated["hashtags"]
                    result = {
                        'title': xhs_title,
                        'content': xhs_content,
                        'keywords': xhs_keywords,
                        'platform': 'xiaohongshu',
                        'type': 'xiaohongshu',
                        'fallback': True,
                        'generated_at': datetime.now().isoformat()
                    }
                except Exception as e2:
                    generation_repo.update_task_status(task_id, TaskStatus.FAILED.value, f'内容生成失败: {str(e2)}')
                    return jsonify({'success': False, 'message': f'内容生成失败: {str(e2)}'}), 500
        else:
            # 其他类型任务生成提示词，供外部AI使用
            prompt = ai_task_manager.generate_content_prompt(task)
            result = {
                'prompt': prompt,
                'type': task_type,
                'message': '请使用此提示词调用AI生成内容'
            }
        
        # 保存生成结果
        generation_repo.update_task_output(task_id, {
            'status': TaskStatus.COMPLETED.value,
            'output_data': result,
            'completed_at': datetime.now().isoformat()
        })
        
        return jsonify({
            'success': True,
            'data': result,
            'message': '任务执行成功'
        })
        
    except Exception as e:
        # 更新任务状态为失败
        generation_repo.update_task_status(task_id, TaskStatus.FAILED.value, str(e))
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'任务执行失败: {str(e)}'
        }), 500


@app.route('/api/ai-tasks/batch-execute', methods=['POST', 'OPTIONS'])
@jwt_required()
def batch_execute_ai_tasks():
    """批量执行AI任务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        data = request.get_json()
        task_ids = data.get('task_ids', [])
        
        if not task_ids:
            return jsonify({'success': False, 'message': '请选择要执行的任务'}), 400
        
        if len(task_ids) > 20:
            return jsonify({'success': False, 'message': '一次最多执行20个任务'}), 400
        
        results = []
        success_count = 0
        failed_count = 0
        
        for task_id in task_ids:
            try:
                task = generation_repo.get_ai_task_by_id(task_id)
                if not task:
                    results.append({'task_id': task_id, 'status': 'failed', 'error': '任务不存在'})
                    failed_count += 1
                    continue
                
                # 验证任务属于当前用户
                if task['user_id'] != user['id']:
                    results.append({'task_id': task_id, 'status': 'failed', 'error': '无权执行'})
                    failed_count += 1
                    continue
                
                # 跳过已完成的任务
                if task['status'] == TaskStatus.COMPLETED.value:
                    results.append({'task_id': task_id, 'status': 'skipped', 'message': '任务已完成'})
                    continue
                
                # 更新任务状态为生成中
                generation_repo.update_task_status(task_id, TaskStatus.GENERATING.value)
                
                # 获取任务输入数据
                input_data = task.get('input_data', {})
                task_type = task.get('task_type')
                
                # 调用真实AI服务生成内容
                if task_type == TaskType.ARTICLE.value:
                    ai_result = ai_service.generate_geo_article(
                        title=task.get('title', ''),
                        brand_info={
                            'name': input_data.get('brand_name', ''),
                            'industry': input_data.get('industry', ''),
                            'expertise': input_data.get('keywords', [])
                        },
                        keywords=input_data.get('keywords', []),
                        target_platform=input_data.get('target_platform', 'chatgpt'),
                        word_count=input_data.get('target_word_count', 2500)
                    )
                    
                    if ai_result['success']:
                        result = {
                            'content': ai_result['content'],
                            'model': ai_result.get('model', 'unknown'),
                            'usage': ai_result.get('usage', {}),
                            'type': 'article',
                            'generated_at': datetime.now().isoformat()
                        }
                        
                        # 保存生成结果
                        generation_repo.update_task_output(task_id, {
                            'status': TaskStatus.COMPLETED.value,
                            'output_data': result,
                            'completed_at': datetime.now().isoformat()
                        })
                        
                        results.append({'task_id': task_id, 'status': 'success', 'title': task.get('title')})
                        success_count += 1
                    else:
                        generation_repo.update_task_status(task_id, TaskStatus.FAILED.value, ai_result.get('error', 'AI生成失败'))
                        results.append({'task_id': task_id, 'status': 'failed', 'error': ai_result.get('error', 'AI生成失败')})
                        failed_count += 1
                elif task_type == TaskType.XIAOHONGSHU.value:
                    # 小红书任务：使用内容策略生成
                    try:
                        from xiaohongshu_content_strategy import content_strategy
                        brand_info = {
                            "style": input_data.get('style', '简约自然'),
                            "features": input_data.get('features', ['品质', '实用', '值得推荐']),
                            "website": input_data.get('domain', '')
                        }
                        keywords = input_data.get('keywords', [])
                        target_keyword = input_data.get('target_keyword', '')
                        if target_keyword:
                            keywords = [target_keyword] + keywords
                        generated = content_strategy.generate_content(brand_info, keywords)
                        result = {
                            'title': generated["title"][:20],
                            'content': generated["content"],
                            'keywords': generated["hashtags"],
                            'platform': 'xiaohongshu',
                            'type': 'xiaohongshu',
                            'generated_at': datetime.now().isoformat()
                        }
                    except Exception as e:
                        result = {
                            'prompt': ai_task_manager.generate_content_prompt(task),
                            'type': task_type,
                            'message': f'内容策略生成失败({str(e)})，请使用提示词调用AI生成内容'
                        }
                else:
                    # 其他类型任务生成提示词
                    prompt = ai_task_manager.generate_content_prompt(task)
                    result = {
                        'prompt': prompt,
                        'type': task_type,
                        'message': '请使用此提示词调用AI生成内容'
                    }
                    
                    generation_repo.update_task_output(task_id, {
                        'status': TaskStatus.COMPLETED.value,
                        'output_data': result,
                        'completed_at': datetime.now().isoformat()
                    })
                    
                    results.append({'task_id': task_id, 'status': 'success', 'title': task.get('title')})
                    success_count += 1
                    
            except Exception as e:
                generation_repo.update_task_status(task_id, TaskStatus.FAILED.value, str(e))
                results.append({'task_id': task_id, 'status': 'failed', 'error': str(e)})
                failed_count += 1
        
        return jsonify({
            'success': True,
            'data': {
                'total': len(task_ids),
                'success': success_count,
                'failed': failed_count,
                'results': results
            },
            'message': f'批量执行完成：成功 {success_count} 个，失败 {failed_count} 个'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'批量执行失败: {str(e)}'
        }), 500


@app.route('/api/ai-tasks/<int:task_id>/prompt', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_ai_task_prompt(task_id):
    """获取AI任务的提示词（用于外部AI工具）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        task = generation_repo.get_ai_task_by_id(task_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        # 验证任务属于当前用户（管理员跳过权限检查）
        if task['user_id'] != user['id'] and user.get('username') != 'admin':
            return jsonify({'success': False, 'message': '无权访问此任务'}), 403
        
        # 生成提示词
        prompt = ai_task_manager.generate_content_prompt(task)
        
        return jsonify({
            'success': True,
            'data': {
                'task_id': task_id,
                'title': task.get('title'),
                'task_type': task.get('task_type'),
                'prompt': prompt,
                'input_data': task.get('input_data')
            },
            'message': '获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取提示词失败: {str(e)}'
        }), 500


@app.route('/api/ai-tasks/<int:task_id>/result', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_ai_task_result(task_id):
    """获取AI任务的生成结果"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        task = generation_repo.get_ai_task_by_id(task_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        # 验证任务属于当前用户（管理员跳过权限检查）
        if task['user_id'] != user['id'] and user.get('username') != 'admin':
            return jsonify({'success': False, 'message': '无权访问此任务'}), 403
        
        # 获取输出数据
        output_data = task.get('output_data', {})
        
        if not output_data:
            return jsonify({
                'success': False,
                'message': '暂无生成结果'
            }), 404
        
        return jsonify({
            'success': True,
            'data': output_data,
            'message': '获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取结果失败: {str(e)}'
        }), 500


@app.route('/api/ai-tasks/<int:task_id>', methods=['DELETE', 'OPTIONS'])
@jwt_required()
def delete_ai_task(task_id):
    """删除AI任务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        task = generation_repo.get_ai_task_by_id(task_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        # 验证任务属于当前用户（user_id为NULL时允许删除）
        if task.get('user_id') is not None and task['user_id'] != user['id']:
            return jsonify({'success': False, 'message': '无权删除此任务'}), 403
        
        result = generation_repo.delete_ai_task(task_id, user['id'])
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': '删除成功'
            })
        else:
            return jsonify({
                'success': False,
                'message': result.get('message', '删除失败')
            }), 400
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }), 500


@app.route('/api/ai-tasks/<int:task_id>/retry', methods=['POST', 'OPTIONS'])
@jwt_required()
def retry_ai_task(task_id):
    """重新执行失败的AI任务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        task = generation_repo.get_ai_task_by_id(task_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        # 验证任务属于当前用户（管理员跳过权限检查）
        if task['user_id'] != user['id'] and user.get('username') != 'admin':
            return jsonify({'success': False, 'message': '无权访问此任务'}), 403
        
        # 只有失败或已完成的任务可以重新执行
        if task['status'] not in ['failed', 'completed']:
            return jsonify({'success': False, 'message': '只有失败或已完成的任务可以重新执行'}), 400
        
        # 更新任务状态为生成中
        generation_repo.update_task_status(task_id, TaskStatus.GENERATING.value)

        # 获取任务输入数据
        input_data = task.get('input_data', {})
        task_type = task.get('task_type')

        try:
            # 调用真实AI服务生成内容
            if task_type == TaskType.ARTICLE.value:
                # 使用真实AI服务生成文章
                ai_result = ai_service.generate_geo_article(
                    title=task.get('title', ''),
                    brand_info={
                        'name': input_data.get('brand_name', ''),
                        'industry': input_data.get('industry', ''),
                        'expertise': input_data.get('keywords', [])
                    },
                    keywords=input_data.get('keywords', []),
                    target_platform=input_data.get('target_platform', 'chatgpt'),
                    word_count=input_data.get('target_word_count', 2500)
                )

                if ai_result['success']:
                    result = {
                        'content': ai_result['content'],
                        'model': ai_result.get('model', 'unknown'),
                        'usage': ai_result.get('usage', {}),
                        'type': 'article',
                        'generated_at': datetime.now().isoformat()
                    }

                    # 保存生成结果
                    generation_repo.update_task_output(task_id, {
                        'status': TaskStatus.COMPLETED.value,
                        'output_data': result,
                        'completed_at': datetime.now().isoformat()
                    })

                    return jsonify({
                        'success': True,
                        'message': '任务重新执行成功',
                        'data': {'task_id': task_id, 'status': 'completed'}
                    })
                else:
                    # AI生成失败
                    generation_repo.update_task_status(task_id, TaskStatus.FAILED.value, ai_result.get('error', 'AI生成失败'))
                    return jsonify({
                        'success': False,
                        'message': f'AI生成失败: {ai_result.get("error", "未知错误")}'
                    }), 500
            else:
                # 其他类型任务生成提示词
                prompt = ai_task_manager.generate_content_prompt(task)
                result = {
                    'prompt': prompt,
                    'type': task_type,
                    'message': '请使用此提示词调用AI生成内容'
                }

                # 保存生成结果
                generation_repo.update_task_output(task_id, {
                    'status': TaskStatus.COMPLETED.value,
                    'output_data': result,
                    'completed_at': datetime.now().isoformat()
                })

                return jsonify({
                    'success': True,
                    'message': '任务重新执行成功',
                    'data': {'task_id': task_id, 'status': 'completed'}
                })

        except Exception as exec_error:
            # 更新任务状态为失败
            generation_repo.update_task_status(task_id, TaskStatus.FAILED.value, str(exec_error))
            raise exec_error
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'重新执行失败: {str(e)}'
        }), 500


# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'message': '接口不存在'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'message': '服务器内部错误'
    }), 500


# ==================== 内容发布API ====================

@app.route('/api/publish/platforms', methods=['GET', 'OPTIONS'])
def get_publish_platforms():
    """获取可发布的平台列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    platforms = [
        {
            'id': 'zhihu',
            'name': '知乎',
            'icon': '📝',
            'description': '发布文章和回答',
            'content_types': ['article', 'faq'],
            'configured': publish_service.get_platform_account(PlatformType.ZHIHU) is not None
        },
        {
            'id': 'xiaohongshu',
            'name': '小红书',
            'icon': '📕',
            'description': '发布种草笔记',
            'content_types': ['short'],
            'configured': publish_service.get_platform_account(PlatformType.XIAOHONGSHU) is not None
        },
        {
            'id': 'weibo',
            'name': '微博',
            'icon': '📢',
            'description': '发布短内容',
            'content_types': ['short'],
            'configured': publish_service.get_platform_account(PlatformType.WEIBO) is not None
        },
        {
            'id': 'website_blog',
            'name': '官网博客',
            'icon': '🌐',
            'description': '发布到官网博客',
            'content_types': ['article'],
            'configured': True  # 官网不需要额外配置
        },
        {
            'id': 'website_faq',
            'name': '官网FAQ',
            'icon': '❓',
            'description': '添加到官网FAQ',
            'content_types': ['faq'],
            'configured': True
        }
    ]

    return jsonify({
        'success': True,
        'platforms': platforms
    })


@app.route('/api/publish/tasks', methods=['POST', 'OPTIONS'])
def create_publish_task():
    """创建发布任务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json()

        # 创建任务
        task = PublishTask(
            content_id=data.get('content_id'),
            content_type=data.get('content_type', 'article'),
            title=data.get('title'),
            content=data.get('content'),
            keywords=data.get('keywords', []),
            images=data.get('images'),
            target_platforms=[PlatformType(p) for p in data.get('platforms', ['website_blog'])],
            status=PublishStatus.PENDING
        )

        task_id = publish_service.create_publish_task(task)

        # 是否立即执行
        if data.get('execute_now', True):
            result = publish_service.execute_publish_task(task_id, images=task.images)
            return jsonify({
                'success': True,
                'task_id': task_id,
                'result': result
            })

        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': '发布任务已创建'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/publish/tasks', methods=['GET', 'OPTIONS'])
def get_publish_tasks():
    """获取发布任务列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        status = request.args.get('status')
        limit = int(request.args.get('limit', 50))

        if status:
            tasks = publish_service.get_tasks(PublishStatus(status), limit)
        else:
            tasks = publish_service.get_tasks(limit=limit)

        return jsonify({
            'success': True,
            'tasks': [{
                'id': t.id,
                'content_id': t.content_id,
                'title': t.title,
                'content_type': t.content_type,
                'status': t.status.value,
                'target_platforms': [p.value for p in t.target_platforms],
                'platform_results': t.platform_results,
                'created_at': t.created_at,
                'published_at': t.published_at,
                'error_message': t.error_message
            } for t in tasks]
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/publish/tasks/<int:task_id>/execute', methods=['POST', 'OPTIONS'])
def execute_publish_task(task_id):
    """执行发布任务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        result = publish_service.execute_publish_task(task_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/publish/quick', methods=['POST', 'OPTIONS'])
def quick_publish_content():
    """快速发布内容"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json()

        result = quick_publish(
            content_id=data.get('content_id', 0),
            title=data.get('title'),
            content=data.get('content'),
            content_type=data.get('content_type', 'article'),
            keywords=data.get('keywords', []),
            platforms=data.get('platforms', ['website_blog']),
            images=data.get('images', [])
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/publish/accounts', methods=['POST', 'OPTIONS'])
@jwt_required()
def add_platform_account():
    """添加平台账号"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        from publish_service import PlatformAccount

        # 获取当前用户
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        data = request.get_json()

        account = PlatformAccount(
            platform=PlatformType(data.get('platform')),
            account_name=data.get('account_name'),
            cookies=data.get('cookies'),
            api_token=data.get('api_token'),
            is_active=data.get('is_active', True),
            daily_limit=data.get('daily_limit', 5)
        )

        publish_service.add_platform_account(account, user['id'])

        return jsonify({
            'success': True,
            'message': '平台账号已添加'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/ai-tasks/<int:task_id>/publish-xiaohongshu', methods=['POST', 'OPTIONS'])
@jwt_required()
def publish_xiaohongshu_task(task_id):
    """执行小红书任务：生成内容并自动发布"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        # 执行小红书任务
        result = ai_task_manager.execute_xiaohongshu_task(task_id, user['id'])
        
        return jsonify(result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/ai-tasks/<int:task_id>/publish', methods=['POST', 'OPTIONS'])
@jwt_required()
def publish_ai_task_result(task_id):
    """发布AI任务结果到各平台"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        # 获取AI任务结果
        task = generation_repo.get_ai_task_by_id(task_id)
        if not task:
            return jsonify({'success': False, 'error': '任务不存在'}), 404
        
        # 验证任务属于当前用户（管理员跳过权限检查）
        if task.get('user_id') != user['id'] and user.get('username') != 'admin':
            return jsonify({'success': False, 'message': '无权访问此任务'}), 403

        # 获取输出数据
        output_data = task.get('output_data', {})
        if not output_data:
            return jsonify({'success': False, 'error': '任务尚未完成'}), 400
        
        # 获取生成的内容（支持多种字段名：content、generated_content、prompt）
        generated_content = output_data.get('content', '') or output_data.get('generated_content', '')
        
        # 如果没有生成内容，但有prompt，则使用prompt作为内容（适用于schema/faq类型）
        if not generated_content and output_data.get('prompt'):
            generated_content = output_data.get('prompt', '')
            # 添加提示说明这是AI提示词
            generated_content = f"<!-- 此内容由GEO系统生成的AI提示词创建 -->\n\n{generated_content}"
        
        if not generated_content:
            return jsonify({'success': False, 'error': '没有可发布的内容'}), 400

        data = request.get_json()
        platforms = data.get('platforms', ['website_blog'])
        images = data.get('images', [])  # 获取图片

        # 检查是否包含小红书但没有图片（现在支持AI自动生成，只记录日志）
        if 'xiaohongshu' in platforms and (not images or len(images) == 0):
            logger.info("AI任务发布到小红书：用户未上传图片，将使用AI自动生成")

        # 创建发布任务
        publish_task = PublishTask(
            content_id=task_id,
            content_type=task.get('task_type', 'article'),
            title=task.get('title', ''),
            content=generated_content,
            keywords=task.get('input_data', {}).get('keywords', []),
            user_id=user['id'],  # 传入用户ID
            target_platforms=[PlatformType(p) for p in platforms],
            status=PublishStatus.PENDING
        )

        publish_task_id = publish_service.create_publish_task(publish_task)
        result = publish_service.execute_publish_task(publish_task_id, user['id'], images)

        # 根据实际发布结果设置 success
        all_success = result.get('success', False)
        results = result.get('results', {})

        # 检查是否有平台成功
        has_success = any(r.get('success', False) for r in results.values())

        if all_success:
            message = '内容已成功发布到所有平台'
        elif has_success:
            message = '内容已发布到部分平台'
        else:
            message = '发布失败，请检查平台配置'

        return jsonify({
            'success': has_success,  # 只要有平台成功就返回 success: true
            'message': message,
            'publish_result': result
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 效果监控API ====================

@app.route('/api/monitoring/search-rank/check', methods=['POST', 'OPTIONS'])
def check_search_rank():
    """检查搜索排名"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json()
        keyword = data.get('keyword')
        search_engine = data.get('search_engine', 'baidu')

        if not keyword:
            return jsonify({'success': False, 'error': '请提供关键词'}), 400

        results = monitoring_service.check_search_rank(
            keyword,
            SearchEngine(search_engine)
        )

        return jsonify({
            'success': True,
            'keyword': keyword,
            'search_engine': search_engine,
            'results': results
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/monitoring/search-rank/history', methods=['GET', 'OPTIONS'])
def get_search_rank_history():
    """获取搜索排名历史"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        keyword = request.args.get('keyword')
        days = int(request.args.get('days', 30))

        if not keyword:
            return jsonify({'success': False, 'error': '请提供关键词'}), 400

        history = monitoring_service.get_rank_history(keyword, days)

        return jsonify({
            'success': True,
            'keyword': keyword,
            'history': history
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/monitoring/ai-citation/check', methods=['POST', 'OPTIONS'])
def check_ai_citation():
    """检查AI引用"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json()
        platform = data.get('platform')
        query = data.get('query')
        brand_name = data.get('brand_name', '织然家具')

        if not platform or not query:
            return jsonify({'success': False, 'error': '请提供平台和查询内容'}), 400

        result = monitoring_service.check_ai_citation(
            AIPlatform(platform),
            query,
            brand_name
        )

        return jsonify({
            'success': True,
            'platform': platform,
            'query': query,
            'result': result
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/monitoring/ai-citation/stats', methods=['GET', 'OPTIONS'])
def get_ai_citation_stats():
    """获取AI引用统计"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        days = int(request.args.get('days', 30))
        stats = monitoring_service.get_citation_stats(days)

        return jsonify({
            'success': True,
            'stats': stats
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== AI 引用批量检测 API ====================

@app.route('/api/monitoring/ai-citation/batch-check', methods=['POST', 'OPTIONS'])
def batch_check_ai_citation():
    """批量检测 AI 引用率（同步等待结果）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json() or {}
        keywords = data.get('keywords')  # 不传则用数据库中所有 active 关键词
        platforms = data.get('platforms', ['chatgpt'])
        brand_name = data.get('brand_name', '织然家具')
        batch_name = data.get('batch_name')

        # 限制单次最多 20 个关键词 × 3 个平台，防止超时
        if keywords:
            keywords = keywords[:20]
        platforms = platforms[:3]

        result = monitoring_service.batch_check_citation(
            keywords=keywords,
            platforms=platforms,
            brand_name=brand_name,
            batch_name=batch_name
        )

        return jsonify(result)

    except Exception as e:
        import traceback
        logger.error(f"[BatchCheck] 批量检测失败: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/monitoring/ai-citation/batches', methods=['GET', 'OPTIONS'])
def list_citation_batches():
    """获取批量检测历史"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        limit = int(request.args.get('limit', 20))
        batches = monitoring_service.get_citation_batches(limit)
        return jsonify({'success': True, 'batches': batches})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/monitoring/ai-citation/trend', methods=['GET', 'OPTIONS'])
def get_citation_trend():
    """获取引用率趋势"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        days = int(request.args.get('days', 30))
        trend = monitoring_service.get_citation_trend(days)
        return jsonify({'success': True, 'trend': trend})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 检测关键词管理 API ====================

@app.route('/api/monitoring/citation-keywords', methods=['GET', 'OPTIONS'])
def list_citation_keywords():
    """获取检测关键词列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        only_active = request.args.get('all') != '1'
        keywords = monitoring_service.list_citation_keywords(only_active)
        return jsonify({'success': True, 'keywords': keywords, 'total': len(keywords)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/monitoring/citation-keywords', methods=['POST', 'OPTIONS'])
def add_citation_keyword():
    """添加检测关键词（支持单个或批量）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json() or {}
        brand_name = data.get('brand_name')
        category = data.get('category')

        # 支持单个 keyword 或 keywords 数组
        if 'keywords' in data and isinstance(data['keywords'], list):
            result = monitoring_service.add_citation_keywords_batch(
                data['keywords'], brand_name, category
            )
        elif 'keyword' in data:
            result = monitoring_service.add_citation_keyword(
                data['keyword'], brand_name, category
            )
        else:
            return jsonify({'success': False, 'error': '请提供 keyword 或 keywords'}), 400

        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/monitoring/citation-keywords/<int:keyword_id>', methods=['DELETE', 'OPTIONS'])
def delete_citation_keyword(keyword_id):
    """删除检测关键词"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        result = monitoring_service.delete_citation_keyword(keyword_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/monitoring/ai-citation/test', methods=['POST', 'OPTIONS'])
def test_ai_citation_query():
    """测试 AI 引用查询（用于验证 API 配置是否正确）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json() or {}
        platform = data.get('platform', 'chatgpt')
        query = data.get('query', '你好，请简单介绍一下定制家具品牌')
        brand_name = data.get('brand_name', '织然家具')

        # 直接调用 _query_via_openai_compatible 测试
        from monitoring_service import AIPlatform
        platform_enum = AIPlatform(platform)
        response_text = monitoring_service._query_via_openai_compatible(platform_enum, query)

        mentioned = brand_name in response_text
        return jsonify({
            'success': True,
            'platform': platform,
            'query': query,
            'response_preview': response_text[:500],
            'response_length': len(response_text),
            'brand_mentioned': mentioned,
            'brand_name': brand_name
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/monitoring/ai-citation/scheduler', methods=['GET', 'OPTIONS'])
def get_scheduler_status():
    """获取定时调度器状态"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    return jsonify({
        'success': True,
        'running': ai_citation_scheduler.running,
        'enabled': ai_citation_scheduler.enabled,
        'brand_name': ai_citation_scheduler.brand_name,
        'platforms': ai_citation_scheduler.platforms
    })


@app.route('/api/monitoring/ai-citation/scheduler', methods=['POST', 'OPTIONS'])
def update_scheduler_config():
    """更新定时调度器配置"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json() or {}
        ai_citation_scheduler.update_config(
            brand_name=data.get('brand_name'),
            platforms=data.get('platforms'),
            enabled=data.get('enabled')
        )
        return jsonify({'success': True, 'message': '配置已更新'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/monitoring/ai-citation/scheduler/run-now', methods=['POST', 'OPTIONS'])
def run_scheduler_now():
    """立即执行一次定时检测（手动触发）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        result = ai_citation_scheduler._run_batch_check_return()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/monitoring/traffic/record', methods=['POST', 'OPTIONS'])
def record_traffic():
    """记录流量数据"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        from monitoring_service import TrafficRecord

        data = request.get_json()

        record = TrafficRecord(
            source=data.get('source', 'direct'),
            medium=data.get('medium', ''),
            campaign=data.get('campaign', ''),
            visitors=data.get('visitors', 0),
            pageviews=data.get('pageviews', 0),
            bounce_rate=data.get('bounce_rate', 0),
            avg_duration=data.get('avg_duration', 0),
            conversions=data.get('conversions', 0),
            recorded_at=datetime.now()
        )

        monitoring_service.record_traffic(record)

        return jsonify({
            'success': True,
            'message': '流量数据已记录'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/monitoring/traffic/summary', methods=['GET', 'OPTIONS'])
def get_traffic_summary():
    """获取流量汇总"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        days = int(request.args.get('days', 30))
        summary = monitoring_service.get_traffic_summary(days)

        return jsonify({
            'success': True,
            'summary': summary
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 工作流引擎 API ====================

@app.route('/api/workflow/stages', methods=['GET', 'OPTIONS'])
def get_workflow_stages():
    """获取工作流所有阶段定义"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    return jsonify({
        'success': True,
        'stages': WORKFLOW_STAGES,
        'total': len(WORKFLOW_STAGES)
    })


@app.route('/api/workflow/start', methods=['POST', 'OPTIONS'])
def start_workflow():
    """启动一个新的工作流（一键启动闭环）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json() or {}
        brand_name = data.get('brand_name', '织然家具')
        industry = data.get('industry', '定制家具')
        keywords = data.get('keywords', [])
        platforms = data.get('platforms', ['website_blog'])
        auto_run = data.get('auto_run', True)

        # 获取当前用户 token 传递给内部调用
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None

        result = workflow_engine.start_workflow(
            brand_name=brand_name, industry=industry,
            keywords=keywords, platforms=platforms,
            token=token, auto_run=auto_run
        )
        return jsonify(result)
    except Exception as e:
        import traceback
        logger.error(f"[Workflow] 启动失败: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/workflow/<wf_id>/status', methods=['GET', 'OPTIONS'])
def get_workflow_status(wf_id):
    """获取工作流执行状态"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    return jsonify(workflow_engine.get_status(wf_id))


@app.route('/api/workflow/list', methods=['GET', 'OPTIONS'])
def list_workflows():
    """列出所有工作流"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    limit = int(request.args.get('limit', 20))
    return jsonify(workflow_engine.list_workflows(limit))


@app.route('/api/workflow/<wf_id>/stage/<stage_id>/execute', methods=['POST', 'OPTIONS'])
def execute_workflow_stage(wf_id, stage_id):
    """手动执行工作流的单个阶段"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None

        result = workflow_engine.execute_stage(wf_id, stage_id, token)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/workflow/<wf_id>/resume', methods=['POST', 'OPTIONS'])
def resume_workflow(wf_id):
    """恢复暂停或失败的工作流"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None

        result = workflow_engine.resume_workflow(wf_id, token)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/monitoring/report', methods=['GET', 'OPTIONS'])
def generate_monitoring_report():
    """生成综合监控报告"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        days = int(request.args.get('days', 30))
        report = monitoring_service.generate_report(days)

        return jsonify({
            'success': True,
            'report': report
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/monitoring/dashboard', methods=['GET', 'OPTIONS'])
def get_monitoring_dashboard():
    """获取监控仪表板数据"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        days = int(request.args.get('days', 7))

        # 获取各项数据
        citation_stats = monitoring_service.get_citation_stats(days)
        traffic_summary = monitoring_service.get_traffic_summary(days)

        # 关键词排名概览
        keywords = ['织然家具', '定制家具', '全屋定制']
        rank_summary = []
        for keyword in keywords:
            latest = monitoring_service.get_latest_ranks(keyword)
            if latest:
                rank_summary.append({
                    'keyword': keyword,
                    'latest_rank': latest[0]['rank'],
                    'change': latest[0]['change']
                })

        return jsonify({
            'success': True,
            'dashboard': {
                'period': f'{days}天',
                'ai_citation': citation_stats,
                'traffic': traffic_summary,
                'search_rank': rank_summary
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== AI平台服务 ====================

from ai_platform_service import ai_platform_service, AIPlatform

@app.route('/api/ai-platforms', methods=['GET', 'OPTIONS'])
def get_ai_platforms():
    """获取所有可用的AI平台列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        platforms = ai_platform_service.get_available_platforms()
        return jsonify({
            'success': True,
            'platforms': platforms
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/ai-platforms/generate', methods=['POST', 'OPTIONS'])
def generate_with_platform():
    """使用指定AI平台生成内容"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        platform_id = data.get('platform', 'doubao')
        prompt = data.get('prompt', '')
        system_prompt = data.get('system_prompt')
        
        if not prompt:
            return jsonify({
                'success': False,
                'error': '提示词不能为空'
            }), 400
        
        platform = AIPlatform(platform_id)
        result = ai_platform_service.generate_with_platform(
            platform, prompt, system_prompt
        )
        
        return jsonify({
            'success': result.success,
            'content': result.content,
            'platform': result.platform,
            'response_time': result.response_time,
            'error': result.error
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 内容模板服务 ====================

from content_template_service import content_template_service, TemplateType

@app.route('/api/templates', methods=['GET', 'OPTIONS'])
def get_content_templates():
    """获取内容模板列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        template_type = request.args.get('type')
        industry = request.args.get('industry')
        
        if template_type:
            templates = content_template_service.get_templates_by_type(
                TemplateType(template_type)
            )
            templates_data = [{
                'id': t.id,
                'name': t.name,
                'type': t.type.value,
                'description': t.description,
                'tags': t.tags,
                'min_length': t.min_length,
                'max_length': t.max_length
            } for t in templates]
        elif industry:
            templates = content_template_service.get_templates_by_industry(industry)
            templates_data = [{
                'id': t.id,
                'name': t.name,
                'type': t.type.value,
                'description': t.description
            } for t in templates]
        else:
            templates_data = content_template_service.get_all_templates()
        
        return jsonify({
            'success': True,
            'templates': templates_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/templates/<template_id>', methods=['GET', 'OPTIONS'])
def get_template_detail(template_id):
    """获取模板详情"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        template = content_template_service.get_template(template_id)
        if not template:
            return jsonify({
                'success': False,
                'error': '模板不存在'
            }), 404
        
        return jsonify({
            'success': True,
            'template': {
                'id': template.id,
                'name': template.name,
                'type': template.type.value,
                'description': template.description,
                'structure': template.structure,
                'example': template.example,
                'tags': template.tags,
                'industry': template.industry,
                'tone': template.tone.value,
                'min_length': template.min_length,
                'max_length': template.max_length,
                'seo_keywords': template.seo_keywords,
                'schema_type': template.schema_type
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/templates/<template_id>/generate-prompt', methods=['POST', 'OPTIONS'])
def generate_template_prompt(template_id):
    """根据模板生成AI提示词"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        variables = data.get('variables', {})
        
        prompt = content_template_service.generate_prompt(template_id, variables)
        
        return jsonify({
            'success': True,
            'prompt': prompt
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 品牌诊断服务 ====================

from brand_diagnosis_service import brand_diagnosis_service

@app.route('/api/brand-diagnosis', methods=['POST', 'OPTIONS'])
def run_brand_diagnosis():
    """运行品牌诊断"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        brand_name = data.get('brand_name')
        website = data.get('website')
        industry = data.get('industry')
        keywords = data.get('keywords', [])
        
        if not brand_name:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        report = brand_diagnosis_service.run_full_diagnosis(
            brand_name=brand_name,
            website=website,
            industry=industry,
            keywords=keywords
        )
        
        return jsonify({
            'success': True,
            'report': {
                'id': report.id,
                'brand_name': report.brand_name,
                'website': report.website,
                'industry': report.industry,
                'overall_score': report.overall_score,
                'scores': {
                    'ai_visibility': report.ai_visibility_score,
                    'search': report.search_score,
                    'content': report.content_score,
                    'sentiment': report.sentiment_score,
                    'competitive': report.competitive_score
                },
                'diagnosis_items': [
                    {
                        'dimension': item.dimension,
                        'name': item.name,
                        'score': item.score,
                        'status': item.status,
                        'findings': item.findings,
                        'recommendations': item.recommendations,
                        'risk_level': item.risk_level
                    }
                    for item in report.diagnosis_items
                ],
                'blind_spots': report.blind_spots,
                'risk_areas': report.risk_areas,
                'opportunities': report.opportunities,
                'action_plan': report.action_plan,
                'created_at': report.created_at.isoformat()
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/brand-diagnosis/history', methods=['GET', 'OPTIONS'])
def get_brand_diagnosis_history():
    """获取品牌诊断历史"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        brand_name = request.args.get('brand_name')
        limit = int(request.args.get('limit', 10))
        
        if not brand_name:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        history = brand_diagnosis_service.get_report_history(brand_name, limit)
        
        return jsonify({
            'success': True,
            'history': history
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/brand-diagnosis/trend', methods=['GET', 'OPTIONS'])
def get_brand_diagnosis_trend():
    """获取得分趋势"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        brand_name = request.args.get('brand_name')
        days = int(request.args.get('days', 30))
        
        if not brand_name:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        trend = brand_diagnosis_service.get_score_trend(brand_name, days)
        
        return jsonify({
            'success': True,
            'trend': trend
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========== 媒体矩阵管理API ==========

@app.route('/api/media-platforms', methods=['GET', 'OPTIONS'])
def get_all_media_platforms():
    """获取所有媒体发布平台"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        category = request.args.get('category')
        
        if category:
            platforms = publish_service.get_platforms_by_category(category)
        else:
            platforms = publish_service.get_all_platforms()
        
        # 按分类组织
        categories = {}
        for p in platforms:
            cat = p.get('category', '其他')
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(p)
        
        return jsonify({
            'success': True,
            'platforms': platforms,
            'categories': categories,
            'total': len(platforms)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/media-platforms/<platform_id>', methods=['GET', 'OPTIONS'])
def get_media_platform_detail(platform_id):
    """获取媒体平台详情"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        from publish_service import PlatformType
        platform_type = PlatformType(platform_id)
        config = publish_service.get_platform_info(platform_type)
        
        if not config:
            return jsonify({
                'success': False,
                'error': '平台不存在'
            }), 404
        
        # 检查是否已配置
        account = publish_service.get_platform_account(platform_type)
        
        return jsonify({
            'success': True,
            'platform': {
                'id': platform_id,
                'configured': account is not None,
                **config
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/media-platforms/categories', methods=['GET', 'OPTIONS'])
def get_media_platform_categories():
    """获取媒体平台分类"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        categories = {
            "自媒体": "内容创作与传播平台",
            "官网": "品牌自有平台",
            "技术社区": "IT开发者社区",
            "综合门户": "新闻资讯门户",
            "垂直媒体": "行业垂直平台",
            "问答社区": "问答互动平台",
            "海外平台": "国际内容平台"
        }
        
        return jsonify({
            'success': True,
            'categories': categories
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/media-platforms/recommend', methods=['POST', 'OPTIONS'])
def recommend_media_platforms():
    """智能推荐发布平台"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        content_type = data.get('content_type', 'article')
        industry = data.get('industry', 'general')
        target_audience = data.get('target_audience', [])
        
        # 平台推荐策略
        recommendations = []
        
        # 所有内容都推荐官网
        recommendations.append({
            'platform': 'website_blog',
            'name': '官网博客',
            'priority': 'high',
            'reason': '品牌自有阵地，SEO权重最高'
        })
        
        # 根据内容类型推荐
        if content_type == 'article':
            recommendations.extend([
                {'platform': 'zhihu', 'name': '知乎', 'priority': 'high', 'reason': '深度内容适合知乎用户'},
                {'platform': 'baijiahao', 'name': '百家号', 'priority': 'high', 'reason': '百度搜索权重高'},
                {'platform': 'toutiao', 'name': '今日头条', 'priority': 'medium', 'reason': '流量大，推荐算法强'},
            ])
        elif content_type == 'short':
            recommendations.extend([
                {'platform': 'xiaohongshu', 'name': '小红书', 'priority': 'high', 'reason': '种草内容首选'},
                {'platform': 'weibo', 'name': '微博', 'priority': 'medium', 'reason': '适合话题传播'},
            ])
        elif content_type == 'faq':
            recommendations.append({
                'platform': 'website_faq',
                'name': '官网FAQ',
                'priority': 'high',
                'reason': '直接服务用户查询'
            })
        
        # 根据行业推荐
        if industry == '家居':
            recommendations.extend([
                {'platform': 'xiaohongshu', 'name': '小红书', 'priority': 'high', 'reason': '家居种草核心平台'},
                {'platform': 'tubatu', 'name': '土巴兔', 'priority': 'medium', 'reason': '家装垂直平台'},
            ])
        elif industry == '科技':
            recommendations.extend([
                {'platform': 'csdn', 'name': 'CSDN', 'priority': 'medium', 'reason': '技术人员聚集'},
                {'platform': 'juejin', 'name': '掘金', 'priority': 'medium', 'reason': '开发者社区'},
            ])
        
        # 根据目标受众推荐
        if '年轻用户' in target_audience:
            recommendations.append({
                'platform': 'bilibili',
                'name': '哔哩哔哩',
                'priority': 'medium',
                'reason': '年轻用户聚集地'
            })
        
        return jsonify({
            'success': True,
            'recommendations': recommendations,
            'content_type': content_type,
            'industry': industry
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========== 舆情监控API ==========

from sentiment_monitor_service import sentiment_monitor_service, SentimentType, SourceType, AlertLevel

@app.route('/api/sentiment/brands', methods=['GET', 'OPTIONS'])
def get_monitored_brands():
    """获取监控品牌列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        brands = sentiment_monitor_service.get_monitored_brands()
        return jsonify({
            'success': True,
            'brands': brands
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sentiment/brands', methods=['POST', 'OPTIONS'])
def add_monitored_brand():
    """添加监控品牌"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        brand_name = data.get('brand_name')
        keywords = data.get('keywords', [brand_name])
        alert_threshold = data.get('alert_threshold', -0.5)
        
        if not brand_name:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        sentiment_monitor_service.add_monitored_brand(
            brand_name=brand_name,
            keywords=keywords,
            alert_threshold=alert_threshold
        )
        
        return jsonify({
            'success': True,
            'message': f'已添加品牌 {brand_name} 到监控列表'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sentiment/items', methods=['GET', 'OPTIONS'])
def get_sentiment_items():
    """获取舆情列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        brand_name = request.args.get('brand_name')
        sentiment = request.args.get('sentiment')
        source = request.args.get('source')
        days = int(request.args.get('days', 7))
        limit = int(request.args.get('limit', 100))
        
        sentiment_type = SentimentType(sentiment) if sentiment else None
        source_type = SourceType(source) if source else None
        
        items = sentiment_monitor_service.get_sentiment_items(
            brand_name=brand_name,
            sentiment=sentiment_type,
            source=source_type,
            days=days,
            limit=limit
        )
        
        return jsonify({
            'success': True,
            'items': [
                {
                    'id': item.id,
                    'brand_name': item.brand_name,
                    'source': item.source.value,
                    'source_name': item.source_name,
                    'title': item.title,
                    'content': item.content,
                    'url': item.url,
                    'sentiment': item.sentiment.value,
                    'sentiment_score': item.sentiment_score,
                    'keywords': item.keywords,
                    'author': item.author,
                    'publish_time': item.publish_time.isoformat() if item.publish_time else None,
                    'engagement': item.engagement,
                    'is_read': item.is_read,
                    'is_alert': item.is_alert
                }
                for item in items
            ],
            'total': len(items)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sentiment/stats', methods=['GET', 'OPTIONS'])
def get_sentiment_stats():
    """获取舆情统计"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        brand_name = request.args.get('brand_name')
        days = int(request.args.get('days', 7))
        
        if not brand_name:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        stats = sentiment_monitor_service.get_sentiment_stats(brand_name, days)
        
        return jsonify({
            'success': True,
            'stats': {
                'brand_name': stats.brand_name,
                'total_count': stats.total_count,
                'positive_count': stats.positive_count,
                'neutral_count': stats.neutral_count,
                'negative_count': stats.negative_count,
                'critical_count': stats.critical_count,
                'sentiment_score': stats.sentiment_score,
                'trend': stats.trend,
                'hot_topics': stats.hot_topics,
                'risk_keywords': stats.risk_keywords,
                'positive_rate': round(stats.positive_count / stats.total_count * 100, 2) if stats.total_count > 0 else 0,
                'negative_rate': round((stats.negative_count + stats.critical_count) / stats.total_count * 100, 2) if stats.total_count > 0 else 0
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sentiment/trend', methods=['GET', 'OPTIONS'])
def get_sentiment_trend():
    """获取舆情趋势"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        brand_name = request.args.get('brand_name')
        days = int(request.args.get('days', 30))
        
        if not brand_name:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        trend = sentiment_monitor_service.get_sentiment_trend(brand_name, days)
        
        return jsonify({
            'success': True,
            'trend': trend
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sentiment/alerts', methods=['GET', 'OPTIONS'])
def get_sentiment_alerts():
    """获取舆情预警"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        brand_name = request.args.get('brand_name')
        level = request.args.get('level')
        is_resolved = request.args.get('is_resolved', 'false').lower() == 'true'
        
        alert_level = AlertLevel(level) if level else None
        
        alerts = sentiment_monitor_service.get_alerts(
            brand_name=brand_name,
            level=alert_level,
            is_resolved=is_resolved
        )
        
        return jsonify({
            'success': True,
            'alerts': [
                {
                    'id': alert.id,
                    'brand_name': alert.brand_name,
                    'alert_level': alert.alert_level.value,
                    'alert_type': alert.alert_type,
                    'title': alert.title,
                    'description': alert.description,
                    'related_items': alert.related_items,
                    'created_at': alert.created_at.isoformat() if alert.created_at else None,
                    'is_resolved': alert.is_resolved
                }
                for alert in alerts
            ],
            'total': len(alerts)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sentiment/crawl', methods=['POST', 'OPTIONS'])
def crawl_sentiment():
    """手动触发舆情爬取"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        brand_name = data.get('brand_name')
        keywords = data.get('keywords')
        days = int(data.get('days', 7))
        
        if not brand_name:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        items = sentiment_monitor_service.crawl_sentiment_data(
            brand_name=brand_name,
            keywords=keywords,
            days=days
        )
        
        # 检查预警
        alerts = sentiment_monitor_service.check_alerts(brand_name)
        
        return jsonify({
            'success': True,
            'message': f'成功爬取 {len(items)} 条舆情数据',
            'crawled_count': len(items),
            'alerts_count': len(alerts),
            'alerts': [
                {
                    'id': alert.id,
                    'level': alert.alert_level.value,
                    'title': alert.title,
                    'description': alert.description
                }
                for alert in alerts
            ]
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sentiment/sources', methods=['GET', 'OPTIONS'])
def get_sentiment_sources():
    """获取舆情来源列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        sources = [
            {'id': 'news', 'name': '新闻', 'icon': '📰'},
            {'id': 'weibo', 'name': '微博', 'icon': '📢'},
            {'id': 'zhihu', 'name': '知乎', 'icon': '📚'},
            {'id': 'xiaohongshu', 'name': '小红书', 'icon': '📕'},
            {'id': 'douyin', 'name': '抖音', 'icon': '🎵'},
            {'id': 'forum', 'name': '论坛', 'icon': '💬'},
            {'id': 'comment', 'name': '评论', 'icon': '💭'},
            {'id': 'qa', 'name': '问答', 'icon': '❓'},
            {'id': 'video', 'name': '视频', 'icon': '📺'}
        ]
        
        return jsonify({
            'success': True,
            'sources': sources
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========== 竞品分析API ==========

from competitor_analysis_service import competitor_analysis_service, CompetitorStatus

@app.route('/api/competitors', methods=['GET', 'OPTIONS'])
def get_competitors():
    """获取竞品列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        status = request.args.get('status')
        status_enum = CompetitorStatus(status) if status else None
        
        competitors = competitor_analysis_service.get_competitors(status_enum)
        
        return jsonify({
            'success': True,
            'competitors': [
                {
                    'id': c.id,
                    'brand_name': c.brand_name,
                    'website': c.website,
                    'industry': c.industry,
                    'description': c.description,
                    'keywords': c.keywords,
                    'status': c.status.value,
                    'created_at': c.created_at.isoformat() if c.created_at else None,
                    'last_analyzed_at': c.last_analyzed_at.isoformat() if c.last_analyzed_at else None
                }
                for c in competitors
            ]
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/competitors', methods=['POST', 'OPTIONS'])
def add_competitor():
    """添加竞品"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        brand_name = data.get('brand_name')
        website = data.get('website')
        industry = data.get('industry')
        description = data.get('description')
        keywords = data.get('keywords')
        
        if not brand_name:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        competitor = competitor_analysis_service.add_competitor(
            brand_name=brand_name,
            website=website,
            industry=industry,
            description=description,
            keywords=keywords
        )
        
        return jsonify({
            'success': True,
            'message': f'已添加竞品: {brand_name}',
            'competitor': {
                'id': competitor.id,
                'brand_name': competitor.brand_name,
                'status': competitor.status.value
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/competitors/<competitor_id>/analyze', methods=['POST', 'OPTIONS'])
def analyze_competitor(competitor_id):
    """分析竞品"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        result = competitor_analysis_service.analyze_competitor(competitor_id)
        
        if 'error' in result:
            return jsonify({
                'success': False,
                'error': result['error']
            }), 404
        
        return jsonify({
            'success': True,
            'result': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/competitors/compare', methods=['POST', 'OPTIONS'])
def compare_with_competitor():
    """与竞品对比"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        my_brand = data.get('my_brand')
        competitor_id = data.get('competitor_id')
        
        if not my_brand or not competitor_id:
            return jsonify({
                'success': False,
                'error': '品牌名称和竞品ID不能为空'
            }), 400
        
        report = competitor_analysis_service.compare_with_competitor(
            my_brand=my_brand,
            competitor_id=competitor_id
        )
        
        return jsonify({
            'success': True,
            'report': {
                'id': report.id,
                'my_brand': report.my_brand,
                'competitor_id': report.competitor_id,
                'my_overall_score': report.my_overall_score,
                'competitor_overall_score': report.competitor_overall_score,
                'overall_gap': report.overall_score,
                'comparison_results': [
                    {
                        'dimension': r.dimension,
                        'my_score': r.my_score,
                        'competitor_score': r.competitor_score,
                        'difference': r.difference,
                        'winner': r.winner,
                        'gap_analysis': r.gap_analysis,
                        'recommendations': r.recommendations
                    }
                    for r in report.comparison_results
                ],
                'swot': {
                    'strengths': report.strengths,
                    'weaknesses': report.weaknesses,
                    'opportunities': report.opportunities,
                    'threats': report.threats
                },
                'action_plan': report.action_plan,
                'created_at': report.created_at.isoformat()
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/competitors/comparison-history', methods=['GET', 'OPTIONS'])
def get_comparison_history():
    """获取对比历史"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        my_brand = request.args.get('my_brand')
        competitor_id = request.args.get('competitor_id')
        limit = int(request.args.get('limit', 10))
        
        if not my_brand:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        history = competitor_analysis_service.get_comparison_history(
            my_brand=my_brand,
            competitor_id=competitor_id,
            limit=limit
        )
        
        return jsonify({
            'success': True,
            'history': history
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/competitors/landscape', methods=['GET', 'OPTIONS'])
def get_competitive_landscape():
    """获取竞争格局"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        my_brand = request.args.get('my_brand')
        
        if not my_brand:
            return jsonify({
                'success': False,
                'error': '品牌名称不能为空'
            }), 400
        
        landscape = competitor_analysis_service.get_competitive_landscape(my_brand)
        
        return jsonify({
            'success': True,
            'landscape': landscape
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/competitors/dimensions', methods=['GET', 'OPTIONS'])
def get_comparison_dimensions():
    """获取对比维度"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        dimensions = [
            {'id': 'ai_visibility', 'name': 'AI可见度', 'icon': '🤖', 'description': '品牌在AI平台的被引用情况'},
            {'id': 'search_rank', 'name': '搜索排名', 'icon': '🔍', 'description': '搜索引擎关键词排名表现'},
            {'id': 'content_volume', 'name': '内容产量', 'icon': '📝', 'description': '内容生产频率和数量'},
            {'id': 'social_engagement', 'name': '社交互动', 'icon': '💬', 'description': '社交媒体互动率'},
            {'id': 'brand_mention', 'name': '品牌提及', 'icon': '📢', 'description': '全网品牌提及次数'},
            {'id': 'sentiment', 'name': '舆情情感', 'icon': '😊', 'description': '品牌舆情正负面比例'}
        ]
        
        return jsonify({
            'success': True,
            'dimensions': dimensions
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========== 关键词研究API ==========

from keyword_research_service import keyword_research_service, KeywordIntent, KeywordType

@app.route('/api/keywords/research', methods=['POST', 'OPTIONS'])
def research_keywords():
    """关键词研究"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        seed_keyword = data.get('seed_keyword')
        industry = data.get('industry')
        depth = int(data.get('depth', 2))
        
        if not seed_keyword:
            return jsonify({
                'success': False,
                'error': '种子关键词不能为空'
            }), 400
        
        report = keyword_research_service.research_keywords(
            seed_keyword=seed_keyword,
            industry=industry,
            depth=depth
        )
        
        return jsonify({
            'success': True,
            'report': {
                'id': report.id,
                'seed_keyword': report.seed_keyword,
                'industry': report.industry,
                'total_keywords': len(report.discovered_keywords),
                'keywords': [
                    {
                        'id': k.id,
                        'keyword': k.keyword,
                        'search_volume': k.search_volume,
                        'difficulty': k.difficulty,
                        'cpc': k.cpc,
                        'intent': k.intent.value,
                        'keyword_type': k.keyword_type.value,
                        'questions': k.questions,
                        'opportunity_score': k.opportunity_score,
                        'geo_relevance': k.geo_relevance
                    }
                    for k in report.discovered_keywords[:20]  # 限制返回数量
                ],
                'recommendations': report.recommendations,
                'content_gaps': report.content_gaps,
                'created_at': report.created_at.isoformat()
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/keywords/suggestions', methods=['GET', 'OPTIONS'])
def get_keyword_suggestions():
    """获取关键词建议"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        query = request.args.get('query')
        limit = int(request.args.get('limit', 10))
        
        if not query:
            return jsonify({
                'success': False,
                'error': '查询词不能为空'
            }), 400
        
        suggestions = keyword_research_service.get_keyword_suggestions(query, limit)
        
        return jsonify({
            'success': True,
            'query': query,
            'suggestions': suggestions
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/keywords/geo', methods=['GET', 'OPTIONS'])
def get_geo_keywords():
    """获取GEO优化关键词"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        industry = request.args.get('industry')
        limit = int(request.args.get('limit', 50))
        
        keywords = keyword_research_service.get_geo_keywords(industry, limit)
        
        return jsonify({
            'success': True,
            'keywords': keywords,
            'total': len(keywords)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/keywords/groups', methods=['POST', 'OPTIONS'])
def create_keyword_group():
    """创建关键词分组"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        name = data.get('name')
        description = data.get('description')
        keywords = data.get('keywords', [])
        
        if not name or not keywords:
            return jsonify({
                'success': False,
                'error': '分组名称和关键词不能为空'
            }), 400
        
        group = keyword_research_service.create_keyword_group(
            name=name,
            description=description,
            keywords=keywords
        )
        
        return jsonify({
            'success': True,
            'group': {
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'keywords': group.keywords,
                'total_volume': group.total_volume,
                'avg_difficulty': group.avg_difficulty
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/keywords/intents', methods=['GET', 'OPTIONS'])
def get_keyword_intents():
    """获取关键词意图类型"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        intents = [
            {'id': 'informational', 'name': '信息型', 'description': '用户寻求信息，如"什么是..."、"怎么样"'},
            {'id': 'navigational', 'name': '导航型', 'description': '用户寻找特定网站或页面'},
            {'id': 'commercial', 'name': '商业型', 'description': '用户比较产品，如"哪个好"、"推荐"'},
            {'id': 'transactional', 'name': '交易型', 'description': '用户准备购买，如"价格"、"购买"'}
        ]
        
        return jsonify({
            'success': True,
            'intents': intents
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========== 内容日历API ==========

from content_calendar_service import content_calendar_service, ContentStatus, ContentPriority, ContentType

@app.route('/api/calendar/items', methods=['GET', 'OPTIONS'])
def get_calendar_items():
    """获取内容项列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        status = request.args.get('status')
        content_type = request.args.get('type')
        priority = request.args.get('priority')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # 转换参数
        status_enum = ContentStatus(status) if status else None
        type_enum = ContentType(content_type) if content_type else None
        priority_enum = ContentPriority(priority) if priority else None
        
        start_dt = datetime.fromisoformat(start_date) if start_date else None
        end_dt = datetime.fromisoformat(end_date) if end_date else None
        
        items = content_calendar_service.get_content_items(
            status=status_enum,
            content_type=type_enum,
            priority=priority_enum,
            start_date=start_dt,
            end_date=end_dt
        )
        
        return jsonify({
            'success': True,
            'items': [
                {
                    'id': item.id,
                    'title': item.title,
                    'content_type': item.content_type.value,
                    'description': item.description,
                    'keywords': item.keywords,
                    'target_platforms': item.target_platforms,
                    'status': item.status.value,
                    'priority': item.priority.value,
                    'assigned_to': item.assigned_to,
                    'planned_date': item.planned_date.isoformat() if item.planned_date else None,
                    'publish_date': item.publish_date.isoformat() if item.publish_date else None,
                    'geo_optimized': item.geo_optimized
                }
                for item in items
            ],
            'total': len(items)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calendar/items', methods=['POST', 'OPTIONS'])
def create_calendar_item():
    """创建内容项"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        title = data.get('title')
        content_type = data.get('type', 'article')
        description = data.get('description')
        keywords = data.get('keywords', [])
        platforms = data.get('platforms', [])
        priority = data.get('priority', 'medium')
        assigned_to = data.get('assigned_to')
        planned_date = data.get('planned_date')
        geo_optimized = data.get('geo_optimized', False)
        
        if not title:
            return jsonify({
                'success': False,
                'error': '标题不能为空'
            }), 400
        
        planned_dt = datetime.fromisoformat(planned_date) if planned_date else None
        
        item = content_calendar_service.create_content_item(
            title=title,
            content_type=ContentType(content_type),
            description=description,
            keywords=keywords,
            target_platforms=platforms,
            priority=ContentPriority(priority),
            assigned_to=assigned_to,
            planned_date=planned_dt,
            geo_optimized=geo_optimized
        )
        
        return jsonify({
            'success': True,
            'message': '内容项创建成功',
            'item': {
                'id': item.id,
                'title': item.title,
                'status': item.status.value,
                'planned_date': item.planned_date.isoformat()
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calendar/items/<item_id>/status', methods=['PUT', 'OPTIONS'])
def update_content_item_status(item_id):
    """更新内容项状态"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        status = data.get('status')
        notes = data.get('notes')
        
        if not status:
            return jsonify({
                'success': False,
                'error': '状态不能为空'
            }), 400
        
        item = content_calendar_service.update_content_status(
            content_id=item_id,
            status=ContentStatus(status),
            notes=notes
        )
        
        if not item:
            return jsonify({
                'success': False,
                'error': '内容项不存在'
            }), 404
        
        return jsonify({
            'success': True,
            'message': '状态更新成功',
            'item': {
                'id': item.id,
                'title': item.title,
                'status': item.status.value
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calendar/view', methods=['GET', 'OPTIONS'])
def get_calendar_view():
    """获取日历视图"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        year = int(request.args.get('year', datetime.now().year))
        month = int(request.args.get('month', datetime.now().month))
        
        calendar_view = content_calendar_service.get_calendar_view(year, month)
        
        return jsonify({
            'success': True,
            'calendar': calendar_view
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calendar/weekly', methods=['GET', 'OPTIONS'])
def get_weekly_plan():
    """获取周计划"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        date_str = request.args.get('date')
        start_date = datetime.fromisoformat(date_str) if date_str else None
        
        weekly_plan = content_calendar_service.get_weekly_plan(start_date)
        
        return jsonify({
            'success': True,
            'weekly_plan': weekly_plan
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calendar/stats', methods=['GET', 'OPTIONS'])
def get_calendar_stats():
    """获取内容统计"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        stats = content_calendar_service.get_content_stats()
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calendar/auto-schedule', methods=['POST', 'OPTIONS'])
def auto_schedule_content():
    """自动排期内容"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        items = data.get('items', [])
        start_date = data.get('start_date')
        frequency = data.get('frequency', 'weekly')
        
        if not items:
            return jsonify({
                'success': False,
                'error': '内容项不能为空'
            }), 400
        
        start_dt = datetime.fromisoformat(start_date) if start_date else None
        
        scheduled_items = content_calendar_service.auto_schedule_content(
            content_items=items,
            start_date=start_dt,
            frequency=frequency
        )
        
        return jsonify({
            'success': True,
            'message': f'成功排期 {len(scheduled_items)} 个内容项',
            'items': [
                {
                    'id': item.id,
                    'title': item.title,
                    'planned_date': item.planned_date.isoformat()
                }
                for item in scheduled_items
            ]
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calendar/upcoming', methods=['GET', 'OPTIONS'])
def get_upcoming_content():
    """获取即将到期的内容"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        days = int(request.args.get('days', 7))
        
        items = content_calendar_service.get_upcoming_content(days)
        
        return jsonify({
            'success': True,
            'items': [
                {
                    'id': item.id,
                    'title': item.title,
                    'planned_date': item.planned_date.isoformat(),
                    'priority': item.priority.value,
                    'days_left': (item.planned_date - datetime.now()).days
                }
                for item in items
            ],
            'total': len(items)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calendar/types', methods=['GET', 'OPTIONS'])
def get_content_types():
    """获取内容类型"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        types = [
            {'id': 'article', 'name': '文章', 'icon': '📝'},
            {'id': 'video', 'name': '视频', 'icon': '🎥'},
            {'id': 'faq', 'name': 'FAQ', 'icon': '❓'},
            {'id': 'guide', 'name': '指南', 'icon': '📚'},
            {'id': 'case_study', 'name': '案例', 'icon': '💼'},
            {'id': 'news', 'name': '新闻', 'icon': '📰'},
            {'id': 'comparison', 'name': '对比', 'icon': '⚖️'},
            {'id': 'review', 'name': '评测', 'icon': '⭐'}
        ]
        
        return jsonify({
            'success': True,
            'types': types
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calendar/statuses', methods=['GET', 'OPTIONS'])
def get_content_statuses():
    """获取内容状态"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        statuses = [
            {'id': 'draft', 'name': '草稿', 'color': '#9E9E9E'},
            {'id': 'planned', 'name': '已计划', 'color': '#2196F3'},
            {'id': 'in_progress', 'name': '进行中', 'color': '#FF9800'},
            {'id': 'review', 'name': '审核中', 'color': '#9C27B0'},
            {'id': 'scheduled', 'name': '已排期', 'color': '#4CAF50'},
            {'id': 'published', 'name': '已发布', 'color': '#00BCD4'},
            {'id': 'cancelled', 'name': '已取消', 'color': '#F44336'}
        ]
        
        return jsonify({
            'success': True,
            'statuses': statuses
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========== 主动发布API ==========

from active_publish_service import (
    active_publish_service,
    ActivePublishTask,
    ActiveTaskStatus
)


def _active_task_user_check(task: ActivePublishTask, user):
    """校验任务归属"""
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    if task.user_id != user['id'] and user.get('username') != 'admin':
        return jsonify({'success': False, 'message': '无权访问此任务'}), 403
    return None


@app.route('/api/active-publish/tasks', methods=['POST', 'OPTIONS'])
@jwt_required()
def create_active_publish_task():
    """创建主动发布任务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        data = request.get_json() or {}
        topic = (data.get('topic') or '').strip()
        if not topic:
            return jsonify({'success': False, 'error': '主题（topic）不能为空'}), 400

        task = ActivePublishTask(
            user_id=user['id'],
            topic=topic,
            keywords=data.get('keywords', []) or [],
            brand_name=data.get('brand_name', ''),
            industry=data.get('industry', ''),
            domain=data.get('domain', ''),
            target_platforms=data.get('target_platforms', ['website_blog']) or ['website_blog'],
            word_count=int(data.get('word_count', 1500)),
            status=ActiveTaskStatus.PENDING.value
        )

        created = active_publish_service.create_task(task)
        if not created:
            return jsonify({'success': False, 'error': '任务创建失败'}), 500

        return jsonify({
            'success': True,
            'message': '主动发布任务已创建',
            'task': _format_active_task(created)
        }), 201
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/active-publish/tasks', methods=['GET', 'OPTIONS'])
@jwt_required()
def list_active_publish_tasks():
    """获取主动发布任务列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        status = request.args.get('status')
        limit = int(request.args.get('limit', 50))

        tasks = active_publish_service.get_user_tasks(user['id'], status=status, limit=limit)
        return jsonify({
            'success': True,
            'tasks': [_format_active_task(t) for t in tasks],
            'total': len(tasks)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/active-publish/tasks/<int:task_id>', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_active_publish_task(task_id):
    """获取任务详情"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        task = active_publish_service.get_task(task_id)
        err = _active_task_user_check(task, user)
        if err:
            return err
        return jsonify({'success': True, 'task': _format_active_task(task)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/active-publish/tasks/<int:task_id>/execute', methods=['POST', 'OPTIONS'])
@jwt_required()
def execute_active_publish_task(task_id):
    """执行主动发布任务：生成内容→生成图片→多平台发布"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        task = active_publish_service.get_task(task_id)
        err = _active_task_user_check(task, user)
        if err:
            return err

        result = active_publish_service.execute_task(task_id)
        return jsonify(result), 200 if result.get('success') else 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/active-publish/tasks/<int:task_id>/cancel', methods=['POST', 'OPTIONS'])
@jwt_required()
def cancel_active_publish_task(task_id):
    """取消主动发布任务"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        task = active_publish_service.get_task(task_id)
        err = _active_task_user_check(task, user)
        if err:
            return err

        updated = active_publish_service.cancel_task(task_id)
        return jsonify({
            'success': True,
            'message': '任务已取消',
            'task': _format_active_task(updated) if updated else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/active-publish/stats', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_active_publish_stats():
    """获取主动发布统计"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        stats = active_publish_service.get_stats(user['id'])
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/active-publish/statuses', methods=['GET', 'OPTIONS'])
def get_active_publish_statuses():
    """获取主动发布任务状态列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        statuses = [
            {'id': 'pending', 'name': '待执行', 'color': '#9E9E9E'},
            {'id': 'generating', 'name': '生成内容中', 'color': '#2196F3'},
            {'id': 'generating_images', 'name': '生成图片中', 'color': '#9C27B0'},
            {'id': 'publishing', 'name': '发布中', 'color': '#FF9800'},
            {'id': 'success', 'name': '全部成功', 'color': '#00BCD4'},
            {'id': 'partial', 'name': '部分成功', 'color': '#4CAF50'},
            {'id': 'failed', 'name': '失败', 'color': '#F44336'},
            {'id': 'cancelled', 'name': '已取消', 'color': '#607D8B'}
        ]
        return jsonify({'success': True, 'statuses': statuses})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _format_active_task(task: ActivePublishTask) -> Dict:
    """格式化任务为前端字典"""
    return {
        'id': task.id,
        'user_id': task.user_id,
        'topic': task.topic,
        'title': task.title,
        'content': task.content,
        'content_preview': (task.content[:200] + '...') if len(task.content) > 200 else task.content,
        'keywords': task.keywords,
        'brand_name': task.brand_name,
        'industry': task.industry,
        'domain': task.domain,
        'target_platforms': task.target_platforms,
        'word_count': task.word_count,
        'images': task.images,
        'image_count': len(task.images) if task.images else 0,
        'status': task.status,
        'publish_task_id': task.publish_task_id,
        'platform_results': task.platform_results,
        'error_message': task.error_message,
        'created_at': task.created_at.isoformat() if task.created_at else None,
        'updated_at': task.updated_at.isoformat() if task.updated_at else None,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None
    }


# ========== 数据分析与可视化API ==========

from analytics_service import analytics_service, MetricType, TimeRange

# 初始化平台账号服务 - 使用PostgreSQL数据库
# 优先使用PostgreSQL，如果不成功则回退到SQLite
try:
    from platform_account_postgres import PlatformAccountServicePostgres
    platform_account_service = PlatformAccountServicePostgres()
    print("✅ 平台账号服务使用PostgreSQL数据库")
except Exception as e:
    print(f"⚠️ PostgreSQL平台账号服务初始化失败，使用SQLite: {e}")
    from platform_account_service import PlatformAccountService
    DB_PATH = os.environ.get('DB_PATH', '/app/data/publish.db')
    platform_account_service = PlatformAccountService(db_path=DB_PATH)

# platform_account_service 就绪后，初始化小红书认证管理器和 Cookie 自动刷新器
_init_xhs_auth()

@app.route('/api/analytics/dashboard', methods=['GET', 'OPTIONS'])
def get_analytics_dashboard():
    """获取仪表盘数据"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        dashboard_data = analytics_service.get_dashboard_data()
        
        return jsonify({
            'success': True,
            'data': dashboard_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analytics/geo-performance', methods=['GET', 'OPTIONS'])
def get_geo_performance():
    """获取GEO效果报表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        time_range = request.args.get('range', 'month')
        range_enum = TimeRange(time_range)
        
        report = analytics_service.get_geo_performance_report(range_enum)
        
        return jsonify({
            'success': True,
            'report': report
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analytics/content-performance', methods=['GET', 'OPTIONS'])
def get_content_performance():
    """获取内容表现报表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        content_id = request.args.get('content_id')
        
        report = analytics_service.get_content_performance_report(content_id)
        
        return jsonify({
            'success': True,
            'report': report
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analytics/trends', methods=['GET', 'OPTIONS'])
def get_trend_analysis():
    """获取趋势分析"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        metric = request.args.get('metric', 'impression')
        granularity = request.args.get('granularity', 'daily')
        days = int(request.args.get('days', 30))
        
        metric_enum = MetricType(metric)
        
        analysis = analytics_service.get_trend_analysis(
            metric_type=metric_enum,
            granularity=granularity,
            days=days
        )
        
        return jsonify({
            'success': True,
            'analysis': analysis
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analytics/comparison', methods=['POST', 'OPTIONS'])
def get_platform_comparison():
    """获取平台对比分析"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        platforms = data.get('platforms', [])
        metrics = data.get('metrics', ['impression', 'click', 'ctr'])
        
        if not platforms:
            return jsonify({
                'success': False,
                'error': '请至少选择一个平台'
            }), 400
        
        metric_enums = [MetricType(m) for m in metrics]
        
        comparison = analytics_service.get_comparison_report(
            platforms=platforms,
            metrics=metric_enums
        )
        
        return jsonify({
            'success': True,
            'comparison': comparison
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analytics/metrics', methods=['POST', 'OPTIONS'])
def record_metric():
    """记录指标数据"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        metric_type = data.get('type')
        value = data.get('value')
        platform = data.get('platform')
        keyword = data.get('keyword')
        content_id = data.get('content_id')
        
        if not metric_type or value is None:
            return jsonify({
                'success': False,
                'error': '指标类型和值不能为空'
            }), 400
        
        metric = analytics_service.record_metric(
            metric_type=MetricType(metric_type),
            value=float(value),
            platform=platform,
            keyword=keyword,
            content_id=content_id
        )
        
        return jsonify({
            'success': True,
            'message': '指标记录成功',
            'metric': {
                'type': metric.metric_type.value,
                'value': metric.value,
                'date': metric.date.isoformat()
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analytics/reports', methods=['GET', 'OPTIONS'])
def get_analytics_reports():
    """获取报表列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        report_type = request.args.get('type')
        
        reports = analytics_service.get_reports(report_type)
        
        return jsonify({
            'success': True,
            'reports': reports
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analytics/reports', methods=['POST', 'OPTIONS'])
def create_analytics_report():
    """创建报表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        name = data.get('name')
        report_type = data.get('type')
        report_data = data.get('data', {})
        date_range = data.get('date_range')
        
        if not name or not report_type:
            return jsonify({
                'success': False,
                'error': '报表名称和类型不能为空'
            }), 400
        
        report = analytics_service.create_report(
            name=name,
            report_type=report_type,
            data=report_data,
            date_range=date_range
        )
        
        return jsonify({
            'success': True,
            'message': '报表创建成功',
            'report': {
                'id': report.id,
                'name': report.name,
                'type': report.report_type,
                'created_at': report.created_at.isoformat()
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analytics/metric-types', methods=['GET', 'OPTIONS'])
def get_metric_types():
    """获取指标类型列表"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        types = [
            {'id': 'impression', 'name': '展现量', 'unit': '次'},
            {'id': 'click', 'name': '点击量', 'unit': '次'},
            {'id': 'ctr', 'name': '点击率', 'unit': '%'},
            {'id': 'rank', 'name': '排名', 'unit': '位'},
            {'id': 'citation', 'name': '引用次数', 'unit': '次'},
            {'id': 'conversion', 'name': '转化率', 'unit': '%'},
            {'id': 'engagement', 'name': '互动率', 'unit': '%'}
        ]
        
        return jsonify({
            'success': True,
            'types': types
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analytics/time-ranges', methods=['GET', 'OPTIONS'])
def get_time_ranges():
    """获取时间范围选项"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        ranges = [
            {'id': 'today', 'name': '今日'},
            {'id': 'yesterday', 'name': '昨日'},
            {'id': 'week', 'name': '最近7天'},
            {'id': 'month', 'name': '最近30天'},
            {'id': 'quarter', 'name': '最近90天'},
            {'id': 'year', 'name': '最近365天'}
        ]
        
        return jsonify({
            'success': True,
            'ranges': ranges
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 平台账号管理 ====================

@app.route('/api/platform-accounts', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_platform_accounts():
    """获取用户的所有平台账号"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        print(f"[DEBUG] 获取平台账号 - user_id: {user['id']}")
        
        accounts = platform_account_service.get_user_accounts(user['id'])
        print(f"[DEBUG] 用户账号列表: {accounts}")
        
        # 获取所有支持的平台
        all_platforms = PlatformLoginHelper.get_all_platforms()
        
        # 合并账号状态
        platform_status = []
        for platform in all_platforms:
            account = next((a for a in accounts if a['platform'] == platform['id']), None)
            status = platform_account_service.check_account_status(user['id'], platform['id'])
            print(f"[DEBUG] 平台 {platform['id']}: account={account is not None}, status={status}")
            platform_status.append({
                **platform,
                'account': account,
                'status': status
            })
        
        return jsonify({
            'success': True,
            'data': platform_status
        })
    except Exception as e:
        import traceback
        print(f"[ERROR] 获取平台账号失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/platform-accounts/<platform>/guide', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_platform_login_guide(platform):
    """获取平台登录指导"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        guide = PlatformLoginHelper.get_login_guide(platform)
        return jsonify({
            'success': True,
            'data': guide
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/platform-accounts/<platform>', methods=['POST', 'OPTIONS'])
@jwt_required()
def save_platform_account(platform):
    """保存平台账号"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        data = request.get_json()
        print(f"[DEBUG] 保存平台账号 - user_id: {user['id']}, platform: {platform}")
        print(f"[DEBUG] 请求数据: {data}")
        
        account_data = {
            'account_name': data.get('account_name'),
            'cookies': data.get('cookies'),
            'api_token': data.get('api_token'),
            'refresh_token': data.get('refresh_token'),
            'status': 'active',
            'is_active': True,
            'last_login_time': datetime.now()
        }
        
        result = platform_account_service.save_account(user['id'], platform, account_data)
        print(f"[DEBUG] 保存结果: {result}")
        
        return jsonify(result)
    except Exception as e:
        import traceback
        print(f"[ERROR] 保存平台账号失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/platform-accounts/<platform>', methods=['DELETE', 'OPTIONS'])
@jwt_required()
def delete_platform_account(platform):
    """删除平台账号"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        result = platform_account_service.delete_account(user['id'], platform)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/platform-accounts/<platform>/status', methods=['GET', 'OPTIONS'])
@jwt_required()
def check_platform_account_status(platform):
    """检查平台账号状态"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        status = platform_account_service.check_account_status(user['id'], platform)
        return jsonify({
            'success': True,
            'data': status
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/platform-accounts/<platform>/cookies', methods=['PUT', 'OPTIONS'])
@jwt_required()
def update_platform_cookies(platform):
    """更新平台Cookie"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        
        data = request.get_json()
        cookies = data.get('cookies')
        expires_at = data.get('expires_at')
        
        if not cookies:
            return jsonify({
                'success': False,
                'error': 'Cookie不能为空'
            }), 400
        
        result = platform_account_service.update_cookies(
            user['id'], 
            platform, 
            cookies,
            datetime.fromisoformat(expires_at) if expires_at else None
        )
        
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ==================== 小红书二维码登录 API ====================

@app.route('/api/platform-accounts/xiaohongshu/qr-login', methods=['POST', 'OPTIONS'])
@jwt_required()
def start_xiaohongshu_qr_login():
    """开始小红书二维码登录"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        import uuid
        session_id = str(uuid.uuid4())

        # 使用全局事件循环运行异步函数（确保 start_qr_login 和 _check_login_status 在同一循环）
        from xiaohongshu_qr_login import run_async
        result = run_async(qr_login_manager.start_qr_login(session_id), timeout=120)

        return jsonify(result)
    except Exception as e:
        import traceback
        print(f"二维码登录启动失败: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': f'启动二维码登录失败: {str(e)}'
        }), 500


@app.route('/api/platform-accounts/xiaohongshu/qr-login/<session_id>/status', methods=['GET', 'OPTIONS'])
@jwt_required()
def check_xiaohongshu_qr_status(session_id):
    """检查小红书二维码登录状态"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        from xiaohongshu_qr_login import run_async
        result = run_async(qr_login_manager.get_login_status(session_id), timeout=10)

        # 如果登录成功，保存 Cookie 到数据库 + storage_state 到用户目录
        if result.get('success') and result.get('status') == 'success':
            current_user = get_jwt_identity()
            user = user_repo.get_user_by_username(current_user)
            if user:
                # 将 cookies 列表转换为 JSON 字符串
                import json
                cookies_str = json.dumps(result['cookies']) if isinstance(result['cookies'], list) else result['cookies']
                platform_account_service.update_cookies(
                    user['id'],
                    'xiaohongshu',
                    cookies_str,
                    datetime.now() + timedelta(days=7)  # 默认7天有效期
                )

                # === 新增：将临时 storage_state 移动到 user_id 对应的正式路径 ===
                try:
                    import os as _os
                    state_dir = _os.environ.get('XHS_STATE_DIR', '/app/data/xhs_state')
                    tmp_path = _os.path.join(state_dir, f'_session_{session_id}.json')
                    final_path = _os.path.join(state_dir, f'user_{user["id"]}.json')
                    if _os.path.exists(tmp_path):
                        _os.replace(tmp_path, final_path)
                        logger.info(f"[QRLogin] storage_state 已移动到 {final_path}")
                except Exception as e:
                    logger.error(f"[QRLogin] 移动 storage_state 失败: {e}")

                # 标记账号状态为 active
                try:
                    with postgres_db.get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "UPDATE platform_accounts SET status='active', updated_at=CURRENT_TIMESTAMP WHERE platform='xiaohongshu' AND user_id=%s",
                            (user['id'],)
                        )
                        conn.commit()
                except Exception as e:
                    logger.error(f"[QRLogin] 更新账号状态失败: {e}")

        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/platform-accounts/xiaohongshu/qr-login/<session_id>/cancel', methods=['POST', 'OPTIONS'])
@jwt_required()
def cancel_xiaohongshu_qr_login(session_id):
    """取消小红书二维码登录"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        from xiaohongshu_qr_login import run_async
        result = run_async(qr_login_manager.cancel_login(session_id), timeout=15)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/platform-accounts/xiaohongshu/qr-login/<session_id>/verify', methods=['POST', 'OPTIONS'])
@jwt_required()
def submit_xiaohongshu_verification_code(session_id):
    """提交小红书登录短信验证码"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    try:
        data = request.get_json() or {}
        code = (data.get('code') or '').strip()
        if not code:
            return jsonify({'success': False, 'error': '验证码不能为空'}), 400

        from xiaohongshu_qr_login import run_async
        result = run_async(qr_login_manager.submit_verification_code(session_id, code), timeout=30)
        return jsonify(result)
    except Exception as e:
        logger.error(f"[QRLogin] 提交验证码接口异常: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/platform-accounts/xiaohongshu/cookie-status', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_xiaohongshu_cookie_status():
    """获取小红书 Cookie 状态（剩余有效期、是否含 access-token 等）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404
        from xhs_auth_manager import xhs_auth_manager as _xhs_mgr
        if not _xhs_mgr:
            return jsonify({'success': False, 'error': '认证管理器未初始化'}), 500
        status = _xhs_mgr.get_account_status(user['id'])
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/platform-accounts/xiaohongshu/refresh-cookie', methods=['POST', 'OPTIONS'])
@jwt_required()
def refresh_xiaohongshu_cookie():
    """手动触发小红书 Cookie 刷新"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        import asyncio
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404
        from xhs_auth_manager import xhs_auth_manager as _xhs_mgr
        if not _xhs_mgr:
            return jsonify({'success': False, 'error': '认证管理器未初始化'}), 500
        success, msg = asyncio.run(_xhs_mgr.refresh_cookie(user['id']))
        return jsonify({
            'success': success,
            'message': msg,
            'status': _xhs_mgr.get_account_status(user['id'])
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/platform-accounts/xiaohongshu/check-cookie', methods=['POST', 'OPTIONS'])
@jwt_required()
def check_xiaohongshu_cookie():
    """检测小红书 Cookie 是否有效（不刷新）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        import asyncio
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404
        from xhs_auth_manager import xhs_auth_manager as _xhs_mgr
        if not _xhs_mgr:
            return jsonify({'success': False, 'error': '认证管理器未初始化'}), 500
        # 获取 cookie
        with postgres_db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT cookies FROM platform_accounts WHERE platform='xiaohongshu' AND user_id=%s",
                (user['id'],)
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return jsonify({'success': False, 'error': '未配置小红书账号'}), 400
        valid, msg = asyncio.run(_xhs_mgr.check_cookie_valid(user['id'], row[0]))
        return jsonify({
            'success': True,
            'valid': valid,
            'message': msg,
            'status': _xhs_mgr.get_account_status(user['id'])
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# 通用多平台扫码登录 API（知乎/微博/B站/抖音）
# 通过 platform 路径参数区分平台
# ============================================================

# 平台 -> (qr_login_module, key_cookie_name, automation_module, automation_class_name)
_PLATFORM_QR_MODULES = {
    'zhihu':    ('zhihu_qr_login',    'z_c0',       'zhihu_automation',    'ZhihuAutomation'),
    'weibo':    ('weibo_qr_login',    'SUB',        'weibo_automation',    'WeiboAutomation'),
    'bilibili': ('bilibili_qr_login', 'SESSDATA',   'bilibili_automation', 'BilibiliAutomation'),
    'douyin':   ('douyin_qr_login',   'sessionid',  'douyin_automation',   'DouyinAutomation'),
}


def _get_platform_qr_manager(platform: str):
    """获取平台的扫码登录管理器单例"""
    if platform not in _PLATFORM_QR_MODULES:
        return None, None, None
    qr_module_name, key_cookie, _, _ = _PLATFORM_QR_MODULES[platform]
    try:
        import importlib
        mod = importlib.import_module(qr_module_name)
        # 单例命名规则：<platform>_qr_login_manager
        manager_attr = f"{platform}_qr_login_manager"
        manager = getattr(mod, manager_attr, None)
        return manager, key_cookie, mod
    except Exception as e:
        logger.error(f"[PlatformQR] 加载平台 {platform} 模块失败: {e}")
        return None, None, None


@app.route('/api/platform-accounts/<platform>/qr-login', methods=['POST', 'OPTIONS'])
@jwt_required()
def start_platform_qr_login(platform):
    """启动平台扫码登录（支持 zhihu/weibo/bilibili/douyin）"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    if platform not in _PLATFORM_QR_MODULES:
        return jsonify({'success': False, 'error': f'不支持的平台: {platform}'}), 400

    try:
        import uuid
        session_id = str(uuid.uuid4())

        manager, _, mod = _get_platform_qr_manager(platform)
        if not manager:
            return jsonify({'success': False, 'error': f'{platform} 登录管理器未初始化'}), 500

        # 在调用前记录 user_id（用于 storage_state 文件命名）
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        # 把 user_id 注入到 session 中（在 start_qr_login 完成后通过 mod.login_sessions 设置）
        result = mod.run_async(manager.start_qr_login(session_id), timeout=120)

        # 把 user_id 关联到 session，用于 storage_state 保存路径
        if result.get('success') and session_id in mod.login_sessions:
            mod.login_sessions[session_id]['user_id'] = user['id']

        return jsonify(result)
    except Exception as e:
        import traceback
        logger.error(f"[{platform}] 二维码登录启动失败: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'启动登录失败: {str(e)}'}), 500


@app.route('/api/platform-accounts/<platform>/qr-login/<session_id>/status', methods=['GET', 'OPTIONS'])
@jwt_required()
def check_platform_qr_status(platform, session_id):
    """检查平台扫码登录状态"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    if platform not in _PLATFORM_QR_MODULES:
        return jsonify({'success': False, 'error': f'不支持的平台: {platform}'}), 400

    try:
        manager, _, mod = _get_platform_qr_manager(platform)
        if not manager:
            return jsonify({'success': False, 'error': f'{platform} 登录管理器未初始化'}), 500

        result = manager.get_login_status(session_id)

        # 登录成功：保存 cookies 到数据库
        if result.get('success') and result.get('status') == 'success':
            current_user = get_jwt_identity()
            user = user_repo.get_user_by_username(current_user)
            if user:
                import json
                cookies = result.get('cookies', [])
                cookies_str = json.dumps(cookies) if isinstance(cookies, list) else cookies

                # 更新数据库 cookies 和状态
                try:
                    with postgres_db.get_connection() as conn:
                        cur = conn.cursor()
                        # 先查是否已有账号
                        cur.execute(
                            "SELECT id FROM platform_accounts WHERE platform=%s AND user_id=%s",
                            (platform, user['id'])
                        )
                        existing = cur.fetchone()
                        if existing:
                            cur.execute(
                                "UPDATE platform_accounts SET cookies=%s, status='active', last_login_time=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE platform=%s AND user_id=%s",
                                (cookies_str, platform, user['id'])
                            )
                        else:
                            cur.execute(
                                "INSERT INTO platform_accounts (user_id, platform, account_name, cookies, status, last_login_time, created_at, updated_at) VALUES (%s, %s, %s, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                                (user['id'], platform, f'{platform}_user', cookies_str)
                            )
                        conn.commit()
                    logger.info(f"[{platform}] 用户 {user['id']} Cookie 已保存（{len(cookies)} 个）")
                except Exception as e:
                    logger.error(f"[{platform}] 保存 Cookie 到数据库失败: {e}")

                # 移动 storage_state 临时文件到 user_id 命名（如果有的话）
                try:
                    state_path = result.get('state_path')
                    if state_path and os.path.exists(state_path):
                        # 已经是 user_id 命名（_state_path 在 _check_login_status 中已用 user_id），无需移动
                        logger.info(f"[{platform}] storage_state 已保存: {state_path}")
                except Exception as e:
                    logger.error(f"[{platform}] storage_state 处理失败: {e}")

        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/platform-accounts/<platform>/qr-login/<session_id>/cancel', methods=['POST', 'OPTIONS'])
@jwt_required()
def cancel_platform_qr_login(platform, session_id):
    """取消平台扫码登录"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    if platform not in _PLATFORM_QR_MODULES:
        return jsonify({'success': False, 'error': f'不支持的平台: {platform}'}), 400

    try:
        manager, _, mod = _get_platform_qr_manager(platform)
        if not manager:
            return jsonify({'success': False, 'error': f'{platform} 登录管理器未初始化'}), 500

        result = mod.run_async(manager.cancel_login(session_id), timeout=15)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/platform-accounts/<platform>/qr-login/<session_id>/verify', methods=['POST', 'OPTIONS'])
@jwt_required()
def submit_platform_verification_code(platform, session_id):
    """提交平台登录验证码"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    if platform not in _PLATFORM_QR_MODULES:
        return jsonify({'success': False, 'error': f'不支持的平台: {platform}'}), 400

    try:
        data = request.get_json() or {}
        code = (data.get('code') or '').strip()
        if not code:
            return jsonify({'success': False, 'error': '验证码不能为空'}), 400

        manager, _, mod = _get_platform_qr_manager(platform)
        if not manager:
            return jsonify({'success': False, 'error': f'{platform} 登录管理器未初始化'}), 500

        result = mod.run_async(manager.submit_verification_code(session_id, code), timeout=30)
        return jsonify(result)
    except Exception as e:
        logger.error(f"[{platform}] 提交验证码接口异常: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/platform-accounts/<platform>/cookie-status', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_platform_cookie_status(platform):
    """获取平台 Cookie 状态"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    if platform not in _PLATFORM_QR_MODULES:
        return jsonify({'success': False, 'error': f'不支持的平台: {platform}'}), 400

    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        _, key_cookie, _, _ = _PLATFORM_QR_MODULES[platform]

        # 从数据库获取 cookies
        with postgres_db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT cookies, status, last_login_time FROM platform_accounts WHERE platform=%s AND user_id=%s",
                (platform, user['id'])
            )
            row = cur.fetchone()

        if not row or not row[0]:
            return jsonify({
                'success': True,
                'status': {
                    'configured': False,
                    'account_status': 'not_configured',
                    'has_key_cookie': False,
                    'cookie_count': 0,
                    'has_storage_state': False,
                    'last_login': None
                }
            })

        cookies_str, account_status, last_login = row
        import json
        try:
            cl = json.loads(cookies_str) if isinstance(cookies_str, str) else cookies_str
        except Exception:
            cl = []

        cookie_count = len(cl) if isinstance(cl, list) else 0
        names = [c.get('name', '') for c in cl] if isinstance(cl, list) else []
        has_key = any(key_cookie in n for n in names)

        # 检查 storage_state 文件
        state_dir = os.environ.get('PLATFORM_STATE_DIR', '/app/data/platform_state')
        state_path = os.path.join(state_dir, f'{platform}_user_{user["id"]}.json')
        has_state = os.path.exists(state_path)

        return jsonify({
            'success': True,
            'status': {
                'configured': True,
                'account_status': account_status or 'unknown',
                'has_key_cookie': has_key,
                'key_cookie_name': key_cookie,
                'cookie_count': cookie_count,
                'has_storage_state': has_state,
                'last_login': last_login.isoformat() if last_login else None
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/platform-accounts/<platform>/publish', methods=['POST', 'OPTIONS'])
@jwt_required()
def publish_to_platform(platform):
    """发布内容到指定平台"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200

    if platform not in _PLATFORM_QR_MODULES:
        return jsonify({'success': False, 'error': f'不支持的平台: {platform}'}), 400

    try:
        data = request.get_json() or {}
        title = data.get('title', '')
        content = data.get('content', '')
        image_path = data.get('image_path')
        image_paths = data.get('image_paths', [])
        topic = data.get('topic')
        task_id = data.get('task_id')

        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        # 如果传了 task_id，从 AI 任务中获取标题和内容
        if task_id:
            try:
                task = generation_repo.get_ai_task_by_id(task_id)
                if not task:
                    return jsonify({'success': False, 'error': 'AI任务不存在'}), 404
                # 权限校验（管理员跳过）
                if task.get('user_id') != user['id'] and user.get('username') != 'admin':
                    return jsonify({'success': False, 'error': '无权访问此任务'}), 403

                # 从任务输出中提取内容
                output_data = task.get('output_data', {}) or {}
                if not content:
                    content = output_data.get('content', '') or output_data.get('generated_content', '')
                    if not content and output_data.get('prompt'):
                        content = output_data.get('prompt', '')
                if not title:
                    title = task.get('title', '')
                if not topic and task.get('input_data', {}).get('keywords'):
                    topic = task['input_data']['keywords'][0]
            except Exception as e:
                logger.warning(f"[{platform}] 加载AI任务 {task_id} 失败: {e}")

        if not content and not title:
            return jsonify({'success': False, 'error': '标题和内容不能同时为空（可传 task_id 或 title/content）'}), 400

        # 获取 cookies
        with postgres_db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT cookies FROM platform_accounts WHERE platform=%s AND user_id=%s",
                (platform, user['id'])
            )
            row = cur.fetchone()

        if not row or not row[0]:
            return jsonify({'success': False, 'error': f'未配置{platform}账号，请先扫码登录'}), 400

        cookies_str = row[0]

        # 加载对应的自动化模块
        _, _, auto_module_name, auto_class_name = _PLATFORM_QR_MODULES[platform]
        import importlib
        try:
            auto_mod = importlib.import_module(auto_module_name)
        except Exception as e:
            return jsonify({'success': False, 'error': f'加载{platform}发布模块失败: {e}'}), 500

        # 实例化发布器（传入 user_id 以加载 storage_state）
        AutoCls = getattr(auto_mod, auto_class_name)
        automation = AutoCls(cookies_str, user_id=user['id'])

        # 根据平台调用对应的发布方法
        import asyncio
        if platform == 'weibo':
            result = asyncio.run(automation.publish_post(
                content=content,
                image_paths=image_paths,
                title=title
            ))
        elif platform == 'douyin':
            # 抖音图文必须上传至少1张图；没有图时尝试用 AI 生成
            all_images = list(image_paths)
            if image_path:
                all_images.append(image_path)
            if not all_images:
                try:
                    from image_generation_service import image_service
                    logger.info(f"[douyin] 没有图片，正在使用AI生成...")
                    generated = image_service.generate_xiaohongshu_images(
                        title=title,
                        content=content,
                        keywords=[topic] if topic else [],
                        count=3
                    )
                    if generated:
                        import tempfile, base64
                        for img_b64 in generated:
                            if ',' in img_b64:
                                img_b64 = img_b64.split(',')[1]
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as f:
                                f.write(base64.b64decode(img_b64))
                                all_images.append(f.name)
                        logger.info(f"[douyin] AI 生成了 {len(all_images)} 张图片")
                except Exception as e:
                    logger.warning(f"[douyin] AI 图片生成失败: {e}")
            if not all_images:
                return jsonify({'success': False, 'error': '抖音发布必须包含至少1张图片（AI生成失败）'}), 400
            result = asyncio.run(automation.publish_post(
                content=content,
                image_paths=all_images,
                title=title
            ))
        else:
            # zhihu, bilibili: publish_article
            result = asyncio.run(automation.publish_article(
                title=title,
                content=content,
                image_path=image_path,
                topic=topic
            ))

        return jsonify(result)
    except Exception as e:
        import traceback
        logger.error(f"[{platform}] 发布失败: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'发布失败: {str(e)}'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print("=" * 50)
    print("GEO系统后端服务启动中...")
    print(f"API地址: http://localhost:{port}/api")
    print(f"文档地址: http://localhost:{port}/api/health")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=True)
