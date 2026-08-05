# -*- coding: utf-8 -*-
"""
自定义业务异常 + 全局异常处理器

设计原则:
1. 业务异常继承 BusinessException,携带 code(业务码)和 message
2. 全局异常处理器统一捕获,返回 {code, message, data} 格式
3. 区分"业务错误"(可预期,如参数缺失)、"系统错误"(不可预期,如 DB 异常)
4. 系统错误自动记录堆栈,业务错误只记录消息

用法:
    from api.utils.exceptions import BusinessError, NotFoundError, AuthError

    if not post:
        raise NotFoundError("推文不存在")
    if not user.is_admin:
        raise AuthError("需要管理员权限")

注册到 FastAPI app(在 main.py 中):
    from api.utils.exceptions import register_exception_handlers
    register_exception_handlers(app)
"""
import logging
import traceback
import uuid
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

logger = logging.getLogger("api.exceptions")


# ==================== 异常基类 ====================

class BusinessException(Exception):
    """业务异常基类

    Attributes:
        code: 业务错误码(非 0)
        message: 错误消息
        data: 附加数据(可选)
        http_status: 对应的 HTTP 状态码
    """

    def __init__(
        self,
        code: int,
        message: str,
        data: Any = None,
        http_status: int = 400,
    ):
        self.code = code
        self.message = message
        self.data = data
        self.http_status = http_status
        super().__init__(message)


class BusinessError(BusinessException):
    """一般业务错误(http 400)"""

    def __init__(self, message: str, data: Any = None, code: int = 4000):
        super().__init__(code=code, message=message, data=data, http_status=400)


class NotFoundError(BusinessException):
    """资源不存在(http 404)"""

    def __init__(self, message: str = "资源不存在", data: Any = None, code: int = 4040):
        super().__init__(code=code, message=message, data=data, http_status=404)


class AuthError(BusinessException):
    """认证/授权错误(http 401/403)"""

    def __init__(self, message: str = "认证失败", data: Any = None, code: int = 4010, http_status: int = 401):
        super().__init__(code=code, message=message, data=data, http_status=http_status)


class ForbiddenError(BusinessException):
    """无权限(http 403)"""

    def __init__(self, message: str = "无权限访问", data: Any = None, code: int = 4030):
        super().__init__(code=code, message=message, data=data, http_status=403)


class RateLimitError(BusinessException):
    """触发限流(http 429)"""

    def __init__(self, message: str = "请求过于频繁,请稍后再试", data: Any = None, code: int = 4290):
        super().__init__(code=code, message=message, data=data, http_status=429)


class ConflictError(BusinessException):
    """资源冲突(如重复创建,http 409)"""

    def __init__(self, message: str = "资源已存在", data: Any = None, code: int = 4090):
        super().__init__(code=code, message=message, data=data, http_status=409)


class ExternalServiceError(BusinessException):
    """外部服务调用失败(http 502)"""

    def __init__(self, message: str = "外部服务调用失败", data: Any = None, code: int = 5020):
        super().__init__(code=code, message=message, data=data, http_status=502)


# ==================== 全局异常处理器 ====================

def _make_request_id(request: Request) -> str:
    """从请求头获取或生成 request_id,用于追踪"""
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    return rid


def _make_error_response(
    code: int,
    message: str,
    data: Any = None,
    request_id: Optional[str] = None,
    http_status: int = 400,
    detail: Any = None,
) -> JSONResponse:
    """构造统一的错误 JSONResponse"""
    body = {"code": code, "message": message, "data": data}
    if detail is not None:
        # Keep FastAPI's historical ``detail`` field for existing clients while
        # retaining the unified error envelope used by newer clients.
        body["detail"] = detail
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=http_status, content=body, headers={"X-Request-ID": request_id or ""})


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器到 FastAPI app"""

    @app.exception_handler(BusinessException)
    async def _handle_business_exception(request: Request, exc: BusinessException):
        rid = _make_request_id(request)
        # 业务异常不打印堆栈,只记录消息
        logger.info(f"[{rid}] business error: code={exc.code} msg={exc.message}")
        return _make_error_response(
            code=exc.code,
            message=exc.message,
            data=exc.data,
            request_id=rid,
            http_status=exc.http_status,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError):
        rid = _make_request_id(request)
        # 参数校验失败,提取错误详情
        errors = exc.errors()
        # 取第一条错误的可读消息作为主消息
        first_msg = "参数校验失败"
        try:
            first_err = errors[0] if errors else {}
            loc = ".".join(str(x) for x in first_err.get("loc", []) if x != "body")
            first_msg = f"{loc}: {first_err.get('msg', 'invalid')}" if loc else first_err.get("msg", first_msg)
        except Exception:
            pass
        logger.info(f"[{rid}] validation error: {errors}")
        return _make_error_response(
            code=4220,
            message=first_msg,
            data={"errors": errors},
            request_id=rid,
            http_status=422,
        )

    @app.exception_handler(HTTPException)
    async def _handle_http_exception(request: Request, exc: HTTPException):
        rid = _make_request_id(request)
        # FastAPI HTTPException(如路由中主动 raise HTTPException(404, ...))
        # 映射 HTTP 状态码到业务码
        code_map = {
            400: 4000, 401: 4010, 403: 4030, 404: 4040,
            409: 4090, 422: 4220, 429: 4290, 500: 5000, 502: 5020,
        }
        biz_code = code_map.get(exc.status_code, exc.status_code * 10)
        logger.info(f"[{rid}] http error: status={exc.status_code} msg={exc.detail}")
        return _make_error_response(
            code=biz_code,
            message=str(exc.detail),
            request_id=rid,
            http_status=exc.status_code,
            detail=exc.detail,
        )

    @app.exception_handler(Exception)
    async def _handle_unknown_exception(request: Request, exc: Exception):
        rid = _make_request_id(request)
        # 未预期异常:打印完整堆栈,返回 500
        tb = traceback.format_exc()
        logger.error(f"[{rid}] unhandled exception: {exc}\n{tb}")
        return _make_error_response(
            code=5000,
            message="服务器内部错误,请联系管理员",
            data={"detail": str(exc)} if logger.isEnabledFor(logging.DEBUG) else None,
            request_id=rid,
            http_status=500,
        )
