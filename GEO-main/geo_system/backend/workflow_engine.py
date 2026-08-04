"""
GEO 内容工程闭环工作流引擎

将各功能模块串联成自动化闭环：
关键词研究 → 品牌诊断 → 内容生成 → 内容分析 → 内容优化 → 创建AI任务 → 加入内容日历 → 发布 → 效果监控 → 反馈

设计原则：
- 数据自动流转，无需用户手动填写
- 每个环节的输出自动作为下一环节的输入
- 支持单步执行和全流程一键执行
- 失败环节自动重试或跳过，不影响整体流程
"""

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


def wf_id_to_int(wf_id: str) -> int:
    """把 workflow id 转换成数字（用于文件名前缀）"""
    if not wf_id:
        return 0
    # 用字符串的 hash 取绝对值的低 16 位
    try:
        return abs(hash(wf_id)) & 0xFFFF
    except Exception:
        return 0


# 工作流阶段定义
WORKFLOW_STAGES = [
    {
        'id': 'keyword_research',
        'name': '关键词研究',
        'icon': '🔑',
        'description': '基于品牌信息自动生成核心关键词和长尾词',
        'api_endpoint': '/api/keywords/research',
        'method': 'POST',
        'next_stage': 'brand_diagnosis',
    },
    {
        'id': 'brand_diagnosis',
        'name': '品牌诊断',
        'icon': '🏥',
        'description': '诊断品牌在AI平台的可见度和影响力',
        'api_endpoint': '/api/brand-diagnosis',
        'method': 'POST',
        'next_stage': 'content_generation',
    },
    {
        'id': 'content_generation',
        'name': '内容生成',
        'icon': '✍️',
        'description': '基于关键词批量生成GEO优化文章',
        'api_endpoint': '/api/content/generate',
        'method': 'POST',
        'next_stage': 'content_analysis',
    },
    {
        'id': 'content_analysis',
        'name': '内容分析',
        'icon': '🔍',
        'description': '评估内容质量（5项评分）',
        'api_endpoint': '/api/content/analyze',
        'method': 'POST',
        'next_stage': 'content_optimization',
    },
    {
        'id': 'content_optimization',
        'name': '内容优化',
        'icon': '⚡',
        'description': '优化内容以提升AI引用率',
        'api_endpoint': '/api/content/optimize',
        'method': 'POST',
        'next_stage': 'ai_task_creation',
    },
    {
        'id': 'ai_task_creation',
        'name': '创建AI任务',
        'icon': '🤖',
        'description': '将优化后的内容创建为AI任务',
        'api_endpoint': '/api/ai-tasks',
        'method': 'POST',
        'next_stage': 'calendar_scheduling',
    },
    {
        'id': 'calendar_scheduling',
        'name': '内容日历排期',
        'icon': '📅',
        'description': '将内容加入日历并自动排期',
        'api_endpoint': '/api/calendar/items',
        'method': 'POST',
        'next_stage': 'publish',
    },
    {
        'id': 'publish',
        'name': '发布到平台',
        'icon': '📤',
        'description': '一键发布到配置的平台账号',
        'api_endpoint': '/api/publish/tasks',
        'method': 'POST',
        'next_stage': 'monitoring',
    },
    {
        'id': 'monitoring',
        'name': '效果监控',
        'icon': '📊',
        'description': '检测AI引用率和品牌提及情况',
        'api_endpoint': '/api/monitoring/ai-citation/batch-check',
        'method': 'POST',
        'next_stage': None,  # 闭环完成
    },
]


