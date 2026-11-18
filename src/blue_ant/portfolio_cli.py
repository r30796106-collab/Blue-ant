"""Resolve approved portfolio project IDs into a bounded GitHub Actions matrix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .json_utils import strict_json_loads
from .portfolio import PortfolioRegistry


def resolve_matrix(project_ids_json: str, registry: PortfolioRegistry) -> dict[str, list[dict[str, str]]]:
    """Resolve only registered IDs; never accept repository/ref coordinates from input."""
    if not isinstance(project_ids_json, str) or len(project_ids_json.encode("utf-8")) > 4096:
        raise ValueError("project_ids input exceeds the 4 KiB limit")
    try:
        project_ids = strict_json_loads(project_ids_json)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("project_ids must be valid JSON") from exc
    if not isinstance(project_ids, list) or not 1 <= len(project_ids) <= 4:
        raise ValueError("project_ids must be a JSON array containing 1 to 4 IDs")
    if any(not isinstance(item, str) for item in project_ids):
        raise ValueError("every project ID must be a string")
    if len(set(project_ids)) != len(project_ids):
        raise ValueError("project_ids must not contain duplicates")
    projects = []
    for project_id in project_ids:
        project = registry.get(project_id)
        projects.append({
            "project_id": project.project_id,
            "repository": project.repository,
            "ref": project.default_branch,
            "audited_baseline_sha": project.audited_baseline_sha,
            "max_workers": registry.max_workers_per_project,
        })
    return {"include": projects}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve registered project IDs for the workforce workflow")
    parser.add_argument("--project-ids", required=True, help="JSON array of registered project IDs")
    parser.add_argument("--registry", default="config/portfolio.json", help="portfolio registry path")
    parser.add_argument("--github-output", help="append validated concurrency limits to a GitHub Actions output file")
    args = parser.parse_args(argv)
    try:
        registry = PortfolioRegistry.load(Path(args.registry))
        print(json.dumps(resolve_matrix(args.project_ids, registry), separators=(",", ":")))
        if args.github_output:
            with Path(args.github_output).open("a", encoding="utf-8") as output:
                output.write(f"max_parallel_projects={registry.max_parallel_projects}\n")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
