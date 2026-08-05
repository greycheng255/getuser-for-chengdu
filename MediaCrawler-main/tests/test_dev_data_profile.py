import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tools.export_dev_data_profile import build_profile


@pytest.mark.asyncio
async def test_dev_profile_contains_schema_and_counts_but_no_secret_values(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile.db'}")
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE publisher_accounts ("
            "id INTEGER PRIMARY KEY, platform TEXT, status TEXT, cookies TEXT)"
        ))
        await conn.execute(text(
            "INSERT INTO publisher_accounts (platform,status,cookies) "
            "VALUES ('douyin','active','sensitive-cookie-value')"
        ))
    profile = await build_profile(engine)
    table = profile["tables"]["publisher_accounts"]
    assert table["row_count"] == 1
    assert table["distributions"]["platform"] == {"douyin": 1}
    assert table["sensitive_columns_present"] == ["cookies"]
    assert "sensitive-cookie-value" not in str(profile)
    await engine.dispose()
