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


def test_runner_executes_all_approved_roles_and_completes_clean_review(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    make_clean_target(target)
    command = tmp_path / "command.json"
    write_command(command)

    result = run_bridge_command(command, target, tmp_path / "out")

    assert result["status"] == "completed"
    assert result["action"] == "stop"
    assert result["workers_completed"] == 4
    assert result["workers_failed"] == 0
    audit = json.loads((tmp_path / "out" / "bridge-v3-test-audit.json").read_text())
    assert audit["execution_mode"] == "parallel_read_only_specialists"
    assert audit["audit_chain"]["valid"] is True
    event_log = tmp_path / "out" / result["artifacts"]["event_log"]
    verification = AuditLog(event_log).verify()
    assert verification.valid is True
    assert verification.records == 14
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
    task_workspace = tmp_path / ".blue-ant-workspaces" / "bridge-v3-test" / "demo" / "tasks" / "cycle-1-repo-analyst"
    assert (task_workspace / "README.md").is_file()
    assert not (task_workspace / ".env").exists()
    assert (target / ".env").read_text(encoding="utf-8") == "TOKEN=keep-out"
    assert not (tmp_path / "out" / "workspaces").exists()
    assert not any((tmp_path / "out").rglob(".env"))
