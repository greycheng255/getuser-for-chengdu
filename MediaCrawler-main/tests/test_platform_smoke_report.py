from tools.platform_smoke_report import evaluate_records


def _records(successes_per_group=8, total_per_group=10):
    records = []
    for platform in ("douyin", "xiaohongshu"):
        for scenario in ("image", "video"):
            for index in range(total_per_group):
                success = index < successes_per_group
                records.append({
                    "run_id": f"{platform}-{scenario}-{index}",
                    "platform": platform,
                    "scenario": scenario,
                    "success": success,
                    "error_code": "RATE_LIMITED" if not success else "",
                    "account_alias": f"{platform}-test",
                    "started_at": "2026-08-05T10:00:00+08:00",
                    "finished_at": "2026-08-05T10:01:00+08:00",
                    "evidence_ref": f"evidence/{platform}-{scenario}-{index}.png",
                })
    return records


def test_platform_smoke_report_accepts_four_groups_at_eighty_percent():
    report = evaluate_records(_records())
    assert report["valid"] is True
    assert report["record_count"] == 40
    assert all(group["success_rate"] == 0.8 for group in report["groups"].values())


def test_platform_smoke_report_rejects_small_samples():
    report = evaluate_records(_records(successes_per_group=5, total_per_group=5))
    assert report["valid"] is False
    assert all(not group["minimum_runs_met"] for group in report["groups"].values())


def test_platform_smoke_report_requires_failure_classification_and_evidence():
    records = _records()
    records[0]["success"] = False
    records[0]["error_code"] = ""
    records[1]["evidence_ref"] = ""
    report = evaluate_records(records)
    assert report["valid"] is False
    assert len(report["validation_errors"]) == 2


def test_platform_smoke_report_rejects_duplicate_run_ids():
    records = _records()
    records[1]["run_id"] = records[0]["run_id"]
    report = evaluate_records(records)
    assert report["valid"] is False
    assert any(
        "run_id 重复" in error.get("errors", [])
        for error in report["validation_errors"]
    )
