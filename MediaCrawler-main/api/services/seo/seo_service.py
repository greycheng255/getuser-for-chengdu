# -*- coding: utf-8 -*-
"""
SEO 品牌推广服务

核心职责：
1. 品牌创建与管理（品牌信息 + Logo）
2. AI 生成行业优势文章
3. 多平台内容投放（抖音/快手/小红书/头条/百家号/知乎）
4. 官媒投稿
5. 搜索效果追踪

参考：知了系统的 SEO 优化与品牌推广功能
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SEO_PLATFORMS = ["douyin", "kuaishou", "xiaohongshu", "toutiao", "baijiahao", "zhihu"]


class SEOService:
    """SEO 品牌推广服务（单例）"""

    _ensured = False
    _instance = None

    def __init__(self):
        self._brands: Dict[str, Dict] = {}

    @classmethod
    def get_instance(cls) -> "SEOService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """创建 seo_brand / seo_article 表"""
        if SEOService._ensured:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS seo_brand ("
                        "  id SERIAL PRIMARY KEY,"
                        "  brand_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  brand_name VARCHAR(255) NOT NULL,"
                        "  company_name VARCHAR(255) DEFAULT '',"
                        "  logo_url VARCHAR(500) DEFAULT '',"
                        "  industry VARCHAR(100) DEFAULT '',"
                        "  brand_intro TEXT DEFAULT '',"
                        "  advantages TEXT DEFAULT '[]',"
                        "  status VARCHAR(20) DEFAULT 'active',"
                        "  owner_user_id VARCHAR(64) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS seo_article ("
                        "  id SERIAL PRIMARY KEY,"
                        "  article_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  brand_id VARCHAR(64) NOT NULL,"
                        "  title VARCHAR(500) NOT NULL,"
                        "  content TEXT NOT NULL,"
                        "  keywords TEXT DEFAULT '[]',"
                        "  target_platforms TEXT DEFAULT '[]',"
                        "  published_platforms TEXT DEFAULT '[]',"
                        "  status VARCHAR(20) DEFAULT 'draft',"
                        "  owner_user_id VARCHAR(64) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_seo_article_brand "
                        "ON seo_article(brand_id, status)"
                    )
                )

            SEOService._ensured = True
            logger.info("[SEO] 表创建完成")
        except Exception as e:
            logger.warning(f"[SEO] 建表失败(非致命): {e}")

    async def create_brand(
        self,
        brand_name: str,
        company_name: str = "",
        logo_url: str = "",
        industry: str = "",
        brand_intro: str = "",
        advantages: Optional[List[str]] = None,
        owner_user_id: str = "",
    ) -> Dict[str, Any]:
        """创建品牌"""
        brand_id = f"brand_{uuid.uuid4().hex[:10]}"
        now = int(time.time())

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO seo_brand "
                        "(brand_id, brand_name, company_name, logo_url, industry, brand_intro, "
                        "advantages, status, owner_user_id, created_at, updated_at) "
                        "VALUES (:bid, :bname, :cname, :logo, :ind, :intro, :adv, 'active', :owner, :now, :now)"
                    ),
                    {
                        "bid": brand_id,
                        "bname": brand_name,
                        "cname": company_name,
                        "logo": logo_url,
                        "ind": industry,
                        "intro": brand_intro,
                        "adv": json.dumps(advantages or [], ensure_ascii=False),
                        "owner": owner_user_id,
                        "now": now,
                    },
                )

            brand_data = {
                "brand_id": brand_id,
                "brand_name": brand_name,
                "company_name": company_name,
                "logo_url": logo_url,
                "industry": industry,
                "brand_intro": brand_intro,
                "advantages": advantages or [],
            }
            self._brands[brand_id] = brand_data

            logger.info(f"[SEO] 品牌创建: {brand_id} ({brand_name})")
            return {"ok": True, "brand_id": brand_id, "brand": brand_data}
        except Exception as e:
            logger.warning(f"[SEO] 创建品牌失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def generate_article(
        self,
        brand_id: str,
        topic: str,
        target_platforms: Optional[List[str]] = None,
        owner_user_id: str = "",
    ) -> Dict[str, Any]:
        """AI 生成 SEO 文章"""
        brand = self._brands.get(brand_id)
        if not brand:
            # 从数据库加载
            try:
                from sqlalchemy import text as sql_text

                engine = self._get_engine()
                async with engine.connect() as conn:
                    row = await conn.execute(
                        sql_text("SELECT * FROM seo_brand WHERE brand_id = :bid"),
                        {"bid": brand_id},
                    )
                    result = row.fetchone()
                    if result:
                        brand = dict(result._mapping)
            except Exception:
                pass

        if not brand:
            return {"ok": False, "reason": "品牌不存在"}

        try:
            from api.services.ai_agent_client import get_ai_agent_client
            client = get_ai_agent_client()

            brand_name = brand.get("brand_name", "") if isinstance(brand, dict) else brand.brand_name
            industry = brand.get("industry", "") if isinstance(brand, dict) else brand.industry
            advantages = brand.get("advantages", "[]") if isinstance(brand, dict) else brand.advantages
            if isinstance(advantages, str):
                advantages = json.loads(advantages)

            prompt = f"""为品牌「{brand_name}」生成一篇 SEO 优化文章。
