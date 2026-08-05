# -*- coding: utf-8 -*-
"""导出账号/话术表结构与脱敏统计，不读取认证字段值。"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import inspect, text


TABLE_GROUP_FIELDS = {
    "publisher_accounts": ("platform", "status"),
    "bot_accounts": ("platform", "status"),
    "unified_accounts": ("platform", "role", "status"),
    "interaction_scripts": ("platform", "script_type", "scene"),
}
SENSITIVE_COLUMNS = {
    "cookies", "cookie", "auth_data", "token", "password", "secret",
}


async def build_profile(engine) -> Dict[str, Any]:
    profile: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
    }
    async with engine.connect() as conn:
        schemas = await conn.run_sync(lambda sync_conn: {
            table: inspect(sync_conn).get_columns(table)
            for table in inspect(sync_conn).get_table_names()
            if table in TABLE_GROUP_FIELDS
        })
        for table, columns in schemas.items():
            column_names = [column["name"] for column in columns]
            table_profile = {
                "columns": [
                    {
                        "name": column["name"],
                        "type": str(column["type"]),
                        "nullable": bool(column.get("nullable", True)),
                    }
                    for column in columns
                ],
                "sensitive_columns_present": sorted(
                    name for name in column_names if name.lower() in SENSITIVE_COLUMNS
                ),
                "row_count": int((await conn.execute(
                    text(f'SELECT COUNT(*) FROM "{table}"')
                )).scalar_one()),
                "distributions": {},
            }
            for field in TABLE_GROUP_FIELDS[table]:
                if field not in column_names:
                    continue
                rows = (await conn.execute(text(
                    f'SELECT "{field}", COUNT(*) FROM "{table}" '
                    f'GROUP BY "{field}" ORDER BY "{field}"'
                ))).all()
                table_profile["distributions"][field] = {
                    str(value or "<empty>"): int(count) for value, count in rows
                }
            profile["tables"][table] = table_profile
    return profile


async def _main(args) -> int:
    from database.db_session import get_async_engine

    engine = get_async_engine()
    if engine is None:
        raise RuntimeError("当前配置无法创建数据库 engine")
    profile = await build_profile(engine)
    output = json.dumps(profile, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "tables": sorted(profile["tables"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导出 dev 数据库脱敏结构和统计")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("migration_reports/dev-data-profile.json"),
    )
    raise SystemExit(asyncio.run(_main(parser.parse_args())))
