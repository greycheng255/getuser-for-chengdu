# -*- coding: utf-8 -*-
"""
数据库迁移脚本: 为 crawler_task 表添加调度相关字段

运行方式: python scripts/migrate_add_schedule_fields.py

添加字段:
- schedule_time: 调度执行时间(HH:MM)
- schedule_weekday: 周几执行(1-7)
- last_scheduled_ts: 上次调度执行时间戳
- next_scheduled_ts: 下次调度执行时间戳
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from config.db_config import postgres_db_config


async def migrate():
    db_url = (
        f"postgresql+asyncpg://{postgres_db_config['user']}:{postgres_db_config['password']}"
        f"@{postgres_db_config['host']}:{postgres_db_config['port']}/{postgres_db_config['db_name']}"
    )

    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(db_url, echo=False)

    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'crawler_task'
        """))
        existing_cols = [row[0] for row in result.fetchall()]

        migrations = []
        if 'schedule_time' not in existing_cols:
            migrations.append("ALTER TABLE crawler_task ADD COLUMN schedule_time VARCHAR(8) DEFAULT '09:00'")
        if 'schedule_weekday' not in existing_cols:
            migrations.append("ALTER TABLE crawler_task ADD COLUMN schedule_weekday INTEGER DEFAULT 1")
        if 'last_scheduled_ts' not in existing_cols:
            migrations.append("ALTER TABLE crawler_task ADD COLUMN last_scheduled_ts BIGINT DEFAULT 0")
        if 'next_scheduled_ts' not in existing_cols:
            migrations.append("ALTER TABLE crawler_task ADD COLUMN next_scheduled_ts BIGINT DEFAULT 0")

        if migrations:
            print(f"[迁移] 将执行 {len(migrations)} 个字段添加操作:")
            for sql in migrations:
                print(f"  - {sql}")
                await conn.execute(text(sql))
            await conn.commit()
            print("\n[成功] 迁移完成!")
        else:
            print("[跳过] 所有字段已存在,无需迁移")

    await engine.dispose()


if __name__ == "__main__":
    print("=" * 50)
    print("crawler_task 表调度字段迁移")
    print("=" * 50)
    asyncio.run(migrate())
