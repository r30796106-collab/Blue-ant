"""CLI for deterministic evaluation of ChatGPT bridge V2 results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bridge_controller import decision_to_dict, evaluate_bridge_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a Blue Ant bridge result bundle")
    parser.add_argument("--input", required=True, help="JSON bundle containing command, audit report and plan")
    parser.add_argument("--output", required=True, help="Path for the deterministic controller decision")
    args = parser.parse_args()
    try:
        source = Path(args.input)
        if source.stat().st_size > 2_500_000:
            raise ValueError("result bundle exceeds the 2.5 MB limit")
        bundle = json.loads(source.read_text(encoding="utf-8"))
        decision = decision_to_dict(evaluate_bridge_result(bundle))
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(decision, indent=2) + "\n, encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps({"status": decision["status"], "action": decision["action"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
