"""Validate and stage up to four independent, human-approved patch tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any


_MAX_TASKS = 4
_MAX_FILES_PER_TASK = 10
_MAX_TOTAL_BYTES = 2_000_000
_SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_REPO = re.compile(r"^r30796106-collab/[A-Za-z0-9_.-]{1,100}$")
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("patch paths must be non-empty POSIX relative paths")
    path = PurePosixPath(value)
    if (path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.parts[0] == ".git" or ":" in path.parts[0]):
        raise ValueError(f"unsafe patch path: {value!r}")
    return path.as_posix()


def validate_bundle(bundle: Any) -> dict[str, Any]:
    """Validate strict schema, approvals, bounded tasks, and disjoint path scopes."""
    required = {"schema_version", "target_repository", "target_ref", "project_id", "apply_approved", "tasks"}
    if not isinstance(bundle, dict) or set(bundle) != required:
        raise ValueError("bundle must contain exactly: " + ", ".join(sorted(required)))
    if bundle["schema_version"] != 1:
        raise ValueError("unsupported bundle schema_version")
    if bundle["apply_approved"] is not True:
        raise PermissionError("bundle requires explicit apply_approved=true")
    if not isinstance(bundle["target_repository"], str) or not _REPO.fullmatch(bundle["target_repository"]):
        raise ValueError("target_repository must be under r30796106-collab")
    ref = bundle["target_ref"]
    if (not isinstance(ref, str) or not _REF.fullmatch(ref) or ref.startswith("-")
        or ".." in ref.split("/") or "//" in ref or ref.endswith(("/", "."))):
        raise ValueError("invalid target_ref")
    project = bundle["project_id"]
    if not isinstance(project, str) or not _SLUG.fullmatch(project):
        raise ValueError("invalid project_id")
    tasks = bundle["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= _MAX_TASKS:
        raise ValueError(f"tasks must contain 1–{_MAX_TASKS} independent tasks")

    seen_ids: set[str] = set()
    all_paths: list[str] = []
    total_bytes = 0
    normalized_tasks = []
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {"task_id", "proposal"}:
            raise ValueError("each task must contain exactly task_id and proposal")
        task_id = task["task_id"]
        if not isinstance(task_id, str) or not _SLUG.fullmatch(task_id) or task_id in seen_ids:
            raise ValueError("task_id values must be unique lowercase slugs")
        seen_ids.add(task_id)
        proposal = task["proposal"]
        if not isinstance(proposal, dict) or set(proposal) != {"proposal_id", "project_id", "task_id", "changes"}:
            raise ValueError("each proposal must use the strict Blue Ant patch proposal schema")
        for field in ("proposal_id", "project_id", "task_id"):
            value = proposal[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError(f"invalid proposal {field}")
        if proposal["project_id"] != project or proposal["task_id"] != task_id:
            raise ValueError("proposal project/task binding mismatch")
        changes = proposal["changes"]
        if not isinstance(changes, list) or not 1 <= len(changes) <= _MAX_FILES_PER_TASK:
            raise ValueError(f"each task must contain 1–{_MAX_FILES_PER_TASK} file changes")
        task_paths: set[str] = set()
        normalized_changes = []
        for change in changes:
            if not isinstance(change, dict) or set(change) != {"path", "content", "expected_sha256"}:
                raise ValueError("each change must contain exactly path, content, expected_sha256")
            path = _safe_path(change["path"])
            content = change["content"]
            digest = change["expected_sha256"]
            if not isinstance(content, str):
                raise ValueError("patch content must be UTF-8 text")
            if digest is not None and (not isinstance(digest, str) or not _SHA.fullmatch(digest)):
                raise ValueError("expected_sha256 must be null or a lowercase SHA-256 digest")
            if path in task_paths:
                raise ValueError("duplicate path within a task")
            task_paths.add(path)
            total_bytes += len(content.encode("utf-8"))
            normalized_changes.append({"path": path, "content": content, "expected_sha256": digest})
        all_paths.extend(task_paths)
        normalized_tasks.append({
            "task_id": task_id,
            "proposal": {
                "proposal_id": proposal["proposal_id"],
                "project_id": project,
                "task_id": task_id,
                "changes": normalized_changes,
            },
        })

    if total_bytes > _MAX_TOTAL_BYTES:
        raise ValueError("combined bundle content exceeds 2 MB")
    sorted_paths = sorted(all_paths)
    for index, path in enumerate(sorted_paths):
        for other in sorted_paths[index + 1:]:
            if other.startswith(path + "/"):
                raise ValueError("overlapping file/directory scopes are not allowed")
    if len(set(all_paths)) != len(all_paths):
        raise ValueError("different tasks must not modify the same file")
    return {
        "schema_version": 1,
        "target_repository": bundle["target_repository"],
        "target_ref": ref,
        "project_id": project,
        "apply_approved": True,
        "tasks": normalized_tasks,
    }


def stage_bundle(bundle: Any, output_dir: str | Path) -> dict[str, Any]:
    """Stage proposals without following symlinks or overwriting prior data.

    The destination is a generated-artifact directory: an existing task
    directory or output file is treated as a conflict, never overwritten.
    """
    validated = validate_bundle(bundle)
    root = Path(output_dir)
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink():
            raise ValueError("staging output directory and parent directories must not be symlinks")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("staging output directory must be a real directory")

    metadata_path = root / "metadata.json"
    if metadata_path.is_symlink() or metadata_path.exists():
        raise FileExistsError(f"staging output already exists: {metadata_path}")

    task_destinations = []
    for task in validated["tasks"]:
        task_dir = root / task["task_id"]
        proposal_path = task_dir / "proposal.json"
        if task_dir.is_symlink():
            raise ValueError(f"staging task directory must not be a symlink: {task_dir}")
        if task_dir.exists() and not task_dir.is_dir():
            raise ValueError(f"staging task path is not a directory: {task_dir}")
        if proposal_path.is_symlink() or proposal_path.exists():
            raise FileExistsError(f"staged proposal already exists: {proposal_path}")
        task_destinations.append((task, task_dir, proposal_path))

    # Preflight every destination before writing the first proposal.
    for task, task_dir, proposal_path in task_destinations:
        task_dir.mkdir(mode=0o700, exist_ok=True)
        with proposal_path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(task["proposal"], indent=2, ensure_ascii=False) + "\n")

    metadata = {key: validated[key] for key in ("schema_version", "target_repository", "target_ref", "project_id", "apply_approved")}
    metadata["tasks"] = [{"task_id": task["task_id"]} for task in validated["tasks"]]
    with metadata_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and stage independent approved Blue Ant tasks")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = stage_bundle(json.loads(Path(args.input).read_text(encoding="utf-8")), args.output_dir)
        print(json.dumps({"status": "validated", "task_count": len(result["tasks"]), "output_dir": str(args.output_dir)}))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError, PermissionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
