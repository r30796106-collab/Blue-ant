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


PATCH_WORKFLOWS = (
    ".github/workflows/issue-approved-patch.yml",
    ".github/workflows/issue-approved-pr.yml",
)


def test_patch_workflows_match_the_patch_engine_ten_file_limit():
    for relative_path in PATCH_WORKFLOWS:
        workflow = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "len(changes) > 10" in workflow
        assert "Proposal must contain 1–10 changes" in workflow
        assert "len(changes) > 50" not in workflow


AUDIT_ARTIFACT_WORKFLOWS = {
    ".github/workflows/issue-approved-pr.yml": "target/.blue-ant/patch-audit.jsonl",
    ".github/workflows/plan-linked-approved-pr.yml": "target/.blue-ant/patch-audit.jsonl",
}


def test_approved_pr_workers_retain_patch_audit_artifacts():
    for relative_path, audit_path in AUDIT_ARTIFACT_WORKFLOWS.items():
        workflow = (ROOT / relative_path).read_text(encoding="utf-8")
        upload = workflow.index("Upload approved")
        commit = workflow.index("Create branch and commit")
        assert upload < commit
        assert "if: always()" in workflow[upload:commit]
        assert "actions/upload-artifact@v4" in workflow[upload:commit]
        assert audit_path in workflow[upload:commit]
        assert "retention-days: 14" in workflow[upload:commit]


def test_disposable_patch_worker_copies_audit_log_into_its_result_artifact():
    workflow = (ROOT / ".github/workflows/issue-approved-patch.yml").read_text(encoding="utf-8")
    retain = workflow.index("Retain patch audit trail")
    upload = workflow.index("Upload patch result")
    assert retain < upload
    assert "if: always()" in workflow[retain:upload]
    assert "workspace/.blue-ant/patch-audit.jsonl" in workflow[retain:upload]
    assert "artifacts/patch-audit.jsonl" in workflow[retain:upload]
