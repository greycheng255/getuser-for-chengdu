# -*- coding: utf-8 -*-
"""
用户与权限模型
- UserModel: 用户账号(含套餐订阅字段,支持商业化)
- UserCookieModel: 用户级别 Cookie 池(每个用户独立管理自己的 Cookie)
- 角色通过 UserModel.role 字段区分: admin / operator / viewer
- 套餐通过 UserModel.plan_type 字段区分: free / basic / pro / enterprise
- 业务表通过 owner_user_id 字段关联用户实现数据隔离
- 细粒度 RBAC: sys_permission / sys_role_permission 表(阶段三 P2-6)
"""
from sqlalchemy import Column, Integer, String, Text, BigInteger, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy import func as sa_func
from sqlalchemy.ext.declarative import declarative_base

# 复用现有 Base,确保与现有模型共用同一个 metadata
from .models import Base


class UserModel(Base):
    """用户账号表(含套餐订阅与计费字段)"""
    __tablename__ = 'sys_user'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='用户ID')
    username = Column(String(64), unique=True, index=True, nullable=False, comment='登录用户名')
    password_hash = Column(String(255), nullable=False, comment='密码哈希(bcrypt)')
    nickname = Column(String(64), default='', comment='昵称')
    email = Column(String(128), default='', comment='邮箱')
    role = Column(String(20), default='operator', comment='角色: admin / operator / viewer')
    status = Column(String(20), default='active', comment='状态: active / disabled')
    created_ts = Column(BigInteger, comment='创建时间戳')
    last_login_ts = Column(BigInteger, default=0, comment='最后登录时间戳')
    # === 套餐订阅字段(v6.6 商业化) ===
    plan_type = Column(String(20), default='free', comment='套餐类型: free / basic / pro / enterprise')
    plan_expires_ts = Column(BigInteger, default=0, comment='套餐过期时间戳(0=永久)')
    plan_started_ts = Column(BigInteger, default=0, comment='套餐开始时间戳')
    # === 按量计费字段 ===
    balance = Column(BigInteger, default=0, comment='账户余额(分,用于超额按量计费)')
    total_spent = Column(BigInteger, default=0, comment='累计消费(分)')
    # === 用量统计(滚动周期,可重置) ===
    usage_period_start_ts = Column(BigInteger, default=0, comment='当前计费周期开始时间戳')
    usage_notes_count = Column(Integer, default=0, comment='当前周期已采集视频/笔记数')
    usage_comments_count = Column(Integer, default=0, comment='当前周期已采集评论数')
    usage_leads_count = Column(Integer, default=0, comment='当前周期已捕获线索数')


class UserCookieModel(Base):
    """用户级别 Cookie 池表

    每个用户可以为每个平台配置多个 Cookie,互相隔离。
    爬虫任务执行时,使用任务创建者的 Cookie。
    """
    __tablename__ = 'sys_user_cookie'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    user_id = Column(Integer, index=True, nullable=False, comment='所属用户ID')
    platform = Column(String(20), index=True, nullable=False, comment='平台: dy/xhs/ks/bili/wb')
    cookie_str = Column(Text, nullable=False, comment='Cookie 字符串')
    alias = Column(String(64), default='', comment='Cookie 别名(可选)')
    status = Column(String(20), default='active', comment='状态: active / invalid / disabled')
    purpose = Column(String(20), default='both', comment='用途: crawl(采集) / outreach(私信) / both(通用)')
    created_ts = Column(BigInteger, comment='创建时间戳')
    last_check_ts = Column(BigInteger, default=0, comment='最后校验时间戳')


