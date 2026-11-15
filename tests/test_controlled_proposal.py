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
    with pytest.raises(ValueError, match="exactly match"):
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
