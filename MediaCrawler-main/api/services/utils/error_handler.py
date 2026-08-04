# -*- coding: utf-8 -*-
"""
统一错误处理与日志服务

迁移自 GEO-main 项目 (geo_system/backend/error_handler.py)
对应 PRD 模块: 通用工具 - 统一错误处理

职责:
- 提供统一的 APIError 异常层次(ValidationError / AuthenticationError / NotFoundError 等)
- 提供统一的错误响应格式 (handle_api_error / handle_generic_error)
- 提供 ErrorLogger: 内存错误日志记录与统计
- 提供 PerformanceMonitor: 请求性能指标记录与统计
- 提供 register_error_handlers(app): 将错误处理器注册到 FastAPI 应用

适配点(相对 GEO-main 原版):
1. Web 框架: Flask -> FastAPI
   - jsonify(request, @app.errorhandler) -> JSONResponse(app.exception_handler)
   - 响应构造由 Flask jsonify 改为返回 (dict, status_code) 元组,框架无关
2. 日志: 模块级 file_handler/console_handler 配置 -> logging.getLogger(__name__),
   交由项目统一的日志配置管理
3. 配置: 硬编码(max_log_size / FLASK_DEBUG) -> os.environ.get(...)
4. 装饰器: log_request / validate_json / validate_params 原为 Flask 装饰器,
   现保留为框架无关的工具函数 + 装饰器(FastAPI 推荐用 middleware / Depends / pydantic)
5. ErrorLogger.log_error: 原依赖 Flask request 全局对象,改为接受可选参数
6. 单例: 提供 get_error_handler_service() 全局访问
7. 与 MediaCrawler 现有 api/utils/exceptions.py 共存:
   - 本模块仅注册 APIError 层级的处理器,不重复注册通用 Exception 处理器
   - 业务侧可按需选用 BusinessException 或 APIError 体系
"""

import logging
import os
import time
import traceback
from collections import Counter
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============== 配置(从环境变量读取,避免硬编码) ==============

# 内存错误日志最大条数
MAX_ERROR_LOG_SIZE = int(os.environ.get("ERROR_HANDLER_MAX_LOG_SIZE", "1000"))

# 性能指标最大记录数
MAX_METRICS_RECORDS = int(os.environ.get("ERROR_HANDLER_MAX_METRICS", "1000"))

# 慢请求阈值(秒),超过则单独记录
SLOW_REQUEST_THRESHOLD = float(os.environ.get("ERROR_HANDLER_SLOW_THRESHOLD", "1.0"))

# 是否在错误响应中暴露详情(生产环境建议关闭)
EXPOSE_ERROR_DETAILS = os.environ.get("ERROR_HANDLER_EXPOSE_DETAILS", "").lower() == "true"


# ============== 异常层次(保留原逻辑) ==============

class APIError(Exception):
    """API 错误基类

    Attributes:
        message: 错误消息
        status_code: HTTP 状态码
        error_code: 业务错误码(自动生成,如 ERR_400)
        details: 附加详情(可选)
    """

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or f"ERR_{status_code}"
        self.details = details or {}


