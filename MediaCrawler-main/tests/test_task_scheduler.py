# -*- coding: utf-8 -*-
"""定时任务调度测试

覆盖 PRD §10.7.3:支持 once/daily/weekly 三种调度模式。

测试场景:
1. _calc_next_scheduled_ts daily 模式时间计算
2. _calc_next_scheduled_ts weekly 模式时间计算
3. schedule_task_now 辅助函数
4. 调度器启动/停止控制
"""
import asyncio
import pytest
from datetime import datetime, timedelta


@pytest.mark.asyncio
async def test_calc_next_scheduled_ts_daily():
    """daily 模式:今天未到指定时间返回今天,已过返回明天"""
    from api.services.task_scheduler import _calc_next_scheduled_ts

    now = datetime(2025, 1, 15, 8, 0, 0)
    now_ts = int(now.timestamp())

    # 今天 9:00 还没到,返回今天 9:00
    next_ts = _calc_next_scheduled_ts("daily", "09:00", 1, now_ts)
    expected = now.replace(hour=9, minute=0, second=0, microsecond=0)
    assert next_ts == int(expected.timestamp())

    # 今天 10:00 已过,返回明天 9:00
    now_late = datetime(2025, 1, 15, 10, 0, 0)
    next_ts = _calc_next_scheduled_ts("daily", "09:00", 1, int(now_late.timestamp()))
    expected = (now_late + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    assert next_ts == int(expected.timestamp())


@pytest.mark.asyncio
async def test_calc_next_scheduled_ts_daily_invalid_time():
    """daily 模式:无效时间格式回退到 09:00"""
    from api.services.task_scheduler import _calc_next_scheduled_ts

    now = datetime(2025, 1, 15, 8, 0, 0)
    next_ts = _calc_next_scheduled_ts("daily", "invalid", 1, int(now.timestamp()))
    expected = now.replace(hour=9, minute=0, second=0, microsecond=0)
    assert next_ts == int(expected.timestamp())


@pytest.mark.asyncio
async def test_calc_next_scheduled_ts_weekly():
    """weekly 模式:计算本周指定星期的指定时间"""
    from api.services.task_scheduler import _calc_next_scheduled_ts

    # 周三(weekday=2),要执行周五(weekday=4)的任务
    now = datetime(2025, 1, 15, 10, 0, 0)  # 周三
    now_ts = int(now.timestamp())

    # 周五还没到,返回本周五 09:00
    next_ts = _calc_next_scheduled_ts("weekly", "09:00", 5, now_ts)
    expected = now + timedelta(days=2)  # 周五
    expected = expected.replace(hour=9, minute=0, second=0, microsecond=0)
    assert next_ts == int(expected.timestamp())

    # 周一(weekday=0),要执行上周六的任务(已过),返回下周周六
    now_monday = datetime(2025, 1, 20, 10, 0, 0)  # 周一
    next_ts = _calc_next_scheduled_ts("weekly", "09:00", 6, int(now_monday.timestamp()))
    expected = now_monday + timedelta(days=5)  # 周六
    expected = expected.replace(hour=9, minute=0, second=0, microsecond=0)
    assert next_ts == int(expected.timestamp())


@pytest.mark.asyncio
async def test_calc_next_scheduled_ts_weekly_boundary():
    """weekly 模式:星期边界处理(1-7 限制)"""
    from api.services.task_scheduler import _calc_next_scheduled_ts

    now = datetime(2025, 1, 15, 8, 0, 0)

    # 超出范围的 weekday 被限制在 1-7
    next_ts = _calc_next_scheduled_ts("weekly", "09:00", 0, int(now.timestamp()))
    next_ts2 = _calc_next_scheduled_ts("weekly", "09:00", 1, int(now.timestamp()))
    assert next_ts == next_ts2

    next_ts = _calc_next_scheduled_ts("weekly", "09:00", 8, int(now.timestamp()))
    next_ts2 = _calc_next_scheduled_ts("weekly", "09:00", 7, int(now.timestamp()))
    assert next_ts == next_ts2


@pytest.mark.asyncio
async def test_calc_next_scheduled_ts_unknown_type():
    """未知 schedule_type 返回 0"""
    from api.services.task_scheduler import _calc_next_scheduled_ts

    now = datetime(2025, 1, 15, 10, 0, 0)
    next_ts = _calc_next_scheduled_ts("unknown", "09:00", 1, int(now.timestamp()))
    assert next_ts == 0


@pytest.mark.asyncio
async def test_schedule_task_now():
    """schedule_task_now 返回有效时间戳"""
    from api.services.task_scheduler import schedule_task_now

    ts = schedule_task_now("task_1", "daily", "09:00", 1)
    assert isinstance(ts, int)
    assert ts > 0

    ts = schedule_task_now("task_1", "weekly", "14:00", 5)
    assert isinstance(ts, int)
    assert ts > 0


@pytest.mark.asyncio
async def test_scheduler_start_stop():
    """调度器启动和停止控制"""
    import api.services.task_scheduler as scheduler

    await scheduler.stop_scheduler()
    assert not scheduler._scheduler_started
    assert scheduler._scheduler_task is None

    await scheduler.start_scheduler()
    assert scheduler._scheduler_started
    assert scheduler._scheduler_task is not None

    task_before = scheduler._scheduler_task
    await scheduler.start_scheduler()
    assert scheduler._scheduler_task is task_before

    await scheduler.stop_scheduler()
    await asyncio.sleep(0.1)
    assert not scheduler._scheduler_started
    assert scheduler._scheduler_task is None