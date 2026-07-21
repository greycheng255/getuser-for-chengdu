# -*- coding: utf-8 -*-
"""
数据库迁移脚本: 为 customer_lead 表添加增强字段

运行方式: python scripts/migrate_add_lead_fields.py

添加字段:
- comment_url: 原评论链接
- profile_url: 用户主页链接  
- platform_display_id: 平台内可搜索用户ID(如抖音号/小红书号)
"""
import asyncio
import os
import sys

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from config.db_config import postgres_db_config


async def migrate():
    """执行迁移"""
    db_url = (
        f"postgresql+asyncpg://{postgres_db_config['user']}:{postgres_db_config['password']}"
        f"@{postgres_db_config['host']}:{postgres_db_config['port']}/{postgres_db_config['db_name']}"
    )
    
    from sqlalchemy.ext.asyncio import create_async_engine
    
    engine = create_async_engine(db_url, echo=True)
    
    async with engine.connect() as conn:
        # 检查字段是否存在
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'customer_lead'
        """))
        existing_cols = [row[0] for row in result.fetchall()]
        
        migrations = []
        
        if 'comment_url' not in existing_cols:
            migrations.append("ALTER TABLE customer_lead ADD COLUMN comment_url TEXT DEFAULT ''")
            
        if 'profile_url' not in existing_cols:
            migrations.append("ALTER TABLE customer_lead ADD COLUMN profile_url TEXT DEFAULT ''")
            
        if 'platform_display_id' not in existing_cols:
            migrations.append("ALTER TABLE customer_lead ADD COLUMN platform_display_id VARCHAR(255) DEFAULT ''")
        
        if migrations:
            print(f"[迁移] 将执行 {len(migrations)} 个字段添加操作:")
            for sql in migrations:
                print(f"  - {sql}")
            
            for sql in migrations:
                print(f"\n[执行] {sql}")
                await conn.execute(text(sql))
            
            await conn.commit()
            print("\n[成功] 迁移完成!")
        else:
            print("[跳过] 所有字段已存在,无需迁移")
    
    await engine.dispose()


if __name__ == "__main__":
    print("=" * 50)
    print("customer_lead 表字段增强迁移")
    print("=" * 50)
    asyncio.run(migrate())
