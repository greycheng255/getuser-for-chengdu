# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/x_twitter/field.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1


from enum import Enum
from typing import NamedTuple


class SearchType(Enum):
    TRENDING = "trending"
    KEYWORD = "keyword"
    USER = "user"


class PostType(Enum):
    TWEET = "tweet"
    RETWEET = "retweet"
    REPLY = "reply"
    QUOTE = "quote"


class Post(NamedTuple):
    post_id: str
    user_id: str
    username: str
    nickname: str
    avatar: str
    content: str
    image_urls: list
    video_url: str
    video_duration: int
    likes_count: str
    retweets_count: str
    replies_count: str
    bookmarks_count: str
    views_count: str
    created_at: int
    post_url: str
    is_retweet: bool
    original_post_id: str
    lang: str


class Comment(NamedTuple):
    comment_id: str
    post_id: str
    user_id: str
    username: str
    nickname: str
    avatar: str
    content: str
    likes_count: str
    replies_count: str
    created_at: int
    parent_comment_id: str


class VideoBreakdown(NamedTuple):
    post_id: str
    script: str
    storyboards: list
    key_points: list
    suggested_comments: list