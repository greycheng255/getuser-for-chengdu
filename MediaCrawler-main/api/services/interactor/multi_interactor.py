# -*- coding: utf-8 -*-
"""
多平台互动编排器

与 multi_publisher.py 对齐，支持：
1. 单互动类型多平台并行执行（如同一帖子在 5 个平台都点赞）
2. asyncio.Semaphore 控制并发（避免浏览器实例过多）
3. 单平台失败不影响其他平台
4. 集成 account_service 获取 Cookie 池
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from .interaction_models import (
    InteractionResult,
    InteractionStatus,
    InteractionTask,
    InteractionType,
)
from .interactor_factory import InteractorFactory

logger = logging.getLogger(__name__)


def _get_engine():
    """获取异步数据库引擎（公共方法，消除重复导入）"""
    from database.db_session import get_async_engine
    import config
    return get_async_engine(config.SAVE_DATA_OPTION)


# 并发互动的平台数上限（避免同时开太多浏览器）
_DEFAULT_CONCURRENCY = 3


class MultiInteractor:
    """多平台互动编排器"""

    def __init__(self, max_concurrency: int = _DEFAULT_CONCURRENCY):
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def interact_across_platforms(
        self,
        task: InteractionTask,
        *,
        use_account_pool: bool = True,
    ) -> InteractionTask:
        """跨平台执行同一互动

        Args:
            task: 互动任务（target_platforms 指定目标平台）
            use_account_pool: 是否从 account_service 获取 Cookie（False 则需任务自带 cookies）
        """
        task.status = InteractionStatus.PENDING
        task.created_at = task.created_at or datetime.utcnow()
        if not task.task_id:
            task.task_id = str(uuid.uuid4())[:8]

        async def _run_one(platform: str):
            async with self._semaphore:
                return await self._interact_on_one(
                    platform, task, use_account_pool=use_account_pool
                )

        platforms = [
            p for p in task.target_platforms if InteractorFactory.is_supported(p)
        ]
        if not platforms:
            task.status = InteractionStatus.FAILED
            task.error_message = "无支持的目标平台"
            return task

        results = await asyncio.gather(
            *[_run_one(p) for p in platforms], return_exceptions=True
        )

        for platform, res in zip(platforms, results):
            if isinstance(res, Exception):
                task.platform_results[platform] = InteractionResult(
                    success=False,
                    platform=platform,
                    interaction_type=task.interaction_type,
                    target_url=task.target_url,
                    error=f"编排异常: {res}",
                    retryable=False,
                )
            else:
                task.platform_results[platform] = res

        # 汇总状态
        successes = sum(1 for r in task.platform_results.values() if r.success)
        total = len(task.platform_results)
        if successes == total:
            task.status = InteractionStatus.SUCCESS
        elif successes == 0:
            task.status = InteractionStatus.FAILED
        else:
            task.status = InteractionStatus.FAILED  # 部分成功也算 failed（上层可看明细）
        task.completed_at = datetime.utcnow()

        # 审计日志：互动执行结果（P1-6）
        try:
            from api.services.utils.audit_log import (
                get_audit_log_service, AuditActionType,
            )
            audit_status = "success" if task.status == InteractionStatus.SUCCESS else "failed"
            await get_audit_log_service().log(
                action_type=AuditActionType.INTERACTION.value,
                user_id=task.user_id,
                platform=",".join(task.target_platforms),
                target=task.target_url or task.task_id,
                description=(
                    f"互动执行: type={task.interaction_type} "
                    f"success={successes}/{total}"
                ),
                request_data={
                    "task_id": task.task_id,
                    "interaction_type": task.interaction_type,
                    "target_url": task.target_url,
                    "platforms": task.target_platforms,
                },
                response_data={
                    "status": task.status.value,
                    "successes": successes,
                    "total": total,
                    "platform_results": {
                        pf: {"success": r.success, "error": r.error}
                        for pf, r in task.platform_results.items()
                    },
                },
                status=audit_status,
                error_message=task.error_message if audit_status != "success" else "",
            )
        except Exception as e:
            logger.warning(f"[MultiInteractor] 记录互动审计日志失败: {e}")

        return task

    async def _interact_on_one(
        self,
        platform: str,
        task: InteractionTask,
        *,
        use_account_pool: bool,
    ) -> InteractionResult:
        """在单个平台执行互动"""
        cookies = ""
        account_id = None
        try:
            if use_account_pool:
                from api.services.publisher.account_service import get_account_service

                account = await get_account_service().acquire_cookie(
                    platform, user_id=task.user_id or 1
                )
                if not account:
                    no_account_result = InteractionResult(
                        success=False,
                        platform=platform,
                        interaction_type=task.interaction_type,
                        target_url=task.target_url,
                        error=f"{platform} 无可用账号（请在「账号与互动 → 机器人账号」中添加 cookie）",
                        retryable=False,
                    )
                    # 即使无账号也持久化一条 skipped 记录，让前端可见
                    await self._record_interaction(
                        platform, task, no_account_result, None, status="skipped"
                    )
                    return no_account_result
                cookies = account.cookies
                account_id = account.id
            else:
                cookies = task.__dict__.get("cookies", "")

            # ===== 频次硬限制校验（任务 P1-7）=====
            quota_blocked = False
            try:
                from api.services.risk_control.quota_config import (
                    get_quota_config_service,
                )
                quota_svc = get_quota_config_service()
                quota_result = await quota_svc.check_interaction_quota(
                    platform=platform,
                    account_id=str(account_id) if account_id is not None else "",
                    interaction_type=task.interaction_type,
                    owner_user_id=task.user_id,
                )
                if not quota_result.allowed:
                    quota_blocked = True
                    logger.warning(
                        f"[MultiInteractor][{platform}] 互动配额拒绝: {quota_result.reason}"
                    )
                    skipped = InteractionResult(
                        success=False,
                        platform=platform,
                        interaction_type=task.interaction_type,
                        target_url=task.target_url,
                        error=f"quota_exceeded: {quota_result.reason}",
                        account_id=account_id,
                        retryable=False,
                    )
                    # 仍持久化一条 skipped 记录
                    await self._record_interaction(
                        platform, task, skipped, account_id, status="skipped"
                    )
                    return skipped
            except Exception as e:
                logger.warning(
                    f"[MultiInteractor][{platform}] 配额校验异常(忽略，继续执行): {e}"
                )

            interactor = InteractorFactory.create(
                platform, cookies=cookies, user_id=task.user_id
            )

            itype = InteractionType(task.interaction_type)
            if itype == InteractionType.LIKE:
                result = await interactor.like(task.target_url)
            elif itype == InteractionType.COMMENT:
                result = await interactor.comment(task.target_url, task.content)
            elif itype == InteractionType.REPLY:
                result = await interactor.reply(
                    task.target_url, task.target_id, task.content
                )
            elif itype == InteractionType.FOLLOW:
                result = await interactor.follow(task.target_url)
            else:
                return InteractionResult(
                    success=False,
                    platform=platform,
                    interaction_type=task.interaction_type,
                    error=f"不支持的互动类型: {task.interaction_type}",
                    retryable=False,
                )

            result.account_id = account_id
            result.timestamp = datetime.utcnow().isoformat()

            # 回写账号状态
            if use_account_pool and account_id is not None:
                from api.services.publisher.account_service import get_account_service

                if result.success:
                    await get_account_service().mark_success(account_id)
                else:
                    await get_account_service().mark_failure(account_id, result.error or "")

            # ===== 记录配额使用（任务 P1-7，容错） =====
            if not quota_blocked:
                try:
                    from api.services.risk_control.quota_config import (
                        get_quota_config_service,
                    )
                    await get_quota_config_service().record_usage(
                        platform=platform,
                        account_id=str(account_id) if account_id is not None else "",
                        action_type="interaction",
                        target_url=task.target_url,
                        owner_user_id=task.user_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"[MultiInteractor][{platform}] record_usage 异常(忽略): {e}"
                    )

            # ===== 持久化互动记录（任务 P1-5） =====
            await self._record_interaction(platform, task, result, account_id)

            return result
        except Exception as e:
            logger.exception(f"[{platform}] 互动执行异常")
            err_result = InteractionResult(
                success=False,
                platform=platform,
                interaction_type=task.interaction_type,
                target_url=task.target_url,
                error=f"执行异常: {e}",
                account_id=account_id,
            )
            # 异常也写入记录，便于审计
            await self._record_interaction(
                platform, task, err_result, account_id, status="failed"
            )
            return err_result

    async def _record_interaction(
        self,
        platform: str,
        task: InteractionTask,
        result: InteractionResult,
        account_id: Optional[int],
        *,
        status: Optional[str] = None,
    ) -> None:
        """写入 multi_interaction_records 表（任务 P1-5）

        字段对齐 InteractionAnalyticsService.ensure_table 的定义。
        容错：写入失败仅记录 warning，不阻断主流程。
        """
        try:
            from sqlalchemy import text as sql_text

            engine = _get_engine()
            if engine is None:
                return

            # 推断状态：success / failed / skipped
            if status is None:
                status = "success" if result.success else "failed"

            interaction_id = f"int_{uuid.uuid4().hex[:16]}"
            now = datetime.utcnow()

            async with engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO multi_interaction_records "
                        "(interaction_id, task_id, platform, account_id, "
                        " interaction_type, target_url, target_id, content, "
                        " status, error, retry_count, owner_user_id, "
                        " created_at, completed_at) "
                        "VALUES (:iid, :tid, :pf, :aid, :itype, :turl, :tid2, "
                        "        :content, :st, :err, :rc, :ouid, :ca, :comp)"
                    ),
                    {
                        "iid": interaction_id,
                        "tid": task.task_id or "",
                        "pf": platform,
                        "aid": account_id,
                        "itype": task.interaction_type,
                        "turl": task.target_url or "",
                        "tid2": task.target_id or "",
                        "content": task.content or "",
                        "st": status,
                        "err": (result.error or "")[:1000] if result.error else None,
                        "rc": 0,
                        "ouid": task.user_id,
                        "ca": now,
                        "comp": now,
                    },
                )
        except Exception as e:
            logger.warning(
                f"[MultiInteractor][{platform}] 写 multi_interaction_records 失败(忽略): {e}"
            )

        # ===== 合规归档互动记录（任务 P2-9，无论成功/失败） =====
        # 容错：失败仅 log warning，不阻断主流程。
        # 避免循环依赖：compliance_archive 不反向依赖 interactor。
        try:
            from api.services.moderation.compliance_archive import (
                ArchiveType,
                get_compliance_archive_service,
            )
            await get_compliance_archive_service().archive(
                archive_type=ArchiveType.INTERACTION.value,
                platform=platform,
                account_id=str(account_id) if account_id else "",
                target_url=task.target_url,
                content=task.content or "",
                metadata={
                    "task_id": task.task_id,
                    "interaction_type": task.interaction_type,
                    "success": result.success,
                    "error": result.error,
                    "target_id": task.target_id,
                    "platform_target_id": result.target_id,
                    "status": status or ("success" if result.success else "failed"),
                    "retryable": result.retryable,
                },
                owner_user_id=task.user_id,
            )
        except Exception as arch_e:
            logger.warning(
                f"[MultiInteractor][{platform}] 合规归档失败(忽略): {arch_e}"
            )


# 单例
_multi_interactor: Optional[MultiInteractor] = None


def get_multi_interactor() -> MultiInteractor:
    global _multi_interactor
    if _multi_interactor is None:
        _multi_interactor = MultiInteractor()
    return _multi_interactor
