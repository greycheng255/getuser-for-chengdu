# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/douyin/_store_impl.py
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


# -*- coding: utf-8 -*-
# @Author  : persist1@126.com
# @Time    : 2025/9/5 19:34
# @Desc    : Douyin storage implementation class
import asyncio
import json
import os
import pathlib
from typing import Dict

from sqlalchemy import select

import config
from base.base_crawler import AbstractStore
from database.db_session import get_session
from database.models import DouyinAweme, DouyinAwemeComment, DyCreator, DouyinDmRecord
from tools import utils, words
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var
from database.mongodb_store_base import MongoDBStoreBase


class DouyinCsvStoreImplement(AbstractStore):
    def __init__(self):
        self.file_writer = AsyncFileWriter(
            crawler_type=crawler_type_var.get(),
            platform="douyin"
        )

    async def store_content(self, content_item: Dict):
        """
        Douyin content CSV storage implementation
        Args:
            content_item: note item dict

        Returns:

        """
        await self.file_writer.write_to_csv(
            item=content_item,
            item_type="contents"
        )

    async def store_comment(self, comment_item: Dict):
        """
        Douyin comment CSV storage implementation
        Args:
            comment_item: comment item dict

        Returns:

        """
        await self.file_writer.write_to_csv(
            item=comment_item,
            item_type="comments"
        )

    async def store_creator(self, creator: Dict):
        """
        Douyin creator CSV storage implementation
        Args:
            creator: creator item dict

        Returns:

        """
        await self.file_writer.write_to_csv(
            item=creator,
            item_type="creators"
        )

    async def store_dm_record(self, dm_item: Dict):
        """
        Douyin DM record CSV storage implementation
        """
        await self.file_writer.write_to_csv(
            item=dm_item,
            item_type="dm_records"
        )


class DouyinDbStoreImplement(AbstractStore):
    async def store_content(self, content_item: Dict):
        """
        Douyin content DB storage implementation
        Args:
            content_item: content item dict
        """
        aweme_id = content_item.get("aweme_id")
        async with get_session() as session:
            result = await session.execute(select(DouyinAweme).where(DouyinAweme.aweme_id == aweme_id))
            aweme_detail = result.scalar_one_or_none()

            # 获取当前任务ID
            from var import task_id_var
            task_id = task_id_var.get() if hasattr(task_id_var, 'get') else ""
            content_item["task_id"] = task_id

            if not aweme_detail:
                content_item["add_ts"] = utils.get_current_timestamp()
                if content_item.get("title"):
                    new_content = DouyinAweme(**content_item)
                    session.add(new_content)
            else:
                for key, value in content_item.items():
                    setattr(aweme_detail, key, value)
            await session.commit()

            # 检测并保存客户线索
            try:
                from store.customer_lead import check_and_save_lead
                if task_id:
                    await check_and_save_lead(
                        task_id=task_id,
                        platform="douyin",
                        data_type="video",
                        data=content_item,
                        content_field="desc",
                        title_field="title",
                        url_field="aweme_url",
                        user_id_field="user_id",
                        nickname_field="nickname",
                        avatar_field="avatar",
                        ip_location_field="ip_location",
                        data_id_field="aweme_id"
                    )
            except Exception as e:
                utils.logger.warning(f"[DouyinDbStoreImplement.store_content] Lead detection error: {e}")

    async def store_comment(self, comment_item: Dict):
        """
        Douyin comment DB storage implementation
        Args:
            comment_item: comment item dict
        """
        comment_id = comment_item.get("comment_id")
        async with get_session() as session:
            # 跨任务去重:同 comment_id + 同 task_id 才算重复(不同任务爬到同一条评论应分别保留)
            from var import task_id_var
            task_id = task_id_var.get() if hasattr(task_id_var, 'get') else ""
            task_id = task_id or ""
            comment_item["task_id"] = task_id

            result = await session.execute(
                select(DouyinAwemeComment)
                .where(DouyinAwemeComment.comment_id == comment_id)
                .where(DouyinAwemeComment.task_id == task_id)
            )
            comment_detail = result.scalar_one_or_none()

            if not comment_detail:
                comment_item["add_ts"] = utils.get_current_timestamp()
                new_comment = DouyinAwemeComment(**comment_item)
                session.add(new_comment)
            else:
                for key, value in comment_item.items():
                    setattr(comment_detail, key, value)
            await session.commit()

            # 检测并保存客户线索
            try:
                from store.customer_lead import check_and_save_lead
                if task_id:
                    # 查询评论所属视频的标题，用于关键词相关性判断
                    aweme_title = ""
                    if aweme_id:
                        aweme_result = await session.execute(
                            select(DouyinAweme.title).where(DouyinAweme.aweme_id == aweme_id)
                        )
                        aweme_row = aweme_result.fetchone()
                        if aweme_row and aweme_row[0]:
                            aweme_title = aweme_row[0]
                    await check_and_save_lead(
                        task_id=task_id,
                        platform="douyin",
                        data_type="comment",
                        data=comment_item,
                        content_field="content",
                        title_field="",  # 评论数据本身没有标题
                        url_field="aweme_url",
                        user_id_field="user_id",
                        nickname_field="nickname",
                        avatar_field="avatar",
                        ip_location_field="ip_location",
                        data_id_field="comment_id",
                        # 传入视频标题作为上下文，用于关键词相关性判断
                        extra_title=aweme_title
                    )
            except Exception as e:
                utils.logger.warning(f"[DouyinDbStoreImplement.store_comment] Lead detection error: {e}")

    async def store_creator(self, creator: Dict):
        """
        Douyin creator DB storage implementation
        Args:
            creator: creator dict
        """
        user_id = creator.get("user_id")
        async with get_session() as session:
            result = await session.execute(select(DyCreator).where(DyCreator.user_id == user_id))
            user_detail = result.scalar_one_or_none()

            if not user_detail:
                creator["add_ts"] = utils.get_current_timestamp()
                new_creator = DyCreator(**creator)
                session.add(new_creator)
            else:
                for key, value in creator.items():
                    setattr(user_detail, key, value)
            await session.commit()

    async def store_dm_record(self, dm_item: Dict):
        """
        Douyin DM record DB storage implementation
        Args:
            dm_item: DM record dict
        """
        async with get_session() as session:
            dm_item["add_ts"] = utils.get_current_timestamp()
            new_record = DouyinDmRecord(**dm_item)
            session.add(new_record)
            await session.commit()


