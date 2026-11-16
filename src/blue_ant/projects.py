"""Project registry and isolated workspace path management.

This module records explicitly registered project roots and allocates separate
workspace directories. It never copies, executes, or modifies project sources.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile


_PROJECT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_REGISTRY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProjectSpec:
    project_id: str
    source_root: Path


class ProjectRegistry:
    """Allowlist of projects with bounded workspaces and optional persistence.

    Persistence is opt-in through registry_path; omitting it preserves the
    original in-memory-only behavior.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        registry_path: str | Path | None = None,
    ) -> None:
        supplied_root = Path(workspace_root).expanduser()
        if supplied_root.is_symlink():
            raise ValueError("workspace_root must not be a symlink")
        self.workspace_root = supplied_root.resolve()
        self.registry_path = (
            Path(registry_path).expanduser() if registry_path is not None else None
        )
        self._projects: dict[str, ProjectSpec] = {}
        if self.registry_path is not None:
            self._load_registry()

    def _load_registry(self) -> None:
        """Load a strict, versioned registry and revalidate every source root."""
        path = self.registry_path
        assert path is not None
        if path.is_symlink():
            raise ValueError("registry_path must not be a symlink")
        if not path.exists():
            return
        if not path.is_file():
            raise ValueError("registry_path must be a regular file")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("project registry cannot be read as valid UTF-8 JSON") from exc

        if not isinstance(data, dict) or set(data) != {"schema_version", "projects"}:
            raise ValueError("project registry has an invalid schema")
        if type(data["schema_version"]) is not int or data["schema_version"] != _REGISTRY_SCHEMA_VERSION:
            raise ValueError("unsupported project registry schema_version")
        projects = data["projects"]
        if not isinstance(projects, list):
            raise ValueError("project registry projects must be a list")

        loaded: dict[str, ProjectSpec] = {}
        for item in projects:
            if not isinstance(item, dict) or set(item) != {"project_id", "source_root"}:
                raise ValueError("project registry entries must contain project_id and source_root")
            project_id = item["project_id"]
            source_value = item["source_root"]
            if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
                raise ValueError("project registry contains an invalid project_id")
            if project_id in loaded:
                raise ValueError(f"project registry contains duplicate ID: {project_id}")
            if not isinstance(source_value, str) or not source_value:
                raise ValueError(f"project registry contains an invalid source_root: {project_id}")
            source = Path(source_value).expanduser()
            if source.is_symlink():
                raise ValueError(f"registered source_root must not be a symlink: {project_id}")
            try:
                resolved_source = source.resolve(strict=True)
            except OSError as exc:
                raise ValueError(f"registered source_root is unavailable: {project_id}") from exc
            if not resolved_source.is_dir():
                raise ValueError(f"registered source_root is not a directory: {project_id}")
            loaded[project_id] = ProjectSpec(project_id, resolved_source)
        self._projects = loaded

    def _save_registry(self) -> None:
        """Atomically replace the registry file without following symlink paths."""
        path = self.registry_path
        if path is None:
            return
        if path.is_symlink():
            raise ValueError("registry_path must not be a symlink")
        for ancestor in (path.parent, *path.parent.parents):
            if ancestor.is_symlink():
                raise ValueError("registry parent directories must not be symlinks")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("registry_path must not be a symlink")
        if path.exists() and not path.is_file():
            raise ValueError("registry_path must be a regular file")

        payload = {
            "schema_version": _REGISTRY_SCHEMA_VERSION,
            "projects": [
                {
                    "project_id": spec.project_id,
                    "source_root": str(spec.source_root),
                }
                for spec in self.list_projects()
            ],
        }
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            os.chmod(temporary_name, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if path.is_symlink():
                raise ValueError("registry_path must not be a symlink")
            os.replace(temporary_name, path)
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

    def register(self, project_id: str, source_root: str | Path) -> ProjectSpec:
        """Register an existing source directory; duplicate IDs are rejected."""
        if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
            raise ValueError("project_id must be a lowercase slug (letters, digits, '_' or '-')")
        if project_id in self._projects:
            raise ValueError(f"project already registered: {project_id}")

        supplied_source = Path(source_root).expanduser()
        if supplied_source.is_symlink():
            raise ValueError("source_root must not be a symlink")
        source = supplied_source.resolve(strict=True)
        if not source.is_dir():
            raise NotADirectoryError(str(source))

        spec = ProjectSpec(project_id=project_id, source_root=source)
        self._projects[project_id] = spec
        try:
            self._save_registry()
        except Exception:
            self._projects.pop(project_id, None)
            raise
        return spec

    def get(self, project_id: str) -> ProjectSpec:
        try:
            return self._projects[project_id]
        except KeyError as exc:
            raise KeyError(f"project is not registered: {project_id}") from exc

    def list_projects(self) -> tuple[ProjectSpec, ...]:
        return tuple(self._projects[key] for key in sorted(self._projects))

    def workspace_for(self, project_id: str, *, create: bool = False) -> Path:
        """Return a project-specific workspace, optionally creating its directory.

        Creation is limited to one direct child of workspace_root. Existing
        symlinks and paths escaping the workspace root are rejected. No source
        files are copied into the workspace.
        """
        self.get(project_id)
        if self.workspace_root.is_symlink():
            raise ValueError("workspace_root must not be a symlink")
        target = self.workspace_root / project_id
        if target.is_symlink():
            raise ValueError("project workspace must not be a symlink")
        resolved = target.resolve(strict=False)
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("project workspace escapes workspace_root") from exc

        if create:
            self.workspace_root.mkdir(parents=True, exist_ok=True)
            target.mkdir(mode=0o700, exist_ok=True)
            if target.is_symlink() or not target.is_dir():
                raise ValueError("project workspace is not a safe directory")
        return target
