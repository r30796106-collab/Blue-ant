from pathlib import Path

import pytest

from blue_ant.audit import AuditLog
from blue_ant.projects import ProjectRegistry
from blue_ant.resources import ResourcePolicy, ResourceSnapshot
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



def test_snapshot_mode_audits_private_copy_and_preserves_source(tmp_path: Path):
    source = make_project(tmp_path, "repo")
    (source / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("private git metadata", encoding="utf-8")
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("repo", source)

    results = Workforce(registry, snapshot_sources=True).run([
        WorkAssignment("snapshot-docs", "repo", SubBotRole.DOCS_AUDITOR),
    ])
    result = results[0]

    assert result.error is None
    assert result.source_root == source.resolve()
    assert result.workspace != source
    assert (result.workspace / "README.md").is_file()
    assert (result.workspace / "test_sample.py").is_file()
    assert not (result.workspace / ".env").exists()
    assert not (result.workspace / ".git").exists()
    assert (source / ".env").read_text(encoding="utf-8") == "TOKEN=secret"
    assert (source / ".git" / "config").read_text(encoding="utf-8") == "private git metadata"


def test_snapshot_mode_refuses_to_overwrite_existing_task_workspace(tmp_path: Path):
    source = make_project(tmp_path, "repo")
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("repo", source)
    workforce = Workforce(registry, snapshot_sources=True)
    assignment = WorkAssignment("snapshot-docs", "repo", SubBotRole.DOCS_AUDITOR)

    workforce.run([assignment])
    workspace = tmp_path / "workspaces" / "repo" / "tasks" / "snapshot-docs"
    marker = workspace / "human-file.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to overwrite"):
        workforce.run([assignment])

    assert marker.read_text(encoding="utf-8") == "preserve"



def test_resource_policy_caps_effective_workforce_concurrency(tmp_path: Path):
    source = make_project(tmp_path, "repo")
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("repo", source)

    workforce = Workforce(
        registry,
        max_workers=8,
        resource_policy=ResourcePolicy(
            max_workers=8,
            reserve_memory_bytes=512,
            memory_per_worker_bytes=256,
        ),
        resource_snapshot=ResourceSnapshot(cpu_count=3, available_memory_bytes=1_024),
    )

    assert workforce.requested_max_workers == 8
    assert workforce.max_workers == 2


def test_resource_policy_and_snapshot_must_be_provided_together(tmp_path: Path):
    with pytest.raises(ValueError, match="provided together"):
        Workforce(
            ProjectRegistry(tmp_path / "workspaces"),
            resource_snapshot=ResourceSnapshot(cpu_count=2, available_memory_bytes=1_024),
        )



def test_workforce_writes_and_verifies_hash_chained_audit_events(tmp_path: Path):
    source = make_project(tmp_path, "repo")
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("repo", source)
    audit_path = tmp_path / "audit.jsonl"

    results = Workforce(registry, max_workers=2, audit_path=audit_path).run([
        WorkAssignment("docs", "repo", SubBotRole.DOCS_AUDITOR),
        WorkAssignment("tests", "repo", SubBotRole.TEST_AUDITOR),
    ])

    assert len(results) == 2
    audit = AuditLog(audit_path)
    verification = audit.verify()
    assert verification.valid is True
    assert verification.records == 8
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert events[0]["event"] == "workforce_started"
    assert events[-1]["event"] == "workforce_completed"
    assert {event["event"] for event in events} >= {
        "task_workspace_prepared", "worker_started", "worker_succeeded"
    }


def test_workforce_refuses_to_run_with_tampered_audit_log(tmp_path: Path):
    source = make_project(tmp_path, "repo")
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("repo", source)
    audit_path = tmp_path / "audit.jsonl"
    audit = AuditLog(audit_path)
    audit.record("initial")
    audit_path.write_text(
        audit_path.read_text(encoding="utf-8").replace('"event": "initial"', '"event": "tampered"'),
        encoding="utf-8",
    )

    workforce = Workforce(registry, audit_path=audit_path)
    with pytest.raises(ValueError, match="failed verification"):
        workforce.run([WorkAssignment("docs", "repo", SubBotRole.DOCS_AUDITOR)])

    assert not (tmp_path / "workspaces" / "repo").exists()