class WorkflowState:
    """工作流状态（内存中保存，进程重启会丢失）"""

    def __init__(self):
        self.lock = threading.Lock()
        # workflow_id -> state dict
        self.workflows: Dict[str, Dict] = {}

    def create(self, brand_name: str, industry: str = '定制家具',
               keywords: List[str] = None, platforms: List[str] = None) -> str:
        wf_id = f"wf_{uuid.uuid4().hex[:12]}"
        with self.lock:
            self.workflows[wf_id] = {
                'id': wf_id,
                'brand_name': brand_name,
                'industry': industry,
                'keywords': keywords or [],
                'platforms': platforms or ['website_blog'],
                'current_stage': 'keyword_research',
                'status': 'pending',  # pending/running/paused/completed/failed
                'started_at': datetime.now().isoformat(),
                'completed_at': None,
                'stages': {},  # stage_id -> stage_state
                'artifacts': {},  # 共享数据
                'error': None,
                'auto_run': True,  # 自动推进到下一阶段
            }
        return wf_id

    def get(self, wf_id: str) -> Optional[Dict]:
        with self.lock:
            return self.workflows.get(wf_id)

    def update(self, wf_id: str, updates: Dict):
        with self.lock:
            if wf_id in self.workflows:
                self.workflows[wf_id].update(updates)

    def update_stage(self, wf_id: str, stage_id: str, stage_state: Dict):
        with self.lock:
            if wf_id in self.workflows:
                self.workflows[wf_id]['stages'][stage_id] = {
                    'status': 'pending',
                    'started_at': None,
                    'completed_at': None,
                    'result': None,
                    'error': None,
                    **stage_state,
                }

    def list_all(self, limit: int = 20) -> List[Dict]:
        with self.lock:
            items = list(self.workflows.values())
        items.sort(key=lambda x: x.get('started_at', ''), reverse=True)
        return items[:limit]


# 全局状态
workflow_state = WorkflowState()


