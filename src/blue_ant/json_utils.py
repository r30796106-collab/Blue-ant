"""Strict JSON parsing helpers shared by Blue Ant command-line interfaces."""
from __future__ import annotations

import json
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object while rejecting duplicate keys at every nesting level."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def strict_json_loads(payload: str) -> Any:
    """Parse JSON and reject ambiguous duplicate object keys."""
    return json.loads(payload, object_pairs_hook=_unique_object)
