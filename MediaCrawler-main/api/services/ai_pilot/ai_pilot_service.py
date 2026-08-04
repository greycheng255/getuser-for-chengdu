# -*- coding: utf-8 -*-
"""
AI 自动驾驶舱服务

核心职责：
1. 接收用户自然语言目标（如"帮我找50个客户并加到微信"）
2. 调用 AI 大脑拆解目标为可执行计划（行业特点/话题词/时间轴/平台选择）
3. 生成 acquisition_plan 表记录
4. 驱动各子模块执行（养号→找客→私信→互动）

参考：知了系统的 AI 自动驾驶舱设计
"""
import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# AI 拆解目标的 system prompt
PILOT_SYSTEM_PROMPT = """你是一个获客系统AI大脑。用户会输入一个获客目标，你需要将其拆解为可执行的获客计划。

请严格按 JSON 格式返回，包含以下字段：
{
  "industry": "行业名称（如企业服务/餐饮/教育）",
  "industry_features": ["行业特点1", "行业特点2", ...],
  "topic_keywords": ["话题词1", "话题词2", ...],
  "target_platforms": ["douyin", "xiaohongshu", "kuaishou", "video_number"],
  "daily_goal": {
    "target_customer_count": 50,
    "description": "今日目标描述"
  },
  "schedule": [
    {"time_start": "08:30", "time_end": "09:30", "task": "养号", "action": "刷行业相关视频提升权重"},
    {"time_start": "09:30", "time_end": "12:00", "task": "找客户", "action": "在同行热门视频下寻找意向评论"},
    {"time_start": "14:00", "time_end": "17:00", "task": "互动私信", "action": "使用配置好的专业话术与客户互动"},
    {"time_start": "17:00", "time_end": "18:00", "task": "复盘", "action": "查看今日数据并调整策略"}
  ],
  "keywords": ["搜索关键词1", "搜索关键词2", ...],
  "reply_scripts": ["私信话术1", "私信话术2", ...]
}

只返回 JSON，不要其他文字。"""


