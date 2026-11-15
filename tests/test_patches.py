from pathlib import Path

import pytest

from blue_ant.patches import (
    FileChange,
    PatchProposal,
    apply_patch_proposal,
    sha256_text,
)


def proposal(*changes: FileChange) -> PatchProposal:
    return PatchProposal("proposal-1", "demo", "task-1", tuple(changes))


def test_patch_requires_explicit_approval(tmp_path: Path):
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    change = FileChange("a.txt", "new", sha256_text("old"))
    with pytest.raises(PermissionError, match="approval"):
        apply_patch_proposal(tmp_path, proposal(change))
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old"


def test_patch_replaces_existing_file_and_creates_new_file(tmp_path: Path):
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    result = apply_patch_proposal(
        tmp_path,
        proposal(
            FileChange("a.txt", "new", sha256_text("old")),
            FileChange("nested/b.txt", "created", None),
        ),
        approved=True,
    )
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new"
    assert (tmp_path / "nested/b.txt").read_text(encoding="utf-8") == "created"
    assert result.changed_paths == ("a.txt", "nested/b.txt")
    assert result.created_paths == ("nested/b.txt",)


@pytest.mark.parametrize("path", ["../escape.txt", "/absolute.txt", ".git/config", "a\\b.txt"])
def test_patch_rejects_unsafe_paths(tmp_path: Path, path: str):
    with pytest.raises(ValueError):
        apply_patch_proposal(
            tmp_path,
            proposal(FileChange(path, "x", None)),
            approved=True,
        )


def test_patch_rejects_stale_hash_without_writing(tmp_path: Path):
    (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="stale patch"):
        apply_patch_proposal(
            tmp_path,
            proposal(FileChange("a.txt", "new", sha256_text("old"))),
            approved=True,
        )
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "changed"


def test_patch_rejects_symlink_target(tmp_path: Path):
    outside = tmp_path.parent / "blue-ant-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        apply_patch_proposal(
            tmp_path,
            proposal(FileChange("link.txt", "overwrite", sha256_text("outside"))),
            approved=True,
        )
    assert outside.read_text(encoding="utf-8") == "outside"
    outside.unlink()


def test_patch_rejects_duplicate_paths_and_existing_new_file(tmp_path: Path):
    duplicate = proposal(FileChange("a.txt", "one", None), FileChange("a.txt", "two", None))
    with pytest.raises(ValueError, match="duplicate"):
        apply_patch_proposal(tmp_path, duplicate, approved=True)

    (tmp_path / "exists.txt").write_text("here", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        apply_patch_proposal(
            tmp_path,
            proposal(FileChange("exists.txt", "replace", None)),
            approved=True,
        )
