import json
from pathlib import Path

import pytest

from blue_ant.portfolio import PortfolioRegistry
from blue_ant.portfolio_cli import resolve_matrix


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = PortfolioRegistry.load(ROOT / "config" / "portfolio.json")


def test_matrix_resolves_registered_ids_to_pinned_repository_coordinates():
    result = resolve_matrix('["elon","voicestudio"]', REGISTRY)
    assert result == {
        "include": [
            {
                "project_id": "elon",
                "repository": "r30796106-collab/Elon",
                "ref": "master",
                "audited_baseline_sha": REGISTRY.get("elon").audited_baseline_sha,
                "max_workers": REGISTRY.max_workers_per_project,
            },
            {
                "project_id": "voicestudio",
                "repository": "r30796106-collab/VoiceStudio",
                "ref": "main",
                "audited_baseline_sha": REGISTRY.get("voicestudio").audited_baseline_sha,
                "max_workers": REGISTRY.max_workers_per_project,
            },
        ]
    }


@pytest.mark.parametrize("value", [
    "not-json", "{}", "[]", '["elon","elon"]',
    '["elon","missing"]', '["elon",1]', '["blue-ant","elon","ai-trading","voicestudio","extra"]',
])
def test_matrix_rejects_invalid_duplicate_unknown_or_oversized_selections(value):
    with pytest.raises((ValueError, KeyError)):
        resolve_matrix(value, REGISTRY)


def test_matrix_never_accepts_user_supplied_repository_or_branch():
    with pytest.raises((ValueError, KeyError)):
        resolve_matrix(
            json.dumps([{"project_id": "elon", "repository": "attacker/repo", "ref": "main"}]),
            REGISTRY,
        )


def test_matrix_input_has_a_strict_size_limit():
    with pytest.raises(ValueError, match="4 KiB"):
        resolve_matrix(" " * 4097, REGISTRY)


def test_github_output_writes_a_real_line_terminated_value(tmp_path):
    from blue_ant.portfolio_cli import main

    output = tmp_path / "github-output.txt"
    result = main([
        "--project-ids", '["blue-ant"]',
        "--registry", str(ROOT / "config" / "portfolio.json"),
        "--github-output", str(output),
    ])
    assert result == 0
    assert output.read_text(encoding="utf-8") == (
        f"max_parallel_projects={REGISTRY.max_parallel_projects}\n"
    )
