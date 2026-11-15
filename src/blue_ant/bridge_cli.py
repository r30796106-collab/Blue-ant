"""CLI validator for GitHub issue commands submitted to Blue Ant bridge V1."""
from __future__ import annotations

import argparse
import json

from .bridge import write_bridge_command


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Blue Ant ChatGPT bridge command")
    parser.add_argument("--input", required=True, help="Raw command JSON file")
    parser.add_argument("--output", required=True, help="Canonical validated command JSON")
    args = parser.parse_args()
    try:
        command = write_bridge_command(args.input, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps({
        "command_id": command["command_id"],
        "command": command["command"],
        "project_id": command["project_id"],
        "repository": command["repository"],
        "ref": command["ref"],
        "roles": command["roles"],
        "max_cycles": command["max_cycles"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
