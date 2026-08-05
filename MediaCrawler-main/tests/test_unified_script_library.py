import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.services.interactor.script_library import ScriptLibrary


@pytest.fixture
async def library(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scripts.db'}")
    ScriptLibrary._ensured = False
    service = ScriptLibrary(engine)
    await service.ensure_table()
    yield service
    ScriptLibrary._ensured = False
    await engine.dispose()


@pytest.mark.asyncio
async def test_all_script_types_can_be_created_filtered_and_picked(library):
    await library.add_script("douyin", "comment_reply", "评论话术", script_type="comment")
    await library.add_script("douyin", "direct_message", "私信话术", script_type="direct_message")
    await library.add_script(
        "douyin",
        "campaign",
        "发布正文",
        script_type="publish",
        title="发布标题",
        tags=["新品"],
        media_type="video",
        platform_constraints=["douyin"],
    )

    for script_type in ("comment", "direct_message", "publish"):
        items = await library.list_scripts(platform="douyin", script_type=script_type)
        assert items
        assert all(item["script_type"] == script_type for item in items)

    picked = await library.pick_random(
        platform="douyin", script_type="publish", scene="campaign"
    )
    assert picked is not None
    assert picked.title == "发布标题"
    assert picked.platform_constraints == ["douyin"]


@pytest.mark.asyncio
async def test_batch_import_is_idempotent(library):
    items = [
        {"platform": "weibo", "script_type": "comment", "scene": "comment_reply", "content": "同一条"},
        {"platform": "weibo", "script_type": "comment", "scene": "comment_reply", "content": "同一条"},
    ]
    assert await library.batch_import(items, owner_user_id=1) == 1
    assert await library.batch_import(items, owner_user_id=1) == 0


@pytest.mark.asyncio
async def test_legacy_type_migration_preserves_scene(library):
    engine = library._get_engine()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO interaction_scripts "
            "(script_id,platform,script_type,scene,content,tags,usage_count) "
            "VALUES ('legacy-dm','','comment','direct_message','私信','[]',0)"
        ))
    dry_run = await library.migrate_legacy_types(dry_run=True)
    assert dry_run["updated"] >= 1
    await library.migrate_legacy_types(dry_run=False)
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT script_type, scene FROM interaction_scripts WHERE script_id='legacy-dm'"
        ))).one()
    assert row[0] == "direct_message"
    assert row[1] == "direct_message"
