"""Parallel bridge V3 runner: dispatch approved auditors and evaluate their results."""
from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from .bridge import load_bridge_command
from .bridge_controller import decision_to_dict, evaluate_bridge_result
from .development_plan import generate_development_plan, plan_to_dict
from .projects import ProjectRegistry
from .subbots import SubBotRole
from .workforce import WorkAssignment, Workforce


def _write_artifact(path: Path, content: bytes) -> None:
    """Atomically replace one artifact without following a final symlink."""
    fd, temporary = tempfile.mkstemp(prefix=".blue-ant-artifact-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _prepare_output_directory(path: Path) -> None:
    """Create output directories component-by-component without following symlinks."""
    absolute = Path(os.path.abspath(path))
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor, os.O_RDONLY | directory_flag | nofollow)
    try:
        for component in absolute.parts[1:]:
            try:
                os.mkdir(component, mode=0o777, dir_fd=descriptor)
            except FileExistsError:
                pass
            try:
                next_descriptor = os.open(
                    component,
                    os.O_RDONLY | directory_flag | nofollow,
                    dir_fd=descriptor,
                )
            except OSError as exc:
                raise ValueError(
                    "output_dir and its parent directories must be real, non-symlink directories"
                ) from exc
            os.close(descriptor)
            descriptor = next_descriptor
    finally:
        os.close(descriptor)


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
    _prepare_output_directory(output)

    # Keep private source snapshots outside the artifact directory so the
    # GitHub workflow uploads reports, not copied project source trees.
    workspace_root = output.parent / ".blue-ant-workspaces" / command["command_id"]
    registry = ProjectRegistry(workspace_root)
    registry.register(command["project_id"], target_path)
    workforce = Workforce(
        registry,
        max_workers=min(4, command["max_cycles"]),
        snapshot_sources=command["snapshot_sources"],
        shared_snapshot_sources=command["snapshot_sources"],
        audit_path=workspace_root / "workforce-audit.jsonl",
    )

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
    audit_verification = workforce.audit.verify() if workforce.audit is not None else None
    if audit_verification is None or not audit_verification.valid:
        raise ValueError("workforce execution audit failed verification")
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
        "mode": "bounded_parallel_read_only_audit",
        "project_id": command["project_id"],
        "task_context": command["task"],
        "cycles_used": len(cycles),
        "stop_reason": "worker_error" if any(c["status"] == "failed" for c in cycles) else "sequence_completed",
        "cycles": cycles,
        "execution_mode": "parallel_read_only_specialists",
        "workspace_mode": "bounded_source_snapshot" if command["snapshot_sources"] else "read_only_source_reference",
        "execution_audit": {
            "valid": audit_verification.valid,
            "records": audit_verification.records,
            "last_hash": audit_verification.last_hash,
        },
        "limitations": [
            "All selected fixed specialists run concurrently; task context is metadata only.",
            "Workers inspect repository text and do not execute target code or tests.",
            "Snapshot mode excludes common generated and credential-like paths, rejects symlinks, and is not an OS sandbox.",
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
    event_log_name = f"{command_id}-events.jsonl"
    event_log_source = Path(workforce.audit.path)
    event_log_target = output / event_log_name
    _write_artifact(event_log_target, event_log_source.read_bytes())
    artifact_paths = {key: f"{command_id}-{key}.json" for key in artifacts}
    artifact_paths["event_log"] = event_log_name
    for suffix, payload in artifacts.items():
        _write_artifact(
            output / f"{command_id}-{suffix}.json",
            (json.dumps(payload, indent=2) + "\n").encode("utf-8"),
        )
    return {
        "command_id": command_id,
        "status": decision["status"],
        "action": decision["action"],
        "workers_completed": len(cycles),
        "workers_failed": sum(c["status"] == "failed" for c in cycles),
        "artifacts": artifact_paths,
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
