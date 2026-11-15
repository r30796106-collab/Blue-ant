"""CLI for deterministic, non-applied code preparation drafts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .code_preparation import prepare_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare safe deterministic replacement-file drafts without applying them")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", default="blue-ant-prepared-tasks.json")
    args = parser.parse_args(argv)
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        result = prepare_plan(args.workspace, plan)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        prepared = sum(item["status"] == "prepared" for item in result["prepared_tasks"])
        print(f"Prepared {prepared} deterministic draft(s); none applied or approved.")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
