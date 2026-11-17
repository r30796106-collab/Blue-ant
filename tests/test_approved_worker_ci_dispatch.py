from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ".github/workflows/issue-approved-pr.yml",
    ".github/workflows/plan-linked-approved-pr.yml",
)


def test_approved_coding_workers_dispatch_all_post_pr_verification_workflows():
    for relative_path in WORKFLOWS:
        workflow = (ROOT / relative_path).read_text(encoding="utf-8")

        pr_creation = workflow.index("Open pull request")
        dispatch = workflow.index("Dispatch", pr_creation)
        report = workflow.index("Report result", dispatch)
        block = workflow[dispatch:report]

        assert pr_creation < dispatch < report
        assert 'gh workflow run tests.yml --repo "$GITHUB_REPOSITORY" --ref main' in block
        assert '-f target_ref="$GITHUB_SHA"' in block
        assert 'gh workflow run subbot-review.yml --repo "$GITHUB_REPOSITORY" --ref main' in block
        assert '-f target_repository="$TARGET_REPOSITORY"' in block
        assert '-f target_ref="$BRANCH"' in block
        assert 'gh workflow run target-python-tests.yml --repo "$GITHUB_REPOSITORY" --ref main' in block


def test_approved_coding_workers_never_merge_after_dispatch():
    for relative_path in WORKFLOWS:
        workflow = (ROOT / relative_path).read_text(encoding="utf-8")
        dispatch = workflow.index("Dispatch")
        report = workflow.index("Report result", dispatch)
        block = workflow[dispatch:report].lower()

        assert "gh pr merge" not in block
        assert "merge_pull_request" not in block
