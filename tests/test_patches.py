from pathlib import Path
import json
from blue_ant.audit import AuditLog

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



def test_patch_rejects_more_than_ten_files_before_writing(tmp_path: Path):
    changes = tuple(FileChange(f"{index}.txt", "x", None) for index in range(11))
    with pytest.raises(ValueError, match="exceeds 10 files"):
        apply_patch_proposal(tmp_path, PatchProposal("p", "demo", "task", changes), approved=True)
    assert list(tmp_path.iterdir()) == []


def test_patch_rejects_single_file_over_one_megabyte(tmp_path: Path):
    change = FileChange("large.txt", "x" * 1_000_001, None)
    with pytest.raises(ValueError, match="exceeds 1000000 bytes"):
        apply_patch_proposal(tmp_path, proposal(change), approved=True)
    assert list(tmp_path.iterdir()) == []


def test_patch_rejects_combined_content_over_two_megabytes(tmp_path: Path):
    changes = tuple(
        FileChange(f"{index}.txt", "x" * 700_000, None)
        for index in range(3)
    )
    with pytest.raises(ValueError, match="combined patch content"):
        apply_patch_proposal(tmp_path, PatchProposal("p", "demo", "task", changes), approved=True)
    assert list(tmp_path.iterdir()) == []


def test_patch_rejects_symlink_workspace_root(tmp_path: Path):
    real_workspace = tmp_path / "real"
    real_workspace.mkdir()
    linked_workspace = tmp_path / "linked"
    linked_workspace.symlink_to(real_workspace, target_is_directory=True)

    with pytest.raises(ValueError, match="workspace root"):
        apply_patch_proposal(
            linked_workspace,
            proposal(FileChange("new.txt", "content", None)),
            approved=True,
        )
    assert list(real_workspace.iterdir()) == []


def test_patch_preserves_existing_file_permissions_and_restricts_new_file(tmp_path: Path):
    import os
    import stat

    existing = tmp_path / "script.py"
    existing.write_text("print('old')\\n", encoding="utf-8")
    os.chmod(existing, 0o755)

    apply_patch_proposal(
        tmp_path,
        proposal(
            FileChange("script.py", "print('new')\\n", sha256_text("print('old')\\n")),
            FileChange("new.txt", "created", None),
        ),
        approved=True,
    )

    assert stat.S_IMODE(existing.stat().st_mode) == 0o755
    assert stat.S_IMODE((tmp_path / "new.txt").stat().st_mode) == 0o600


def test_patch_rejects_malformed_expected_hash(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        apply_patch_proposal(
            tmp_path,
            proposal(FileChange("file.txt", "new", "not-a-hash")),
            approved=True,
        )
    assert target.read_text(encoding="utf-8") == "old"


def test_patch_rolls_back_prior_file_when_later_replace_fails(tmp_path: Path, monkeypatch):
    import blue_ant.patches as patch_module

    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first-old", encoding="utf-8")
    second.write_text("second-old", encoding="utf-8")
    original_replace = patch_module.os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replacement failure")
        return original_replace(source, destination)

    monkeypatch.setattr(patch_module.os, "replace", fail_second_replace)
    changes = proposal(
        FileChange("first.txt", "first-new", sha256_text("first-old")),
        FileChange("second.txt", "second-new", sha256_text("second-old")),
    )

    audit = AuditLog(tmp_path.parent / "patch-failure-audit.jsonl")
    with pytest.raises(OSError, match="simulated"):
        apply_patch_proposal(tmp_path, changes, approved=True, audit=audit)

    verification = audit.verify()
    assert verification.valid is True
    events = [json.loads(line)["event"] for line in audit.path.read_text(encoding="utf-8").splitlines()]
    assert events == ["patch_apply_started", "patch_apply_failed"]
    assert first.read_text(encoding="utf-8") == "first-old"
    assert second.read_text(encoding="utf-8") == "second-old"
    assert not list(tmp_path.glob(".blue-ant-*"))



def test_patch_writes_hash_chained_audit_events_on_success(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    audit = AuditLog(tmp_path / "patch-audit.jsonl")
    result = apply_patch_proposal(
        workspace,
        proposal(FileChange("created.txt", "content", None)),
        approved=True,
        audit=audit,
    )

    verification = audit.verify()
    assert result.created_paths == ("created.txt",)
    assert verification.valid is True
    assert verification.records == 2
    events = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]
    assert [item["event"] for item in events] == ["patch_apply_started", "patch_apply_succeeded"]
    assert events[0]["paths"] == ["created.txt"]


def test_patch_refuses_to_modify_its_own_audit_log(tmp_path: Path):
    workspace = tmp_path / "workspace"
    audit_path = workspace / ".blue-ant" / "patch-audit.jsonl"
    audit = AuditLog(audit_path)

    with pytest.raises(ValueError, match="cannot modify its own audit log"):
        apply_patch_proposal(
            workspace,
            proposal(FileChange(".blue-ant/patch-audit.jsonl", "forged", None)),
            approved=True,
            audit=audit,
        )


def test_patch_refuses_a_previously_tampered_audit_log(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    audit = AuditLog(tmp_path / "patch-audit.jsonl")
    audit.record("initial")
    audit.path.write_text(
        audit.path.read_text(encoding="utf-8").replace('"event": "initial"', '"event": "changed"'),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="failed verification"):
        apply_patch_proposal(
            workspace,
            proposal(FileChange("new.txt", "content", None)),
            approved=True,
            audit=audit,
        )
    assert not (workspace / "new.txt").exists()


def test_patch_rejects_symlinked_parent_directory(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "protected.txt"
    protected.write_text("preserve", encoding="utf-8")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked parent"):
        apply_patch_proposal(
            tmp_path,
            proposal(FileChange("linked/protected.txt", "overwrite", sha256_text("preserve"))),
            approved=True,
        )

    assert protected.read_text(encoding="utf-8") == "preserve"
