"""
全局错误处理和日志系统
"""

import logging
import traceback
import json
from datetime import datetime
from functools import wraps
from flask import jsonify, request
import os

# 配置日志
log_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(log_dir, exist_ok=True)

# 文件日志
file_handler = logging.FileHandler(
    os.path.join(log_dir, f'app_{datetime.now().strftime("%Y%m%d")}.log'),
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)

# 控制台日志
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# 格式化
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# 根日志配置
logger = logging.getLogger('geo_system')
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)


class APIError(Exception):
    """API错误基类"""
    def __init__(self, message, status_code=400, error_code=None, details=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or f"ERR_{status_code}"
        self.details = details or {}


class ValidationError(APIError):
    """验证错误"""
    def __init__(self, message, details=None):
        super().__init__(message, 400, "VALIDATION_ERROR", details)


class AuthenticationError(APIError):
    """认证错误"""
    def __init__(self, message="认证失败"):
        super().__init__(message, 401, "AUTH_ERROR")


class AuthorizationError(APIError):
    """授权错误"""
    def __init__(self, message="权限不足"):
        super().__init__(message, 403, "FORBIDDEN")


class NotFoundError(APIError):
    """资源不存在"""
    def __init__(self, resource="资源"):
        super().__init__(f"{resource}不存在", 404, "NOT_FOUND")


class RateLimitError(APIError):
    """速率限制"""
    def __init__(self, message="请求过于频繁"):
        super().__init__(message, 429, "RATE_LIMIT")


class ServerError(APIError):
    """服务器错误"""
    def __init__(self, message="服务器内部错误"):
        super().__init__(message, 500, "INTERNAL_ERROR")


def handle_api_error(error):
    """处理API错误"""
    response = {
        'success': False,
        'error': {
            'code': error.error_code,
            'message': error.message,
            'details': error.details
        },
        'timestamp': datetime.now().isoformat()
    }
    
    logger.warning(f"API Error: {error.error_code} - {error.message}")
    
    return jsonify(response), error.status_code


def handle_generic_error(error):
    """处理通用错误"""
    logger.error(f"Unhandled error: {str(error)}\n{traceback.format_exc()}")
    
    response = {
        'success': False,
        'error': {
            'code': 'INTERNAL_ERROR',
            'message': '服务器内部错误',
            'details': str(error) if os.getenv('FLASK_DEBUG') else None
        },
        'timestamp': datetime.now().isoformat()
    }
    
    return jsonify(response), 500


def log_request(f):
    """请求日志装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = datetime.now()
        
        # 记录请求
        logger.info(f"Request: {request.method} {request.path} - {request.remote_addr}")
        
        try:
            response = f(*args, **kwargs)
            
            # 记录响应时间
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"Response: {request.path} - {duration:.3f}s")
            
            return response
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Error in {request.path} after {duration:.3f}s: {str(e)}")
            raise
    
    return decorated_function


def validate_json(*required_fields):
    """JSON验证装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not request.is_json:
                raise ValidationError("请求必须是JSON格式")
            
            data = request.get_json()
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                raise ValidationError(
                    f"缺少必填字段: {', '.join(missing_fields)}",
                    {'missing_fields': missing_fields}
                )
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def validate_params(*required_params):
    """查询参数验证装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            missing_params = [param for param in required_params if param not in request.args]
            
            if missing_params:
                raise ValidationError(
                    f"缺少必填参数: {', '.join(missing_params)}",
                    {'missing_params': missing_params}
                )
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


class ErrorLogger:
    """错误日志记录器"""
    
    def __init__(self):
        self.error_log = []
        self.max_log_size = 1000
    
    def log_error(self, error_type, message, details=None):
        """记录错误"""
        error_entry = {
            'timestamp': datetime.now().isoformat(),
            'type': error_type,
            'message': message,
            'details': details,
            'path': request.path if request else None,
            'method': request.method if request else None
        }
        
        self.error_log.append(error_entry)
        
        # 限制日志大小
        if len(self.error_log) > self.max_log_size:
            self.error_log = self.error_log[-self.max_log_size:]
        
        # 写入文件
        logger.error(f"[{error_type}] {message}")
    
    def get_recent_errors(self, count=10):
        """获取最近的错误"""
        return self.error_log[-count:]
    
    def get_error_stats(self):
        """获取错误统计"""
        from collections import Counter
        
        if not self.error_log:
            return {}
        
        type_counts = Counter(error['type'] for error in self.error_log)
        
        return {
            'total_errors': len(self.error_log),
            'error_types': dict(type_counts),
            'recent_errors': self.get_recent_errors(5)
        }


# 全局错误日志记录器
error_logger = ErrorLogger()


def register_error_handlers(app):
    """注册错误处理器到Flask应用"""
    
    @app.errorhandler(APIError)
    def handle_api_error_handler(error):
        return handle_api_error(error)
    
    @app.errorhandler(ValidationError)
    def handle_validation_error_handler(error):
        return handle_api_error(error)
    
    @app.errorhandler(AuthenticationError)
    def handle_auth_error_handler(error):
        return handle_api_error(error)
    
    @app.errorhandler(NotFoundError)
    def handle_not_found_error_handler(error):
        return handle_api_error(error)
    
    @app.errorhandler(Exception)
    def handle_exception_handler(error):
        error_logger.log_error('UNHANDLED', str(error), traceback.format_exc())
        return handle_generic_error(error)
    
    @app.errorhandler(404)
    def handle_404(error):
        return jsonify({
            'success': False,
            'error': {
                'code': 'NOT_FOUND',
                'message': '请求的资源不存在'
            }
        }), 404
    
    @app.errorhandler(405)
    def handle_405(error):
        return jsonify({
            'success': False,
            'error': {
                'code': 'METHOD_NOT_ALLOWED',
                'message': '请求方法不允许'
            }
        }), 405
    
    logger.info("Error handlers registered successfully")


# 性能监控
class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.metrics = {
            'requests': [],
            'slow_queries': [],
            'errors': []
        }
        self.max_records = 1000
    
    def record_request(self, path, method, duration, status_code):
        """记录请求指标"""
        self.metrics['requests'].append({
            'timestamp': datetime.now().isoformat(),
            'path': path,
            'method': method,
            'duration': duration,
            'status_code': status_code
        })
        
        # 记录慢请求
        if duration > 1.0:  # 超过1秒
            self.metrics['slow_queries'].append({
                'timestamp': datetime.now().isoformat(),
                'path': path,
                'duration': duration
            })
        
        # 限制记录数
        for key in self.metrics:
            if len(self.metrics[key]) > self.max_records:
                self.metrics[key] = self.metrics[key][-self.max_records:]
    
    def get_stats(self):
        """获取性能统计"""
        if not self.metrics['requests']:
            return {
                'total_requests': 0,
                'avg_response_time': 0,
                'slow_requests': 0,
                'error_rate': 0
            }
        
        total = len(self.metrics['requests'])
        durations = [r['duration'] for r in self.metrics['requests']]
        errors = len([r for r in self.metrics['requests'] if r['status_code'] >= 400])
        
        return {
            'total_requests': total,
            'avg_response_time': sum(durations) / len(durations),
            'slow_requests': len(self.metrics['slow_queries']),
            'error_rate': errors / total if total > 0 else 0
        }


# 全局性能监控器
performance_monitor = PerformanceMonitor()
