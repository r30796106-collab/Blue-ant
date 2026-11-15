"""Build a hash-checked patch proposal for one reviewed plan task.

This module packages externally supplied file content; it does not generate code,
write to the target workspace, execute commands, or approve/apply a proposal.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .patches import FileChange, PatchProposal, sha256_text


_MAX_CONTENT_BYTES = 2_000_000


def _safe_task_path(raw: Any) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\x00" in raw or chr(92) in raw:
        raise ValueError("task must identify one safe POSIX relative file path")
    path = PurePosixPath(raw)
    if (path.is_absolute() or not path.parts or raw in {".", "./"}
        or any(part in {"", ".", ".."} for part in raw.split("/"))
        or path.parts[0] == ".git" or ":" in path.parts[0]):
        raise ValueError("task path is not an allowed workspace-relative file")
    return path


def build_patch_proposal(
    workspace: str | Path,
    development_plan: dict[str, Any],
    task_id: str,
    changes: list[dict[str, Any]],
) -> PatchProposal:
    """Package one task's exact existing file into a hash-checked proposal."""
    if not isinstance(development_plan, dict) or development_plan.get("schema_version") != 1:
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
    task_path = _safe_task_path(task.get("path"))

    if not isinstance(changes, list) or len(changes) != 1:
        raise ValueError("exactly one file change is allowed for a single-path plan task")
    change = changes[0]
    if not isinstance(change, dict) or set(change) != {"path", "content"}:
        raise ValueError("each proposed change must contain exactly path and content")
    proposed_path = _safe_task_path(change["path"])
    if proposed_path != task_path:
        raise ValueError("proposed path must exactly match the reviewed plan task path")
    content = change["content"]
    if not isinstance(content, str):
        raise ValueError("proposed file content must be text")
    if len(content.encode("utf-8")) > _MAX_CONTENT_BYTES:
        raise ValueError("proposed content exceeds 2 MB")

    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    target = root.joinpath(*task_path.parts)
    current = root
    for part in task_path.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlinked parent directories are not allowed")
        if current.exists() and not current.is_dir():
            raise ValueError("task path parent is not a directory")
    if target.is_symlink() or not target.exists() or not target.is_file():
        raise ValueError("task path must identify an existing regular file")
    try:
        target.resolve(strict=True).relative_to(root)
    except ValueError as exc:
        raise ValueError("task path escapes the workspace") from exc
    current_content = target.read_text(encoding="utf-8")
    expected = sha256_text(current_content)

    canonical = {
        "plan_id": plan_id,
        "task_id": task_id,
        "project_id": project_id,
        "path": task_path.as_posix(),
        "expected_sha256": expected,
        "content": content,
    }
    proposal_id = "proposal-" + hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return PatchProposal(
        proposal_id=proposal_id,
        project_id=project_id,
        task_id=task_id,
        changes=(FileChange(
            path=task_path.as_posix(),
            content=content,
            expected_sha256=expected,
        ),),
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
