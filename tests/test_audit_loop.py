from pathlib import Path

import pytest

from blue_ant.audit_loop import BoundedAuditLoop
from blue_ant.subbots import Finding, SubBotRole
from blue_ant.workforce import WorkResult


def result(role: SubBotRole, cycle: int, *, error: str | None = None) -> WorkResult:
    return WorkResult(
        task_id=f"cycle-{cycle}-{role.value.replace('_', '-')}",
        project_id="demo",
        role=role.value,
        source_root=Path("/tmp/demo"),
        workspace=Path(f"/tmp/demo-work/{cycle}"),
        findings=(Finding(f"bot-{role.value}", role.value, "info", ".", "checked"),),
        error=error,
    )


def test_audit_loop_runs_roles_in_order_and_completes():
    seen = []

    def execute(role, cycle):
        seen.append((role, cycle))
        return result(role, cycle)

    report = BoundedAuditLoop().run(
        [SubBotRole.REPO_ANALYST, SubBotRole.TEST_AUDITOR, SubBotRole.DOCS_AUDITOR],
        execute=execute,
    )

    assert seen == [
        (SubBotRole.REPO_ANALYST, 1),
        (SubBotRole.TEST_AUDITOR, 2),
        (SubBotRole.DOCS_AUDITOR, 3),
    ]
    assert report.stop_reason == "sequence_completed"
    assert report.cycles_used == 3
    assert all(item.status == "success" for item in report.cycles)
    assert report.cycles[0].findings[0]["message"] == "checked"


def test_worker_error_stops_before_next_role():
    seen = []

    def execute(role, cycle):
        seen.append(role)
        return result(role, cycle, error="worker unavailable")

    report = BoundedAuditLoop().run(
        [SubBotRole.REPO_ANALYST, SubBotRole.TEST_AUDITOR],
        execute=execute,
    )

    assert seen == [SubBotRole.REPO_ANALYST]
    assert report.stop_reason == "worker_error"
    assert report.cycles_used == 1
    assert report.cycles[0].error == "worker unavailable"


def test_loop_respects_cycle_limit():
    seen = []
    report = BoundedAuditLoop(max_cycles=2).run(
        list(SubBotRole),
        execute=lambda role, cycle: (seen.append(role) or result(role, cycle)),
    )
    assert len(seen) == 2
    assert report.stop_reason == "cycle_limit_reached"
    assert report.cycles_used == 2


@pytest.mark.parametrize("limit", [0, 5])
def test_cycle_limit_is_hard_bounded(limit):
    with pytest.raises(ValueError, match="between 1 and 4"):
        BoundedAuditLoop(max_cycles=limit)


def test_rejects_empty_duplicate_and_unapproved_roles():
    loop = BoundedAuditLoop()
    execute = lambda role, cycle: result(role, cycle)
    with pytest.raises(ValueError, match="at least one"):
        loop.run([], execute=execute)
    with pytest.raises(ValueError, match="duplicate"):
        loop.run([SubBotRole.DOCS_AUDITOR, SubBotRole.DOCS_AUDITOR], execute=execute)
    with pytest.raises(ValueError, match="approved"):
        loop.run(["shell"], execute=execute)


def test_executor_result_role_mismatch_stops_loop():
    report = BoundedAuditLoop().run(
        [SubBotRole.REPO_ANALYST, SubBotRole.TEST_AUDITOR],
        execute=lambda role, cycle: result(SubBotRole.DOCS_AUDITOR, cycle),
    )
    assert report.stop_reason == "worker_error"
    assert report.cycles[0].error == "ValueError: worker result role does not match requested role"
