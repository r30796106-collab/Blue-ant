from pathlib import Path

from blue_ant.code_preparation import prepare_plan, prepare_task


def task(evidence, **overrides):
    value = {
        "task_id": "review-finding-1",
        "kind": "audit_finding_review",
        "role": "docs_auditor",
        "path": "README.md",
        "evidence": evidence,
    }
    value.update(overrides)
    return value


def test_prepares_unclosed_markdown_fence_without_writing_workspace(tmp_path: Path):
    readme = tmp_path / "README.md"
    original = "# Example\n\n```python\nprint('ok')\n"
    readme.write_text(original, encoding="utf-8")
    result = prepare_task(tmp_path, task("README contains an unclosed fenced code block."))
    assert result["status"] == "prepared"
    assert result["strategy"] == "append_matching_markdown_fence"
    assert result["content"] == original + "```\n"
    assert readme.read_text(encoding="utf-8") == original


def test_prepares_unique_case_only_relative_link(tmp_path: Path):
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Docs" / "Guide.md").write_text("# Guide\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("[Guide](docs/guide.md)\n", encoding="utf-8")
    result = prepare_task(
        tmp_path,
        task("README contains a relative link to a missing repository file: docs/guide.md"),
    )
    assert result["status"] == "prepared"
    assert result["strategy"] == "correct_unique_case_only_relative_link"
    assert result["content"] == "[Guide](Docs/Guide.md)\n"
    assert readme.read_text(encoding="utf-8") == "[Guide](docs/guide.md)\n"


def test_ambiguous_or_missing_link_stays_manual(tmp_path: Path):
    (tmp_path / "README.md").write_text("[Guide](docs/guide.md)\n", encoding="utf-8")
    result = prepare_task(tmp_path, task("README contains a relative link to a missing repository file: docs/guide.md"))
    assert result["status"] == "manual_review"
    assert result["content"] == ""


def test_non_documentation_and_safety_tasks_never_prepare(tmp_path: Path):
    (tmp_path / "README.md").write_text("```python\n", encoding="utf-8")
    security = prepare_task(tmp_path, task("README contains an unclosed fenced code block.", role="safety_auditor"))
    code = prepare_task(tmp_path, task("README contains an unclosed fenced code block.", path="src/app.py"))
    assert security["status"] == "manual_review"
    assert code["status"] == "manual_review"


def test_plan_preparation_returns_each_eligible_task(tmp_path: Path):
    (tmp_path / "README.md").write_text("```python\nprint('ok')\n", encoding="utf-8")
    plan = {"schema_version": 1, "plan_id": "plan-test", "tasks": [task("README contains an unclosed fenced code block.")]}
    result = prepare_plan(tmp_path, plan)
    assert result["plan_id"] == "plan-test"
    assert result["prepared_tasks"][0]["status"] == "prepared"


def test_case_insensitive_collision_stays_manual(tmp_path: Path):
    (tmp_path / "Docs").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "Docs" / "Guide.md").write_text("one", encoding="utf-8")
    (tmp_path / "docs" / "GUIDE.md").write_text("two", encoding="utf-8")
    (tmp_path / "README.md").write_text("[Guide](DOCS/guide.md)\n", encoding="utf-8")
    result = prepare_task(
        tmp_path,
        task("README contains a relative link to a missing repository file: DOCS/guide.md"),
    )
    assert result["status"] == "manual_review"


def test_malformed_task_is_rejected_without_exception(tmp_path: Path):
    result = prepare_task(tmp_path, None)
    assert result["status"] == "manual_review"
    assert result["content"] == ""


def test_cli_writes_drafts_without_modifying_target(tmp_path: Path):
    import json
    from blue_ant.code_preparation_cli import main

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original = "```python\nprint('ok')\n"
    (workspace / "README.md").write_text(original, encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "schema_version": 1,
        "plan_id": "plan-cli",
        "tasks": [task("README contains an unclosed fenced code block.")],
    }), encoding="utf-8")
    output = tmp_path / "prepared.json"
    assert main(["--workspace", str(workspace), "--plan", str(plan_path), "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["prepared_tasks"][0]["status"] == "prepared"
    assert (workspace / "README.md").read_text(encoding="utf-8") == original
