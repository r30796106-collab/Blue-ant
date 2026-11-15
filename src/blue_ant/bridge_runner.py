"""Parallel bridge V3 runner: dispatch approved auditors and evaluate their results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .bridge import load_bridge_command
from .bridge_controller import decision_to_dict, evaluate_bridge_result
from .development_plan import generate_development_plan, plan_to_dict
from .projects import ProjectRegistry
from .subbots import SubBotRole
from .workforce import WorkAssignment, Workforce


def run_bridge_command(
    command_path: str | Path,
    target_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Run up to four pre-authorized read-only specialists concurrently.

    The runner only reads the checked-out target. It emits an audit report,
    a human-review plan, and a deterministic controller decision. It never
    executes target code, creates patches, approves changes, or writes to the
    target repository.
    """
    command = load_bridge_command(command_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    registry = ProjectRegistry(output / "workspaces")
    registry.register(command["project_id"], target_path)
    workforce = Workforce(registry, max_workers=min(4, command["max_cycles"]))

    roles = [SubBotRole(role) for role in command["roles"][: command["max_cycles"]]]
    assignments = [
        WorkAssignment(
            task_id=f"cycle-{index}-{role.value.replace('_', '-')}",
            project_id=command["project_id"],
            role=role,
        )
        for index, role in enumerate(roles, start=1)
    ]
    results = workforce.run(assignments)
    by_task = {result.task_id: result for result in results}
    cycles = []
    for assignment in assignments:
        result = by_task[assignment.task_id]
        cycles.append({
            "cycle": len(cycles) + 1,
            "role": result.role,
            "task_id": result.task_id,
            "status": "failed" if result.error else "success",
            "error": result.error,
            "findings": [
                {
                    "bot_id": finding.bot_id,
                    "role": finding.role,
                    "severity": finding.severity,
                    "path": finding.path,
                    "message": finding.message,
                }
                for finding in result.findings
            ],
        })

    audit_report = {
        "schema_version": 1,
        "mode": "bounded_sequential_read_only_audit_loop",
        "project_id": command["project_id"],
        "task_context": command["task"],
        "cycles_used": len(cycles),
        "stop_reason": "worker_error" if any(c["status"] == "failed" for c in cycles) else "sequence_completed",
        "cycles": cycles,
        "execution_mode": "parallel_read_only_specialists",
        "limitations": [
            "All selected fixed specialists run concurrently; task context is metadata only.",
            "Workers inspect repository text and do not execute target code or tests.",
            "Findings are heuristic and require independent human verification.",
        ],
    }
    plan = plan_to_dict(generate_development_plan(
        audit_report,
        project_id=command["project_id"],
        target_repository=command["repository"],
        target_ref=command["ref"],
    ))
    decision = decision_to_dict(evaluate_bridge_result({
        "schema_version": 1,
        "command": command,
        "audit_report": audit_report,
        "plan": plan,
    }))

    command_id = command["command_id"]
    artifacts = {
        "audit": audit_report,
        "plan": plan,
        "decision": decision,
    }
    for suffix, payload in artifacts.items():
        (output / f"{command_id}-{suffix}.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
    return {
        "command_id": command_id,
        "status": decision["status"],
        "action": decision["action"],
        "workers_completed": len(cycles),
        "workers_failed": sum(c["status"] == "failed" for c in cycles),
        "artifacts": {key: f"{command_id}-{key}.json" for key in artifacts},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the parallel Blue Ant ChatGPT bridge V3")
    parser.add_argument("--command", required=True, help="Validated bridge command JSON")
    parser.add_argument("--target-path", required=True, help="Read-only checked-out target directory")
    parser.add_argument("--output-dir", required=True, help="Directory for JSON reports")
    args = parser.parse_args()
    try:
        result = run_bridge_command(args.command, args.target_path, args.output_dir)
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
