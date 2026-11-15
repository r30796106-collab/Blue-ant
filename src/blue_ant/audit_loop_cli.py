"""CLI for bounded sequential read-only specialist audits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit_loop import BoundedAuditLoop
from .projects import ProjectRegistry
from .subbots import SubBotRole
from .workforce import WorkAssignment, Workforce


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded sequential Blue Ant audit loop")
    parser.add_argument("--project", required=True, metavar="ID=PATH")
    parser.add_argument("--roles", default="repo_analyst,test_auditor,docs_auditor,safety_auditor")
    parser.add_argument("--max-cycles", type=int, default=4)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--workspace-root", default=".blue-ant/workspaces")
    parser.add_argument("--task", default="Run the selected fixed read-only repository audits")
    parser.add_argument("--output", default="blue-ant-audit-loop-report.json")
    args = parser.parse_args()

    try:
        project_id, separator, raw_path = args.project.partition("=")
        if not separator or not project_id or not raw_path:
            raise ValueError("--project must use ID=PATH")
        roles = tuple(SubBotRole(value.strip()) for value in args.roles.split(",") if value.strip())
        registry = ProjectRegistry(args.workspace_root)
        registry.register(project_id, raw_path)
        workforce = Workforce(registry, max_workers=args.max_workers)

        def execute(role: SubBotRole, cycle: int):
            assignment = WorkAssignment(
                f"cycle-{cycle}-{role.value.replace('_', '-')}",
                project_id,
                role,
            )
            return workforce.run([assignment])[0]

        report = BoundedAuditLoop(max_cycles=args.max_cycles).run(roles, execute=execute)
        payload = {
            "schema_version": 1,
            "mode": "bounded_sequential_read_only_audit_loop",
            "project_id": project_id,
            "task_context": args.task,
            "cycles_used": report.cycles_used,
            "stop_reason": report.stop_reason,
            "cycles": [
                {
                    "cycle": item.cycle,
                    "role": item.role,
                    "task_id": item.task_id,
                    "status": item.status,
                    "error": item.error,
                    "findings": list(item.findings),
                }
                for item in report.cycles
            ],
            "limitations": [
                "Task context is metadata; it is not executed as code or shell commands.",
                "Only the four fixed read-only specialist templates are supported.",
                "The next-step policy advances through the supplied role list after success and stops on worker error.",
                "A successful audit is not a code change or a security certification.",
            ],
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Blue Ant audit loop: {report.cycles_used} cycles, stop={report.stop_reason} -> {output}")
        return 1 if report.stop_reason == "worker_error" else 0
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
