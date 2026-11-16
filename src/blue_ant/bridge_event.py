"""Local, one-shot event adapter for the read-only ChatGPT bridge.

This adapter consumes an explicitly supplied JSON event file. It has no
network listener, polling loop, credentials, shell execution, or write access
to the target repository. Event IDs are claimed once (at-most-once delivery).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from .json_utils import strict_json_loads

from .bridge import load_bridge_command
from .bridge_runner import run_bridge_command

_EVENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_EVENT_KEYS = {"schema_version", "event_id", "event_type", "command_id"}
_MAX_EVENT_BYTES = 16 * 1024


def _load_event(path: str | Path) -> tuple[dict[str, Any], str]:
    event_path = Path(path)
    if event_path.is_symlink() or not event_path.is_file():
        raise ValueError("event path must be a regular, non-symlink file")
    raw = event_path.read_bytes()
    if not raw or len(raw) > _MAX_EVENT_BYTES:
        raise ValueError("event file must be between 1 byte and 16 KiB")
    try:
        event = strict_json_loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("event file must contain valid UTF-8 JSON") from exc
    if not isinstance(event, dict) or set(event) != _EVENT_KEYS:
        raise ValueError("event must contain exactly the four supported fields")
    if type(event["schema_version"]) is not int or event["schema_version"] != 1:
        raise ValueError("event schema_version must be integer 1")
    if event["event_type"] != "bridge.command":
        raise ValueError("unsupported event_type")
    if not isinstance(event["event_id"], str) or not _EVENT_ID.fullmatch(event["event_id"]):
        raise ValueError("event_id must be 1-64 safe filename characters")
    if not isinstance(event["command_id"], str) or not _EVENT_ID.fullmatch(event["command_id"]):
        raise ValueError("command_id must be 1-64 safe filename characters")
    return event, hashlib.sha256(raw).hexdigest()


def run_bridge_event(
    event_path: str | Path,
    command_path: str | Path,
    target_path: str | Path,
    output_dir: str | Path,
    state_dir: str | Path,
) -> dict[str, Any]:
    """Process one local event exactly once and persist its final receipt."""
    event, event_hash = _load_event(event_path)

    state = Path(state_dir)
    if state.is_symlink() or not state.is_dir():
        raise ValueError("state_dir must be an existing, non-symlink directory")
    receipt_path = state / f"{event['event_id']}.json"
    initial = {
        "schema_version": 1,
        "event_id": event["event_id"],
        "event_sha256": event_hash,
        "command_id": event["command_id"],
        "status": "processing",
    }

    # Check an existing event claim before validating its referenced command.
    # This makes reuse of an event ID with any changed payload fail explicitly,
    # even when the altered payload also contains an invalid command reference.
    if receipt_path.exists() or receipt_path.is_symlink():
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError("existing event receipt is not a regular file")
        try:
            prior = strict_json_loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("existing event receipt is unreadable; refusing replay") from exc
        if prior.get("event_sha256") != event_hash:
            raise ValueError("event_id was already used for a different event payload")
        return {
            "event_id": event["event_id"],
            "status": prior.get("status", "unknown"),
            "duplicate": True,
        }

    command = load_bridge_command(command_path)
    if event["command_id"] != command["command_id"]:
        raise ValueError("event command_id does not match the validated bridge command")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(receipt_path, flags, 0o600)
    except FileExistsError:
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError("existing event receipt is not a regular file")
        try:
            prior = strict_json_loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("existing event receipt is unreadable; refusing replay") from exc
        if prior.get("event_sha256") != event_hash:
            raise ValueError("event_id was already used for a different event payload")
        return {
            "event_id": event["event_id"],
            "status": prior.get("status", "unknown"),
            "duplicate": True,
        }

    with os.fdopen(fd, "w+", encoding="utf-8") as receipt:
        receipt.write(json.dumps(initial, sort_keys=True) + "\n")
        receipt.flush()
        os.fsync(receipt.fileno())
        try:
            result = run_bridge_command(command_path, target_path, output_dir)
            final = {**initial, "status": "completed", "result": result}
        except Exception as exc:
            final = {
                **initial,
                "status": "failed",
                "error_type": type(exc).__name__,
            }
            receipt.seek(0)
            receipt.truncate()
            receipt.write(json.dumps(final, sort_keys=True) + "\n")
            receipt.flush()
            os.fsync(receipt.fileno())
            raise
        receipt.seek(0)
        receipt.truncate()
        receipt.write(json.dumps(final, sort_keys=True) + "\n")
        receipt.flush()
        os.fsync(receipt.fileno())
    return {
        "event_id": event["event_id"],
        "status": "completed",
        "duplicate": False,
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process one local Blue Ant bridge event (no network or background service)"
    )
    parser.add_argument("--event", required=True, help="Strict event JSON file")
    parser.add_argument("--command", required=True, help="Validated bridge command JSON")
    parser.add_argument("--target-path", required=True, help="Read-only target checkout")
    parser.add_argument("--output-dir", required=True, help="Directory for bridge reports")
    parser.add_argument("--state-dir", required=True, help="Existing directory for event receipts")
    args = parser.parse_args()
    try:
        result = run_bridge_event(
            args.event, args.command, args.target_path, args.output_dir, args.state_dir
        )
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
