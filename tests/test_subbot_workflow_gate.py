from pathlib import Path


def test_subbot_review_is_success_gated_for_all_branch_names():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "subbot-review.yml"
    ).read_text(encoding="utf-8")

    trigger = workflow.split("  workflow_dispatch:", 1)[0]
    assert "  workflow_run:" in trigger
    assert 'workflows: ["tests"]' in trigger
    assert "types: [completed]" in trigger
    assert "branches:" not in trigger
    assert "  pull_request:" not in trigger
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert '.base.ref == "main" and .head.sha == $sha' in workflow
