# -*- coding: utf-8 -*-
"""
互动话术库（最小骨架）

阶段二 P1 任务 2.5：补齐 PRD 5.4 话术智能配置。
当前为最小骨架，供 interaction_scheduler 引用；完整实现见任务 2.5。

设计：
1. 话术按平台 + 场景分类存储
2. 支持 CRUD + 批量导入
3. 支持 AI 差异化话术生成（任务 2.5 接入）
4. 互动时随机选取话术，避免重复
"""

import json
import logging
import random
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# 场景分类
class ScriptScene:
    COMMENT_REPLY = "comment_reply"        # 评论回复
    DIRECT_MESSAGE = "direct_message"       # 私信
    ENGAGEMENT_BOOST = "engagement_boost"   # 互动引导
    CONVERSION = "conversion"               # 转化引导


@dataclass
class Script:
    """话术条目"""
    script_id: str = ""
    platform: str = ""               # 平台名（空表示通用）
    scene: str = ScriptScene.COMMENT_REPLY
    content: str = ""                # 话术内容
    tags: List[str] = field(default_factory=list)
    usage_count: int = 0             # 使用次数
    owner_user_id: Optional[int] = None
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# 内置默认话术（首次启动时入库）
DEFAULT_SCRIPTS = [
    ("douyin", ScriptScene.COMMENT_REPLY, "干货满满，学到了！"),
    ("douyin", ScriptScene.COMMENT_REPLY, "这个角度很新颖，受教了。"),
    ("douyin", ScriptScene.COMMENT_REPLY, "内容很实用，已关注。"),
    ("xiaohongshu", ScriptScene.COMMENT_REPLY, "姐妹这个好用心，码住！"),
    ("xiaohongshu", ScriptScene.COMMENT_REPLY, "种草了，求链接～"),
    ("bilibili", ScriptScene.COMMENT_REPLY, "讲得真清楚，期待更新。"),
    ("bilibili", ScriptScene.COMMENT_REPLY, "三连了，求更多系列。"),
    ("weibo", ScriptScene.COMMENT_REPLY, "这个分析到位了。"),
    ("zhihu", ScriptScene.COMMENT_REPLY, "感谢分享，受益匪浅。"),
    ("kuaishou", ScriptScene.COMMENT_REPLY, "老铁这波讲得透彻。"),
    ("", ScriptScene.COMMENT_REPLY, "收藏了，慢慢消化。"),
    ("", ScriptScene.COMMENT_REPLY, "这个观点很有启发。"),
]


