"""Validated GitHub issue command envelope for the ChatGPT control bridge V1.

The bridge accepts one bounded, read-only audit-and-plan command. It does not
interpret task text as code, invoke a shell, modify target repositories, or
approve patches.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_ALLOWED_ROLES = {"repo_analyst", "test_auditor", "docs_auditor", "safety_auditor"}
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_PROJECT_ID = _COMMAND_ID
_REPOSITORY = re.compile(r"^r30796106-collab/[A-Za-z0-9_.-]{1,100}$")
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_REQUIRED = {
    "schema_version", "command_id", "command", "project_id", "repository",
    "ref", "roles", "max_cycles", "task",
}


def validate_bridge_command(value: Any) -> dict[str, Any]:
    """Validate and return a canonical bridge command, rejecting extra fields."""
    if not isinstance(value, dict) or not _REQUIRED.issubset(value) or set(value) - (_REQUIRED | {"snapshot_sources"}):
        raise ValueError("command must contain required fields and only the optional snapshot_sources field")
    snapshot_sources = value.get("snapshot_sources", False)
    if not isinstance(snapshot_sources, bool):
        raise ValueError("snapshot_sources must be a boolean")
    if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
        raise ValueError("schema_version must be integer 1")
    if value["command"] != "audit_plan":
        raise ValueError("only the audit_plan command is enabled in bridge V1")

    command_id = value["command_id"]
    project_id = value["project_id"]
    repository = value["repository"]
    ref = value["ref"]
    task = value["task"]
    roles = value["roles"]
    cycles = value["max_cycles"]

    if not isinstance(command_id, str) or not _COMMAND_ID.fullmatch(command_id):
        raise ValueError("command_id must be a lowercase slug of at most 48 characters")
    if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
        raise ValueError("project_id must be a lowercase slug of at most 48 characters")
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ValueError("only repositories owned by r30796106-collab are allowed")
    if (not isinstance(ref, str) or not _REF.fullmatch(ref) or ref.startswith("-")
        or ".." in ref.split("/") or "//" in ref or ref.endswith(("/", "."))):
        raise ValueError("invalid target ref")
    if not isinstance(roles, list) or not 1 <= len(roles) <= 4:
        raise ValueError("roles must contain 1–4 approved read-only roles")
    if any(not isinstance(role, str) or role not in _ALLOWED_ROLES for role in roles):
        raise ValueError("roles contains an unsupported specialist")
    if len(set(roles)) != len(roles):
        raise ValueError("duplicate specialist roles are not allowed")
    if not isinstance(cycles, int) or isinstance(cycles, bool) or not 1 <= cycles <= len(roles):
        raise ValueError("max_cycles must be between 1 and the number of selected roles")
    if (not isinstance(task, str) or not task.strip() or len(task) > 1000
        or "\n" in task or "\r" in task):
        raise ValueError("task must contain 1–1000 single-line context characters")

    return {
        "schema_version": 1,
        "command_id": command_id,
        "command": "audit_plan",
        "project_id": project_id,
        "repository": repository,
        "ref": ref,
        "roles": list(roles),
        "max_cycles": cycles,
        "task": task.strip(),
        "snapshot_sources": snapshot_sources,
    }


def load_bridge_command(path: str | Path) -> dict[str, Any]:
    """Load a bounded JSON command file and validate its exact schema."""
    source = Path(path)
    if source.stat().st_size > 16_384:
        raise ValueError("bridge command exceeds the 16 KiB limit")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read bridge command JSON: {exc}") from exc
    return validate_bridge_command(value)


def write_bridge_command(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Validate a command and write canonical JSON to the destination."""
    command = load_bridge_command(source)
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
    return command
