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
    action: str = "local_task"
    project: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id must not be empty")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.task_id in self.depends_on:
            raise ValueError("a task cannot depend on itself")


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    status: TaskStatus
    attempts: int
    value: Any = None
    error: str | None = None
