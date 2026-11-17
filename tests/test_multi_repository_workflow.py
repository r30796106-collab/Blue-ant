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
    assert "max_parallel_projects" in workflow
    assert "max-parallel: ${{ fromJSON(needs.prepare.outputs.max_parallel_projects) }}" in workflow
    assert '--max-workers "${{ matrix.project.max_workers }}"' in workflow
    assert "timeout-minutes: 30" in workflow



def test_multi_repository_workforce_audits_a_verified_baseline_descendant_in_private_snapshots():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "fetch-depth: 0" in workflow
    assert "merge-base --is-ancestor" in workflow
    assert "inspected_commit_sha" in workflow
    assert "args+=(--snapshot-sources --shared-snapshot-sources)" in workflow


def test_multi_repository_workforce_uses_registry_limits_not_hardcoded_worker_counts():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "--github-output \"$GITHUB_OUTPUT\"" in workflow
    assert "max_parallel_projects=" in (ROOT / "src" / "blue_ant" / "portfolio_cli.py").read_text(encoding="utf-8")
    assert "max_workers" in (ROOT / "src" / "blue_ant" / "portfolio_cli.py").read_text(encoding="utf-8")
