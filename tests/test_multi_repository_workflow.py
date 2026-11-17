from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "multi-repository-workforce.yml"


def test_multi_repository_workflow_uses_registered_project_ids_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "project_ids:" in workflow
    assert "blue_ant.portfolio_cli" in workflow
    assert "TARGET_REPOSITORY" not in workflow
    assert "matrix.project.repository" in workflow
    assert "matrix.project.ref" in workflow
    assert "BLUE_ANT_WORKER_TOKEN" in workflow


def test_multi_repository_workflow_keeps_private_repo_checkout_fail_closed():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "ai-trading" in workflow
    assert "requires BLUE_ANT_WORKER_TOKEN" in workflow
    assert "persist-credentials: false" in workflow
    assert "contents: read" in workflow


def test_multi_repository_workforce_is_bounded_and_failure_isolated():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "fail-fast: false" in workflow
    assert "max-parallel: 4" in workflow
    assert "--max-workers 4" in workflow
    assert "timeout-minutes: 30" in workflow
