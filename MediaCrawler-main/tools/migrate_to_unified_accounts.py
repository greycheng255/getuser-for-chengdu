# -*- coding: utf-8 -*-
"""将 publisher_accounts / bot_accounts 幂等迁移到 unified_accounts。

支持 dry-run、apply、validate、rollback-plan、rollback；每次执行都会输出可审计
JSON 报告。apply 只写统一表，绝不修改旧表。相同 owner/platform/账号名称的数据
会合并为 both。rollback 只删除指定迁移批次创建的数据。
"""

import argparse
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from api.schemas.accounts import AccountRole, AccountStatus, normalize_platform
from database.models import Base, UnifiedAccount
from api.services.unified_account_service import stable_legacy_account_id


STATUS_MAP = {
    "active": AccountStatus.ACTIVE.value,
    "cooldown": AccountStatus.COOLDOWN.value,
    "cooling": AccountStatus.COOLDOWN.value,
    "expired": AccountStatus.EXPIRED.value,
    "login_expired": AccountStatus.NEEDS_RELOGIN.value,
    "needs_relogin": AccountStatus.NEEDS_RELOGIN.value,
    "invalid": AccountStatus.INVALID.value,
    "banned": AccountStatus.INVALID.value,
    "disabled": AccountStatus.DISABLED.value,
    "deleted": AccountStatus.DISABLED.value,
    "inactive": AccountStatus.DISABLED.value,
}


