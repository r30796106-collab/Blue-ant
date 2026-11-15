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
