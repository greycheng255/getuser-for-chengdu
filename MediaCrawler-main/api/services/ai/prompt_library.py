# -*- coding: utf-8 -*-
"""
提示词库沉淀服务（阶段四任务 4.2）

对应 PRD 8.5 抓取视频 - 提示词库可检索复用：
1. 从历史热点视频提取的提示词 + 分镜结构化存储
2. 支持检索（关键词 + 类型 + 风格 + 相似度）
3. 支持复用（按 ID 加载，按相似度推荐）
4. 支持变体生成（基于已有提示词微调）
5. 持久化到 prompt_library + storyboards 表

设计：异步 + PostgreSQL + JSONB。
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ==================== 数据类 ====================


@dataclass
class PromptRecord:
    """提示词库记录"""

    prompt_id: str = ""
    title: str = ""
    prompt_text: str = ""  # 整体提示词
    category: str = ""  # 热点类型
    style_keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    source_video_url: str = ""
    source_hotspot_id: str = ""
    storyboard_id: str = ""  # 关联分镜 ID
    usage_count: int = 0  # 复用次数
    success_count: int = 0  # 成功生成视频次数
    avg_rating: float = 0.0  # AI 评分 0-5
    owner_user_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==================== 服务 ====================


class PromptLibrary:
    """提示词库服务

    表结构：
        prompt_library:
            prompt_id VARCHAR(64) PRIMARY KEY
            title VARCHAR(256)
            prompt_text TEXT
            category VARCHAR(64)
            style_keywords JSONB
            tags JSONB
            source_video_url TEXT
            source_hotspot_id VARCHAR(64)
            storyboard_id VARCHAR(64)
            usage_count INT DEFAULT 0
            success_count INT DEFAULT 0
            avg_rating NUMERIC(3,2) DEFAULT 0
            owner_user_id INT
            created_at TIMESTAMP
            updated_at TIMESTAMP

        storyboards:
            storyboard_id VARCHAR(64) PRIMARY KEY
            source_video_url TEXT
            title VARCHAR(256)
            total_duration NUMERIC(8,2)
            scenes_json JSONB
            overall_prompt TEXT
            style_keywords JSONB
            category VARCHAR(64)
            tags JSONB
            owner_user_id INT
            created_at TIMESTAMP
    """

    TABLE_PROMPT = "prompt_library"
    TABLE_STORYBOARD = "storyboards"
    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self):
        if PromptLibrary._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        f"CREATE TABLE IF NOT EXISTS {self.TABLE_STORYBOARD} ("
                        "  storyboard_id VARCHAR(64) PRIMARY KEY,"
                        "  source_video_url TEXT,"
                        "  title VARCHAR(256),"
                        "  total_duration NUMERIC(8,2) DEFAULT 0,"
                        "  scenes_json JSONB,"
                        "  overall_prompt TEXT,"
                        "  style_keywords JSONB,"
                        "  category VARCHAR(64),"
                        "  tags JSONB,"
                        "  owner_user_id INT,"
                        "  created_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        f"CREATE TABLE IF NOT EXISTS {self.TABLE_PROMPT} ("
                        "  prompt_id VARCHAR(64) PRIMARY KEY,"
                        "  title VARCHAR(256),"
                        "  prompt_text TEXT,"
                        "  category VARCHAR(64),"
                        "  style_keywords JSONB,"
                        "  tags JSONB,"
                        "  source_video_url TEXT,"
                        "  source_hotspot_id VARCHAR(64),"
                        "  storyboard_id VARCHAR(64),"
                        "  usage_count INT DEFAULT 0,"
                        "  success_count INT DEFAULT 0,"
                        "  avg_rating NUMERIC(3,2) DEFAULT 0,"
                        "  owner_user_id INT,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  updated_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_prompt_library_category "
                        f"ON {self.TABLE_PROMPT} (category)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_prompt_library_tags "
                        f"ON {self.TABLE_PROMPT} USING GIN (tags)"
                    )
                )
            PromptLibrary._ensured = True
        except Exception as e:
            logger.warning(f"[PromptLibrary] 建表失败: {e}")

    # ==================== 写入 ====================

    async def save_storyboard(self, storyboard) -> Optional[str]:
        """沉淀分镜到库(storyboard 为 Storyboard 数据类实例)"""
        await self.ensure_table()
        if not storyboard.storyboard_id:
            storyboard.storyboard_id = f"sb_{uuid.uuid4().hex[:12]}"
        if not storyboard.created_at:
            storyboard.created_at = datetime.utcnow().isoformat()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        f"INSERT INTO {self.TABLE_STORYBOARD} "
                        "(storyboard_id, source_video_url, title, total_duration, scenes_json, "
                        "overall_prompt, style_keywords, category, tags, owner_user_id) "
                        "VALUES (:sid, :sv, :t, :td, :sj, :op, :sk, :c, :tg, :u) "
                        "ON CONFLICT (storyboard_id) DO UPDATE SET "
                        "  title=EXCLUDED.title, scenes_json=EXCLUDED.scenes_json, "
                        "  overall_prompt=EXCLUDED.overall_prompt, category=EXCLUDED.category"
                    ),
                    {
                        "sid": storyboard.storyboard_id,
                        "sv": storyboard.source_video_url,
                        "t": storyboard.title[:256],
                        "td": storyboard.total_duration,
                        "sj": json.dumps([asdict(s) for s in storyboard.scenes], ensure_ascii=False),
                        "op": storyboard.overall_prompt,
                        "sk": json.dumps(storyboard.style_keywords, ensure_ascii=False),
                        "c": storyboard.category,
                        "tg": json.dumps(storyboard.tags, ensure_ascii=False),
                        "u": storyboard.owner_user_id,
                    },
                )
            return storyboard.storyboard_id
        except Exception as e:
            logger.warning(f"[PromptLibrary] 沉淀分镜失败: {e}")
            return None

    async def save_prompt(
        self,
        *,
        title: str,
        prompt_text: str,
        category: str = "",
        style_keywords: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        source_video_url: str = "",
        source_hotspot_id: str = "",
        storyboard_id: str = "",
        owner_user_id: Optional[int] = None,
    ) -> Optional[str]:
        """沉淀提示词到库"""
        await self.ensure_table()
        prompt_id = f"pl_{uuid.uuid4().hex[:12]}"
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        f"INSERT INTO {self.TABLE_PROMPT} "
                        "(prompt_id, title, prompt_text, category, style_keywords, tags, "
                        "source_video_url, source_hotspot_id, storyboard_id, owner_user_id) "
                        "VALUES (:pid, :t, :pt, :c, :sk, :tg, :sv, :sh, :sid, :u)"
                    ),
                    {
                        "pid": prompt_id,
                        "t": title[:256],
                        "pt": prompt_text,
                        "c": category,
                        "sk": json.dumps(style_keywords or [], ensure_ascii=False),
                        "tg": json.dumps(tags or [], ensure_ascii=False),
                        "sv": source_video_url,
                        "sh": source_hotspot_id,
                        "sid": storyboard_id,
                        "u": owner_user_id,
                    },
                )
            return prompt_id
        except Exception as e:
            logger.warning(f"[PromptLibrary] 沉淀提示词失败: {e}")
            return None

    # ==================== 查询 ====================

    async def search(
        self,
        *,
        keyword: str = "",
        category: str = "",
        tags: Optional[List[str]] = None,
        style_keyword: str = "",
        owner_user_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[PromptRecord]:
        """检索提示词

        支持关键词模糊匹配 + 分类 + 标签 + 风格关键词组合查询
        """
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            conditions: List[str] = []
            params: Dict[str, Any] = {"l": limit, "o": offset}
            if keyword:
                conditions.append("(title ILIKE :kw OR prompt_text ILIKE :kw)")
                params["kw"] = f"%{keyword}%"
            if category:
                conditions.append("category = :c")
                params["c"] = category
            if style_keyword:
                conditions.append("style_keywords @> :sk")
                params["sk"] = json.dumps([style_keyword])
            if tags:
                conditions.append("tags @> :tg")
                params["tg"] = json.dumps(tags)
            if owner_user_id is not None:
                conditions.append("(owner_user_id = :u OR owner_user_id IS NULL)")
                params["u"] = owner_user_id

            sql = f"SELECT prompt_id, title, prompt_text, category, style_keywords, tags, " \
                  f"source_video_url, source_hotspot_id, storyboard_id, usage_count, " \
                  f"success_count, avg_rating, owner_user_id, created_at, updated_at " \
                  f"FROM {self.TABLE_PROMPT}"
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY usage_count DESC, avg_rating DESC, created_at DESC LIMIT :l OFFSET :o"

            async with engine.connect() as conn:
                rows = await conn.execute(sql_text(sql), params)
                results: List[PromptRecord] = []
                for r in rows.fetchall():
                    results.append(self._row_to_prompt(r))
                return results
        except Exception as e:
            logger.warning(f"[PromptLibrary] 检索失败: {e}")
            return []

    async def get(self, prompt_id: str) -> Optional[PromptRecord]:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT prompt_id, title, prompt_text, category, style_keywords, tags, "
                        f"source_video_url, source_hotspot_id, storyboard_id, usage_count, "
                        f"success_count, avg_rating, owner_user_id, created_at, updated_at "
                        f"FROM {self.TABLE_PROMPT} WHERE prompt_id=:pid"
                    ),
                    {"pid": prompt_id},
                )
                r = rows.fetchone()
                return self._row_to_prompt(r) if r else None
        except Exception as e:
            logger.warning(f"[PromptLibrary] 查询失败: {e}")
            return None

    async def get_storyboard(self, storyboard_id: str) -> Optional[Dict[str, Any]]:
        """获取分镜详情"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT storyboard_id, source_video_url, title, total_duration, "
                        f"scenes_json, overall_prompt, style_keywords, category, tags, "
                        f"owner_user_id, created_at "
                        f"FROM {self.TABLE_STORYBOARD} WHERE storyboard_id=:sid"
                    ),
                    {"sid": storyboard_id},
                )
                r = rows.fetchone()
                if not r:
                    return None
                return {
                    "storyboard_id": r[0],
                    "source_video_url": r[1],
                    "title": r[2],
                    "total_duration": float(r[3] or 0),
                    "scenes": r[4] if isinstance(r[4], list) else (json.loads(r[4]) if r[4] else []),
                    "overall_prompt": r[5],
                    "style_keywords": r[6] if isinstance(r[6], list) else (json.loads(r[6]) if r[6] else []),
                    "category": r[7],
                    "tags": r[8] if isinstance(r[8], list) else (json.loads(r[8]) if r[8] else []),
                    "owner_user_id": r[9],
                    "created_at": str(r[10]) if r[10] else None,
                }
        except Exception as e:
            logger.warning(f"[PromptLibrary] 查询分镜失败: {e}")
            return None

    async def find_similar(
        self,
        *,
        category: str = "",
        tags: Optional[List[str]] = None,
        style_keyword: str = "",
        limit: int = 5,
    ) -> List[PromptRecord]:
        """查找相似提示词（按分类+标签+风格匹配）"""
        return await self.search(
            category=category,
            tags=tags,
            style_keyword=style_keyword,
            limit=limit,
        )

    # ==================== 更新 ====================

    async def mark_used(self, prompt_id: str, success: bool = True, rating: float = 0.0):
        """记录一次复用"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                if success:
                    await conn.execute(
                        sql_text(
                            f"UPDATE {self.TABLE_PROMPT} SET "
                            "  usage_count = usage_count + 1, "
                            "  success_count = success_count + 1, "
                            "  avg_rating = (avg_rating * success_count + :r) / (success_count + 1), "
                            "  updated_at = NOW() "
                            "WHERE prompt_id=:pid"
                        ),
                        {"pid": prompt_id, "r": rating},
                    )
                else:
                    await conn.execute(
                        sql_text(
                            f"UPDATE {self.TABLE_PROMPT} SET "
                            "  usage_count = usage_count + 1, "
                            "  updated_at = NOW() "
                            "WHERE prompt_id=:pid"
                        ),
                        {"pid": prompt_id},
                    )
        except Exception as e:
            logger.warning(f"[PromptLibrary] 更新使用计数失败: {e}")

    async def generate_variant(
        self, prompt_id: str, variant_intent: str = ""
    ) -> Optional[str]:
        """基于已有提示词生成变体（AI 微调）

        Args:
            prompt_id: 源提示词 ID
            variant_intent: 变体方向（如"更幽默"、"更专业"、"更口语"）

        Returns:
            新变体提示词文本
        """
        source = await self.get(prompt_id)
        if not source:
            return None
        try:
            from api.services.ai_agent_client import get_ai_agent_client, is_ai_in_cooldown, is_ai_expected_error

            if is_ai_in_cooldown():
                logger.debug("[PromptLibrary] AI 服务冷却中，跳过变体生成")
                return None
            prompt = (
                f"以下是一个已成功的视频生成提示词：\n{source.prompt_text}\n\n"
                f"请基于此生成一个变体提示词，要求：{variant_intent or '保持原意但更差异化'}\n"
                "直接输出新的提示词，不要解释。"
            )
            client = get_ai_agent_client()
            result = await client.generate_text(prompt)
            return result.strip() if result else None
        except Exception as e:
            if is_ai_expected_error(e):
                logger.debug(f"[PromptLibrary] AI 预期内错误跳过: {e}")
            else:
                logger.warning(f"[PromptLibrary] 生成变体失败: {e}")
            return None

    # ==================== 私有 ====================

    def _row_to_prompt(self, r) -> PromptRecord:
        def _parse(val):
            if val is None:
                return []
            if isinstance(val, (list, dict)):
                return val
            try:
                return json.loads(val)
            except Exception:
                return []

        return PromptRecord(
            prompt_id=str(r[0] or ""),
            title=str(r[1] or ""),
            prompt_text=str(r[2] or ""),
            category=str(r[3] or ""),
            style_keywords=_parse(r[4]),
            tags=_parse(r[5]),
            source_video_url=str(r[6] or ""),
            source_hotspot_id=str(r[7] or ""),
            storyboard_id=str(r[8] or ""),
            usage_count=int(r[9] or 0),
            success_count=int(r[10] or 0),
            avg_rating=float(r[11] or 0),
            owner_user_id=r[12],
            created_at=str(r[13]) if r[13] else None,
            updated_at=str(r[14]) if r[14] else None,
        )


# ==================== 单例 ====================

_singleton: Optional[PromptLibrary] = None


def get_prompt_library() -> PromptLibrary:
    global _singleton
    if _singleton is None:
        _singleton = PromptLibrary()
    return _singleton
