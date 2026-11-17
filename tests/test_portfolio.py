import json
from pathlib import Path

import pytest

from blue_ant.portfolio import PortfolioRegistry


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "portfolio.json"


def test_checked_in_portfolio_contains_four_isolated_repositories():
    registry = PortfolioRegistry.load(CONFIG)
    assert [item.project_id for item in registry.list_projects()] == [
        "ai-trading", "blue-ant", "elon", "voicestudio"
    ]
    assert registry.max_parallel_projects == 4
    assert registry.max_workers_per_project == 4
    assert registry.max_total_workers == 16
    assert registry.get("elon").default_branch == "master"
    assert registry.get("ai-trading").repository.endswith("/ai_crypto_bot")


def test_each_project_has_unique_repo_and_baseline_pin():
    registry = PortfolioRegistry.load(CONFIG)
    projects = registry.list_projects()
    assert len({item.repository for item in projects}) == 4
    assert len({item.audited_baseline_sha for item in projects}) == 4
    assert all(len(item.audited_baseline_sha) == 40 for item in projects)


def test_path_scope_allows_only_explicit_paths_and_denials_override():
    registry = PortfolioRegistry.load(CONFIG)
    elon = registry.get("elon")
    assert elon.allows_path("engine/task_engine.py")
    assert not elon.allows_path("engine/autonomous_controller.py")
    assert not elon.allows_path("core/audit.py")
    assert not elon.allows_path("security/policy.py")
    assert not elon.allows_path("providers/gemini_provider.py")


@pytest.mark.parametrize("path", [
    "../outside.py", "/etc/passwd", r"engine\..\secret.py", ".git/config", "",
])
def test_path_scope_fails_closed_for_traversal_absolute_and_git_paths(path):
    registry = PortfolioRegistry.load(CONFIG)
    assert not registry.get("blue-ant").allows_path(path)


def test_voice_and_trading_data_paths_are_outside_code_change_scope():
    registry = PortfolioRegistry.load(CONFIG)
    voice = registry.get("voicestudio")
    trading = registry.get("ai-trading")
    assert voice.allows_path("src/voice_studio/engine.py")
    assert not voice.allows_path("voice_profiles/private.json")
    assert not voice.allows_path("outputs/generated.wav")
    assert trading.allows_path("src/trading_system/data/validator.py")
    assert not trading.allows_path("live_execution/orders.py")
    assert not trading.allows_path("credentials/api.json")


def test_all_projects_require_approval_review_and_ci_and_prohibit_high_impact_actions():
    registry = PortfolioRegistry.load(CONFIG)
    for project in registry.list_projects():
        policy = project.policy
        assert policy.require_explicit_patch_approval
        assert policy.require_independent_review
        assert policy.require_ci
        assert not policy.allow_deploy
        assert not policy.allow_real_money
        assert not policy.allow_unrestricted_shell
        assert not policy.allow_credential_access
        assert not policy.allow_destructive_actions
        assert policy.preserve_existing_ai_configuration


def _write_config(tmp_path: Path, mutate):
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_registry_rejects_unknown_repository_owner(tmp_path):
    path = _write_config(
        tmp_path,
        lambda data: data["projects"][0].update(repository="attacker/other"),
    )
    with pytest.raises(ValueError, match="owner allowlist"):
        PortfolioRegistry.load(path)


def test_registry_rejects_policy_weakening(tmp_path):
    path = _write_config(
        tmp_path,
        lambda data: data["projects"][0]["policy"].update(allow_real_money=True),
    )
    with pytest.raises(ValueError, match="prohibited action"):
        PortfolioRegistry.load(path)


def test_registry_rejects_disabled_required_gates(tmp_path):
    path = _write_config(
        tmp_path,
        lambda data: data["projects"][0]["policy"].update(require_ci=False),
    )
    with pytest.raises(ValueError, match="weakens a required gate"):
        PortfolioRegistry.load(path)


def test_registry_rejects_unknown_or_missing_fields(tmp_path):
    path = _write_config(
        tmp_path,
        lambda data: data["projects"][0].update(extra_permission=True),
    )
    with pytest.raises(ValueError, match="exact project schema"):
        PortfolioRegistry.load(path)


def test_registry_rejects_duplicate_project_ids(tmp_path):
    path = _write_config(
        tmp_path,
        lambda data: data["projects"].__setitem__(3, data["projects"][0].copy()),
    )
    with pytest.raises(ValueError, match="IDs must be unique"):
        PortfolioRegistry.load(path)


def test_registry_rejects_invalid_baseline_sha(tmp_path):
    path = _write_config(
        tmp_path,
        lambda data: data["projects"][0].update(audited_baseline_sha="not-a-sha"),
    )
    with pytest.raises(ValueError, match="baseline_sha"):
        PortfolioRegistry.load(path)


def test_registry_rejects_oversized_and_symlink_config(tmp_path):
    oversized = tmp_path / "large.json"
    oversized.write_text(" " * (256 * 1024 + 1), encoding="utf-8")
    with pytest.raises(ValueError, match="256 KiB"):
        PortfolioRegistry.load(oversized)
    target = tmp_path / "target.json"
    target.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    alias = tmp_path / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(ValueError, match="non-symlink"):
        PortfolioRegistry.load(alias)
