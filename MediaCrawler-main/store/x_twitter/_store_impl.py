# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/x_twitter/_store_impl.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1


import json
import os
from datetime import datetime
from typing import List, Dict, Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from base.base_crawler import AbstractStore
from database.db_session import get_session
from database.models import XTwitterPost, XTwitterComment, XTwitterVideoBreakdown

from tools.async_file_writer import AsyncFileWriter
from tools.time_util import get_current_timestamp
from var import crawler_type_var
from database.mongodb_store_base import MongoDBStoreBase
from tools import utils
from store.excel_store_base import ExcelStoreBase


class XTwitterCsvStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="x_twitter", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_to_csv(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        await self.writer.write_to_csv(item_type="comments", item=comment_item)

    async def store_creator(self, creator_item: Dict):
        pass

    def flush(self):
        pass


class XTwitterJsonStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="x_twitter", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_single_item_to_json(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        await self.writer.write_single_item_to_json(item_type="comments", item=comment_item)

    async def store_creator(self, creator_item: Dict):
        pass

    def flush(self):
        pass


class XTwitterJsonlStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="x_twitter", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_to_jsonl(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        await self.writer.write_to_jsonl(item_type="comments", item=comment_item)

    async def store_creator(self, creator_item: Dict):
        pass

    def flush(self):
        pass


class XTwitterDbStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def store_content(self, content_item: Dict):
        async with get_session() as session:
            try:
                select_stmt = select(XTwitterPost).where(XTwitterPost.post_id == content_item.get("post_id"))
                result = await session.execute(select_stmt)
                db_post = result.scalar_one_or_none()

                if db_post:
                    for key, value in content_item.items():
                        setattr(db_post, key, value)
                else:
                    db_post = XTwitterPost(**content_item)
                    session.add(db_post)

                await session.commit()
                utils.logger.info(f"[XTwitterDbStoreImplement.store_content] x_twitter post saved to db: {content_item.get('post_id')}")
            except Exception as e:
                await session.rollback()
                utils.logger.error(f"[XTwitterDbStoreImplement.store_content] Failed to save post to db: {e}")

    async def store_comment(self, comment_item: Dict):
        async with get_session() as session:
            try:
                select_stmt = select(XTwitterComment).where(XTwitterComment.comment_id == comment_item.get("comment_id"))
                result = await session.execute(select_stmt)
                db_comment = result.scalar_one_or_none()

                if db_comment:
                    for key, value in comment_item.items():
                        setattr(db_comment, key, value)
                else:
                    db_comment = XTwitterComment(**comment_item)
                    session.add(db_comment)

                await session.commit()
                utils.logger.info(f"[XTwitterDbStoreImplement.store_comment] x_twitter comment saved to db: {comment_item.get('comment_id')}")
            except Exception as e:
                await session.rollback()
                utils.logger.error(f"[XTwitterDbStoreImplement.store_comment] Failed to save comment to db: {e}")

    async def store_creator(self, creator_item: Dict):
        pass

    def flush(self):
        pass


class XTwitterSqliteStoreImplement(XTwitterDbStoreImplement):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class XTwitterMongoStoreImplement(AbstractStore, MongoDBStoreBase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def store_content(self, content_item: Dict):
        await self._store_mongodb(
            platform="x_twitter",
            item_type="contents",
            item=content_item,
            unique_key="post_id"
        )

    async def store_comment(self, comment_item: Dict):
        await self._store_mongodb(
            platform="x_twitter",
            item_type="comments",
            item=comment_item,
            unique_key="comment_id"
        )

    async def store_creator(self, creator_item: Dict):
        pass

    def flush(self):
        pass


class XTwitterExcelStoreImplement(ExcelStoreBase):
    def __init__(self, **kwargs):
        super().__init__(platform="x_twitter", crawler_type=crawler_type_var.get(), **kwargs)

    async def store_content(self, content_item: Dict):
        await self._store_excel(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        await self._store_excel(item_type="comments", item=comment_item)

    async def store_creator(self, creator_item: Dict):
        pass

    def flush(self):
        pass