class ScriptLibrary:
    """话术库服务"""

    _ensured = False  # DDL 仅首次执行一次，避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if ScriptLibrary._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS interaction_scripts ("
                        "  script_id VARCHAR(64) PRIMARY KEY,"
                        "  platform VARCHAR(32),"
                        "  scene VARCHAR(32),"
                        "  content TEXT,"
                        "  tags TEXT,"
                        "  usage_count INTEGER DEFAULT 0,"
                        "  owner_user_id INTEGER,"
                        "  created_at TIMESTAMP DEFAULT NOW())"
                    )
                )
                # 查询索引（list_scripts/pick_random 高频查询路径）
                # 复合索引覆盖 platform+scene+owner 过滤 + created_at 排序
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_scripts_platform_scene "
                        "ON interaction_scripts(platform, scene, created_at DESC)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_scripts_owner "
                        "ON interaction_scripts(owner_user_id, created_at DESC)"
                    )
                )
                # 首次创建时灌入默认话术（批量插入优化）
                rows = await conn.execute(
                    sql_text("SELECT COUNT(*) FROM interaction_scripts")
                )
                if int(rows.fetchone()[0] or 0) == 0:
                    # 构建批量插入数据
                    default_data = [
                        {
                            "sid": f"script_{uuid.uuid4().hex[:12]}",
                            "pf": pf,
                            "sc": scene,
                            "ct": content,
                        }
                        for pf, scene, content in DEFAULT_SCRIPTS
                    ]
                    # 批量插入（单次事务）
                    for item in default_data:
                        await conn.execute(
                            sql_text(
                                "INSERT INTO interaction_scripts "
                                "(script_id, platform, scene, content, tags, usage_count) "
                                "VALUES (:sid, :pf, :sc, :ct, '[]', 0)"
                            ),
                            item,
                        )
            ScriptLibrary._ensured = True
        except Exception as e:
            logger.warning(f"[ScriptLibrary] ensure_table failed: {e}")

    async def add_script(
        self,
        platform: str,
        scene: str,
        content: str,
        tags: Optional[List[str]] = None,
        owner_user_id: Optional[int] = None,
    ) -> Script:
        """新增话术"""
        await self.ensure_table()
        script = Script(
            script_id=f"script_{uuid.uuid4().hex[:12]}",
            platform=platform,
            scene=scene,
            content=content,
            tags=tags or [],
            owner_user_id=owner_user_id,
            created_at=datetime.now().isoformat(),
        )
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return script
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO interaction_scripts "
                        "(script_id, platform, scene, content, tags, usage_count, owner_user_id, created_at) "
                        "VALUES (:sid, :pf, :sc, :ct, :tg, 0, :ouid, :ca)"
                    ),
                    {
                        "sid": script.script_id,
                        "pf": script.platform,
                        "sc": script.scene,
                        "ct": script.content,
                        "tg": json.dumps(script.tags, ensure_ascii=False),
                        "ouid": script.owner_user_id,
                        "ca": datetime.now(),
                    },
                )
        except Exception as e:
            logger.warning(f"[ScriptLibrary] add_script failed: {e}")
        return script

    async def pick_random(
        self,
        platform: str = "",
        scene: str = ScriptScene.COMMENT_REPLY,
        owner_user_id: Optional[int] = None,
    ) -> Optional[Script]:
        """随机选取一条话术（优先平台匹配，其次通用）"""
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            async with engine.begin() as conn:  # 需要写操作，使用 begin()
                # 优先匹配平台 + 场景
                sql = (
                    "SELECT * FROM interaction_scripts "
                    "WHERE scene = :sc AND (platform = :pf OR platform = '')"
                )
                params: Dict[str, Any] = {"sc": scene, "pf": platform}
                if owner_user_id is not None:
                    sql += " AND (owner_user_id IS NULL OR owner_user_id = :ouid)"
                    params["ouid"] = owner_user_id
                sql += " ORDER BY usage_count ASC, RANDOM() LIMIT 1"
                rows = await conn.execute(sql_text(sql), params)
                row = rows.fetchone()
                if not row:
                    return None
                script = self._row_to_script(row)
                # 使用次数 +1
                await conn.execute(
                    sql_text(
                        "UPDATE interaction_scripts SET usage_count = usage_count + 1 "
                        "WHERE script_id = :sid"
                    ),
                    {"sid": script.script_id},
                )
                return script
        except Exception as e:
            logger.warning(f"[ScriptLibrary] pick_random failed: {e}")
            return None

    async def list_scripts(
        self,
        platform: Optional[str] = None,
        scene: Optional[str] = None,
        owner_user_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:  # 只读查询，使用 connect()
                sql = "SELECT * FROM interaction_scripts WHERE 1=1"
                params: Dict[str, Any] = {"limit": limit, "offset": offset}
                if platform:
                    sql += " AND platform = :pf"
                    params["pf"] = platform
                if scene:
                    sql += " AND scene = :sc"
                    params["sc"] = scene
                if owner_user_id is not None:
                    sql += " AND (owner_user_id IS NULL OR owner_user_id = :ouid)"
                    params["ouid"] = owner_user_id
                sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_script(r).to_dict() for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[ScriptLibrary] list_scripts failed: {e}")
            return []

    async def delete_script(self, script_id: str) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text("DELETE FROM interaction_scripts WHERE script_id = :sid"),
                    {"sid": script_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[ScriptLibrary] delete_script failed: {e}")
            return False

    async def batch_import(
        self,
        items: List[Dict[str, Any]],
        owner_user_id: Optional[int] = None,
    ) -> int:
        """批量导入话术，返回成功数量"""
        count = 0
        for item in items:
            try:
                await self.add_script(
                    platform=item.get("platform", ""),
                    scene=item.get("scene", ScriptScene.COMMENT_REPLY),
                    content=item.get("content", ""),
                    tags=item.get("tags", []),
                    owner_user_id=owner_user_id,
                )
                count += 1
            except Exception as e:
                logger.warning(f"[ScriptLibrary] batch_import item failed: {e}")
        return count

    def _row_to_script(self, row) -> Script:
        try:
            tags = json.loads(row[4]) if row[4] else []
        except Exception:
            tags = []
        return Script(
            script_id=row[0],
            platform=row[1] or "",
            scene=row[2] or ScriptScene.COMMENT_REPLY,
            content=row[3] or "",
            tags=tags,
            usage_count=int(row[5] or 0),
            owner_user_id=row[6],
            created_at=str(row[7]) if row[7] else None,
        )


# ============ 单例 ============

_library: Optional[ScriptLibrary] = None


def get_script_library() -> ScriptLibrary:
    global _library
    if _library is None:
        _library = ScriptLibrary()
    return _library
