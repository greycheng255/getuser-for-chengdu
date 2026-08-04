"""
工具函数模块
提供通用工具函数和装饰器
"""

import functools
import time
import logging
from flask import jsonify
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def timer_decorator(func):
    """计时装饰器 - 记录函数执行时间"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            end_time = time.time()
            logger.info(f"[TIMER] {func.__name__} 执行时间: {(end_time - start_time):.2f}s")
            return result
        except Exception as e:
            end_time = time.time()
            logger.error(f"[TIMER] {func.__name__} 执行失败 ({(end_time - start_time):.2f}s): {str(e)}")
            raise
    return wrapper


def retry_on_error(max_retries=3, delay=1, exceptions=(Exception,)):
    """重试装饰器 - 在失败时自动重试"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries - 1:
                        logger.error(f"[RETRY] {func.__name__} 重试{max_retries}次后仍然失败: {str(e)}")
                        raise
                    logger.warning(f"[RETRY] {func.__name__} 第{attempt + 1}次尝试失败，{delay}秒后重试...")
                    time.sleep(delay)
        return wrapper
    return decorator


def api_response(success=True, data=None, message=None, status_code=200):
    """统一API响应格式"""
    response = {
        'success': success,
        'timestamp': datetime.now().isoformat(),
    }
    
    if data is not None:
        response['data'] = data
    if message is not None:
        response['message'] = message
    
    return jsonify(response), status_code


def error_response(message, status_code=500, error_details=None):
    """统一错误响应格式"""
    response = {
        'success': False,
        'message': message,
        'timestamp': datetime.now().isoformat(),
    }
    
    if error_details:
        response['error_details'] = error_details
    
    return jsonify(response), status_code


class RateLimiter:
    """简单的速率限制器"""
    def __init__(self, max_requests=100, window=60):
        self.max_requests = max_requests
        self.window = window
        self.requests = {}
    
    def is_allowed(self, key):
        """检查是否允许请求"""
        now = time.time()
        
        # 清理过期的请求记录
        if key in self.requests:
            self.requests[key] = [t for t in self.requests[key] if now - t < self.window]
        else:
            self.requests[key] = []
        
        # 检查是否超过限制
        if len(self.requests[key]) >= self.max_requests:
            return False
        
        # 记录本次请求
        self.requests[key].append(now)
        return True
    
    def get_remaining(self, key):
        """获取剩余请求次数"""
        if key not in self.requests:
            return self.max_requests
        
        now = time.time()
        valid_requests = [t for t in self.requests[key] if now - t < self.window]
        return max(0, self.max_requests - len(valid_requests))


# 全局速率限制器实例
rate_limiter = RateLimiter(max_requests=100, window=60)


def sanitize_input(text, max_length=1000):
    """清理用户输入"""
    if not text:
        return ""
    
    # 限制长度
    text = text[:max_length]
    
    # 移除潜在危险字符
    dangerous_chars = ['<', '>', '"', "'", "&"]
    for char in dangerous_chars:
        text = text.replace(char, '')
    
    return text.strip()


def format_number(num, precision=2):
    """格式化数字显示"""
    if num is None:
        return "N/A"
    
    if abs(num) >= 1000000:
        return f"{num/1000000:.{precision}f}M"
    elif abs(num) >= 1000:
        return f"{num/1000:.{precision}f}K"
    else:
        return f"{num:.{precision}f}"


def truncate_text(text, max_length=100, suffix="..."):
    """截断文本"""
    if not text or len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + suffix


class Cache:
    """简单的内存缓存"""
    def __init__(self, default_timeout=300):
        self.cache = {}
        self.default_timeout = default_timeout
    
    def get(self, key):
        """获取缓存值"""
        if key in self.cache:
            value, expiry = self.cache[key]
            if time.time() < expiry:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key, value, timeout=None):
        """设置缓存值"""
        if timeout is None:
            timeout = self.default_timeout
        
        expiry = time.time() + timeout
        self.cache[key] = (value, expiry)
    
    def delete(self, key):
        """删除缓存值"""
        if key in self.cache:
            del self.cache[key]
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
    
    def cleanup(self):
        """清理过期缓存"""
        now = time.time()
        expired_keys = [k for k, (_, expiry) in self.cache.items() if now > expiry]
        for key in expired_keys:
            del self.cache[key]


# 全局缓存实例
cache = Cache()


def validate_required_fields(data, required_fields):
    """验证必填字段"""
    missing = [field for field in required_fields if not data.get(field)]
    if missing:
        return False, f"缺少必填字段: {', '.join(missing)}"
    return True, None


def parse_datetime(date_string, formats=None):
    """解析日期时间字符串"""
    if formats is None:
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f'
        ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue
    
    return None
