"""Bounded deterministic sequential audit loop over approved read-only specialists."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .subbots import SubBotRole
from .workforce import WorkResult


@dataclass(frozen=True, slots=True)
class AuditCycle:
    cycle: int
    role: str
    task_id: str
    status: str
    findings: tuple[dict[str, str], ...]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AuditLoopReport:
    cycles: tuple[AuditCycle, ...]
    stop_reason: str
    cycles_used: int


AuditExecutor = Callable[[SubBotRole, int], WorkResult]


class BoundedAuditLoop:
    """Run a caller-selected role sequence, stopping immediately on worker error.

    The only automatic decision is deterministic: advance to the next explicitly
    supplied role after success; stop on error or at the hard cycle limit.
    Workers remain the existing read-only specialists.
    """

    def __init__(self, *, max_cycles: int = 4) -> None:
        if not 1 <= max_cycles <= 4:
            raise ValueError("max_cycles must be between 1 and 4")
        self.max_cycles = max_cycles

    def run(
        self,
        roles: Sequence[SubBotRole],
        *,
        execute: AuditExecutor,
    ) -> AuditLoopReport:
        selected = tuple(roles)
        if not selected:
            raise ValueError("at least one approved specialist role is required")
        if len(selected) > 4:
            raise ValueError("at most four specialist roles may be selected")
        if any(not isinstance(role, SubBotRole) for role in selected):
            raise ValueError("roles must use approved SubBotRole values")
        if len(set(selected)) != len(selected):
            raise ValueError("duplicate specialist roles are not allowed")

        cycles: list[AuditCycle] = []
        for cycle, role in enumerate(selected[: self.max_cycles], start=1):
            task_id = f"cycle-{cycle}-{role.value.replace('_', '-')}"
            try:
                result = execute(role, cycle)
                if not isinstance(result, WorkResult):
                    raise TypeError("audit executor must return WorkResult")
                if result.role != role.value:
                    raise ValueError("worker result role does not match requested role")
                if result.task_id != task_id:
                    raise ValueError("worker result task_id does not match requested cycle")
                findings = tuple(
                    {
                        "bot_id": item.bot_id,
                        "role": item.role,
                        "severity": item.severity,
                        "path": item.path,
                        "message": item.message,
                    }
                    for item in result.findings
                )
                status = "failed" if result.error else "success"
                cycles.append(AuditCycle(cycle, role.value, result.task_id, status, findings, result.error))
            except Exception as exc:
                cycles.append(AuditCycle(cycle, role.value, task_id, "failed", (), f"{type(exc).__name__}: {exc}"))
                return AuditLoopReport(tuple(cycles), "worker_error", len(cycles))

            # Feed the observation into the deterministic next-step policy.
            # A successful result advances; any worker error stops the loop.
            if result.error:
                return AuditLoopReport(tuple(cycles), "worker_error", len(cycles))

        if len(cycles) < len(selected):
            reason = "cycle_limit_reached"
        else:
            reason = "sequence_completed"
        return AuditLoopReport(tuple(cycles), reason, len(cycles))
