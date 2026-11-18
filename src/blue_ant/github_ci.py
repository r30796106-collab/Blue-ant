"""Read-only GitHub Actions evidence collection for an exact commit.

Uses GitHub's REST API and a read-only token. It never dispatches workflows,
reruns jobs, changes repositories, or approves patches.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class GitHubCIError(RuntimeError):
    """GitHub API evidence could not be collected or did not match the target."""


def _github_get(path: str, token: str) -> dict[str, Any]:
    request = Request(
        "https://api.github.com" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Blue-Ant-CI-Evidence",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read(1_000_001).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GitHubCIError("GitHub Actions evidence request failed") from exc
    if not isinstance(payload, dict):
        raise GitHubCIError("GitHub API returned an invalid response")
    return payload


def collect_github_ci_evidence(
    repository: str,
    ref: str,
    commit_sha: str,
    run_id: int,
    required_checks: tuple[str, ...] | list[str],
    token: str,
    *,
    fetch_json: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, object]:
    """Collect a successful run and its jobs, bound to exact repository/ref/SHA.

    The run ID must be supplied explicitly; this function never guesses which
    workflow run belongs to a review. A caller may inject fetch_json in tests.
    """
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ValueError("repository must be owner/name")
    if not isinstance(ref, str) or not ref.strip() or len(ref) > 255:
        raise ValueError("ref is invalid")
    if not isinstance(commit_sha, str) or not _SHA.fullmatch(commit_sha):
        raise ValueError("commit_sha must be a lowercase 40-character SHA")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run_id must be a positive integer")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("a read-only GitHub token is required")
    if (not isinstance(required_checks, (tuple, list)) or not required_checks
        or any(not isinstance(name, str) or not name.strip() or len(name) > 200
               for name in required_checks)
        or len(set(required_checks)) != len(required_checks)):
        raise ValueError("required_checks must be unique non-empty job names")

    get_json = fetch_json or _github_get
    prefix = "/repos/" + repository
    run = get_json(f"{prefix}/actions/runs/{run_id}", token)
    if run.get("id") != run_id or run.get("head_sha") != commit_sha:
        raise GitHubCIError("workflow run does not match the requested commit")
    if run.get("head_branch") != ref:
        raise GitHubCIError("workflow run does not match the requested ref")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise GitHubCIError("workflow run has not completed successfully")
    workflow = run.get("name")
    if not isinstance(workflow, str) or not workflow.strip() or len(workflow) > 200:
        raise GitHubCIError("workflow run has an invalid name")

    jobs_response = get_json(f"{prefix}/actions/runs/{run_id}/jobs?per_page=100", token)
    jobs = jobs_response.get("jobs")
    if not isinstance(jobs, list):
        raise GitHubCIError("GitHub API returned an invalid jobs list")
    passed = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise GitHubCIError("GitHub API returned a malformed job")
        name = job.get("name")
        if (isinstance(name, str) and name.strip()
            and job.get("status") == "completed"
            and job.get("conclusion") == "success"):
            passed.add(name)
    missing = set(required_checks) - passed
    if missing:
        raise GitHubCIError("required jobs did not pass: " + ", ".join(sorted(missing)))

    return {
        "repository": repository,
        "ref": ref,
        "commit_sha": commit_sha,
        "workflow": workflow,
        "conclusion": "success",
        "required_checks": list(required_checks),
        "passed_checks": sorted(passed),
    }
