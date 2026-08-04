"""
GEO系统后端API服务（真实数据版本）
使用Flask构建，提供完整的RESTful API
集成SQLite数据库，支持真实数据存储
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
from datetime import datetime, timedelta
import json
import os
import sys
from functools import wraps

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 导入核心模块
from core.content_generator import GEOArticleGenerator
from core.content_optimizer import GEOContentOptimizer
from utils.content_analyzer import ContentAnalyzer
from modules.data.metrics_tracker import GEOMetricsTracker, GEOMetrics
from modules.data.roi_calculator import ROICalculator
from modules.source.authority_builder import AuthorityBuilder
from modules.source.platform_distributor import PlatformDistributor
from modules.source.schema_optimizer import SchemaOptimizer
from modules.website_analyzer import GEODiagnostician, WebsiteCrawler

# 导入数据库模块
from database import (
    db, user_repo, generation_repo, analysis_repo,
    optimization_repo, metrics_repo, roi_repo
)

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 'geo-system-secret-key-change-in-production'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# CORS配置
CORS(app, resources={
    r"/api/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

jwt = JWTManager(app)

# 初始化核心组件
content_generator = GEOArticleGenerator()
content_optimizer = GEOContentOptimizer()
content_analyzer = ContentAnalyzer()
metrics_tracker = GEOMetricsTracker()
roi_calculator = ROICalculator()
authority_builder = AuthorityBuilder()
platform_distributor = PlatformDistributor()
schema_optimizer = SchemaOptimizer()
geo_diagnostician = GEODiagnostician()

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


def get_current_user_id():
    """获取当前用户ID"""
    try:
        username = get_jwt_identity()
        if username:
            user = user_repo.get_user_by_username(username)
            if user:
                return user['id']
    except:
        pass
    return None


# ==================== 认证相关 ====================

@app.route('/api/auth/register', methods=['POST'])
def register():
    """用户注册"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        email = data.get('email')
        
        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400
        
        if len(password) < 6:
            return jsonify({'success': False, 'message': '密码长度至少6位'}), 400
        
        result = user_repo.create_user(username, password, email)
        
        if result['success']:
            return jsonify(result), 201
        else:
            return jsonify(result), 400
            
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
        
        result = user_repo.verify_user(username, password)
        
        if result['success']:
            access_token = create_access_token(identity=username)
            return jsonify({
                'success': True,
                'access_token': access_token,
                'username': username,
                'user_id': result['user_id'],
                'message': '登录成功'
            })
        else:
            return jsonify(result), 401
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'登录失败: {str(e)}'}), 500


