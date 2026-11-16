from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_pull_request_review_is_a_ci_dependent_check():
    workflow = (WORKFLOWS / "tests.yml").read_text(encoding="utf-8")

    assert "  read-only-review:" in workflow
    assert "  package-smoke:" in workflow
    assert "python -m build --sdist --wheel" in workflow
    assert "    needs: [test, package-smoke]" in workflow
    assert "needs.test.result == 'success'" in workflow
    assert "needs.package-smoke.result == 'success'" in workflow
    assert "github.event_name == 'pull_request'" in workflow
    assert "blue_ant.subbot_report" in workflow
    assert "blue-ant-subbot-report" in workflow


def test_manual_review_workflow_is_read_only_and_manual_only():
    workflow = (WORKFLOWS / "subbot-review.yml").read_text(encoding="utf-8")

    assert "  workflow_dispatch:" in workflow
    assert "  workflow_run:" not in workflow
    assert "  pull_request:" not in workflow
    assert "contents: read" in workflow
    assert "pull-requests: read" in workflow
    assert "persist-credentials: false" in workflow
