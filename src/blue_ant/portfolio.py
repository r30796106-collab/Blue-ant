"""Strict, read-only configuration for Blue Ant's approved project portfolio.

This registry describes repository identity, audited baselines, path scopes and
safety gates. It does not fetch repositories, execute code, grant permissions,
or perform GitHub operations.
"""
from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import json
from pathlib import PurePosixPath
import re
from pathlib import Path
from typing import Any

from .json_utils import strict_json_loads

_SCHEMA_VERSION = 1
_OWNER = "r30796106-collab"
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PROJECT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_PATH_PATTERN = re.compile(r"^[A-Za-z0-9_.*?/-]+$")

_POLICY_KEYS = {
    "require_explicit_patch_approval",
    "require_independent_review",
    "require_ci",
    "allow_deploy",
    "allow_real_money",
    "allow_unrestricted_shell",
    "allow_credential_access",
    "allow_destructive_actions",
    "preserve_existing_ai_configuration",
}


@dataclass(frozen=True, slots=True)
class ProjectPolicy:
    require_explicit_patch_approval: bool
    require_independent_review: bool
    require_ci: bool
    allow_deploy: bool
    allow_real_money: bool
    allow_unrestricted_shell: bool
    allow_credential_access: bool
    allow_destructive_actions: bool
    preserve_existing_ai_configuration: bool


@dataclass(frozen=True, slots=True)
class PortfolioProject:
    project_id: str
    repository: str
    default_branch: str
    audited_baseline_sha: str
    allowed_paths: tuple[str, ...]
    denied_paths: tuple[str, ...]
    policy: ProjectPolicy

    def allows_path(self, path: str) -> bool:
        """Return whether a normalized repository-relative path is in scope.

        Deny patterns always override allow patterns. Absolute paths, traversal,
        backslashes, empty components and malformed paths fail closed.
        """
        if not isinstance(path, str) or not path or "\\" in path:
            return False
        if any(part in {"", ".", ".."} for part in path.split("/")):
            return False
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
            return False
        normalized = candidate.as_posix()
        if normalized.startswith(".git/") or normalized == ".git":
            return False
        if any(fnmatch.fnmatchcase(normalized, pattern) for pattern in self.denied_paths):
            return False
        return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in self.allowed_paths)


