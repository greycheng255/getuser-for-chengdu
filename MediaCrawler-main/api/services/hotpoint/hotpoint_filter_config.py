# -*- coding: utf-8 -*-
"""
热点筛选配置 + 抓取频率可调

阶段一 P0 任务 1.7：补齐 PRD 5.1.3 第 3 条
"热度阈值/行业品类/受众人群/地域范围筛选 + 5 分钟级抓取频率"。

提供：
1. HotpointFilterConfig 数据类：热度阈值/行业/受众/地域/关键词
2. HotpointFilterConfigService：CRUD + 用户隔离
3. 持久化到 hotpoint_filter_configs 表
4. 抓取频率配置（环境变量 HOTPOINT_FETCH_INTERVAL_SECONDS，最小 5 分钟）
"""

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============ 抓取频率（环境变量） ============
# 最小 5 分钟（300 秒），默认 30 分钟
DEFAULT_FETCH_INTERVAL = max(int(os.environ.get("HOTPOINT_FETCH_INTERVAL_SECONDS", "1800")), 300)


@dataclass
class HotpointFilterConfig:
    """热点筛选规则配置"""
    config_id: str = ""
    name: str = ""                              # 配置名称
    min_heat_value: int = 0                     # 最低热度阈值
    industry_categories: List[str] = field(default_factory=list)   # 行业品类
    target_audience: List[str] = field(default_factory=list)       # 受众人群
    regions: List[str] = field(default_factory=list)               # 地域范围
    include_keywords: List[str] = field(default_factory=list)      # 包含关键词
    exclude_keywords: List[str] = field(default_factory=list)      # 排除关键词
    only_viral: bool = False                    # 仅看爆款
    categories: List[str] = field(default_factory=list)            # 热点类型（entertainment/tech/...）
    platforms: List[str] = field(default_factory=list)             # 适配平台
    fetch_interval_seconds: int = DEFAULT_FETCH_INTERVAL           # 抓取频率
    owner_user_id: Optional[int] = None
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def matches(self, hotspot: Dict[str, Any]) -> bool:
        """判断热点是否匹配筛选规则"""
        # 热度阈值
        heat = int(hotspot.get("heat_value", 0) or 0)
        if heat < self.min_heat_value:
            return False
        # 爆款
        if self.only_viral and not hotspot.get("is_viral", False):
            return False
        # 类型
        if self.categories:
            cat = hotspot.get("category", "")
            if cat and cat not in self.categories:
                return False
        # 平台
        if self.platforms:
            hp_platforms = hotspot.get("platforms", []) or hotspot.get("platform", "")
            if isinstance(hp_platforms, str):
                hp_platforms = [hp_platforms]
            if hp_platforms and not any(p in self.platforms for p in hp_platforms):
                return False
        # 标题/描述关键词
        title = (hotspot.get("title", "") or "").lower()
        desc = (hotspot.get("description", "") or "").lower()
        text = f"{title} {desc}"
        for ex_kw in self.exclude_keywords:
            if ex_kw.lower() in text:
                return False
        if self.include_keywords:
            if not any(kw.lower() in text for kw in self.include_keywords):
                return False
        return True


