import json

from blue_ant.project_cli import main


def test_cli_registers_and_lists_persistent_projects(tmp_path, capsys):
    source = tmp_path / "elon"
    source.mkdir()
    registry = tmp_path / ".blue-ant" / "projects.json"
    workspaces = tmp_path / ".blue-ant" / "workspaces"
    args = ["--registry", str(registry), "--workspace-root", str(workspaces)]

    assert main(args + ["register", "elon", str(source)]) == 0
    registered = json.loads(capsys.readouterr().out)
    assert registered["status"] == "registered"
    assert registered["project_id"] == "elon"

    assert main(args + ["list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["projects"] == [
        {"project_id": "elon", "source_root": str(source.resolve())}
    ]


def test_cli_workspace_lookup_is_read_only_until_create_is_requested(tmp_path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    registry = tmp_path / "projects.json"
    workspaces = tmp_path / "workspaces"
    args = ["--registry", str(registry), "--workspace-root", str(workspaces)]

    assert main(args + ["register", "project", str(source)]) == 0
    capsys.readouterr()

    assert main(args + ["workspace", "project"]) == 0
    lookup = json.loads(capsys.readouterr().out)
    assert lookup["created"] is False
    assert lookup["exists"] is False
    assert not workspaces.exists()

    assert main(args + ["workspace", "project", "--create"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["created"] is True
    assert created["exists"] is True
    assert (workspaces / "project").is_dir()


def test_cli_returns_error_for_unregistered_project(tmp_path, capsys):
    registry = tmp_path / "projects.json"
    workspaces = tmp_path / "workspaces"

    assert main([
        "--registry", str(registry),
        "--workspace-root", str(workspaces),
        "workspace", "missing",
    ]) == 2
    assert "project is not registered" in capsys.readouterr().err
