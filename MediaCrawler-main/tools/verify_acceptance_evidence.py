# -*- coding: utf-8 -*-
"""汇总 dev/staging 外部验收证据，形成机器可判定的上线门禁。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 必须包含 JSON 对象")
    return payload


def verify_evidence(
    *,
    migration_apply_reports: Iterable[Dict[str, Any]],
    migration_validate_report: Dict[str, Any],
    migration_rollback_report: Dict[str, Any],
    platform_smoke_report: Dict[str, Any],
    apollo_status: Dict[str, Any],
    signoff: Dict[str, Any],
) -> Dict[str, Any]:
    apply_reports = list(migration_apply_reports)
    checks: List[Dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add(
        "migration_apply_twice",
        len(apply_reports) >= 2 and all(report.get("valid") is True for report in apply_reports[:2]),
        f"received={len(apply_reports)}",
    )
    second_created = apply_reports[1].get("created_count") if len(apply_reports) >= 2 else None
    add(
        "migration_second_apply_idempotent",
        second_created == 0,
        f"second_created_count={second_created}",
    )
    add(
        "migration_validation_complete",
        migration_validate_report.get("valid") is True
        and float(migration_validate_report.get("coverage_rate", 0)) == 1.0,
        f"coverage_rate={migration_validate_report.get('coverage_rate')}",
    )
    add(
        "migration_rollback_exercised",
        migration_rollback_report.get("valid") is True
        and migration_rollback_report.get("mode") == "rollback"
        and int(migration_rollback_report.get("deleted_count", -1))
        == int(migration_rollback_report.get("rollback_candidate_count", -2)),
        (
            f"deleted={migration_rollback_report.get('deleted_count')}, "
            f"candidates={migration_rollback_report.get('rollback_candidate_count')}"
        ),
    )
    add(
        "platform_smoke_threshold",
        platform_smoke_report.get("valid") is True,
        f"records={platform_smoke_report.get('record_count')}",
    )
    add(
        "apollo_runtime_loaded",
        apollo_status.get("enabled") is True
        and apollo_status.get("loaded") is True
        and int(apollo_status.get("keys_loaded", 0)) > 0,
        f"keys_loaded={apollo_status.get('keys_loaded', 0)}",
    )
    add(
        "business_signoff",
        signoff.get("approved") is True
        and bool(str(signoff.get("approver") or "").strip())
        and bool(str(signoff.get("approved_at") or "").strip()),
        f"approver_present={bool(str(signoff.get('approver') or '').strip())}",
    )
    return {
        "valid": all(check["passed"] for check in checks),
        "checks": checks,
        "failed_checks": [check["name"] for check in checks if not check["passed"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证上线验收证据")
    parser.add_argument("--migration-apply", type=Path, action="append", required=True)
    parser.add_argument("--migration-validate", type=Path, required=True)
    parser.add_argument("--migration-rollback", type=Path, required=True)
    parser.add_argument("--platform-smoke", type=Path, required=True)
    parser.add_argument("--apollo-status", type=Path, required=True)
    parser.add_argument("--signoff", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = verify_evidence(
        migration_apply_reports=[read_json(path) for path in args.migration_apply],
        migration_validate_report=read_json(args.migration_validate),
        migration_rollback_report=read_json(args.migration_rollback),
        platform_smoke_report=read_json(args.platform_smoke),
        apollo_status=read_json(args.apollo_status),
        signoff=read_json(args.signoff),
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
