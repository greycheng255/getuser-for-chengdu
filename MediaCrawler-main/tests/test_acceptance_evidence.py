from tools.verify_acceptance_evidence import verify_evidence


def _valid_evidence():
    return {
        "migration_apply_reports": [
            {"valid": True, "created_count": 3},
            {"valid": True, "created_count": 0},
        ],
        "migration_validate_report": {"valid": True, "coverage_rate": 1.0},
        "migration_rollback_report": {
            "valid": True,
            "mode": "rollback",
            "rollback_candidate_count": 3,
            "deleted_count": 3,
        },
        "platform_smoke_report": {"valid": True, "record_count": 40},
        "apollo_status": {"enabled": True, "loaded": True, "keys_loaded": 33},
        "signoff": {
            "approved": True,
            "approver": "业务验收人",
            "approved_at": "2026-08-05T18:00:00+08:00",
        },
    }


def test_acceptance_evidence_passes_only_when_all_gates_are_proven():
    report = verify_evidence(**_valid_evidence())
    assert report["valid"] is True
    assert report["failed_checks"] == []


def test_acceptance_evidence_reports_each_missing_gate():
    evidence = _valid_evidence()
    evidence["migration_apply_reports"] = evidence["migration_apply_reports"][:1]
    evidence["migration_validate_report"]["coverage_rate"] = 0.9
    evidence["platform_smoke_report"]["valid"] = False
    evidence["apollo_status"]["loaded"] = False
    evidence["signoff"]["approved"] = False
    report = verify_evidence(**evidence)
    assert report["valid"] is False
    assert "migration_apply_twice" in report["failed_checks"]
    assert "migration_second_apply_idempotent" in report["failed_checks"]
    assert "migration_validation_complete" in report["failed_checks"]
    assert "platform_smoke_threshold" in report["failed_checks"]
    assert "apollo_runtime_loaded" in report["failed_checks"]
    assert "business_signoff" in report["failed_checks"]
