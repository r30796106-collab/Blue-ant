"""Deterministic worker limits from caller-supplied device capacity."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """A point-in-time capacity snapshot; collection is platform-specific."""

    cpu_count: int
    available_memory_bytes: int

    def __post_init__(self) -> None:
        if self.cpu_count < 1:
            raise ValueError("cpu_count must be at least 1")
        if self.available_memory_bytes < 0:
            raise ValueError("available_memory_bytes must not be negative")


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    """Calculate a conservative worker cap without probing the host itself."""

    max_workers: int = 4
    reserve_memory_bytes: int = 512 * 1024 * 1024
    memory_per_worker_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if self.reserve_memory_bytes < 0:
            raise ValueError("reserve_memory_bytes must not be negative")
        if self.memory_per_worker_bytes < 1:
            raise ValueError("memory_per_worker_bytes must be at least 1")

    def worker_limit(self, snapshot: ResourceSnapshot) -> int:
        """Return a safe positive worker cap; never exceed configured or CPU limits."""
        usable = max(0, snapshot.available_memory_bytes - self.reserve_memory_bytes)
        memory_cap = usable // self.memory_per_worker_bytes
        if memory_cap < 1:
            raise ValueError("insufficient available memory for one worker")
        return min(self.max_workers, snapshot.cpu_count, memory_cap)
