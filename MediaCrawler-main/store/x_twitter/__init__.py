# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/x_twitter/__init__.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1


import config
from tools import utils

from typing import Dict

from ._store_impl import *


class XTwitterStoreFactory:
    STORES = {
        "csv": XTwitterCsvStoreImplement,
        "db": XTwitterDbStoreImplement,
        "postgres": XTwitterDbStoreImplement,
        "json": XTwitterJsonStoreImplement,
        "jsonl": XTwitterJsonlStoreImplement,
        "sqlite": XTwitterSqliteStoreImplement,
        "mongodb": XTwitterMongoStoreImplement,
        "excel": XTwitterExcelStoreImplement,
    }

    @staticmethod
    def create_store() -> AbstractStore:
        store_class = XTwitterStoreFactory.STORES.get(config.SAVE_DATA_OPTION)
        if not store_class:
            raise ValueError("[XTwitterStoreFactory.create_store] Invalid save option only supported csv or db or json or sqlite or mongodb or excel ...")
        return store_class()


async def update_x_twitter_post(post_item: Dict):
    local_db_item = {
        "post_id": post_item.get("post_id"),
        "content": post_item.get("content", "")[:5000],
        "video_url": post_item.get("video_url", ""),
        "image_urls": ",".join(post_item.get("image_urls", [])),
        "username": post_item.get("username", ""),
        "user_id": post_item.get("user_id", ""),
        "created_at": post_item.get("created_at", ""),
        "likes_count": str(post_item.get("likes_count", 0)),
        "retweets_count": str(post_item.get("retweets_count", 0)),
        "replies_count": str(post_item.get("replies_count", 0)),
        "quotes_count": str(post_item.get("quotes_count", 0)),
        "post_url": post_item.get("post_url", ""),
        "hashtags": ",".join(post_item.get("hashtags", [])),
        "last_modify_ts": utils.get_current_timestamp(),
        "source_keyword": post_item.get("source_keyword", ""),
    }
    utils.logger.info(f"[store.x_twitter.update_x_twitter_post] x_twitter post: {local_db_item}")
    await XTwitterStoreFactory.create_store().store_content(local_db_item)


async def update_x_twitter_comment(post_id: str, comment_item: Dict):
    user_info = comment_item.get("user_info", {})
    local_db_item = {
        "comment_id": comment_item.get("comment_id", ""),
        "post_id": post_id,
        "content": comment_item.get("content", "")[:2000],
        "username": user_info.get("username", ""),
        "user_id": user_info.get("user_id", ""),
        "created_at": comment_item.get("created_at", ""),
        "likes_count": str(comment_item.get("likes_count", 0)),
        "replies_count": str(comment_item.get("replies_count", 0)),
        "last_modify_ts": utils.get_current_timestamp(),
    }
    utils.logger.info(f"[store.x_twitter.update_x_twitter_comment] x_twitter comment:{local_db_item}")
    await XTwitterStoreFactory.create_store().store_comment(local_db_item)


async def update_x_twitter_video_breakdown(post_id: str, post_url: str, breakdown_data: Dict):
    local_db_item = {
        "post_id": post_id,
        "post_url": post_url,
        "script": breakdown_data.get("script", ""),
        "storyboards": breakdown_data.get("storyboards", ""),
        "key_points": breakdown_data.get("key_points", ""),
        "suggested_comments": breakdown_data.get("suggested_comments", ""),
        "add_ts": utils.get_current_timestamp(),
    }
    utils.logger.info(f"[store.x_twitter.update_x_twitter_video_breakdown] x_twitter video breakdown: {local_db_item}")
    store = XTwitterStoreFactory.create_store()
    if hasattr(store, 'store_video_breakdown'):
        await store.store_video_breakdown(local_db_item)
