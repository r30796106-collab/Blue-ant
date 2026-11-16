"""CLI for parallel read-only work across multiple checked-out repositories."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .projects import ProjectRegistry
from .resources import ResourcePolicy, ResourceSnapshot
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
    parser.add_argument("--cpu-count", type=int, help="available CPU count for optional resource-aware worker limiting")
    parser.add_argument("--available-memory-mb", type=int, help="available memory in MiB for optional resource-aware worker limiting")
    parser.add_argument("--detect-resources", action="store_true", help="explicitly detect Linux host/cgroup capacity once; mutually exclusive with manual CPU/memory values")
    parser.add_argument("--reserve-memory-mb", type=int, default=512, help="memory to reserve in MiB (default: 512)")
    parser.add_argument("--memory-per-worker-mb", type=int, default=256, help="memory budget per worker in MiB (default: 256)")
    parser.add_argument("--snapshot-sources", action="store_true",
                        help="copy project sources into bounded, private workspace snapshots before auditing")
    parser.add_argument("--shared-snapshot-sources", action="store_true",
                        help="copy once per project and reuse the snapshot across read-only workers; requires --snapshot-sources")
    parser.add_argument("--audit-log", help="append hash-chained workforce events to this JSONL file")
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

        if (args.cpu_count is None) != (args.available_memory_mb is None):
            raise ValueError("--cpu-count and --available-memory-mb must be provided together")
        if args.detect_resources and args.cpu_count is not None:
            raise ValueError("--detect-resources cannot be combined with --cpu-count or --available-memory-mb")
        resource_policy = None
        resource_snapshot = None
        if args.detect_resources:
            resource_policy = ResourcePolicy(
                max_workers=args.max_workers,
                reserve_memory_bytes=args.reserve_memory_mb * 1024 * 1024,
                memory_per_worker_bytes=args.memory_per_worker_mb * 1024 * 1024,
            )
            resource_snapshot = ResourceSnapshot.detect()
        elif args.cpu_count is not None:
            resource_policy = ResourcePolicy(
                max_workers=args.max_workers,
                reserve_memory_bytes=args.reserve_memory_mb * 1024 * 1024,
                memory_per_worker_bytes=args.memory_per_worker_mb * 1024 * 1024,
            )
            resource_snapshot = ResourceSnapshot(
                cpu_count=args.cpu_count,
                available_memory_bytes=args.available_memory_mb * 1024 * 1024,
            )
        workforce = Workforce(
            registry,
            max_workers=args.max_workers,
            snapshot_sources=args.snapshot_sources,
            shared_snapshot_sources=args.shared_snapshot_sources,
            resource_policy=resource_policy,
            resource_snapshot=resource_snapshot,
            audit_path=args.audit_log,
        )
        results = workforce.run(assignments)
        audit_verification = workforce.audit.verify() if workforce.audit is not None else None
        payload = {
            "schema_version": 1,
            "mode": "parallel_read_only_multi_project",
            "projects": [{"project_id": project_id, "source_root": str(path.resolve())}
                         for project_id, path in projects],
            "max_workers": args.max_workers,
            "requested_max_workers": workforce.requested_max_workers,
            "effective_max_workers": workforce.max_workers,
            "audit_log": str(workforce.audit.path) if workforce.audit is not None else None,
            "audit_verification": (
                {
                    "valid": audit_verification.valid,
                    "records": audit_verification.records,
                    "last_hash": audit_verification.last_hash,
                    "error": audit_verification.error,
                } if audit_verification is not None else None
            ),
            "resource_detection": ("linux_procfs_cgroup_opt_in" if args.detect_resources else "caller_supplied" if resource_snapshot is not None else None),
            "resource_snapshot": (
                {
                    "cpu_count": resource_snapshot.cpu_count,
                    "available_memory_bytes": resource_snapshot.available_memory_bytes,
                    "reserve_memory_bytes": resource_policy.reserve_memory_bytes,
                    "memory_per_worker_bytes": resource_policy.memory_per_worker_bytes,
                } if resource_snapshot is not None and resource_policy is not None else None
            ),
            "workspace_mode": "bounded_source_snapshot" if args.snapshot_sources else "read_only_source_reference",
            "snapshot_strategy": (
                "shared_project" if args.shared_snapshot_sources
                else "per_task" if args.snapshot_sources
                else "source_reference"
            ),
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
                "Each assignment has a separate task workspace; shared-snapshot mode reuses one bounded source copy per project.",
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
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
