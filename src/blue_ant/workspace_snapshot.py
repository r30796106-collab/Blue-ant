"""Create bounded, credential-conscious snapshots of registered project sources.

Snapshots are copies for isolated work, not OS sandboxes. The source tree is
never modified. Symlinks and special files are rejected rather than followed.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat


_MAX_FILES = 5_000
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_TOTAL_BYTES = 50 * 1024 * 1024
_EXCLUDED_DIRECTORIES = {
    ".git", ".blue-ant", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", "dist", "build", ".idea", ".vscode",
}
_EXCLUDED_FILES = {
    ".env", ".netrc", ".npmrc", ".pypirc", "credentials.json",
    "secrets.json", "id_rsa", "id_ed25519",
}
_EXCLUDED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    source_root: Path
    workspace: Path
    files_copied: int
    bytes_copied: int
    skipped_directories: tuple[str, ...]
    skipped_sensitive_files: tuple[str, ...]


def _reject_symlink_components(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"workspace path must not contain symlinks: {component}")


def _raise_walk_error(error: OSError) -> None:
    raise error


def _is_sensitive_file(relative: Path) -> bool:
    """Recognize common repository-local credential stores by relative path."""
    parts = tuple(part.lower() for part in relative.parts)
    name = parts[-1] if parts else ""
    if name == ".env.example":
        return False
    credential_paths = {
        (".git-credentials",),
        (".aws", "credentials"),
        (".config", "gcloud", "application_default_credentials.json"),
        (".config", "gcloud", "credentials.db"),
        (".docker", "config.json"),
        (".kube", "config"),
        (".azure", "accesstokens.json"),
        (".azure", "msal_token_cache.json"),
        (".terraform.d", "credentials.tfrc.json"),
    }
    if parts in credential_paths:
        return True
    if len(parts) >= 4 and parts[:3] == (".aws", "sso", "cache"):
        return True
    if len(parts) >= 4 and parts[:3] == (".config", "gcloud", "legacy_credentials"):
        return True
    return (
        name in _EXCLUDED_FILES
        or (name.startswith(".env.") and name != ".env.example")
        or Path(name).suffix in _EXCLUDED_SUFFIXES
    )


def _remove_partial_snapshot(root: Path, files: list[Path], directories: list[Path]) -> None:
    for path in reversed(files):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    for path in reversed(directories):
        try:
            path.rmdir()
        except OSError:
            pass


def create_workspace_snapshot(
    source_root: str | Path,
    workspace: str | Path,
    *,
    max_files: int = _MAX_FILES,
    max_file_bytes: int = _MAX_FILE_BYTES,
    max_total_bytes: int = _MAX_TOTAL_BYTES,
) -> SnapshotResult:
    """Copy a bounded source snapshot without following symlinks or copying secrets.

    The destination must be absent or an empty, non-symlink directory. Common
    VCS, cache, build, virtual-environment, and dependency directories are
    excluded. Common credential files and private-key formats are excluded.
    Every copied file is created with mode 0600. No source metadata or
    executable permission bits are copied.
    """
    if not 1 <= max_files <= _MAX_FILES:
        raise ValueError(f"max_files must be between 1 and {_MAX_FILES}")
    if not 1 <= max_file_bytes <= _MAX_FILE_BYTES:
        raise ValueError(f"max_file_bytes must be between 1 and {_MAX_FILE_BYTES}")
    if not 1 <= max_total_bytes <= _MAX_TOTAL_BYTES:
        raise ValueError(f"max_total_bytes must be between 1 and {_MAX_TOTAL_BYTES}")

    supplied_source = Path(source_root).expanduser()
    if supplied_source.is_symlink():
        raise ValueError("source_root must not be a symlink")
    source = supplied_source.resolve(strict=True)
    if not source.is_dir():
        raise NotADirectoryError(str(source))

    supplied_destination = Path(workspace).expanduser()
    _reject_symlink_components(supplied_destination.parent)
    if supplied_destination.is_symlink():
        raise ValueError("workspace destination must not be a symlink")
    parent = supplied_destination.parent.resolve(strict=True)
    destination = parent / supplied_destination.name
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        raise ValueError("workspace destination must be outside source_root")
    try:
        source.relative_to(destination)
    except ValueError:
        pass
    else:
        raise ValueError("source_root must not be inside workspace destination")

    destination_created = False
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise ValueError("workspace destination must be an empty directory")
    else:
        destination.mkdir(mode=0o700)
        destination_created = True

    copied_files: list[Path] = []
    created_directories: list[Path] = []
    skipped_directories: list[str] = []
    skipped_sensitive: list[str] = []
    files_copied = 0
    bytes_copied = 0
    nofollow = getattr(os, "O_NOFOLLOW", 0)

    try:
        for current_text, dir_names, file_names in os.walk(
            source, topdown=True, followlinks=False, onerror=_raise_walk_error
        ):
            current = Path(current_text)
            kept_dirs: list[str] = []
            for name in sorted(dir_names):
                if name in _EXCLUDED_DIRECTORIES:
                    skipped_directories.append((current / name).relative_to(source).as_posix())
                    continue
                child = current / name
                if child.is_symlink():
                    raise ValueError(f"source contains a symlinked directory: {child.relative_to(source)}")
                if not child.is_dir():
                    raise ValueError(f"source contains a non-directory path: {child.relative_to(source)}")
                kept_dirs.append(name)
            dir_names[:] = kept_dirs

            for name in sorted(file_names):
                source_file = current / name
                relative = source_file.relative_to(source)
                if _is_sensitive_file(relative):
                    skipped_sensitive.append(relative.as_posix())
                    continue
                if source_file.is_symlink():
                    raise ValueError(f"source contains a symlinked file: {relative}")
                info = source_file.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError(f"source contains a non-regular file: {relative}")
                if info.st_size > max_file_bytes:
                    raise ValueError(f"source file exceeds {max_file_bytes} bytes: {relative}")
                if files_copied + 1 > max_files:
                    raise ValueError(f"snapshot exceeds {max_files} files")
                if bytes_copied + info.st_size > max_total_bytes:
                    raise ValueError(f"snapshot exceeds {max_total_bytes} total bytes")

                target = destination.joinpath(*relative.parts)
                target_parent = target.parent
                if not target_parent.exists():
                    missing: list[Path] = []
                    cursor = target_parent
                    while not cursor.exists():
                        missing.append(cursor)
                        cursor = cursor.parent
                    for directory in reversed(missing):
                        directory.mkdir(mode=0o700)
                        created_directories.append(directory)

                source_fd = os.open(source_file, os.O_RDONLY | nofollow)
                target_fd = -1
                try:
                    before = os.fstat(source_fd)
                    if not stat.S_ISREG(before.st_mode):
                        raise ValueError(f"source changed to a non-regular file: {relative}")
                    if before.st_size > max_file_bytes:
                        raise ValueError(f"source file exceeds {max_file_bytes} bytes: {relative}")
                    target_fd = os.open(
                        target,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                        0o600,
                    )
                    copied_files.append(target)
                    copied_for_file = 0
                    while True:
                        chunk = os.read(source_fd, 1024 * 1024)
                        if not chunk:
                            break
                        copied_for_file += len(chunk)
                        if copied_for_file > max_file_bytes:
                            raise ValueError(f"source file grew beyond {max_file_bytes} bytes: {relative}")
                        if bytes_copied + copied_for_file > max_total_bytes:
                            raise ValueError(f"snapshot exceeds {max_total_bytes} total bytes")
                        view = memoryview(chunk)
                        while view:
                            written = os.write(target_fd, view)
                            if written <= 0:
                                raise OSError("short write while creating workspace snapshot")
                            view = view[written:]
                    after = os.fstat(source_fd)
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError(f"source file changed while snapshotting: {relative}")
                    os.fsync(target_fd)
                finally:
                    os.close(source_fd)
                    if target_fd >= 0:
                        os.close(target_fd)

                files_copied += 1
                bytes_copied += copied_for_file

        return SnapshotResult(
            source_root=source,
            workspace=destination,
            files_copied=files_copied,
            bytes_copied=bytes_copied,
            skipped_directories=tuple(skipped_directories),
            skipped_sensitive_files=tuple(skipped_sensitive),
        )
    except Exception:
        _remove_partial_snapshot(destination, copied_files, created_directories)
        if destination_created:
            try:
                destination.rmdir()
            except OSError:
                pass
        raise
