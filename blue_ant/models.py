"""Core immutable task and worker models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    project: str
    wing: str
    title: str
    worker_role: str = "general"
    depends_on: tuple[str, ...] = ()
    required_memory_mb: int = 0
    max_attempts: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("task_id", "project", "wing", "title", "worker_role"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.required_memory_mb < 0:
            raise ValueError("required_memory_mb cannot be negative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.task_id in self.depends_on:
            raise ValueError("a task cannot depend on itself")


@dataclass(frozen=True, slots=True)
class WorkerTemplate:
    role: str
    capabilities: tuple[str, ...]
    max_concurrency: int = 1
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("worker role must not be empty")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")


@dataclass(slots=True)
class TaskRecord:
    task: Task
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    result: Any = None
    error: str | None = None
