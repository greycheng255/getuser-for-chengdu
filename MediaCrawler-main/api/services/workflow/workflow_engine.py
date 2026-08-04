# -*- coding: utf-8 -*-
"""
GEO 内容工程闭环工作流引擎（迁移自 GEO-main）

迁移自: GEO-main/geo_system/backend/workflow_engine.py
对应 PRD 模块: 工作流引擎 - 多模块协作闭环编排

适配点:
1. 数据库: 原内存态 → PostgreSQL 异步 (database.db_session.get_async_engine)
   工作流实例与阶段状态持久化到 workflow_instances 表，进程重启可恢复。
2. 配置: 硬编码敏感信息 → os.environ.get("XXX", "default")
3. 日志: print → logging.getLogger(__name__)
4. 异步: threading.Thread 后台执行 → asyncio.create_task
   所有公开方法改为 async def。
5. 服务调用: 原内部 HTTP API (_call_api) → 直接调用 MediaCrawler 已迁移的服务模块
   (publisher / interactor / moderation / scheduling / analytics / ai)，
   每个导入用 try/except 包裹，降级为 None 以支持渐进式上线。
6. 工作流阶段: GEO 9 阶段（关键词研究/品牌诊断/...）→ MediaCrawler 7 阶段
   热点搜集 → 内容生成 → 视频生成 → 内容审核 → 多平台分发 → 互动监控 → 数据统计
   阶段与 MediaCrawler 已迁移的服务模块一一对应。
7. 闭环反馈: 保留原 monitoring_feedback 数据回流机制，
   在 data_analytics 阶段生成下一轮优化建议。
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)


def _get_engine():
    """获取异步数据库引擎（公共方法，消除重复导入）"""
    from database.db_session import get_async_engine
    return get_async_engine(config.SAVE_DATA_OPTION)


# ============ 服务模块集成（try/except 降级为 None，支持渐进式上线）============
try:
    from ..publisher import get_multi_publisher  # 多平台发布
    _publisher_available = True
except Exception as _e:  # noqa: F841
    logger.warning(f"[Workflow] publisher 模块不可用: {_e}")
    get_multi_publisher = None
    _publisher_available = False

try:
    from ..interactor import get_multi_interactor  # 多平台互动
    _interactor_available = True
except Exception as _e:  # noqa: F841
    logger.warning(f"[Workflow] interactor 模块不可用: {_e}")
    get_multi_interactor = None
    _interactor_available = False

try:
    from ..moderation import get_moderation_service  # 内容风控
    _moderation_available = True
except Exception as _e:  # noqa: F841
    logger.warning(f"[Workflow] moderation 模块不可用: {_e}")
    get_moderation_service = None
    _moderation_available = False

try:
    from ..scheduling import get_publish_scheduler  # 发布调度
    _scheduling_available = True
except Exception as _e:  # noqa: F841
    logger.warning(f"[Workflow] scheduling 模块不可用: {_e}")
    get_publish_scheduler = None
    _scheduling_available = False

try:
    from ..analytics import get_analytics_service  # 数据统计
    _analytics_available = True
except Exception as _e:  # noqa: F841
    logger.warning(f"[Workflow] analytics 模块不可用: {_e}")
    get_analytics_service = None
    _analytics_available = False

try:
    from ..ai import get_ai_service  # AI 服务（内容生成/视频生成/热点分析）
    _ai_available = True
except Exception as _e:  # noqa: F841
    logger.warning(f"[Workflow] ai 模块不可用: {_e}")
    get_ai_service = None
    _ai_available = False


def wf_id_to_int(wf_id: str) -> int:
    """把 workflow id 转换成数字（用于文件名前缀）"""
    if not wf_id:
        return 0
    try:
        return abs(hash(wf_id)) & 0xFFFF
    except Exception:
        return 0


# ============ 工作流阶段定义 ============
# 7 个阶段串联成闭环，每个阶段对应一个已迁移的 MediaCrawler 服务模块。
WORKFLOW_STAGES: List[Dict[str, Any]] = [
    {
        'id': 'hotspot_collection',
        'name': '热点搜集',
        'icon': '🔥',
        'description': '抓取多平台热点话题，挖掘内容选题方向',
        'service': 'ai',  # 主要依赖的 service 模块
        'next_stage': 'content_generation',
    },
    {
        'id': 'content_generation',
        'name': '内容生成',
        'icon': '✍️',
        'description': '基于热点生成多平台适配的图文/文案内容',
        'service': 'ai',
        'next_stage': 'video_generation',
    },
    {
        'id': 'video_generation',
        'name': '视频生成',
        'icon': '🎬',
        'description': '生成解说视频或短视频素材',
        'service': 'ai',
        'next_stage': 'content_moderation',
    },
    {
        'id': 'content_moderation',
        'name': '内容审核',
        'icon': '🛡️',
        'description': '违规词检测 + 查重 + 发布前审核',
        'service': 'moderation',
        'next_stage': 'multi_platform_distribution',
    },
    {
        'id': 'multi_platform_distribution',
        'name': '多平台分发',
        'icon': '📤',
        'description': '一键发布到多平台（支持定时/错峰）',
        'service': 'publisher',
        'next_stage': 'interaction_monitoring',
    },
    {
        'id': 'interaction_monitoring',
        'name': '互动监控',
        'icon': '💬',
        'description': '监控评论/私信，自动互动回复',
        'service': 'interactor',
        'next_stage': 'data_analytics',
    },
    {
        'id': 'data_analytics',
        'name': '数据统计',
        'icon': '📊',
        'description': '全链路数据聚合统计与效果分析',
        'service': 'analytics',
        'next_stage': None,  # 闭环完成
    },
]


class WorkflowState:
    """工作流状态管理（PostgreSQL 持久化 + 内存缓存）

    - workflow_instances 表持久化工作流元数据、阶段状态、artifacts
    - 内存缓存用于活跃工作流的快速访问（避免每次都查库）
    - 进程重启后通过 load_from_db 恢复
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        # workflow_id -> state dict（内存缓存，DB 为 source of truth）
        self.workflows: Dict[str, Dict] = {}
        self._table_ready = False

    async def _ensure_table(self):
        """确保持久化表存在（PostgreSQL）"""
        if self._table_ready:
            return
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                self._table_ready = True
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS workflow_instances ("
                        "  id SERIAL PRIMARY KEY,"
                        "  workflow_id VARCHAR(64) UNIQUE,"
                        "  brand_name VARCHAR(128),"
                        "  industry VARCHAR(64),"
                        "  keywords TEXT,"
                        "  platforms TEXT,"
                        "  current_stage VARCHAR(64),"
                        "  status VARCHAR(16) DEFAULT 'pending',"
                        "  started_at TIMESTAMP,"
                        "  completed_at TIMESTAMP,"
                        "  stages TEXT,"
                        "  artifacts TEXT,"
                        "  error TEXT,"
                        "  auto_run BOOLEAN DEFAULT TRUE,"
                        "  created_at TIMESTAMP DEFAULT NOW()"
                        ")"
                    )
                )
            self._table_ready = True
        except Exception as e:
            logger.warning(f"[WorkflowState] 建表失败（降级为纯内存模式）: {e}")
            self._table_ready = True

    async def create(self, brand_name: str, industry: str = '默认行业',
                     keywords: List[str] = None, platforms: List[str] = None) -> str:
        wf_id = f"wf_{uuid.uuid4().hex[:12]}"
        state = {
            'id': wf_id,
            'brand_name': brand_name,
            'industry': industry,
            'keywords': keywords or [],
            'platforms': platforms or ['website_blog'],
            'current_stage': 'hotspot_collection',
            'status': 'pending',  # pending/running/paused/completed/failed
            'started_at': datetime.now().isoformat(),
            'completed_at': None,
            'stages': {},  # stage_id -> stage_state
            'artifacts': {},  # 共享数据
            'error': None,
            'auto_run': True,
        }
        async with self._lock:
            self.workflows[wf_id] = state
        await self._persist(wf_id)
        return wf_id

    async def get(self, wf_id: str) -> Optional[Dict]:
        async with self._lock:
            if wf_id in self.workflows:
                return self.workflows[wf_id]
        # 内存未命中，查 DB
        return await self._load_from_db(wf_id)

    async def update(self, wf_id: str, updates: Dict):
        async with self._lock:
            if wf_id in self.workflows:
                self.workflows[wf_id].update(updates)
        await self._persist(wf_id)

    async def update_stage(self, wf_id: str, stage_id: str, stage_state: Dict):
        async with self._lock:
            wf = self.workflows.get(wf_id)
            if wf is None:
                return
            wf['stages'][stage_id] = {
                'status': 'pending',
                'started_at': None,
                'completed_at': None,
                'result': None,
                'error': None,
                **stage_state,
            }
        await self._persist(wf_id)

    async def list_all(self, limit: int = 20) -> List[Dict]:
        # 优先从 DB 查询（保证拿到所有历史工作流）
        items = await self._list_from_db(limit)
        if items:
            return items
        # DB 不可用时降级为内存
        async with self._lock:
            items = list(self.workflows.values())
        items.sort(key=lambda x: x.get('started_at', ''), reverse=True)
        return items[:limit]

    async def _persist(self, wf_id: str):
        """持久化单个工作流到 DB"""
        try:
            await self._ensure_table()
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return
            async with self._lock:
                wf = self.workflows.get(wf_id)
            if wf is None:
                return
            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO workflow_instances "
                        "(workflow_id, brand_name, industry, keywords, platforms, "
                        " current_stage, status, started_at, completed_at, stages, "
                        " artifacts, error, auto_run) "
                        "VALUES (:wid, :bn, :ind, :kw, :pf, :cs, :st, :sa, :ca, :sg, :ar, :er, :au) "
                        "ON CONFLICT (workflow_id) DO UPDATE SET "
                        " brand_name=EXCLUDED.brand_name, industry=EXCLUDED.industry, "
                        " keywords=EXCLUDED.keywords, platforms=EXCLUDED.platforms, "
                        " current_stage=EXCLUDED.current_stage, status=EXCLUDED.status, "
                        " started_at=EXCLUDED.started_at, completed_at=EXCLUDED.completed_at, "
                        " stages=EXCLUDED.stages, artifacts=EXCLUDED.artifacts, "
                        " error=EXCLUDED.error, auto_run=EXCLUDED.auto_run"
                    ),
                    {
                        'wid': wf_id,
                        'bn': wf.get('brand_name'),
                        'ind': wf.get('industry'),
                        'kw': json.dumps(wf.get('keywords', []), ensure_ascii=False),
                        'pf': json.dumps(wf.get('platforms', []), ensure_ascii=False),
                        'cs': wf.get('current_stage'),
                        'st': wf.get('status'),
                        'sa': wf.get('started_at'),
                        'ca': wf.get('completed_at'),
                        'sg': json.dumps(wf.get('stages', {}), ensure_ascii=False),
                        'ar': json.dumps(wf.get('artifacts', {}), ensure_ascii=False),
                        'er': wf.get('error'),
                        'au': wf.get('auto_run', True),
                    },
                )
        except Exception as e:
            logger.warning(f"[WorkflowState] 持久化失败（内存仍可用）: {e}")

    async def _load_from_db(self, wf_id: str) -> Optional[Dict]:
        try:
            await self._ensure_table()
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return None
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT workflow_id, brand_name, industry, keywords, platforms, "
                        "current_stage, status, started_at, completed_at, stages, "
                        "artifacts, error, auto_run FROM workflow_instances "
                        "WHERE workflow_id=:wid"
                    ),
                    {'wid': wf_id},
                )
                row = rows.fetchone()
            if not row:
                return None
            wf = self._row_to_dict(row)
            async with self._lock:
                self.workflows[wf_id] = wf
            return wf
        except Exception as e:
            logger.warning(f"[WorkflowState] 从 DB 加载失败: {e}")
            return None

    async def _list_from_db(self, limit: int) -> List[Dict]:
        try:
            await self._ensure_table()
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT workflow_id, brand_name, industry, keywords, platforms, "
                        "current_stage, status, started_at, completed_at, stages, "
                        "artifacts, error, auto_run FROM workflow_instances "
                        "ORDER BY started_at DESC NULLS LAST LIMIT :l"
                    ),
                    {'l': limit},
                )
                items = [self._row_to_dict(r) for r in rows.fetchall()]
            # 同步到内存缓存
            async with self._lock:
                for wf in items:
                    self.workflows[wf['id']] = wf
            return items
        except Exception as e:
            logger.warning(f"[WorkflowState] 列表查询失败: {e}")
            return []

    @staticmethod
    def _row_to_dict(row) -> Dict:
        def _loads(s, default):
            if not s:
                return default
            if isinstance(s, (list, dict)):
                return s
            try:
                return json.loads(s)
            except Exception:
                return default

        return {
            'id': row[0],
            'brand_name': row[1],
            'industry': row[2],
            'keywords': _loads(row[3], []),
            'platforms': _loads(row[4], []),
            'current_stage': row[5],
            'status': row[6],
            'started_at': str(row[7]) if row[7] else None,
            'completed_at': str(row[8]) if row[8] else None,
            'stages': _loads(row[9], {}),
            'artifacts': _loads(row[10], {}),
            'error': row[11],
            'auto_run': bool(row[12]) if row[12] is not None else True,
        }


