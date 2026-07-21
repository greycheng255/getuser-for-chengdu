# -*- coding: utf-8 -*-
"""
用户与权限模型
- UserModel: 用户账号(含套餐订阅字段,支持商业化)
- UserCookieModel: 用户级别 Cookie 池(每个用户独立管理自己的 Cookie)
- 角色通过 UserModel.role 字段区分: admin / operator / viewer
- 套餐通过 UserModel.plan_type 字段区分: free / basic / pro / enterprise
- 业务表通过 owner_user_id 字段关联用户实现数据隔离
"""
from sqlalchemy import Column, Integer, String, Text, BigInteger
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
    created_ts = Column(BigInteger, comment='创建时间戳')
    last_check_ts = Column(BigInteger, default=0, comment='最后校验时间戳')
