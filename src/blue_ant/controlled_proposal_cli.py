"""CLI for creating dry-run hash-checked proposals from reviewed plan tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .controlled_proposal import build_patch_proposal, proposal_to_dict
from .json_utils import strict_json_loads
from .portfolio import PortfolioRegistry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a non-applied hash-checked proposal for a reviewed plan task")
    parser.add_argument("--workspace", required=True, help="Read-only target workspace snapshot")
    parser.add_argument("--plan", required=True, help="Development plan JSON")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--portfolio", required=True, help="Approved portfolio registry JSON")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--change", help="JSON file containing exactly path and content (single-file compatibility)")
    source.add_argument("--changes", help="JSON file containing an array of path/content objects (multi-file mode)")
    parser.add_argument("--output", default="blue-ant-proposal.json")
    args = parser.parse_args(argv)
    try:
        plan = strict_json_loads(Path(args.plan).read_text(encoding="utf-8"))
        changes = strict_json_loads(Path(args.changes if args.changes else args.change).read_text(encoding="utf-8"))
        if args.change:
            changes = [changes]
        portfolio = PortfolioRegistry.load(args.portfolio)
        proposal = build_patch_proposal(args.workspace, plan, args.task_id, changes, portfolio_registry=portfolio)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(proposal_to_dict(proposal), indent=2) + "\n", encoding="utf-8")
        print(f"PROPOSAL ONLY: {proposal.proposal_id}")
        print(f"Task: {proposal.task_id}; files: {len(proposal.changes)}")
        print("Not applied. Human review and explicit approval are still required.")
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, PermissionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
