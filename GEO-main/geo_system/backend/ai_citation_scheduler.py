"""
AI 引用率定时检测调度器
- 每日固定时间自动执行批量检测
- 使用 monitoring_service 的 batch_check_citation 方法
- 参照 cookie_refresher.py 的实现模式
"""

import logging
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 默认每日凌晨 3 点执行（避开业务高峰）
DEFAULT_CHECK_HOUR = 3
# 每 24 小时一次
CHECK_INTERVAL_SECONDS = 24 * 3600


class AICitationScheduler:
    """AI 引用率定时检测调度器"""

    def __init__(self, monitoring_service=None):
        self.monitoring_service = monitoring_service
        self.running = False
        self.thread = None
        # 默认配置（可被 update_config 覆盖）
        self.brand_name = '织然家具'
        self.platforms = ['chatgpt']
        self.enabled = True  # 总开关

    def set_monitoring_service(self, service):
        self.monitoring_service = service
        logger.info("[AICitationScheduler] 已注入 monitoring_service")

    def update_config(self, brand_name=None, platforms=None, enabled=None):
        """更新调度配置"""
        if brand_name is not None:
            self.brand_name = brand_name
        if platforms is not None:
            self.platforms = platforms
        if enabled is not None:
            self.enabled = enabled
        logger.info(
            f"[AICitationScheduler] 配置已更新: enabled={self.enabled}, "
            f"brand={self.brand_name}, platforms={self.platforms}"
        )

    def start(self):
        """启动定时调度"""
        if self.running:
            return
        self.running = True

        def run_schedule():
            while self.running:
                # 计算到下一个凌晨 3 点的等待时间
                next_run = self._next_run_time()
                wait_seconds = (next_run - datetime.now()).total_seconds()
                if wait_seconds < 0:
                    wait_seconds = CHECK_INTERVAL_SECONDS

                # 分段等待，便于响应 stop()
                waited = 0
                while self.running and waited < wait_seconds:
                    time.sleep(60)
                    waited += 60

                if not self.running:
                    break

                if not self.enabled:
                    logger.info("[AICitationScheduler] 调度已禁用，跳过本次执行")
                    continue

                try:
                    self._run_batch_check()
                except Exception as e:
                    logger.error(f"[AICitationScheduler] 定时检测出错: {e}")

        self.thread = threading.Thread(target=run_schedule)
        self.thread.daemon = True
        self.thread.start()
        logger.info(
            f"[AICitationScheduler] 定时检测已启动，每日 {DEFAULT_CHECK_HOUR}:00 执行，"
            f"品牌={self.brand_name}，平台={self.platforms}"
        )

    def _next_run_time(self) -> datetime:
        """计算下次运行时间"""
        now = datetime.now()
        next_run = now.replace(hour=DEFAULT_CHECK_HOUR, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

    def _run_batch_check(self):
        """执行一次批量检测"""
        if not self.monitoring_service:
            logger.warning("[AICitationScheduler] monitoring_service 未注入，跳过")
            return

        batch_name = f"scheduled_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"[AICitationScheduler] 开始定时检测: {batch_name}")

        result = self.monitoring_service.batch_check_citation(
            keywords=None,  # 使用数据库中所有 active 关键词
            platforms=self.platforms,
            brand_name=self.brand_name,
            batch_name=batch_name
        )

        if result.get('success'):
            logger.info(
                f"[AICitationScheduler] 定时检测完成: batch_id={result.get('batch_id')}, "
                f"总查询={result.get('total_queries')}, "
                f"被引用={result.get('mentioned_count')}, "
                f"引用率={result.get('citation_rate')}%"
            )
        else:
            logger.error(f"[AICitationScheduler] 定时检测失败: {result.get('error')}")

    def run_now(self) -> dict:
        """立即执行一次（手动触发）"""
        if not self.monitoring_service:
            return {'success': False, 'error': 'monitoring_service 未注入'}
        return self._run_batch_check_return()

    def _run_batch_check_return(self) -> dict:
        """执行批量检测并返回结果"""
        if not self.monitoring_service:
            return {'success': False, 'error': 'monitoring_service 未注入'}

        batch_name = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return self.monitoring_service.batch_check_citation(
            keywords=None,
            platforms=self.platforms,
            brand_name=self.brand_name,
            batch_name=batch_name
        )

    def stop(self):
        """停止调度"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("[AICitationScheduler] 已停止")


# 全局单例
ai_citation_scheduler = AICitationScheduler()
