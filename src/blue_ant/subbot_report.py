"""Command-line entry point for deterministic read-only repository review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .subbots import SubBotFactory, run_fleet


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Blue Ant read-only repository sub-bots")
    parser.add_argument("--repo", default=".", help="Repository directory to inspect")
    parser.add_argument("--output", default="blue-ant-report.json", help="JSON report destination")
    parser.add_argument("--max-bots", type=int, default=4)
    args = parser.parse_args()

    bots = SubBotFactory(max_bots=args.max_bots).create_fleet()
    findings = run_fleet(args.repo, bots)
    payload = {
        "schema_version": 1,
        "mode": "read_only_static_review",
        "bots": [{"bot_id": bot.bot_id, "role": bot.role.value} for bot in bots],
        "findings": [finding.__dict__ if hasattr(finding, "__dict__") else {
            "bot_id": finding.bot_id, "role": finding.role, "severity": finding.severity,
            "path": finding.path, "message": finding.message,
        } for finding in findings],
        "limitations": ["No project code was executed.", "Findings are heuristic and require review."],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Blue Ant: {len(bots)} sub-bots produced {len(findings)} findings -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
