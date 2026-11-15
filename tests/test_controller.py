import pytest

from blue_ant.controller import FeedbackLoop, LoopInstruction, LoopObservation


def instruction(number: int, task: str = "inspect repository") -> LoopInstruction:
    return LoopInstruction(str(number), "demo", "repo_analyst", task)


def test_feedback_loop_executes_worker_and_requests_next_instruction():
    calls = []
    def execute(item):
        calls.append(item.instruction_id)
        return LoopObservation(item.instruction_id, "ok", "completed")

    report = FeedbackLoop(max_cycles=3).run(
        instruction(1),
        execute=execute,
        decide_next=lambda current, result, cycle: instruction(cycle + 1) if cycle < 2 else None,
    )

    assert calls == ["1", "2"]
    assert report.stop_reason == "controller_stopped"
    assert report.cycles_used == 2
    assert [item.status for item in report.observations] == ["ok", "ok"]


def test_feedback_loop_stops_at_hard_cycle_limit():
    report = FeedbackLoop(max_cycles=2).run(
        instruction(1),
        execute=lambda item: LoopObservation(item.instruction_id, "ok", "done"),
        decide_next=lambda current, result, cycle: instruction(cycle + 1),
    )
    assert report.stop_reason == "cycle_limit_reached"
    assert report.cycles_used == 2


def test_worker_exception_becomes_observation_and_loop_continues():
    seen = []
    def decide(current, result, cycle):
        seen.append(result.status)
        return instruction(2) if cycle == 1 else None

    report = FeedbackLoop().run(
        instruction(1),
        execute=lambda item: (_ for _ in ()).throw(RuntimeError("worker unavailable")),
        decide_next=decide,
    )
    assert seen == ["failed"]
    assert report.observations[0].summary == "RuntimeError: worker unavailable"
    assert report.stop_reason == "controller_stopped"


def test_duplicate_instruction_ids_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        FeedbackLoop(max_cycles=3).run(
            instruction(1),
            execute=lambda item: LoopObservation(item.instruction_id, "ok", "done"),
            decide_next=lambda current, result, cycle: instruction(1),
        )


@pytest.mark.parametrize("limit", [0, 11])
def test_cycle_limit_is_bounded(limit):
    with pytest.raises(ValueError, match="between 1 and 10"):
        FeedbackLoop(max_cycles=limit)


def test_invalid_instruction_is_rejected_before_execution():
    bad = LoopInstruction("", "demo", "repo_analyst", "task")
    with pytest.raises(ValueError, match="instruction_id"):
        FeedbackLoop().run(
            bad,
            execute=lambda item: LoopObservation(item.instruction_id, "ok", "done"),
            decide_next=lambda current, result, cycle: None,
        )
