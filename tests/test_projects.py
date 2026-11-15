from pathlib import Path
import json

import pytest

from blue_ant.projects import ProjectRegistry


def test_register_and_list_projects_in_stable_order(tmp_path: Path):
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    source_a.mkdir()
    source_b.mkdir()
    registry = ProjectRegistry(tmp_path / "workspaces")

    registry.register("trading", source_b)
    registry.register("elon", source_a)

    assert [item.project_id for item in registry.list_projects()] == ["elon", "trading"]
    assert registry.get("elon").source_root == source_a.resolve()


def test_rejects_invalid_and_duplicate_project_ids(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    registry = ProjectRegistry(tmp_path / "workspaces")

    for invalid in ("../escape", "Uppercase", "", "a" * 49, "two words"):
        with pytest.raises(ValueError):
            registry.register(invalid, source)

    registry.register("valid-project", source)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("valid-project", source)


def test_register_requires_existing_real_directory(tmp_path: Path):
    registry = ProjectRegistry(tmp_path / "workspaces")
    with pytest.raises(FileNotFoundError):
        registry.register("missing", tmp_path / "missing")

    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        registry.register("file-root", file_path)


def test_workspace_is_separate_and_created_only_when_requested(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "important.txt").write_text("keep", encoding="utf-8")
    workspace_root = tmp_path / "workspaces"
    registry = ProjectRegistry(workspace_root)
    registry.register("animation", source)

    workspace = registry.workspace_for("animation")
    assert workspace == workspace_root / "animation"
    assert not workspace_root.exists()

    created = registry.workspace_for("animation", create=True)
    assert created.is_dir()
    assert not (created / "important.txt").exists()
    assert (source / "important.txt").read_text(encoding="utf-8") == "keep"


def test_each_project_gets_a_distinct_workspace(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("elon", source)
    registry.register("trading", source)

    first = registry.workspace_for("elon", create=True)
    second = registry.workspace_for("trading", create=True)
    assert first != second
    assert first.parent == second.parent


def test_rejects_unregistered_project_and_workspace_symlinks(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("project", source)

    with pytest.raises(KeyError):
        registry.workspace_for("unknown", create=True)

    registry.workspace_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (registry.workspace_root / "project").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        registry.workspace_for("project", create=True)


def test_rejects_symlink_source_root(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    registry = ProjectRegistry(tmp_path / "workspaces")

    with pytest.raises(ValueError, match="symlink"):
        registry.register("project", alias)



def test_persistent_registry_round_trips_projects_in_stable_order(tmp_path: Path):
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    source_a.mkdir()
    source_b.mkdir()
    workspace_root = tmp_path / "workspaces"
    registry_path = tmp_path / ".blue-ant" / "projects.json"

    registry = ProjectRegistry(workspace_root, registry_path=registry_path)
    registry.register("trading", source_b)
    registry.register("elon", source_a)

    loaded = ProjectRegistry(workspace_root, registry_path=registry_path)
    assert [item.project_id for item in loaded.list_projects()] == ["elon", "trading"]
    assert loaded.get("elon").source_root == source_a.resolve()
    assert loaded.workspace_for("elon") == workspace_root / "elon"
    assert registry_path.stat().st_mode & 0o777 == 0o600


def test_persistent_registry_rejects_unsupported_or_malformed_schema(tmp_path: Path):
    registry_path = tmp_path / "projects.json"
    registry_path.write_text(json.dumps({"schema_version": 99, "projects": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        ProjectRegistry(tmp_path / "workspaces", registry_path=registry_path)

    registry_path.write_text(json.dumps({"schema_version": 1, "projects": "not-a-list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a list"):
        ProjectRegistry(tmp_path / "workspaces", registry_path=registry_path)


def test_persistent_registry_rejects_symlink_registry_file(tmp_path: Path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"schema_version": 1, "projects": []}), encoding="utf-8")
    linked = tmp_path / "projects.json"
    linked.symlink_to(outside)

    with pytest.raises(ValueError, match="registry_path"):
        ProjectRegistry(tmp_path / "workspaces", registry_path=linked)


def test_persistent_registry_revalidates_registered_source_roots(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    registry_path = tmp_path / "projects.json"
    ProjectRegistry(tmp_path / "workspaces", registry_path=registry_path).register("project", source)
    source.rmdir()

    with pytest.raises(ValueError, match="unavailable"):
        ProjectRegistry(tmp_path / "workspaces", registry_path=registry_path)


def test_persistent_registry_rejects_symlink_parent_and_rolls_back_registration(tmp_path: Path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    source = tmp_path / "source"
    source.mkdir()
    registry = ProjectRegistry(tmp_path / "workspaces", registry_path=linked_parent / "projects.json")

    with pytest.raises(ValueError, match="parent directories"):
        registry.register("project", source)
    assert registry.list_projects() == ()
    assert list(real_parent.iterdir()) == []


def test_registry_remains_in_memory_when_persistence_is_not_requested(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    registry_path = tmp_path / "projects.json"
    registry = ProjectRegistry(tmp_path / "workspaces")
    registry.register("project", source)

    assert registry.get("project").source_root == source.resolve()
    assert not registry_path.exists()
