"""Command-line management for the persistent Blue Ant project registry."""
from __future__ import annotations

import argparse
import json
import sys

from .projects import ProjectRegistry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register projects and manage their isolated workspace directories"
    )
    parser.add_argument(
        "--registry",
        default=".blue-ant/projects.json",
        help="persistent project registry JSON path (default: .blue-ant/projects.json)",
    )
    parser.add_argument(
        "--workspace-root",
        default=".blue-ant/workspaces",
        help="workspace parent directory (default: .blue-ant/workspaces)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register", help="register an existing project directory")
    register.add_argument("project_id")
    register.add_argument("source_root")

    commands.add_parser("list", help="list registered projects")

    workspace = commands.add_parser("workspace", help="show or create one project workspace")
    workspace.add_argument("project_id")
    workspace.add_argument(
        "--create",
        action="store_true",
        help="create the workspace directory; omitted means read-only lookup",
    )

    args = parser.parse_args(argv)
    try:
        registry = ProjectRegistry(args.workspace_root, registry_path=args.registry)
        if args.command == "register":
            spec = registry.register(args.project_id, args.source_root)
            result = {
                "status": "registered",
                "project_id": spec.project_id,
                "source_root": str(spec.source_root),
            }
        elif args.command == "list":
            result = {
                "projects": [
                    {"project_id": spec.project_id, "source_root": str(spec.source_root)}
                    for spec in registry.list_projects()
                ]
            }
        else:
            path = registry.workspace_for(args.project_id, create=args.create)
            result = {
                "project_id": args.project_id,
                "workspace": str(path),
                "created": bool(args.create),
                "exists": path.is_dir(),
            }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, PermissionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
