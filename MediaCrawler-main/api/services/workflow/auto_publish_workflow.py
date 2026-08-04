# -*- coding: utf-8 -*-
"""
自动化发布工作流（迁移自 GEO-main）

迁移自: GEO-main/geo_system/backend/auto_publish_workflow.py
对应 PRD 模块: 自动化发布工作流 - 每日内容自动生成 + 多平台分发

适配点:
1. 数据库: 无直接 DB 操作（通过 workflow_engine 间接持久化），
   服务账号等敏感配置走 os.environ.get。
2. 配置: 硬编码品牌信息 → 调用方传入 brand_info；AI 配置走环境变量。
3. 日志: print → logging.getLogger(__name__)。
4. 异步: 同步 schedule 库 → async def，由调用方（调度器/路由）驱动。
5. 服务依赖:
   - 原 ContentDistributionService / GEOOptimizationService →
     MediaCrawler 的 publisher + moderation 服务（通过 workflow_engine 编排）。
   - 原 ai_service → MediaCrawler 的 ..ai 服务（try/except 降级）。
6. 编排: 不再自行实现分发逻辑，而是调用 workflow_engine.start_workflow
   完成完整的"热点搜集→内容生成→...→多平台分发"闭环。
7. 单例: 文件末尾提供 get_auto_publish_workflow()。
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 依赖 workflow_engine 完成闭环编排
try:
    from .workflow_engine import get_workflow_engine, WORKFLOW_STAGES
    _workflow_engine_available = True
except Exception as _e:  # noqa: F841
    logger.warning(f"[AutoPublish] workflow_engine 模块不可用: {_e}")
    get_workflow_engine = None
    WORKFLOW_STAGES = []
    _workflow_engine_available = False

# AI 服务（内容生成/优化），可选
try:
    from ..ai import get_ai_service
    _ai_available = True
except Exception as _e:  # noqa: F841
    logger.warning(f"[AutoPublish] ai 模块不可用: {_e}")
    get_ai_service = None
    _ai_available = False


class AutoPublishWorkflow:
    """自动化发布工作流

    每日自动生成内容计划并发布到多平台。本类负责"内容计划生成"，
    实际发布委托给 workflow_engine 完成完整闭环（含审核/调度/统计）。
    """

    def __init__(self):
        # 默认平台列表可通过环境变量覆盖
        default_platforms = os.environ.get(
            "AUTO_PUBLISH_PLATFORMS",
            "xiaohongshu,zhihu,weibo",
        )
        self.default_platforms: List[str] = [
            p.strip() for p in default_platforms.split(",") if p.strip()
        ]
        # 每日内容计划条数
        self.daily_count = int(os.environ.get("AUTO_PUBLISH_DAILY_COUNT", "3"))

    async def run_daily_publish(self, brand_info: Dict) -> Dict[str, Any]:
        """每日自动发布流程

        Args:
            brand_info: 品牌信息（name/industry/products/target_audience/...）

        Returns:
            {
                'success': bool,
                'workflow_id': str,  # 启动的工作流 ID
                'content_plan': List[Dict],
                'message': str,
            }
        """
        logger.info(f"[{datetime.now()}] 开始每日自动发布流程...")

        # 1. 生成当日内容计划
        content_plan = await self.generate_daily_content_plan(brand_info)
        logger.info(f"[AutoPublish] 生成 {len(content_plan)} 条内容计划")

        # 2. 委托 workflow_engine 启动完整闭环工作流
        if not _workflow_engine_available or get_workflow_engine is None:
            logger.error("[AutoPublish] workflow_engine 不可用，无法启动发布")
            return {
                'success': False,
                'error': 'workflow_engine 不可用',
                'content_plan': content_plan,
            }

        brand_name = brand_info.get('name', '')
        industry = brand_info.get('industry', '')
        keywords = self._extract_keywords(brand_info, content_plan)
        platforms = self._extract_platforms(content_plan) or self.default_platforms

        engine = get_workflow_engine()
        result = await engine.start_workflow(
            brand_name=brand_name,
            industry=industry,
            keywords=keywords,
            platforms=platforms,
            auto_run=True,
        )

        logger.info(
            f"[{datetime.now()}] 每日发布流程已启动: workflow_id={result.get('workflow_id')}"
        )
        return {
            'success': result.get('success', False),
            'workflow_id': result.get('workflow_id'),
            'content_plan': content_plan,
            'message': result.get('message', '工作流已启动'),
        }

    async def generate_daily_content_plan(self, brand_info: Dict) -> List[Dict]:
        """生成每日内容计划

        优先使用 AI 生成，失败时降级为默认计划。
        """
        if _ai_available and get_ai_service is not None:
            try:
                ai_service = get_ai_service()
                prompt = self._build_content_plan_prompt(brand_info)
                method = getattr(ai_service, 'generate_content', None)
                if method is not None:
                    import asyncio
                    result = await method(prompt) if asyncio.iscoroutinefunction(method) else method(prompt)
                    content = result.get('content') if isinstance(result, dict) else result
                    if content:
                        return self.parse_content_plan(content)
            except Exception as e:
                logger.warning(f"[AutoPublish] AI 生成内容计划失败，降级默认: {e}")

        return self.get_default_content_plan(brand_info)

    def _build_content_plan_prompt(self, brand_info: Dict) -> str:
        """构造 AI 内容计划 prompt"""
        return f"""
