# -*- coding: utf-8 -*-
"""
平台评论抓取抽象层

支持平台：douyin / xhs / ks / bili / wb

实现方式：
1. 通过 crawler_manager 启动 detail/creator 类型爬虫子进程（enable_comments=True）
2. 爬虫自动抓取评论入各平台评论表
3. fetcher 从评论表读取并转为 UnifiedComment

子类需实现：
- PLATFORM / COMMENT_TABLE / POST_ID_FIELD
- fetch_comments (含 ID 解析)
- fetch_user_posts (账号模式)
- _read_comments_from_db (字段映射)
- _read_user_posts_from_db (字段映射)
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class UnifiedComment:
    """统一评论数据结构"""
    platform: str
    post_id: str            # 视频/笔记ID
    post_url: str = ""      # 视频/笔记URL
    comment_id: str = ""    # 平台评论ID
    comment_text: str = ""  # 评论内容
    author_id: str = ""     # 评论作者ID
    author_nickname: str = ""
    author_sec_uid: str = ""
    author_avatar: str = ""
    parent_comment_id: str = ""  # 父评论ID（子评论时填）
    like_count: int = 0
    created_ts: int = 0     # 评论创建时间戳


@dataclass
class CommentFetchResult:
    """抓取结果"""
    comments: List[UnifiedComment] = field(default_factory=list)
    has_more: bool = False
    next_cursor: Any = None
    error: str = ""


class PlatformCommentFetcher:
    """平台评论抓取基类

    子类只需声明 PLATFORM / COMMENT_TABLE / POST_ID_FIELD，
    并实现 fetch_comments / fetch_user_posts / _read_comments_from_db /
    _read_user_posts_from_db 即可，_trigger_crawl 由基类提供。
    """

    PLATFORM: str = ""
    COMMENT_TABLE: str = ""       # 评论表名
    POST_ID_FIELD: str = ""       # 评论表中关联视频/笔记的字段名
    POST_TABLE: str = ""          # 视频/笔记表名（用于 fetch_user_posts）
    POST_TABLE_USER_FIELD: str = ""  # POST_TABLE 中关联用户的字段名

    def __init__(self, owner_user_id: Optional[int] = None):
        self.owner_user_id = owner_user_id

    async def fetch_comments(
        self,
        target_id: str,
        cursor: Any = None,
        max_count: int = 100,
    ) -> CommentFetchResult:
        """抓取指定视频/笔记的评论（子类实现）"""
        raise NotImplementedError

    async def fetch_user_posts(self, sec_user_id: str) -> List[Dict]:
        """获取用户最近发布的视频/笔记列表（子类实现）"""
        raise NotImplementedError

    async def _read_comments_from_db(
        self, post_id: str, limit: int = 100
    ) -> List[UnifiedComment]:
        """从平台评论表读取评论（子类实现具体字段映射）"""
        raise NotImplementedError

    async def _read_user_posts_from_db(
        self, sec_user_id: str, limit: int = 10
    ) -> List[Dict]:
        """从平台视频/笔记表读用户最近发布（子类实现）"""
        raise NotImplementedError

    # ============ 公共：触发爬虫子进程 ============

    async def _trigger_crawl(
        self,
        crawler_type: str,
        specified_ids: str = "",
        creator_ids: str = "",
    ) -> bool:
        """通过 crawler_manager 启动爬虫子进程（5 平台通用）"""
        try:
            from api.services.crawler_manager import crawler_manager
            from api.schemas.crawler import (
                CrawlerStartRequest, PlatformEnum, CrawlerTypeEnum, LoginTypeEnum,
            )

            platform_map = {
                "douyin": PlatformEnum.DOUYIN,
                "xhs": PlatformEnum.XHS,
                "ks": PlatformEnum.KUAISHOU,
                "bili": PlatformEnum.BILIBILI,
                "wb": PlatformEnum.WEIBO,
            }
            crawler_type_map = {
                "detail": CrawlerTypeEnum.DETAIL,
                "creator": CrawlerTypeEnum.CREATOR,
                "search": CrawlerTypeEnum.SEARCH,
            }

            req = CrawlerStartRequest(
                platform=platform_map.get(self.PLATFORM, PlatformEnum.DOUYIN),
                login_type=LoginTypeEnum.COOKIE,
                crawler_type=crawler_type_map.get(crawler_type, CrawlerTypeEnum.DETAIL),
                specified_ids=specified_ids,
                creator_ids=creator_ids,
                enable_comments=True,
                enable_sub_comments=False,
                headless=True,
                task_id=f"cmt_monitor_{self.PLATFORM}_{int(time.time())}",
            )
            task_id = f"cmt_{self.PLATFORM}_{int(time.time())}"
            ok, _ = await crawler_manager.start(
                req, task_id=task_id, owner_user_id=self.owner_user_id
            )
            if not ok:
                return False

            # 等待爬虫完成（最多 120 秒）
            for _ in range(60):
                await asyncio.sleep(2)
                if not crawler_manager.is_running(task_id=task_id):
                    return True
            logger.warning(
                f"[{self.PLATFORM}Fetcher] 爬虫超时 120s task_id={task_id}"
            )
            return True  # 超时也尝试读DB
        except Exception as e:
            logger.error(f"[{self.PLATFORM}Fetcher] 启动爬虫失败: {e}")
            return False

    # ============ 公共：DB 引擎获取 ============

    @staticmethod
    def _get_engine():
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    @staticmethod
    def _safe_int(v, default=0) -> int:
        try:
            if v is None:
                return default
            if isinstance(v, (int, float)):
                return int(v)
            s = str(v)
            if s.isdigit():
                return int(s)
            # 兼容 "123.0" 这种字符串
            try:
                return int(float(s))
            except Exception:
                return default
        except Exception:
            return default


# ============ 抖音 ============

class DouyinCommentFetcher(PlatformCommentFetcher):
    """抖音评论抓取器"""

    PLATFORM = "douyin"
    COMMENT_TABLE = "douyin_aweme_comment"
    POST_ID_FIELD = "aweme_id"
    POST_TABLE = "douyin_aweme"
    POST_TABLE_USER_FIELD = "sec_uid"

    async def fetch_comments(
        self, target_id: str, cursor: Any = None, max_count: int = 100,
    ) -> CommentFetchResult:
        aweme_id = self._parse_aweme_id(target_id)
        if not aweme_id:
            return CommentFetchResult(error=f"无法解析 aweme_id: {target_id}")

        crawl_ok = await self._trigger_crawl(
            crawler_type="detail", specified_ids=aweme_id
        )
        if not crawl_ok:
            logger.warning(
                f"[DouyinFetcher] 爬虫启动失败，尝试读取已有评论 aweme_id={aweme_id}"
            )

        comments = await self._read_comments_from_db(aweme_id, limit=max_count)
        return CommentFetchResult(
            comments=comments,
            has_more=False,
            error="" if comments else "无评论数据",
        )

    async def fetch_user_posts(self, sec_user_id: str) -> List[Dict]:
        crawl_ok = await self._trigger_crawl(
            crawler_type="creator", creator_ids=sec_user_id
        )
        if not crawl_ok:
            logger.warning(f"[DouyinFetcher] creator 爬虫启动失败 sec_uid={sec_user_id}")
        return await self._read_user_posts_from_db(sec_user_id, limit=10)

    async def _read_comments_from_db(self, post_id: str, limit: int = 100) -> List[UnifiedComment]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT comment_id, content, user_id, sec_uid, nickname, "
                        "avatar, parent_comment_id, like_count, create_time, aweme_id "
                        f"FROM {self.COMMENT_TABLE} WHERE aweme_id = :aid "
                        "ORDER BY create_time DESC LIMIT :l"
                    ),
                    {"aid": post_id, "l": limit},
                )
                comments = []
                for r in rows.fetchall():
                    comments.append(UnifiedComment(
                        platform=self.PLATFORM,
                        post_id=r[9] or post_id,
                        comment_id=r[0] or "",
                        comment_text=r[1] or "",
                        author_id=r[2] or "",
                        author_sec_uid=r[3] or "",
                        author_nickname=r[4] or "",
                        author_avatar=r[5] or "",
                        parent_comment_id=r[6] or "",
                        like_count=self._safe_int(r[7]),
                        created_ts=self._safe_int(r[8]),
                    ))
                return comments
        except Exception as e:
            logger.error(f"[DouyinFetcher] 读DB评论失败: {e}")
            return []

    async def _read_user_posts_from_db(self, sec_user_id: str, limit: int = 10) -> List[Dict]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT aweme_id, title, desc as description, video_url, "
                        "create_time, cover "
                        f"FROM {self.POST_TABLE} WHERE sec_uid = :suid "
                        "ORDER BY create_time DESC LIMIT :l"
                    ),
                    {"suid": sec_user_id, "l": limit},
                )
                posts = []
                for r in rows.fetchall():
                    posts.append({
                        "post_id": r[0] or "",
                        "title": r[1] or r[2] or "",
                        "url": r[3] or "",
                        "created_ts": self._safe_int(r[4]),
                        "cover": r[5] or "",
                    })
                return posts
        except Exception as e:
            logger.error(f"[DouyinFetcher] 读用户视频失败: {e}")
            return []

    @staticmethod
    def _parse_aweme_id(target: str) -> str:
        target = target.strip()
        if target.isdigit():
            return target
        m = re.search(r"modal_id=(\d+)", target)
        if m:
            return m.group(1)
        m = re.search(r"/video/(\d+)", target)
        if m:
            return m.group(1)
        m = re.search(r"/note/(\d+)", target)
        if m:
            return m.group(1)
        return ""


# ============ 小红书 ============

class XhsCommentFetcher(PlatformCommentFetcher):
    """小红书评论抓取器"""

    PLATFORM = "xhs"
    COMMENT_TABLE = "xhs_note_comment"
    POST_ID_FIELD = "note_id"
    POST_TABLE = "xhs_note"
    POST_TABLE_USER_FIELD = "user_id"

    async def fetch_comments(
        self, target_id: str, cursor: Any = None, max_count: int = 100,
    ) -> CommentFetchResult:
        note_id = self._parse_note_id(target_id)
        if not note_id:
            return CommentFetchResult(error=f"无法解析 note_id: {target_id}")

        crawl_ok = await self._trigger_crawl(
            crawler_type="detail", specified_ids=note_id
        )
        if not crawl_ok:
            logger.warning(f"[XhsFetcher] 爬虫启动失败 note_id={note_id}")

        comments = await self._read_comments_from_db(note_id, limit=max_count)
        return CommentFetchResult(
            comments=comments,
            has_more=False,
            error="" if comments else "无评论数据",
        )

    async def fetch_user_posts(self, sec_user_id: str) -> List[Dict]:
        crawl_ok = await self._trigger_crawl(
            crawler_type="creator", creator_ids=sec_user_id
        )
        if not crawl_ok:
            logger.warning(f"[XhsFetcher] creator 爬虫启动失败 user_id={sec_user_id}")
        return await self._read_user_posts_from_db(sec_user_id, limit=10)

    async def _read_comments_from_db(self, post_id: str, limit: int = 100) -> List[UnifiedComment]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT comment_id, content, user_id, nickname, avatar, "
                        "parent_comment_id, like_count, create_time, note_id "
                        f"FROM {self.COMMENT_TABLE} WHERE note_id = :nid "
                        "ORDER BY create_time DESC LIMIT :l"
                    ),
                    {"nid": post_id, "l": limit},
                )
                comments = []
                for r in rows.fetchall():
                    comments.append(UnifiedComment(
                        platform=self.PLATFORM,
                        post_id=r[8] or post_id,
                        comment_id=r[0] or "",
                        comment_text=r[1] or "",
                        author_id=r[2] or "",
                        author_sec_uid="",  # xhs 表无 sec_uid
                        author_nickname=r[3] or "",
                        author_avatar=r[4] or "",
                        parent_comment_id=r[5] or "",
                        like_count=self._safe_int(r[6]),
                        created_ts=self._safe_int(r[7]),
                    ))
                return comments
        except Exception as e:
            logger.error(f"[XhsFetcher] 读DB评论失败: {e}")
            return []

    async def _read_user_posts_from_db(self, sec_user_id: str, limit: int = 10) -> List[Dict]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT note_id, title, desc as description, note_url, time, type "
                        f"FROM {self.POST_TABLE} WHERE user_id = :uid "
                        "ORDER BY time DESC LIMIT :l"
                    ),
                    {"uid": sec_user_id, "l": limit},
                )
                posts = []
                for r in rows.fetchall():
                    posts.append({
                        "post_id": r[0] or "",
                        "title": r[1] or r[2] or "",
                        "url": r[3] or "",
                        "created_ts": self._safe_int(r[4]),
                        "cover": "",
                    })
                return posts
        except Exception as e:
            logger.error(f"[XhsFetcher] 读用户笔记失败: {e}")
            return []

    @staticmethod
    def _parse_note_id(target: str) -> str:
        target = target.strip()
        # 纯ID（小红书 note_id 通常是 24 位十六进制，但也可能有更短的）
        if re.fullmatch(r"[a-zA-Z0-9]{16,32}", target):
            return target
        m = re.search(r"/explore/([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        m = re.search(r"/note/([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        m = re.search(r"/discovery/item/([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        m = re.search(r"[?&]note_id=([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        m = re.search(r"xhslink\.com/([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        return ""


# ============ 快手 ============

class KsCommentFetcher(PlatformCommentFetcher):
    """快手评论抓取器"""

    PLATFORM = "ks"
    COMMENT_TABLE = "kuaishou_video_comment"
    POST_ID_FIELD = "video_id"
    POST_TABLE = "kuaishou_video"
    POST_TABLE_USER_FIELD = "user_id"

    async def fetch_comments(
        self, target_id: str, cursor: Any = None, max_count: int = 100,
    ) -> CommentFetchResult:
        video_id = self._parse_video_id(target_id)
        if not video_id:
            return CommentFetchResult(error=f"无法解析 video_id: {target_id}")

        crawl_ok = await self._trigger_crawl(
            crawler_type="detail", specified_ids=video_id
        )
        if not crawl_ok:
            logger.warning(f"[KsFetcher] 爬虫启动失败 video_id={video_id}")

        comments = await self._read_comments_from_db(video_id, limit=max_count)
        return CommentFetchResult(
            comments=comments,
            has_more=False,
            error="" if comments else "无评论数据",
        )

    async def fetch_user_posts(self, sec_user_id: str) -> List[Dict]:
        crawl_ok = await self._trigger_crawl(
            crawler_type="creator", creator_ids=sec_user_id
        )
        if not crawl_ok:
            logger.warning(f"[KsFetcher] creator 爬虫启动失败 user_id={sec_user_id}")
        return await self._read_user_posts_from_db(sec_user_id, limit=10)

    async def _read_comments_from_db(self, post_id: str, limit: int = 100) -> List[UnifiedComment]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT comment_id, content, user_id, nickname, avatar, "
                        "create_time, video_id "
                        f"FROM {self.COMMENT_TABLE} WHERE video_id = :vid "
                        "ORDER BY create_time DESC LIMIT :l"
                    ),
                    {"vid": post_id, "l": limit},
                )
                comments = []
                for r in rows.fetchall():
                    comments.append(UnifiedComment(
                        platform=self.PLATFORM,
                        post_id=r[6] or post_id,
                        comment_id=r[0] or "",
                        comment_text=r[1] or "",
                        author_id=r[2] or "",
                        author_sec_uid="",
                        author_nickname=r[3] or "",
                        author_avatar=r[4] or "",
                        parent_comment_id="",  # ks 表无 parent_comment_id
                        like_count=0,
                        created_ts=self._safe_int(r[5]),
                    ))
                return comments
        except Exception as e:
            logger.error(f"[KsFetcher] 读DB评论失败: {e}")
            return []

    async def _read_user_posts_from_db(self, sec_user_id: str, limit: int = 10) -> List[Dict]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT video_id, title, desc as description, video_url, create_time "
                        f"FROM {self.POST_TABLE} WHERE user_id = :uid "
                        "ORDER BY create_time DESC LIMIT :l"
                    ),
                    {"uid": sec_user_id, "l": limit},
                )
                posts = []
                for r in rows.fetchall():
                    posts.append({
                        "post_id": r[0] or "",
                        "title": r[1] or r[2] or "",
                        "url": r[3] or "",
                        "created_ts": self._safe_int(r[4]),
                        "cover": "",
                    })
                return posts
        except Exception as e:
            logger.error(f"[KsFetcher] 读用户视频失败: {e}")
            return []

    @staticmethod
    def _parse_video_id(target: str) -> str:
        target = target.strip()
        # 快手 video_id 通常 8+ 位字母数字
        if re.fullmatch(r"[a-zA-Z0-9]{8,40}", target):
            return target
        m = re.search(r"/short-video/([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        m = re.search(r"/video/([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        m = re.search(r"/fw/photo/([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        m = re.search(r"[?&]photoId=([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        return ""


# ============ B站 ============

class BiliCommentFetcher(PlatformCommentFetcher):
    """B站评论抓取器"""

    PLATFORM = "bili"
    COMMENT_TABLE = "bilibili_video_comment"
    POST_ID_FIELD = "video_id"
    POST_TABLE = "bilibili_video"
    POST_TABLE_USER_FIELD = "user_id"

    async def fetch_comments(
        self, target_id: str, cursor: Any = None, max_count: int = 100,
    ) -> CommentFetchResult:
        video_id = self._parse_video_id(target_id)
        if not video_id:
            return CommentFetchResult(error=f"无法解析 video_id (BV/av): {target_id}")

        crawl_ok = await self._trigger_crawl(
            crawler_type="detail", specified_ids=video_id
        )
        if not crawl_ok:
            logger.warning(f"[BiliFetcher] 爬虫启动失败 video_id={video_id}")

        comments = await self._read_comments_from_db(video_id, limit=max_count)
        return CommentFetchResult(
            comments=comments,
            has_more=False,
            error="" if comments else "无评论数据",
        )

    async def fetch_user_posts(self, sec_user_id: str) -> List[Dict]:
        crawl_ok = await self._trigger_crawl(
            crawler_type="creator", creator_ids=sec_user_id
        )
        if not crawl_ok:
            logger.warning(f"[BiliFetcher] creator 爬虫启动失败 user_id={sec_user_id}")
        return await self._read_user_posts_from_db(sec_user_id, limit=10)

    async def _read_comments_from_db(self, post_id: str, limit: int = 100) -> List[UnifiedComment]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT comment_id, content, user_id, nickname, avatar, "
                        "parent_comment_id, like_count, create_time, video_id "
                        f"FROM {self.COMMENT_TABLE} WHERE video_id = :vid "
                        "ORDER BY create_time DESC LIMIT :l"
                    ),
                    {"vid": post_id, "l": limit},
                )
                comments = []
                for r in rows.fetchall():
                    comments.append(UnifiedComment(
                        platform=self.PLATFORM,
                        post_id=r[8] or post_id,
                        comment_id=r[0] or "",
                        comment_text=r[1] or "",
                        author_id=r[2] or "",
                        author_sec_uid="",
                        author_nickname=r[3] or "",
                        author_avatar=r[4] or "",
                        parent_comment_id=r[5] or "",
                        like_count=self._safe_int(r[6]),
                        created_ts=self._safe_int(r[7]),
                    ))
                return comments
        except Exception as e:
            logger.error(f"[BiliFetcher] 读DB评论失败: {e}")
            return []

    async def _read_user_posts_from_db(self, sec_user_id: str, limit: int = 10) -> List[Dict]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT video_id, video_url, user_id, nickname, add_ts "
                        f"FROM {self.POST_TABLE} WHERE user_id = :uid "
                        "ORDER BY add_ts DESC LIMIT :l"
                    ),
                    {"uid": sec_user_id, "l": limit},
                )
                posts = []
                for r in rows.fetchall():
                    posts.append({
                        "post_id": r[0] or "",
                        "title": "",
                        "url": r[1] or "",
                        "created_ts": self._safe_int(r[4]),
                        "cover": "",
                    })
                return posts
        except Exception as e:
            logger.error(f"[BiliFetcher] 读用户视频失败: {e}")
            return []

    @staticmethod
    def _parse_video_id(target: str) -> str:
        target = target.strip()
        # BV 号
        m = re.fullmatch(r"(BV[a-zA-Z0-9]{10})", target)
        if m:
            return m.group(1)
        m = re.search(r"/video/(BV[a-zA-Z0-9]{10})", target)
        if m:
            return m.group(1)
        # av 号（带前缀）
        m = re.fullmatch(r"av(\d+)", target, re.IGNORECASE)
        if m:
            return target
        m = re.search(r"/video/av(\d+)", target, re.IGNORECASE)
        if m:
            return f"av{m.group(1)}"
        # 纯数字 av 号（至少 6 位）
        m = re.fullmatch(r"(\d{6,12})", target)
        if m:
            return target
        m = re.search(r"/video/(\d{6,12})", target)
        if m:
            return m.group(1)
        return ""


# ============ 微博 ============

class WbCommentFetcher(PlatformCommentFetcher):
    """微博评论抓取器"""

    PLATFORM = "wb"
    COMMENT_TABLE = "weibo_note_comment"
    POST_ID_FIELD = "note_id"
    POST_TABLE = "weibo_note"
    POST_TABLE_USER_FIELD = "user_id"

    async def fetch_comments(
        self, target_id: str, cursor: Any = None, max_count: int = 100,
    ) -> CommentFetchResult:
        note_id = self._parse_note_id(target_id)
        if not note_id:
            return CommentFetchResult(error=f"无法解析 note_id (mid): {target_id}")

        crawl_ok = await self._trigger_crawl(
            crawler_type="detail", specified_ids=note_id
        )
        if not crawl_ok:
            logger.warning(f"[WbFetcher] 爬虫启动失败 note_id={note_id}")

        comments = await self._read_comments_from_db(note_id, limit=max_count)
        return CommentFetchResult(
            comments=comments,
            has_more=False,
            error="" if comments else "无评论数据",
        )

    async def fetch_user_posts(self, sec_user_id: str) -> List[Dict]:
        crawl_ok = await self._trigger_crawl(
            crawler_type="creator", creator_ids=sec_user_id
        )
        if not crawl_ok:
            logger.warning(f"[WbFetcher] creator 爬虫启动失败 user_id={sec_user_id}")
        return await self._read_user_posts_from_db(sec_user_id, limit=10)

    async def _read_comments_from_db(self, post_id: str, limit: int = 100) -> List[UnifiedComment]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT comment_id, content, user_id, nickname, avatar, "
                        "parent_comment_id, comment_like_count, create_time, note_id "
                        f"FROM {self.COMMENT_TABLE} WHERE note_id = :nid "
                        "ORDER BY create_time DESC LIMIT :l"
                    ),
                    {"nid": post_id, "l": limit},
                )
                comments = []
                for r in rows.fetchall():
                    comments.append(UnifiedComment(
                        platform=self.PLATFORM,
                        post_id=r[8] or post_id,
                        comment_id=r[0] or "",
                        comment_text=r[1] or "",
                        author_id=r[2] or "",
                        author_sec_uid="",
                        author_nickname=r[3] or "",
                        author_avatar=r[4] or "",
                        parent_comment_id=r[5] or "",
                        like_count=self._safe_int(r[6]),
                        created_ts=self._safe_int(r[7]),
                    ))
                return comments
        except Exception as e:
            logger.error(f"[WbFetcher] 读DB评论失败: {e}")
            return []

    async def _read_user_posts_from_db(self, sec_user_id: str, limit: int = 10) -> List[Dict]:
        try:
            from sqlalchemy import text as sql_text
            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT note_id, content, note_url, create_time "
                        f"FROM {self.POST_TABLE} WHERE user_id = :uid "
                        "ORDER BY create_time DESC LIMIT :l"
                    ),
                    {"uid": sec_user_id, "l": limit},
                )
                posts = []
                for r in rows.fetchall():
                    posts.append({
                        "post_id": r[0] or "",
                        "title": (r[1] or "")[:50],
                        "url": r[2] or "",
                        "created_ts": self._safe_int(r[3]),
                        "cover": "",
                    })
                return posts
        except Exception as e:
            logger.error(f"[WbFetcher] 读用户微博失败: {e}")
            return []

    @staticmethod
    def _parse_note_id(target: str) -> str:
        target = target.strip()
        # 微博 mid 通常是纯数字或 Base62
        if re.fullmatch(r"[a-zA-Z0-9]{8,20}", target):
            return target
        m = re.search(r"/detail/([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        # 优先匹配带字母的 note_id（如 N1234567890），避免误匹配 user_id
        m = re.search(r"/\d+/([a-zA-Z]+\d+[a-zA-Z0-9]*)", target)
        if m:
            return m.group(1)
        m = re.search(r"/(\d{10,20})(?:\?|$|/)", target)
        if m:
            return m.group(1)
        m = re.search(r"[?&]mid=([a-zA-Z0-9]+)", target)
        if m:
            return m.group(1)
        return ""


# ============ 工厂 ============

class CommentFetcherFactory:
    """评论抓取器工厂"""

    _registry: Dict[str, type] = {
        "douyin": DouyinCommentFetcher,
        "xhs": XhsCommentFetcher,
        "ks": KsCommentFetcher,
        "bili": BiliCommentFetcher,
        "wb": WbCommentFetcher,
    }

    @classmethod
    def create(
        cls, platform: str, owner_user_id: Optional[int] = None
    ) -> PlatformCommentFetcher:
        fetcher_cls = cls._registry.get(platform)
        if fetcher_cls is None:
            raise NotImplementedError(
                f"平台 {platform} 评论抓取暂未实现，当前支持: {list(cls._registry.keys())}"
            )
        return fetcher_cls(owner_user_id=owner_user_id)

    @classmethod
    def supported_platforms(cls) -> List[str]:
        return list(cls._registry.keys())
