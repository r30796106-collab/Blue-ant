import json

from blue_ant.audit import AuditLog
from blue_ant.bridge_runner import run_bridge_command


def write_command(path, *, roles=None, max_cycles=None, snapshot_sources=False):
    roles = roles or ["repo_analyst", "test_auditor", "docs_auditor", "safety_auditor"]
    value = {
        "schema_version": 1,
        "command_id": "bridge-v3-test",
        "command": "audit_plan",
        "project_id": "demo",
        "repository": "r30796106-collab/ELON",
        "ref": "master",
        "roles": roles,
        "max_cycles": max_cycles or len(roles),
        "task": "Read-only parallel review",
        "snapshot_sources": snapshot_sources,
    }
    path.write_text(json.dumps(value), encoding="utf-8")


def make_clean_target(root):
    (root / "README.md").write_text("# Demo\n\nSee [tests](tests/test_demo.py).\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_demo.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("run: pytest\n", encoding="utf-8")


def test_runner_executes_all_roles_and_stops_for_safety_auditor_review(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    make_clean_target(target)
    command = tmp_path / "command.json"
    write_command(command)

    result = run_bridge_command(command, target, tmp_path / "out")

    assert result["status"] == "stopped"
    assert result["action"] == "human_review"
    assert result["workers_completed"] == 4
    assert result["workers_failed"] == 0
    audit = json.loads((tmp_path / "out" / "bridge-v3-test-audit.json").read_text())
    assert audit["execution_mode"] == "parallel_read_only_specialists"
    assert audit["execution_audit"]["valid"] is True
    event_log = tmp_path / "out" / result["artifacts"]["event_log"]
    verification = AuditLog(event_log).verify()
    assert verification.valid is True
    assert verification.records == 14
    assert event_log.stat().st_mode & 0o777 == 0o600
    assert {cycle["role"] for cycle in audit["cycles"]} == {
        "repo_analyst", "test_auditor", "docs_auditor", "safety_auditor"
    }


def test_runner_stops_for_human_review_when_auditor_finds_issue(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    make_clean_target(target)
    (target / "README.md").write_text("# Demo\n\n[missing](not-here.md)\n", encoding="utf-8")
    command = tmp_path / "command.json"
    write_command(command, roles=["repo_analyst", "docs_auditor"])

    result = run_bridge_command(command, target, tmp_path / "out")

    assert result["status"] == "stopped"
    assert result["action"] == "human_review"
    plan = json.loads((tmp_path / "out" / "bridge-v3-test-plan.json").read_text())
    assert any(task["kind"] == "audit_finding_review" for task in plan["tasks"])


def test_runner_does_not_modify_target_files(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    make_clean_target(target)
    before = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    command = tmp_path / "command.json"
    write_command(command, roles=["repo_analyst"])

    run_bridge_command(command, target, tmp_path / "out")

    after = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert after == before



def test_runner_uses_isolated_snapshot_when_requested(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    make_clean_target(target)
    (target / ".env").write_text("TOKEN=keep-out", encoding="utf-8")
    command = tmp_path / "command.json"
    write_command(command, roles=["repo_analyst"], snapshot_sources=True)

    result = run_bridge_command(command, target, tmp_path / "out")

    assert result["workers_completed"] == 1
    audit = json.loads((tmp_path / "out" / "bridge-v3-test-audit.json").read_text())
    assert audit["workspace_mode"] == "bounded_source_snapshot"
    assert audit["execution_audit"]["valid"] is True
    assert audit["execution_audit"]["records"] == 6
    audit_path = tmp_path / ".blue-ant-workspaces" / "bridge-v3-test" / "workforce-audit.jsonl"
    assert audit_path.is_file()
    assert not (tmp_path / "out" / "workforce-audit.jsonl").exists()
    project_workspace = tmp_path / ".blue-ant-workspaces" / "bridge-v3-test" / "demo"
    task_workspace = project_workspace / "tasks" / "cycle-1-repo-analyst"
    shared_snapshot = project_workspace / "shared-source"
    assert task_workspace.is_dir()
    assert (shared_snapshot / "README.md").is_file()
    assert not (shared_snapshot / ".env").exists()
    assert not (task_workspace / "README.md").exists()
    assert (target / ".env").read_text(encoding="utf-8") == "TOKEN=keep-out"
    assert not (tmp_path / "out" / "workspaces").exists()
    assert not any((tmp_path / "out").rglob(".env"))


def test_runner_replaces_artifact_symlink_without_writing_through_it(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    make_clean_target(target)
    command = tmp_path / "command.json"
    write_command(command, roles=["repo_analyst"])
    output = tmp_path / "out"
    output.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("keep unchanged", encoding="utf-8")
    (output / "bridge-v3-test-audit.json").symlink_to(outside)

    run_bridge_command(command, target, output)

    assert outside.read_text(encoding="utf-8") == "keep unchanged"
    assert not (output / "bridge-v3-test-audit.json").is_symlink()
    assert json.loads((output / "bridge-v3-test-audit.json").read_text())["schema_version"] == 1


def test_runner_rejects_symlinked_output_directory(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    make_clean_target(target)
    command = tmp_path / "command.json"
    write_command(command, roles=["repo_analyst"])
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    alias = tmp_path / "output-alias"
    alias.symlink_to(real_output, target_is_directory=True)

    import pytest
    with pytest.raises(ValueError, match="output_dir"):
        run_bridge_command(command, target, alias)
    assert list(real_output.iterdir()) == []



def test_runner_rejects_symlinked_output_parent_without_creating_through_it(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    make_clean_target(target)
    command = tmp_path / "command.json"
    write_command(command, roles=["repo_analyst"])

    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "output-parent-alias"
    alias.symlink_to(outside, target_is_directory=True)
    requested_output = alias / "new-output"

    import pytest
    with pytest.raises(ValueError, match="output_dir"):
        run_bridge_command(command, target, requested_output)

    assert not (outside / "new-output").exists()
    assert list(outside.iterdir()) == []
