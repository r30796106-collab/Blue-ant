"""Resource-aware admission controls (no platform probing in the core)."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    max_workers: int = 2
    available_memory_mb: int | None = None

    def __post_init__(self) -> None:
        if self.max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if self.available_memory_mb is not None and self.available_memory_mb < 0:
            raise ValueError("available_memory_mb cannot be negative")

    def permits(self, required_memory_mb: int) -> bool:
        if required_memory_mb < 0:
            return False
        return (
            self.available_memory_mb is None
            or required_memory_mb <= self.available_memory_mb
        )
