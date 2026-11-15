from pathlib import Path

import pytest

from blue_ant.projects import ProjectRegistry
from blue_ant.subbots import SubBotRole
from blue_ant.workforce import WorkAssignment, Workforce


def make_project(root: Path, name: str) -> Path:
    source = root / name
    source.mkdir()
    (source / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    (source / "test_sample.py").write_text("def test_sample(): pass\n", encoding="utf-8")
    return source


def test_runs_multiple_tasks_in_one_project_and_multiple_projects(tmp_path: Path):
    source_a = make_project(tmp_path, "repo-a")
    source_b = make_project(tmp_path, "repo-b")
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("repo-a", source_a)
    registry.register("repo-b", source_b)

    assignments = [
        WorkAssignment("a-repo", "repo-a", SubBotRole.REPO_ANALYST),
        WorkAssignment("a-tests", "repo-a", SubBotRole.TEST_AUDITOR),
        WorkAssignment("a-docs", "repo-a", SubBotRole.DOCS_AUDITOR),
        WorkAssignment("b-repo", "repo-b", SubBotRole.REPO_ANALYST),
        WorkAssignment("b-safety", "repo-b", SubBotRole.SAFETY_AUDITOR),
    ]
    results = Workforce(registry, max_workers=3).run(assignments)

    assert len(results) == 5
    assert {(item.project_id, item.task_id) for item in results} == {
        ("repo-a", "a-repo"), ("repo-a", "a-tests"), ("repo-a", "a-docs"),
        ("repo-b", "b-repo"), ("repo-b", "b-safety"),
    }
    assert all(item.error is None for item in results)
    assert len({item.workspace for item in results}) == 5
    assert all(item.workspace.is_dir() for item in results)
    assert all(item.source_root in (source_a, source_b) for item in results)
    assert any("Indexed" in finding.message for item in results for finding in item.findings)


def test_worker_failure_isolated_from_other_assignments(tmp_path: Path, monkeypatch):
    source = make_project(tmp_path, "repo")
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("repo", source)

    from blue_ant.subbots import SubBot

    original_run = SubBot.run

    def selective_run(self, root):
        if self.role == SubBotRole.SAFETY_AUDITOR:
            raise RuntimeError("test worker failure")
        return original_run(self, root)

    monkeypatch.setattr(SubBot, "run", selective_run)
    results = Workforce(registry, max_workers=2).run([
        WorkAssignment("docs", "repo", SubBotRole.DOCS_AUDITOR),
        WorkAssignment("safety", "repo", SubBotRole.SAFETY_AUDITOR),
    ])
    assert results[0].task_id == "docs"
    assert results[0].error is None
    assert results[1].task_id == "safety"
    assert results[1].error == "RuntimeError: test worker failure"


def test_rejects_duplicate_or_invalid_assignments(tmp_path: Path):
    source = make_project(tmp_path, "repo")
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("repo", source)
    workforce = Workforce(registry)

    with pytest.raises(ValueError, match="duplicate task_id"):
        workforce.run([
            WorkAssignment("same", "repo", SubBotRole.DOCS_AUDITOR),
            WorkAssignment("same", "repo", SubBotRole.TEST_AUDITOR),
        ])
    with pytest.raises(ValueError, match="lowercase slug"):
        workforce.run([WorkAssignment("../bad", "repo", SubBotRole.DOCS_AUDITOR)])
    with pytest.raises(KeyError):
        workforce.run([WorkAssignment("unknown", "missing", SubBotRole.DOCS_AUDITOR)])


def test_enforces_worker_and_task_limits(tmp_path: Path):
    with pytest.raises(ValueError):
        Workforce(ProjectRegistry(tmp_path), max_workers=17)
    with pytest.raises(ValueError):
        Workforce(ProjectRegistry(tmp_path), max_tasks=257)
    with pytest.raises(ValueError):
        Workforce(ProjectRegistry(tmp_path)).run([])
