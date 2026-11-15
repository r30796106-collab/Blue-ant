"""Project registry and isolated workspace path management.

This module records explicitly registered project roots and allocates separate
workspace directories. It never copies, executes, or modifies project sources.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_PROJECT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


@dataclass(frozen=True, slots=True)
class ProjectSpec:
    project_id: str
    source_root: Path


class ProjectRegistry:
    """In-memory allowlist of projects with bounded, separate workspaces."""

    def __init__(self, workspace_root: str | Path) -> None:
        supplied_root = Path(workspace_root).expanduser()
        if supplied_root.exists() and supplied_root.is_symlink():
            raise ValueError("workspace_root must not be a symlink")
        self.workspace_root = supplied_root.resolve()
        self._projects: dict[str, ProjectSpec] = {}

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
        if self.workspace_root.exists() and self.workspace_root.is_symlink():
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
