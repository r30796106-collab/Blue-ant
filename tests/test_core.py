import pytest

from blue_ant.controller import BlueAntController
from blue_ant.models import Task, TaskStatus, WorkerTemplate
from blue_ant.policy import PolicyGateway
from blue_ant.resources import ResourceBudget


def make_task(task_id, depends_on=(), max_attempts=1):
    return Task(task_id, "demo", "qa", task_id, depends_on=tuple(depends_on), max_attempts=max_attempts)


def test_dependency_readiness_and_completion():
    controller = BlueAntController()
    controller.submit(make_task("a"))
    controller.submit(make_task("b", ["a"]))
    assert [task.task_id for task in controller.ready_tasks()] == ["a"]
    controller.mark_running("a")
    controller.mark_succeeded("a", {"ok": True})
    assert [task.task_id for task in controller.ready_tasks()] == ["b"]


def test_unknown_dependency_rejected():
    with pytest.raises(ValueError, match="unknown dependencies"):
        BlueAntController().submit(make_task("b", ["missing"]))


def test_duplicate_task_rejected():
    controller = BlueAntController()
    controller.submit(make_task("a"))
    with pytest.raises(ValueError, match="duplicate"):
        controller.submit(make_task("a"))


def test_retry_limit():
    controller = BlueAntController()
    controller.submit(make_task("a", max_attempts=2))
    controller.mark_running("a")
    controller.mark_failed("a", "temporary")
    assert controller.tasks["a"].status is TaskStatus.READY
    controller.mark_running("a")
    controller.mark_failed("a", "again")
    assert controller.tasks["a"].status is TaskStatus.FAILED


def test_policy_blocks_real_money_and_gates_delete():
    policy = PolicyGateway()
    assert not policy.evaluate("real_money_trade").allowed
    decision = policy.evaluate("delete")
    assert decision.requires_approval and not decision.allowed
    policy.approve("delete")
    assert policy.evaluate("delete").allowed


def test_security_test_requires_authorized_scope():
    policy = PolicyGateway()
    assert not policy.evaluate("security_test").allowed
    assert policy.evaluate("security_test", scope_authorized=True).requires_approval


def test_resource_budget():
    budget = ResourceBudget(max_workers=2, available_memory_mb=512)
    assert budget.permits(256)
    assert not budget.permits(1024)


def test_worker_template_validation():
    with pytest.raises(ValueError):
        WorkerTemplate("developer", (), max_concurrency=0)

from blue_ant.scheduler import Scheduler


def test_scheduler_runs_independent_tasks_and_respects_dependencies():
    controller = BlueAntController()
    controller.submit(make_task("first"))
    controller.submit(make_task("second"))
    controller.submit(make_task("third", ["first", "second"]))
    scheduler = Scheduler(controller, ResourceBudget(max_workers=2))
    result = scheduler.run({"general": lambda task: task.task_id.upper()})
    assert result["first"] is TaskStatus.SUCCEEDED
    assert result["second"] is TaskStatus.SUCCEEDED
    assert result["third"] is TaskStatus.SUCCEEDED
    assert controller.tasks["third"].result == "THIRD"


def test_scheduler_retries_handler_failure_with_bounded_attempts():
    controller = BlueAntController()
    controller.submit(make_task("retry", max_attempts=2))
    calls = {"count": 0}

    def flaky(_task):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary")
        return "ok"

    result = Scheduler(controller, ResourceBudget()).run({"general": flaky})
    assert calls["count"] == 2
    assert result["retry"] is TaskStatus.SUCCEEDED


def test_scheduler_leaves_task_ready_when_memory_budget_is_insufficient():
    controller = BlueAntController()
    task = Task("large", "demo", "qa", "large", required_memory_mb=2048)
    controller.submit(task)
    result = Scheduler(
        controller, ResourceBudget(max_workers=2, available_memory_mb=512)
    ).run({"general": lambda _task: "should not run"})
    assert result["large"] is TaskStatus.READY
