from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ".github/workflows/issue-approved-pr.yml",
    ".github/workflows/plan-linked-approved-pr.yml",
)
TARGET_TEST_DISPATCH = (
    'gh workflow run target-python-tests.yml --repo "$GITHUB_REPOSITORY" '
    '--ref main -f target_repository="$TARGET_REPOSITORY" -f target_ref="$BRANCH"'
)
SAME_REPOSITORY_SKIP = (
    'Same-repository pull-request CI already runs against the PR head; '
    'skipping the standard-library-only target test runner.'
)
TOKEN_SELECTOR = (
    "${{ steps.instruction.outputs.target_repository == github.repository "
    "&& github.token || secrets.BLUE_ANT_WORKER_TOKEN }}"
)


def test_approved_coding_workers_dispatch_post_pr_verification_workflows():
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

        guard_start = block.index('if [ "$TARGET_REPOSITORY" != "$GITHUB_REPOSITORY" ]; then')
        guard_end = block.index("\n          fi", guard_start)
        guarded_block = block[guard_start:guard_end]
        assert TARGET_TEST_DISPATCH in guarded_block
        assert "else" in guarded_block
        assert SAME_REPOSITORY_SKIP in guarded_block


def test_plan_linked_worker_prefers_github_token_for_same_repository():
    workflow = (ROOT / WORKFLOWS[1]).read_text(encoding="utf-8")

    assert workflow.count(TOKEN_SELECTOR) == 3
    assert "${{ secrets.BLUE_ANT_WORKER_TOKEN || github.token }}" not in workflow


def test_issue_worker_keeps_same_repository_first_token_selection():
    workflow = (ROOT / WORKFLOWS[0]).read_text(encoding="utf-8")

    assert workflow.count(TOKEN_SELECTOR) == 3
    assert "${{ secrets.BLUE_ANT_WORKER_TOKEN || github.token }}" not in workflow


def test_approved_coding_workers_never_merge_after_dispatch():
    for relative_path in WORKFLOWS:
        workflow = (ROOT / relative_path).read_text(encoding="utf-8")
        dispatch = workflow.index("Dispatch")
        report = workflow.index("Report result", dispatch)
        block = workflow[dispatch:report].lower()

        assert "gh pr merge" not in block
        assert "merge_pull_request" not in block