行业：{industry}
主题：{topic}
品牌优势：{', '.join(advantages) if advantages else '暂无'}

要求：
1. 标题包含行业关键词，吸引搜索流量
2. 正文 800-1500 字，自然融入品牌名称 3-5 次
3. 突出品牌优势和专业性
4. 结尾引导咨询

按 JSON 格式返回：
{{
  "title": "文章标题",
  "content": "文章正文（Markdown 格式）",
  "keywords": ["关键词1", "关键词2", ...],
  "meta_description": "150字以内的摘要"
}}

只返回 JSON。"""

            response = await client.generate_text(prompt=prompt)
            if not response:
                return {"ok": False, "reason": "AI 生成文章失败"}

            import json as json_mod
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].strip()

            article_data = json_mod.loads(text)

            # 保存文章
            article_id = f"art_{uuid.uuid4().hex[:10]}"
            now = int(time.time())
            platforms = target_platforms or SEO_PLATFORMS

            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO seo_article "
                        "(article_id, brand_id, title, content, keywords, target_platforms, "
                        "status, owner_user_id, created_at, updated_at) "
                        "VALUES (:aid, :bid, :title, :content, :kw, :plats, 'draft', :owner, :now, :now)"
                    ),
                    {
                        "aid": article_id,
                        "bid": brand_id,
                        "title": article_data.get("title", ""),
                        "content": article_data.get("content", ""),
                        "kw": json_mod.dumps(article_data.get("keywords", []), ensure_ascii=False),
                        "plats": json_mod.dumps(platforms, ensure_ascii=False),
                        "owner": owner_user_id,
                        "now": now,
                    },
                )

            logger.info(f"[SEO] 文章生成: {article_id} ({article_data.get('title', '')[:30]}...)")
            return {
                "ok": True,
                "article_id": article_id,
                "article": article_data,
            }
        except Exception as e:
            logger.warning(f"[SEO] 生成文章失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def publish_article(
        self,
        article_id: str,
        platform: str,
    ) -> Dict[str, Any]:
        """发布文章到指定平台（模拟，实际需对接各平台 API）"""
        if platform not in SEO_PLATFORMS:
            return {"ok": False, "reason": f"不支持的平台: {platform}"}

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                row = await conn.execute(
                    sql_text("SELECT * FROM seo_article WHERE article_id = :aid"),
                    {"aid": article_id},
                )
                article = row.fetchone()
                if not article:
                    return {"ok": False, "reason": "文章不存在"}

                article_data = dict(article._mapping)
                published = json.loads(article_data.get("published_platforms", "[]"))
                if platform in published:
                    return {"ok": False, "reason": f"已在 {platform} 发布过"}

                published.append(platform)
                await conn.execute(
                    sql_text(
                        "UPDATE seo_article SET published_platforms = :plats, "
                        "status = 'published', updated_at = :now WHERE article_id = :aid"
                    ),
                    {
                        "plats": json.dumps(published, ensure_ascii=False),
                        "now": int(time.time()),
                        "aid": article_id,
                    },
                )

            logger.info(f"[SEO] 文章发布到 {platform}: {article_id}")
            return {"ok": True, "platform": platform}
        except Exception as e:
            logger.warning(f"[SEO] 发布失败: {e}")
            return {"ok": False, "reason": str(e)}

    async def list_brands(self, owner_user_id: str = "") -> List[Dict]:
        """列出品牌"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text("SELECT * FROM seo_brand WHERE status='active' ORDER BY created_at DESC"),
                )
            return [dict(r._mapping) for r in rows.fetchall()]
        except Exception:
            return []

    async def list_articles(
        self,
        brand_id: Optional[str] = None,
        status: str = "draft",
        limit: int = 20,
    ) -> List[Dict]:
        """列出文章"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return []

            where = "status = :status"
            params: Dict[str, Any] = {"status": status, "limit": limit}
            if brand_id:
                where += " AND brand_id = :bid"
                params["bid"] = brand_id

            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT * FROM seo_article WHERE {where} ORDER BY created_at DESC LIMIT :limit"
                    ),
                    params,
                )
            return [dict(r._mapping) for r in rows.fetchall()]
        except Exception:
            return []


def get_seo_service() -> SEOService:
    return SEOService.get_instance()
