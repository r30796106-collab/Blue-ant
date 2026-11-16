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
    assert events[0]["previous_hash"] == "0" * 64
    assert events[1]["previous_hash"] == events[0]["record_hash"]
    verification = audit.verify()
    assert verification.valid is True
    assert verification.records == 2
    assert verification.last_hash == events[-1]["record_hash"]


def test_audit_log_rejects_reserved_metadata_override(tmp_path: Path):
    audit = AuditLog(tmp_path / "events.jsonl")

    with pytest.raises(ValueError, match="reserved fields"):
        audit.record("legitimate", timestamp="forged")
    with pytest.raises(ValueError, match="reserved fields"):
        audit.record("legitimate", previous_hash="forged")

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



def test_audit_log_detects_tampered_record_content(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    audit = AuditLog(path)
    audit.record("started", task_id="one")
    audit.record("finished", task_id="one")

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[0]["event"] = "tampered"
    path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in records), encoding="utf-8")

    verification = audit.verify()
    assert verification.valid is False
    assert verification.records == 0
    assert "record hash mismatch" in verification.error


def test_audit_log_refuses_to_append_after_corrupt_final_record(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    audit = AuditLog(path)
    audit.record("created")
    path.write_text(path.read_text(encoding="utf-8").replace('"event": "created"', '"event": "changed"'), encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        audit.record("next")


def test_audit_log_refuses_non_terminated_tail(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    audit = AuditLog(path)
    audit.record("created")
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one newline"):
        audit.record("next")


def test_audit_log_hash_chain_serializes_multiple_instances(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    writers = [AuditLog(path) for _ in range(4)]
    threads = [
        threading.Thread(
            target=writers[index % len(writers)].record,
            args=(f"event-{index}",),
            kwargs={"index": index},
        )
        for index in range(40)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    verification = AuditLog(path).verify()
    assert verification.valid is True
    assert verification.records == 40
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {event["index"] for event in events} == set(range(40))


def test_oversized_audit_event_is_rejected_without_partial_record(tmp_path):
    audit = AuditLog(tmp_path / "oversized.jsonl")

    with pytest.raises(ValueError, match="1 MB limit"):
        audit.record("oversized", payload="x" * (1_000_001))

    assert audit.path.read_bytes() == b""
    verification = audit.verify()
    assert verification.valid is True
    assert verification.records == 0


def test_audit_verification_rejects_duplicate_json_keys(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    audit = AuditLog(path)
    audit.record("valid")
    with path.open("ab") as stream:
        stream.write(b'{"event":"forged","event":"duplicate"}\\n')

    verification = audit.verify()

    assert verification.valid is False
    assert verification.records == 1
    assert "duplicate keys" in verification.error


def test_audit_log_refuses_to_append_after_duplicate_key_tail(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    audit = AuditLog(path)
    audit.record("valid")
    with path.open("ab") as stream:
        stream.write(b'{"event":"forged","event":"duplicate"}\\n')

    with pytest.raises(ValueError, match="duplicate keys"):
        audit.record("next")


def test_audit_verification_rejects_non_object_json_record(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    audit = AuditLog(path)
    audit.record("valid")
    with path.open("ab") as stream:
        stream.write(b'[]\n')

    verification = audit.verify()

    assert verification.valid is False
    assert verification.records == 1
    assert "line 2 is not a JSON object" == verification.error
