# -*- coding: utf-8 -*-
"""校验抖音/小红书真实平台冒烟证据并生成成功率报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


PLATFORMS = ("douyin", "xiaohongshu")
SCENARIOS = ("image", "video")
ERROR_CODES = {
    "AUTH_EXPIRED",
    "CAPTCHA_REQUIRED",
    "RATE_LIMITED",
    "INVALID_MEDIA",
    "CONTENT_REJECTED",
    "UPLOAD_FAILED",
    "SELECTOR_CHANGED",
    "TIMEOUT",
    "UNKNOWN",
}


def load_records(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError("JSON 输入必须是数组")
        return [dict(item) for item in payload]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def evaluate_records(
    records: Iterable[Dict[str, Any]],
    *,
    minimum_runs: int = 10,
    success_threshold: float = 0.8,
) -> Dict[str, Any]:
    if minimum_runs < 1:
        raise ValueError("minimum_runs 必须大于 0")
    if not 0 <= success_threshold <= 1:
        raise ValueError("success_threshold 必须在 0 到 1 之间")

    groups = {
        f"{platform}:{scenario}": {
            "platform": platform,
            "scenario": scenario,
            "total": 0,
            "successes": 0,
            "failures": 0,
            "success_rate": 0.0,
            "minimum_runs_met": False,
            "threshold_met": False,
            "error_codes": {},
        }
        for platform in PLATFORMS
        for scenario in SCENARIOS
    }
    errors: List[Dict[str, Any]] = []
    seen_run_ids = set()

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            errors.append({"row": index, "error": "记录必须是 JSON 对象"})
            continue
        run_id = str(record.get("run_id") or "").strip()
        platform = str(record.get("platform") or "").strip().lower()
        scenario = str(record.get("scenario") or "").strip().lower()
        success = record.get("success")
        row_errors = []
        if not run_id:
            row_errors.append("缺少 run_id")
        elif run_id in seen_run_ids:
            row_errors.append("run_id 重复")
        if platform not in PLATFORMS:
            row_errors.append("platform 必须为 douyin 或 xiaohongshu")
        if scenario not in SCENARIOS:
            row_errors.append("scenario 必须为 image 或 video")
        if not isinstance(success, bool):
            row_errors.append("success 必须为布尔值")
        for field in ("account_alias", "started_at", "finished_at", "evidence_ref"):
            if not str(record.get(field) or "").strip():
                row_errors.append(f"缺少 {field}")
        error_code = str(record.get("error_code") or "").strip()
        if success is False and error_code not in ERROR_CODES:
            row_errors.append("失败记录必须提供标准 error_code")
        if success is True and error_code:
            row_errors.append("成功记录不得包含 error_code")
        if row_errors:
            errors.append({"row": index, "run_id": run_id, "errors": row_errors})
            continue

        seen_run_ids.add(run_id)
        group = groups[f"{platform}:{scenario}"]
        group["total"] += 1
        if success:
            group["successes"] += 1
        else:
            group["failures"] += 1
            group["error_codes"][error_code] = group["error_codes"].get(error_code, 0) + 1

    for group in groups.values():
        total = group["total"]
        group["success_rate"] = round(group["successes"] / total, 4) if total else 0.0
        group["minimum_runs_met"] = total >= minimum_runs
        group["threshold_met"] = group["success_rate"] >= success_threshold

    valid = not errors and all(
        group["minimum_runs_met"] and group["threshold_met"]
        for group in groups.values()
    )
    return {
        "valid": valid,
        "minimum_runs": minimum_runs,
        "success_threshold": success_threshold,
        "record_count": sum(group["total"] for group in groups.values()),
        "validation_errors": errors,
        "groups": groups,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成真实平台发布成功率报告")
    parser.add_argument("input", type=Path, help="JSON 数组或 JSONL 证据文件")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--minimum-runs", type=int, default=10)
    parser.add_argument("--success-threshold", type=float, default=0.8)
    args = parser.parse_args()

    report = evaluate_records(
        load_records(args.input),
        minimum_runs=args.minimum_runs,
        success_threshold=args.success_threshold,
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
