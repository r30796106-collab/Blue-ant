import json
from pathlib import Path
import threading

import pytest

from blue_ant.audit import AuditLog


def test_audit_log_appends_valid_json_lines(tmp_path: Path):
    path = tmp_path / "logs" / "events.jsonl"
    audit = AuditLog(path)

    audit.record("task_started", task_id="one", attempt=1)
    audit.record("task_succeeded", task_id="one", attempts=1)

    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 2
    assert [event["event"] for event in events] == ["task_started", "task_succeeded"]
    assert events[0]["task_id"] == "one"
    assert events[0]["attempt"] == 1
    assert events[0]["timestamp"]


def test_audit_log_rejects_reserved_metadata_override(tmp_path: Path):
    audit = AuditLog(tmp_path / "events.jsonl")

    with pytest.raises(ValueError, match="reserved fields"):
        audit.record("legitimate", timestamp="forged")

    assert not audit.path.exists()


def test_audit_log_rejects_empty_event_name(tmp_path: Path):
    audit = AuditLog(tmp_path / "events.jsonl")

    with pytest.raises(ValueError, match="non-empty"):
        audit.record("  ")

    assert not audit.path.exists()


def test_audit_log_rejects_symlink_file_without_touching_target(tmp_path: Path):
    target = tmp_path / "outside.jsonl"
    target.write_text("preserve", encoding="utf-8")
    linked = tmp_path / "events.jsonl"
    linked.symlink_to(target)

    with pytest.raises(ValueError, match="symlinks"):
        AuditLog(linked)

    assert target.read_text(encoding="utf-8") == "preserve"


def test_audit_log_rejects_symlink_parent_directory(tmp_path: Path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinks"):
        AuditLog(linked_parent / "events.jsonl")

    assert list(real_parent.iterdir()) == []


def test_new_audit_log_file_uses_restrictive_permissions(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    audit = AuditLog(path)
    audit.record("created")

    assert path.stat().st_mode & 0o777 == 0o600


def test_audit_log_serializes_concurrent_thread_appends(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    audit = AuditLog(path)
    threads = [
        threading.Thread(target=audit.record, args=(f"event-{index}",), kwargs={"index": index})
        for index in range(24)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 24
    assert {event["index"] for event in events} == set(range(24))
