import json

import pytest

from blue_ant.bridge_event import run_bridge_event


def write_inputs(tmp_path, *, event_id="event-001", command_id="event-test"):
    command = {
        "schema_version": 1,
        "command_id": command_id,
        "command": "audit_plan",
        "project_id": "demo",
        "repository": "r30796106-collab/ELON",
        "ref": "master",
        "roles": ["repo_analyst"],
        "max_cycles": 1,
        "task": "Local event adapter test",
        "snapshot_sources": False,
    }
    command_path = tmp_path / "command.json"
    command_path.write_text(json.dumps(command), encoding="utf-8")
    event = {
        "schema_version": 1,
        "event_id": event_id,
        "event_type": "bridge.command",
        "command_id": command_id,
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "README.md").write_text("# Clean demo\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    return event_path, command_path, target, state


def test_processes_event_and_records_completed_receipt(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    before = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}

    result = run_bridge_event(event, command, target, tmp_path / "out", state)

    assert result["status"] == "completed"
    assert result["duplicate"] is False
    receipt = json.loads((state / "event-001.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "completed"
    assert receipt["result"]["action"] == "stop"
    assert {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()} == before
    assert (state / "event-001.json").stat().st_mode & 0o777 == 0o600


def test_duplicate_event_is_not_executed_twice(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    first = run_bridge_event(event, command, target, tmp_path / "out", state)
    second = run_bridge_event(event, command, target, tmp_path / "out", state)

    assert first["duplicate"] is False
    assert second == {"event_id": "event-001", "status": "completed", "duplicate": True}


def test_rejects_reused_event_id_with_changed_payload(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    run_bridge_event(event, command, target, tmp_path / "out", state)
    value = json.loads(event.read_text(encoding="utf-8"))
    value["command_id"] = "different-command"
    event.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="different event payload"):
        run_bridge_event(event, command, target, tmp_path / "out", state)


@pytest.mark.parametrize("change", [
    {"event_type": "shell.command"},
    {"extra": "not-allowed"},
    {"schema_version": True},
])
def test_rejects_unsupported_or_malformed_event(tmp_path, change):
    event, command, target, state = write_inputs(tmp_path)
    value = json.loads(event.read_text(encoding="utf-8"))
    value.update(change)
    event.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError):
        run_bridge_event(event, command, target, tmp_path / "out", state)


def test_rejects_command_id_mismatch_before_claiming_event(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    value = json.loads(event.read_text(encoding="utf-8"))
    value["command_id"] = "not-the-command"
    event.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        run_bridge_event(event, command, target, tmp_path / "out", state)
    assert not (state / "event-001.json").exists()


def test_refuses_symlinked_state_directory(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    alias = tmp_path / "state-alias"
    alias.symlink_to(state, target_is_directory=True)

    with pytest.raises(ValueError, match="non-symlink"):
        run_bridge_event(event, command, target, tmp_path / "out", alias)
