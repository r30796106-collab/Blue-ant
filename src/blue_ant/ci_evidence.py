"""Strict validation for externally produced GitHub Actions test evidence.

Blue Ant does not execute target-project code. This module verifies that a
reported CI result belongs to the exact repository/ref/commit being reviewed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class CIEvidence:
    repository: str
    ref: str
    commit_sha: str
    workflow: str
    conclusion: str
    required_checks: tuple[str, ...]
    passed_checks: tuple[str, ...]


def validate_ci_evidence(
    evidence: dict[str, object],
    *,
    expected_repository: str,
    expected_ref: str,
    expected_sha: str,
) -> CIEvidence:
    """Fail closed unless successful CI evidence matches the exact target."""
    required = {
        "repository", "ref", "commit_sha", "workflow", "conclusion",
        "required_checks", "passed_checks",
    }
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ValueError("CI evidence has an invalid schema")
    repository = evidence["repository"]
    ref = evidence["ref"]
    commit_sha = evidence["commit_sha"]
    workflow = evidence["workflow"]
    conclusion = evidence["conclusion"]
    required_checks = evidence["required_checks"]
    passed_checks = evidence["passed_checks"]

    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ValueError("CI evidence repository is invalid")
    if repository != expected_repository or ref != expected_ref:
        raise ValueError("CI evidence target does not match the reviewed repository/ref")
    if not isinstance(commit_sha, str) or not _SHA.fullmatch(commit_sha):
        raise ValueError("CI evidence commit SHA is invalid")
    if commit_sha != expected_sha:
        raise ValueError("CI evidence commit does not match the reviewed commit")
    if not isinstance(workflow, str) or not workflow.strip() or len(workflow) > 200:
        raise ValueError("CI evidence workflow name is invalid")
    if conclusion != "success":
        raise ValueError("CI workflow did not succeed")
    for name, values in (("required_checks", required_checks), ("passed_checks", passed_checks)):
        if not isinstance(values, list) or not values or any(
            not isinstance(item, str) or not item.strip() or len(item) > 200
            for item in values
        ):
            raise ValueError(f"CI evidence {name} must be a non-empty list of names")
        if len(set(values)) != len(values):
            raise ValueError(f"CI evidence {name} contains duplicate names")
    missing = set(required_checks) - set(passed_checks)
    if missing:
        raise ValueError("required CI checks are missing: " + ", ".join(sorted(missing)))

    return CIEvidence(
        repository=repository,
        ref=ref,
        commit_sha=commit_sha,
        workflow=workflow,
        conclusion=conclusion,
        required_checks=tuple(required_checks),
        passed_checks=tuple(passed_checks),
    )
