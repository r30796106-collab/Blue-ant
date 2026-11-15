"""Deterministic, human-reviewed development plans from audit and test reports.

This module emits recommendations only. It never generates patch contents,
runs commands, changes files, or approves work automatically.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any


_ALLOWED_ROLES = {"repo_analyst", "test_auditor", "docs_auditor", "safety_auditor"}
_ALLOWED_SEVERITIES = {"info", "warning", "review", "error"}
_MAX_FINDINGS = 100
_MAX_TEXT = 1000


@dataclass(frozen=True, slots=True)
class PlanTask:
    task_id: str
    kind: str
    priority: str
    source: str
    role: str
    path: str
    evidence: str
    recommended_action: str
    requires_human_review: bool = True


@dataclass(frozen=True, slots=True)
class DevelopmentPlan:
    schema_version: int
    plan_id: str
    project_id: str
    target_repository: str | None
    target_ref: str | None
    tasks: tuple[PlanTask, ...]
    approval_required: bool
    apply_approved: bool
    patch_proposal: None
    limitations: tuple[str, ...]


def _text(value: Any, field: str, *, max_length: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"{field} must be a non-empty string of at most {max_length} characters")
    return value.strip()


def _priority(severity: str) -> str:
    return {"error": "high", "review": "high", "warning": "medium", "info": "low"}[severity]


def generate_development_plan(
    audit_report: dict[str, Any],
    test_report: dict[str, Any] | None = None,
    *,
    project_id: str,
    target_repository: str | None = None,
    target_ref: str | None = None,
) -> DevelopmentPlan:
    """Convert bounded structured observations into non-executable review tasks."""
    project = _text(project_id, "project_id", max_length=48)
    if not isinstance(audit_report, dict) or audit_report.get("schema_version") != 1:
        raise ValueError("audit report must be a schema_version 1 object")
    if audit_report.get("mode") not in {"bounded_sequential_read_only_audit_loop", "bounded_parallel_read_only_audit"}:
        raise ValueError("unsupported audit report mode")
    if audit_report.get("project_id") != project:
        raise ValueError("audit report project_id does not match requested project")
    cycles = audit_report.get("cycles")
    if not isinstance(cycles, list) or len(cycles) > 4:
        raise ValueError("audit report cycles must be an array of at most four entries")

    tasks: list[PlanTask] = []
    finding_count = 0
    for cycle in cycles:
        if not isinstance(cycle, dict):
            raise ValueError("each audit cycle must be an object")
        role = cycle.get("role")
        if role not in _ALLOWED_ROLES:
            raise ValueError("audit report contains an unsupported specialist role")
        status = cycle.get("status")
        if status not in {"success", "failed"}:
            raise ValueError("audit cycle status must be success or failed")
        if status == "failed":
            tasks.append(PlanTask(
                task_id=f"review-worker-{len(tasks)+1}",
                kind="worker_failure_review",
                priority="high",
                source="audit",
                role=role,
                path="",
                evidence=_text(cycle.get("error") or "Worker failed without an error message", "cycle.error"),
                recommended_action="Inspect the worker failure and determine whether a safe retry is appropriate.",
            ))
            continue
        findings = cycle.get("findings")
        if not isinstance(findings, list):
            raise ValueError("successful audit cycle findings must be an array")
        finding_count += len(findings)
        if finding_count > _MAX_FINDINGS:
            raise ValueError("audit report exceeds the 100-finding planning limit")
        for finding in findings:
            if not isinstance(finding, dict):
                raise ValueError("each finding must be an object")
            severity = finding.get("severity")
            if severity not in _ALLOWED_SEVERITIES:
                raise ValueError("finding has an unsupported severity")
            path = finding.get("path", "")
            if (not isinstance(path, str) or len(path) > 300 or path.startswith("/")
                or chr(92) in path or ".." in path.split("/")
                or (path != "." and any(part in {"", "."} for part in path.split("/")))):
                raise ValueError("finding path is invalid")
            message = _text(finding.get("message"), "finding.message")
            if severity == "info":
                kind = "informational_observation"
                action = "Record this observation; no code change is recommended automatically."
            elif role == "safety_auditor" or severity == "review":
                kind = "security_human_review"
                action = "Have a human inspect the cited code and its controls; do not auto-generate a patch for this finding."
            else:
                kind = "audit_finding_review"
                action = "Reproduce and verify this finding, then prepare a separate patch proposal for human review if confirmed."
            tasks.append(PlanTask(
                task_id=f"review-finding-{len(tasks)+1}",
                kind=kind,
                priority=_priority(severity),
                source="audit",
                role=role,
                path=path,
                evidence=message,
                recommended_action=action,
            ))

    if (target_repository is None) != (target_ref is None):
        raise ValueError("target_repository and target_ref must be provided together")
    if target_repository is not None:
        target_repository = _text(target_repository, "target_repository", max_length=150)
        target_ref = _text(target_ref, "target_ref", max_length=200)
        if not re.fullmatch(r"r30796106-collab/[A-Za-z0-9_.-]{1,100}", target_repository):
            raise ValueError("target_repository is outside the configured owner scope")
        if (not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", target_ref)
            or target_ref.startswith("-") or ".." in target_ref.split("/")
            or "//" in target_ref or target_ref.endswith(("/", "."))):
            raise ValueError("target_ref is invalid")
    if test_report is not None:
        if not isinstance(test_report, dict):
            raise ValueError("test report must be a JSON object")
        report_repository = _text(test_report.get("target_repository"), "target_repository", max_length=150)
        report_ref = _text(test_report.get("target_ref"), "target_ref", max_length=200)
        if target_repository is not None and (report_repository != target_repository or report_ref != target_ref):
            raise ValueError("test report target does not match requested repository/ref")
        target_repository, target_ref = report_repository, report_ref
        if not re.fullmatch(r"r30796106-collab/[A-Za-z0-9_.-]{1,100}", target_repository):
            raise ValueError("target_repository is outside the configured owner scope")
        if (not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", target_ref)
            or target_ref.startswith("-") or ".." in target_ref.split("/") or "//" in target_ref
            or target_ref.endswith(("/", "."))):
            raise ValueError("target_ref is invalid")
        if test_report.get("test_profile") != "python-unittest":
            raise ValueError("unsupported target test profile")
        status = test_report.get("status")
        if status not in {"success", "failure", "cancelled"}:
            raise ValueError("target test status must be success, failure, or cancelled")
        if status != "success":
            tasks.append(PlanTask(
                task_id=f"review-tests-{len(tasks)+1}",
                kind="target_test_failure_review",
                priority="high",
                source="target_tests",
                role="test_runner",
                path="",
                evidence=f"Target test workflow status: {status}.",
                recommended_action="Inspect the target workflow logs and reproduce the failure in an isolated environment; no automatic dependency installation or patching.",
            ))
        else:
            tasks.append(PlanTask(
                task_id=f"verify-tests-{len(tasks)+1}",
                kind="target_tests_passed",
                priority="low",
                source="target_tests",
                role="test_runner",
                path="",
                evidence="Python compileall and standard-library unittest workflow completed successfully.",
                recommended_action="Record the passing test result for this exact repository ref; rerun after any subsequent code change.",
            ))

    canonical = {
        "project_id": project,
        "audit": audit_report,
        "tests": test_report,
    }
    plan_id = "plan-" + hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return DevelopmentPlan(
        schema_version=1,
        plan_id=plan_id,
        project_id=project,
        target_repository=target_repository,
        target_ref=target_ref,
        tasks=tuple(tasks),
        approval_required=True,
        apply_approved=False,
        patch_proposal=None,
        limitations=(
            "This plan contains review tasks, not patch contents or executable commands.",
            "Audit findings are heuristic and must be independently verified by a human.",
            "A passing target test report applies only to the exact repository ref and test profile recorded.",
            "No task is approved for code modification; a separate hash-checked patch proposal and explicit human approval are required.",
        ),
    )


def plan_to_dict(plan: DevelopmentPlan) -> dict[str, Any]:
    result = asdict(plan)
    result["tasks"] = [asdict(task) for task in plan.tasks]
    result["limitations"] = list(plan.limitations)
    return result
