from __future__ import annotations

import pytest

from blue_ant.json_utils import strict_json_loads


def test_strict_json_loads_accepts_valid_nested_json():
    assert strict_json_loads('{"items": [{"name": "blue-ant"}]}') == {
        "items": [{"name": "blue-ant"}]
    }


@pytest.mark.parametrize(
    "payload",
    [
        '{"name": "first", "name": "second"}',
        '{"outer": {"name": "first", "name": "second"}}',
        '{"items": [{"id": 1, "id": 2}]}',
    ],
)
def test_strict_json_loads_rejects_duplicate_keys_at_any_depth(payload):
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        strict_json_loads(payload)


def test_strict_json_loads_preserves_json_decode_errors():
    with pytest.raises(ValueError):
        strict_json_loads("{not-json")
