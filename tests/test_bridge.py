from __future__ import annotations

import json

import pytest

from blue_ant.bridge import load_bridge_command, validate_bridge_command


def valid_command():
    return {
        "schema_version": 1,
        "command_id": "inspect-elon",
        "command": "audit_plan",
        "project_id": "elon",
        "repository": "r30796106-collab/Elon",
        "ref": "master",
        "roles": ["repo_analyst", "test_auditor", "docs_auditor", "safety_auditor"],
        "max_cycles": 4,
        "task": "Inspect repository health and prepare a review plan",
    }


def test_accepts_valid_bounded_audit_plan_command():
    result = validate_bridge_command(valid_command())
    assert result["command_id"] == "inspect-elon"
    assert result["roles"][-1] == "safety_auditor"


@pytest.mark.parametrize("field,value", [
    ("command", "run_shell"),
    ("repository", "someone-else/private"),
    ("ref", "../main"),
    ("roles", ["repo_analyst", "repo_analyst"]),
    ("roles", ["unknown_worker"]),
    ("max_cycles", True),
    ("max_cycles", 5),
    ("task", "inspect\nrun something"),
    ("schema_version", True),
    ("schema_version", 1.0),
    ("schema_version", "1"),
])
def test_rejects_unsafe_or_invalid_values(field, value):
    command = valid_command()
    command[field] = value
    with pytest.raises(ValueError):
        validate_bridge_command(command)


def test_rejects_extra_or_missing_fields():
    command = valid_command()
    command["shell"] = "echo unsafe"
    with pytest.raises(ValueError):
        validate_bridge_command(command)
    del command["shell"]
    del command["task"]
    with pytest.raises(ValueError):
        validate_bridge_command(command)


def test_load_rejects_oversized_command(tmp_path):
    source = tmp_path / "command.json"
    source.write_text(json.dumps(valid_command()) + (" " * 16_385), encoding="utf-8")
    with pytest.raises(ValueError, match="16 KiB"):
        load_bridge_command(source)



def test_snapshot_sources_is_optional_and_defaults_to_false():
    command = valid_command()
    result = validate_bridge_command(command)
    assert result["snapshot_sources"] is False

    command["snapshot_sources"] = True
    result = validate_bridge_command(command)
    assert result["snapshot_sources"] is True


@pytest.mark.parametrize("value", ["true", 1, None, [], {}])
def test_rejects_non_boolean_snapshot_sources(value):
    command = valid_command()
    command["snapshot_sources"] = value
    with pytest.raises(ValueError, match="snapshot_sources"):
        validate_bridge_command(command)


def test_load_rejects_duplicate_top_level_json_keys(tmp_path):
    source = tmp_path / "command.json"
    source.write_text(
        '{"schema_version": 1, "schema_version": 1}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_bridge_command(source)


def test_load_rejects_symlinked_command_file(tmp_path):
    source = tmp_path / "command.json"
    source.write_text(json.dumps(valid_command()), encoding="utf-8")
    alias = tmp_path / "command-alias.json"
    alias.symlink_to(source)

    with pytest.raises(ValueError, match="non-symlink"):
        load_bridge_command(alias)


def test_write_replaces_destination_symlink_without_writing_through_it(tmp_path):
    from blue_ant.bridge import write_bridge_command

    source = tmp_path / "source.json"
    source.write_text(json.dumps(valid_command()), encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text("keep unchanged", encoding="utf-8")
    destination = tmp_path / "destination.json"
    destination.symlink_to(outside)

    write_bridge_command(source, destination)

    assert outside.read_text(encoding="utf-8") == "keep unchanged"
    assert not destination.is_symlink()
    assert json.loads(destination.read_text(encoding="utf-8"))["command_id"] == "inspect-elon"
    assert destination.stat().st_mode & 0o777 == 0o600


def test_write_rejects_symlinked_destination_parent(tmp_path):
    from blue_ant.bridge import write_bridge_command

    source = tmp_path / "source.json"
    source.write_text(json.dumps(valid_command()), encoding="utf-8")
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="parent directories"):
        write_bridge_command(source, alias_parent / "destination.json")
    assert list(real_parent.iterdir()) == []
