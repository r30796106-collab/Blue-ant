"""CLI for reviewing and explicitly applying Blue Ant patch proposals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .audit import AuditLog
from .patches import FileChange, PatchProposal, apply_patch_proposal
from .json_utils import strict_json_loads
from .portfolio import PortfolioRegistry


def load_proposal(path: str | Path) -> PatchProposal:
    """Load a strict JSON patch proposal from disk."""
    raw = strict_json_loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"proposal_id", "project_id", "task_id", "changes"}:
        raise ValueError("proposal must contain exactly proposal_id, project_id, task_id, changes")
    if not isinstance(raw["changes"], list):
        raise ValueError("changes must be a JSON array")
    changes = []
    for item in raw["changes"]:
        if not isinstance(item, dict) or set(item) != {"path", "content", "expected_sha256"}:
            raise ValueError("each change must contain exactly path, content, expected_sha256")
        changes.append(FileChange(**item))
    return PatchProposal(
        proposal_id=raw["proposal_id"],
        project_id=raw["project_id"],
        task_id=raw["task_id"],
        changes=tuple(changes),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review and apply a Blue Ant patch proposal")
    parser.add_argument("--workspace", required=True, help="Dedicated disposable workspace")
    parser.add_argument("--proposal", required=True, help="Path to proposal JSON")
    parser.add_argument("--portfolio", required=True, help="Approved portfolio registry JSON")
    parser.add_argument("--approve", action="store_true", help="Explicitly approve and apply changes")
    parser.add_argument("--audit-log", help="Override the default hash-chained workspace audit log path")
    args = parser.parse_args(argv)

    try:
        proposal = load_proposal(args.proposal)
        portfolio = PortfolioRegistry.load(args.portfolio)
        portfolio.validate_paths(proposal.project_id, [change.path for change in proposal.changes])
        print(f"Proposal: {proposal.proposal_id}")
        print(f"Project/task: {proposal.project_id}/{proposal.task_id}")
        for change in proposal.changes:
            operation = "create" if change.expected_sha256 is None else "replace"
            print(f"  {operation}: {change.path}")
        if not args.approve:
            print("DRY RUN ONLY — review the proposal, then rerun with --approve.")
            return 0
        audit_path = Path(args.audit_log) if args.audit_log else Path(args.workspace) / ".blue-ant" / "patch-audit.jsonl"
        audit = AuditLog(audit_path)
        result = apply_patch_proposal(args.workspace, proposal, approved=True, audit=audit, portfolio_registry=portfolio)
        verification = audit.verify()
        if not verification.valid:
            raise RuntimeError(f"audit log failed verification: {verification.error}")
        print(f"APPLIED: {len(result.changed_paths)} file(s)")
        print(f"AUDIT VERIFIED: {verification.records} record(s) -> {audit.path}")
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, json.JSONDecodeError, PermissionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
