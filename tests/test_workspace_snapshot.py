from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from blue_ant.workspace_snapshot import create_workspace_snapshot


def test_snapshot_copies_regular_project_files_and_skips_generated_and_sensitive_content(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "app.py").write_text("print('safe')\\n", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("git metadata", encoding="utf-8")
    (source / "node_modules").mkdir()
    (source / "node_modules" / "package.js").write_text("generated", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "module.pyc").write_bytes(b"cache")
    (source / ".env").write_text("SECRET=do-not-copy", encoding="utf-8")
    (source / ".env.local").write_text("SECRET=do-not-copy", encoding="utf-8")
    (source / "private.pem").write_text("PRIVATE KEY", encoding="utf-8")
    (source / ".env.example").write_text("EXAMPLE=value", encoding="utf-8")
    destination = tmp_path / "workspaces" / "task-one"
    destination.parent.mkdir()

    result = create_workspace_snapshot(source, destination)

    assert result.files_copied == 2
    assert result.bytes_copied == len("print('safe')\\nEXAMPLE=value".encode())
    assert (destination / "src" / "app.py").read_text(encoding="utf-8") == "print('safe')\\n"
    assert (destination / ".env.example").read_text(encoding="utf-8") == "EXAMPLE=value"
    assert not (destination / ".git").exists()
    assert not (destination / "node_modules").exists()
    assert not (destination / "__pycache__").exists()
    assert not (destination / ".env").exists()
    assert not (destination / ".env.local").exists()
    assert not (destination / "private.pem").exists()
    assert set(result.skipped_sensitive_files) == {".env", ".env.local", "private.pem"}
    assert set(result.skipped_directories) == {".git", "node_modules", "__pycache__"}
    assert stat.S_IMODE((destination / "src" / "app.py").stat().st_mode) == 0o600
    assert (source / ".env").read_text(encoding="utf-8") == "SECRET=do-not-copy"


def test_snapshot_rejects_symlinked_source_files_and_rolls_back(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("copied first", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("do not read", encoding="utf-8")
    (source / "z-link.txt").symlink_to(outside)
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="symlinked file"):
        create_workspace_snapshot(source, destination)

    assert not destination.exists()
    assert outside.read_text(encoding="utf-8") == "do not read"
    assert (source / "a.txt").read_text(encoding="utf-8") == "copied first"


def test_snapshot_rejects_symlinked_directories(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (source / "linked-dir").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked directory"):
        create_workspace_snapshot(source, tmp_path / "snapshot")


def test_snapshot_enforces_file_count_limit_and_cleans_partial_output(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "b.txt").write_text("b", encoding="utf-8")
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="exceeds 1 files"):
        create_workspace_snapshot(source, destination, max_files=1)

    assert not destination.exists()


def test_snapshot_enforces_per_file_and_total_byte_limits(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("12345", encoding="utf-8")
    destination = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="exceeds 4 bytes"):
        create_workspace_snapshot(source, destination, max_file_bytes=4)
    assert not destination.exists()

    (source / "a.txt").write_text("123", encoding="utf-8")
    (source / "b.txt").write_text("456", encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds 5 total bytes"):
        create_workspace_snapshot(source, destination, max_total_bytes=5)
    assert not destination.exists()


def test_snapshot_requires_empty_destination_and_never_overwrites(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "new.txt").write_text("new", encoding="utf-8")
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="empty directory"):
        create_workspace_snapshot(source, destination)

    assert (destination / "existing.txt").read_text(encoding="utf-8") == "keep"


def test_snapshot_rejects_source_destination_overlap_and_symlink_root(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "nested").mkdir()

    with pytest.raises(ValueError, match="outside source_root"):
        create_workspace_snapshot(source, source / "nested" / "snapshot")

    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="source_root"):
        create_workspace_snapshot(alias, tmp_path / "snapshot")


def test_snapshot_rejects_invalid_limits(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="max_files"):
        create_workspace_snapshot(source, tmp_path / "snapshot", max_files=0)



def test_snapshot_rejects_symlinked_destination_parent(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        create_workspace_snapshot(source, linked_parent / "snapshot")

    assert list(real_parent.iterdir()) == []
