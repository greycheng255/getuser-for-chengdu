"""
GEO系统API模块

提供RESTful API接口，支持外部系统集成
"""

from .server import create_app
from .routes import api_router

__all__ = ['create_app', 'api_router']