class PortfolioRegistry:
    """Load a strict, bounded, owner-allowlisted portfolio description."""

    def __init__(self, projects: tuple[PortfolioProject, ...], *, max_parallel_projects: int,
                 max_workers_per_project: int) -> None:
        if type(max_parallel_projects) is not int or not 1 <= max_parallel_projects <= 4:
            raise ValueError("max_parallel_projects must be between 1 and 4")
        if type(max_workers_per_project) is not int or not 1 <= max_workers_per_project <= 4:
            raise ValueError("max_workers_per_project must be between 1 and 4")
        if not projects or len(projects) > 4:
            raise ValueError("portfolio must contain between 1 and 4 projects")
        ids = [project.project_id for project in projects]
        repositories = [project.repository.casefold() for project in projects]
        if len(set(ids)) != len(ids):
            raise ValueError("portfolio project IDs must be unique")
        if len(set(repositories)) != len(repositories):
            raise ValueError("portfolio repositories must be unique")
        self._projects = {project.project_id: project for project in projects}
        self.max_parallel_projects = max_parallel_projects
        self.max_workers_per_project = max_workers_per_project
        self.max_total_workers = max_parallel_projects * max_workers_per_project

    @classmethod
    def load(cls, path: str | Path) -> "PortfolioRegistry":
        """Load UTF-8 JSON with duplicate-key rejection and strict schemas."""
        registry_path = Path(path)
        if registry_path.is_symlink() or not registry_path.is_file():
            raise ValueError("portfolio registry must be a regular non-symlink file")
        for ancestor in (registry_path.parent, *registry_path.parent.parents):
            if ancestor.is_symlink():
                raise ValueError("portfolio registry parent directories must not be symlinks")
        if registry_path.stat().st_size > 256 * 1024:
            raise ValueError("portfolio registry exceeds the 256 KiB limit")
        try:
            data = strict_json_loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("portfolio registry is not valid UTF-8 JSON") from exc
        if not isinstance(data, dict) or set(data) != {
            "schema_version", "max_parallel_projects", "max_workers_per_project", "projects"
        }:
            raise ValueError("portfolio registry has an invalid top-level schema")
        if type(data["schema_version"]) is not int or data["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("unsupported portfolio schema_version")
        raw_projects = data["projects"]
        if not isinstance(raw_projects, list):
            raise ValueError("portfolio projects must be a list")
        projects = tuple(cls._parse_project(item) for item in raw_projects)
        return cls(
            projects,
            max_parallel_projects=data["max_parallel_projects"],
            max_workers_per_project=data["max_workers_per_project"],
        )

    @staticmethod
    def _parse_project(item: Any) -> PortfolioProject:
        required = {
            "project_id", "repository", "default_branch", "audited_baseline_sha",
            "allowed_paths", "denied_paths", "policy",
        }
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError("each portfolio entry must use the exact project schema")
        project_id = item["project_id"]
        repository = item["repository"]
        branch = item["default_branch"]
        baseline = item["audited_baseline_sha"]
        if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
            raise ValueError("invalid portfolio project_id")
        if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
            raise ValueError(f"invalid repository coordinate for {project_id}")
        owner, _ = repository.split("/", 1)
        if owner.casefold() != _OWNER.casefold():
            raise ValueError(f"repository is outside the approved owner allowlist: {project_id}")
        if not isinstance(branch, str) or not _BRANCH.fullmatch(branch) or ".." in branch or branch.endswith("/"):
            raise ValueError(f"invalid default_branch for {project_id}")
        if not isinstance(baseline, str) or not _SHA.fullmatch(baseline):
            raise ValueError(f"invalid audited_baseline_sha for {project_id}")
        parsed_patterns: dict[str, tuple[str, ...]] = {}
        for key in ("allowed_paths", "denied_paths"):
            value = item[key]
            if not isinstance(value, list) or not value:
                raise ValueError(f"{key} must be a non-empty list for {project_id}")
            if any(not isinstance(pattern, str) or not _PATH_PATTERN.fullmatch(pattern)
                   or pattern.startswith("/") or ".." in pattern.split("/") for pattern in value):
                raise ValueError(f"invalid {key} pattern for {project_id}")
            if len(set(value)) != len(value):
                raise ValueError(f"duplicate {key} pattern for {project_id}")
            parsed_patterns[key] = tuple(value)
        raw_policy = item["policy"]
        if not isinstance(raw_policy, dict) or set(raw_policy) != _POLICY_KEYS:
            raise ValueError(f"policy has an invalid schema for {project_id}")
        if any(type(value) is not bool for value in raw_policy.values()):
            raise ValueError(f"policy values must be booleans for {project_id}")
        mandatory_false = (
            "allow_deploy", "allow_real_money", "allow_unrestricted_shell",
            "allow_credential_access", "allow_destructive_actions",
        )
        if any(raw_policy[key] for key in mandatory_false):
            raise ValueError(f"portfolio policy attempts to enable a prohibited action: {project_id}")
        mandatory_true = ("require_explicit_patch_approval", "require_independent_review", "require_ci")
        if any(not raw_policy[key] for key in mandatory_true):
            raise ValueError(f"portfolio policy weakens a required gate: {project_id}")
        policy = ProjectPolicy(**raw_policy)
        return PortfolioProject(
            project_id=project_id,
            repository=repository,
            default_branch=branch,
            audited_baseline_sha=baseline,
            allowed_paths=parsed_patterns["allowed_paths"],
            denied_paths=parsed_patterns["denied_paths"],
            policy=policy,
        )

    def get(self, project_id: str) -> PortfolioProject:
        try:
            return self._projects[project_id]
        except KeyError as exc:
            raise KeyError(f"portfolio project is not registered: {project_id}") from exc

    def list_projects(self) -> tuple[PortfolioProject, ...]:
        return tuple(self._projects[key] for key in sorted(self._projects))
