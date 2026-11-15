"""CLI for creating a dry-run hash-checked proposal from a reviewed plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .controlled_proposal import build_patch_proposal, proposal_to_dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a non-applied patch proposal for one reviewed plan task")
    parser.add_argument("--workspace", required=True, help="Read-only target workspace snapshot")
    parser.add_argument("--plan", required=True, help="Development plan JSON")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--change", required=True, help="JSON file containing exactly path and content")
    parser.add_argument("--output", default="blue-ant-proposal.json")
    args = parser.parse_args(argv)
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        change = json.loads(Path(args.change).read_text(encoding="utf-8"))
        proposal = build_patch_proposal(args.workspace, plan, args.task_id, [change])
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(proposal_to_dict(proposal), indent=2) + "\\n", encoding="utf-8")
        print(f"PROPOSAL ONLY: {proposal.proposal_id}")
        print(f"Task: {proposal.task_id}; file: {proposal.changes[0].path}")
        print("Not applied. Human review and explicit approval are still required.")
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, PermissionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
