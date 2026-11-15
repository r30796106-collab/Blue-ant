"""Parallel, bounded workforce execution across registered repositories."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from .projects import ProjectRegistry
from .subbots import Finding, SubBotFactory, SubBotRole


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
    """Run multiple specialist tasks concurrently across one or many projects.

    Every assignment receives its own task workspace directory. Current
    built-in specialists inspect source roots read-only; they do not yet write
    code. The workspace is reserved for later isolated patch-producing workers.
    """

    def __init__(
        self,
        registry: ProjectRegistry,
        *,
        max_workers: int = 4,
        max_tasks: int = 64,
    ) -> None:
        if not 1 <= max_workers <= 16:
            raise ValueError("max_workers must be between 1 and 16")
        if not 1 <= max_tasks <= 256:
            raise ValueError("max_tasks must be between 1 and 256")
        self.registry = registry
        self.max_workers = max_workers
        self.max_tasks = max_tasks

    def run(self, assignments: Iterable[WorkAssignment]) -> tuple[WorkResult, ...]:
        jobs = tuple(assignments)
        if not jobs:
            raise ValueError("at least one work assignment is required")
        if len(jobs) > self.max_tasks:
            raise ValueError("assignments exceed configured max_tasks")
        ids: set[str] = set()
        prepared: list[tuple[WorkAssignment, Path, Path]] = []
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
            task_workspace = project_workspace / "tasks" / job.task_id
            if task_workspace.is_symlink():
                raise ValueError("task workspace must not be a symlink")
            resolved = task_workspace.resolve(strict=False)
            try:
                resolved.relative_to(project_workspace.resolve())
            except ValueError as exc:
                raise ValueError("task workspace escapes project workspace") from exc
            task_workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
            if task_workspace.is_symlink() or not task_workspace.is_dir():
                raise ValueError("task workspace is not a safe directory")
            prepared.append((job, project.source_root, task_workspace))

        def execute(item: tuple[WorkAssignment, Path, Path]) -> WorkResult:
            job, source_root, workspace = item
            bot = SubBotFactory(max_bots=1).create_fleet([job.role])[0]
            try:
                findings = tuple(bot.run(source_root))
                return WorkResult(job.task_id, job.project_id, job.role.value, source_root, workspace, findings)
            except Exception as exc:
                return WorkResult(
                    job.task_id, job.project_id, job.role.value, source_root, workspace, (),
                    f"{type(exc).__name__}: {exc}",
                )

        results: list[WorkResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="blue-ant-worker") as pool:
            futures = [pool.submit(execute, item) for item in prepared]
            for future in as_completed(futures):
                results.append(future.result())
        return tuple(sorted(results, key=lambda result: (result.project_id, result.task_id)))
