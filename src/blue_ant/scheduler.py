"""Bounded, dependency-aware deterministic task scheduler."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Iterable

from .audit import AuditLog
from .models import TaskResult, TaskSpec, TaskStatus
from .policy import Policy


_MAX_WORKERS = 16
_MAX_TASKS = 256


class Scheduler:
    """Execute independent local tasks concurrently with bounded retries.

    This MVP uses threads for I/O-friendly work. CPU-heavy workloads should use
    a separately bounded process adapter in a later milestone.
    """

    def __init__(
        self,
        max_workers: int = 2,
        policy: Policy | None = None,
        audit_path: str | Path | None = None,
        max_tasks: int = _MAX_TASKS,
    ) -> None:
        if not 1 <= max_workers <= _MAX_WORKERS:
            raise ValueError(f"max_workers must be between 1 and {_MAX_WORKERS}")
        if not 1 <= max_tasks <= _MAX_TASKS:
            raise ValueError(f"max_tasks must be between 1 and {_MAX_TASKS}")
        self.max_workers = max_workers
        self.max_tasks = max_tasks
        self.policy = policy or Policy()
        self.audit = AuditLog(audit_path) if audit_path is not None else None

    def run(
        self,
        tasks: Iterable[TaskSpec],
        *,
        approved_actions: frozenset[str] = frozenset(),
    ) -> dict[str, TaskResult]:
        task_list = list(tasks)
        if len(task_list) > self.max_tasks:
            raise ValueError("tasks exceed configured max_tasks")
        by_id = {task.task_id: task for task in task_list}
        if len(by_id) != len(task_list):
            raise ValueError("task_id values must be unique")
        for task in task_list:
            unknown = set(task.depends_on) - by_id.keys()
            if unknown:
                raise ValueError(f"{task.task_id} has unknown dependencies: {sorted(unknown)}")
            if not self.policy.check(task.action, approved_actions):
                raise PermissionError(f"action not permitted without approval: {task.action}")

        self._check_cycles(by_id)
        results: dict[str, TaskResult] = {}
        pending = set(by_id)
        running: dict[Future[object], tuple[TaskSpec, int]] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="blue-ant") as pool:
            while pending or running:
                # A dependency that failed or was blocked prevents downstream work.
                for task_id in tuple(pending):
                    task = by_id[task_id]
                    dependency_results = [results.get(dep) for dep in task.depends_on]
                    if any(r is not None and r.status != TaskStatus.SUCCEEDED for r in dependency_results):
                        results[task_id] = TaskResult(task_id, TaskStatus.BLOCKED, 0, error="dependency did not succeed")
                        pending.remove(task_id)
                        self._record("task_blocked", task_id=task_id)

                while len(running) < self.max_workers:
                    ready = next(
                        (
                            by_id[task_id]
                            for task_id in sorted(pending)
                            if all(
                                dep in results and results[dep].status == TaskStatus.SUCCEEDED
                                for dep in by_id[task_id].depends_on
                            )
                        ),
                        None,
                    )
                    if ready is None:
                        break
                    pending.remove(ready.task_id)
                    future = pool.submit(ready.run)
                    running[future] = (ready, 1)
                    self._record("task_started", task_id=ready.task_id, attempt=1)

                if not running:
                    if pending:
                        raise RuntimeError("scheduler stalled with unresolved dependencies")
                    break

                completed, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in completed:
                    task, attempt = running.pop(future)
                    try:
                        value = future.result()
                    except Exception as exc:  # task boundary: capture worker failure
                        self._record("task_attempt_failed", task_id=task.task_id, attempt=attempt, error_type=type(exc).__name__)
                        if task.retry_safe and attempt < task.max_attempts:
                            retry = pool.submit(task.run)
                            running[retry] = (task, attempt + 1)
                            self._record("task_retry", task_id=task.task_id, attempt=attempt + 1)
                        else:
                            results[task.task_id] = TaskResult(
                                task.task_id, TaskStatus.FAILED, attempt, error=f"{type(exc).__name__}: {exc}"
                            )
                    else:
                        results[task.task_id] = TaskResult(task.task_id, TaskStatus.SUCCEEDED, attempt, value=value)
                        self._record("task_succeeded", task_id=task.task_id, attempts=attempt)

        return results

    @staticmethod
    def _check_cycles(tasks: dict[str, TaskSpec]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("task dependency cycle detected")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in tasks[task_id].depends_on:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in tasks:
            visit(task_id)

    def _record(self, event: str, **details: object) -> None:
        if self.audit is not None:
            self.audit.record(event, **details)
