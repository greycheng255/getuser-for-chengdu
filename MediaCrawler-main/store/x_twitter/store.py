# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/x_twitter/store.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1


import os
import json
from datetime import datetime
from typing import Any, Dict, List

from tools.utils import logger


class XTwitterDataStore:
    def __init__(self, save_data_path: str = ""):
        self.save_data_path = save_data_path or os.path.join(os.getcwd(), "data", "x_twitter")
        os.makedirs(self.save_data_path, exist_ok=True)
        logger.info(f"[XTwitterDataStore] Data store initialized at: {self.save_data_path}")

    def save_post(self, post_data: Dict[str, Any]) -> None:
        try:
            filename = f"{post_data.get('post_id', datetime.now().strftime('%Y%m%d_%H%M%S'))}.json"
            filepath = os.path.join(self.save_data_path, filename)
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(post_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[XTwitterDataStore] Post saved: {filepath}")
        except Exception as e:
            logger.error(f"[XTwitterDataStore] Failed to save post: {e}")

    def save_posts(self, posts_data: List[Dict[str, Any]]) -> None:
        for post in posts_data:
            self.save_post(post)

    def save_comment(self, comment_data: Dict[str, Any]) -> None:
        try:
            comments_dir = os.path.join(self.save_data_path, "comments")
            os.makedirs(comments_dir, exist_ok=True)
            
            filename = f"{comment_data.get('post_id', '')}_{comment_data.get('comment_id', datetime.now().strftime('%Y%m%d_%H%M%S'))}.json"
            filepath = os.path.join(comments_dir, filename)
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(comment_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[XTwitterDataStore] Comment saved: {filepath}")
        except Exception as e:
            logger.error(f"[XTwitterDataStore] Failed to save comment: {e}")

    def save_comments(self, comments_data: List[Dict[str, Any]], post_id: str = "") -> None:
        for comment in comments_data:
            if post_id:
                comment["post_id"] = post_id
            self.save_comment(comment)

    def save_trending_topics(self, trending_data: List[Dict[str, Any]]) -> None:
        try:
            trending_dir = os.path.join(self.save_data_path, "trending")
            os.makedirs(trending_dir, exist_ok=True)
            
            filename = f"trending_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(trending_dir, filename)
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(trending_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[XTwitterDataStore] Trending topics saved: {filepath}")
        except Exception as e:
            logger.error(f"[XTwitterDataStore] Failed to save trending topics: {e}")

    def save_outreach_record(self, record_data: Dict[str, Any]) -> None:
        try:
            outreach_dir = os.path.join(self.save_data_path, "outreach")
            os.makedirs(outreach_dir, exist_ok=True)
            
            filename = f"{record_data.get('task_id', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(outreach_dir, filename)
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(record_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[XTwitterDataStore] Outreach record saved: {filepath}")
        except Exception as e:
            logger.error(f"[XTwitterDataStore] Failed to save outreach record: {e}")

    def load_posts(self) -> List[Dict[str, Any]]:
        posts = []
        try:
            for filename in os.listdir(self.save_data_path):
                if filename.endswith(".json") and not filename.startswith("trending_"):
                    filepath = os.path.join(self.save_data_path, filename)
                    with open(filepath, "r", encoding="utf-8") as f:
                        posts.append(json.load(f))
            logger.info(f"[XTwitterDataStore] Loaded {len(posts)} posts")
        except Exception as e:
            logger.error(f"[XTwitterDataStore] Failed to load posts: {e}")
        return posts

    def load_trending_topics(self) -> List[Dict[str, Any]]:
        trending = []
        try:
            trending_dir = os.path.join(self.save_data_path, "trending")
            if os.path.exists(trending_dir):
                for filename in os.listdir(trending_dir):
                    if filename.endswith(".json"):
                        filepath = os.path.join(trending_dir, filename)
                        with open(filepath, "r", encoding="utf-8") as f:
                            trending.extend(json.load(f))
            logger.info(f"[XTwitterDataStore] Loaded {len(trending)} trending topics")
        except Exception as e:
            logger.error(f"[XTwitterDataStore] Failed to load trending topics: {e}")
        return trending