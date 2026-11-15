from pathlib import Path


def test_subbot_review_is_strictly_gated_by_successful_ci():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "subbot-review.yml"
    ).read_text(encoding="utf-8")

    assert "\n  workflow_run:\n" in workflow
    assert "\n  pull_request:\n" not in workflow
    assert "workflows: [\"tests\"]" in workflow
    assert "types: [completed]" in workflow
    assert 'branches: ["feat/**", "fix/**", "docs/**", "test/**"]' in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
