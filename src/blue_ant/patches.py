"""Human-approved, hash-checked file patching inside isolated workspaces.

This module never clones repositories, runs commands, installs packages, or
contacts GitHub. Callers must provide a disposable workspace and explicit
approval. It supports file creation/replacement only; deletion is intentionally
not supported.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Iterable


@dataclass(frozen=True, slots=True)
class FileChange:
    """A complete replacement for one workspace-relative UTF-8 text file.

    expected_sha256 is the current file hash, or None when creating a new file.
    """

    path: str
    content: str
    expected_sha256: str | None


@dataclass(frozen=True, slots=True)
class PatchProposal:
    proposal_id: str
    project_id: str
    task_id: str
    changes: tuple[FileChange, ...]


@dataclass(frozen=True, slots=True)
class PatchResult:
    proposal_id: str
    changed_paths: tuple[str, ...]
    created_paths: tuple[str, ...]


def sha256_text(content: str) -> str:
    """Return the SHA-256 digest of UTF-8 text."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _safe_relative_path(raw: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw:
        raise ValueError("patch path must be a non-empty POSIX relative path")
    path = PurePosixPath(raw)
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("patch path must not be absolute or contain traversal")
    if path.parts[0] == ".git" or ":" in path.parts[0]:
        raise ValueError("patch path targets a reserved location")
    return path


def _resolve_target(root: Path, relative: PurePosixPath) -> Path:
    target = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinked parent directory is not allowed: {relative}")
        if current.exists() and not current.is_dir():
            raise ValueError(f"parent path is not a directory: {relative}")
    if target.is_symlink():
        raise ValueError(f"symlink target is not allowed: {relative}")
    try:
        target.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError(f"patch path escapes workspace: {relative}") from exc
    return target


def apply_patch_proposal(
    workspace: str | Path,
    proposal: PatchProposal,
    *,
    approved: bool = False,
) -> PatchResult:
    """Apply a proposal only after explicit approval and hash validation.

    The workspace must be a dedicated, disposable checkout. All changes are
    validated before the first write. If a later write fails, prior writes are
    best-effort rolled back. This is not an OS sandbox or a multi-file atomic
    transaction.
    """
    if not approved:
        raise PermissionError("patch proposal requires explicit human approval")
    if not proposal.proposal_id.strip() or not proposal.project_id.strip() or not proposal.task_id.strip():
        raise ValueError("proposal_id, project_id, and task_id are required")
    if not proposal.changes:
        raise ValueError("patch proposal must contain at least one file change")

    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    prepared: list[tuple[Path, str, str | None]] = []
    seen: set[str] = set()
    for change in proposal.changes:
        relative = _safe_relative_path(change.path)
        normalized = relative.as_posix()
        if normalized in seen:
            raise ValueError(f"duplicate patch path: {normalized}")
        seen.add(normalized)
        if not isinstance(change.content, str):
            raise ValueError(f"patch content must be text: {normalized}")
        target = _resolve_target(root, relative)
        if target.exists():
            if not target.is_file():
                raise ValueError(f"patch target is not a regular file: {normalized}")
            current = target.read_text(encoding="utf-8")
            if change.expected_sha256 is None:
                raise ValueError(f"file already exists: {normalized}")
            if sha256_text(current) != change.expected_sha256:
                raise ValueError(f"stale patch; current file hash differs: {normalized}")
            previous = current
        else:
            if change.expected_sha256 is not None:
                raise ValueError(f"expected existing file is missing: {normalized}")
            previous = None
        prepared.append((target, change.content, previous))

    written: list[tuple[Path, str | None]] = []
    try:
        for target, new_content, previous in prepared:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.parent.is_symlink():
                raise ValueError(f"symlinked parent directory is not allowed: {target}")
            fd, temporary_name = tempfile.mkstemp(prefix=".blue-ant-", dir=target.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                    stream.write(new_content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, target)
            except Exception:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise
            written.append((target, previous))
    except Exception:
        for target, previous in reversed(written):
            try:
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_text(previous, encoding="utf-8")
            except OSError:
                # Preserve the original exception; caller must inspect workspace.
                pass
        raise

    created = tuple(path.relative_to(root).as_posix() for path, _, previous in prepared if previous is None)
    changed = tuple(path.relative_to(root).as_posix() for path, _, _ in prepared)
    return PatchResult(proposal.proposal_id, changed, created)
