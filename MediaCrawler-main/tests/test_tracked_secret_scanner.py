from tools.check_tracked_secrets import scan_paths


def test_secret_scanner_reports_location_without_secret_value(tmp_path):
    secret_file = tmp_path / "bad.py"
    secret_file.write_text(
        'COOKIE = "auth_token=' + "a" * 32 + '"\n',
        encoding="utf-8",
    )
    findings = scan_paths([secret_file])
    assert findings == [{
        "file": str(secret_file),
        "line": 1,
        "pattern": "x_auth_token",
    }]
    assert "a" * 32 not in str(findings)


def test_secret_scanner_accepts_empty_examples(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text(
        "JWT_SECRET_KEY=\nCRAWLER_COOKIES=\nAPOLLO_META_SERVER_URL=\n",
        encoding="utf-8",
    )
    assert scan_paths([example]) == []
