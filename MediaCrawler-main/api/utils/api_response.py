# -*- coding: utf-8 -*-
"""
统一 API 响应格式

所有 API 接口返回统一的结构:
    {
        "code": 0,           # 0 表示成功,非 0 表示业务错误码
        "message": "ok",     # 人类可读的消息
        "data": ...,         # 业务数据(成功时)或 None(失败时)
        "request_id": "...", # 请求追踪 ID(可选)
    }

用法:
    from api.utils.api_response import success, error, paginated, SuccessResponse

    @router.get("/foo", response_model=SuccessResponse[Item])
    async def get_foo():
        return success(item)

    @router.get("/list", response_model=SuccessResponse[List[Item]])
    async def list_foo():
        return paginated(items, total=100, page=1, page_size=20)
"""
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """成功响应模型(用于 OpenAPI 文档生成)"""
    code: int = Field(0, description="业务码,0 表示成功")
    message: str = Field("ok", description="人类可读消息")
    data: Optional[T] = None


class ErrorResponse(BaseModel):
    """错误响应模型"""
    code: int = Field(..., description="业务错误码,非 0")
    message: str = Field(..., description="错误消息")
    data: Optional[Any] = Field(None, description="附加错误数据")
    request_id: Optional[str] = Field(None, description="请求追踪 ID")


class PaginatedData(BaseModel, Generic[T]):
    """分页数据包装"""
    items: List[T]
    total: int = 0
    page: int = 1
    page_size: int = 20
    has_more: bool = False


def success(data: Any = None, message: str = "ok") -> dict:
    """构造成功响应"""
    return {"code": 0, "message": message, "data": data}


def error(
    code: int,
    message: str,
    data: Any = None,
    request_id: Optional[str] = None,
) -> dict:
    """构造错误响应(用于业务逻辑主动返回错误)"""
    resp = {"code": code, "message": message, "data": data}
    if request_id:
        resp["request_id"] = request_id
    return resp


def paginated(
    items: List[Any],
    total: int,
    page: int = 1,
    page_size: int = 20,
    message: str = "ok",
) -> dict:
    """构造分页成功响应"""
    has_more = (page * page_size) < total
    return {
        "code": 0,
        "message": message,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        },
    }