class AIPilotService:
    """AI 自动驾驶舱服务（单例）"""

    _ensured = False
    _instance = None

    def __init__(self):
        self._plans: Dict[str, Dict] = {}  # plan_id → plan data (内存缓存)
        self._plan_cache_ttl = 300  # 缓存有效期 5 分钟

    @classmethod
    def get_instance(cls) -> "AIPilotService":
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
        """创建 ai_pilot_plan 表"""
        if AIPilotService._ensured:
            return
        try:
            engine = self._get_engine()
            if engine is None:
                return
            from sqlalchemy import text as sql_text

            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS ai_pilot_plan ("
                        "  id SERIAL PRIMARY KEY,"
                        "  plan_id VARCHAR(64) UNIQUE NOT NULL,"
                        "  user_goal TEXT NOT NULL,"
                        "  industry VARCHAR(100) DEFAULT '',"
                        "  industry_features TEXT DEFAULT '[]',"
                        "  topic_keywords TEXT DEFAULT '[]',"
                        "  target_platforms TEXT DEFAULT '[]',"
                        "  target_customer_count INTEGER DEFAULT 0,"
                        "  goal_description TEXT DEFAULT '',"
                        "  schedule TEXT DEFAULT '[]',"
                        "  keywords TEXT DEFAULT '[]',"
                        "  reply_scripts TEXT DEFAULT '[]',"
                        "  status VARCHAR(20) DEFAULT 'draft',"
                        "  owner_user_id VARCHAR(64) DEFAULT '',"
                        "  created_at BIGINT DEFAULT 0,"
                        "  updated_at BIGINT DEFAULT 0"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_pilot_plan_owner "
                        "ON ai_pilot_plan(owner_user_id, status)"
                    )
                )
            AIPilotService._ensured = True
            logger.info("[AIPilot] 表 ai_pilot_plan 创建完成")
        except Exception as e:
            logger.warning(f"[AIPilot] 建表失败(非致命): {e}")

    async def generate_plan(
        self,
        user_goal: str,
        owner_user_id: str = "",
    ) -> Dict[str, Any]:
        """接收用户目标，调用 AI 拆解生成获客计划"""
        plan_id = f"pilot_{uuid.uuid4().hex[:12]}"
        now = int(time.time())

        # 调用 AI 拆解目标
        ai_result = await self._call_ai_to_decompose(user_goal)

        if not ai_result:
            return {
                "ok": False,
                "plan_id": plan_id,
                "reason": "AI 拆解失败，请检查 AI 服务是否可用",
            }

        # 持久化计划
        plan_data = {
            "plan_id": plan_id,
            "user_goal": user_goal,
            "industry": ai_result.get("industry", ""),
            "industry_features": json.dumps(ai_result.get("industry_features", []), ensure_ascii=False),
            "topic_keywords": json.dumps(ai_result.get("topic_keywords", []), ensure_ascii=False),
            "target_platforms": json.dumps(ai_result.get("target_platforms", []), ensure_ascii=False),
            "target_customer_count": ai_result.get("daily_goal", {}).get("target_customer_count", 0),
            "goal_description": ai_result.get("daily_goal", {}).get("description", ""),
            "schedule": json.dumps(ai_result.get("schedule", []), ensure_ascii=False),
            "keywords": json.dumps(ai_result.get("keywords", []), ensure_ascii=False),
            "reply_scripts": json.dumps(ai_result.get("reply_scripts", []), ensure_ascii=False),
            "status": "active",
            "owner_user_id": owner_user_id,
            "created_at": now,
            "updated_at": now,
        }

        await self._save_plan(plan_data)
        self._plans[plan_id] = plan_data

        logger.info(f"[AIPilot] 计划生成成功: {plan_id} (目标: {user_goal[:50]}...)")

        return {
            "ok": True,
            "plan_id": plan_id,
            "plan": ai_result,
        }

    async def _call_ai_to_decompose(self, user_goal: str) -> Optional[Dict]:
        """调用 AI 拆解用户目标"""
        try:
            from api.services.ai_agent_client import get_ai_agent_client
            client = get_ai_agent_client()

            prompt = f"用户获客目标：{user_goal}\n\n请拆解为可执行计划。"
            response = await client.generate_text(
                prompt=prompt,
                system_prompt=PILOT_SYSTEM_PROMPT,
            )

            if not response:
                return None

            # 解析 AI 返回的 JSON（增强鲁棒性：处理 markdown 代码块）
            text = response.strip()
            # 移除 markdown 代码块标记
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

            result = json.loads(text)
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"[AIPilot] AI 返回 JSON 解析失败: {e}, raw={response[:200] if response else 'None'}")
            return None
        except Exception as e:
            logger.warning(f"[AIPilot] AI 拆解失败: {e}")
            return None

    async def _save_plan(self, plan_data: Dict) -> None:
        """保存计划到数据库"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO ai_pilot_plan "
                        "(plan_id, user_goal, industry, industry_features, topic_keywords, "
                        "target_platforms, target_customer_count, goal_description, "
                        "schedule, keywords, reply_scripts, status, owner_user_id, "
                        "created_at, updated_at) "
                        "VALUES (:plan_id, :user_goal, :industry, :industry_features, :topic_keywords, "
                        ":target_platforms, :target_customer_count, :goal_description, "
                        ":schedule, :keywords, :reply_scripts, :status, :owner_user_id, "
                        ":created_at, :updated_at)"
                    ),
                    plan_data,
                )
        except Exception as e:
            logger.warning(f"[AIPilot] 保存计划失败: {e}")

    async def list_plans(
        self,
        owner_user_id: str = "",
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """列出计划"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return {"plans": [], "total": 0}

            conditions = []
            params: Dict[str, Any] = {}

            if owner_user_id:
                conditions.append("owner_user_id = :owner")
                params["owner"] = owner_user_id
            if status:
                conditions.append("status = :status")
                params["status"] = status

            where = " AND ".join(conditions) if conditions else "1=1"
            params["limit"] = page_size
            params["offset"] = (page - 1) * page_size

            # 只读查询用 connect() 而非 begin()
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        f"SELECT * FROM ai_pilot_plan WHERE {where} "
                        "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                    ),
                    params,
                )
                total = await conn.execute(
                    sql_text(
                        f"SELECT count(*) FROM ai_pilot_plan WHERE {where}"
                    ),
                    {k: v for k, v in params.items() if k not in ("limit", "offset")},
                )

            plans = [dict(row._mapping) for row in rows.fetchall()]
            return {"plans": plans, "total": total.scalar()}
        except Exception as e:
            logger.warning(f"[AIPilot] 列出计划失败: {e}")
            return {"plans": [], "total": 0}

    async def get_plan(self, plan_id: str) -> Optional[Dict]:
        """获取单个计划（带内存缓存）"""
        # 先查内存缓存
        if plan_id in self._plans:
            return self._plans[plan_id]

        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return None
            # 只读查询用 connect()
            async with engine.connect() as conn:
                row = await conn.execute(
                    sql_text("SELECT * FROM ai_pilot_plan WHERE plan_id = :pid"),
                    {"pid": plan_id},
                )
                result = row.fetchone()
                if result:
                    plan_dict = dict(result._mapping)
                    # 写入缓存
                    self._plans[plan_id] = plan_dict
                    return plan_dict
                return None
        except Exception as e:
            logger.warning(f"[AIPilot] 获取计划失败: {e}")
            return None

    async def update_plan_status(self, plan_id: str, status: str) -> bool:
        """更新计划状态"""
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "UPDATE ai_pilot_plan SET status = :status, updated_at = :now "
                        "WHERE plan_id = :pid"
                    ),
                    {"status": status, "now": int(time.time()), "pid": plan_id},
                )
            # 更新缓存
            if plan_id in self._plans:
                self._plans[plan_id]["status"] = status
            return True
        except Exception as e:
            logger.warning(f"[AIPilot] 更新状态失败: {e}")
            return False

    async def execute_plan(self, plan_id: str) -> Dict[str, Any]:
        """执行计划：将计划拆解为各子模块任务"""
        plan = await self.get_plan(plan_id)
        if not plan:
            return {"ok": False, "reason": "计划不存在"}

        schedule = json.loads(plan.get("schedule", "[]"))
        keywords = json.loads(plan.get("keywords", "[]"))
        platforms = json.loads(plan.get("target_platforms", "[]"))

        tasks_created = []

        # 为每个 schedule 项创建 comment_monitor 任务
        for item in schedule:
            task_type = item.get("task", "")
            if task_type in ("找客户", "互动私信"):
                # 创建评论监控任务
                for platform in platforms:
                    tasks_created.append({
                        "plan_id": plan_id,
                        "schedule_item": item,
                        "platform": platform,
                        "keywords": keywords,
                    })

        await self.update_plan_status(plan_id, "running")
        logger.info(f"[AIPilot] 计划 {plan_id} 开始执行，创建 {len(tasks_created)} 个子任务")

        return {
            "ok": True,
            "plan_id": plan_id,
            "sub_tasks": tasks_created,
        }


def get_ai_pilot_service() -> AIPilotService:
    return AIPilotService.get_instance()
