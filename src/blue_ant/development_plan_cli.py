"""CLI to create a non-executable development plan from audit/test reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .development_plan import generate_development_plan, plan_to_dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a human-reviewed Blue Ant development plan")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--audit-report", required=True)
    parser.add_argument("--test-report")
    parser.add_argument("--output", default="blue-ant-development-plan.json")
    args = parser.parse_args(argv)
    try:
        audit = json.loads(Path(args.audit_report).read_text(encoding="utf-8"))
        tests = json.loads(Path(args.test_report).read_text(encoding="utf-8")) if args.test_report else None
        plan = generate_development_plan(audit, tests, project_id=args.project_id)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan_to_dict(plan), indent=2) + "\n", encoding="utf-8")
        print(f"Plan {plan.plan_id}: {len(plan.tasks)} review task(s); human approval required -> {output}")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
