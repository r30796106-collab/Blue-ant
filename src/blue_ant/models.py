"""Typed models for deterministic task execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


TaskCallable = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """A bounded unit of work.

    The callable is intentionally local and explicit in the MVP. Remote agents
    and model-backed workers will be adapters, not implicit shell execution.
    """

    task_id: str
    run: TaskCallable
    depends_on: tuple[str, ...] = ()
    max_attempts: int = 1
    retry_safe: bool = False
    action: str = "local_task"
    project: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        if not callable(self.run):
            raise ValueError("run must be callable")
        if not isinstance(self.depends_on, tuple) or any(
            not isinstance(dependency, str) or not dependency.strip()
            for dependency in self.depends_on
        ):
            raise ValueError("depends_on must be a tuple of non-empty task ID strings")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on must not contain duplicate task IDs")
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if self.task_id in self.depends_on:
            raise ValueError("a task cannot depend on itself")


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    status: TaskStatus
    attempts: int
    value: Any = None
    error: str | None = None
