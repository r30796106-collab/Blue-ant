"""Prepare narrowly scoped, deterministic documentation repair drafts.

This module never writes to the inspected workspace, executes target code, or
approves/applies a patch. It only returns complete replacement text for a small
allowlist of mechanically verifiable Markdown repairs.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import posixpath
import re
from typing import Any


_MAX_FILE_BYTES = 1_000_000
_MAX_OUTPUT_BYTES = 2_000_000
_README_NAMES = {"readme.md", "readme.rst", "readme"}


def _safe_readme(root: Path, raw_path: Any) -> tuple[Path, str]:
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path or chr(92) in raw_path:
        raise ValueError("task path must be a safe relative README path")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in raw_path.split("/")):
        raise ValueError("task path must be a safe relative README path")
    if relative.name.lower() not in _README_NAMES:
        raise ValueError("automatic preparation is limited to README files")
    target = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlinked README parent is not allowed")
    if target.is_symlink() or not target.is_file():
        raise ValueError("README must be an existing regular file")
    target.resolve(strict=True).relative_to(root)
    if target.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError("README exceeds the preparation size limit")
    return target, relative.as_posix()


def _existing_files(root: Path) -> list[str]:
    ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}
    result: list[str] = []
    for item in root.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        rel = item.relative_to(root)
        if any(part in ignored for part in rel.parts):
            continue
        try:
            item.resolve(strict=True).relative_to(root)
            if item.stat().st_size <= _MAX_FILE_BYTES:
                result.append(rel.as_posix())
        except (OSError, ValueError):
            continue
    return result


def _close_unclosed_fence(content: str) -> str | None:
    lines = content.splitlines()
    opened: tuple[str, int] | None = None
    for line in lines:
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if not match:
            continue
        fence, tail = match.groups()
        if opened is None:
            if fence[0] == "`" and "`" in tail:
                continue
            opened = (fence[0], len(fence))
        elif fence[0] == opened[0] and len(fence) >= opened[1] and not tail.strip():
            opened = None
    if opened is None:
        return None
    closing = opened[0] * opened[1]
    separator = "" if not content or content.endswith(("\n", "\r")) else "\n"
    return content + separator + closing + "\n"


def _fix_case_only_link(root: Path, readme_path: str, content: str, evidence: str) -> str | None:
    prefix = "README contains a relative link to a missing repository file: "
    if not evidence.startswith(prefix):
        return None
    destination = evidence[len(prefix):].strip()
    if not destination or any(ch.isspace() for ch in destination) or destination.startswith(("/", "#")):
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", destination):
        return None
    base = posixpath.dirname(readme_path)
    local = destination.split("#", 1)[0].split("?", 1)[0]
    if not local:
        return None
    intended = posixpath.normpath(posixpath.join(base, local))
    if intended == ".." or intended.startswith("../") or intended.startswith("/"):
        return None
    files = _existing_files(root)
    candidates = [name for name in files if name.casefold() == intended.casefold()]
    if len(candidates) != 1 or candidates[0] == intended:
        return None
    corrected = posixpath.relpath(candidates[0], base or ".")
    suffix = destination[len(local):]
    replacement = corrected + suffix
    link_pattern = re.compile(r"(!?\[[^\]]*\]\()(" + re.escape(destination) + r")(\))")
    matches = list(link_pattern.finditer(content))
    if len(matches) != 1:
        return None
    match = matches[0]
    return content[:match.start(2)] + replacement + content[match.end(2):]


def prepare_task(workspace: str | Path, task: dict[str, Any]) -> dict[str, Any]:
    """Return a prepared full-file draft or a manual-review reason."""
    result = {"task_id": task.get("task_id"), "status": "manual_review", "path": task.get("path", ""), "strategy": None, "content": "", "reason": "No safe deterministic repair rule matched this task."}
    if not isinstance(task, dict):
        result["reason"] = "Task must be a structured object."
        return result
    if task.get("kind") != "audit_finding_review" or task.get("role") != "docs_auditor":
        result["reason"] = "Automatic preparation is limited to non-security documentation audit findings."
        return result
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    try:
        target, relative = _safe_readme(root, task.get("path"))
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        result["reason"] = str(exc)
        return result

    evidence = task.get("evidence")
    if not isinstance(evidence, str):
        result["reason"] = "Finding evidence is missing or invalid."
        return result

    prepared = None
    strategy = None
    if evidence.startswith("README contains an unclosed fenced code block"):
        prepared = _close_unclosed_fence(content)
        strategy = "append_matching_markdown_fence"
    elif evidence.startswith("README contains a relative link to a missing repository file: "):
        prepared = _fix_case_only_link(root, relative, content, evidence)
        strategy = "correct_unique_case_only_relative_link"

    if prepared is None or prepared == content:
        result["reason"] = "No unique, mechanically verifiable repair was found; human preparation is required."
        return result
    if len(prepared.encode("utf-8")) > _MAX_OUTPUT_BYTES:
        result["reason"] = "Prepared replacement exceeds the 2 MB output limit."
        return result
    result.update(status="prepared", strategy=strategy, content=prepared, reason="Deterministic draft only; independently review before approval.")
    return result


def prepare_plan(workspace: str | Path, plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema_version") != 1 or not isinstance(plan.get("tasks"), list):
        raise ValueError("development plan must be a schema v1 object with a tasks array")
    prepared = [prepare_task(workspace, task) for task in plan["tasks"] if isinstance(task, dict)]
    return {"schema_version": 1, "plan_id": plan.get("plan_id"), "prepared_tasks": prepared}