class ValidationError(APIError):
    """验证错误(参数缺失/格式错误)"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 400, "VALIDATION_ERROR", details)


class AuthenticationError(APIError):
    """认证错误(未登录/token 失效)"""

    def __init__(self, message: str = "认证失败"):
        super().__init__(message, 401, "AUTH_ERROR")


class AuthorizationError(APIError):
    """授权错误(权限不足)"""

    def __init__(self, message: str = "权限不足"):
        super().__init__(message, 403, "FORBIDDEN")


class NotFoundError(APIError):
    """资源不存在"""

    def __init__(self, resource: str = "资源"):
        super().__init__(f"{resource}不存在", 404, "NOT_FOUND")


class RateLimitError(APIError):
    """速率限制(请求过于频繁)"""

    def __init__(self, message: str = "请求过于频繁"):
        super().__init__(message, 429, "RATE_LIMIT")


class ServerError(APIError):
    """服务器内部错误"""

    def __init__(self, message: str = "服务器内部错误"):
        super().__init__(message, 500, "INTERNAL_ERROR")


# ============== 错误响应构造(框架无关) ==============

def handle_api_error(error: APIError) -> Tuple[Dict[str, Any], int]:
    """处理 APIError,返回 (响应体字典, HTTP 状态码)

    适配点: 原版返回 Flask jsonify 响应,现改为返回元组,
    由 FastAPI 的 exception_handler 包装为 JSONResponse
    """
    response = {
        "success": False,
        "error": {
            "code": error.error_code,
            "message": error.message,
            "details": error.details,
        },
        "timestamp": datetime.now().isoformat(),
    }
    logger.warning(f"API Error: {error.error_code} - {error.message}")
    return response, error.status_code


def handle_generic_error(error: Exception) -> Tuple[Dict[str, Any], int]:
    """处理通用异常,返回 (响应体字典, 500)

    适配点: 原版使用 os.getenv('FLASK_DEBUG') 决定是否暴露详情,
    现改为使用 ERROR_HANDLER_EXPOSE_DETAILS 环境变量
    """
    logger.error(f"Unhandled error: {str(error)}\n{traceback.format_exc()}")
    response = {
        "success": False,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "服务器内部错误",
            "details": str(error) if EXPOSE_ERROR_DETAILS else None,
        },
        "timestamp": datetime.now().isoformat(),
    }
    return response, 500


# ============== 请求日志与参数校验工具(框架无关) ==============

def log_request(func: Callable) -> Callable:
    """请求日志装饰器

    适配点: 原版依赖 Flask request 全局对象,现改为:
    - 若调用时第一个参数是带 .method/.url.path/.client.host 的对象(如 FastAPI Request),则记录请求信息
    - 否则仅记录函数名与耗时
    """
    @wraps(func)
    def decorated_function(*args, **kwargs):
        start_time = datetime.now()
        method = getattr(args[0], "method", None) if args else None
        path = None
        remote_addr = None
        # FastAPI Request: request.method / request.url.path / request.client.host
        if args and hasattr(args[0], "url"):
            path = getattr(args[0].url, "path", None)
        if args and hasattr(args[0], "client"):
            client = getattr(args[0], "client", None)
            remote_addr = getattr(client, "host", None) if client else None

        label = f"{method} {path}" if method and path else func.__name__
        logger.info(f"Request: {label} - {remote_addr or '-'}")

        try:
            response = func(*args, **kwargs)
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"Response: {label} - {duration:.3f}s")
            return response
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Error in {label} after {duration:.3f}s: {str(e)}")
            raise

    return decorated_function


def validate_json_fields(data: Optional[Dict[str, Any]], required_fields: Tuple[str, ...]) -> None:
    """校验 JSON 字段是否齐全(框架无关)

    适配点: 原版 validate_json 装饰器从 Flask request.get_json() 取数据,
    现改为接受显式 data 参数,FastAPI 中可结合 pydantic / Depends 使用

    Raises:
        ValidationError: 当缺少必填字段时
    """
    if data is None:
        raise ValidationError("请求必须提供 JSON 数据")
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        raise ValidationError(
            f"缺少必填字段: {', '.join(missing_fields)}",
            {"missing_fields": missing_fields},
        )


def validate_query_params(params: Dict[str, Any], required_params: Tuple[str, ...]) -> None:
    """校验查询参数是否齐全(框架无关)

    适配点: 原版 validate_params 装饰器从 Flask request.args 取参数,
    现改为接受显式 params 参数

    Raises:
        ValidationError: 当缺少必填参数时
    """
    missing_params = [param for param in required_params if param not in params]
    if missing_params:
        raise ValidationError(
            f"缺少必填参数: {', '.join(missing_params)}",
            {"missing_params": missing_params},
        )


def validate_json(*required_fields: str) -> Callable:
    """JSON 校验装饰器(Flask 风格,保留原逻辑)

    适配点: 依赖 Flask request 全局对象。FastAPI 项目中推荐使用 pydantic 模型或
    validate_json_fields(data, required_fields) 替代。仅在 Flask 上下文中可用。
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                from flask import request  # type: ignore
            except ImportError as e:
                raise RuntimeError(
                    "validate_json 装饰器需要 Flask,FastAPI 项目请使用 "
                    "validate_json_fields(data, required_fields) 或 pydantic 模型"
                ) from e
            if not request.is_json:
                raise ValidationError("请求必须是JSON格式")
            data = request.get_json() or {}
            validate_json_fields(data, required_fields)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def validate_params(*required_params: str) -> Callable:
    """查询参数校验装饰器(Flask 风格,保留原逻辑)

    适配点: 依赖 Flask request 全局对象。FastAPI 项目中推荐使用
    validate_query_params(params, required_params) 或 Depends 替代。
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                from flask import request  # type: ignore
            except ImportError as e:
                raise RuntimeError(
                    "validate_params 装饰器需要 Flask,FastAPI 项目请使用 "
                    "validate_query_params(params, required_params) 或 Depends"
                ) from e
            params = dict(request.args)
            validate_query_params(params, required_params)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


# ============== ErrorLogger(保留原逻辑) ==============

class ErrorLogger:
    """内存错误日志记录器

    适配点: 原版 log_error 依赖 Flask request 全局对象获取 path/method,
    现改为接受可选的 path/method 参数,框架无关
    """

    def __init__(self, max_log_size: int = MAX_ERROR_LOG_SIZE):
        self.error_log: List[Dict[str, Any]] = []
        self.max_log_size = max_log_size

    def log_error(
        self,
        error_type: str,
        message: str,
        details: Any = None,
        path: Optional[str] = None,
        method: Optional[str] = None,
    ) -> None:
        """记录一条错误

        Args:
            error_type: 错误类型标识(如 UNHANDLED / VALIDATION_ERROR)
            message: 错误消息
            details: 错误详情(如堆栈字符串)
            path: 请求路径(可选)
            method: 请求方法(可选)
        """
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "type": error_type,
            "message": message,
            "details": details,
            "path": path,
            "method": method,
        }
        self.error_log.append(error_entry)

        # 限制日志大小(保留最新 max_log_size 条)
        if len(self.error_log) > self.max_log_size:
            self.error_log = self.error_log[-self.max_log_size:]

        # 同时写入标准日志
        logger.error(f"[{error_type}] {message}")

    def get_recent_errors(self, count: int = 10) -> List[Dict[str, Any]]:
        """获取最近的 N 条错误"""
        return self.error_log[-count:]

    def get_error_stats(self) -> Dict[str, Any]:
        """获取错误统计"""
        if not self.error_log:
            return {}
        type_counts = Counter(error["type"] for error in self.error_log)
        return {
            "total_errors": len(self.error_log),
            "error_types": dict(type_counts),
            "recent_errors": self.get_recent_errors(5),
        }


# ============== PerformanceMonitor(保留原逻辑) ==============

class PerformanceMonitor:
    """性能监控器(请求耗时、慢请求、错误率)"""

    def __init__(self, max_records: int = MAX_METRICS_RECORDS):
        self.metrics: Dict[str, List[Dict[str, Any]]] = {
            "requests": [],
            "slow_queries": [],
            "errors": [],
        }
        self.max_records = max_records

    def record_request(
        self,
        path: str,
        method: str,
        duration: float,
        status_code: int,
    ) -> None:
        """记录一次请求的指标

        Args:
            path: 请求路径
            method: 请求方法
            duration: 耗时(秒)
            status_code: HTTP 状态码
        """
        self.metrics["requests"].append({
            "timestamp": datetime.now().isoformat(),
            "path": path,
            "method": method,
            "duration": duration,
            "status_code": status_code,
        })

        # 记录慢请求
        if duration > SLOW_REQUEST_THRESHOLD:
            self.metrics["slow_queries"].append({
                "timestamp": datetime.now().isoformat(),
                "path": path,
                "duration": duration,
            })

        # 记录错误请求(状态码 >= 400)
        if status_code >= 400:
            self.metrics["errors"].append({
                "timestamp": datetime.now().isoformat(),
                "path": path,
                "method": method,
                "status_code": status_code,
            })

        # 限制各类记录数
        for key in self.metrics:
            if len(self.metrics[key]) > self.max_records:
                self.metrics[key] = self.metrics[key][-self.max_records:]

    def get_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        if not self.metrics["requests"]:
            return {
                "total_requests": 0,
                "avg_response_time": 0,
                "slow_requests": 0,
                "error_rate": 0,
            }
        total = len(self.metrics["requests"])
        durations = [r["duration"] for r in self.metrics["requests"]]
        errors = len([r for r in self.metrics["requests"] if r["status_code"] >= 400])
        return {
            "total_requests": total,
            "avg_response_time": sum(durations) / len(durations),
            "slow_requests": len(self.metrics["slow_queries"]),
            "error_rate": errors / total if total > 0 else 0,
        }


# ============== 服务单例 ==============

class ErrorHandlerService:
    """统一错误处理服务(聚合 ErrorLogger + PerformanceMonitor)

    使用方式:
        from api.services.utils.error_handler import get_error_handler_service
        service = get_error_handler_service()
        service.error_logger.log_error("VALIDATION_ERROR", "缺少字段")
        service.performance_monitor.record_request("/api/x", "GET", 0.05, 200)
        service.register_error_handlers(app)  # 注册到 FastAPI app
    """

    def __init__(self):
        self.error_logger = ErrorLogger()
        self.performance_monitor = PerformanceMonitor()

    def register_error_handlers(self, app: Any) -> None:
        """注册错误处理器到 FastAPI 应用

        适配点: 原版为 Flask app.errorhandler,现改为 FastAPI app.exception_handler。
        仅注册 APIError 层级处理器,通用 Exception 处理器由
        MediaCrawler 现有 api/utils/exceptions.py 负责,避免冲突。

        Args:
            app: FastAPI 应用实例
        """
        from fastapi import Request
        from fastapi.responses import JSONResponse

        @app.exception_handler(APIError)
        async def _handle_api_error_handler(request: Request, exc: APIError):
            body, status = handle_api_error(exc)
            # 记录到性能监控
            self.performance_monitor.record_request(
                path=request.url.path,
                method=request.method,
                duration=0.0,  # APIError 通常在路由处理早期抛出,耗时忽略
                status_code=status,
            )
            return JSONResponse(status_code=status, content=body)

        # 为每个 APIError 子类显式注册,确保覆盖(FastAPI 默认会按继承链匹配,
        # 但显式注册可避免与 BusinessException 体系混淆)
        for exc_cls in (
            ValidationError,
            AuthenticationError,
            AuthorizationError,
            NotFoundError,
            RateLimitError,
            ServerError,
        ):
            @app.exception_handler(exc_cls)
            async def _handle_subclass_error(request: Request, exc: APIError, _cls=exc_cls):
                body, status = handle_api_error(exc)
                self.performance_monitor.record_request(
                    path=request.url.path,
                    method=request.method,
                    duration=0.0,
                    status_code=status,
                )
                return JSONResponse(status_code=status, content=body)

        logger.info("APIError handlers registered successfully")


# ============== 单例 ==============

_error_handler_service: Optional[ErrorHandlerService] = None


def get_error_handler_service() -> ErrorHandlerService:
    """获取全局 ErrorHandlerService 单例(懒初始化)

    Returns:
        ErrorHandlerService 实例,聚合了 error_logger 与 performance_monitor
    """
    global _error_handler_service
    if _error_handler_service is None:
        _error_handler_service = ErrorHandlerService()
    return _error_handler_service
