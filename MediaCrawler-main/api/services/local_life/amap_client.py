# -*- coding: utf-8 -*-
"""
高德地图 API 客户端

接口：
- /place/text/v5  关键词 POI 搜索（返回名称/电话/地址/营业时间/经纬度/评分）
- /place/detail/v5 POI 详情
- /geocode/geo    地理编码

Key 从环境变量 AMAP_API_KEY 读取。
使用 httpx.AsyncClient(timeout=15.0) 异步调用。
"""
import asyncio
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AmapClient:
    """高德地图 Web 服务客户端"""

    BASE_URL_V5 = "https://restapi.amap.com/v5"
    BASE_URL_V3 = "https://restapi.amap.com/v3"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key or os.getenv("AMAP_API_KEY", "")).strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _http_get(self, url: str, params: Dict[str, Any]) -> Dict:
        """异步 GET 请求（用 httpx，避免阻塞事件循环）"""
        try:
            import httpx
        except ImportError:
            # httpx 不可用时退化为同步 requests + asyncio.to_thread
            return await self._http_get_via_requests(url, params)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning(f"[AmapClient] httpx 请求失败: {e}")
            return {"status": "1", "info": f"http_error: {e}", "pois": []}

    async def _http_get_via_requests(self, url: str, params: Dict[str, Any]) -> Dict:
        """兜底：用 requests + asyncio.to_thread（避免阻塞事件循环）"""
        import requests

        def _do():
            try:
                r = requests.get(url, params=params, timeout=15)
                return r.json()
            except Exception as e:
                return {"status": "1", "info": f"http_error: {e}", "pois": []}

        return await asyncio.to_thread(_do)

    async def search_poi(
        self,
        keyword: str,
        city: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        types: Optional[str] = None,
    ) -> Dict:
        """关键词 POI 搜索（v5）

        Args:
            keyword: 关键词，如 "火锅"
            city: 城市名（可选），如 "成都"
            page: 页码（从 1 开始）
            page_size: 每页数量（最大 25）
            types: POI 类型码（可选，如 050000 餐饮服务）

        Returns:
            高德 v5 接口原始响应（含 pois 列表）
        """
        if not self.is_configured():
            return {"status": "0", "info": "未配置 AMAP_API_KEY", "pois": []}
        params: Dict[str, Any] = {
            "key": self.api_key,
            "keywords": keyword,
            "page_size": min(25, max(1, page_size)),
            "page": max(1, page),
            "show_fields": "business,photos,children,indoor,navi",
        }
        if city:
            params["city"] = city
        if types:
            params["types"] = types
        return await self._http_get(f"{self.BASE_URL_V5}/place/text", params)

    async def get_poi_detail(self, poi_id: str) -> Dict:
        """获取 POI 详情（v5）"""
        if not self.is_configured():
            return {"status": "0", "info": "未配置 AMAP_API_KEY"}
        params = {
            "key": self.api_key,
            "id": poi_id,
            "show_fields": "business,photos,children,indoor,navi",
        }
        return await self._http_get(f"{self.BASE_URL_V5}/place/detail", params)

    async def geocode(self, address: str, city: Optional[str] = None) -> Dict:
        """地理编码（v3）"""
        if not self.is_configured():
            return {"status": "0", "info": "未配置 AMAP_API_KEY"}
        params = {"key": self.api_key, "address": address}
        if city:
            params["city"] = city
        return await self._http_get(f"{self.BASE_URL_V3}/geocode/geo", params)


# ============ 单例 ============
_amap_client: Optional[AmapClient] = None


def get_amap_client() -> AmapClient:
    global _amap_client
    if _amap_client is None:
        _amap_client = AmapClient()
    return _amap_client
