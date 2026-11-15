from __future__ import annotations

import threading
import time

import pytest

from blue_ant import Scheduler, TaskSpec, TaskStatus
from blue_ant.policy import Policy


def test_independent_tasks_run_concurrently() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def work() -> str:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.08)
        with lock:
            active -= 1
        return "ok"

    scheduler = Scheduler(max_workers=2)
    results = scheduler.run([TaskSpec("a", work), TaskSpec("b", work)])

    assert all(result.status == TaskStatus.SUCCEEDED for result in results.values())
    assert peak == 2


def test_dependency_runs_after_parent() -> None:
    seen: list[str] = []
    tasks = [
        TaskSpec("first", lambda: seen.append("first")),
        TaskSpec("second", lambda: seen.append("second"), depends_on=("first",)),
    ]

    Scheduler().run(tasks)

    assert seen == ["first", "second"]


def test_failed_dependency_blocks_child() -> None:
    results = Scheduler().run(
        [
            TaskSpec("bad", lambda: 1 / 0),
            TaskSpec("child", lambda: "should not run", depends_on=("bad",)),
        ]
    )

    assert results["bad"].status == TaskStatus.FAILED
    assert results["child"].status == TaskStatus.BLOCKED


def test_retry_is_bounded() -> None:
    attempts = 0

    def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary")
        return "recovered"

    result = Scheduler().run([TaskSpec("flaky", flaky, max_attempts=3)])["flaky"]

    assert attempts == 3
    assert result.status == TaskStatus.SUCCEEDED
    assert result.attempts == 3


def test_unknown_dependency_and_cycle_rejected() -> None:
    with pytest.raises(ValueError, match="unknown dependencies"):
        Scheduler().run([TaskSpec("a", lambda: None, depends_on=("missing",))])

    with pytest.raises(ValueError, match="cycle"):
        Scheduler().run(
            [
                TaskSpec("a", lambda: None, depends_on=("b",)),
                TaskSpec("b", lambda: None, depends_on=("a",)),
            ]
        )


def test_policy_denies_unapproved_side_effect() -> None:
    policy = Policy()
    assert policy.check("test")
    assert not policy.check("deploy")
    assert policy.check("deploy", frozenset({"deploy"}))
    assert not policy.check("unknown_action")
