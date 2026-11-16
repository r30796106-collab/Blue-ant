import json

import pytest

from blue_ant.controlled_proposal import build_patch_proposal, proposal_to_dict


def plan(kind="audit_finding_review", role="repo_analyst", path="src/example.py"):
    return {
        "schema_version": 1,
        "plan_id": "plan-0123456789abcdef",
        "project_id": "demo",
        "approval_required": True,
        "apply_approved": False,
        "tasks": [{
            "task_id": "review-finding-1",
            "kind": kind,
            "role": role,
            "path": path,
            "requires_human_review": True,
        }],
    }


def test_builds_hash_checked_proposal_without_modifying_workspace(tmp_path):
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("old = True\n", encoding="utf-8")
    result = build_patch_proposal(
        tmp_path, plan(), "review-finding-1",
        [{"path": "src/example.py", "content": "new = True\n"}],
    )
    data = proposal_to_dict(result)
    assert data["task_id"] == "review-finding-1"
    assert data["changes"][0]["expected_sha256"] is not None
    assert data["changes"][0]["content"] == "new = True\n"
    assert target.read_text(encoding="utf-8") == "old = True\n"


def test_builds_bounded_multi_file_proposal_from_exact_task_allowlist(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("old_app = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text("old_test = 1\n", encoding="utf-8")
    p = plan()
    p["tasks"][0].pop("path")
    p["tasks"][0]["paths"] = ["src/app.py", "tests/test_app.py"]
    result = build_patch_proposal(tmp_path, p, "review-finding-1", [
        {"path": "src/app.py", "content": "new_app = 1\n"},
        {"path": "tests/test_app.py", "content": "new_test = 1\n"},
    ])
    data = proposal_to_dict(result)
    assert [item["path"] for item in data["changes"]] == ["src/app.py", "tests/test_app.py"]
    assert all(item["expected_sha256"] for item in data["changes"])
    assert (tmp_path / "src" / "app.py").read_text(encoding="utf-8") == "old_app = 1\n"


def test_multi_file_proposal_rejects_missing_extra_duplicate_and_too_many_paths(tmp_path):
    (tmp_path / "src").mkdir()
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / "src" / name).write_text("old\n", encoding="utf-8")
    p = plan()
    p["tasks"][0].pop("path")
    p["tasks"][0]["paths"] = ["src/a.py", "src/b.py"]
    with pytest.raises(ValueError, match="exactly one change"):
        build_patch_proposal(tmp_path, p, "review-finding-1", [{"path": "src/a.py", "content": "new"}])
    with pytest.raises(ValueError, match="outside"):
        build_patch_proposal(tmp_path, p, "review-finding-1", [
            {"path": "src/a.py", "content": "new"},
            {"path": "src/c.py", "content": "new"},
        ])
    p["tasks"][0]["paths"] = ["src/a.py", "src/a.py"]
    with pytest.raises(ValueError, match="unique"):
        build_patch_proposal(tmp_path, p, "review-finding-1", [
            {"path": "src/a.py", "content": "new"},
            {"path": "src/a.py", "content": "new"},
        ])
    p["tasks"][0]["paths"] = [f"src/{i}.py" for i in range(11)]
    with pytest.raises(ValueError, match="1–10"):
        build_patch_proposal(tmp_path, p, "review-finding-1", [])


def test_multi_file_proposal_cli_writes_unapproved_json(tmp_path):
    from blue_ant.controlled_proposal_cli import main
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "tests").mkdir()
    (workspace / "src" / "app.py").write_text("old\n", encoding="utf-8")
    (workspace / "tests" / "test_app.py").write_text("old\n", encoding="utf-8")
    p = plan()
    p["tasks"][0].pop("path")
    p["tasks"][0]["paths"] = ["src/app.py", "tests/test_app.py"]
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(p), encoding="utf-8")
    changes_file = tmp_path / "changes.json"
    changes_file.write_text(json.dumps([
        {"path": "src/app.py", "content": "new app\n"},
        {"path": "tests/test_app.py", "content": "new test\n"},
    ]), encoding="utf-8")
    output = tmp_path / "proposal.json"
    assert main(["--workspace", str(workspace), "--plan", str(plan_file), "--task-id", "review-finding-1", "--changes", str(changes_file), "--output", str(output)]) == 0
    proposal = json.loads(output.read_text(encoding="utf-8"))
    assert len(proposal["changes"]) == 2
    assert all(item["expected_sha256"] for item in proposal["changes"])


def test_proposal_id_is_deterministic(tmp_path):
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("old\n", encoding="utf-8")
    args = (tmp_path, plan(), "review-finding-1", [{"path": "src/example.py", "content": "new\n"}])
    assert build_patch_proposal(*args).proposal_id == build_patch_proposal(*args).proposal_id