class HotpointFilterConfigService:
    """筛选配置服务"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if HotpointFilterConfigService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS hotpoint_filter_configs ("
                        "  config_id VARCHAR(64) PRIMARY KEY,"
                        "  name VARCHAR(128),"
                        "  min_heat_value INTEGER DEFAULT 0,"
                        "  industry_categories TEXT,"
                        "  target_audience TEXT,"
                        "  regions TEXT,"
                        "  include_keywords TEXT,"
                        "  exclude_keywords TEXT,"
                        "  only_viral BOOLEAN DEFAULT FALSE,"
                        "  categories TEXT,"
                        "  platforms TEXT,"
                        "  fetch_interval_seconds INTEGER DEFAULT 1800,"
                        "  owner_user_id INTEGER,"
                        "  is_active BOOLEAN DEFAULT TRUE,"
                        "  created_at TIMESTAMP DEFAULT NOW(),"
                        "  updated_at TIMESTAMP DEFAULT NOW())"
                    )
                )
            HotpointFilterConfigService._ensured = True
        except Exception as e:
            logger.warning(f"[HotpointFilter] ensure_table failed: {e}")

    async def save_config(self, cfg: HotpointFilterConfig) -> bool:
        if not cfg.config_id:
            cfg.config_id = f"hfc_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        if not cfg.created_at:
            cfg.created_at = now
        cfg.updated_at = now
        # 抓取频率下限保护
        cfg.fetch_interval_seconds = max(cfg.fetch_interval_seconds, 300)

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO hotpoint_filter_configs "
                        "(config_id, name, min_heat_value, industry_categories, target_audience, "
                        " regions, include_keywords, exclude_keywords, only_viral, categories, "
                        " platforms, fetch_interval_seconds, owner_user_id, is_active, "
                        " created_at, updated_at) "
                        "VALUES (:cid, :nm, :mh, :ic, :ta, :rg, :ik, :ek, :ov, :ca, :pl, :fi, :ouid, :ia, :cr, :ua) "
                        "ON CONFLICT (config_id) DO UPDATE SET "
                        " name=EXCLUDED.name, min_heat_value=EXCLUDED.min_heat_value, "
                        " industry_categories=EXCLUDED.industry_categories, "
                        " target_audience=EXCLUDED.target_audience, regions=EXCLUDED.regions, "
                        " include_keywords=EXCLUDED.include_keywords, "
                        " exclude_keywords=EXCLUDED.exclude_keywords, "
                        " only_viral=EXCLUDED.only_viral, categories=EXCLUDED.categories, "
                        " platforms=EXCLUDED.platforms, "
                        " fetch_interval_seconds=EXCLUDED.fetch_interval_seconds, "
                        " owner_user_id=EXCLUDED.owner_user_id, is_active=EXCLUDED.is_active, "
                        " updated_at=EXCLUDED.updated_at"
                    ),
                    {
                        "cid": cfg.config_id,
                        "nm": cfg.name,
                        "mh": cfg.min_heat_value,
                        "ic": json.dumps(cfg.industry_categories, ensure_ascii=False),
                        "ta": json.dumps(cfg.target_audience, ensure_ascii=False),
                        "rg": json.dumps(cfg.regions, ensure_ascii=False),
                        "ik": json.dumps(cfg.include_keywords, ensure_ascii=False),
                        "ek": json.dumps(cfg.exclude_keywords, ensure_ascii=False),
                        "ov": cfg.only_viral,
                        "ca": json.dumps(cfg.categories, ensure_ascii=False),
                        "pl": json.dumps(cfg.platforms, ensure_ascii=False),
                        "fi": cfg.fetch_interval_seconds,
                        "ouid": cfg.owner_user_id,
                        "ia": cfg.is_active,
                        "cr": datetime.now(),
                        "ua": datetime.now(),
                    },
                )
            return True
        except Exception as e:
            logger.warning(f"[HotpointFilter] save_config failed: {e}")
            return False

    async def list_configs(
        self, owner_user_id: Optional[int] = None, active_only: bool = False
    ) -> List[Dict[str, Any]]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                sql = "SELECT * FROM hotpoint_filter_configs WHERE 1=1"
                params: Dict[str, Any] = {}
                if owner_user_id is not None:
                    sql += " AND owner_user_id = :ouid"
                    params["ouid"] = owner_user_id
                if active_only:
                    sql += " AND is_active = TRUE"
                sql += " ORDER BY created_at DESC"
                rows = await conn.execute(sql_text(sql), params)
                return [self._row_to_dict(r) for r in rows.fetchall()]
        except Exception as e:
            logger.warning(f"[HotpointFilter] list_configs failed: {e}")
            return []

    async def get_active_config(self, owner_user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """获取当前激活的筛选配置"""
        configs = await self.list_configs(owner_user_id=owner_user_id, active_only=True)
        return configs[0] if configs else None

    async def delete_config(self, config_id: str) -> bool:
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return False
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text("DELETE FROM hotpoint_filter_configs WHERE config_id = :cid"),
                    {"cid": config_id},
                )
            return True
        except Exception as e:
            logger.warning(f"[HotpointFilter] delete_config failed: {e}")
            return False

    async def preview(
        self, cfg: HotpointFilterConfig, limit: int = 20
    ) -> Dict[str, Any]:
        """预览筛选结果（不入库）"""
        try:
            from api.services.hotpoint.hot_items_store import get_hot_items_store

            store = get_hot_items_store()
            # 拉取最近 1 小时所有热点
            all_items_raw = await store.list_recent(hours=1, limit=200)
            all_items = []
            for r in all_items_raw:
                all_items.append({
                    "id": str(r.get("hot_id") or r.get("id") or ""),
                    "title": r.get("title") or "",
                    "description": r.get("description") or r.get("content") or "",
                    "platform": r.get("platform") or "",
                    "heat_value": int(r.get("heat_value") or 0),
                })
            matched = [item for item in all_items if cfg.matches(item)]
            return {
                "total": len(matched),
                "items": matched[:limit],
                "total_scanned": len(all_items),
            }
        except Exception as e:
            logger.warning(f"[HotpointFilter] preview failed: {e}")
            return {"total": 0, "items": [], "error": str(e)}

    def _row_to_dict(self, row) -> Dict[str, Any]:
        def _parse(v):
            try:
                return json.loads(v) if v else []
            except Exception:
                return []
        return {
            "config_id": row[0],
            "name": row[1],
            "min_heat_value": row[2],
            "industry_categories": _parse(row[3]),
            "target_audience": _parse(row[4]),
            "regions": _parse(row[5]),
            "include_keywords": _parse(row[6]),
            "exclude_keywords": _parse(row[7]),
            "only_viral": row[8],
            "categories": _parse(row[9]),
            "platforms": _parse(row[10]),
            "fetch_interval_seconds": row[11],
            "owner_user_id": row[12],
            "is_active": row[13],
            "created_at": str(row[14]) if row[14] else None,
            "updated_at": str(row[15]) if row[15] else None,
        }


# ============ 单例 ============
_service: Optional[HotpointFilterConfigService] = None


def get_hotpoint_filter_config_service() -> HotpointFilterConfigService:
    global _service
    if _service is None:
        _service = HotpointFilterConfigService()
    return _service
