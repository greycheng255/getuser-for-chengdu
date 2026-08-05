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


class ScriptType:
    COMMENT = "comment"
    DIRECT_MESSAGE = "direct_message"
    PUBLISH = "publish"
    ALL = {COMMENT, DIRECT_MESSAGE, PUBLISH}


def infer_script_type(scene: str) -> str:
    if scene in {ScriptScene.DIRECT_MESSAGE, ScriptScene.CONVERSION, "dm_reply"}:
        return ScriptType.DIRECT_MESSAGE
    return ScriptType.COMMENT


@dataclass
class Script:
    """话术条目"""
    script_id: str = ""
    platform: str = ""               # 平台名（空表示通用）
    script_type: str = ScriptType.COMMENT
    scene: str = ScriptScene.COMMENT_REPLY
    title: str = ""
    content: str = ""                # 话术内容
    tags: List[str] = field(default_factory=list)
    media_type: str = ""
    platform_constraints: List[str] = field(default_factory=list)
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

    def __init__(self, engine=None):
        self._engine = engine

    def _get_engine(self):
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        if self._engine is not None:
            return self._engine
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
                        "  script_type VARCHAR(32) DEFAULT 'comment',"
                        "  scene VARCHAR(32),"
                        "  title VARCHAR(256) DEFAULT '',"
                        "  content TEXT,"
                        "  tags TEXT,"
                        "  media_type VARCHAR(32) DEFAULT '',"
                        "  platform_constraints TEXT DEFAULT '[]',"
                        "  usage_count INTEGER DEFAULT 0,"
                        "  owner_user_id INTEGER,"
                        "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                    )
                )
                existing_columns = await conn.run_sync(
                    lambda sync_conn: {
                        column["name"]
                        for column in __import__("sqlalchemy").inspect(sync_conn).get_columns("interaction_scripts")
                    }
                )
                additions = {
                    "script_type": "VARCHAR(32) DEFAULT 'comment'",
                    "title": "VARCHAR(256) DEFAULT ''",
                    "media_type": "VARCHAR(32) DEFAULT ''",
                    "platform_constraints": "TEXT DEFAULT '[]'",
                }
                for column, ddl in additions.items():
                    if column not in existing_columns:
                        await conn.execute(sql_text(f"ALTER TABLE interaction_scripts ADD COLUMN {column} {ddl}"))
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
                                "(script_id, platform, script_type, scene, content, tags, usage_count) "
                                "VALUES (:sid, :pf, 'comment', :sc, :ct, '[]', 0)"
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
        script_type: Optional[str] = None,
        title: str = "",
        media_type: str = "",
        platform_constraints: Optional[List[str]] = None,
    ) -> Script:
        """新增话术"""
        await self.ensure_table()
        resolved_type = script_type or infer_script_type(scene)
        if resolved_type not in ScriptType.ALL:
            raise ValueError(f"不支持的话术类型: {resolved_type}")
        if not content.strip():
            raise ValueError("话术内容不能为空")
        script = Script(
            script_id=f"script_{uuid.uuid4().hex[:12]}",
            platform=platform,
            script_type=resolved_type,
            scene=scene,
            title=title,
            content=content,
            tags=tags or [],
            media_type=media_type,
            platform_constraints=platform_constraints or [],
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
                        "(script_id, platform, script_type, scene, title, content, tags, media_type, "
                        "platform_constraints, usage_count, owner_user_id, created_at) "
                        "VALUES (:sid, :pf, :st, :sc, :ti, :ct, :tg, :mt, :pc, 0, :ouid, :ca)"
                    ),
                    {
                        "sid": script.script_id,
                        "pf": script.platform,
                        "st": script.script_type,
                        "sc": script.scene,
                        "ti": script.title,
                        "ct": script.content,
                        "tg": json.dumps(script.tags, ensure_ascii=False),
                        "mt": script.media_type,
                        "pc": json.dumps(script.platform_constraints, ensure_ascii=False),
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
        script_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
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
                if script_type:
                    sql += " AND script_type = :st"
                    params["st"] = script_type
                if owner_user_id is not None:
                    sql += " AND (owner_user_id IS NULL OR owner_user_id = :ouid)"
                    params["ouid"] = owner_user_id
                for index, tag in enumerate(tags or []):
                    key = f"tag_{index}"
                    sql += f" AND tags LIKE :{key}"
                    params[key] = f'%"{tag}"%'
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
        script_type: Optional[str] = None,
        tag: Optional[str] = None,
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
                if script_type:
                    sql += " AND script_type = :st"
                    params["st"] = script_type
                if tag:
                    sql += " AND tags LIKE :tag"
                    params["tag"] = f'%"{tag}"%'
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

    async def migrate_legacy_types(self, *, dry_run: bool = True) -> Dict[str, Any]:
        """按 scene 幂等补齐一级类型，原 scene 值保持不变。"""

        await self.ensure_table()
        report: Dict[str, Any] = {"scanned": 0, "updated": 0, "review": []}
        engine = self._get_engine()
        if engine is None:
            return report
        from sqlalchemy import text as sql_text
        async with engine.begin() as conn:
            rows = await conn.execute(sql_text(
                "SELECT script_id, scene, script_type, tags FROM interaction_scripts"
            ))
            for row in rows.mappings().all():
                report["scanned"] += 1
                scene = row.get("scene") or ScriptScene.COMMENT_REPLY
                expected = infer_script_type(scene)
                if scene == ScriptScene.CONVERSION:
                    try:
                        tags = json.loads(row.get("tags") or "[]")
                    except Exception:
                        tags = []
                    if "comment" in tags and "dm" not in tags:
                        expected = ScriptType.COMMENT
                    elif not ({"dm", "direct_message"} & set(tags)):
                        report["review"].append({"script_id": row["script_id"], "scene": scene})
                if row.get("script_type") != expected:
                    report["updated"] += 1
                    if not dry_run:
                        await conn.execute(
                            sql_text("UPDATE interaction_scripts SET script_type=:st WHERE script_id=:sid"),
                            {"st": expected, "sid": row["script_id"]},
                        )
        report["dry_run"] = dry_run
        report["valid"] = not report["review"]
        return report

    async def batch_import(
        self,
        items: List[Dict[str, Any]],
        owner_user_id: Optional[int] = None,
    ) -> int:
        """批量导入话术，返回成功数量"""
        count = 0
        seen = set()
        for item in items:
            try:
                key = (
                    item.get("platform", ""),
                    item.get("script_type") or infer_script_type(item.get("scene", ScriptScene.COMMENT_REPLY)),
                    item.get("scene", ScriptScene.COMMENT_REPLY),
                    item.get("content", "").strip(),
                    owner_user_id,
                )
                if key in seen or not key[3]:
                    continue
                seen.add(key)
                existing = await self.list_scripts(
                    platform=key[0] or None,
                    script_type=key[1],
                    scene=key[2],
                    owner_user_id=owner_user_id,
                    limit=500,
                )
                if any(script.get("content", "").strip() == key[3] for script in existing):
                    continue
                await self.add_script(
                    platform=item.get("platform", ""),
                    scene=item.get("scene", ScriptScene.COMMENT_REPLY),
                    content=item.get("content", ""),
                    tags=item.get("tags", []),
                    owner_user_id=owner_user_id,
                    script_type=item.get("script_type"),
                    title=item.get("title", ""),
                    media_type=item.get("media_type", ""),
                    platform_constraints=item.get("platform_constraints", []),
                )
                count += 1
            except Exception as e:
                logger.warning(f"[ScriptLibrary] batch_import item failed: {e}")
        return count

    def _row_to_script(self, row) -> Script:
        values = row._mapping if hasattr(row, "_mapping") else row
        try:
            tags_raw = values.get("tags") if hasattr(values, "get") else None
            tags = json.loads(tags_raw) if tags_raw else []
        except Exception:
            tags = []
        try:
            constraints_raw = values.get("platform_constraints") if hasattr(values, "get") else None
            constraints = json.loads(constraints_raw) if constraints_raw else []
        except Exception:
            constraints = []
        return Script(
            script_id=values.get("script_id", ""),
            platform=values.get("platform", "") or "",
            script_type=values.get("script_type") or infer_script_type(values.get("scene", "")),
            scene=values.get("scene") or ScriptScene.COMMENT_REPLY,
            title=values.get("title", "") or "",
            content=values.get("content", "") or "",
            tags=tags,
            media_type=values.get("media_type", "") or "",
            platform_constraints=constraints,
            usage_count=int(values.get("usage_count") or 0),
            owner_user_id=values.get("owner_user_id"),
            created_at=str(values.get("created_at")) if values.get("created_at") else None,
        )


# ============ 单例 ============

_library: Optional[ScriptLibrary] = None


def get_script_library() -> ScriptLibrary:
    global _library
    if _library is None:
        _library = ScriptLibrary()
    return _library