class OpenNotebookConnectionModel(Base):
    """MediaCrawler 用户的 OpenNotebook OAuth 连接。

    OAuth 凭证始终按 ``owner_user_id`` 隔离，密文由服务层负责
    加解密；前端和 API 响应都不暴露 token。
    """

    __tablename__ = 'sys_user_opennotebook_connection'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    owner_user_id = Column(String(64), unique=True, index=True, nullable=False, comment='归属系统用户ID')
    provider_user_id = Column(String(128), default='', comment='OpenNotebook 用户ID')
    tenant_id = Column(String(128), default='', index=True, comment='OpenNotebook Tenant ID')
    workspace_id = Column(String(128), default='', comment='默认 Workspace ID')
    workspace_name = Column(String(255), default='', comment='默认 Workspace 名称')
    grant_id = Column(String(128), default='', comment='OAuth Grant ID')
    scope = Column(Text, default='*', comment='OAuth scope')
    token_type = Column(String(32), default='Bearer', comment='Token 类型')
    access_token_ciphertext = Column(Text, nullable=False, comment='加密 Access Token')
    refresh_token_ciphertext = Column(Text, default='', comment='加密 Refresh Token')
    access_token_expires_ts = Column(BigInteger, default=0, comment='Access Token 过期时间(秒)')
    refresh_token_expires_ts = Column(BigInteger, default=0, comment='Refresh Token 过期时间(秒)')
    status = Column(String(32), default='active', index=True, comment='active/reauth_required/revoked/error')
    credential_version = Column(Integer, default=1, comment='凭证轮换版本')
    last_error = Column(Text, default='', comment='最近错误(不含敏感信息)')
    created_ts = Column(BigInteger, comment='创建时间戳(秒)')
    updated_ts = Column(BigInteger, comment='更新时间戳(秒)')
    last_refresh_ts = Column(BigInteger, default=0, comment='最近刷新时间戳(秒)')
    last_used_ts = Column(BigInteger, default=0, comment='最近使用时间戳(秒)')


class OpenNotebookOAuthFlowModel(Base):
    """OAuth 授权码流的一次性 state/PKCE 会话。"""

    __tablename__ = 'sys_user_opennotebook_oauth_flow'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    state_hash = Column(String(64), unique=True, index=True, nullable=False, comment='state SHA-256')
    owner_user_id = Column(String(64), index=True, nullable=False, comment='发起授权的系统用户ID')
    browser_binding_hash = Column(String(64), nullable=False, default='', comment='发起浏览器随机绑定值的 SHA-256')
    expected_credential_version = Column(Integer, default=0, nullable=False, comment='发起授权时的凭证版本')
    code_verifier_ciphertext = Column(Text, nullable=False, comment='加密 PKCE verifier')
    return_to = Column(String(255), default='/x-workbench', comment='授权后返回的内部路径')
    expires_ts = Column(BigInteger, index=True, nullable=False, comment='过期时间戳(秒)')
    consumed_ts = Column(BigInteger, default=0, comment='消费时间戳(秒)')
    created_ts = Column(BigInteger, comment='创建时间戳(秒)')


# ============ 细粒度 RBAC 权限表(阶段三 P2-6) ============


class SysPermissionModel(Base):
    """权限定义表

    定义系统所有可分配的权限码,如 publisher:multi-publish / moderation:review 等。
    admin 角色默认拥有所有权限,无需在此表分配。
    """
    __tablename__ = 'sys_permission'
    permission_id = Column(Integer, primary_key=True, autoincrement=True, comment='权限ID')
    permission_code = Column(String(64), unique=True, index=True, nullable=False, comment='权限码(模块:动作)')
    permission_name = Column(String(128), nullable=False, default='', comment='权限名称')
    module = Column(String(32), index=True, nullable=False, default='', comment='模块名')
    description = Column(Text, default='', comment='描述')
    created_at = Column(DateTime, server_default=sa_func.now(), comment='创建时间')


class SysRolePermissionModel(Base):
    """角色-权限关联表

    role 取值: admin / operator / viewer。
    admin 角色默认拥有所有权限,本表可不记录(admin 判断在代码层短路);
    此表主要用于 operator/viewer 的权限差异化分配。
    """
    __tablename__ = 'sys_role_permission'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    role = Column(String(32), index=True, nullable=False, comment='角色: admin / operator / viewer')
    permission_id = Column(Integer, ForeignKey('sys_permission.permission_id', ondelete='CASCADE'), nullable=False, comment='权限ID')

    __table_args__ = (
        UniqueConstraint('role', 'permission_id', name='uq_role_permission'),
    )


class BusinessProfileRuleModel(Base):
    """可复用的、按用户隔离的获客画像规则"""
    __tablename__ = 'business_profile_rule'
    id = Column(String(64), primary_key=True)
    owner_user_id = Column(String(64), index=True, nullable=False)
    name = Column(String(128), nullable=False)
    business_intent = Column(Text, default='')
    business_keywords = Column(Text, default='[]')
    intent_keywords = Column(Text, default='[]')
    exclude_keywords = Column(Text, default='[]')
    enabled = Column(Integer, default=1)
    created_ts = Column(BigInteger, nullable=False)
    updated_ts = Column(BigInteger, nullable=False)