def _timestamp(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, datetime):
        return int(value.timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _stable_account_id(owner: str, platform: str, identity: str) -> str:
    return stable_legacy_account_id(owner, platform, identity)


@dataclass
class MigrationCandidate:
    owner_user_id: str
    platform: str
    identity: str
    account_name: str
    role: str
    status: str
    auth_data: Dict[str, Any]
    capabilities: List[str]
    group_name: str = ""
    region: str = ""
    health_score: int = 100
    daily_limit: int = 0
    today_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    cooldown_until: int = 0
    last_used_ts: int = 0
    created_ts: int = 0
    updated_ts: int = 0
    sources: List[str] = field(default_factory=list)

    @property
    def account_id(self) -> str:
        return _stable_account_id(self.owner_user_id, self.platform, self.identity)


class LegacyAccountMigrator:
    def __init__(self, session_factory, engine=None):
        self.session_factory = session_factory
        self.engine = engine

    async def target_schema_exists(self) -> bool:
        """只读检查统一账号表是否存在。"""
        if self.engine is None:
            return False
        async with self.engine.connect() as conn:
            return await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).has_table(
                    UnifiedAccount.__tablename__
                )
            )

    async def ensure_schema(self) -> None:
        if self.engine is None:
            return
        async with self.engine.begin() as conn:
            # 迁移工具只负责统一账号表，不能顺带创建项目中的其他业务表。
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn,
                    tables=[UnifiedAccount.__table__],
                )
            )
            columns = await conn.run_sync(
                lambda sync_conn: {
                    item["name"] for item in inspect(sync_conn).get_columns("unified_accounts")
                }
            )
            if "migration_batch_id" not in columns:
                await conn.execute(text(
                    "ALTER TABLE unified_accounts ADD COLUMN migration_batch_id VARCHAR(64) NOT NULL DEFAULT ''"
                ))
            if "legacy_source" not in columns:
                await conn.execute(text(
                    "ALTER TABLE unified_accounts ADD COLUMN legacy_source VARCHAR(32) NOT NULL DEFAULT ''"
                ))

    async def _read_table(self, table_name: str) -> List[Dict[str, Any]]:
        try:
            async with self.session_factory() as session:
                result = await session.execute(text(f"SELECT * FROM {table_name}"))
                return [dict(row) for row in result.mappings().all()]
        except Exception:
            return []

    @staticmethod
    def _mapped_status(value: Any, report: Dict[str, Any], source: str) -> str:
        raw = str(value or "active").strip().lower()
        mapped = STATUS_MAP.get(raw)
        if mapped is None:
            report["conflicts"].append({
                "type": "unmapped_status",
                "source": source,
                "value": raw,
                "action": "disabled",
            })
            return AccountStatus.DISABLED.value
        return mapped

    async def collect(self, batch_id: str) -> tuple[List[MigrationCandidate], Dict[str, Any]]:
        publishers = await self._read_table("publisher_accounts")
        bots = await self._read_table("bot_accounts")
        report: Dict[str, Any] = {
            "batch_id": batch_id,
            "source_counts": {"publisher_accounts": len(publishers), "bot_accounts": len(bots)},
            "candidate_count": 0,
            "merged_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "unchanged_count": 0,
            "failed_count": 0,
            "conflict_count": 0,
            "failures": [],
            "conflicts": [],
        }
        candidates: Dict[str, MigrationCandidate] = {}

        def add_candidate(candidate: MigrationCandidate, source: str) -> None:
            key = f"{candidate.owner_user_id}|{candidate.platform}|{candidate.identity.strip().lower()}"
            current = candidates.get(key)
            if current is None:
                candidate.sources.append(source)
                candidates[key] = candidate
                return
            if source not in current.sources:
                current.sources.append(source)
            if current.role != candidate.role:
                current.role = AccountRole.BOTH.value
                report["merged_count"] += 1
            if current.auth_data != candidate.auth_data and candidate.auth_data:
                report["conflicts"].append({
                    "type": "auth_conflict",
                    "account_id": current.account_id,
                    "sources": list(current.sources),
                    "action": "keep_first",
                })
            current.capabilities = list(dict.fromkeys(current.capabilities + candidate.capabilities))
            current.health_score = min(current.health_score, candidate.health_score)
            current.success_count += candidate.success_count
            current.failure_count += candidate.failure_count
            current.cooldown_until = max(current.cooldown_until, candidate.cooldown_until)
            current.last_used_ts = max(current.last_used_ts, candidate.last_used_ts)

        for row in publishers:
            try:
                owner = str(row.get("user_id") if row.get("user_id") is not None else "")
                identity = str(row.get("account_name") or "").strip()
                if not identity:
                    raise ValueError("缺少 account_name，无法生成可追溯业务标识")
                platform = normalize_platform(str(row.get("platform") or ""))
                cookies = str(row.get("cookies") or "").strip()
                if not cookies:
                    raise ValueError("缺少 cookies")
                status = self._mapped_status(row.get("status"), report, "publisher_accounts")
                if not bool(row.get("is_active", 1)):
                    status = AccountStatus.DISABLED.value
                add_candidate(MigrationCandidate(
                    owner_user_id=owner,
                    platform=platform,
                    identity=identity,
                    account_name=identity,
                    role=AccountRole.PUBLISHER.value,
                    status=status,
                    auth_data={"cookies": cookies},
                    capabilities=["image", "video", "article"],
                    group_name=str(row.get("group") or ""),
                    region=str(row.get("region") or ""),
                    daily_limit=max(0, int(row.get("daily_limit") or 0)),
                    today_count=max(0, int(row.get("today_count") or 0)),
                    success_count=max(0, int(row.get("successes") or 0)),
                    failure_count=max(0, int(row.get("failures") or 0)),
                    cooldown_until=max(0, _timestamp(row.get("cooldown_until"))),
                    last_used_ts=max(0, _timestamp(row.get("last_used_ts"))),
                    created_ts=_timestamp(row.get("created_at")),
                    updated_ts=_timestamp(row.get("updated_at")),
                ), "publisher_accounts")
            except Exception as exc:
                report["failures"].append({"source": "publisher_accounts", "id": row.get("id"), "error": str(exc)})

        for row in bots:
            try:
                legacy_id = str(row.get("account_id") or "").strip()
                if not legacy_id:
                    raise ValueError("缺少 account_id")
                identity = str(row.get("label") or legacy_id).strip()
                owner = str(row.get("owner_user_id") if row.get("owner_user_id") is not None else "")
                platform = normalize_platform(str(row.get("platform") or ""))
                cookie = str(row.get("cookie") or "").strip()
                if not cookie:
                    raise ValueError("缺少 cookie")
                add_candidate(MigrationCandidate(
                    owner_user_id=owner,
                    platform=platform,
                    identity=identity,
                    account_name=identity,
                    role=AccountRole.INTERACTOR.value,
                    status=self._mapped_status(row.get("status"), report, "bot_accounts"),
                    auth_data={"cookies": cookie},
                    capabilities=["comment", "dm"],
                    group_name=str(row.get("account_group") or ""),
                    region=str(row.get("region") or ""),
                    health_score=max(0, min(100, int(float(row.get("health_score") or 100)))),
                    success_count=max(0, int(row.get("success_count") or 0)),
                    failure_count=max(0, int(row.get("failure_count") or 0)),
                    cooldown_until=max(0, _timestamp(row.get("cooldown_until"))),
                    last_used_ts=max(0, _timestamp(row.get("last_used_at"))),
                    created_ts=_timestamp(row.get("created_at")),
                ), "bot_accounts")
            except Exception as exc:
                report["failures"].append({"source": "bot_accounts", "id": row.get("account_id"), "error": str(exc)})

        report["candidate_count"] = len(candidates)
        report["failed_count"] = len(report["failures"])
        report["conflict_count"] = len(report["conflicts"])
        return list(candidates.values()), report

    async def _rollback(
        self,
        batch_id: str,
        *,
        apply: bool,
    ) -> Dict[str, Any]:
        if not batch_id:
            raise ValueError("回滚必须显式提供 --batch-id")
        async with self.session_factory() as session:
            rows = (await session.execute(
                select(
                    UnifiedAccount.id,
                    UnifiedAccount.account_id,
                    UnifiedAccount.platform,
                ).where(
                    UnifiedAccount.migration_batch_id == batch_id,
                    UnifiedAccount.legacy_source != "",
                )
            )).all()

        report: Dict[str, Any] = {
            "batch_id": batch_id,
            "mode": "rollback" if apply else "rollback-plan",
            "rollback_candidate_count": len(rows),
            "rollback_candidates": [
                {"id": row[0], "account_id": row[1], "platform": row[2]}
                for row in rows
            ],
            "deleted_count": 0,
            "valid": True,
        }
        if not apply:
            return report

        async with self.session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(UnifiedAccount).where(
                        UnifiedAccount.migration_batch_id == batch_id,
                        UnifiedAccount.legacy_source != "",
                    )
                )
                report["deleted_count"] = max(0, int(result.rowcount or 0))
        report["valid"] = report["deleted_count"] == report["rollback_candidate_count"]
        return report

    async def run(
        self,
        mode: str,
        batch_id: Optional[str] = None,
        *,
        confirm_rollback: bool = False,
    ) -> Dict[str, Any]:
        # dry-run 和 rollback-plan 必须保持严格只读；validate 也不能为了校验
        # 而偷偷创建目标表。只有明确的 apply 可以补建统一账号表结构。
        target_exists = await self.target_schema_exists()
        if mode == "apply":
            await self.ensure_schema()
            target_exists = True

        if mode in {"rollback-plan", "rollback"}:
            if mode == "rollback" and not confirm_rollback:
                raise ValueError("执行 rollback 必须同时提供 --confirm-rollback")
            if not target_exists:
                if not batch_id:
                    raise ValueError("回滚必须显式提供 --batch-id")
                return {
                    "batch_id": batch_id,
                    "mode": mode,
                    "target_table_exists": False,
                    "rollback_candidate_count": 0,
                    "rollback_candidates": [],
                    "deleted_count": 0,
                    "valid": True,
                }
            return await self._rollback(batch_id or "", apply=mode == "rollback")

        batch_id = batch_id or f"ua_{datetime.utcnow():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}"
        candidates, report = await self.collect(batch_id)
        report["mode"] = mode
        if mode == "dry-run":
            report["valid"] = report["failed_count"] == 0 and report["conflict_count"] == 0
            return report

        factory = self.session_factory
        if mode == "apply":
            now = int(time.time())
            async with factory() as session:
                async with session.begin():
                    for candidate in candidates:
                        existing = (
                            await session.execute(
                                select(UnifiedAccount).where(
                                    UnifiedAccount.owner_user_id == candidate.owner_user_id,
                                    UnifiedAccount.platform == candidate.platform,
                                    UnifiedAccount.account_id == candidate.account_id,
                                ).limit(1)
                            )
                        ).scalar_one_or_none()
                        if existing is None:
                            session.add(UnifiedAccount(
                                account_id=candidate.account_id,
                                owner_user_id=candidate.owner_user_id,
                                platform=candidate.platform,
                                account_name=candidate.account_name,
                                role=candidate.role,
                                status=candidate.status,
                                auth_data=json.dumps(candidate.auth_data, ensure_ascii=False),
                                capabilities=json.dumps(candidate.capabilities, ensure_ascii=False),
                                group_name=candidate.group_name,
                                region=candidate.region,
                                health_score=candidate.health_score,
                                daily_limit=candidate.daily_limit,
                                today_count=candidate.today_count,
                                success_count=candidate.success_count,
                                failure_count=candidate.failure_count,
                                cooldown_until=candidate.cooldown_until,
                                last_used_ts=candidate.last_used_ts,
                                migration_batch_id=batch_id,
                                legacy_source=",".join(candidate.sources),
                                created_ts=candidate.created_ts or now,
                                updated_ts=candidate.updated_ts or now,
                            ))
                            report["created_count"] += 1
                        elif existing.role != candidate.role and candidate.role == AccountRole.BOTH.value:
                            existing.role = AccountRole.BOTH.value
                            existing.updated_ts = now
                            report["updated_count"] += 1
                        else:
                            report["unchanged_count"] += 1
            report["valid"] = report["failed_count"] == 0
            return report

        if mode == "validate":
            expected = {candidate.account_id for candidate in candidates}
            if not target_exists:
                report["target_table_exists"] = False
                report["covered_count"] = 0
                report["missing_account_ids"] = sorted(expected)
                report["coverage_rate"] = 0.0 if expected else 1.0
                report["valid"] = not expected and report["failed_count"] == 0
                return report
            async with factory() as session:
                found = set((await session.execute(
                    select(UnifiedAccount.account_id).where(UnifiedAccount.account_id.in_(expected))
                )).scalars().all()) if expected else set()
            report["covered_count"] = len(found)
            report["missing_account_ids"] = sorted(expected - found)
            report["coverage_rate"] = round(len(found) / len(expected), 6) if expected else 1.0
            report["valid"] = not report["missing_account_ids"] and report["failed_count"] == 0
            return report

        raise ValueError(f"不支持的迁移模式: {mode}")


async def _main(args) -> int:
    from database.db_session import get_async_engine

    engine = get_async_engine()
    if engine is None:
        raise RuntimeError("当前数据库配置无法创建异步 engine")
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    report = await LegacyAccountMigrator(factory, engine).run(
        args.mode,
        args.batch_id,
        confirm_rollback=args.confirm_rollback,
    )
    output = Path(args.output) if args.output else Path("migration_reports") / f"{report['batch_id']}_{args.mode}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("valid") else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="迁移旧账号到 unified_accounts")
    parser.add_argument(
        "mode",
        choices=["dry-run", "apply", "validate", "rollback-plan", "rollback"],
    )
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--confirm-rollback",
        action="store_true",
        help="确认删除指定批次创建的统一账号；旧表不会被修改",
    )
    raise SystemExit(asyncio.run(_main(parser.parse_args())))
