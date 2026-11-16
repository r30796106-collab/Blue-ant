"""Deterministic result-driven controller policy for ChatGPT bridge V2.

This module evaluates structured V1 audit/plan results and emits only a bounded
next-step decision. It never calls an LLM, executes commands, edits files,
approves patches, or performs GitHub operations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .bridge import validate_bridge_command

_ACTIONABLE_KINDS = {
    "audit_finding_review",
    "security_human_review",
    "worker_failure_review",
    "target_test_failure_review",
}


@dataclass(frozen=True, slots=True)
class ControllerDecision:
    status: str
    action: str
    reason: str
    completed_roles: tuple[str, ...]
    next_role: str | None = None
    next_command: dict[str, Any] | None = None


def evaluate_bridge_result(bundle: Any) -> ControllerDecision:
    """Validate a command/result bundle and deterministically choose one next step.

    The next command, when emitted, is a read-only audit of exactly one role
    from the original owner-approved role list. Human-review findings always
    stop automatic continuation.
    """
    if not isinstance(bundle, dict) or set(bundle) != {
        "schema_version", "command", "audit_report", "plan"
    }:
        raise ValueError("bundle must contain exactly schema_version, command, audit_report, plan")
    if bundle["schema_version"] != 1 or isinstance(bundle["schema_version"], bool):
        raise ValueError("bundle schema_version must be integer 1")
    command = validate_bridge_command(bundle["command"])
    audit = bundle["audit_report"]
    plan = bundle["plan"]
    if (not isinstance(audit, dict)
        or isinstance(audit.get("schema_version"), bool)
        or audit.get("schema_version") != 1):
        raise ValueError("audit_report must be a schema_version 1 object")
    if audit.get("mode") not in {"bounded_sequential_read_only_audit_loop", "bounded_parallel_read_only_audit"}:
        raise ValueError("unsupported audit report mode")
    if audit.get("project_id") != command["project_id"]:
        raise ValueError("audit project does not match command")
    if (not isinstance(plan, dict)
        or isinstance(plan.get("schema_version"), bool)
        or plan.get("schema_version") != 1):
        raise ValueError("plan must be a schema_version 1 object")
    if plan.get("project_id") != command["project_id"]:
        raise ValueError("plan project does not match command")
    if plan.get("target_repository") != command["repository"] or plan.get("target_ref") != command["ref"]:
        raise ValueError("plan target does not match command")
    if plan.get("apply_approved") is not False or plan.get("patch_proposal") is not None:
        raise ValueError("controller accepts review-only plans; approval and patch content are forbidden")

    cycles = audit.get("cycles")
    if not isinstance(cycles, list) or len(cycles) > command["max_cycles"]:
        raise ValueError("audit cycles exceed the command's bound")
    completed: list[str] = []
    for cycle in cycles:
        if not isinstance(cycle, dict):
            raise ValueError("audit cycle must be an object")
        role, status = cycle.get("role"), cycle.get("status")
        if role not in command["roles"] or role in completed:
            raise ValueError("audit cycle contains an unrequested or duplicate role")
        if status not in {"success", "failed"}:
            raise ValueError("audit cycle has an invalid status")
        completed.append(role)
        if status == "failed":
            return ControllerDecision(
                "stopped", "human_review", "A specialist failed; inspect its report before retrying.",
                tuple(completed),
            )

    # Independently inspect the audit evidence instead of trusting that the
    # derived plan faithfully preserved every finding. A malformed or omitted
    # plan task must never downgrade an actionable audit finding to "continue".
    for cycle in cycles:
        findings = cycle.get("findings")
        if not isinstance(findings, list):
            raise ValueError("audit cycle findings must be an array")
        for finding in findings:
            if not isinstance(finding, dict):
                raise ValueError("each audit finding must be an object")
            severity = finding.get("severity")
            if severity not in {"info", "warning", "review", "error"}:
                raise ValueError("audit finding has an invalid severity")
            if severity != "info" or cycle["role"] == "safety_auditor":
                return ControllerDecision(
                    "stopped", "human_review",
                    "The audit report contains a finding that requires human verification.",
                    tuple(completed),
                )

    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("plan tasks must be an array")
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("kind"), str):
            raise ValueError("each plan task must contain a kind")
        if task["kind"] in _ACTIONABLE_KINDS:
            return ControllerDecision(
                "stopped", "human_review",
                "The plan contains a finding or test failure that requires human verification.",
                tuple(completed),
            )

    if len(completed) < len(command["roles"]):
        if len(completed) >= command["max_cycles"]:
            return ControllerDecision(
                "stopped", "cycle_limit",
                "The command's maximum cycle count was reached; a new owner-approved command is required.",
                tuple(completed),
            )
        next_role = next(role for role in command["roles"] if role not in completed)
        suffix = f"-next-{len(completed) + 1}"
        next_id = command["command_id"][: 48 - len(suffix)] + suffix
        next_command = {
            "schema_version": 1,
            "command_id": next_id,
            "command": "audit_plan",
            "project_id": command["project_id"],
            "repository": command["repository"],
            "ref": command["ref"],
            "roles": [next_role],
            "max_cycles": 1,
            "task": command["task"],
            "snapshot_sources": command["snapshot_sources"],
        }
        return ControllerDecision(
            "continue", "next_instruction",
            "No actionable findings were produced; continue with the next pre-authorized read-only role.",
            tuple(completed), next_role, next_command,
        )

    return ControllerDecision(
        "completed", "stop",
        "All pre-authorized roles completed without actionable findings.",
        tuple(completed),
    )


def decision_to_dict(decision: ControllerDecision) -> dict[str, Any]:
    result = asdict(decision)
    result["completed_roles"] = list(decision.completed_roles)
    return result
