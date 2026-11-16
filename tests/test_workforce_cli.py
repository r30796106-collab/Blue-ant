import json
import sys
from pathlib import Path

from blue_ant.workforce_cli import main


def test_cli_generates_valid_task_ids_for_first_project(tmp_path: Path, monkeypatch):
    source = tmp_path / "sample"
    source.mkdir()
    (source / "README.md").write_text("# Sample\n", encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample_project=" + str(source),
        "--roles", "docs_auditor",
        "--workspace-root", str(tmp_path / "workspaces"),
        "--output", str(output),
    ])

    assert main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(report["assignments"]) == 1
    task_id = report["assignments"][0]["task_id"]
    assert task_id.startswith("task-0-")
    assert task_id[0].isalpha()
    assert report["assignments"][0]["error"] is None



def test_cli_exposes_snapshot_sources_mode(tmp_path: Path, monkeypatch):
    source = tmp_path / "sample"
    source.mkdir()
    (source / "README.md").write_text("# Sample\\n", encoding="utf-8")
    (source / ".env").write_text("TOKEN=secret", encoding="utf-8")
    output = tmp_path / "report.json"
    workspace_root = tmp_path / "workspaces"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample=" + str(source),
        "--roles", "docs_auditor",
        "--workspace-root", str(workspace_root),
        "--snapshot-sources",
        "--output", str(output),
    ])

    assert main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["workspace_mode"] == "bounded_source_snapshot"
    workspace = Path(report["assignments"][0]["workspace"])
    assert (workspace / "README.md").is_file()
    assert not (workspace / ".env").exists()
    assert (source / ".env").read_text(encoding="utf-8") == "TOKEN=secret"



def test_cli_reports_resource_aware_effective_worker_limit(tmp_path: Path, monkeypatch):
    source = tmp_path / "sample"
    source.mkdir()
    (source / "README.md").write_text("# Sample\\n", encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample=" + str(source),
        "--roles", "docs_auditor",
        "--workspace-root", str(tmp_path / "workspaces"),
        "--max-workers", "8",
        "--cpu-count", "3",
        "--available-memory-mb", "1",
        "--reserve-memory-mb", "0",
        "--memory-per-worker-mb", "1",
        "--output", str(output),
    ])

    assert main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["requested_max_workers"] == 8
    assert report["effective_max_workers"] == 1
    assert report["resource_snapshot"]["cpu_count"] == 3
    assert report["resource_snapshot"]["available_memory_bytes"] == 1024 * 1024



def test_cli_emits_verified_audit_log_when_requested(tmp_path: Path, monkeypatch):
    source = tmp_path / "sample"
    source.mkdir()
    (source / "README.md").write_text("# Sample\\n", encoding="utf-8")
    output = tmp_path / "report.json"
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample=" + str(source),
        "--roles", "docs_auditor",
        "--workspace-root", str(tmp_path / "workspaces"),
        "--audit-log", str(audit_path),
        "--output", str(output),
    ])

    assert main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["audit_log"] == str(audit_path.resolve())
    assert report["audit_verification"]["valid"] is True
    assert report["audit_verification"]["records"] == 5



def test_cli_detect_resources_is_explicit_and_reports_detected_capacity(tmp_path: Path, monkeypatch):
    from blue_ant.resources import ResourceSnapshot

    source = tmp_path / "sample"
    source.mkdir()
    (source / "README.md").write_text("# Sample\\n", encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample=" + str(source),
        "--roles", "docs_auditor",
        "--workspace-root", str(tmp_path / "workspaces"),
        "--max-workers", "8",
        "--detect-resources",
        "--reserve-memory-mb", "0",
        "--memory-per-worker-mb", "1",
        "--output", str(output),
    ])
    monkeypatch.setattr(
        "blue_ant.workforce_cli.ResourceSnapshot.detect",
        lambda: ResourceSnapshot(cpu_count=3, available_memory_bytes=10 * 1024 * 1024),
    )

    assert main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["resource_detection"] == "linux_procfs_cgroup_opt_in"
    assert report["requested_max_workers"] == 8
    assert report["effective_max_workers"] == 3
    assert report["resource_snapshot"]["cpu_count"] == 3


def test_cli_rejects_detect_resources_with_manual_capacity(tmp_path: Path, monkeypatch):
    source = tmp_path / "sample"
    source.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample=" + str(source),
        "--detect-resources",
        "--cpu-count", "2",
        "--available-memory-mb", "1024",
    ])

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("conflicting resource options must be rejected")