@app.route('/api/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    """用户登出"""
    return jsonify({'success': True, 'message': '登出成功'})


@app.route('/api/auth/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """获取用户信息"""
    try:
        current_user = get_jwt_identity()
        user = user_repo.get_user_by_username(current_user)
        
        if user:
            return jsonify({
                'success': True,
                'data': {
                    'id': user['id'],
                    'username': user['username'],
                    'email': user['email'],
                    'created_at': user['created_at'],
                    'last_login': user['last_login']
                }
            })
        else:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== 内容生成 ====================

@app.route('/api/content/generate', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
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
            return jsonify({'success': False, 'message': '标题不能为空'}), 400
        
        if not brand_info or not brand_info.get('name'):
            return jsonify({'success': False, 'message': '品牌信息不能为空'}), 400
        
        # 生成内容
        result = content_generator.generate(
            title=title,
            brand_info=brand_info,
            target_platform=target_platform,
            word_count=word_count
        )
        
        # 保存到数据库（如果用户已登录）
        user_id = get_current_user_id()
        if user_id:
            generation_repo.save_generation(
                user_id=user_id,
                title=title,
                brand_name=brand_info.get('name'),
                industry=brand_info.get('industry', ''),
                platform=target_platform,
                word_count=word_count,
                outline=result['outline'],
                prompt=result['prompt']
            )
        
        return jsonify({
            'success': True,
            'data': result,
            'message': '内容生成成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'生成失败: {str(e)}'}), 500


@app.route('/api/content/history', methods=['GET'])
@jwt_required()
def get_generation_history():
    """获取生成历史"""
    try:
        user_id = get_current_user_id()
        limit = request.args.get('limit', 50, type=int)
        
        history = generation_repo.get_user_generations(user_id, limit)
        
        return jsonify({
            'success': True,
            'data': history,
            'message': '获取成功'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/content/analyze', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
def analyze_content():
    """分析内容质量"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        content = data.get('content', '')
        
        if not content or len(content.strip()) < 50:
            return jsonify({'success': False, 'message': '内容不能为空且至少50个字符'}), 400
        
        # 分析内容
        result = content_analyzer.analyze(content)
        
        # 转换为字典
        analysis_result = {
            'overall_score': result.overall_score,
            'structure_score': result.structure_score,
            'citation_score': result.citation_score,
            'readability_score': result.readability_score,
            'authority_score': result.authority_score,
            'geo_compliance': result.geo_compliance,
            'issues': result.issues,
            'suggestions': result.suggestions
        }
        
        # 保存到数据库
        user_id = get_current_user_id()
        if user_id:
            analysis_repo.save_analysis(user_id, content, analysis_result)
        
        return jsonify({
            'success': True,
            'data': analysis_result,
            'message': '分析完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'分析失败: {str(e)}'}), 500


@app.route('/api/content/optimize', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
def optimize_content():
    """优化内容"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        content = data.get('content', '')
        optimization_level = data.get('optimization_level', 'medium')
        
        if not content or len(content.strip()) < 50:
            return jsonify({'success': False, 'message': '内容不能为空且至少50个字符'}), 400
        
        # 优化内容
        result = content_optimizer.optimize(content, optimization_level)
        
        # 转换为字典
        optimization_result = {
            'optimized_content': result.optimized_content,
            'score_before': result.score_before,
            'score_after': result.score_after,
            'improvements': result.improvements
        }
        
        # 保存到数据库
        user_id = get_current_user_id()
        if user_id:
            optimization_repo.save_optimization(
                user_id=user_id,
                original_content=content,
                optimized_content=result.optimized_content,
                level=optimization_level,
                result=optimization_result
            )
        
        return jsonify({
            'success': True,
            'data': optimization_result,
            'message': '优化完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'优化失败: {str(e)}'}), 500


# ==================== 批量处理 ====================

@app.route('/api/content/batch-generate', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
def batch_generate():
    """批量生成内容"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        topics = data.get('topics', [])
        brand_info = data.get('brand_info', {})
        
        if not topics or len(topics) > 10:
            return jsonify({'success': False, 'message': '主题列表不能为空且最多10个'}), 400
        
        results = []
        user_id = get_current_user_id()
        
        for topic in topics:
            try:
                result = content_generator.generate(
                    title=topic.get('title', ''),
                    brand_info=brand_info,
                    target_platform=topic.get('platform', 'chatgpt'),
                    word_count=topic.get('word_count', 3000)
                )
                
                # 分析质量
                content_text = '\n'.join([item['title'] for item in result['outline']])
                analysis = content_analyzer.analyze(content_text)
                
                # 保存到数据库
                if user_id:
                    generation_repo.save_generation(
                        user_id=user_id,
                        title=topic.get('title'),
                        brand_name=brand_info.get('name'),
                        industry=brand_info.get('industry', ''),
                        platform=topic.get('platform', 'chatgpt'),
                        word_count=topic.get('word_count', 3000),
                        outline=result['outline'],
                        prompt=result['prompt']
                    )
                
                results.append({
                    'title': topic.get('title'),
                    'outline': result['outline'],
                    'prompt': result['prompt'],
                    'quality_score': analysis.overall_score,
                    'success': True
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
            'message': f'成功生成 {len(successful)}/{len(results)} 个内容大纲'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'批量生成失败: {str(e)}'}), 500


# ==================== 数据监测 ====================

@app.route('/api/metrics/record', methods=['POST', 'OPTIONS'])
@jwt_required()
def record_metrics():
    """记录指标"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        user_id = get_current_user_id()
        
        metrics = {
            'date': data.get('date', datetime.now().strftime('%Y-%m-%d')),
            'ai_citation_count': data.get('ai_citation_count', 0),
            'brand_mention_count': data.get('brand_mention_count', 0),
            'answer_space_coverage': data.get('answer_space_coverage', 0),
            'source_diversity_score': data.get('source_diversity_score', 0),
            'content_quality_score': data.get('content_quality_score', 0),
            'citations_by_platform': data.get('citations_by_platform', {}),
            'mentions_by_source': data.get('mentions_by_source', {}),
            'top_queries': data.get('top_queries', []),
            'notes': data.get('notes', '')
        }
        
        result = metrics_repo.record_metrics(user_id, metrics)
        
        return jsonify(result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'记录失败: {str(e)}'}), 500


@app.route('/api/metrics/report', methods=['GET'])
@jwt_required()
def get_metrics_report():
    """获取指标报告"""
    try:
        user_id = get_current_user_id()
        report_type = request.args.get('type', 'monthly')
        
        report = metrics_repo.get_metrics_report(user_id, report_type)
        
        return jsonify({
            'success': True,
            'data': report,
            'message': '报告生成成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'报告生成失败: {str(e)}'}), 500


@app.route('/api/metrics/history', methods=['GET'])
@jwt_required()
def get_metrics_history():
    """获取历史指标"""
    try:
        user_id = get_current_user_id()
        days = request.args.get('days', 30, type=int)
        days = min(days, 365)
        
        history = metrics_repo.get_metrics_history(user_id, days)
        
        return jsonify({
            'success': True,
            'data': history,
            'message': '历史数据获取成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'获取历史数据失败: {str(e)}'}), 500


# ==================== ROI计算 ====================

@app.route('/api/roi/calculate', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
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
        
        # 保存到数据库
        user_id = get_current_user_id()
        if user_id:
            roi_repo.save_calculation(user_id, params, result)
        
        return jsonify({
            'success': True,
            'data': result,
            'message': 'ROI计算完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'计算失败: {str(e)}'}), 500


@app.route('/api/roi/history', methods=['GET'])
@jwt_required()
def get_roi_history():
    """获取ROI计算历史"""
    try:
        user_id = get_current_user_id()
        limit = request.args.get('limit', 20, type=int)
        
        history = roi_repo.get_user_calculations(user_id, limit)
        
        return jsonify({
            'success': True,
            'data': history,
            'message': '获取成功'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


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
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'}), 500


@app.route('/api/authority/official-site-plan', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
def get_official_site_plan():
    """获取官网建设方案"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        brand_info = data.get('brand_info', {})
        
        if not brand_info.get('name'):
            return jsonify({'success': False, 'message': '品牌名称不能为空'}), 400
        
        plan = authority_builder.build_official_site_authority(brand_info)
        
        return jsonify({
            'success': True,
            'data': plan,
            'message': '方案生成成功'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'生成失败: {str(e)}'}), 500


# ==================== 域名诊断 ====================

@app.route('/api/website/diagnose', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
def diagnose_website():
    """域名GEO诊断"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        url = data.get('url', '')
        
        if not url:
            return jsonify({'success': False, 'message': '请输入域名或URL'}), 400
        
        # 执行诊断
        result = geo_diagnostician.diagnose(url)
        
        if not result:
            return jsonify({'success': False, 'message': '无法访问该网站，请检查域名是否正确'}), 400
        
        # 保存到数据库
        user_id = get_current_user_id()
        if user_id:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO website_diagnosis 
                    (user_id, domain, url, overall_score, content_score, structure_score, 
                     authority_score, technical_score, issues_count, diagnosis_result)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    result['domain'],
                    result['url'],
                    result['scores']['overall'],
                    result['scores']['content'],
                    result['scores']['structure'],
                    result['scores']['authority'],
                    result['scores']['technical'],
                    len(result['issues']),
                    json.dumps(result, ensure_ascii=False)
                ))
        
        return jsonify({
            'success': True,
            'data': result,
            'message': '诊断完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'诊断失败: {str(e)}'}), 500


@app.route('/api/website/history', methods=['GET'])
@jwt_required()
def get_diagnosis_history():
    """获取诊断历史"""
    try:
        user_id = get_current_user_id()
        limit = request.args.get('limit', 20, type=int)
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, domain, url, overall_score, content_score, structure_score,
                       authority_score, technical_score, issues_count, created_at
                FROM website_diagnosis 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, limit))
            
            rows = cursor.fetchall()
            history = [dict(row) for row in rows]
        
        return jsonify({
            'success': True,
            'data': history,
            'message': '获取成功'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/website/compare', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
def compare_websites():
    """对比多个网站"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    
    try:
        data = request.get_json()
        urls = data.get('urls', [])
        
        if len(urls) < 2:
            return jsonify({'success': False, 'message': '请至少输入两个域名进行对比'}), 400
        
        if len(urls) > 5:
            return jsonify({'success': False, 'message': '最多支持5个域名对比'}), 400
        
        results = []
        for url in urls:
            result = geo_diagnostician.diagnose(url)
            if result:
                results.append(result)
        
        if len(results) < 2:
            return jsonify({'success': False, 'message': '无法获取足够的网站数据进行分析'}), 400
        
        # 生成对比报告
        comparison = {
            'websites': results,
            'ranking': sorted(results, key=lambda x: x['scores']['overall'], reverse=True),
            'best_practices': _extract_best_practices(results),
            'gaps_analysis': _analyze_gaps(results)
        }
        
        return jsonify({
            'success': True,
            'data': comparison,
            'message': '对比分析完成'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'对比失败: {str(e)}'}), 500


def _extract_best_practices(results: List[Dict]) -> List[Dict]:
    """提取最佳实践"""
    practices = []
    
    # 找出各方面得分最高的
    best_content = max(results, key=lambda x: x['scores']['content'])
    best_structure = max(results, key=lambda x: x['scores']['structure'])
    best_authority = max(results, key=lambda x: x['scores']['authority'])
    best_technical = max(results, key=lambda x: x['scores']['technical'])
    
    practices.append({
        'aspect': '内容质量',
        'leader': best_content['domain'],
        'score': best_content['scores']['content'],
        'tip': '参考其内容深度和丰富度'
    })
    
    practices.append({
        'aspect': '结构优化',
        'leader': best_structure['domain'],
        'score': best_structure['scores']['structure'],
        'tip': '学习其标题层级和内部链接策略'
    })
    
    practices.append({
        'aspect': '权威性',
        'leader': best_authority['domain'],
        'score': best_authority['scores']['authority'],
        'tip': '借鉴其Schema标记和社交标签'
    })
    
    practices.append({
        'aspect': '技术性能',
        'leader': best_technical['domain'],
        'score': best_technical['scores']['technical'],
        'tip': '参考其加载速度和SSL配置'
    })
    
    return practices


def _analyze_gaps(results: List[Dict]) -> Dict:
    """分析差距"""
    scores = [r['scores']['overall'] for r in results]
    avg_score = sum(scores) / len(scores)
    max_score = max(scores)
    min_score = min(scores)
    
    return {
        'average_score': round(avg_score, 1),
        'score_range': round(max_score - min_score, 1),
        'leader_advantage': round(max_score - avg_score, 1),
        'improvement_potential': round(100 - avg_score, 1)
    }


# ==================== 平台分发 ====================

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
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'}), 500


# ==================== 系统状态 ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
        'database': 'connected',
        'services': {
            'content_generator': 'ok',
            'content_optimizer': 'ok',
            'content_analyzer': 'ok',
            'database': 'ok',
            'roi_calculator': 'ok',
            'authority_builder': 'ok',
            'platform_distributor': 'ok'
        }
    })


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取系统统计"""
    try:
        # 获取数据库统计
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) as total_users FROM users')
            total_users = cursor.fetchone()['total_users']
            
            cursor.execute('SELECT COUNT(*) as total_generations FROM generation_history')
            total_generations = cursor.fetchone()['total_generations']
            
            cursor.execute('SELECT COUNT(*) as total_analyses FROM analysis_records')
            total_analyses = cursor.fetchone()['total_analyses']
            
            cursor.execute('SELECT COUNT(*) as total_metrics FROM metrics_records')
            total_metrics = cursor.fetchone()['total_metrics']
        
        return jsonify({
            'success': True,
            'data': {
                'total_users': total_users,
                'total_generations': total_generations,
                'total_analyses': total_analyses,
                'total_metrics_records': total_metrics,
                'system_status': 'running',
                'database_status': 'connected'
            },
            'message': '统计信息获取成功'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取统计信息失败: {str(e)}'}), 500


# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'message': '接口不存在'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'message': '服务器内部错误'}), 500


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 GEO系统后端服务启动中...")
    print("=" * 60)
    print("📊 数据库: SQLite")
    print("🔧 API地址: http://localhost:5000/api")
    print("📖 文档地址: http://localhost:5000/api/health")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
