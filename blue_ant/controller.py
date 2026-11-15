"""Minimal deterministic task registry and dependency validation."""
from __future__ import annotations

from .models import Task, TaskRecord, TaskStatus, WorkerTemplate


class BlueAntController:
    def __init__(self) -> None:
        self.tasks: dict[str, TaskRecord] = {}
        self.workers: dict[str, WorkerTemplate] = {}

    def register_worker(self, template: WorkerTemplate) -> None:
        self.workers[template.role] = template

    def submit(self, task: Task) -> TaskRecord:
        if task.task_id in self.tasks:
            raise ValueError(f"duplicate task id: {task.task_id}")
        unknown = set(task.depends_on) - self.tasks.keys()
        if unknown:
            raise ValueError(f"unknown dependencies: {sorted(unknown)}")
        if task.worker_role in self.workers and not self.workers[task.worker_role].enabled:
            raise ValueError(f"worker role is disabled: {task.worker_role}")
        record = TaskRecord(task=task)
        self.tasks[task.task_id] = record
        self._refresh_readiness()
        return record

    def _refresh_readiness(self) -> None:
        for record in self.tasks.values():
            if record.status not in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.BLOCKED):
                continue
            dependencies = [self.tasks[item].status for item in record.task.depends_on]
            if any(status in (TaskStatus.FAILED, TaskStatus.CANCELLED) for status in dependencies):
                record.status = TaskStatus.BLOCKED
            elif all(status is TaskStatus.SUCCEEDED for status in dependencies):
                record.status = TaskStatus.READY
            else:
                record.status = TaskStatus.PENDING

    def ready_tasks(self) -> list[Task]:
        self._refresh_readiness()
        return [
            record.task for record in self.tasks.values()
            if record.status is TaskStatus.READY
        ]

    def mark_running(self, task_id: str) -> None:
        record = self.tasks[task_id]
        if record.status is not TaskStatus.READY:
            raise ValueError("only ready tasks can start")
        record.status = TaskStatus.RUNNING
        record.attempts += 1

    def mark_succeeded(self, task_id: str, result=None) -> None:
        record = self.tasks[task_id]
        if record.status is not TaskStatus.RUNNING:
            raise ValueError("only running tasks can succeed")
        record.status, record.result, record.error = TaskStatus.SUCCEEDED, result, None
        self._refresh_readiness()

    def mark_failed(self, task_id: str, error: str) -> None:
        record = self.tasks[task_id]
        if record.status is not TaskStatus.RUNNING:
            raise ValueError("only running tasks can fail")
        record.error = error
        record.status = (
            TaskStatus.READY if record.attempts < record.task.max_attempts
            else TaskStatus.FAILED
        )
        self._refresh_readiness()
