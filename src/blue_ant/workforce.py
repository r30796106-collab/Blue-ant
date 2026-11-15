"""Parallel, bounded workforce execution across registered repositories."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from .audit import AuditLog
from .projects import ProjectRegistry
from .resources import ResourcePolicy, ResourceSnapshot
from .subbots import Finding, SubBotFactory, SubBotRole
from .workspace_snapshot import create_workspace_snapshot


_TASK_ID = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


@dataclass(frozen=True, slots=True)
class WorkAssignment:
    """One specialist task against one registered project."""

    task_id: str
    project_id: str
    role: SubBotRole


@dataclass(frozen=True, slots=True)
class WorkResult:
    task_id: str
    project_id: str
    role: str
    source_root: Path
    workspace: Path
    findings: tuple[Finding, ...]
    error: str | None = None


class Workforce:
    """Run specialist tasks concurrently with separate task workspaces.

    By default, read-only specialists inspect the registered source directly.
    Set snapshot_sources=True to inspect a bounded private copy in each task
    workspace. Snapshots exclude common generated directories and credential
    files, reject symlinks, and never modify the registered source.
    """

    def __init__(
        self,
        registry: ProjectRegistry,
        *,
        max_workers: int = 4,
        max_tasks: int = 64,
        snapshot_sources: bool = False,
        resource_policy: ResourcePolicy | None = None,
        resource_snapshot: ResourceSnapshot | None = None,
        audit_path: str | Path | None = None,
    ) -> None:
        if not 1 <= max_workers <= 16:
            raise ValueError("max_workers must be between 1 and 16")
        if not 1 <= max_tasks <= 256:
            raise ValueError("max_tasks must be between 1 and 256")
        if not isinstance(snapshot_sources, bool):
            raise ValueError("snapshot_sources must be a boolean")
        if (resource_policy is None) != (resource_snapshot is None):
            raise ValueError("resource_policy and resource_snapshot must be provided together")
        if resource_policy is not None and not isinstance(resource_policy, ResourcePolicy):
            raise ValueError("resource_policy must be a ResourcePolicy")
        if resource_snapshot is not None and not isinstance(resource_snapshot, ResourceSnapshot):
            raise ValueError("resource_snapshot must be a ResourceSnapshot")
        self.registry = registry
        self.requested_max_workers = max_workers
        self.resource_policy = resource_policy
        self.resource_snapshot = resource_snapshot
        self.max_workers = (
            min(max_workers, resource_policy.worker_limit(resource_snapshot))
            if resource_policy is not None and resource_snapshot is not None
            else max_workers
        )
        self.max_tasks = max_tasks
        self.snapshot_sources = snapshot_sources
        self.audit = AuditLog(audit_path) if audit_path is not None else None

    def run(self, assignments: Iterable[WorkAssignment]) -> tuple[WorkResult, ...]:
        jobs = tuple(assignments)
        if not jobs:
            raise ValueError("at least one work assignment is required")
        if len(jobs) > self.max_tasks:
            raise ValueError("assignments exceed configured max_tasks")
        self._record("workforce_started", assignments=len(jobs), max_workers=self.max_workers, snapshot_sources=self.snapshot_sources)
        ids: set[str] = set()
        prepared: list[tuple[WorkAssignment, Path, Path, Path]] = []
        for job in jobs:
            if not isinstance(job, WorkAssignment):
                raise ValueError("assignments must be WorkAssignment instances")
            if not isinstance(job.task_id, str) or not _TASK_ID.fullmatch(job.task_id):
                raise ValueError("task_id must be a lowercase slug")
            if job.task_id in ids:
                raise ValueError(f"duplicate task_id: {job.task_id}")
            ids.add(job.task_id)
            if not isinstance(job.role, SubBotRole):
                raise ValueError("role must be an approved SubBotRole")
            project = self.registry.get(job.project_id)
            project_workspace = self.registry.workspace_for(job.project_id, create=True)
            tasks_root = project_workspace / "tasks"
            if tasks_root.is_symlink():
                raise ValueError("tasks directory must not be a symlink")
            tasks_root.mkdir(mode=0o700, exist_ok=True)
            if tasks_root.is_symlink() or not tasks_root.is_dir():
                raise ValueError("tasks directory is not a safe directory")
            task_workspace = tasks_root / job.task_id
            if task_workspace.is_symlink():
                raise ValueError("task workspace must not be a symlink")
            resolved = task_workspace.resolve(strict=False)
            try:
                resolved.relative_to(tasks_root.resolve())
            except ValueError as exc:
                raise ValueError("task workspace escapes its tasks directory") from exc

            snapshot_result = None
            if self.snapshot_sources:
                if task_workspace.exists() and (
                    not task_workspace.is_dir() or any(task_workspace.iterdir())
                ):
                    raise ValueError("snapshot task workspace must be absent or empty; refusing to overwrite")
                snapshot_result = create_workspace_snapshot(project.source_root, task_workspace)
                scan_root = snapshot_result.workspace
            else:
                task_workspace.mkdir(mode=0o700, exist_ok=True)
                if task_workspace.is_symlink() or not task_workspace.is_dir():
                    raise ValueError("task workspace is not a safe directory")
                scan_root = project.source_root

            self._record(
                "task_workspace_prepared",
                task_id=job.task_id,
                project_id=job.project_id,
                role=job.role.value,
                workspace=str(task_workspace),
                snapshot_files=snapshot_result.files_copied if snapshot_result else None,
                snapshot_bytes=snapshot_result.bytes_copied if snapshot_result else None,
            )
            prepared.append((job, project.source_root, task_workspace, scan_root))

        def execute(item: tuple[WorkAssignment, Path, Path, Path]) -> WorkResult:
            job, source_root, workspace, scan_root = item
            bot = SubBotFactory(max_bots=1).create_fleet([job.role])[0]
            self._record(
                "worker_started", task_id=job.task_id, project_id=job.project_id, role=job.role.value
            )
            try:
                findings = tuple(bot.run(scan_root))
                self._record(
                    "worker_succeeded", task_id=job.task_id, project_id=job.project_id,
                    role=job.role.value, findings=len(findings),
                )
                return WorkResult(job.task_id, job.project_id, job.role.value, source_root, workspace, findings)
            except Exception as exc:
                self._record(
                    "worker_failed", task_id=job.task_id, project_id=job.project_id,
                    role=job.role.value, error=f"{type(exc).__name__}: {exc}",
                )
                return WorkResult(
                    job.task_id, job.project_id, job.role.value, source_root, workspace, (),
                    f"{type(exc).__name__}: {exc}",
                )

        results: list[WorkResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="blue-ant-worker") as pool:
            futures = [pool.submit(execute, item) for item in prepared]
            for future in as_completed(futures):
                results.append(future.result())
        self._record(
            "workforce_completed",
            assignments=len(results),
            failed=sum(result.error is not None for result in results),
            findings=sum(len(result.findings) for result in results),
        )
        return tuple(sorted(results, key=lambda result: (result.project_id, result.task_id)))

    def _record(self, event: str, **details: object) -> None:
        if self.audit is not None:
            self.audit.record(event, **details)
