"""Smoke-test every packaged CLI module's argument parser."""

from __future__ import annotations

import importlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


CLI_MODULES = (
    "blue_ant.approved_task_bundle",
    "blue_ant.audit_loop_cli",
    "blue_ant.bridge_cli",
    "blue_ant.bridge_controller_cli",
    "blue_ant.bridge_event",
    "blue_ant.bridge_runner",
    "blue_ant.code_preparation_cli",
    "blue_ant.controlled_proposal_cli",
    "blue_ant.development_plan_cli",
    "blue_ant.patch_cli",
    "blue_ant.portfolio_cli",
    "blue_ant.project_cli",
    "blue_ant.subbot_report",
    "blue_ant.workforce_cli",
)


@pytest.mark.parametrize("module", CLI_MODULES)
def test_cli_module_help_exits_successfully(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, (
        f"{module} --help failed with exit {result.returncode}: "
        f"{result.stderr[-2000:]}"
    )
    assert "usage:" in result.stdout.lower()


def test_project_scripts_resolve_to_all_smoke_tested_cli_modules() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = project["project"]["scripts"]

    targets = {}
    for script_name, target in scripts.items():
        module_name, separator, attribute = target.partition(":")
        assert separator and module_name and attribute, script_name
        targets[script_name] = (module_name, attribute)
        resolved = getattr(importlib.import_module(module_name), attribute)
        assert callable(resolved), script_name

    assert {module for module, _ in targets.values()} == set(CLI_MODULES)
