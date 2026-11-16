"""Smoke-test every packaged CLI module's argument parser."""

from __future__ import annotations

import subprocess
import sys

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
