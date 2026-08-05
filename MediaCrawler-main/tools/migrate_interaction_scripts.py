import argparse
import asyncio
import json
from pathlib import Path

from api.services.interactor.script_library import get_script_library


async def main(args) -> int:
    report = await get_script_library().migrate_legacy_types(dry_run=args.mode == "dry-run")
    output = Path(args.output or f"migration_reports/scripts_{args.mode}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("valid") else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="补齐 interaction_scripts 一级话术类型")
    parser.add_argument("mode", choices=["dry-run", "apply"])
    parser.add_argument("--output")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
