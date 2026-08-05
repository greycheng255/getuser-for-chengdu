# -*- coding: utf-8 -*-
"""扫描 Git 跟踪文件中的高置信凭据，不输出敏感原文。"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_style_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "x_auth_token": re.compile(r"\bauth_token=[0-9a-fA-F]{20,}"),
    "jwt_literal": re.compile(r"(?i)\bJWT_SECRET_KEY\s*=\s*['\"][^'\"]{16,}['\"]"),
}


def scan_paths(paths: Iterable[Path]) -> List[Dict[str, object]]:
    findings: List[Dict[str, object]] = []
    for path in paths:
        try:
            if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append({
                        "file": str(path),
                        "line": line_number,
                        "pattern": name,
                    })
    return findings


def tracked_project_files() -> List[Path]:
    """返回已跟踪及准备提交的未跟踪文件，忽略 .gitignore 内容。"""
    git_root = Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=PROJECT_ROOT,
        text=True,
    ).strip())
    relative_project = PROJECT_ROOT.relative_to(git_root).as_posix()
    output = subprocess.check_output(
        [
            "git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
            "--", relative_project,
        ],
        cwd=git_root,
    )
    files = []
    for raw in output.decode("utf-8", errors="replace").split("\0"):
        if raw:
            files.append(git_root / raw)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描当前项目的 Git 跟踪凭据")
    parser.parse_args()
    files = tracked_project_files()
    findings = scan_paths(files)
    env_tracked = any(path.name == ".env" for path in files)
    print({
        "tracked_files_scanned": len(files),
        "env_tracked": env_tracked,
        "finding_count": len(findings),
        "findings": findings,
    })
    return 1 if env_tracked or findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
