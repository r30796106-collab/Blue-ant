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
