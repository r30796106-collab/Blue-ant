"""Bounded, dependency-aware concurrent task execution."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Callable

from .controller import BlueAntController
from .models import Task, TaskStatus
from .resources import ResourceBudget


TaskHandler = Callable[[Task], object]


class Scheduler:
    """Run registered task handlers with worker and memory admission limits.

    Handlers are trusted in-process callables. This scheduler is not a sandbox;
    untrusted code must run behind a separate isolated execution adapter.
    """

    def __init__(self, controller: BlueAntController, budget: ResourceBudget) -> None:
        self.controller = controller
        self.budget = budget

    def run(self, handlers: dict[str, TaskHandler]) -> dict[str, TaskStatus]:
        in_flight: dict[Future, Task] = {}
        used_memory = 0

        with ThreadPoolExecutor(max_workers=self.budget.max_workers) as pool:
            while True:
                for task in self.controller.ready_tasks():
                    if len(in_flight) >= self.budget.max_workers:
                        break
                    if task.worker_role not in handlers:
                        continue
                    required = task.required_memory_mb
                    if self.budget.available_memory_mb is not None:
                        if used_memory + required > self.budget.available_memory_mb:
                            continue
                    self.controller.mark_running(task.task_id)
                    future = pool.submit(handlers[task.worker_role], task)
                    in_flight[future] = task
                    used_memory += required

                if not in_flight:
                    # No runnable work remains, or every ready task lacks a handler
                    # or exceeds the available memory budget.
                    break

                completed, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in completed:
                    task = in_flight.pop(future)
                    used_memory -= task.required_memory_mb
                    try:
                        result = future.result()
                    except Exception as exc:  # handler failures become task state
                        self.controller.mark_failed(task.task_id, f"{type(exc).__name__}: {exc}")
                    else:
                        self.controller.mark_succeeded(task.task_id, result)

        return {
            task_id: record.status
            for task_id, record in self.controller.tasks.items()
        }
