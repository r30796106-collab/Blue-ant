"""CLI for parallel read-only work across multiple checked-out repositories."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .projects import ProjectRegistry
from .subbots import SubBotRole
from .workforce import WorkAssignment, Workforce


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded Blue Ant workers across repositories")
    parser.add_argument("--project", action="append", required=True, metavar="ID=PATH",
                        help="Registered project checkout; repeat for multiple repositories")
    parser.add_argument("--roles", default=",".join(role.value for role in SubBotRole),
                        help="Comma-separated approved specialist roles")
    parser.add_argument("--workspace-root", default=".blue-ant/workspaces")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--snapshot-sources", action="store_true",
                        help="copy each project into a bounded, private task workspace before auditing")
    parser.add_argument("--output", default="blue-ant-workforce-report.json")
    args = parser.parse_args()

    try:
        roles = tuple(SubBotRole(value.strip()) for value in args.roles.split(",") if value.strip())
        if not roles or len(set(roles)) != len(roles):
            raise ValueError("roles must be a non-empty, unique list of approved roles")
        registry = ProjectRegistry(args.workspace_root)
        projects: list[tuple[str, Path]] = []
        for value in args.project:
            project_id, separator, raw_path = value.partition("=")
            if not separator or not project_id or not raw_path:
                raise ValueError("--project must use ID=PATH")
            registry.register(project_id, raw_path)
            projects.append((project_id, Path(raw_path)))

        assignments = []
        for index, (project_id, _) in enumerate(projects):
            for role in roles:
                task_id = f"task-{index}-{project_id[:20]}-{role.value}"
                assignments.append(WorkAssignment(task_id, project_id, role))

        results = Workforce(registry, max_workers=args.max_workers, snapshot_sources=args.snapshot_sources).run(assignments)
        payload = {
            "schema_version": 1,
            "mode": "parallel_read_only_multi_project",
            "projects": [{"project_id": project_id, "source_root": str(path.resolve())}
                         for project_id, path in projects],
            "max_workers": args.max_workers,
            "workspace_mode": "bounded_source_snapshot" if args.snapshot_sources else "read_only_source_reference",
            "assignments": [{
                "task_id": item.task_id,
                "project_id": item.project_id,
                "role": item.role,
                "source_root": str(item.source_root),
                "workspace": str(item.workspace),
                "error": item.error,
                "findings": [{
                    "bot_id": finding.bot_id, "role": finding.role,
                    "severity": finding.severity, "path": finding.path,
                    "message": finding.message,
                } for finding in item.findings],
            } for item in results],
            "limitations": [
                "Built-in workers are read-only auditors; they do not write or execute project code.",
                "Each assignment has a separate task workspace; snapshot mode copies bounded source files into it.",
                "Snapshots exclude common generated directories and credential-like files, reject symlinks, and are not OS sandboxes.",
                "Workspace directories are not an operating-system security sandbox.",
                "Security findings are heuristic and require human review.",
            ],
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        failed = sum(item.error is not None for item in results)
        print(f"Blue Ant workforce: {len(projects)} projects, {len(results)} parallel assignments, {failed} errors -> {output}")
        return 1 if failed else 0
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