def test_rejects_path_outside_task_scope(tmp_path):
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("old\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        build_patch_proposal(tmp_path, plan(), "review-finding-1", [{"path": "README.md", "content": "x"}])


@pytest.mark.parametrize("bad_path", ["../secret", "/etc/passwd", "src\\example.py", ".git/config", "."])
def test_rejects_unsafe_plan_paths(tmp_path, bad_path):
    with pytest.raises(ValueError):
        build_patch_proposal(tmp_path, plan(path=bad_path), "review-finding-1", [{"path": bad_path, "content": "x"}])


def test_rejects_safety_or_non_code_review_tasks(tmp_path):
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("old\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        build_patch_proposal(tmp_path, plan(kind="security_human_review", role="safety_auditor"), "review-finding-1", [{"path": "src/example.py", "content": "new"}])
    with pytest.raises(PermissionError):
        build_patch_proposal(tmp_path, plan(kind="informational_observation"), "review-finding-1", [{"path": "src/example.py", "content": "new"}])


def test_rejects_missing_or_symlinked_targets(tmp_path):
    with pytest.raises(ValueError, match="existing regular file"):
        build_patch_proposal(tmp_path, plan(), "review-finding-1", [{"path": "src/example.py", "content": "new"}])
    outside = tmp_path.parent / "outside.py"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "src"
    link.symlink_to(outside.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinked"):
        build_patch_proposal(tmp_path, plan(), "review-finding-1", [{"path": "src/example.py", "content": "new"}])


def test_rejects_approved_or_invalid_plan_and_duplicate_task(tmp_path):
    p = plan()
    p["apply_approved"] = True
    with pytest.raises(ValueError, match="unapproved"):
        build_patch_proposal(tmp_path, p, "review-finding-1", [{"path": "src/example.py", "content": "x"}])
    p = plan()
    p["tasks"].append(dict(p["tasks"][0]))
    with pytest.raises(ValueError, match="exactly one"):
        build_patch_proposal(tmp_path, p, "review-finding-1", [{"path": "src/example.py", "content": "x"}])


def test_rejects_multiple_changes_and_large_content(tmp_path):
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        build_patch_proposal(tmp_path, plan(), "review-finding-1", [
            {"path": "src/example.py", "content": "a"},
            {"path": "src/example.py", "content": "b"},
        ])
    with pytest.raises(ValueError, match="2 MB"):
        build_patch_proposal(tmp_path, plan(), "review-finding-1", [{"path": "src/example.py", "content": "x" * 2_000_001}])


def test_cli_writes_proposal_json_without_approval(tmp_path):
    from blue_ant.controlled_proposal_cli import main
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "example.py").write_text("old\n", encoding="utf-8")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan()), encoding="utf-8")
    change_file = tmp_path / "change.json"
    change_file.write_text(json.dumps({"path": "src/example.py", "content": "new\n"}), encoding="utf-8")
    output = tmp_path / "proposal.json"
    assert main(["--workspace", str(workspace), "--plan", str(plan_file), "--task-id", "review-finding-1", "--change", str(change_file), "--output", str(output)]) == 0
    proposal = json.loads(output.read_text(encoding="utf-8"))
    assert proposal["task_id"] == "review-finding-1"
    assert proposal["changes"][0]["expected_sha256"]


def test_rejects_boolean_development_plan_schema_version(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text("old = True\\n", encoding="utf-8")
    value = plan()
    value["schema_version"] = True
    with pytest.raises(ValueError, match="schema_version"):
        build_patch_proposal(tmp_path, value, "review-finding-1", [
            {"path": "src/example.py", "content": "new = True\\n"},
        ])


@pytest.mark.parametrize("schema_version", [1.0, "1"])
def test_rejects_non_integer_development_plan_schema_version(tmp_path, schema_version):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "example.py").write_text("old = True\\n", encoding="utf-8")
    value = plan()
    value["schema_version"] = schema_version
    with pytest.raises(ValueError, match="schema_version"):
        build_patch_proposal(tmp_path, value, "review-finding-1", [
            {"path": "src/example.py", "content": "new = True\\n"},
        ])


def test_controlled_proposal_cli_rejects_duplicate_plan_keys(tmp_path, capsys):
    from blue_ant.controlled_proposal_cli import main

    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "example.py").write_text("old\\n", encoding="utf-8")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        '{"schema_version":1,"plan_id":"one","plan_id":"two",'
        '"project_id":"demo","approval_required":true,"apply_approved":false,"tasks":[]}',
        encoding="utf-8",
    )
    change_file = tmp_path / "change.json"
    change_file.write_text('{"path":"src/example.py","content":"new"}', encoding="utf-8")
    output = tmp_path / "proposal.json"
    assert main([
        "--workspace", str(workspace), "--plan", str(plan_file),
        "--task-id", "review-finding-1", "--change", str(change_file),
        "--output", str(output),
    ]) == 2
    assert "duplicate JSON object key" in capsys.readouterr().err
    assert not output.exists()