class GEOWorkflowEngine:
    """GEO 工作流引擎"""

    # 服务账号配置（用于内部 API 调用，无需用户登录）
    SERVICE_USERNAME = 'workflow_service'
    SERVICE_PASSWORD = 'workflow-svc-2026-geo!'

    def __init__(self):
        # 容器内 Flask 监听 5000 端口；API 端点已包含 /api 前缀
        self.api_base = 'http://127.0.0.1:5000'
        self.timeout = 90
        self._service_token = None
        self._token_expires_at = 0  # unix timestamp

    def _ensure_service_account(self) -> str:
        """确保服务账号存在并返回有效的 JWT token

        必须在 Flask app context 中调用一次以完成初始化。
        之后在子线程调用时，若 token 仍在有效期内，直接返回缓存。
        """
        import time
        # token 还有 1 小时以上有效期，直接复用
        if self._service_token and time.time() < self._token_expires_at - 3600:
            return self._service_token

        # 1. 直接用 user_repo 创建服务账号（如果不存在），然后登录获取 token
        try:
            from postgresql_database import user_repo
            existing = user_repo.get_user_by_username(self.SERVICE_USERNAME)
            if not existing:
                # 创建服务账号
                result = user_repo.create_user(self.SERVICE_USERNAME, self.SERVICE_PASSWORD)
                if result.get('success'):
                    logger.info("[Workflow] 服务账号已创建")
                else:
                    logger.warning(f"[Workflow] 服务账号创建失败: {result.get('message')}")
        except Exception as e:
            logger.warning(f"[Workflow] 服务账号 user_repo 操作失败: {e}")

        # 2. 通过 HTTP 登录获取 token（注意路径是 /api/auth/login）
        try:
            resp = requests.post(
                f'{self.api_base}/api/auth/login',
                json={'username': self.SERVICE_USERNAME, 'password': self.SERVICE_PASSWORD},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success') and data.get('access_token'):
                    self._service_token = data['access_token']
                    self._token_expires_at = time.time() + 86400 - 3600
                    logger.info("[Workflow] 服务账号 token 获取成功（HTTP 登录）")
                    return self._service_token
        except Exception as e:
            logger.warning(f"[Workflow] 服务账号 HTTP 登录失败: {e}")

        # 3. 兜底：直接用 flask_jwt_extended 生成 token
        # 注意：此方法必须在 Flask 请求上下文或 app_context 中调用
        try:
            from flask_jwt_extended import create_access_token
            token = create_access_token(identity=self.SERVICE_USERNAME)
            self._service_token = token
            self._token_expires_at = time.time() + 86400 - 3600
            logger.info("[Workflow] 服务账号 token 直接生成（兜底）")
            return token
        except Exception as e:
            logger.error(f"[Workflow] 直接生成 token 失败: {e}（请在 app_context 中预先调用 _ensure_service_account）")
            return None

    def _call_api(self, method: str, endpoint: str, payload: Dict = None,
                  token: str = None) -> Dict:
        """内部调用后端 API（自动注入服务账号 token）"""
        url = f"{self.api_base}{endpoint}"
        headers = {'Content-Type': 'application/json'}

        # 优先使用传入的 token（用户 token），否则使用服务账号 token
        if not token:
            token = self._ensure_service_account()
        if token:
            headers['Authorization'] = f'Bearer {token}'

        try:
            if method.upper() == 'GET':
                resp = requests.get(url, headers=headers, params=payload, timeout=self.timeout)
            else:
                resp = requests.request(method, url, headers=headers, json=payload, timeout=self.timeout)

            try:
                return resp.json()
            except Exception:
                return {'success': False, 'error': f'HTTP {resp.status_code}: {resp.text[:200]}'}
        except Exception as e:
            return {'success': False, 'error': f'API调用失败: {str(e)}'}

    def start_workflow(self, brand_name: str, industry: str = '定制家具',
                       keywords: List[str] = None, platforms: List[str] = None,
                       token: str = None, auto_run: bool = True) -> Dict:
        """启动一个完整的工作流"""
        wf_id = workflow_state.create(
            brand_name=brand_name, industry=industry,
            keywords=keywords, platforms=platforms
        )
        workflow_state.update(wf_id, {'auto_run': auto_run})

        if auto_run:
            # 后台异步执行
            t = threading.Thread(target=self._run_workflow_async,
                                 args=(wf_id, token), daemon=True)
            t.start()

        return {
            'success': True,
            'workflow_id': wf_id,
            'message': '工作流已创建' + ('，正在后台执行' if auto_run else '，等待手动执行'),
        }

    def _run_workflow_async(self, wf_id: str, token: str = None):
        """异步执行完整工作流"""
        wf = workflow_state.get(wf_id)
        if not wf:
            return

        workflow_state.update(wf_id, {'status': 'running'})

        try:
            current_stage_id = wf['current_stage']
            while current_stage_id:
                stage = self._get_stage_by_id(current_stage_id)
                if not stage:
                    break

                workflow_state.update_stage(wf_id, current_stage_id, {
                    'status': 'running',
                    'started_at': datetime.now().isoformat(),
                })

                logger.info(f"[Workflow {wf_id}] 执行阶段: {stage['name']}")
                result = self._execute_stage(wf_id, stage, token)

                if result.get('success'):
                    workflow_state.update_stage(wf_id, current_stage_id, {
                        'status': 'completed',
                        'completed_at': datetime.now().isoformat(),
                        'result': result.get('data'),
                    })
                    logger.info(f"[Workflow {wf_id}] 阶段完成: {stage['name']}")
                    current_stage_id = stage['next_stage']
                    workflow_state.update(wf_id, {'current_stage': current_stage_id})
                else:
                    workflow_state.update_stage(wf_id, current_stage_id, {
                        'status': 'failed',
                        'completed_at': datetime.now().isoformat(),
                        'error': result.get('error'),
                    })
                    logger.error(f"[Workflow {wf_id}] 阶段失败 {stage['name']}: {result.get('error')}")
                    workflow_state.update(wf_id, {
                        'status': 'failed',
                        'error': f"阶段 '{stage['name']}' 失败: {result.get('error')}",
                    })
                    return

            workflow_state.update(wf_id, {
                'status': 'completed',
                'completed_at': datetime.now().isoformat(),
                'current_stage': None,
            })
            logger.info(f"[Workflow {wf_id}] 工作流全部完成")

        except Exception as e:
            logger.exception(f"[Workflow {wf_id}] 异常: {e}")
            workflow_state.update(wf_id, {
                'status': 'failed',
                'error': str(e),
            })

    def _get_stage_by_id(self, stage_id: str) -> Optional[Dict]:
        for s in WORKFLOW_STAGES:
            if s['id'] == stage_id:
                return s
        return None

    def _execute_stage(self, wf_id: str, stage: Dict, token: str = None) -> Dict:
        """执行单个阶段"""
        wf = workflow_state.get(wf_id)
        if not wf:
            return {'success': False, 'error': '工作流不存在'}

        stage_id = stage['id']
        endpoint = stage['api_endpoint']
        method = stage['method']

        # 根据阶段构造 payload
        payload = self._build_stage_payload(wf_id, stage_id, wf)

        # monitoring 阶段直接调用 monitoring_service（避免 HTTP 超时）
        if stage_id == 'monitoring':
            return self._execute_monitoring_stage(wf_id, payload)

        # 优先用用户 token，否则用服务账号 token（_call_api 内部自动处理）
        result = self._call_api(method, endpoint, payload, token)
        if result.get('success'):
            # 保存到 artifacts，供下一阶段使用
            artifacts = wf.get('artifacts', {})
            artifacts[stage_id] = result.get('data') or result.get('report') or result.get('result') or {}
            workflow_state.update(wf_id, {'artifacts': artifacts})

            # 内容优化完成后，预生成图片（避免发布时才生成导致失败）
            if stage_id == 'content_optimization':
                try:
                    self._generate_images_for_workflow(wf_id)
                except Exception as e:
                    logger.warning(f"[Workflow {wf_id}] 图片预生成失败（不阻断流程）: {e}")

            return {'success': True, 'data': artifacts[stage_id]}
        else:
            # 提取错误信息
            err = result.get('error') or result.get('message') or result.get('msg') or '未知错误'
            return {'success': False, 'error': err}

    def _generate_images_for_workflow(self, wf_id: str):
        """在内容优化完成后，预生成小红书配图，写入 artifacts['images']

        图片会持久化保存到 /app/data/generated_images/workflow/，artifacts['images']
        存放本地文件路径列表，便于发布阶段直接上传到小红书。

        失败不阻断主流程，发布阶段会再尝试一次。
        """
        wf = workflow_state.get(wf_id)
        if not wf:
            return

        artifacts = wf.get('artifacts', {})

        # 如果已有图片，跳过
        if artifacts.get('images'):
            logger.info(f"[Workflow {wf_id}] 图片已存在，跳过预生成")
            return

        # 取优化后的内容
        opt_artifact = artifacts.get('content_optimization', {}) or {}
        gen_artifact = artifacts.get('content_generation', {}) or {}

        content = ''
        if isinstance(opt_artifact, dict):
            content = (opt_artifact.get('optimized_text')
                       or opt_artifact.get('optimized_content')
                       or opt_artifact.get('content') or '')
        if not content and isinstance(gen_artifact, dict):
            content = (gen_artifact.get('content')
                       or gen_artifact.get('full_content') or '')

        title = ''
        if isinstance(gen_artifact, dict):
            title = (gen_artifact.get('title')
                     or gen_artifact.get('config', {}).get('title') or '')
        if not title:
            title = f"{wf.get('brand_name', '')} GEO内容"

        if len(content) < 50:
            logger.warning(f"[Workflow {wf_id}] 内容过短，跳过图片生成")
            return

        try:
            from image_generation_service import image_service
            logger.info(f"[Workflow {wf_id}] 开始预生成图片: title={title[:30]}")
            base64_images = image_service.generate_xiaohongshu_images(
                title=title,
                content=content,
                keywords=wf.get('keywords', []),
                count=3,
                brand_name=wf.get('brand_name'),
            )
            if base64_images:
                # 持久化保存到本地，artifacts['images'] 存本地路径（发布时直接上传）
                local_paths = []
                for idx, img_b64 in enumerate(base64_images):
                    path = image_service.save_base64_to_local(
                        img_b64,
                        brand_name=wf.get('brand_name'),
                        task_id=wf_id_to_int(wf_id),
                        index=idx,
                        subdir='workflow',
                    )
                    if path:
                        local_paths.append(path)
                if local_paths:
                    artifacts['images'] = local_paths
                    workflow_state.update(wf_id, {'artifacts': artifacts})
                    logger.info(f"[Workflow {wf_id}] 预生成 {len(local_paths)} 张图片已保存到本地: {local_paths}")
                else:
                    # 本地保存失败时降级为 base64
                    artifacts['images'] = base64_images
                    workflow_state.update(wf_id, {'artifacts': artifacts})
                    logger.warning(f"[Workflow {wf_id}] 本地保存失败，使用 base64 降级")
            else:
                logger.warning(f"[Workflow {wf_id}] 图片预生成返回空")
        except Exception as e:
            logger.error(f"[Workflow {wf_id}] 图片预生成异常: {e}")

    def _execute_monitoring_stage(self, wf_id: str, payload: Dict) -> Dict:
        """直接调用 monitoring_service 执行监控（绕过 HTTP 避免超时）

        监控结果会回流到 artifacts['monitoring_feedback']，供下一轮工作流参考：
        - mentioned_keywords: 被AI提及的关键词（表现好，可继续保持）
        - missed_keywords: 未被提及的关键词（下一轮需要加强优化）
        - citation_rate: AI引用率
        - next_workflow_suggestions: 给下一轮关键词研究的建议
        """
        try:
            from monitoring_service import monitoring_service
            if not monitoring_service:
                return {'success': False, 'error': 'monitoring_service 未初始化'}

            keywords = payload.get('keywords')
            platforms = payload.get('platforms', ['chatgpt'])
            brand_name = payload.get('brand_name', '织然家具')
            batch_name = payload.get('batch_name')

            # 限制规模，避免耗时过长
            if keywords:
                keywords = keywords[:10]
            platforms = platforms[:2]

            result = monitoring_service.batch_check_citation(
                keywords=keywords,
                platforms=platforms,
                brand_name=brand_name,
                batch_name=batch_name
            )

            # 保存到 artifacts
            wf = workflow_state.get(wf_id)
            artifacts = wf.get('artifacts', {})
            artifacts['monitoring'] = result

            # 数据回流：解析监控结果，形成下一轮优化建议
            feedback = self._build_monitoring_feedback(result, keywords or [])
            artifacts['monitoring_feedback'] = feedback
            workflow_state.update(wf_id, {'artifacts': artifacts})

            logger.info(f"[Workflow {wf_id}] 监控数据回流: 引用率={feedback.get('citation_rate')}%, "
                        f"被提及={len(feedback.get('mentioned_keywords', []))}个, "
                        f"未提及={len(feedback.get('missed_keywords', []))}个")

            return {'success': True, 'data': result}
        except Exception as e:
            logger.error(f"[Workflow] monitoring 阶段失败: {e}")
            return {'success': False, 'error': str(e)}

    def _get_last_workflow_feedback(self, brand_name: str) -> Optional[Dict]:
        """从最近一个已完成工作流的 artifacts 中读取 monitoring_feedback

        用于实现真闭环：上一轮的监控结果影响下一轮的关键词研究。
        """
        try:
            items = workflow_state.list_all(20)
            for wf in items:
                # 跳过当前工作流本身（如果传入的是同一个），只看已完成的工作流
                if wf.get('status') != 'completed':
                    continue
                # 同品牌才回流
                if wf.get('brand_name') != brand_name:
                    continue
                feedback = (wf.get('artifacts') or {}).get('monitoring_feedback')
                if feedback and isinstance(feedback, dict):
                    return feedback
            return None
        except Exception as e:
            logger.warning(f"[Workflow] 读取上一轮反馈失败: {e}")
            return None

    def _build_monitoring_feedback(self, monitoring_result: Dict,
                                     original_keywords: List[str]) -> Dict:
        """把监控结果转换为下一轮工作流的输入建议"""
        feedback = {
            'citation_rate': 0,
            'mentioned_keywords': [],
            'missed_keywords': list(original_keywords),
            'next_workflow_suggestions': [],
            'generated_at': datetime.now().isoformat(),
        }

        try:
            if not isinstance(monitoring_result, dict):
                return feedback

            # 解析批量检测的结果
            checks = monitoring_result.get('checks') or monitoring_result.get('results') or []
            total = 0
            mentioned = 0
            mentioned_set = set()

            for check in checks:
                if not isinstance(check, dict):
                    continue
                kw = check.get('keyword') or check.get('query') or ''
                is_mentioned = check.get('mentioned') or check.get('is_mentioned') or False
                if kw:
                    total += 1
                    if is_mentioned:
                        mentioned += 1
                        mentioned_set.add(kw)

            if total > 0:
                feedback['citation_rate'] = round(mentioned * 100 / total, 1)

            feedback['mentioned_keywords'] = list(mentioned_set)
            feedback['missed_keywords'] = [k for k in original_keywords if k not in mentioned_set]

            # 生成下一轮建议
            if feedback['missed_keywords']:
                feedback['next_workflow_suggestions'] = [
                    f'针对未被AI提及的关键词加强内容优化: {", ".join(feedback["missed_keywords"][:3])}',
                    '在内容中更自然地植入品牌名和核心产品词',
                    '增加长尾关键词覆盖，提升AI抓取概率',
                ]
            else:
                feedback['next_workflow_suggestions'] = [
                    '当前关键词已被AI稳定引用，可拓展新长尾词',
                    '尝试扩展到更多AI平台（如Kimi、豆包）',
                ]

        except Exception as e:
            logger.warning(f"[Workflow] 监控反馈解析失败: {e}")

        return feedback

    def _build_stage_payload(self, wf_id: str, stage_id: str, wf: Dict) -> Dict:
        """根据阶段构造 API 请求 payload，数据从 artifacts 自动串联"""
        brand = wf.get('brand_name', '织然家具')
        industry = wf.get('industry', '定制家具')
        artifacts = wf.get('artifacts', {})

        if stage_id == 'keyword_research':
            # 关键词研究：基于品牌+行业生成
            # 闭环回流：读取上一个已完成工作流的 monitoring_feedback，把未提及的关键词作为本轮回炉重点
            payload = {
                'seed_keyword': brand,
                'industry': industry,
                'depth': 2,
            }
            previous_feedback = self._get_last_workflow_feedback(brand)
            if previous_feedback:
                payload['focus_keywords'] = previous_feedback.get('missed_keywords', [])
                payload['avoid_keywords'] = previous_feedback.get('mentioned_keywords', [])
                payload['previous_citation_rate'] = previous_feedback.get('citation_rate', 0)
                payload['suggestions'] = previous_feedback.get('next_workflow_suggestions', [])
                logger.info(f"[Workflow {wf_id}] 应用上一轮回流: "
                            f"引用率={payload['previous_citation_rate']}%, "
                            f"focus={len(payload['focus_keywords'])}个, "
                            f"avoid={len(payload['avoid_keywords'])}个")
            return payload

        elif stage_id == 'brand_diagnosis':
            return {'brand_name': brand}

        elif stage_id == 'content_generation':
            # 用关键词研究的结果生成内容
            kw_artifact = artifacts.get('keyword_research', {})
            keywords = wf.get('keywords') or []
            if not keywords and isinstance(kw_artifact, dict):
                keywords = kw_artifact.get('keywords') or kw_artifact.get('suggestions') or []
                if isinstance(keywords, list) and keywords:
                    if isinstance(keywords[0], dict):
                        keywords = [k.get('keyword', str(k)) for k in keywords[:5]]
                    else:
                        keywords = [str(k) for k in keywords[:5]]

            if not keywords:
                keywords = [f'{industry}推荐', f'{brand}怎么样', '怎么选家具']

            return {
                'title': f'{brand}{industry}选购指南',
                'brand_info': {
                    'name': brand,
                    'industry': industry,
                    'expertise': keywords,
                },
                'target_platform': 'chatgpt',
                'word_count': 1500,
            }

        elif stage_id == 'content_analysis':
            # 用生成的内容进行分析
            gen_artifact = artifacts.get('content_generation', {})
            content = ''
            if isinstance(gen_artifact, dict):
                content = (gen_artifact.get('content') or gen_artifact.get('full_content')
                          or gen_artifact.get('optimized_text') or '')
                # 如果没有完整内容，从 outline 拼接
                if not content and gen_artifact.get('outline'):
                    outline = gen_artifact['outline']
                    if isinstance(outline, list):
                        parts = []
                        for item in outline:
                            if isinstance(item, dict):
                                title = item.get('title', '')
                                points = item.get('key_points', [])
                                if title:
                                    parts.append(f"## {title}")
                                if points:
                                    for p in points:
                                        parts.append(f"- {p}")
                                parts.append('')  # 空行
                            elif isinstance(item, str):
                                parts.append(item)
                        content = '\n'.join(parts)

            if not content or len(content) < 50:
                # 用品牌信息兜底
                content = f"{brand}是{industry}领域的专业品牌，致力于为客户提供高品质的产品和服务。" \
                         f"我们采用环保材料，经过严格质量控制，确保每一件产品都能满足客户需求。" \
                         f"选择{brand}，就是选择品质生活的开始。"
            return {'content': content}

        elif stage_id == 'content_optimization':
            # 用分析前的内容进行优化（分析结果中有原内容引用）
            gen_artifact = artifacts.get('content_generation', {})
            content = ''
            if isinstance(gen_artifact, dict):
                content = gen_artifact.get('content') or gen_artifact.get('full_content') or ''
                # 从 outline 拼接
                if not content and gen_artifact.get('outline'):
                    outline = gen_artifact['outline']
                    if isinstance(outline, list):
                        parts = []
                        for item in outline:
                            if isinstance(item, dict):
                                title = item.get('title', '')
                                points = item.get('key_points', [])
                                if title:
                                    parts.append(f"## {title}")
                                if points:
                                    for p in points:
                                        parts.append(f"- {p}")
                                parts.append('')
                            elif isinstance(item, str):
                                parts.append(item)
                        content = '\n'.join(parts)

            if not content or len(content) < 50:
                content = f"{brand}是{industry}领域的专业品牌，致力于为客户提供高品质的产品和服务。" \
                         f"我们采用环保材料，经过严格质量控制，确保每一件产品都能满足客户需求。"
            return {
                'content': content,
                'optimization_level': 'medium',
            }

        elif stage_id == 'ai_task_creation':
            # 创建 AI 任务跟踪
            gen_artifact = artifacts.get('content_generation', {})
            title = f'{brand} GEO内容'
            if isinstance(gen_artifact, dict):
                title = gen_artifact.get('title') or gen_artifact.get('config', {}).get('title') or title

            return {
                'task_type': 'geo_optimization',
                'title': title,
                'description': f'由工作流自动创建 - {brand} {industry}',
                'input_data': {
                    'brand_name': brand,
                    'industry': industry,
                    'keywords': wf.get('keywords', []),
                    'workflow_id': wf_id,
                },
            }

        elif stage_id == 'calendar_scheduling':
            # 加入内容日历，排期为明天发布
            gen_artifact = artifacts.get('content_generation', {})
            task_artifact = artifacts.get('ai_task_creation', {})
            title = f'{brand} GEO内容'
            if isinstance(gen_artifact, dict):
                title = gen_artifact.get('title') or title

            task_id = None
            if isinstance(task_artifact, dict):
                task_id = task_artifact.get('id') or task_artifact.get('task_id')

            tomorrow = (datetime.now() + timedelta(days=1)).isoformat()
            return {
                'title': title,
                'type': 'article',
                'description': f'工作流自动排期 - {brand}',
                'keywords': wf.get('keywords', []),
                'platforms': wf.get('platforms', ['website_blog']),
                'priority': 'medium',
                'planned_date': tomorrow,
                'geo_optimized': True,
                'assigned_to': task_id,
            }

        elif stage_id == 'publish':
            # 发布任务 - 真实立即执行（execute_now=True）
            gen_artifact = artifacts.get('content_generation', {})
            opt_artifact = artifacts.get('content_optimization', {})
            content = ''
            # 优先用优化后的内容
            if isinstance(opt_artifact, dict):
                content = (opt_artifact.get('optimized_text')
                           or opt_artifact.get('optimized_content')
                           or opt_artifact.get('content') or '')
            if not content and isinstance(gen_artifact, dict):
                content = gen_artifact.get('content') or gen_artifact.get('full_content') or ''

            title = f'{brand} GEO内容'
            if isinstance(gen_artifact, dict):
                title = gen_artifact.get('title') or title

            # 注入预生成的图片（content_optimization 阶段后已生成）
            images = artifacts.get('images', [])

            return {
                'content_type': 'article',
                'title': title,
                'content': content or f'{brand}是{industry}领域的专业品牌',
                'keywords': wf.get('keywords', []),
                'platforms': wf.get('platforms', ['website_blog']),
                'images': images,  # 注入预生成的图片
                'execute_now': True,  # 真实立即发布
            }

        elif stage_id == 'monitoring':
            # 启动 AI 引用率检测
            return {
                'platforms': ['chatgpt'],
                'brand_name': brand,
                'batch_name': f'工作流自动检测_{datetime.now().strftime("%Y%m%d_%H%M")}',
            }

        return {}

    def get_status(self, wf_id: str) -> Dict:
        """获取工作流状态"""
        wf = workflow_state.get(wf_id)
        if not wf:
            return {'success': False, 'error': '工作流不存在'}

        # 计算进度
        total = len(WORKFLOW_STAGES)
        completed = sum(1 for s in wf['stages'].values() if s.get('status') == 'completed')
        progress = int(completed / total * 100) if total > 0 else 0

        # 构造阶段列表（带顺序）
        stages_list = []
        for s in WORKFLOW_STAGES:
            stage_state = wf['stages'].get(s['id'], {})
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
                'brand_name': wf['brand_name'],
                'industry': wf['industry'],
                'status': wf['status'],
                'current_stage': wf['current_stage'],
                'progress': progress,
                'completed_stages': completed,
                'total_stages': total,
                'started_at': wf['started_at'],
                'completed_at': wf['completed_at'],
                'error': wf['error'],
                'stages': stages_list,
                'artifacts': wf.get('artifacts', {}),
            }
        }

    def list_workflows(self, limit: int = 20) -> Dict:
        """列出所有工作流"""
        items = workflow_state.list_all(limit)
        # 为每个工作流计算进度
        workflows = []
        for wf in items:
            total = len(WORKFLOW_STAGES)
            completed = sum(1 for s in wf['stages'].values() if s.get('status') == 'completed')
            workflows.append({
                'id': wf['id'],
                'brand_name': wf['brand_name'],
                'status': wf['status'],
                'progress': int(completed / total * 100) if total > 0 else 0,
                'current_stage': wf['current_stage'],
                'started_at': wf['started_at'],
                'completed_at': wf['completed_at'],
            })
        return {'success': True, 'workflows': workflows, 'total': len(workflows)}

    def execute_stage(self, wf_id: str, stage_id: str, token: str = None) -> Dict:
        """手动执行单个阶段"""
        wf = workflow_state.get(wf_id)
        if not wf:
            return {'success': False, 'error': '工作流不存在'}

        stage = self._get_stage_by_id(stage_id)
        if not stage:
            return {'success': False, 'error': '阶段不存在'}

        workflow_state.update_stage(wf_id, stage_id, {
            'status': 'running',
            'started_at': datetime.now().isoformat(),
        })

        result = self._execute_stage(wf_id, stage, token)
        if result.get('success'):
            workflow_state.update_stage(wf_id, stage_id, {
                'status': 'completed',
                'completed_at': datetime.now().isoformat(),
                'result': result.get('data'),
            })
            # 自动推进 current_stage
            workflow_state.update(wf_id, {'current_stage': stage['next_stage']})
        else:
            workflow_state.update_stage(wf_id, stage_id, {
                'status': 'failed',
                'completed_at': datetime.now().isoformat(),
                'error': result.get('error'),
            })

        return result

    def resume_workflow(self, wf_id: str, token: str = None) -> Dict:
        """恢复工作流（从当前阶段继续）"""
        wf = workflow_state.get(wf_id)
        if not wf:
            return {'success': False, 'error': '工作流不存在'}

        if not wf['current_stage']:
            return {'success': False, 'error': '工作流已完成'}

        t = threading.Thread(target=self._run_workflow_async,
                             args=(wf_id, token), daemon=True)
        t.start()
        return {'success': True, 'message': '工作流已恢复执行'}


# 全局引擎实例
workflow_engine = GEOWorkflowEngine()
