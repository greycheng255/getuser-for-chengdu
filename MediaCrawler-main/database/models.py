# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/database/models.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

from sqlalchemy import create_engine, Column, Integer, Text, String, BigInteger, Boolean, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class BilibiliVideo(Base):
    __tablename__ = 'bilibili_video'
    id = Column(Integer, primary_key=True, comment='主键ID')
    video_id = Column(BigInteger, nullable=False, index=True, unique=True, comment='视频ID')
    video_url = Column(Text, nullable=False, comment='视频URL')
    user_id = Column(BigInteger, index=True, comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    liked_count = Column(Integer, comment='点赞数')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    video_coin_count = Column(String(255), default='0', comment='硬币数')
    video_danmaku = Column(String(255), default='0', comment='弹幕数')
    video_comment = Column(String(255), default='0', comment='评论数')
    video_cover_url = Column(Text, comment='视频封面URL')
    source_keyword = Column(Text, default='', comment='来源关键词')

class BilibiliVideoComment(Base):
    __tablename__ = 'bilibili_video_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    sex = Column(String(255), default='', comment='性别')
    sign = Column(Text, comment='签名')
    avatar = Column(Text, comment='头像')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(BigInteger, index=True, comment='评论ID')
    video_id = Column(BigInteger, index=True, comment='视频ID')
    content = Column(Text, comment='评论内容')
    create_time = Column(BigInteger, comment='创建时间戳')
    sub_comment_count = Column(String(255), default='0', comment='子评论数')
    parent_comment_id = Column(String(255), comment='父评论ID')
    like_count = Column(String(255), default='0', comment='点赞数')
    task_id = Column(String(255), index=True, default='', comment='任务ID')

class BilibiliUpInfo(Base):
    __tablename__ = 'bilibili_up_info'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(BigInteger, index=True, comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    sex = Column(String(255), default='', comment='性别')
    sign = Column(Text, comment='签名')
    avatar = Column(Text, comment='头像')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    total_fans = Column(Integer, comment='总粉丝数')
    total_liked = Column(Integer, comment='总获赞数')
    user_rank = Column(Integer, comment='用户等级')
    is_official = Column(Integer, comment='是否官方认证')

class BilibiliContactInfo(Base):
    __tablename__ = 'bilibili_contact_info'
    id = Column(Integer, primary_key=True, comment='主键ID')
    up_id = Column(BigInteger, index=True, comment='UP主ID')
    fan_id = Column(BigInteger, index=True, comment='粉丝ID')
    up_name = Column(Text, comment='UP主名称')
    fan_name = Column(Text, comment='粉丝名称')
    up_sign = Column(Text, comment='UP主签名')
    fan_sign = Column(Text, comment='粉丝签名')
    up_avatar = Column(Text, comment='UP主头像')
    fan_avatar = Column(Text, comment='粉丝头像')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')

class BilibiliUpDynamic(Base):
    __tablename__ = 'bilibili_up_dynamic'
    id = Column(Integer, primary_key=True, comment='主键ID')
    dynamic_id = Column(BigInteger, index=True, comment='动态ID')
    user_id = Column(String(255), comment='用户ID')
    user_name = Column(Text, comment='用户名称')
    text = Column(Text, comment='动态内容')
    type = Column(String(255), default='', comment='动态类型')
    pub_ts = Column(BigInteger, comment='发布时间戳')
    total_comments = Column(Integer, comment='总评论数')
    total_forwards = Column(Integer, comment='总转发数')
    total_liked = Column(Integer, comment='总点赞数')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')

class DouyinAweme(Base):
    __tablename__ = 'douyin_aweme'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    sec_uid = Column(String(255), comment='安全用户ID')
    short_user_id = Column(String(255), comment='短用户ID')
    user_unique_id = Column(String(255), comment='用户唯一ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    user_signature = Column(Text, comment='用户签名')
    ip_location = Column(String(255), default='', comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    aweme_id = Column(String(255), index=True, comment='作品ID')
    aweme_type = Column(String(255), default='', comment='作品类型')
    title = Column(Text, comment='作品标题')
    desc = Column(Text, comment='作品描述')
    create_time = Column(BigInteger, index=True, comment='创建时间戳')
    liked_count = Column(String(255), default='0', comment='点赞数')
    comment_count = Column(String(255), default='0', comment='评论数')
    share_count = Column(String(255), default='0', comment='分享数')
    collected_count = Column(String(255), default='0', comment='收藏数')
    aweme_url = Column(Text, comment='作品URL')
    cover_url = Column(Text, comment='封面URL')
    video_download_url = Column(Text, comment='视频下载URL')
    music_download_url = Column(Text, comment='音乐下载URL')
    note_download_url = Column(Text, comment='笔记下载URL')
    source_keyword = Column(Text, default='', comment='来源关键词')
    task_id = Column(String(255), index=True, default='', comment='任务ID')

class DouyinAwemeComment(Base):
    __tablename__ = 'douyin_aweme_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    sec_uid = Column(String(255), comment='安全用户ID')
    short_user_id = Column(String(255), comment='短用户ID')
    user_unique_id = Column(String(255), comment='用户唯一ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    user_signature = Column(Text, comment='用户签名')
    ip_location = Column(Text, comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(String(255), index=True, comment='评论ID')
    aweme_id = Column(String(255), index=True, comment='作品ID')
    content = Column(Text, comment='评论内容')
    create_time = Column(BigInteger, comment='创建时间戳')
    sub_comment_count = Column(String(255), default='0', comment='子评论数')
    parent_comment_id = Column(String(255), comment='父评论ID')
    like_count = Column(String(255), default='0', comment='点赞数')
    pictures = Column(Text, default='', comment='图片')
    task_id = Column(String(255), index=True, default='', comment='任务ID')

class DyCreator(Base):
    __tablename__ = 'dy_creator'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    ip_location = Column(Text, comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    desc = Column(Text, comment='描述')
    gender = Column(String(255), default='', comment='性别')
    follows = Column(String(255), default='0', comment='关注数')
    fans = Column(String(255), default='0', comment='粉丝数')
    interaction = Column(String(255), default='0', comment='互动数')
    videos_count = Column(String(255), default='0', comment='视频数量')

class KuaishouVideo(Base):
    __tablename__ = 'kuaishou_video'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(64), comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    video_id = Column(String(255), index=True, comment='视频ID')
    video_type = Column(String(255), default='', comment='视频类型')
    title = Column(Text, comment='视频标题')
    desc = Column(Text, comment='视频描述')
    create_time = Column(BigInteger, index=True, comment='创建时间戳')
    liked_count = Column(String(255), default='0', comment='点赞数')
    viewd_count = Column(String(255), default='0', comment='观看数')
    video_url = Column(Text, comment='视频URL')
    video_cover_url = Column(Text, comment='视频封面URL')
    video_play_url = Column(Text, comment='视频播放URL')
    source_keyword = Column(Text, default='', comment='来源关键词')

class KuaishouVideoComment(Base):
    __tablename__ = 'kuaishou_video_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(Text, comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(BigInteger, index=True, comment='评论ID')
    video_id = Column(String(255), index=True, comment='视频ID')
    content = Column(Text, comment='评论内容')
    create_time = Column(BigInteger, comment='创建时间戳')
    sub_comment_count = Column(String(255), default='0', comment='子评论数')
    task_id = Column(String(255), index=True, default='', comment='任务ID')

class WeiboNote(Base):
    __tablename__ = 'weibo_note'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    gender = Column(String(255), default='', comment='性别')
    profile_url = Column(Text, comment='个人主页URL')
    ip_location = Column(Text, default='', comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    note_id = Column(BigInteger, index=True, comment='笔记ID')
    content = Column(Text, comment='笔记内容')
    create_time = Column(BigInteger, index=True, comment='创建时间戳')
    create_date_time = Column(String(255), index=True, comment='创建日期时间')
    liked_count = Column(String(255), default='0', comment='点赞数')
    comments_count = Column(String(255), default='0', comment='评论数')
    shared_count = Column(String(255), default='0', comment='分享数')
    note_url = Column(Text, comment='笔记URL')
    source_keyword = Column(Text, default='', comment='来源关键词')

class WeiboNoteComment(Base):
    __tablename__ = 'weibo_note_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    gender = Column(String(255), default='', comment='性别')
    profile_url = Column(Text, comment='个人主页URL')
    ip_location = Column(Text, default='', comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(BigInteger, index=True, comment='评论ID')
    note_id = Column(BigInteger, index=True, comment='笔记ID')
    content = Column(Text, comment='评论内容')
    create_time = Column(BigInteger, comment='创建时间戳')
    create_date_time = Column(String(255), index=True, comment='创建日期时间')
    comment_like_count = Column(String(255), default='0', comment='评论点赞数')
    sub_comment_count = Column(String(255), default='0', comment='子评论数')
    parent_comment_id = Column(String(255), comment='父评论ID')
    task_id = Column(String(255), index=True, default='', comment='任务ID')

class WeiboCreator(Base):
    __tablename__ = 'weibo_creator'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    ip_location = Column(Text, comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    desc = Column(Text, comment='描述')
    gender = Column(String(255), default='', comment='性别')
    follows = Column(String(255), default='0', comment='关注数')
    fans = Column(String(255), default='0', comment='粉丝数')
    tag_list = Column(Text, comment='标签列表')

class XhsCreator(Base):
    __tablename__ = 'xhs_creator'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    ip_location = Column(Text, comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    desc = Column(Text, comment='描述')
    gender = Column(String(255), default='', comment='性别')
    follows = Column(String(255), default='0', comment='关注数')
    fans = Column(String(255), default='0', comment='粉丝数')
    interaction = Column(String(255), default='0', comment='互动数')
    tag_list = Column(Text, comment='标签列表')

class XhsNote(Base):
    __tablename__ = 'xhs_note'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    ip_location = Column(Text, comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    note_id = Column(String(255), index=True, comment='笔记ID')
    type = Column(String(255), default='', comment='笔记类型')
    title = Column(Text, comment='笔记标题')
    desc = Column(Text, comment='笔记描述')
    video_url = Column(Text, comment='视频URL')
    time = Column(BigInteger, index=True, comment='时间戳')
    last_update_time = Column(BigInteger, comment='最后更新时间戳')
    liked_count = Column(String(255), default='0', comment='点赞数')
    collected_count = Column(String(255), default='0', comment='收藏数')
    comment_count = Column(String(255), default='0', comment='评论数')
    share_count = Column(String(255), default='0', comment='分享数')
    image_list = Column(Text, comment='图片列表')
    tag_list = Column(Text, comment='标签列表')
    note_url = Column(Text, comment='笔记URL')
    source_keyword = Column(Text, default='', comment='来源关键词')
    xsec_token = Column(String(255), default='', comment='Xsec Token')
    task_id = Column(String(255), index=True, default='', comment='任务ID')

class XhsNoteComment(Base):
    __tablename__ = 'xhs_note_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(255), comment='用户ID')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    ip_location = Column(Text, comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    comment_id = Column(String(255), index=True, comment='评论ID')
    create_time = Column(BigInteger, index=True, comment='创建时间戳')
    note_id = Column(String(255), comment='笔记ID')
    content = Column(Text, comment='评论内容')
    sub_comment_count = Column(Integer, comment='子评论数')
    pictures = Column(Text, comment='图片')
    parent_comment_id = Column(String(255), comment='父评论ID')
    like_count = Column(String(255), default='0', comment='点赞数')
    task_id = Column(String(255), index=True, default='', comment='任务ID')

class TiebaNote(Base):
    __tablename__ = 'tieba_note'
    id = Column(Integer, primary_key=True, comment='主键ID')
    note_id = Column(String(644), index=True, comment='笔记ID')
    title = Column(Text, comment='笔记标题')
    desc = Column(Text, comment='笔记描述')
    note_url = Column(Text, comment='笔记URL')
    publish_time = Column(String(255), index=True, comment='发布时间')
    user_link = Column(Text, default='', comment='用户链接')
    user_nickname = Column(Text, default='', comment='用户昵称')
    user_avatar = Column(Text, default='', comment='用户头像')
    tieba_id = Column(String(255), default='', comment='贴吧ID')
    tieba_name = Column(Text, comment='贴吧名称')
    tieba_link = Column(Text, comment='贴吧链接')
    total_replay_num = Column(Integer, default=0, comment='总回复数')
    total_replay_page = Column(Integer, default=0, comment='总回复页数')
    ip_location = Column(Text, default='', comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    source_keyword = Column(Text, default='', comment='来源关键词')

class TiebaComment(Base):
    __tablename__ = 'tieba_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    comment_id = Column(String(255), index=True, comment='评论ID')
    parent_comment_id = Column(String(255), default='', comment='父评论ID')
    content = Column(Text, comment='评论内容')
    user_link = Column(Text, default='', comment='用户链接')
    user_nickname = Column(Text, default='', comment='用户昵称')
    user_avatar = Column(Text, default='', comment='用户头像')
    tieba_id = Column(String(255), default='', comment='贴吧ID')
    tieba_name = Column(Text, comment='贴吧名称')
    tieba_link = Column(Text, comment='贴吧链接')
    publish_time = Column(String(255), index=True, comment='发布时间')
    ip_location = Column(Text, default='', comment='IP地址位置')
    sub_comment_count = Column(Integer, default=0, comment='子评论数')
    note_id = Column(String(255), index=True, comment='笔记ID')
    note_url = Column(Text, comment='笔记URL')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    task_id = Column(String(255), index=True, default='', comment='任务ID')

class TiebaCreator(Base):
    __tablename__ = 'tieba_creator'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(64), comment='用户ID')
    user_name = Column(Text, comment='用户名')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    ip_location = Column(Text, comment='IP地址位置')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    gender = Column(String(255), default='', comment='性别')
    follows = Column(String(255), default='0', comment='关注数')
    fans = Column(String(255), default='0', comment='粉丝数')
    registration_duration = Column(String(255), default='', comment='注册时长')

class ZhihuContent(Base):
    __tablename__ = 'zhihu_content'
    id = Column(Integer, primary_key=True, comment='主键ID')
    content_id = Column(String(64), index=True, comment='内容ID')
    content_type = Column(String(255), default='', comment='内容类型')
    content_text = Column(Text, comment='内容文本')
    content_url = Column(Text, comment='内容URL')
    question_id = Column(String(255), comment='问题ID')
    title = Column(Text, comment='标题')
    desc = Column(Text, comment='描述')
    created_time = Column(String(32), index=True, comment='创建时间')
    updated_time = Column(String(255), default='', comment='更新时间')
    voteup_count = Column(Integer, default=0, comment='赞同数')
    comment_count = Column(Integer, default=0, comment='评论数')
    source_keyword = Column(Text, comment='来源关键词')
    user_id = Column(String(255), comment='用户ID')
    user_link = Column(Text, comment='用户链接')
    user_nickname = Column(Text, comment='用户昵称')
    user_avatar = Column(Text, comment='用户头像')
    user_url_token = Column(String(255), default='', comment='用户URL Token')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')

    # persist-1<persist1@126.com>
    # Reason: Fixed ORM model definition error, ensuring consistency with database table structure.
    # Side effects: None
    # Rollback strategy: Restore this line

class ZhihuComment(Base):
    __tablename__ = 'zhihu_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    comment_id = Column(String(64), index=True, comment='评论ID')
    parent_comment_id = Column(String(64), comment='父评论ID')
    content = Column(Text, comment='评论内容')
    publish_time = Column(String(32), index=True, comment='发布时间')
    ip_location = Column(Text, comment='IP地址位置')
    sub_comment_count = Column(Integer, default=0, comment='子评论数')
    like_count = Column(Integer, default=0, comment='点赞数')
    dislike_count = Column(Integer, default=0, comment='点踩数')
    content_id = Column(String(64), index=True, comment='内容ID')
    content_type = Column(String(255), default='', comment='内容类型')
    user_id = Column(String(64), comment='用户ID')
    user_link = Column(Text, comment='用户链接')
    user_nickname = Column(Text, comment='用户昵称')
    user_avatar = Column(Text, comment='用户头像')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    task_id = Column(String(255), index=True, default='', comment='任务ID')

class ZhihuCreator(Base):
    __tablename__ = 'zhihu_creator'
    id = Column(Integer, primary_key=True, comment='主键ID')
    user_id = Column(String(64), unique=True, index=True, comment='用户ID')
    user_link = Column(Text, comment='用户链接')
    user_nickname = Column(Text, comment='用户昵称')
    user_avatar = Column(Text, comment='用户头像')
    url_token = Column(String(255), default='', comment='URL Token')
    gender = Column(String(255), default='', comment='性别')
    ip_location = Column(Text, comment='IP地址位置')
    follows = Column(Integer, default=0, comment='关注数')
    fans = Column(Integer, default=0, comment='粉丝数')
    anwser_count = Column(Integer, default=0, comment='回答数')
    video_count = Column(Integer, default=0, comment='视频数')
    question_count = Column(Integer, default=0, comment='问题数')
    article_count = Column(Integer, default=0, comment='文章数')
    column_count = Column(Integer, default=0, comment='专栏数')
    get_voteup_count = Column(Integer, default=0, comment='获赞数')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')


class TaskDataMapping(Base):
    """任务数据关联表 - 用于关联任务和爬取的数据"""
    __tablename__ = 'task_data_mapping'
    id = Column(Integer, primary_key=True, comment='主键ID')
    task_id = Column(String(255), index=True, comment='任务ID')
    platform = Column(String(20), comment='平台')
    data_type = Column(String(20), comment='数据类型: note, comment, video')
    data_id = Column(String(255), comment='数据ID')
    user_id = Column(String(255), comment='用户ID')
    nickname = Column(String(255), comment='用户昵称')
    title = Column(Text, comment='标题')
    content = Column(Text, comment='内容')
    url = Column(Text, comment='链接')
    add_ts = Column(BigInteger, comment='添加时间戳')

class CrawlerTaskModel(Base):
    """爬虫任务表 - 存储任务配置和状态"""
    __tablename__ = 'crawler_task'
    id = Column(String(255), primary_key=True, comment='任务ID')
    name = Column(String(255), nullable=False, comment='任务名称')
    platform = Column(String(20), nullable=False, comment='平台: xhs, douyin, kuaishou, weibo, zhihu, tieba, bilibili')
    keywords = Column(Text, default='', comment='关键词列表，JSON数组字符串')
    crawl_type = Column(String(20), default='search', comment='爬取类型: search, creator, trending, detail')
    data_types = Column(Text, default='["note","comment"]', comment='数据类型，JSON数组字符串')
    max_notes = Column(Integer, default=100, comment='预计获客数量')
    min_lead_score = Column(Integer, default=50, comment='最小线索评分')
    enable_lead_capture = Column(Integer, default=1, comment='是否启用获客')
    schedule_type = Column(String(20), default='once', comment='调度类型: once, daily, weekly')
    schedule_time = Column(String(8), default='09:00', comment='调度执行时间(HH:MM),daily/weekly 类型生效')
    schedule_weekday = Column(Integer, default=1, comment='周几执行(1-7),weekly 类型生效')
    last_scheduled_ts = Column(BigInteger, default=0, comment='上次调度执行时间戳')
    next_scheduled_ts = Column(BigInteger, default=0, comment='下次调度执行时间戳')
    status = Column(String(20), default='pending', comment='状态: pending, running, paused, completed, failed, cancelled')
    total_crawled = Column(Integer, default=0, comment='已爬取数量')
    total_leads = Column(Integer, default=0, comment='已获客数量')
    created_ts = Column(BigInteger, comment='创建时间戳')
    updated_ts = Column(BigInteger, comment='更新时间戳')
    completed_ts = Column(BigInteger, comment='完成时间戳')
    error_message = Column(Text, default='', comment='错误信息')
    promo_config = Column(Text, default='', comment='推广配置JSON: 产品名称、推广链接、产品描述、价格信息、联系方式等')
    publish_time_type = Column(Integer, default=0, comment='发布时间过滤: 0=不限, 1=一天内, 7=一周内, 180=半年内')
    owner_user_id = Column(String(64), index=True, default='', comment='归属用户ID(数据隔离)')
    # 精准获客配置(从 getuser-canrun 迁移)
    business_intent = Column(Text, default='', comment='业务意图描述(如"寻找需要学琵琶的用户")')
    intent_keywords = Column(Text, default='', comment='意向词 JSON 数组(严格双词匹配用)')
    exclude_keywords = Column(Text, default='', comment='排除词 JSON 数组(命中即丢弃)')
    target_role = Column(String(20), default='c端用户', comment='目标角色: c端用户/厂家供应商/不限')
    target_regions = Column(Text, default='', comment='目标地区 JSON 数组(可选)')


class TaskLogModel(Base):
    """任务日志表 - 存储任务运行日志"""
    __tablename__ = 'task_log'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    task_id = Column(String(255), index=True, nullable=False, comment='任务ID')
    level = Column(String(20), default='info', comment='日志级别: debug, info, warning, error, success')
    message = Column(Text, nullable=False, comment='日志内容')
    add_ts = Column(BigInteger, comment='添加时间戳')


class CustomerLead(Base):
    """获客线索表 - 存储识别出的潜在客户咨询"""
    __tablename__ = 'customer_lead'
    id = Column(Integer, primary_key=True, comment='主键ID')
    task_id = Column(String(255), index=True, comment='任务ID')
    platform = Column(String(20), comment='平台: xhs, douyin, kuaishou, weibo, zhihu, tieba, bilibili')
    data_type = Column(String(20), comment='数据类型: note, comment, video, answer')
    data_id = Column(String(255), comment='原始数据ID')
    user_id = Column(String(255), index=True, comment='用户ID')
    sec_uid = Column(String(255), default='', comment='安全用户ID（抖音等平台主页链接用）')
    nickname = Column(String(255), comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    ip_location = Column(String(255), default='', comment='IP地址位置')
    content = Column(Text, comment='咨询内容')
    title = Column(Text, comment='帖子标题')
    url = Column(Text, comment='链接')
    matched_keywords = Column(Text, comment='匹配到的关键词')
    intent_type = Column(String(50), comment='意图类型: inquiry, recommendation, comparison, purchase')
    lead_score = Column(Integer, default=0, comment='线索评分 0-100')
    status = Column(String(20), default='new', comment='状态: new, contacted, qualified, converted, ignored')
    notes = Column(Text, comment='备注')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')
    create_time = Column(BigInteger, comment='评论真实创建时间戳(秒)')
    owner_user_id = Column(String(64), index=True, default='', comment='归属用户ID(数据隔离)')
    # 源视频/作品信息(评论场景下,记录该评论所属的视频/作品,方便回复评论时知道上下文)
    source_aweme_id = Column(String(255), default='', comment='源视频/作品ID')
    source_video_title = Column(Text, default='', comment='源视频标题')
    source_video_desc = Column(Text, default='', comment='源视频描述')
    source_video_url = Column(Text, default='', comment='源视频链接')
    source_cover_url = Column(Text, default='', comment='源视频封面URL')
    source_author_nickname = Column(String(255), default='', comment='源视频作者昵称')
    # 增强字段(客户需求:支持复制和打开链接)
    comment_url = Column(Text, default='', comment='原评论链接')
    profile_url = Column(Text, default='', comment='用户主页链接')
    platform_display_id = Column(String(255), default='', comment='平台内可搜索用户ID(如抖音号/小红书号)')
    # 获客采集增强字段(从 getuser-canrun 迁移)
    content_hash = Column(String(64), index=True, default='', comment='内容 md5 指纹,用于精确去重')
    dup_count = Column(Integer, default=1, comment='重复命中次数(相似内容累加)')
    role_tag = Column(String(20), default='', comment='角色分类: supplier/consumer/neutral')
    contact_phone = Column(String(20), default='', comment='采集到的联系电话')
    contact_wechat = Column(String(64), default='', comment='采集到的微信号')
    bio_text = Column(Text, default='', comment='用户主页简介(联系方式提取来源)')
    contact_status = Column(String(16), default='none', comment='联系方式采集状态: none/pending/found/not_found')
    reply_monitor_ts = Column(BigInteger, default=0, comment='上次回复监控扫描时间戳')


class LeadCommentReply(Base):
    """线索评论回复监测表 - 监测线索用户在我们触达的视频评论区的新回复(抖音版,从 getuser-canrun 迁移)

    用途: 当线索被识别/触达后,定期回扫其源视频评论区,捕获:
    1. 同一 user_id 的新评论(线索回来再说)
    2. 回复线索原评论的子评论(parent_comment_id == 线索 comment_id)
    供线索转化闭环使用。
    """
    __tablename__ = 'lead_comment_reply'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    lead_id = Column(Integer, index=True, comment='关联线索ID(CustomerLead.id)')
    task_id = Column(String(255), index=True, default='', comment='关联任务ID')
    platform = Column(String(20), default='douyin', comment='平台')
    aweme_id = Column(String(255), index=True, default='', comment='源视频ID')
    comment_id = Column(String(255), index=True, default='', comment='被监测到的回复评论ID')
    parent_comment_id = Column(String(255), default='', comment='父评论ID(回复的是哪条)')
    user_id = Column(String(255), default='', comment='回复者用户ID')
    sec_uid = Column(String(255), default='', comment='回复者安全用户ID')
    nickname = Column(String(255), default='', comment='回复者昵称')
    avatar = Column(Text, default='', comment='回复者头像')
    content = Column(Text, default='', comment='回复内容')
    like_count = Column(String(255), default='0', comment='点赞数')
    create_time = Column(BigInteger, default=0, comment='回复创建时间戳(秒)')
    is_from_lead = Column(Integer, default=0, comment='是否来自线索本人: 0=否, 1=是')
    is_read = Column(Integer, default=0, comment='是否已读: 0=否, 1=是')
    owner_user_id = Column(String(64), index=True, default='', comment='归属用户ID(数据隔离)')
    add_ts = Column(BigInteger, default=0, comment='采集时间戳')


class OutreachRecord(Base):
    """触达记录表 - 存储私信发送记录"""
    __tablename__ = 'outreach_record'
    id = Column(Integer, primary_key=True, comment='主键ID')
    task_id = Column(String(255), index=True, comment='任务ID')
    outreach_task_id = Column(String(255), index=True, comment='触达任务ID')
    platform = Column(String(20), comment='平台: douyin, xhs, kuaishou, weibo')
    user_id = Column(String(255), index=True, comment='目标用户ID')
    sec_uid = Column(String(255), comment='安全用户ID')
    nickname = Column(String(255), comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    user_url = Column(Text, comment='用户主页链接')
    message_content = Column(Text, comment='发送的消息内容')
    status = Column(String(20), default='pending', comment='发送状态: pending, success, failed')
    error_message = Column(Text, comment='错误信息')
    screenshot = Column(String(255), comment='发送结果截图文件名')
    send_time = Column(BigInteger, comment='发送时间戳')
    add_ts = Column(BigInteger, comment='添加时间戳')
    owner_user_id = Column(String(64), index=True, default='', comment='归属用户ID(数据隔离)')


class OutreachTaskModel(Base):
    """触达任务表 - 存储私信触达任务的完整状态"""
    __tablename__ = 'outreach_task'
    id = Column(String(64), primary_key=True, comment='触达任务ID')
    user_id = Column(String(255), index=True, comment='目标用户ID')
    sec_uid = Column(String(255), comment='安全用户ID')
    platform = Column(String(20), default='douyin', comment='平台: douyin, xhs')
    content = Column(Text, comment='发送的消息内容')
    nickname = Column(String(255), default='', comment='用户昵称')
    status = Column(String(20), default='pending', comment='状态: pending, running, success, failed, cancelled')
    error_message = Column(Text, default='', comment='错误信息')
    result = Column(Text, default='{}', comment='执行结果JSON')
    steps = Column(Text, default='[]', comment='步骤列表JSON')
    logs = Column(Text, default='[]', comment='日志列表JSON')
    screenshot = Column(String(255), default='', comment='结果截图文件名')
    created_at = Column(BigInteger, comment='创建时间戳')
    updated_at = Column(BigInteger, comment='更新时间戳')
    owner_user_id = Column(String(64), index=True, default='', comment='归属用户ID(数据隔离)')


class DouyinDmRecord(Base):
    """抖音私信发送记录表"""
    __tablename__ = 'douyin_dm_record'
    id = Column(Integer, primary_key=True, comment='主键ID')
    sec_uid = Column(String(255), index=True, comment='目标用户sec_uid')
    user_id = Column(String(255), comment='目标用户ID')
    nickname = Column(String(255), comment='用户昵称')
    message = Column(Text, comment='发送的私信内容')
    aweme_id = Column(String(255), comment='来源视频ID')
    success = Column(Integer, default=0, comment='是否发送成功: 0失败, 1成功')
    error = Column(Text, default='', comment='错误信息')
    task_id = Column(String(255), index=True, default='', comment='任务ID')
    add_ts = Column(BigInteger, comment='添加时间戳')


class AutoOutreachJobModel(Base):
    """自动获客任务表 - 持久化后台运行状态"""
    __tablename__ = 'auto_outreach_job'
    id = Column(Integer, primary_key=True, comment='主键ID')
    job_id = Column(String(64), unique=True, index=True, comment='任务唯一ID')
    task_id = Column(String(255), index=True, comment='关联的爬虫任务ID')
    platform = Column(String(20), default='douyin', comment='平台')
    intent_level = Column(String(20), default='high', comment='意向等级')
    status = Column(String(20), default='running', comment='状态: running, completed, cancelled, failed')
    total = Column(Integer, default=0, comment='总目标数')
    completed = Column(Integer, default=0, comment='已完成数')
    success = Column(Integer, default=0, comment='成功数')
    failed = Column(Integer, default=0, comment='失败数')
    skipped = Column(Integer, default=0, comment='跳过数')
    results = Column(Text, default='[]', comment='发送结果JSON')
    outreach_list = Column(Text, default='[]', comment='目标用户列表JSON')
    auto_send = Column(Integer, default=1, comment='是否自动发送')
    interval_seconds = Column(Integer, default=90, comment='发送间隔秒数')
    current_index = Column(Integer, default=0, comment='当前发送到第几个')
    error_message = Column(Text, default='', comment='错误信息')
    created_at = Column(BigInteger, comment='创建时间戳')
    finished_at = Column(BigInteger, default=0, comment='完成时间戳')
    updated_at = Column(BigInteger, comment='更新时间戳')
    data_source = Column(String(20), default='comment', comment='数据来源: customer_lead=客户线索, comment=评论分析')
    owner_user_id = Column(String(64), index=True, default='', comment='归属用户ID(数据隔离)')


# ==================== 线索商业化相关表 ====================

class BusinessUser(Base):
    """业务用户表 - 存储客户(家具公司)和销售人员信息"""
    __tablename__ = 'business_user'
    id = Column(String(64), primary_key=True, comment='业务用户ID')
    username = Column(String(255), unique=True, comment='登录账号')
    password_hash = Column(String(255), comment='密码哈希')
    nickname = Column(String(255), comment='显示名称')
    role = Column(String(20), default='customer', comment='角色: customer=客户(家具公司), sales=销售, admin=管理员')
    company_name = Column(String(255), default='', comment='公司名称(客户用)')
    contact_phone = Column(String(255), default='', comment='联系电话')
    contact_email = Column(String(255), default='', comment='联系邮箱')
    balance = Column(BigInteger, default=0, comment='账户余额(分,便于精确计算)')
    total_spent = Column(BigInteger, default=0, comment='累计消费(分)')
    status = Column(String(20), default='active', comment='状态: active, disabled, deleted')
    # 销售特有字段
    sales_region = Column(String(255), default='', comment='负责地域(销售用,逗号分隔)')
    sales_quota = Column(Integer, default=100, comment='每日线索配额(销售用)')
    # 客户特有字段
    webhook_url = Column(Text, default='', comment='Webhook推送地址(客户用)')
    api_key = Column(String(255), default='', comment='API密钥(客户用)')
    auto_push = Column(Integer, default=0, comment='是否自动推送新线索: 0关闭, 1开启')
    # 归属和统计
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID')
    assigned_leads_count = Column(Integer, default=0, comment='已分配线索数')
    converted_leads_count = Column(Integer, default=0, comment='已转化线索数')
    created_ts = Column(BigInteger, comment='创建时间戳')
    updated_ts = Column(BigInteger, comment='更新时间戳')
    last_login_ts = Column(BigInteger, default=0, comment='最后登录时间戳')


class LeadPackage(Base):
    """线索包表 - 打包销售给客户的线索组合"""
    __tablename__ = 'lead_package'
    id = Column(String(64), primary_key=True, comment='线索包ID')
    name = Column(String(255), comment='包名')
    description = Column(Text, default='', comment='描述')
    platform = Column(String(20), default='', comment='平台筛选')
    task_id = Column(String(255), default='', comment='任务筛选')
    min_score = Column(Integer, default=0, comment='最低意向分')
    max_score = Column(Integer, default=100, comment='最高意向分')
    level = Column(String(20), default='', comment='意向等级: high/medium/low/all')
    ip_location = Column(String(255), default='', comment='地域筛选')
    keyword = Column(String(255), default='', comment='关键词筛选')
    total_count = Column(Integer, default=0, comment='线索总数')
    available_count = Column(Integer, default=0, comment='可售数量')
    sold_count = Column(Integer, default=0, comment='已售数量')
    price_per_lead = Column(Integer, default=0, comment='单价(分)')
    total_price = Column(Integer, default=0, comment='总价(分)')
    expire_days = Column(Integer, default=90, comment='有效期天数')
    status = Column(String(20), default='draft', comment='状态: draft/active/sold_out/discontinued')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID')
    created_ts = Column(BigInteger, comment='创建时间戳')
    updated_ts = Column(BigInteger, comment='更新时间戳')
    publish_ts = Column(BigInteger, default=0, comment='发布时间戳')


class LeadAssignment(Base):
    """线索分配记录表 - 记录线索分配给客户/销售的历史"""
    __tablename__ = 'lead_assignment'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    lead_id = Column(Integer, index=True, comment='线索ID(CustomerLead.id)')
    package_id = Column(String(64), default='', comment='线索包ID')
    business_user_id = Column(String(64), index=True, comment='分配给的业务用户ID')
    assign_type = Column(String(20), default='purchase', comment='分配类型: purchase=购买, manual=手动分配, auto=自动分配')
    status = Column(String(20), default='assigned', comment='状态: assigned=已分配, used=已使用, recalled=已回收, expired=已过期')
    price_paid = Column(Integer, default=0, comment='支付价格(分)')
    expire_ts = Column(BigInteger, default=0, comment='过期时间戳(0=永不过期)')
    assigned_ts = Column(BigInteger, default=0, comment='分配时间戳')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID')


class FollowUpRecord(Base):
    """跟进记录表 - 销售跟进线索的记录"""
    __tablename__ = 'follow_up_record'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    lead_id = Column(Integer, index=True, comment='线索ID')
    lead_assignment_id = Column(Integer, default=0, comment='分配记录ID')
    business_user_id = Column(String(64), index=True, comment='跟进人ID(销售)')
    action_type = Column(String(20), default='call', comment='跟进方式: call=电话, message=私信, visit=拜访, wechat=微信')
    action_ts = Column(BigInteger, comment='跟进时间戳')
    result = Column(String(20), default='pending', comment='跟进结果: pending=待跟进, contacted=已联系, interested=有意向, not_interested=无意向, converted=已成交, failed=失败')
    notes = Column(Text, default='', comment='跟进备注')
    next_follow_ts = Column(BigInteger, default=0, comment='下次跟进时间戳')
    created_ts = Column(BigInteger, comment='创建时间戳')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID')


class PurchaseOrder(Base):
    """购买订单表 - 客户购买线索包的订单"""
    __tablename__ = 'purchase_order'
    id = Column(String(64), primary_key=True, comment='订单ID')
    package_id = Column(String(64), index=True, comment='线索包ID')
    business_user_id = Column(String(64), index=True, comment='买家ID')
    lead_count = Column(Integer, default=0, comment='购买线索数')
    total_price = Column(Integer, default=0, comment='订单金额(分)')
    payment_method = Column(String(20), default='balance', comment='支付方式: balance=余额, offline=线下转账')
    status = Column(String(20), default='pending', comment='订单状态: pending/paid/completed/cancelled/refunded')
    paid_ts = Column(BigInteger, default=0, comment='支付时间戳')
    completed_ts = Column(BigInteger, default=0, comment='完成时间戳')
    created_ts = Column(BigInteger, comment='创建时间戳')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID')


class ApiClient(Base):
    """API客户端表 - 对接客户CRM系统的配置"""
    __tablename__ = 'api_client'
    id = Column(String(64), primary_key=True, comment='API客户端ID')
    name = Column(String(255), comment='客户端名称')
    business_user_id = Column(String(64), index=True, comment='关联业务用户ID')
    api_key = Column(String(255), unique=True, comment='API密钥')
    api_secret = Column(String(255), comment='API密钥密码')
    webhook_url = Column(Text, default='', comment='推送地址')
    callback_url = Column(Text, default='', comment='回调地址(接收客户状态更新)')
    # 筛选条件(JSON)
    filters = Column(Text, default='{}', comment='推送筛选条件JSON: platform/min_score/ip_location等')
    push_mode = Column(String(20), default='batch', comment='推送模式: batch=批量, realtime=实时')
    push_interval = Column(Integer, default=300, comment='批量推送间隔(秒)')
    status = Column(String(20), default='active', comment='状态: active/disabled')
    last_push_ts = Column(BigInteger, default=0, comment='最后推送时间戳')
    total_pushed = Column(Integer, default=0, comment='累计推送数')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID')
    created_ts = Column(BigInteger, comment='创建时间戳')
    updated_ts = Column(BigInteger, comment='更新时间戳')


class UserNeedAnalysis(Base):
    """用户需求分析表 - 持久化需求分析结果,支持历史回看"""
    __tablename__ = 'user_need_analysis'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    lead_id = Column(Integer, index=True, comment='关联线索ID(CustomerLead.id)')
    task_id = Column(String(64), index=True, comment='关联任务ID')
    user_id = Column(String(128), index=True, comment='平台用户ID')
    nickname = Column(String(255), default='', comment='用户昵称')
    content = Column(Text, default='', comment='原始评论内容')
    need_type = Column(String(32), default='general', comment='需求类型: product_inquiry/price_sensitive/tutorial_request/cooperation/frustration/comparison/general')
    need_type_name = Column(String(64), default='', comment='需求类型中文名')
    pain_points = Column(Text, default='[]', comment='痛点列表JSON')
    need_summary = Column(Text, default='', comment='需求摘要')
    pitch = Column(Text, default='', comment='推荐话术')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID(数据隔离)')
    created_ts = Column(BigInteger, comment='创建时间戳')


class AdContent(Base):
    """广告内容表 - 持久化生成的文案结果,支持历史回看和复用"""
    __tablename__ = 'ad_content'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    lead_id = Column(Integer, index=True, comment='关联线索ID')
    task_id = Column(String(64), index=True, comment='关联任务ID')
    user_id = Column(String(128), index=True, comment='平台用户ID')
    nickname = Column(String(255), default='', comment='用户昵称')
    need_type = Column(String(32), default='general', comment='需求类型')
    tone = Column(String(32), default='friendly', comment='语气: friendly/professional/passionate')
    direct_message = Column(Text, default='', comment='私信文案')
    comment_reply = Column(Text, default='', comment='评论回复文案')
    product_id = Column(String(64), default='', comment='关联产品ID(AdContentProduct.id)')
    product_name = Column(String(255), default='', comment='产品名称(冗余,便于历史展示)')
    promo_link = Column(Text, default='', comment='推广链接(已混淆)')
    used = Column(Boolean, default=False, comment='是否已用于触达')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID(数据隔离)')
    created_ts = Column(BigInteger, comment='创建时间戳')


class ProductInfo(Base):
    """产品库表 - 替代任务配置中的 promo_config,支持多产品管理和复用"""
    __tablename__ = 'product_info'
    id = Column(String(64), primary_key=True, comment='产品ID')
    name = Column(String(255), index=True, comment='产品名称')
    desc = Column(Text, default='', comment='产品描述')
    product_desc = Column(Text, default='', comment='详细产品说明(用于文案生成)')
    promo_link = Column(Text, default='', comment='推广链接')
    contact_wechat = Column(String(128), default='', comment='联系微信')
    price_info = Column(String(255), default='', comment='价格信息')
    discount_info = Column(String(255), default='', comment='优惠信息')
    free_quota = Column(String(128), default='', comment='免费额度')
    solution_desc = Column(Text, default='', comment='解决方案描述')
    tutorial_name = Column(String(255), default='', comment='教程名称')
    tutorial_desc = Column(Text, default='', comment='教程描述')
    cooperation_desc = Column(Text, default='', comment='合作描述')
    commission_rate = Column(String(64), default='', comment='佣金比例')
    category = Column(String(64), default='', comment='产品分类')
    status = Column(String(20), default='active', comment='状态: active/disabled')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID(数据隔离)')
    created_ts = Column(BigInteger, comment='创建时间戳')
    updated_ts = Column(BigInteger, comment='更新时间戳')


class Notification(Base):
    """站内消息表 - 系统通知/任务结果通知/线索提醒等"""
    __tablename__ = 'notification'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID(数据隔离)')
    title = Column(String(255), nullable=False, comment='消息标题')
    content = Column(Text, default='', comment='消息内容')
    msg_type = Column(String(32), default='info', comment='消息类型: info/success/warning/error/lead/task')
    extra = Column(Text, default='{}', comment='附加数据JSON: lead_id/task_id/链接等')
    is_read = Column(Integer, default=0, comment='是否已读: 0=未读, 1=已读')
    created_ts = Column(BigInteger, comment='创建时间戳')


class XTwitterPost(Base):
    __tablename__ = 'x_twitter_post'
    id = Column(Integer, primary_key=True, comment='主键ID')
    post_id = Column(String(255), index=True, comment='推文ID')
    user_id = Column(String(255), comment='用户ID')
    username = Column(String(255), comment='用户名')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    content = Column(Text, comment='推文内容')
    image_urls = Column(Text, comment='图片列表JSON')
    video_url = Column(Text, comment='视频URL')
    video_duration = Column(Integer, default=0, comment='视频时长')
    likes_count = Column(String(255), default='0', comment='点赞数')
    retweets_count = Column(String(255), default='0', comment='转发数')
    replies_count = Column(String(255), default='0', comment='回复数')
    quotes_count = Column(String(255), default='0', comment='引用数')
    bookmarks_count = Column(String(255), default='0', comment='收藏数')
    views_count = Column(String(255), default='0', comment='浏览数')
    created_at = Column(BigInteger, index=True, comment='创建时间戳')
    post_url = Column(Text, comment='推文链接')
    is_retweet = Column(Boolean, default=False, comment='是否转发')
    original_post_id = Column(String(255), comment='原始推文ID')
    lang = Column(String(50), default='', comment='语言')
    source_keyword = Column(Text, default='', comment='来源关键词')
    hashtags = Column(Text, default='', comment='标签列表')
    task_id = Column(String(255), index=True, default='', comment='任务ID')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')


class XTwitterComment(Base):
    __tablename__ = 'x_twitter_comment'
    id = Column(Integer, primary_key=True, comment='主键ID')
    comment_id = Column(String(255), index=True, comment='评论ID')
    post_id = Column(String(255), index=True, comment='推文ID')
    user_id = Column(String(255), comment='用户ID')
    username = Column(String(255), comment='用户名')
    nickname = Column(Text, comment='用户昵称')
    avatar = Column(Text, comment='用户头像')
    content = Column(Text, comment='评论内容')
    likes_count = Column(String(255), default='0', comment='点赞数')
    replies_count = Column(String(255), default='0', comment='回复数')
    created_at = Column(BigInteger, index=True, comment='创建时间戳')
    parent_comment_id = Column(String(255), comment='父评论ID')
    task_id = Column(String(255), index=True, default='', comment='任务ID')
    add_ts = Column(BigInteger, comment='添加时间戳')
    last_modify_ts = Column(BigInteger, comment='最后修改时间戳')


class XTwitterVideoBreakdown(Base):
    __tablename__ = 'x_twitter_video_breakdown'
    id = Column(Integer, primary_key=True, comment='主键ID')
    post_id = Column(String(255), index=True, comment='推文ID')
    post_url = Column(Text, comment='推文链接')
    script = Column(Text, comment='脚本分析')
    storyboards = Column(Text, comment='分镜拆解JSON')
    key_points = Column(Text, comment='关键要点JSON')
    suggested_comments = Column(Text, comment='推荐评论JSON')
    add_ts = Column(BigInteger, comment='添加时间戳')


class XTwitterExplainerVideoTask(Base):
    """OpenNotebook 解说视频任务的本地所有权映射。"""

    __tablename__ = 'x_twitter_explainer_video_task'
    __table_args__ = (
        UniqueConstraint(
            'owner_user_id',
            'idempotency_key',
            name='uq_explainer_video_owner_idempotency',
        ),
    )
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    local_task_id = Column(String(64), unique=True, index=True, nullable=False, comment='返回前端的本地任务ID')
    provider_task_id = Column(String(255), default='', index=True, comment='OpenNotebook 任务ID')
    owner_user_id = Column(String(64), index=True, nullable=False, comment='归属系统用户ID')
    idempotency_key = Column(String(64), nullable=True, comment='用户生成意图 UUID')
    request_hash = Column(String(64), default='', comment='幂等请求指纹')
    submission_payload = Column(Text, default='{}', comment='可安全重放的上游提交快照')
    connection_id = Column(Integer, default=0, index=True, comment='提交时的 OpenNotebook 连接ID')
    grant_id = Column(String(128), default='', comment='提交时的 OpenNotebook Grant ID')
    post_id = Column(String(255), index=True, nullable=False, comment='关联推文ID')
    tenant_id = Column(String(128), default='', comment='提交时 Tenant ID')
    workspace_id = Column(String(128), default='', comment='提交时 Workspace ID')
    model = Column(String(128), default='', comment='视频模型')
    model_name = Column(String(255), default='', comment='视频模型显示名')
    status = Column(String(32), default='submitting', index=True, comment='submitting/running/done/error')
    progress = Column(Integer, default=0, comment='进度 0-100')
    result_url = Column(Text, default='', comment='结果视频 URL')
    error = Column(Text, default='', comment='失败信息')
    cost = Column(String(64), default='0', comment='远程返回费用')
    created_ts = Column(BigInteger, comment='创建时间戳(秒)')
    updated_ts = Column(BigInteger, comment='更新时间戳(秒)')
    finished_ts = Column(BigInteger, default=0, comment='完成时间戳(秒)')


class XTwitterSentComment(Base):
    """X Twitter 工作台已发送评论跟踪表
    记录通过工作台发送的每一条评论，用于后续监控回复和 AI 自动回复。
    """
    __tablename__ = 'x_twitter_sent_comment'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    # 评论所属平台: x/douyin/xiaohongshu/bilibili/weibo/kuaishou 等，默认 x（兼容历史数据）
    platform = Column(String(32), default='x', index=True, comment='评论所属平台: x/dy/xhs/bili/wb/ks')
    post_id = Column(String(255), index=True, comment='被评论的推文ID')
    post_url = Column(Text, comment='被评论的推文URL')
    post_content = Column(Text, comment='推文内容摘要（便于展示）')
    post_username = Column(String(255), comment='推文作者用户名')
    video_url = Column(Text, comment='推文视频URL')
    comment_content = Column(Text, comment='发送的评论内容')
    comment_url = Column(Text, comment='评论在 X.com 上的URL（若获取到）')
    # 索引:sent_status 用于状态筛选;sent_at 用于时间范围筛选;monitoring 用于监控任务查询
    sent_status = Column(String(32), default='pending', index=True, comment='发送状态: pending/success/failed')
    sent_error = Column(Text, default='', comment='失败原因')
    sent_at = Column(BigInteger, index=True, comment='发送时间戳')
    # 来源: workbench（手动工作台触发）, auto（自动批量评论）
    source = Column(String(32), default='workbench', comment='评论来源: workbench/auto')
    # 是否正在监控回复
    monitoring = Column(Integer, default=1, index=True, comment='是否监控回复: 0=停止, 1=进行中')
    # 最后一次检查回复的时间戳
    last_check_ts = Column(BigInteger, default=0, comment='最后检查回复时间戳')
    # 收到的回复数
    reply_count = Column(Integer, default=0, comment='收到的回复数')
    # AI 已自动回复数
    auto_replied_count = Column(Integer, default=0, comment='AI已自动回复数')
    add_ts = Column(BigInteger, comment='记录创建时间戳')
    last_modify_ts = Column(BigInteger, comment='记录更新时间戳')


class XTwitterCommentTemplate(Base):
    """X Twitter 工作台评论模板表

    预设评论模板,用于:
    1. 快速选择常用评论(避免每次都调 AI 生成)
    2. AI 生成时基于模板风格生成,保持一致性
    3. 统计哪类模板效果最好(配合效果分析)

    支持变量插值:{topic} {username} {keyword} 会在使用时替换。
    """
    __tablename__ = 'x_twitter_comment_template'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    name = Column(String(128), comment='模板名称(便于管理)')
    content = Column(Text, comment='模板内容,支持变量: {topic} {username} {keyword}')
    # 分类: greeting(问候), question(提问), insight(见解), humor(幽默), cta(行动号召), other
    category = Column(String(32), default='other', index=True, comment='分类: greeting/question/insight/humor/cta/other')
    # 标签(逗号分隔,便于搜索)
    tags = Column(String(255), default='', comment='标签,逗号分隔')
    # 使用次数(每次被选用 +1,用于统计热度)
    use_count = Column(Integer, default=0, comment='被使用次数')
    # 最后使用时间戳
    last_used_ts = Column(BigInteger, default=0, comment='最后使用时间戳')
    # 是否启用(软删除)
    is_active = Column(Integer, default=1, index=True, comment='是否启用: 0=禁用, 1=启用')
    # 创建者(预留多用户)
    created_by = Column(String(64), default='', comment='创建者用户ID')
    add_ts = Column(BigInteger, comment='记录创建时间戳')
    last_modify_ts = Column(BigInteger, comment='记录更新时间戳')


class XTwitterMonitoredPost(Base):
    """X Twitter 工作台监控的帖子表
    记录我们要监控的帖子（自己发的帖子），用于自动回复帖子下的评论。
    """
    __tablename__ = 'x_twitter_monitored_post'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    post_id = Column(String(255), index=True, comment='推文ID')
    post_url = Column(Text, comment='推文URL')
    post_content = Column(Text, comment='推文内容摘要')
    post_username = Column(String(255), comment='推文作者用户名')
    # 是否正在监控
    monitoring = Column(Integer, default=1, comment='是否监控: 0=停止, 1=进行中')
    # 最后一次检查时间戳
    last_check_ts = Column(BigInteger, default=0, comment='最后检查评论时间戳')
    # 总评论数
    total_comments = Column(Integer, default=0, comment='总评论数')
    # AI 已自动回复数
    auto_replied_count = Column(Integer, default=0, comment='AI已自动回复数')
    add_ts = Column(BigInteger, comment='记录创建时间戳')
    last_modify_ts = Column(BigInteger, comment='记录更新时间戳')


class XTwitterPostReply(Base):
    """X Twitter 工作台帖子评论回复表
    记录帖子下收到的评论，以及 AI 是否已经自动回复。
    """
    __tablename__ = 'x_twitter_post_reply'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    monitored_post_id = Column(Integer, index=True, comment='关联 XTwitterMonitoredPost.id')
    post_id = Column(String(255), index=True, comment='推文ID')
    comment_id = Column(String(255), index=True, comment='评论ID')
    comment_url = Column(Text, comment='评论URL')
    commenter_user_id = Column(String(255), comment='评论者用户ID')
    commenter_username = Column(String(255), comment='评论者用户名')
    commenter_nickname = Column(Text, comment='评论者昵称')
    commenter_avatar = Column(Text, comment='评论者头像')
    comment_content = Column(Text, comment='评论内容')
    comment_likes_count = Column(String(255), default='0', comment='评论点赞数')
    comment_created_at = Column(BigInteger, comment='评论创建时间戳')
    # AI 自动回复信息
    auto_reply_status = Column(String(32), default='pending', comment='AI自动回复状态: pending/sent/failed/skipped')
    auto_reply_content = Column(Text, default='', comment='AI自动回复内容')
    auto_reply_url = Column(Text, default='', comment='AI自动回复URL')
    auto_replied_at = Column(BigInteger, default=0, comment='AI自动回复时间戳')
    add_ts = Column(BigInteger, comment='记录创建时间戳')
    last_modify_ts = Column(BigInteger, comment='记录更新时间戳')


class XTwitterTrendingTopic(Base):
    """X Twitter 热点话题表
    记录从 X.com Trending 页面采集的热点话题。
    """
    __tablename__ = 'x_twitter_trending_topic'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    topic = Column(String(500), index=True, comment='话题名称')
    topic_url = Column(Text, comment='话题URL')
    rank = Column(Integer, comment='排名')
    tweet_count = Column(String(100), default='', comment='推文数量')
    is_hashtag = Column(Integer, default=0, comment='是否是 hashtag: 0/1')
    crawl_ts = Column(BigInteger, comment='采集时间戳')
    add_ts = Column(BigInteger, comment='记录创建时间戳')
    last_modify_ts = Column(BigInteger, comment='记录更新时间戳')


class XTwitterTrendingPost(Base):
    """X Twitter 热点帖子表
    记录基于热点话题搜索到的热门帖子。
    """
    __tablename__ = 'x_twitter_trending_post'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    trending_topic_id = Column(Integer, index=True, comment='关联 XTwitterTrendingTopic.id')
    topic = Column(String(500), comment='所属话题')
    post_id = Column(String(255), index=True, comment='推文ID')
    post_url = Column(Text, comment='推文URL')
    username = Column(String(255), comment='用户名')
    nickname = Column(Text, comment='昵称')
    content = Column(Text, comment='推文内容')
    likes_count = Column(String(100), default='0', comment='点赞数')
    retweets_count = Column(String(100), default='0', comment='转发数')
    replies_count = Column(String(100), default='0', comment='回复数')
    views_count = Column(String(100), default='0', comment='浏览数')
    created_at = Column(BigInteger, comment='发布时间戳')
    video_url = Column(Text, comment='视频URL')
    image_url = Column(Text, comment='图片URL')
    # 索引:crawl_ts 用于热点列表 ORDER BY 优化
    crawl_ts = Column(BigInteger, index=True, comment='采集时间戳')
    add_ts = Column(BigInteger, comment='记录创建时间戳')
    last_modify_ts = Column(BigInteger, comment='记录更新时间戳')


class XTwitterReply(Base):
    """X Twitter 工作台收到的评论回复表
    记录其他用户对我们已发评论的回复，以及 AI 是否已经自动回复。
    """
    __tablename__ = 'x_twitter_reply'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    sent_comment_id = Column(Integer, index=True, comment='关联 XTwitterSentComment.id')
    post_id = Column(String(255), index=True, comment='原推文ID')
    reply_id = Column(String(255), index=True, comment='回复评论ID')
    reply_url = Column(Text, comment='回复评论URL')
    replier_user_id = Column(String(255), comment='回复者用户ID')
    replier_username = Column(String(255), comment='回复者用户名')
    replier_nickname = Column(Text, comment='回复者昵称')
    replier_avatar = Column(Text, comment='回复者头像')
    reply_content = Column(Text, comment='回复内容')
    reply_likes_count = Column(String(255), default='0', comment='回复点赞数')
    reply_created_at = Column(BigInteger, comment='回复创建时间戳')
    # AI 自动回复信息
    # 索引:auto_reply_status 用于统计和过滤;auto_replied_at 用于每日配额查询
    auto_reply_status = Column(String(32), default='pending', index=True, comment='AI自动回复状态: pending/sent/failed/skipped')
    auto_reply_content = Column(Text, default='', comment='AI自动回复内容')
    auto_reply_url = Column(Text, default='', comment='AI自动回复URL')
    auto_replied_at = Column(BigInteger, default=0, index=True, comment='AI自动回复时间戳')
    add_ts = Column(BigInteger, comment='记录创建时间戳')
    last_modify_ts = Column(BigInteger, comment='记录更新时间戳')


class IntentRule(Base):
    """意向识别规则表 - 替代 tasks.py 中的硬编码 STRONG_INTENT_SIGNALS/NOSTALGIA_PATTERNS 等

    支持运行时增删改查,无需重启服务即可调整评分规则。
    """
    __tablename__ = 'intent_rule'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    rule_type = Column(String(32), index=True, nullable=False, comment='规则类型: strong_intent/industry_template/nostalgia/discussion/past_purchase')
    pattern = Column(String(255), nullable=False, comment='匹配模式(关键词/模板),模板用 {w} 占位核心词')
    action = Column(String(32), default='upgrade', comment='动作: upgrade=升级为高意向, downgrade=降级为低/中')
    target_level = Column(String(16), default='high', comment='目标等级: high/middle/low')
    score_delta = Column(Integer, default=0, comment='分数调整值(正=加分,负=减分)')
    score_cap = Column(Integer, default=0, comment='分数上限(降级规则用,0=不限制)')
    enabled = Column(Integer, default=1, comment='是否启用: 0=禁用, 1=启用')
    category = Column(String(64), default='general', comment='分类标签(便于管理)')
    note = Column(String(255), default='', comment='备注说明')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID(数据隔离)')
    created_ts = Column(BigInteger, comment='创建时间戳')
    updated_ts = Column(BigInteger, comment='更新时间戳')


class KeywordCategory(Base):
    """关键词分类表 - 关键词库,按分类组织,支持权重"""
    __tablename__ = 'keyword_category'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    name = Column(String(128), nullable=False, comment='分类名称')
    keywords = Column(Text, default='[]', comment='关键词列表JSON')
    weight = Column(Integer, default=1, comment='权重(倍数)')
    category = Column(String(64), default='general', comment='上级分类')
    enabled = Column(Integer, default=1, comment='是否启用: 0=禁用, 1=启用')
    owner_user_id = Column(String(64), index=True, default='', comment='归属系统用户ID(数据隔离)')
    created_ts = Column(BigInteger, comment='创建时间戳')
    updated_ts = Column(BigInteger, comment='更新时间戳')


class XTwitterNotificationChannel(Base):
    """X Twitter 工作台 - 通知渠道配置表

    存储邮件/钉钉/企业微信/自定义 webhook 等通知渠道配置,
    在检测到新回复、AI 回复失败等事件时触发推送。
    """
    __tablename__ = 'x_twitter_notification_channel'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    name = Column(String(128), nullable=False, comment='渠道名称(用户友好)')
    channel_type = Column(String(32), index=True, nullable=False, comment='渠道类型: email/dingtalk/wechat_work/custom_webhook')
    config = Column(Text, default='{}', comment='渠道配置JSON: email_to/webhook_url/at_mobiles 等')
    events = Column(Text, default='[]', comment='订阅事件JSON数组: new_reply/reply_failed/cookie_pool_empty/comment_sent')
    is_active = Column(Integer, default=1, index=True, comment='是否启用: 0=禁用, 1=启用')
    min_interval_seconds = Column(Integer, default=60, comment='最小触发间隔(秒),避免频繁通知')
    last_trigger_ts = Column(BigInteger, default=0, comment='上次触发时间戳,用于限频')
    success_count = Column(Integer, default=0, comment='成功推送次数')
    fail_count = Column(Integer, default=0, comment='失败次数')
    note = Column(String(255), default='', comment='备注说明')
    created_ts = Column(BigInteger, comment='创建时间戳')
    updated_ts = Column(BigInteger, comment='更新时间戳')


class XTwitterAutoPipelineTask(Base):
    """X Twitter 自动化流水线任务表
    记录从视频拆解到发布的全流程状态,支持 WebSocket 实时推送进度。
    """
    __tablename__ = 'x_twitter_auto_pipeline_task'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    task_id = Column(String(64), unique=True, index=True, comment='任务UUID')
    post_id = Column(String(64), index=True, comment='原推文ID')
    status = Column(String(32), default='pending', index=True, comment='任务状态: pending/running/completed/failed')
    current_step = Column(Integer, default=0, comment='当前步骤 0-6')
    step_detail = Column(String(512), default='', comment='当前步骤详细描述')
    # Step 1 结果
    breakdown_id = Column(Integer, comment='关联 XTwitterVideoBreakdown.id')
    # Step 2 结果
    video_task_id = Column(String(128), default='', comment='AI6700 视频任务ID')
    video_url = Column(Text, default='', comment='生成的解说视频URL')
    video_status = Column(String(32), default='', comment='视频生成状态: submitting/processing/succeeded/failed')
    # Step 3-4 结果
    candidate_contents = Column(Text, default='[]', comment='候选文案JSON数组')
    selected_content = Column(Text, default='', comment='AI自动选择的最佳文案')
    # Step 6 结果
    tweet_id = Column(String(64), default='', comment='发布后的推文ID')
    tweet_url = Column(Text, default='', comment='发布后的推文URL')
    # 错误信息
    error_msg = Column(Text, default='', comment='错误信息')
    # 选项
    skip_video = Column(Integer, default=0, comment='是否跳过视频生成: 0=否, 1=是')
    add_ts = Column(BigInteger, comment='记录创建时间戳')
    update_ts = Column(BigInteger, comment='记录更新时间戳')


class VoiceModel(Base):
    """声音克隆模型"""
    __tablename__ = 'voice_models'
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(String(64), index=True, comment='归属用户ID')
    name = Column(String(255), comment='声音名称')
    provider = Column(String(32), default='edge_tts', comment='提供方: cosyvoice/edge_tts')
    provider_model_id = Column(String(255), default='', comment='CosyVoice返回的模型ID')
    sample_audio_path = Column(Text, default='', comment='录音样本路径')
    voice_config = Column(Text, default='{}', comment='声音配置JSON(音色/语速等)')
    status = Column(String(32), default='pending', comment='状态: pending/ready/failed')
    created_ts = Column(BigInteger, comment='创建时间戳')


class DigitalHumanModel(Base):
    """数字人形象模型"""
    __tablename__ = 'digital_human_models'
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(String(64), index=True, comment='归属用户ID')
    name = Column(String(255), comment='数字人名称')
    provider = Column(String(32), default='image_video', comment='提供方: heygem/image_video')
    provider_model_id = Column(String(255), default='', comment='HeyGem返回的模型ID')
    portrait_path = Column(Text, default='', comment='形象照路径')
    status = Column(String(32), default='pending', comment='状态: pending/ready/failed')
    created_ts = Column(BigInteger, comment='创建时间戳')


class TalkingHeadTask(Base):
    """口播视频生成任务"""
    __tablename__ = 'talking_head_tasks'
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(String(64), index=True, comment='归属用户ID')
    source_video_url = Column(Text, default='', comment='对标视频链接')
    original_script = Column(Text, default='', comment='提取的原始文案')
    rewritten_script = Column(Text, default='', comment='仿写后文案')
    voice_model_id = Column(Integer, index=True, comment='声音模型ID')
    digital_human_id = Column(Integer, index=True, comment='数字人模型ID')
    audio_path = Column(Text, default='', comment='合成音频路径')
    video_path = Column(Text, default='', comment='最终视频路径')
    cover_path = Column(Text, default='', comment='封面图片路径')
    subtitle_path = Column(Text, default='', comment='字幕文件路径')
    title_suggestions = Column(Text, default='[]', comment='标题建议JSON')
    tags = Column(Text, default='[]', comment='话题标签JSON')
    pipeline_steps = Column(Text, default='[]', comment='流水线步骤记录JSON')
    status = Column(String(32), default='pending', comment='状态: pending/extracting/rewriting/synthesizing/generating/done/failed')
    error = Column(Text, default='', comment='错误信息')
    elapsed = Column(Integer, default=0, comment='总耗时(秒)')
    created_ts = Column(BigInteger, comment='创建时间戳')
    updated_ts = Column(BigInteger, comment='更新时间戳')