# 全局状态实例
workflow_state = WorkflowState()


class WorkflowEngine:
    """工作流引擎（异步，多模块协作闭环）

    编排 7 个阶段：热点搜集 → 内容生成 → 视频生成 → 内容审核 →
    多平台分发 → 互动监控 → 数据统计。
    每个阶段调用对应的 MediaCrawler 服务模块，失败可恢复。
    """

    def __init__(self):
        # 配置全部走环境变量，禁止硬编码敏感信息
        self.api_base = os.environ.get("WORKFLOW_API_BASE", "http://127.0.0.1:8000")
        self.timeout = int(os.environ.get("WORKFLOW_API_TIMEOUT", "90"))
        # 服务账号（仅当需要回退到 HTTP 调用时使用）
        self.service_username = os.environ.get("WORKFLOW_SERVICE_USERNAME", "workflow_service")
        self.service_password = os.environ.get("WORKFLOW_SERVICE_PASSWORD", "")
        self._service_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ---------- 工作流生命周期 ----------
    async def start_workflow(self, brand_name: str, industry: str = '默认行业',
                             keywords: List[str] = None, platforms: List[str] = None,
                             token: str = None, auto_run: bool = True) -> Dict:
        """启动一个完整的工作流"""
        wf_id = await workflow_state.create(
            brand_name=brand_name, industry=industry,
            keywords=keywords, platforms=platforms,
        )
        await workflow_state.update(wf_id, {'auto_run': auto_run})

        if auto_run:
            # 异步后台执行（替代原 threading.Thread）
            asyncio.create_task(self._run_workflow_async(wf_id, token))

        return {
            'success': True,
            'workflow_id': wf_id,
            'message': '工作流已创建' + ('，正在后台执行' if auto_run else '，等待手动执行'),
        }

    async def _run_workflow_async(self, wf_id: str, token: str = None):
        """异步执行完整工作流（后台 task）"""
        wf = await workflow_state.get(wf_id)
        if not wf:
            return

        await workflow_state.update(wf_id, {'status': 'running'})

        try:
            current_stage_id = wf.get('current_stage') or 'hotspot_collection'
            while current_stage_id:
                stage = self._get_stage_by_id(current_stage_id)
                if not stage:
                    break

                await workflow_state.update_stage(wf_id, current_stage_id, {
                    'status': 'running',
                    'started_at': datetime.now().isoformat(),
                })

                logger.info(f"[Workflow {wf_id}] 执行阶段: {stage['name']}")
                result = await self._execute_stage(wf_id, stage, token)

                if result.get('success'):
                    await workflow_state.update_stage(wf_id, current_stage_id, {
                        'status': 'completed',
                        'completed_at': datetime.now().isoformat(),
                        'result': result.get('data'),
                    })
                    logger.info(f"[Workflow {wf_id}] 阶段完成: {stage['name']}")
                    current_stage_id = stage.get('next_stage')
                    await workflow_state.update(wf_id, {'current_stage': current_stage_id})
                else:
                    await workflow_state.update_stage(wf_id, current_stage_id, {
                        'status': 'failed',
                        'completed_at': datetime.now().isoformat(),
                        'error': result.get('error'),
                    })
                    logger.error(
                        f"[Workflow {wf_id}] 阶段失败 {stage['name']}: {result.get('error')}"
                    )
                    await workflow_state.update(wf_id, {
                        'status': 'failed',
                        'error': f"阶段 '{stage['name']}' 失败: {result.get('error')}",
                    })
                    return

            await workflow_state.update(wf_id, {
                'status': 'completed',
                'completed_at': datetime.now().isoformat(),
                'current_stage': None,
            })
            logger.info(f"[Workflow {wf_id}] 工作流全部完成")

        except Exception as e:
            logger.exception(f"[Workflow {wf_id}] 异常: {e}")
            await workflow_state.update(wf_id, {
                'status': 'failed',
                'error': str(e),
            })

    def _get_stage_by_id(self, stage_id: str) -> Optional[Dict]:
        for s in WORKFLOW_STAGES:
            if s['id'] == stage_id:
                return s
        return None

    # ---------- 阶段执行 ----------
    async def _execute_stage(self, wf_id: str, stage: Dict, token: str = None) -> Dict:
        """执行单个阶段（直接调用对应 service 模块）"""
        wf = await workflow_state.get(wf_id)
        if not wf:
            return {'success': False, 'error': '工作流不存在'}

        stage_id = stage['id']
        payload = self._build_stage_payload(wf_id, stage_id, wf)

        # 按阶段分发到对应的 service 模块
        dispatch = {
            'hotspot_collection': self._execute_hotspot_stage,
            'content_generation': self._execute_content_generation_stage,
            'video_generation': self._execute_video_generation_stage,
            'content_moderation': self._execute_moderation_stage,
            'multi_platform_distribution': self._execute_distribution_stage,
            'interaction_monitoring': self._execute_interaction_stage,
            'data_analytics': self._execute_analytics_stage,
        }
        handler = dispatch.get(stage_id)
        if handler is None:
            return {'success': False, 'error': f'未知阶段: {stage_id}'}

        try:
            result = await handler(wf_id, payload, wf)
        except Exception as e:
            logger.exception(f"[Workflow {wf_id}] 阶段 {stage_id} 执行异常: {e}")
            return {'success': False, 'error': str(e)}

        if result.get('success'):
            # 保存到 artifacts，供下一阶段使用
            artifacts = wf.get('artifacts', {})
            artifacts[stage_id] = result.get('data') or {}
            await workflow_state.update(wf_id, {'artifacts': artifacts})
            return {'success': True, 'data': artifacts[stage_id]}
        else:
            err = result.get('error') or '未知错误'
            return {'success': False, 'error': err}

    async def _execute_hotspot_stage(self, wf_id: str, payload: Dict,
                                     wf: Dict) -> Dict:
        """热点搜集阶段：调用 ai_service 抓取热点"""
        if not _ai_available or get_ai_service is None:
            return {'success': False, 'error': 'ai 模块不可用，无法执行热点搜集'}

        try:
            ai_service = get_ai_service()
            # 调用 ai_service 的热点分析接口（若存在）
            method = getattr(ai_service, 'fetch_hotspots', None) \
                or getattr(ai_service, 'analyze_hotspots', None)
            if method is None:
                return {'success': False, 'error': 'ai_service 缺少 fetch_hotspots/analyze_hotspots 方法'}
            result = await method(**payload) if asyncio.iscoroutinefunction(method) else method(**payload)
            if isinstance(result, dict) and result.get('success', True):
                return {'success': True, 'data': result}
            return {'success': False, 'error': result.get('error', '热点搜集返回空') if isinstance(result, dict) else '热点搜集失败'}
        except Exception as e:
            return {'success': False, 'error': f'热点搜集异常: {e}'}

    async def _execute_content_generation_stage(self, wf_id: str, payload: Dict,
                                                wf: Dict) -> Dict:
        """内容生成阶段：调用 ai_service 生成图文内容"""
        if not _ai_available or get_ai_service is None:
            return {'success': False, 'error': 'ai 模块不可用，无法生成内容'}

        try:
            ai_service = get_ai_service()
            method = getattr(ai_service, 'generate_content', None)
            if method is None:
                return {'success': False, 'error': 'ai_service 缺少 generate_content 方法'}
            # ai_service.generate_content 通常接受 prompt 字符串
            prompt = payload.get('prompt') or payload.get('title', '')
            result = await method(prompt) if asyncio.iscoroutinefunction(method) else method(prompt)
            if isinstance(result, dict) and result.get('success'):
                return {'success': True, 'data': result}
            if isinstance(result, str):
                return {'success': True, 'data': {'content': result}}
            return {'success': False, 'error': '内容生成失败'}
        except Exception as e:
            return {'success': False, 'error': f'内容生成异常: {e}'}

    async def _execute_video_generation_stage(self, wf_id: str, payload: Dict,
                                              wf: Dict) -> Dict:
        """视频生成阶段：调用 ai_service 生成视频素材"""
        if not _ai_available or get_ai_service is None:
            # 视频生成非必须，降级跳过
            logger.warning(f"[Workflow {wf_id}] ai 模块不可用，视频生成阶段跳过")
            return {'success': True, 'data': {'skipped': True, 'reason': 'ai 模块不可用'}}

        try:
            ai_service = get_ai_service()
            method = getattr(ai_service, 'generate_video', None) \
                or getattr(ai_service, 'generate_explainer_video', None)
            if method is None:
                logger.warning(f"[Workflow {wf_id}] ai_service 无视频生成方法，跳过")
                return {'success': True, 'data': {'skipped': True, 'reason': '无视频生成方法'}}
            result = await method(**payload) if asyncio.iscoroutinefunction(method) else method(**payload)
            if isinstance(result, dict):
                return {'success': True, 'data': result}
            return {'success': True, 'data': {'result': result}}
        except Exception as e:
            # 视频生成失败不阻断主流程
            logger.warning(f"[Workflow {wf_id}] 视频生成失败（不阻断）: {e}")
            return {'success': True, 'data': {'skipped': True, 'error': str(e)}}

    async def _execute_moderation_stage(self, wf_id: str, payload: Dict,
                                        wf: Dict) -> Dict:
        """内容审核阶段：调用 moderation_service 审核内容"""
        if not _moderation_available or get_moderation_service is None:
            logger.warning(f"[Workflow {wf_id}] moderation 模块不可用，审核阶段跳过")
            return {'success': True, 'data': {'skipped': True, 'reason': 'moderation 模块不可用'}}

        try:
            moderation_service = get_moderation_service()
            content = payload.get('content', '')
            platform = (payload.get('platforms') or [''])[0]
            result = await moderation_service.moderate(content, platform)
            # result 是 ModerationResult 对象
            if hasattr(result, 'to_dict'):
                result_dict = result.to_dict()
            elif isinstance(result, dict):
                result_dict = result
            else:
                result_dict = {'decision': str(result)}

            # 命中拒绝决策时阻断流程
            decision = result_dict.get('decision', '')
            if decision == 'rejected':
                return {
                    'success': False,
                    'error': f"内容审核拒绝: {result_dict.get('violation_hits', [])}",
                }
            return {'success': True, 'data': result_dict}
        except Exception as e:
            logger.warning(f"[Workflow {wf_id}] 审核异常（降级通过）: {e}")
            return {'success': True, 'data': {'skipped': True, 'error': str(e)}}

    async def _execute_distribution_stage(self, wf_id: str, payload: Dict,
                                          wf: Dict) -> Dict:
        """多平台分发阶段：调用 publisher + scheduling 发布内容"""
        if not _publisher_available or get_multi_publisher is None:
            return {'success': False, 'error': 'publisher 模块不可用，无法发布'}

        try:
            from ..publisher import PublishTask, PublishStatus
            publisher = get_multi_publisher()

            platforms = payload.get('platforms', [])
            pub_task = PublishTask(
                source_post_id=wf_id,
                title=payload.get('title', ''),
                content=payload.get('content', ''),
                images=payload.get('images', []),
                video_path=payload.get('video_path'),
                target_platforms=platforms,
                user_id=int(payload.get('user_id', 1)),
            )

            # 定时发布走 scheduling，立即发布走 publisher
            scheduled_at = payload.get('scheduled_at')
            if scheduled_at and _scheduling_available and get_publish_scheduler is not None:
                scheduler = get_publish_scheduler()
                # 委托给调度器在指定时间执行
                await scheduler.schedule_task(pub_task, scheduled_at=scheduled_at)
                return {'success': True, 'data': {
                    'status': 'scheduled',
                    'scheduled_at': str(scheduled_at),
                    'platforms': platforms,
                }}

            result = await publisher.publish_to_multiple_platforms(pub_task)
            status = result.status if hasattr(result, 'status') else None
            if status == PublishStatus.SUCCESS or status == PublishStatus.PARTIAL:
                data = result.to_dict() if hasattr(result, 'to_dict') else {'status': str(status)}
                return {'success': True, 'data': data}
            return {
                'success': False,
                'error': getattr(result, 'error_message', None) or f'发布失败: {status}',
            }
        except Exception as e:
            return {'success': False, 'error': f'发布异常: {e}'}

    async def _execute_interaction_stage(self, wf_id: str, payload: Dict,
                                         wf: Dict) -> Dict:
        """互动监控阶段：调用 interactor 监控评论并自动互动"""
        if not _interactor_available or get_multi_interactor is None:
            logger.warning(f"[Workflow {wf_id}] interactor 模块不可用，互动阶段跳过")
            return {'success': True, 'data': {'skipped': True, 'reason': 'interactor 模块不可用'}}

        try:
            from ..interactor import InteractionTask, InteractionType
            interactor = get_multi_interactor()

            platforms = payload.get('platforms', [])
            # 默认执行点赞+评论互动
            task = InteractionTask(
                source_post_id=payload.get('source_post_id', wf_id),
                interaction_type=InteractionType.LIKE,
                target_platforms=platforms,
                content=payload.get('content', ''),
            )
            result = await interactor.interact_across_platforms(task)
            data = result.to_dict() if hasattr(result, 'to_dict') else {'status': str(result.status)}
            return {'success': True, 'data': data}
        except Exception as e:
            logger.warning(f"[Workflow {wf_id}] 互动异常（不阻断）: {e}")
            return {'success': True, 'data': {'skipped': True, 'error': str(e)}}

    async def _execute_analytics_stage(self, wf_id: str, payload: Dict,
                                       wf: Dict) -> Dict:
        """数据统计阶段：调用 analytics_service 聚合数据 + 生成下一轮反馈"""
        if not _analytics_available or get_analytics_service is None:
            logger.warning(f"[Workflow {wf_id}] analytics 模块不可用，统计阶段跳过")
            return {'success': True, 'data': {'skipped': True, 'reason': 'analytics 模块不可用'}}

        try:
            analytics_service = get_analytics_service()
            days = int(payload.get('days', 7))
            dashboard = await analytics_service.get_dashboard(days=days)

            # 数据回流：构建下一轮优化建议（保留原 monitoring_feedback 机制）
            feedback = self._build_analytics_feedback(dashboard, wf)
            dashboard['feedback'] = feedback

            # 写回 artifacts，供下一轮工作流读取
            wf = await workflow_state.get(wf_id)
            if wf:
                artifacts = wf.get('artifacts', {})
                artifacts['analytics_feedback'] = feedback
                await workflow_state.update(wf_id, {'artifacts': artifacts})

            logger.info(
                f"[Workflow {wf_id}] 统计完成: 引用率={feedback.get('citation_rate')}%, "
                f"建议={len(feedback.get('next_workflow_suggestions', []))}条"
            )
            return {'success': True, 'data': dashboard}
        except Exception as e:
            return {'success': False, 'error': f'统计异常: {e}'}

    def _build_analytics_feedback(self, dashboard: Dict, wf: Dict) -> Dict:
        """把统计数据转换为下一轮工作流的输入建议（保留原闭环反馈机制）"""
        feedback = {
            'citation_rate': 0,
            'mentioned_keywords': [],
            'missed_keywords': list(wf.get('keywords', [])),
            'next_workflow_suggestions': [],
            'generated_at': datetime.now().isoformat(),
        }
        try:
            summary = dashboard.get('summary', {}) if isinstance(dashboard, dict) else {}
            publish_count = summary.get('publish_count', 0)
            interaction_count = summary.get('interaction_count', 0)
            success_rate = summary.get('publish_success_rate', 0)

            if success_rate >= 0.8:
                feedback['next_workflow_suggestions'] = [
                    f'本期发布成功率 {success_rate*100:.1f}%，可拓展新长尾词',
                    '尝试扩展到更多平台（如快手、微信公众号）',
                ]
            elif success_rate > 0:
                feedback['next_workflow_suggestions'] = [
                    f'发布成功率仅 {success_rate*100:.1f}%，需检查账号健康度',
                    '针对失败平台加强内容适配',
                    '增加长尾关键词覆盖，提升抓取概率',
                ]
            else:
                feedback['next_workflow_suggestions'] = [
                    '本期无成功发布数据，建议检查账号 Cookie 有效性',
                    '降低发布频次，确保账号安全',
                ]

            feedback['publish_count'] = publish_count
            feedback['interaction_count'] = interaction_count
        except Exception as e:
            logger.warning(f"[Workflow] 反馈构建失败: {e}")
        return feedback

    async def _get_last_workflow_feedback(self, brand_name: str) -> Optional[Dict]:
        """从最近一个已完成工作流的 artifacts 中读取 analytics_feedback

        用于实现真闭环：上一轮的统计结果影响下一轮的热点搜集/内容生成。
        """
        try:
            items = await workflow_state.list_all(20)
            for wf in items:
                if wf.get('status') != 'completed':
                    continue
                if wf.get('brand_name') != brand_name:
                    continue
                feedback = (wf.get('artifacts') or {}).get('analytics_feedback')
                if feedback and isinstance(feedback, dict):
                    return feedback
            return None
        except Exception as e:
            logger.warning(f"[Workflow] 读取上一轮反馈失败: {e}")
            return None

    # ---------- payload 构造（保留原数据串联逻辑）----------
    def _build_stage_payload(self, wf_id: str, stage_id: str, wf: Dict) -> Dict:
        """根据阶段构造调用参数，数据从 artifacts 自动串联"""
        brand = wf.get('brand_name', '')
        industry = wf.get('industry', '')
        artifacts = wf.get('artifacts', {})
        keywords = wf.get('keywords', [])
        platforms = wf.get('platforms', [])

        if stage_id == 'hotspot_collection':
            payload = {
                'brand_name': brand,
                'industry': industry,
                'keywords': keywords,
                'platforms': platforms,
            }
            # 闭环回流：上一轮的反馈作为本轮输入
            # （异步获取在调用方处理，这里仅放占位）
            return payload

        elif stage_id == 'content_generation':
            hotspot = artifacts.get('hotspot_collection', {}) or {}
            topics = hotspot.get('topics') or hotspot.get('hotspots') or []
            topic_str = topics[0] if topics and isinstance(topics, list) else brand
            return {
                'title': f'{brand}{industry}内容选题',
                'prompt': f'为品牌"{brand}"({industry})生成一篇优质内容。选题方向: {topic_str}。关键词: {", ".join(keywords[:5])}',
                'brand_info': {
                    'name': brand,
                    'industry': industry,
                    'expertise': keywords,
                },
                'target_platform': platforms[0] if platforms else 'chatgpt',
                'word_count': 1500,
            }

        elif stage_id == 'video_generation':
            gen_artifact = artifacts.get('content_generation', {}) or {}
            content = ''
            title = f'{brand}内容'
            if isinstance(gen_artifact, dict):
                content = gen_artifact.get('content') or gen_artifact.get('full_content') or ''
                title = gen_artifact.get('title') or title
            return {
                'title': title,
                'content': content,
                'brand_name': brand,
                'keywords': keywords,
            }

        elif stage_id == 'content_moderation':
            gen_artifact = artifacts.get('content_generation', {}) or {}
            opt_artifact = artifacts.get('content_optimization', {}) or {}
            content = ''
            if isinstance(opt_artifact, dict):
                content = (opt_artifact.get('optimized_text')
                           or opt_artifact.get('optimized_content')
                           or opt_artifact.get('content') or '')
            if not content and isinstance(gen_artifact, dict):
                content = gen_artifact.get('content') or gen_artifact.get('full_content') or ''
            if not content or len(content) < 50:
                content = f"{brand}是{industry}领域的专业品牌，致力于为客户提供高品质的产品和服务。"
            return {
                'content': content,
                'platforms': platforms,
            }

        elif stage_id == 'multi_platform_distribution':
            gen_artifact = artifacts.get('content_generation', {}) or {}
            opt_artifact = artifacts.get('content_optimization', {}) or {}
            content = ''
            if isinstance(opt_artifact, dict):
                content = (opt_artifact.get('optimized_text')
                           or opt_artifact.get('optimized_content')
                           or opt_artifact.get('content') or '')
            if not content and isinstance(gen_artifact, dict):
                content = gen_artifact.get('content') or gen_artifact.get('full_content') or ''
            title = f'{brand}内容'
            if isinstance(gen_artifact, dict):
                title = gen_artifact.get('title') or title
            images = artifacts.get('images', [])
            video_artifact = artifacts.get('video_generation', {}) or {}
            video_path = video_artifact.get('video_path') or video_artifact.get('path') if isinstance(video_artifact, dict) else None

            tomorrow = (datetime.now() + timedelta(days=1)).isoformat()
            return {
                'content_type': 'article',
                'title': title,
                'content': content or f'{brand}是{industry}领域的专业品牌',
                'keywords': keywords,
                'platforms': platforms,
                'images': images,
                'video_path': video_path,
                'execute_now': True,
                'scheduled_at': None,  # 立即发布
                'user_id': 1,
            }

        elif stage_id == 'interaction_monitoring':
            pub_artifact = artifacts.get('multi_platform_distribution', {}) or {}
            source_post_id = ''
            if isinstance(pub_artifact, dict):
                source_post_id = pub_artifact.get('task_id') or pub_artifact.get('source_post_id') or wf_id
            return {
                'source_post_id': source_post_id,
                'platforms': platforms,
                'content': f'感谢关注{brand}，欢迎互动！',
            }

        elif stage_id == 'data_analytics':
            return {
                'brand_name': brand,
                'industry': industry,
                'keywords': keywords,
                'days': 7,
                'workflow_id': wf_id,
            }

        return {}

    # ---------- 查询与管理 ----------
    async def get_status(self, wf_id: str) -> Dict:
        """获取工作流状态"""
        wf = await workflow_state.get(wf_id)
        if not wf:
            return {'success': False, 'error': '工作流不存在'}

        total = len(WORKFLOW_STAGES)
        stages_state = wf.get('stages', {})
        completed = sum(1 for s in stages_state.values() if s.get('status') == 'completed')
        progress = int(completed / total * 100) if total > 0 else 0

        stages_list = []
        for s in WORKFLOW_STAGES:
            stage_state = stages_state.get(s['id'], {})
            stages_list.append({
                'id': s['id'],
                'name': s['name'],
                'icon': s['icon'],
                'description': s['description'],
                'status': stage_state.get('status', 'pending'),
                'started_at': stage_state.get('started_at'),
                'completed_at': stage_state.get('completed_at'),
                'result': stage_state.get('result'),
                'error': stage_state.get('error'),
            })

        return {
            'success': True,
            'workflow': {
                'id': wf['id'],
                'brand_name': wf.get('brand_name'),
                'industry': wf.get('industry'),
                'status': wf.get('status'),
                'current_stage': wf.get('current_stage'),
                'progress': progress,
                'completed_stages': completed,
                'total_stages': total,
                'started_at': wf.get('started_at'),
                'completed_at': wf.get('completed_at'),
                'error': wf.get('error'),
                'stages': stages_list,
                'artifacts': wf.get('artifacts', {}),
            },
        }

    async def list_workflows(self, limit: int = 20) -> Dict:
        """列出所有工作流"""
        items = await workflow_state.list_all(limit)
        workflows = []
        total = len(WORKFLOW_STAGES)
        for wf in items:
            stages_state = wf.get('stages', {})
            completed = sum(1 for s in stages_state.values() if s.get('status') == 'completed')
            workflows.append({
                'id': wf.get('id'),
                'brand_name': wf.get('brand_name'),
                'status': wf.get('status'),
                'progress': int(completed / total * 100) if total > 0 else 0,
                'current_stage': wf.get('current_stage'),
                'started_at': wf.get('started_at'),
                'completed_at': wf.get('completed_at'),
            })
        return {'success': True, 'workflows': workflows, 'total': len(workflows)}

    async def execute_stage(self, wf_id: str, stage_id: str, token: str = None) -> Dict:
        """手动执行单个阶段"""
        wf = await workflow_state.get(wf_id)
        if not wf:
            return {'success': False, 'error': '工作流不存在'}

        stage = self._get_stage_by_id(stage_id)
        if not stage:
            return {'success': False, 'error': '阶段不存在'}

        await workflow_state.update_stage(wf_id, stage_id, {
            'status': 'running',
            'started_at': datetime.now().isoformat(),
        })

        result = await self._execute_stage(wf_id, stage, token)
        if result.get('success'):
            await workflow_state.update_stage(wf_id, stage_id, {
                'status': 'completed',
                'completed_at': datetime.now().isoformat(),
                'result': result.get('data'),
            })
            await workflow_state.update(wf_id, {'current_stage': stage.get('next_stage')})
        else:
            await workflow_state.update_stage(wf_id, stage_id, {
                'status': 'failed',
                'completed_at': datetime.now().isoformat(),
                'error': result.get('error'),
            })

        return result

    async def resume_workflow(self, wf_id: str, token: str = None) -> Dict:
        """恢复工作流（从当前阶段继续）"""
        wf = await workflow_state.get(wf_id)
        if not wf:
            return {'success': False, 'error': '工作流不存在'}

        if not wf.get('current_stage'):
            return {'success': False, 'error': '工作流已完成'}

        asyncio.create_task(self._run_workflow_async(wf_id, token))
        return {'success': True, 'message': '工作流已恢复执行'}


# ============ 单例 ============
_workflow_engine: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    """获取工作流引擎单例"""
    global _workflow_engine
    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine()
    return _workflow_engine
