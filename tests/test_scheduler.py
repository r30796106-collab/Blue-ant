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

    result = Scheduler().run([TaskSpec("flaky", flaky, max_attempts=3, retry_safe=True)])["flaky"]

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


def test_approval_required_action_runs_only_with_explicit_approval() -> None:
    task = TaskSpec("write", lambda: "written", action="write_files")

    with pytest.raises(PermissionError, match="write_files"):
        Scheduler().run([task])

    result = Scheduler().run([task], approved_actions=frozenset({"write_files"}))
    assert result["write"].status == TaskStatus.SUCCEEDED
    assert result["write"].value == "written"


def test_approval_does_not_authorize_unknown_action() -> None:
    task = TaskSpec("unknown", lambda: None, action="arbitrary_shell")
    with pytest.raises(PermissionError, match="arbitrary_shell"):
        Scheduler().run([task], approved_actions=frozenset({"arbitrary_shell"}))



@pytest.mark.parametrize("workers", [0, 17])
def test_scheduler_worker_count_has_hard_bounds(workers: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 16"):
        Scheduler(max_workers=workers)


@pytest.mark.parametrize("max_tasks", [0, 257])
def test_scheduler_task_capacity_has_hard_bounds(max_tasks: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 256"):
        Scheduler(max_tasks=max_tasks)


def test_scheduler_rejects_task_batch_above_configured_limit() -> None:
    scheduler = Scheduler(max_tasks=1)
    tasks = [TaskSpec("one", lambda: None), TaskSpec("two", lambda: None)]
    with pytest.raises(ValueError, match="configured max_tasks"):
        scheduler.run(tasks)


def test_task_retry_count_has_hard_upper_bound() -> None:
    with pytest.raises(ValueError, match="between 1 and 10"):
        TaskSpec("too-many-retries", lambda: None, max_attempts=11)


def test_scheduler_audit_redacts_task_exception_message(tmp_path) -> None:
    audit_path = tmp_path / "scheduler-audit.jsonl"
    secret = "credential=do-not-persist-this"

    def fail_with_sensitive_message() -> None:
        raise RuntimeError(secret)

    result = Scheduler(audit_path=audit_path).run(
        [TaskSpec("sensitive-failure", fail_with_sensitive_message)]
    )["sensitive-failure"]

    assert result.status == TaskStatus.FAILED
    assert result.error == f"RuntimeError: {secret}"
    audit_text = audit_path.read_text(encoding="utf-8")
    assert secret not in audit_text
    assert '"error_type": "RuntimeError"' in audit_text


def test_scheduler_does_not_retry_unmarked_task_even_with_multiple_attempts() -> None:
    attempts = 0

    def flaky() -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("transient")

    result = Scheduler().run([TaskSpec("not-retry-safe", flaky, max_attempts=3)])["not-retry-safe"]

    assert attempts == 1
    assert result.status == TaskStatus.FAILED
    assert result.attempts == 1


def test_scheduler_retries_only_when_explicitly_marked_safe() -> None:
    attempts = 0

    def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        return "ok"

    result = Scheduler().run(
        [TaskSpec("retry-safe", flaky, max_attempts=2, retry_safe=True)]
    )["retry-safe"]

    assert attempts == 2
    assert result.status == TaskStatus.SUCCEEDED
    assert result.attempts == 2


def test_scheduler_clamps_workers_to_supplied_resource_snapshot() -> None:
    from blue_ant.resources import ResourceSnapshot

    scheduler = Scheduler(
        max_workers=8,
        resource_snapshot=ResourceSnapshot(cpu_count=2, available_memory_bytes=2 * 1024 * 1024 * 1024),
    )

    assert scheduler.max_workers == 2


def test_scheduler_rejects_snapshot_without_capacity_for_one_worker() -> None:
    from blue_ant.resources import ResourceSnapshot

    with pytest.raises(ValueError, match="insufficient available memory"):
        Scheduler(
            max_workers=4,
            resource_snapshot=ResourceSnapshot(cpu_count=4, available_memory_bytes=100),
        )
