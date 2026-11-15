"""Bounded feedback-loop controller for trusted Blue Ant worker adapters.

The controller never launches shell commands or executes repository code itself.
A host supplies a narrowly scoped executor and a decision callback that converts
worker observations into the next instruction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class LoopInstruction:
    """One bounded instruction addressed to a registered worker adapter."""

    instruction_id: str
    project_id: str
    worker_role: str
    task: str


@dataclass(frozen=True)
class LoopObservation:
    """Result returned by a worker adapter after one instruction."""

    instruction_id: str
    status: str
    summary: str
    details: str = ""


@dataclass(frozen=True)
class LoopReport:
    """Immutable record of one controller run."""

    observations: tuple[LoopObservation, ...]
    stop_reason: str
    cycles_used: int


class WorkerExecutor(Protocol):
    def __call__(self, instruction: LoopInstruction) -> LoopObservation: ...


class NextInstruction(Protocol):
    def __call__(
        self, instruction: LoopInstruction, observation: LoopObservation, cycle: int
    ) -> LoopInstruction | None: ...


class FeedbackLoop:
    """Run worker -> observe -> decide -> worker with a hard cycle limit.

    The decision callback is the integration point for an external controller
    (for example ChatGPT or a separately approved planner). Returning None
    finishes the run. Exceptions at the worker boundary become failed
    observations and are still passed to the decision callback.
    """

    def __init__(self, *, max_cycles: int = 5, audit: object | None = None) -> None:
        if not 1 <= max_cycles <= 10:
            raise ValueError("max_cycles must be between 1 and 10")
        self.max_cycles = max_cycles
        self.audit = audit

    def run(
        self,
        first: LoopInstruction,
        *,
        execute: WorkerExecutor,
        decide_next: NextInstruction,
    ) -> LoopReport:
        current = first
        observations: list[LoopObservation] = []
        seen_ids: set[str] = set()

        for cycle in range(1, self.max_cycles + 1):
            self._validate_instruction(current)
            if current.instruction_id in seen_ids:
                raise ValueError("instruction_id values must be unique within a loop")
            seen_ids.add(current.instruction_id)
            self._record("worker_started", cycle=cycle, instruction_id=current.instruction_id)

            try:
                observation = execute(current)
                if not isinstance(observation, LoopObservation):
                    raise TypeError("worker must return LoopObservation")
                if observation.instruction_id != current.instruction_id:
                    raise ValueError("worker observation instruction_id mismatch")
            except Exception as exc:
                observation = LoopObservation(
                    instruction_id=current.instruction_id,
                    status="failed",
                    summary=f"{type(exc).__name__}: {exc}",
                )

            observations.append(observation)
            self._record(
                "worker_observed",
                cycle=cycle,
                instruction_id=current.instruction_id,
                status=observation.status,
            )

            if cycle == self.max_cycles:
                return LoopReport(tuple(observations), "cycle_limit_reached", cycle)

            following = decide_next(current, observation, cycle)
            if following is None:
                return LoopReport(tuple(observations), "controller_stopped", cycle)
            current = following

        raise AssertionError("unreachable")

    @staticmethod
    def _validate_instruction(instruction: LoopInstruction) -> None:
        for field in ("instruction_id", "project_id", "worker_role", "task"):
            value = getattr(instruction, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string")

    def _record(self, event: str, **details: object) -> None:
        if self.audit is not None:
            record = getattr(self.audit, "record", None)
            if not callable(record):
                raise TypeError("audit must provide record(event, **details)")
            record(event, **details)