class DouyinJsonStoreImplement(AbstractStore):
    def __init__(self):
        self.file_writer = AsyncFileWriter(
            crawler_type=crawler_type_var.get(),
            platform="douyin"
        )

    async def store_content(self, content_item: Dict):
        """
        content JSON storage implementation
        Args:
            content_item:

        Returns:

        """
        await self.file_writer.write_single_item_to_json(
            item=content_item,
            item_type="contents"
        )

    async def store_comment(self, comment_item: Dict):
        """
        comment JSON storage implementation
        Args:
            comment_item:

        Returns:

        """
        await self.file_writer.write_single_item_to_json(
            item=comment_item,
            item_type="comments"
        )

    async def store_creator(self, creator: Dict):
        """
        creator JSON storage implementation
        Args:
            creator:

        Returns:

        """
        await self.file_writer.write_single_item_to_json(
            item=creator,
            item_type="creators"
        )

    async def store_dm_record(self, dm_item: Dict):
        """
        DM record JSON storage implementation
        """
        await self.file_writer.write_single_item_to_json(
            item=dm_item,
            item_type="dm_records"
        )



class DouyinJsonlStoreImplement(AbstractStore):
    def __init__(self):
        self.file_writer = AsyncFileWriter(
            crawler_type=crawler_type_var.get(),
            platform="douyin"
        )

    async def store_content(self, content_item: Dict):
        from var import task_id_var
        task_id = task_id_var.get() if hasattr(task_id_var, 'get') else ""
        if task_id:
            content_item["task_id"] = task_id
        await self.file_writer.write_to_jsonl(
            item=content_item,
            item_type="contents"
        )

    async def store_comment(self, comment_item: Dict):
        from var import task_id_var
        task_id = task_id_var.get() if hasattr(task_id_var, 'get') else ""
        if task_id:
            comment_item["task_id"] = task_id
        await self.file_writer.write_to_jsonl(
            item=comment_item,
            item_type="comments"
        )

    async def store_creator(self, creator: Dict):
        from var import task_id_var
        task_id = task_id_var.get() if hasattr(task_id_var, 'get') else ""
        if task_id:
            creator["task_id"] = task_id
        await self.file_writer.write_to_jsonl(
            item=creator,
            item_type="creators"
        )

    async def store_dm_record(self, dm_item: Dict):
        """
        DM record JSONL storage implementation
        """
        from var import task_id_var
        task_id = task_id_var.get() if hasattr(task_id_var, 'get') else ""
        if task_id:
            dm_item["task_id"] = task_id
        await self.file_writer.write_to_jsonl(
            item=dm_item,
            item_type="dm_records"
        )


class DouyinSqliteStoreImplement(DouyinDbStoreImplement):
    pass


class DouyinMongoStoreImplement(AbstractStore):
    """Douyin MongoDB storage implementation"""

    def __init__(self):
        self.mongo_store = MongoDBStoreBase(collection_prefix="douyin")

    async def store_content(self, content_item: Dict):
        """
        Store video content to MongoDB
        Args:
            content_item: Video content data
        """
        aweme_id = content_item.get("aweme_id")
        if not aweme_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="contents",
            query={"aweme_id": aweme_id},
            data=content_item
        )
        utils.logger.info(f"[DouyinMongoStoreImplement.store_content] Saved aweme {aweme_id} to MongoDB")

    async def store_comment(self, comment_item: Dict):
        """
        Store comment to MongoDB
        Args:
            comment_item: Comment data
        """
        comment_id = comment_item.get("comment_id")
        if not comment_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="comments",
            query={"comment_id": comment_id},
            data=comment_item
        )
        utils.logger.info(f"[DouyinMongoStoreImplement.store_comment] Saved comment {comment_id} to MongoDB")

    async def store_creator(self, creator_item: Dict):
        """
        Store creator information to MongoDB
        Args:
            creator_item: Creator data
        """
        user_id = creator_item.get("user_id")
        if not user_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="creators",
            query={"user_id": user_id},
            data=creator_item
        )
        utils.logger.info(f"[DouyinMongoStoreImplement.store_creator] Saved creator {user_id} to MongoDB")

    async def store_dm_record(self, dm_item: Dict):
        """
        Store DM record to MongoDB
        Args:
            dm_item: DM record data
        """
        sec_uid = dm_item.get("sec_uid")
        add_ts = dm_item.get("add_ts")
        await self.mongo_store.save_or_update(
            collection_suffix="dm_records",
            query={"sec_uid": sec_uid, "add_ts": add_ts},
            data=dm_item
        )
        utils.logger.info(f"[DouyinMongoStoreImplement.store_dm_record] Saved DM record for {sec_uid} to MongoDB")


class DouyinExcelStoreImplement:
    """Douyin Excel storage implementation - Global singleton"""

    def __new__(cls, *args, **kwargs):
        from store.excel_store_base import ExcelStoreBase
        return ExcelStoreBase.get_instance(
            platform="douyin",
            crawler_type=crawler_type_var.get()
        )
