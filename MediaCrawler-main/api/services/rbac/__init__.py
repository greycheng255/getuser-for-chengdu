# -*- coding: utf-8 -*-
"""细粒度 RBAC 权限服务(阶段三 P2-6)"""
from .permission_service import (
    DEFAULT_PERMISSIONS,
    ROLE_PERMISSION_MAP,
    PermissionService,
    get_permission_service,
)

__all__ = [
    "DEFAULT_PERMISSIONS",
    "ROLE_PERMISSION_MAP",
    "PermissionService",
    "get_permission_service",
]
