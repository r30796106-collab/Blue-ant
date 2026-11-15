from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {
    ".github/workflows/issue-approved-pr.yml": "blue-ant/issue-${ISSUE_NUMBER}",
    ".github/workflows/plan-linked-approved-pr.yml": "blue-ant/plan-issue-${ISSUE_NUMBER}",
}


def test_approved_issue_workers_are_idempotent_before_target_checkout():
    for relative_path, stable_branch in WORKFLOWS.items():
        workflow = (ROOT / relative_path).read_text(encoding="utf-8")
        preflight = workflow.index("Reject duplicate")
        checkout = workflow.index("Checkout target repository")
        assert preflight < checkout
        assert stable_branch in workflow
        assert "pulls?state=all&per_page=100" in workflow
        assert ".head.ref ==" in workflow
        assert ".head.repo.full_name ==" in workflow
        assert "git/matching-refs/heads/" in workflow
        assert "cancel-in-progress: false" in workflow
        assert "github.run_id" not in workflow
        assert "-run-${RUN_ID}" not in workflow


def test_approved_issue_workers_keep_explicit_approval_and_cross_repo_token_gate():
    for relative_path in WORKFLOWS:
        workflow = (ROOT / relative_path).read_text(encoding="utf-8")
        assert 'data["apply_approved"] is not True' in workflow
        assert "Cross-repository" in workflow
        assert "BLUE_ANT_WORKER_TOKEN" in workflow
        assert "never merges" in workflow.lower()
