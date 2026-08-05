# -*- coding: utf-8 -*-
"""
本地生活服务

职责：
1. ensure_table 创建 local_business 表
2. search_from_amap 透传高德搜索（不落库）
3. get_business_detail 高德 POI 详情
4. save_business / batch_save_from_amap upsert 到 local_business
5. list_businesses / get_business / update_business / delete_business
6. export_businesses 导出 xlsx
7. 字段映射 _map_amap_to_business
"""
import io
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from .amap_client import get_amap_client

logger = logging.getLogger(__name__)


class LocalLifeService:
    """本地生活服务（单例）"""

    _ensured = False

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        if LocalLifeService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS local_business ("
                        "  id SERIAL PRIMARY KEY,"
                        "  business_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  name VARCHAR(255) NOT NULL,"
                        "  phone TEXT DEFAULT '',"
                        "  address TEXT DEFAULT '',"
                        "  province VARCHAR(64) DEFAULT '',"
                        "  city VARCHAR(64) DEFAULT '',"
                        "  district VARCHAR(64) DEFAULT '',"
                        "  business_hours TEXT DEFAULT '',"
                        "  latitude FLOAT DEFAULT 0,"
                        "  longitude FLOAT DEFAULT 0,"
                        "  platform VARCHAR(20) DEFAULT 'amap',"
                        "  platform_poi_id VARCHAR(255) DEFAULT '',"
                        "  rating FLOAT DEFAULT 0,"
                        "  rating_count INTEGER DEFAULT 0,"
                        "  category VARCHAR(255) DEFAULT '',"
                        "  tags TEXT DEFAULT '[]',"
                        "  photos TEXT DEFAULT '[]',"
                        "  price_avg INTEGER DEFAULT 0,"
                        "  source VARCHAR(20) DEFAULT 'amap',"
                        "  extra TEXT DEFAULT '{}',"
                        "  owner_user_id VARCHAR(64) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0,"
                        "  UNIQUE(platform, platform_poi_id, owner_user_id)"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_local_biz_owner "
                        "ON local_business(owner_user_id, created_at DESC)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_local_biz_city "
                        "ON local_business(city, category)"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_local_biz_name "
                        "ON local_business(name)"
                    )
                )
            LocalLifeService._ensured = True
            print("[local_life] 表已就绪")
        except Exception as e:
            logger.warning(f"[local_life] ensure_table failed: {e}")

    # ==================== 高德搜索 ====================

    async def search_from_amap(
        self,
        keyword: str,
        city: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        types: Optional[str] = None,
    ) -> Dict:
        """透传高德搜索结果（不落库）"""
        client = get_amap_client()
        if not client.is_configured():
            return {
                "configured": False,
                "items": [],
                "total": 0,
                "page": page,
                "message": "未配置 AMAP_API_KEY，请在 .env 中设置",
            }
        raw = await client.search_poi(
            keyword=keyword, city=city, page=page, page_size=page_size, types=types
        )
        pois = raw.get("pois") or []
        items = [self._map_amap_to_poi(p) for p in pois]
        return {
            "configured": True,
            "items": items,
            "total": int(raw.get("count", 0) or len(items)),
            "page": page,
            "page_size": page_size,
            "raw_count": raw.get("count"),
        }

    async def get_business_detail(self, *, source: str = "amap", poi_id: str) -> Dict:
        """获取高德 POI 详情"""
        client = get_amap_client()
        if not client.is_configured():
            return {"configured": False, "detail": None}
        raw = await client.get_poi_detail(poi_id)
        # v5 详情接口返回 {pois:[...]}
        pois = raw.get("pois") or []
        if not pois:
            return {"configured": True, "detail": None, "raw": raw}
        return {
            "configured": True,
            "detail": self._map_amap_to_poi(pois[0]),
            "raw": raw,
        }

    # ==================== 保存 / 列表 / 详情 / 更新 / 删除 ====================

    async def save_business(
        self,
        *,
        platform: str = "amap",
        poi_id: str,
        owner_user_id: str = "",
        extra: Optional[Dict] = None,
    ) -> Dict:
        """保存单个商家（先从高德拉详情，再 upsert）"""
        await self.ensure_table()
        # 拉详情
        detail = await self.get_business_detail(source=platform, poi_id=poi_id)
        if not detail.get("detail"):
            # 兜底：用 extra 中提供的数据
            if not extra:
                return {"saved": False, "reason": "无法获取 POI 详情且无 extra 数据"}
            poi_data = extra
        else:
            poi_data = detail["detail"]
        # 合并 extra 覆盖
        if extra:
            poi_data.update(extra)
        return await self._upsert_business(
            poi_data=poi_data, platform=platform, owner_user_id=owner_user_id
        )

    async def batch_save_from_amap(
        self, items: List[Dict], owner_user_id: str = "", platform: str = "amap"
    ) -> Dict:
        """批量保存（items 来自 search_from_amap 的 items）"""
        await self.ensure_table()
        ok = 0
        skipped = 0
        for it in items:
            poi_id = it.get("poi_id") or ""
            if not poi_id:
                skipped += 1
                continue
            r = await self._upsert_business(
                poi_data=it, platform=platform, owner_user_id=owner_user_id
            )
            if r.get("saved"):
                ok += 1
            else:
                skipped += 1
        return {"saved": ok, "skipped": skipped, "total": len(items)}

    async def list_businesses(
        self,
        *,
        owner_user_id: str = "",
        city: Optional[str] = None,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        min_rating: Optional[float] = None,
        page: int = 1,
        page_size: int = 20,
        is_admin: bool = False,
    ) -> Dict:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = []
            params: Dict[str, Any] = {}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            if city:
                conditions.append("city = :city")
                params["city"] = city
            if category:
                conditions.append("category LIKE :cat")
                params["cat"] = f"%{category}%"
            if keyword:
                conditions.append("(name LIKE :kw OR address LIKE :kw OR phone LIKE :kw)")
                params["kw"] = f"%{keyword}%"
            if min_rating is not None:
                conditions.append("rating >= :mr")
                params["mr"] = float(min_rating)
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            async with engine.connect() as conn:
                cnt = await conn.execute(
                    sql_text(f"SELECT COUNT(*) FROM local_business{where}"), params
                )
                total = int(cnt.fetchone()[0] or 0)
                offset = (page - 1) * page_size
                params["lim"] = page_size
                params["off"] = offset
                rows = await conn.execute(
                    sql_text(
                        f"SELECT business_id, name, phone, address, province, city, district, "
                        f" business_hours, latitude, longitude, platform, platform_poi_id, "
                        f" rating, rating_count, category, tags, photos, price_avg, source, "
                        f" owner_user_id, created_at, updated_at "
                        f"FROM local_business{where} "
                        f"ORDER BY rating DESC NULLS LAST, created_at DESC "
                        f"LIMIT :lim OFFSET :off"
                    ),
                    params,
                )
                items = [self._row_to_biz_dict(r) for r in rows.fetchall()]
            return {"total": total, "page": page, "page_size": page_size, "items": items}
        except Exception as e:
            logger.error(f"[local_life] list_businesses failed: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "items": []}

    async def get_business(
        self, business_id: str, owner_user_id: str = "", is_admin: bool = False
    ) -> Optional[Dict]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["business_id = :bid"]
            params = {"bid": business_id}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT business_id, name, phone, address, province, city, district, "
                        " business_hours, latitude, longitude, platform, platform_poi_id, "
                        " rating, rating_count, category, tags, photos, price_avg, source, "
                        " owner_user_id, created_at, updated_at "
                        "FROM local_business WHERE " + " AND ".join(conditions)
                    ),
                    params,
                )
                r = rows.fetchone()
                return self._row_to_biz_dict(r) if r else None
        except Exception as e:
            logger.error(f"[local_life] get_business failed: {e}")
            return None

    async def update_business(
        self,
        business_id: str,
        *,
        owner_user_id: str = "",
        is_admin: bool = False,
        **fields,
    ) -> bool:
        await self.ensure_table()
        allowed = {
            "name", "phone", "address", "province", "city", "district",
            "business_hours", "category", "tags", "photos", "price_avg",
            "rating", "rating_count",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return False
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["business_id = :bid"]
            params: Dict[str, Any] = {"bid": business_id, "ua": int(time.time())}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            set_parts = []
            for k, v in updates.items():
                ph = f"_{k}"
                if k in ("tags", "photos"):
                    # JSON 字段：list → JSON 字符串
                    if isinstance(v, (list, dict)):
                        v = json.dumps(v, ensure_ascii=False)
                set_parts.append(f"{k} = :{ph}")
                params[ph] = v
            set_parts.append("updated_at = :ua")
            sql = (
                "UPDATE local_business SET " + ", ".join(set_parts)
                + " WHERE " + " AND ".join(conditions)
            )
            async with engine.begin() as conn:
                res = await conn.execute(sql_text(sql), params)
                return res.rowcount > 0
        except Exception as e:
            logger.error(f"[local_life] update_business failed: {e}")
            return False

    async def delete_business(
        self, business_id: str, owner_user_id: str = "", is_admin: bool = False
    ) -> bool:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["business_id = :bid"]
            params = {"bid": business_id}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            async with engine.begin() as conn:
                res = await conn.execute(
                    sql_text(
                        "DELETE FROM local_business WHERE " + " AND ".join(conditions)
                    ),
                    params,
                )
                return res.rowcount > 0
        except Exception as e:
            logger.error(f"[local_life] delete_business failed: {e}")
            return False

    # ==================== 导出 ====================

    async def export_businesses(
        self, *, owner_user_id: str = "", is_admin: bool = False, **filters
    ) -> bytes:
        """导出全部（不限分页）为 xlsx，返回 bytes"""
        # 拉全部数据（page_size 放大）
        all_filters = dict(filters)
        result = await self.list_businesses(
            owner_user_id=owner_user_id, is_admin=is_admin,
            page=1, page_size=10000, **all_filters,
        )
        items = result.get("items", [])
        try:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = "本地商家"
            headers = [
                "名称", "电话", "地址", "省", "市", "区",
                "营业时间", "评分", "评分人数", "品类",
                "人均消费(分)", "经度", "纬度", "来源", "创建时间",
            ]
            ws.append(headers)
            for it in items:
                ws.append([
                    it.get("name", ""),
                    it.get("phone", ""),
                    it.get("address", ""),
                    it.get("province", ""),
                    it.get("city", ""),
                    it.get("district", ""),
                    it.get("business_hours", ""),
                    it.get("rating", 0),
                    it.get("rating_count", 0),
                    it.get("category", ""),
                    it.get("price_avg", 0),
                    it.get("longitude", 0),
                    it.get("latitude", 0),
                    it.get("source", ""),
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(it["created_at"]))
                    if it.get("created_at") else "",
                ])
            # 列宽自适应
            for col in ws.columns:
                max_len = 0
                col_letter = col[0].column_letter
                for cell in col:
                    v = str(cell.value or "")
                    if len(v) > max_len:
                        max_len = len(v)
                ws.column_dimensions[col_letter].width = min(60, max(12, max_len + 2))

            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()
        except Exception as e:
            logger.error(f"[local_life] export failed: {e}")
            return b""

    # ==================== 聚合：城市 / 品类 ====================

    async def list_cities(self, owner_user_id: str = "", is_admin: bool = False) -> List[Dict]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["city <> ''"]
            params: Dict[str, Any] = {}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            where = " WHERE " + " AND ".join(conditions)
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT city, COUNT(*) AS cnt FROM local_business{where} "
                        f"GROUP BY city ORDER BY cnt DESC"
                    ),
                    params,
                )
                return [{"city": r[0], "count": int(r[1])} for r in rows.fetchall()]
        except Exception as e:
            logger.error(f"[local_life] list_cities failed: {e}")
            return []

    async def list_categories(self, owner_user_id: str = "", is_admin: bool = False) -> List[Dict]:
        await self.ensure_table()
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            conditions = ["category <> ''"]
            params: Dict[str, Any] = {}
            if not is_admin and owner_user_id:
                conditions.append("owner_user_id = :ouid")
                params["ouid"] = owner_user_id
            where = " WHERE " + " AND ".join(conditions)
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT category, COUNT(*) AS cnt FROM local_business{where} "
                        f"GROUP BY category ORDER BY cnt DESC"
                    ),
                    params,
                )
                return [{"category": r[0], "count": int(r[1])} for r in rows.fetchall()]
        except Exception as e:
            logger.error(f"[local_life] list_categories failed: {e}")
            return []

    # ==================== 配置检查 ====================

    def is_amap_configured(self) -> bool:
        return get_amap_client().is_configured()

    # ==================== 字段映射 / 内部辅助 ====================

    def _map_amap_to_poi(self, poi: Dict) -> Dict:
        """高德 POI 字段映射为统一结构"""
        # location = "lng,lat"
        location = poi.get("location", "") or ""
        lng, lat = 0.0, 0.0
        if location and "," in location:
            parts = location.split(",")
            try:
                lng = float(parts[0])
                lat = float(parts[1])
            except Exception:
                pass

        # business 字段（嵌套）
        biz = poi.get("business") or {}
        opentime = biz.get("opentime_today") or biz.get("opentime_week") or ""
        rating_str = biz.get("rating") or ""
        try:
            rating = float(rating_str) if rating_str else 0.0
        except Exception:
            rating = 0.0

        photos = poi.get("photos") or []
        photo_urls = []
        if isinstance(photos, list):
            for p in photos[:5]:
                if isinstance(p, dict) and p.get("url"):
                    photo_urls.append(p["url"])
                elif isinstance(p, str):
                    photo_urls.append(p)

        # 区县 / 市 / 省（高德 pname / cityname / adname）
        return {
            "poi_id": poi.get("id", "") or "",
            "name": poi.get("name", "") or "",
            "phone": poi.get("tel", "") or "",
            "address": poi.get("address", "") or "",
            "province": poi.get("pname", "") or "",
            "city": poi.get("cityname", "") or "",
            "district": poi.get("adname", "") or "",
            "business_hours": opentime,
            "latitude": lat,
            "longitude": lng,
            "rating": rating,
            "category": poi.get("type", "") or "",
            "typecode": poi.get("typecode", "") or "",
            "photos": photo_urls,
            "extra": poi,
        }

    async def _upsert_business(
        self, *, poi_data: Dict, platform: str, owner_user_id: str
    ) -> Dict:
        """upsert 到 local_business 表"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            poi_id = poi_data.get("poi_id") or poi_data.get("id") or ""
            if not poi_id:
                return {"saved": False, "reason": "缺少 poi_id"}
            business_id = f"lb_{uuid.uuid4().hex[:12]}"
            now = int(time.time())
            photos = poi_data.get("photos") or []
            tags = poi_data.get("tags") or []
            extra = poi_data.get("extra") or {}
            async with engine.begin() as conn:
                # ON CONFLICT (platform, platform_poi_id, owner_user_id) DO UPDATE
                await conn.execute(
                    sql_text(
                        "INSERT INTO local_business "
                        "(business_id, name, phone, address, province, city, district, "
                        " business_hours, latitude, longitude, platform, platform_poi_id, "
                        " rating, rating_count, category, tags, photos, price_avg, source, "
                        " extra, owner_user_id, created_at, updated_at) "
                        "VALUES (:bid, :name, :phone, :addr, :prov, :city, :dist, "
                        " :hours, :lat, :lng, :pf, :poid, :rating, :rc, :cat, :tags, "
                        " :photos, :pa, :src, :extra, :ouid, :ca, :ua) "
                        "ON CONFLICT (platform, platform_poi_id, owner_user_id) DO UPDATE SET "
                        " name = EXCLUDED.name, phone = EXCLUDED.phone, "
                        " address = EXCLUDED.address, business_hours = EXCLUDED.business_hours, "
                        " rating = EXCLUDED.rating, category = EXCLUDED.category, "
                        " photos = EXCLUDED.photos, extra = EXCLUDED.extra, "
                        " updated_at = EXCLUDED.updated_at"
                    ),
                    {
                        "bid": business_id,
                        "name": poi_data.get("name", "")[:255],
                        "phone": poi_data.get("phone", ""),
                        "addr": poi_data.get("address", ""),
                        "prov": poi_data.get("province", ""),
                        "city": poi_data.get("city", ""),
                        "dist": poi_data.get("district", ""),
                        "hours": poi_data.get("business_hours", ""),
                        "lat": float(poi_data.get("latitude") or 0),
                        "lng": float(poi_data.get("longitude") or 0),
                        "pf": platform,
                        "poid": poi_id,
                        "rating": float(poi_data.get("rating") or 0),
                        "rc": int(poi_data.get("rating_count") or 0),
                        "cat": (poi_data.get("category") or "")[:255],
                        "tags": json.dumps(tags, ensure_ascii=False) if tags else "[]",
                        "photos": json.dumps(photos, ensure_ascii=False) if photos else "[]",
                        "pa": int(poi_data.get("price_avg") or 0),
                        "src": platform,
                        "extra": json.dumps(extra, ensure_ascii=False),
                        "ouid": owner_user_id,
                        "ca": now,
                        "ua": now,
                    },
                )
            return {"saved": True, "poi_id": poi_id, "platform": platform}
        except Exception as e:
            logger.error(f"[local_life] _upsert_business failed: {e}")
            return {"saved": False, "reason": str(e)}

    @staticmethod
    def _row_to_biz_dict(r) -> Dict:
        if r is None:
            return {}
        try:
            tags = json.loads(r[15]) if r[15] else []
        except Exception:
            tags = []
        try:
            photos = json.loads(r[16]) if r[16] else []
        except Exception:
            photos = []
        return {
            "business_id": r[0], "name": r[1], "phone": r[2], "address": r[3],
            "province": r[4], "city": r[5], "district": r[6],
            "business_hours": r[7], "latitude": float(r[8] or 0),
            "longitude": float(r[9] or 0), "platform": r[10],
            "platform_poi_id": r[11], "rating": float(r[12] or 0),
            "rating_count": int(r[13] or 0), "category": r[14],
            "tags": tags, "photos": photos, "price_avg": int(r[17] or 0),
            "source": r[18], "owner_user_id": r[19],
            "created_at": r[20], "updated_at": r[21],
        }


# ============ 单例 ============
_local_life_service: Optional[LocalLifeService] = None


def get_local_life_service() -> LocalLifeService:
    global _local_life_service
    if _local_life_service is None:
        _local_life_service = LocalLifeService()
    return _local_life_service
