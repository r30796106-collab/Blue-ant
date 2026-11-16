"""Build bounded hash-checked patch proposals for reviewed plan tasks.

The builder packages externally supplied replacement text only. It never
generates code, writes to the target workspace, executes commands, or approves
or applies a proposal. A task may explicitly authorize one path (legacy) or a
small, exact allowlist of existing paths (multi-file mode).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .patches import FileChange, PatchProposal, sha256_text


_MAX_CONTENT_BYTES = 2_000_000
_MAX_FILES = 10


def _safe_task_path(raw: Any) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\x00" in raw or chr(92) in raw:
        raise ValueError("task must identify one safe POSIX relative file path")
    path = PurePosixPath(raw)
    if (path.is_absolute() or not path.parts or raw in {".", "./"}
        or any(part in {"", ".", ".."} for part in raw.split("/"))
        or path.parts[0] == ".git" or ":" in path.parts[0]):
        raise ValueError("task path is not an allowed workspace-relative file")
    return path


def _task_paths(task: dict[str, Any]) -> tuple[PurePosixPath, ...]:
    raw_paths = task.get("paths")
    if raw_paths is None:
        raw_paths = [task.get("path")]
    if not isinstance(raw_paths, list) or not 1 <= len(raw_paths) <= _MAX_FILES:
        raise ValueError(f"task paths must contain 1–{_MAX_FILES} explicitly allowed paths")
    paths = tuple(_safe_task_path(raw) for raw in raw_paths)
    normalized = [path.as_posix() for path in paths]
    if len(set(normalized)) != len(normalized):
        raise ValueError("task paths must be unique")
    if "path" in task and task["path"] not in (None, ""):
        legacy = _safe_task_path(task["path"])
        if legacy not in paths:
            raise ValueError("legacy task path must be included in the explicit paths allowlist")
    return paths


def build_patch_proposal(
    workspace: str | Path,
    development_plan: dict[str, Any],
    task_id: str,
    changes: list[dict[str, Any]],
) -> PatchProposal:
    """Package a task's exact existing file allowlist into a hash-checked proposal."""
    if (not isinstance(development_plan, dict)
        or isinstance(development_plan.get("schema_version"), bool)
        or development_plan.get("schema_version") != 1):
        raise ValueError("development plan must use schema_version 1")
    project_id = development_plan.get("project_id")
    plan_id = development_plan.get("plan_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("development plan project_id is required")
    if not isinstance(plan_id, str) or not plan_id.startswith("plan-"):
        raise ValueError("development plan plan_id is invalid")
    if development_plan.get("approval_required") is not True or development_plan.get("apply_approved") is not False:
        raise ValueError("development plan must remain unapproved")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id is required")
    tasks = development_plan.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("development plan tasks must be an array")
    matches = [task for task in tasks if isinstance(task, dict) and task.get("task_id") == task_id]
    if len(matches) != 1:
        raise ValueError("task_id must identify exactly one task in the development plan")
    task = matches[0]
    if task.get("requires_human_review") is not True:
        raise ValueError("task must require human review")
    if task.get("kind") != "audit_finding_review" or task.get("role") == "safety_auditor":
        raise PermissionError("this task type is not eligible for a patch proposal")
    allowed_paths = _task_paths(task)
    if not isinstance(changes, list) or len(changes) != len(allowed_paths):
        raise ValueError("proposal must contain exactly one change for every explicitly allowed task path")
    by_path: dict[str, dict[str, Any]] = {}
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"path", "content"}:
            raise ValueError("each proposed change must contain exactly path and content")
        proposed_path = _safe_task_path(change["path"]).as_posix()
        if proposed_path in by_path:
            raise ValueError("duplicate proposed file path")
        if proposed_path not in {path.as_posix() for path in allowed_paths}:
            raise ValueError("proposed path is outside the reviewed task paths allowlist")
        if not isinstance(change["content"], str):
            raise ValueError("proposed file content must be text")
        by_path[proposed_path] = change
    expected_order = [path.as_posix() for path in allowed_paths]
    if set(by_path) != set(expected_order):
        raise ValueError("proposal is missing one or more explicitly allowed task paths")
    total_bytes = sum(len(by_path[path]["content"].encode("utf-8")) for path in expected_order)
    if total_bytes > _MAX_CONTENT_BYTES:
        raise ValueError("combined proposed content exceeds 2 MB")

    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    file_changes: list[FileChange] = []
    canonical_changes = []
    for relative_name in expected_order:
        relative = _safe_task_path(relative_name)
        target = root.joinpath(*relative.parts)
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ValueError("symlinked parent directories are not allowed")
            if current.exists() and not current.is_dir():
                raise ValueError("task path parent is not a directory")
        if target.is_symlink() or not target.exists() or not target.is_file():
            raise ValueError("every task path must identify an existing regular file")
        try:
            target.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise ValueError("task path escapes the workspace") from exc
        content = by_path[relative_name]["content"]
        expected = sha256_text(target.read_text(encoding="utf-8"))
        file_changes.append(FileChange(path=relative_name, content=content, expected_sha256=expected))
        canonical_changes.append({"path": relative_name, "expected_sha256": expected, "content": content})

    canonical = {
        "plan_id": plan_id,
        "task_id": task_id,
        "project_id": project_id,
        "changes": canonical_changes,
    }
    proposal_id = "proposal-" + hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return PatchProposal(
        proposal_id=proposal_id,
        project_id=project_id,
        task_id=task_id,
        changes=tuple(file_changes),
    )


def proposal_to_dict(proposal: PatchProposal) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "project_id": proposal.project_id,
        "task_id": proposal.task_id,
        "changes": [
            {
                "path": change.path,
                "content": change.content,
                "expected_sha256": change.expected_sha256,
            }
            for change in proposal.changes
        ],
    }
