# -*- coding: utf-8 -*-
"""
多平台发布编排器

迁移自 GEO-main 的 PublishService + ActivePublishService，重构为：
1. 异步原生（去除 GEO 中的 asyncio.run() 同步包装）
2. Cookie 池轮换（账号失败自动切换下一个）
3. 内容风控预检测（基于 content_adapter.moderate_content）
4. 多平台并行分发（asyncio.gather）+ 单平台失败不影响其他
5. 失败重试（基于 BasePublisher.is_retryable_error 判断）

设计：
- 输入：PublishTask（标题/正文/图片/视频/目标平台列表）
- 输出：更新后的 PublishTask（含每个平台的 PublishResult）
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from .account_service import PlatformAccountService, get_account_service
from .base_publisher import BasePublisher, classify_publish_error
from .content_adapter import adapt_for_platform
from .exceptions import LoginExpiredError
from .publish_task import PublishErrorCode, PublishResult, PublishStatus, PublishTask
from .publisher_factory import PublisherFactory

logger = logging.getLogger(__name__)


# 单平台最大重试次数（每次切换不同账号）
MAX_RETRIES_PER_PLATFORM = 2
# 平台并行并发上限（避免浏览器实例过多导致 OOM）
MAX_CONCURRENT_PLATFORMS = 3


def _parse_result_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class MultiPlatformPublisher:
    """多平台发布编排器"""

    def __init__(
        self,
        account_service: Optional[PlatformAccountService] = None,
        max_concurrent: int = MAX_CONCURRENT_PLATFORMS,
    ):
        self.account_service = account_service or get_account_service()
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def publish_to_multiple_platforms(
        self,
        task: PublishTask,
        *,
        adapt_content: bool = True,
        enforce_moderation: bool = False,
    ) -> PublishTask:
        """多平台并行发布

        Args:
            task: 发布任务（含目标平台列表）
            adapt_content: 是否按平台适配内容（标题截断 / hashtag 风格）
            enforce_moderation: 是否强制风控（命中敏感词时跳过发布）

        Returns:
            更新后的 task（含每个平台的 platform_results）
        """
        if not task.target_platforms:
            task.error_message = "未指定目标平台"
            task.status = PublishStatus.FAILED
            return task

        task.task_id = task.task_id or str(uuid.uuid4())
        task.status = PublishStatus.PUBLISHING
        task.created_at = task.created_at or datetime.utcnow()

        logger.info(
            f"[MultiPublisher] 开始多平台发布 task={task.task_id} "
            f"platforms={task.target_platforms}"
        )

        # 审计日志：发布开始（P1-6）
        try:
            from api.services.utils.audit_log import (
                get_audit_log_service, AuditActionType,
            )
            await get_audit_log_service().log(
                action_type=AuditActionType.PUBLISH.value,
                user_id=task.user_id,
                platform=",".join(task.target_platforms),
                target=task.task_id,
                description=f"开始多平台发布: {task.title[:50]}",
                request_data={
                    "task_id": task.task_id,
                    "platforms": task.target_platforms,
                    "title": task.title,
                },
                status="started",
            )
        except Exception as e:
            logger.warning(f"[MultiPublisher] 记录发布开始审计日志失败: {e}")

        # 并行分发到各平台
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(
                    self._publish_to_one_platform_with_sem(
                        task, platform, adapt_content, enforce_moderation
                    )
                )
                for platform in task.target_platforms
                if PublisherFactory.is_supported(platform)
            ]

        # 汇总结果
        success_count = sum(1 for r in task.platform_results.values() if r.success)
        failed_count = len(task.platform_results) - success_count

        if success_count == 0:
            task.status = PublishStatus.FAILED
            task.error_message = f"所有平台发布失败（{failed_count} 个）"
        elif failed_count > 0:
            task.status = PublishStatus.PARTIAL
            task.error_message = f"{success_count} 个平台成功，{failed_count} 个失败"
        else:
            task.status = PublishStatus.SUCCESS

        task.published_at = datetime.utcnow()
        logger.info(
            f"[MultiPublisher] 发布完成 task={task.task_id} "
            f"status={task.status.value} success={success_count} failed={failed_count}"
        )

        # 审计日志：发布结果（成功 / 部分成功 / 失败）（P1-6）
        try:
            from api.services.utils.audit_log import (
                get_audit_log_service, AuditActionType,
            )
            audit_status = "success"
            if task.status == PublishStatus.FAILED:
                audit_status = "failed"
            elif task.status == PublishStatus.PARTIAL:
                audit_status = "partial"
            await get_audit_log_service().log(
                action_type=AuditActionType.PUBLISH.value,
                user_id=task.user_id,
                platform=",".join(task.target_platforms),
                target=task.task_id,
                description=(
                    f"发布完成: status={task.status.value} "
                    f"success={success_count} failed={failed_count}"
                ),
                request_data={"task_id": task.task_id},
                response_data={
                    "status": task.status.value,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "platform_results": {
                        pf: {"success": r.success, "error": r.error}
                        for pf, r in task.platform_results.items()
                    },
                },
                status=audit_status,
                error_message=task.error_message if audit_status != "success" else "",
            )
        except Exception as e:
            logger.warning(f"[MultiPublisher] 记录发布结果审计日志失败: {e}")

        return task

    async def publish_to_single_platform(
        self,
        platform: str,
        title: str,
        content: str,
        images: Optional[List[str]] = None,
        video_path: Optional[str] = None,
        user_id: int = 1,
        skip_publish_record: bool = False,
        **kwargs,
    ) -> PublishResult:
        """单平台发布（带 Cookie 池轮换 + 重试）

        :param skip_publish_record: 跳过 _save_publish_record（流水线调用时由 Step 6.1 统一写记录，避免重复）
        """
        if not PublisherFactory.is_supported(platform):
            return PublishResult(
                success=False,
                platform=platform,
                error=f"不支持的平台: {platform}",
                retryable=False,
            ).finalize()

        task = PublishTask(
            title=title,
            content=content,
            images=images or [],
            video_path=video_path,
            target_platforms=[platform],
            user_id=user_id,
            task_id=str(uuid.uuid4()),
        )
        # 标记是否跳过内部 publish_records 写入（流水线场景由 Step 6.1 统一写）
        task.skip_publish_record = skip_publish_record  # type: ignore[attr-defined]

        await self._publish_to_one_platform_with_sem(
            task, platform, adapt_content=True, enforce_moderation=False, **kwargs
        )
        return task.platform_results.get(platform, PublishResult(
            success=False, platform=platform, error="未知错误"
        ))

    # ==================== 内部方法 ====================

    async def _publish_to_one_platform_with_sem(
        self,
        task: PublishTask,
        platform: str,
        adapt_content: bool,
        enforce_moderation: bool,
        **kwargs,
    ):
        """带并发信号量的单平台发布"""
        async with self._semaphore:
            try:
                result = await self._publish_to_one_platform(
                    task, platform, adapt_content, enforce_moderation, **kwargs
                )
            except Exception as e:
                logger.exception(f"[MultiPublisher][{platform}] 发布异常")
                result = PublishResult(
                    success=False,
                    platform=platform,
                    error=f"发布异常: {e}",
                )
            if not result.success and not result.error_code:
                result.error_code = classify_publish_error(
                    result.error_message or result.error
                ).value
            result.finalize(task_id=task.task_id)
            task.platform_results[platform] = result
            # ===== 持久化即时发布记录（任务 P2-1，无论成功/失败/跳过） =====
            # 流水线场景由 Step 6.1 统一写记录，跳过避免重复
            if not getattr(task, 'skip_publish_record', False):
                await self._save_publish_record(task, platform, result)
            # ===== 合规归档（任务 P2-9，无论成功/失败） =====
            await self._archive_publish(task, platform, result)
            return result

    async def _save_publish_record(
        self,
        task: PublishTask,
        platform: str,
        result: PublishResult,
    ) -> None:
        """写入 publish_records 表（任务 P2-1），容错：失败仅 log warning"""
        try:
            from .publish_records_store import get_publish_records_store
            store = get_publish_records_store()

            # 状态映射：success / failed / skipped
            if result.success:
                status = "success"
            elif result.error and "quota_exceeded" in result.error:
                status = "skipped"
            else:
                status = "failed"

            await store.save_record(
                task_id=task.task_id,
                platform=platform,
                account_id=result.account_id,
                title=task.title,
                content=task.content,
                video_path=task.video_path,
                post_url=result.url,
                platform_id=result.platform_id,
                status=status,
                error_code=result.error_code,
                error_message=result.error,
                retryable=result.retryable,
                started_at=_parse_result_time(result.started_at),
                finished_at=_parse_result_time(result.finished_at),
                owner_user_id=task.user_id,
                source_post_id=task.source_post_id or None,
                metadata={
                    "retryable": result.retryable,
                    "error_code": result.error_code,
                    "started_at": result.started_at,
                    "finished_at": result.finished_at,
                    "message": result.message,
                    "status_detail": result.status,
                    "skipped_reason": (
                        "quota_exceeded"
                        if (not result.success and result.error and "quota_exceeded" in result.error)
                        else None
                    ),
                },
            )
        except Exception as e:
            logger.warning(
                f"[MultiPublisher][{platform}] 写 publish_records 失败(忽略): {e}"
            )

    async def _archive_publish(
        self,
        task: PublishTask,
        platform: str,
        result: PublishResult,
    ) -> None:
        """合规归档发布记录到 compliance_archive（任务 P2-9）

        容错：失败仅 log warning，不阻断主流程。
        避免循环依赖：compliance_archive 不反向依赖 publisher。
        """
        try:
            from api.services.moderation.compliance_archive import (
                ArchiveType,
                get_compliance_archive_service,
            )
            # 状态映射
            if result.success:
                status = "success"
            elif result.error and "quota_exceeded" in result.error:
                status = "skipped"
            else:
                status = "failed"
            await get_compliance_archive_service().archive(
                archive_type=ArchiveType.PUBLISH.value,
                platform=platform,
                account_id=str(result.account_id) if result.account_id else "",
                target_url=result.url or "",
                content=f"{task.title}\n{task.content}",
                metadata={
                    "task_id": task.task_id,
                    "video_path": task.video_path,
                    "images_count": len(task.images or []),
                    "status": status,
                    "error": result.error,
                    "platform_id": result.platform_id,
                    "retryable": result.retryable,
                    "source_post_id": task.source_post_id,
                },
                owner_user_id=task.user_id,
            )
        except Exception as e:
            logger.warning(
                f"[MultiPublisher][{platform}] 合规归档失败(忽略): {e}"
            )

    async def _publish_to_one_platform(
        self,
        task: PublishTask,
        platform: str,
        adapt_content: bool,
        enforce_moderation: bool,
        **kwargs,
    ) -> PublishResult:
        """单平台发布（含风控检测 + Cookie 池轮换 + 重试）"""
        title = task.title
        content = task.content

        # 1. 内容适配
        if adapt_content:
            adapted = adapt_for_platform(title, content, platform, enforce_moderation=False)
            title = adapted["title"]
            content = adapted["content"]

            # 风控检测
            if not adapted["moderation_passed"]:
                if enforce_moderation:
                    return PublishResult(
                        success=False,
                        platform=platform,
                        error=f"内容风控未通过: {adapted['moderation_hits'][:3]}",
                        retryable=False,
                    )
                logger.warning(
                    f"[MultiPublisher][{platform}] 内容风控警告: {adapted['moderation_hits'][:3]}"
                )

        # 1.5 视频规格适配（按平台裁切/截断，P2-2）
        # 在重试循环外做一次，避免每次重试都重复转码
        video_path = task.video_path
        if video_path:
            try:
                from .video_adapter import VideoAdapter
                adapted_video = await VideoAdapter.adapt_video(video_path, platform)
                if adapted_video != video_path:
                    logger.info(
                        f"[MultiPublisher][{platform}] 视频已适配: "
                        f"{video_path} -> {adapted_video}"
                    )
                    video_path = adapted_video
            except Exception as e:
                logger.warning(
                    f"[MultiPublisher][{platform}] 视频适配异常，使用原视频: {e}"
                )
                video_path = task.video_path

        # 2. Cookie 池轮换重试
        last_error = None
        for attempt in range(MAX_RETRIES_PER_PLATFORM + 1):
            # 获取账号
            account = await self.account_service.acquire_cookie(
                platform=platform, user_id=task.user_id or 1
            )
            if account is None:
                return PublishResult(
                    success=False,
                    platform=platform,
                    error="无可用账号（全部冷却或配额耗尽）",
                    error_code=PublishErrorCode.NO_AVAILABLE_ACCOUNT.value,
                    retryable=False,
                )

            # ===== 频次硬限制校验（任务 P1-7）=====
            try:
                from api.services.risk_control.quota_config import (
                    get_quota_config_service,
                )
                quota_svc = get_quota_config_service()
                quota_result = await quota_svc.check_publish_quota(
                    platform=platform,
                    account_id=str(account.id),
                    owner_user_id=task.user_id,
                )
                if not quota_result.allowed:
                    logger.warning(
                        f"[MultiPublisher][{platform}] 发布配额拒绝: {quota_result.reason}"
                    )
                    # 账号未被使用，不需要 mark_failure
                    return PublishResult(
                        success=False,
                        platform=platform,
                        error=f"quota_exceeded: {quota_result.reason}",
                        error_code=PublishErrorCode.QUOTA_EXCEEDED.value,
                        retryable=False,
                        account_id=account.id,
                    )
            except Exception as e:
                logger.warning(
                    f"[MultiPublisher][{platform}] 配额校验异常(忽略，继续发布): {e}"
                )

            # 创建 Publisher
            try:
                publisher = PublisherFactory.create(
                    platform=platform,
                    cookies=account.cookies,
                    user_id=account.user_id,
                )
            except ValueError as e:
                return PublishResult(
                    success=False,
                    platform=platform,
                    error=str(e),
                    retryable=False,
                )

            # 发布
            try:
                result = await publisher.publish(
                    title=title,
                    content=content,
                    images=task.images,
                    video_path=video_path,
                    task_id=task.task_id,
                    **kwargs,
                )
                result.account_id = account.id

                # ===== 记录配额使用（任务 P1-7，容错） =====
                try:
                    from api.services.risk_control.quota_config import (
                        get_quota_config_service,
                    )
                    await get_quota_config_service().record_usage(
                        platform=platform,
                        account_id=str(account.id),
                        action_type="publish",
                        target_url=result.url or "",
                        owner_user_id=task.user_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"[MultiPublisher][{platform}] record_usage 异常(忽略): {e}"
                    )

                # 反馈账号池
                if result.success:
                    await self.account_service.mark_success(account.id)
                    return result
                else:
                    if result.error_code == PublishErrorCode.AUTH_EXPIRED.value:
                        await self.account_service.mark_login_expired(account.id)
                    elif result.error_code in {
                        PublishErrorCode.RATE_LIMITED.value,
                        PublishErrorCode.CAPTCHA_REQUIRED.value,
                    }:
                        await self.account_service.mark_cooldown(
                            account.id, result.error_message or result.error or ""
                        )
                    else:
                        await self.account_service.mark_failure(
                            account.id, result.error_message or result.error or ""
                        )
                    last_error = result.error

                    # 不可重试错误：立即返回
                    if not result.retryable or not BasePublisher.is_retryable_error(result.error or ""):
                        return result

                    logger.info(
                        f"[MultiPublisher][{platform}] 第 {attempt + 1} 次失败，"
                        f"准备切换账号重试: {result.error}"
                    )

            except LoginExpiredError as e:
                await self.account_service.mark_login_expired(account.id)
                last_error = str(e)
                logger.info(f"[MultiPublisher][{platform}] 账号登录失效，切换账号")
                # 登录失效也记一次使用，避免被反复重试占满配额
                try:
                    from api.services.risk_control.quota_config import (
                        get_quota_config_service,
                    )
                    await get_quota_config_service().record_usage(
                        platform=platform,
                        account_id=str(account.id),
                        action_type="publish",
                        target_url="",
                        owner_user_id=task.user_id,
                    )
                except Exception as e2:
                    logger.warning(
                        f"[MultiPublisher][{platform}] record_usage 异常(忽略): {e2}"
                    )
            except Exception as e:
                await self.account_service.mark_failure(account.id, str(e))
                last_error = str(e)
                logger.exception(f"[MultiPublisher][{platform}] 发布异常")
                # 发布异常也记一次使用
                try:
                    from api.services.risk_control.quota_config import (
                        get_quota_config_service,
                    )
                    await get_quota_config_service().record_usage(
                        platform=platform,
                        account_id=str(account.id),
                        action_type="publish",
                        target_url="",
                        owner_user_id=task.user_id,
                    )
                except Exception as e2:
                    logger.warning(
                        f"[MultiPublisher][{platform}] record_usage 异常(忽略): {e2}"
                    )

        # 所有账号重试均失败 → 发送发布失败预警到 alert_center
        try:
            from api.services.alert.alert_center import emit_publish_failure
            await emit_publish_failure(
                platform=platform,
                account_label=f"task_id={task.task_id or 'N/A'}" if task else platform,
                error_message=f"已重试 {MAX_RETRIES_PER_PLATFORM} 次仍失败: {last_error}",
                content_preview=(task.content or "")[:200] if task else "",
                post_id=task.source_post_id if task else "",
                owner_user_id=task.user_id if task else None,
            )
        except Exception as ae:
            logger.warning(f"[MultiPublisher][{platform}] 发送发布失败预警异常(忽略): {ae}")

        return PublishResult(
            success=False,
            platform=platform,
            error=f"已重试 {MAX_RETRIES_PER_PLATFORM} 次仍失败: {last_error}",
            retryable=False,
        )


# 模块级单例
_multi_publisher: Optional[MultiPlatformPublisher] = None


def get_multi_publisher() -> MultiPlatformPublisher:
    """获取 MultiPlatformPublisher 单例"""
    global _multi_publisher
    if _multi_publisher is None:
        _multi_publisher = MultiPlatformPublisher()
    return _multi_publisher