为品牌"{brand_info.get('name', '')}"制定今日内容发布计划。

品牌信息:
- 行业: {brand_info.get('industry', '')}
- 产品: {brand_info.get('products', '')}
- 目标用户: {brand_info.get('target_audience', '')}

请生成 {self.daily_count} 个内容主题，覆盖以下平台: {", ".join(self.default_platforms)}

格式:
- 平台: [平台名]
- 类型: [article/faq/short]
- 主题: [具体内容主题]
- 关键词: [相关关键词]
"""

    def parse_content_plan(self, ai_content: str) -> List[Dict]:
        """解析 AI 生成的内容计划

        简化实现：按行解析"平台: xxx"格式的块。
        """
        plans: List[Dict] = []
        current: Optional[Dict] = None
        for line in (ai_content or '').splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('- 平台') or line.startswith('平台'):
                if current:
                    plans.append(current)
                current = {'platform': line.split(':', 1)[-1].strip(),
                           'type': 'article', 'topic': '', 'keywords': []}
            elif current is not None:
                if line.startswith('- 类型') or line.startswith('类型'):
                    current['type'] = line.split(':', 1)[-1].strip()
                elif line.startswith('- 主题') or line.startswith('主题'):
                    current['topic'] = line.split(':', 1)[-1].strip()
                elif line.startswith('- 关键词') or line.startswith('关键词'):
                    kws = line.split(':', 1)[-1].strip()
                    current['keywords'] = [k.strip() for k in kws.split(',') if k.strip()]
        if current:
            plans.append(current)
        # 兜底：解析失败则用默认
        if not plans:
            return self.get_default_content_plan({'name': ''})
        return plans[:self.daily_count]

    def get_default_content_plan(self, brand_info: Dict) -> List[Dict]:
        """获取默认内容计划"""
        name = brand_info.get('name', '')
        industry = brand_info.get('industry', '')
        return [
            {
                'platform': self.default_platforms[0] if self.default_platforms else 'zhihu',
                'type': 'article',
                'topic': f"{name}{industry}选购指南" if name else f"{industry}选购指南",
                'keywords': [industry, '选购指南', name] if name else [industry, '选购指南'],
            },
            {
                'platform': self.default_platforms[-1] if self.default_platforms else 'weibo',
                'type': 'short',
                'topic': f"{name}产品实测分享" if name else f"{industry}产品实测分享",
                'keywords': [name, '实测', industry] if name else ['实测', industry],
            },
        ]

    def _extract_keywords(self, brand_info: Dict, content_plan: List[Dict]) -> List[str]:
        """从品牌信息和内容计划中提取关键词"""
        keywords: List[str] = []
        for item in content_plan:
            keywords.extend(item.get('keywords', []))
        # 补充品牌名/行业作为种子词
        if brand_info.get('name'):
            keywords.append(brand_info['name'])
        if brand_info.get('industry'):
            keywords.append(brand_info['industry'])
        # 去重保序
        seen = set()
        unique = []
        for k in keywords:
            if k and k not in seen:
                seen.add(k)
                unique.append(k)
        return unique[:20]

    def _extract_platforms(self, content_plan: List[Dict]) -> List[str]:
        """从内容计划中提取去重后的平台列表"""
        seen = set()
        platforms: List[str] = []
        for item in content_plan:
            p = item.get('platform')
            if p and p not in seen:
                seen.add(p)
                platforms.append(p)
        return platforms


class KnowledgeBaseSubmission:
    """向 AI 知识库提交品牌信息

    保留原 GEO 的提交策略说明（大部分 AI 平台无公开提交 API，
    需通过内容生态建设被收录）。本类仅提供策略指导，不做实际网络请求。
    """

    def __init__(self):
        # 提交策略文档可通过环境变量覆盖路径
        self.instructions_path = os.environ.get(
            "KB_SUBMISSION_INSTRUCTIONS_PATH", ""
        )

    async def submit_to_ai_platforms(self, brand_info: Dict) -> Dict:
        """向各 AI 平台提交品牌信息（返回策略指导）

        Returns:
            {platform: {method, status, instructions}}
        """
        results = {
            'baidu': self._submit_to_baidu(brand_info),
            'bytedance': self._submit_to_bytedance(brand_info),
            'alibaba': self._submit_to_alibaba(brand_info),
        }
        logger.info(
            f"[KB] 品牌知识库提交策略已生成: brand={brand_info.get('name', '')}, "
            f"platforms={list(results.keys())}"
        )
        return results

    def _submit_to_baidu(self, brand_info: Dict) -> Dict:
        """百度 AI 知识库提交策略"""
        return {
            'platform': 'baidu',
            'method': '知识图谱提交',
            'status': '需要人工提交',
            'instructions': (
                '1. 访问百度知识图谱开放平台\n'
                '2. 注册并认证企业账号\n'
                f'3. 提交品牌实体信息: {brand_info.get("name", "")}\n'
                '4. 等待审核收录'
            ),
        }

    def _submit_to_bytedance(self, brand_info: Dict) -> Dict:
        """字节跳动 AI 知识库提交策略"""
        return {
            'platform': 'bytedance',
            'method': '内容生态建设',
            'status': '通过内容被收录',
            'instructions': (
                '1. 在抖音、今日头条发布优质内容\n'
                '2. 使用品牌关键词和话题标签\n'
                '3. 获得用户互动和分享\n'
                '4. 内容会被豆包AI引用'
            ),
        }

    def _submit_to_alibaba(self, brand_info: Dict) -> Dict:
        """阿里 AI 知识库提交策略"""
        return {
            'platform': 'alibaba',
            'method': '通义千问知识增强',
            'status': '通过高质量内容',
            'instructions': (
                '1. 在淘宝、天猫建立品牌旗舰店\n'
                '2. 完善商品详情和品牌故事\n'
                '3. 积累用户评价和问答\n'
                '4. 信息会被通义千问收录'
            ),
        }


# ============ 单例 ============
_auto_publish_workflow: Optional[AutoPublishWorkflow] = None
_kb_submission: Optional[KnowledgeBaseSubmission] = None


def get_auto_publish_workflow() -> AutoPublishWorkflow:
    """获取自动化发布工作流单例"""
    global _auto_publish_workflow
    if _auto_publish_workflow is None:
        _auto_publish_workflow = AutoPublishWorkflow()
    return _auto_publish_workflow


def get_kb_submission_service() -> KnowledgeBaseSubmission:
    """获取知识库提交服务单例"""
    global _kb_submission
    if _kb_submission is None:
        _kb_submission = KnowledgeBaseSubmission()
    return _kb_submission
