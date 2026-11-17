"""Human-approved, hash-checked file patching inside isolated workspaces.

This module never clones repositories, runs commands, installs packages, or
contacts GitHub. Callers must provide a disposable workspace and explicit
approval. It supports bounded file creation/replacement only; deletion is
intentionally not supported.
"""
from __future__ import annotations

from .audit import AuditLog
from .portfolio import PortfolioRegistry
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile


_MAX_PATCH_FILES = 10
_MAX_FILE_BYTES = 1_000_000
_MAX_TOTAL_BYTES = 2_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def _reject_symlink_components(path: Path) -> None:
    """Reject symlinks in every component of the supplied workspace path."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            if current == absolute:
                raise ValueError("workspace root must not be a symlink")
            raise ValueError(f"workspace path contains a symlink component: {current}")


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


def _atomic_write(target: Path, content: str, mode: int) -> None:
    """Write UTF-8 content through a same-directory temporary file."""
    encoded = content.encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(prefix=".blue-ant-", dir=target.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def apply_patch_proposal(
    workspace: str | Path,
    proposal: PatchProposal,
    *,
    approved: bool = False,
    audit: AuditLog | None = None,
    portfolio_registry: PortfolioRegistry,
) -> PatchResult:
    """Apply an explicitly approved proposal after complete validation.

    Every file is validated before the first write. Replacements preserve the
    original permission bits; newly created files use owner-only permissions.
    If a later replacement fails, earlier writes are restored on a best-effort
    basis using atomic per-file replacement. This is not a globally atomic
    multi-file transaction or an OS sandbox; callers must use a disposable
    workspace that is not concurrently modified by untrusted processes.
    """
    if not approved:
        raise PermissionError("patch proposal requires explicit human approval")
    if not isinstance(proposal, PatchProposal):
        raise TypeError("proposal must be a PatchProposal")
    for field_name in ("proposal_id", "project_id", "task_id"):
        value = getattr(proposal, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required")
    if not isinstance(proposal.changes, tuple) or not proposal.changes:
        raise ValueError("patch proposal must contain at least one file change")
    if len(proposal.changes) > _MAX_PATCH_FILES:
        raise ValueError(f"patch proposal exceeds {_MAX_PATCH_FILES} files")
    if not isinstance(portfolio_registry, PortfolioRegistry):
        raise TypeError("portfolio_registry must be a PortfolioRegistry")
    scope_paths = []
    for change in proposal.changes:
        if not isinstance(change, FileChange):
            raise TypeError("each patch change must be a FileChange")
        scope_paths.append(_safe_relative_path(change.path).as_posix())
    portfolio_registry.validate_paths(proposal.project_id, scope_paths)

    supplied_root = Path(workspace).expanduser()
    _reject_symlink_components(supplied_root)
    root = supplied_root.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    if audit is not None and not isinstance(audit, AuditLog):
        raise TypeError("audit must be an AuditLog instance")
    prepared: list[tuple[Path, str, str | None, int]] = []
    seen: set[str] = set()
    total_bytes = 0
    for change in proposal.changes:
        if not isinstance(change, FileChange):
            raise TypeError("each patch change must be a FileChange")
        relative = _safe_relative_path(change.path)
        normalized = relative.as_posix()
        if normalized in seen:
            raise ValueError(f"duplicate patch path: {normalized}")
        seen.add(normalized)
        if not isinstance(change.content, str):
            raise ValueError(f"patch content must be text: {normalized}")
        try:
            new_bytes = change.content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(f"patch content is not valid UTF-8 text: {normalized}") from exc
        if len(new_bytes) > _MAX_FILE_BYTES:
            raise ValueError(f"patch file exceeds {_MAX_FILE_BYTES} bytes: {normalized}")
        total_bytes += len(new_bytes)
        if total_bytes > _MAX_TOTAL_BYTES:
            raise ValueError(f"combined patch content exceeds {_MAX_TOTAL_BYTES} bytes")

        target = _resolve_target(root, relative)
        if audit is not None and target.resolve(strict=False) == audit.path.resolve(strict=False):
            raise ValueError("patch proposal cannot modify its own audit log")
        if target.exists():
            if not target.is_file():
                raise ValueError(f"patch target is not a regular file: {normalized}")
            current = target.read_text(encoding="utf-8")
            if change.expected_sha256 is None:
                raise ValueError(f"file already exists: {normalized}")
            if not isinstance(change.expected_sha256, str) or not _SHA256.fullmatch(change.expected_sha256):
                raise ValueError(f"expected_sha256 must be a lowercase SHA-256 digest: {normalized}")
            if sha256_text(current) != change.expected_sha256:
                raise ValueError(f"stale patch; current file hash differs: {normalized}")
            previous = current
            mode = stat.S_IMODE(target.stat().st_mode)
        else:
            if change.expected_sha256 is not None:
                raise ValueError(f"expected existing file is missing: {normalized}")
            previous = None
            mode = 0o600
        prepared.append((target, change.content, previous, mode))

    if audit is not None:
        verification = audit.verify()
        if not verification.valid:
            raise ValueError(f"patch audit log failed verification: {verification.error}")
        audit.record(
            "patch_apply_started",
            proposal_id=proposal.proposal_id,
            project_id=proposal.project_id,
            task_id=proposal.task_id,
            files=len(prepared),
            paths=[target.relative_to(root).as_posix() for target, _, _, _ in prepared],
        )
    written: list[tuple[Path, str | None, int]] = []
    try:
        for target, new_content, previous, mode in prepared:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.parent.is_symlink():
                raise ValueError(f"symlinked parent directory is not allowed: {target}")
            _atomic_write(target, new_content, mode)
            written.append((target, previous, mode))
        if audit is not None:
            audit.record(
                "patch_apply_succeeded",
                proposal_id=proposal.proposal_id,
                project_id=proposal.project_id,
                task_id=proposal.task_id,
                changed_paths=[target.relative_to(root).as_posix() for target, _, _, _ in prepared],
            )
            verification = audit.verify()
            if not verification.valid:
                raise RuntimeError(f"patch audit log failed verification: {verification.error}")
    except Exception as exc:
        for target, previous, mode in reversed(written):
            try:
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    _atomic_write(target, previous, mode)
            except OSError:
                # Preserve the original exception; caller must inspect workspace.
                pass
        if audit is not None:
            try:
                audit.record(
                    "patch_apply_failed",
                    proposal_id=proposal.proposal_id,
                    project_id=proposal.project_id,
                    task_id=proposal.task_id,
                    error_type=type(exc).__name__,
                )
            except Exception:
                pass
        raise

    created = tuple(
        path.relative_to(root).as_posix()
        for path, _, previous, _ in prepared
        if previous is None
    )
    changed = tuple(path.relative_to(root).as_posix() for path, _, _, _ in prepared)
    return PatchResult(proposal.proposal_id, changed, created)
