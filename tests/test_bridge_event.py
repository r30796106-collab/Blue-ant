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
    {"schema_version": 1.0},
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


def test_rejects_duplicate_json_keys(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    event.write_text(
        '{"schema_version":1,"event_id":"event-001","event_type":"bridge.command",'
        '"command_id":"event-test","command_id":"other"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        run_bridge_event(event, command, target, tmp_path / "out", state)


def test_rejects_duplicate_keys_in_existing_receipt(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    (state / "event-001.json").write_text(
        '{"event_sha256":"same","event_sha256":"changed"}', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unreadable"):
        run_bridge_event(event, command, target, tmp_path / "out", state)


def test_rejects_event_larger_than_limit(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    event.write_text(" " * (16 * 1024 + 1), encoding="utf-8")

    with pytest.raises(ValueError, match="16 KiB"):
        run_bridge_event(event, command, target, tmp_path / "out", state)


def test_rejects_symlinked_event_file(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    alias = tmp_path / "event-alias.json"
    alias.symlink_to(event)

    with pytest.raises(ValueError, match="non-symlink"):
        run_bridge_event(alias, command, target, tmp_path / "out", state)


def test_processing_receipt_blocks_automatic_replay(tmp_path):
    import hashlib

    event, command, target, state = write_inputs(tmp_path)
    raw = event.read_bytes()
    receipt = {
        "schema_version": 1,
        "event_id": "event-001",
        "event_sha256": hashlib.sha256(raw).hexdigest(),
        "command_id": "event-test",
        "status": "processing",
    }
    (state / "event-001.json").write_text(json.dumps(receipt), encoding="utf-8")

    result = run_bridge_event(event, command, target, tmp_path / "out", state)

    assert result == {"event_id": "event-001", "status": "processing", "duplicate": True}
    assert not (tmp_path / "out").exists()


def test_failed_event_is_receipted_and_not_replayed(tmp_path, monkeypatch):
    import blue_ant.bridge_event as bridge_event

    event, command, target, state = write_inputs(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated worker failure")

    monkeypatch.setattr(bridge_event, "run_bridge_command", fail)
    with pytest.raises(RuntimeError, match="simulated worker failure"):
        run_bridge_event(event, command, target, tmp_path / "out", state)

    receipt = json.loads((state / "event-001.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert receipt["error_type"] == "RuntimeError"

    replay = run_bridge_event(event, command, target, tmp_path / "out", state)
    assert replay == {"event_id": "event-001", "status": "failed", "duplicate": True}


def test_existing_receipt_must_match_event_identity_and_schema(tmp_path):
    import hashlib

    event, command, target, state = write_inputs(tmp_path)
    raw = event.read_bytes()
    receipt = {
        "schema_version": 1,
        "event_id": "another-event",
        "event_sha256": hashlib.sha256(raw).hexdigest(),
        "command_id": "event-test",
        "status": "completed",
        "result": {"action": "stop"},
    }
    (state / "event-001.json").write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        run_bridge_event(event, command, target, tmp_path / "out", state)


@pytest.mark.parametrize("receipt_text", [
    "[]",
    '{"schema_version":1,"event_id":"event-001","event_sha256":"hash",'
    '"command_id":"event-test","status":"unknown"}',
    '{"schema_version":true,"event_id":"event-001","event_sha256":"hash",'
    '"command_id":"event-test","status":"processing"}',
    '{"schema_version":1,"event_id":"event-001","event_sha256":"hash",'
    '"command_id":"event-test","status":"processing","unexpected":true}',
])
def test_existing_receipt_rejects_invalid_schema(tmp_path, receipt_text):
    event, command, target, state = write_inputs(tmp_path)
    (state / "event-001.json").write_text(receipt_text, encoding="utf-8")

    with pytest.raises(ValueError, match="receipt"):
        run_bridge_event(event, command, target, tmp_path / "out", state)


def test_existing_receipt_rejects_oversized_content(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    (state / "event-001.json").write_text(" " * (16 * 1024 + 1), encoding="utf-8")

    with pytest.raises(ValueError, match="16 KiB"):
        run_bridge_event(event, command, target, tmp_path / "out", state)


def test_existing_receipt_rejects_symlink(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    outside = tmp_path / "receipt.json"
    outside.write_text('{"status":"completed"}', encoding="utf-8")
    (state / "event-001.json").symlink_to(outside)

    with pytest.raises(ValueError, match="receipt"):
        run_bridge_event(event, command, target, tmp_path / "out", state)
    assert outside.read_text(encoding="utf-8") == '{"status":"completed"}'


def test_rejects_symlinked_parent_of_state_directory(tmp_path):
    event, command, target, state = write_inputs(tmp_path)
    alias_parent = tmp_path / "state-parent-alias"
    alias_parent.symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(ValueError, match="parent directories"):
        run_bridge_event(
            event, command, target, tmp_path / "out", alias_parent / "state"
        )
    assert not (state / "event-001.json").exists()
