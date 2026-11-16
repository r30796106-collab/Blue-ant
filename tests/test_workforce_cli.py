import json
import sys
import threading
import time
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



def test_cli_does_not_probe_resources_without_explicit_opt_in(tmp_path: Path, monkeypatch):
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
        "--output", str(output),
    ])

    def unexpected_probe():
        raise AssertionError("resource detection must remain opt-in")

    monkeypatch.setattr("blue_ant.workforce_cli.ResourceSnapshot.detect", unexpected_probe)

    assert main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["resource_detection"] is None
    assert report["resource_snapshot"] is None
    assert report["effective_max_workers"] == 4


def test_cli_fails_closed_when_opt_in_detection_is_unsupported(tmp_path: Path, monkeypatch):
    source = tmp_path / "sample"
    source.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample=" + str(source),
        "--roles", "docs_auditor",
        "--workspace-root", str(tmp_path / "workspaces"),
        "--detect-resources",
        "--output", str(tmp_path / "report.json"),
    ])

    def unsupported_host():
        raise RuntimeError("Linux /proc/meminfo is unavailable")

    monkeypatch.setattr("blue_ant.workforce_cli.ResourceSnapshot.detect", unsupported_host)

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("unsupported resource detection must fail closed")
    assert not (tmp_path / "report.json").exists()



def test_cli_calls_opt_in_resource_detection_exactly_once(tmp_path: Path, monkeypatch):
    from blue_ant.resources import ResourceSnapshot

    source = tmp_path / "sample"
    source.mkdir()
    (source / "README.md").write_text("# Sample\n", encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample=" + str(source),
        "--roles", "docs_auditor",
        "--workspace-root", str(tmp_path / "workspaces"),
        "--detect-resources",
        "--reserve-memory-mb", "0",
        "--memory-per-worker-mb", "1",
        "--output", str(output),
    ])
    calls = 0

    def detect_once():
        nonlocal calls
        calls += 1
        return ResourceSnapshot(cpu_count=2, available_memory_bytes=4 * 1024 * 1024)

    monkeypatch.setattr("blue_ant.workforce_cli.ResourceSnapshot.detect", detect_once)

    assert main() == 0
    assert calls == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["effective_max_workers"] == 2


def test_cli_fails_closed_when_detected_memory_cannot_support_one_worker(
    tmp_path: Path, monkeypatch
):
    from blue_ant.resources import ResourceSnapshot

    source = tmp_path / "sample"
    source.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample=" + str(source),
        "--roles", "docs_auditor",
        "--workspace-root", str(tmp_path / "workspaces"),
        "--detect-resources",
        "--reserve-memory-mb", "512",
        "--memory-per-worker-mb", "256",
        "--output", str(tmp_path / "report.json"),
    ])
    calls = 0

    def detect_low_memory():
        nonlocal calls
        calls += 1
        return ResourceSnapshot(cpu_count=4, available_memory_bytes=128 * 1024 * 1024)

    monkeypatch.setattr("blue_ant.workforce_cli.ResourceSnapshot.detect", detect_low_memory)

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("insufficient detected memory must fail closed")

    assert calls == 1
    assert not (tmp_path / "report.json").exists()


def test_cli_detected_resources_limit_actual_worker_concurrency(tmp_path: Path, monkeypatch):
    from blue_ant.resources import ResourceSnapshot
    from blue_ant.subbots import SubBot

    source = tmp_path / "sample"
    source.mkdir()
    (source / "README.md").write_text("# Sample\\n", encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "blue-ant-workforce",
        "--project", "sample=" + str(source),
        "--workspace-root", str(tmp_path / "workspaces"),
        "--max-workers", "8",
        "--detect-resources",
        "--reserve-memory-mb", "0",
        "--memory-per-worker-mb", "1",
        "--output", str(output),
    ])
    monkeypatch.setattr(
        "blue_ant.workforce_cli.ResourceSnapshot.detect",
        lambda: ResourceSnapshot(cpu_count=3, available_memory_bytes=2 * 1024 * 1024),
    )

    lock = threading.Lock()
    active = 0
    peak = 0

    def measured_run(self, root, indexed_files=None):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return ()

    monkeypatch.setattr(SubBot, "run", measured_run)

    assert main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(report["assignments"]) == 4
    assert report["requested_max_workers"] == 8
    assert report["effective_max_workers"] == 2
    assert peak == 2
    assert all(item["error"] is None for item in report["assignments"])
