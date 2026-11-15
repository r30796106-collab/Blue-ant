from pathlib import Path

import pytest

from blue_ant.subbots import SubBotFactory, SubBotRole, run_fleet


def test_factory_creates_four_specialist_bots():
    bots = SubBotFactory().create_fleet()
    assert len(bots) == 4
    assert {bot.role for bot in bots} == set(SubBotRole)


def test_factory_enforces_limit_and_unique_roles():
    with pytest.raises(ValueError):
        SubBotFactory(max_bots=2).create_fleet()
    with pytest.raises(ValueError):
        SubBotFactory().create_fleet([SubBotRole.REPO_ANALYST, SubBotRole.REPO_ANALYST])


def test_factory_rejects_empty_or_unapproved_roles():
    with pytest.raises(ValueError):
        SubBotFactory().create_fleet([])
    with pytest.raises(ValueError):
        SubBotFactory().create_fleet(["custom_shell_bot"])


def test_run_fleet_enforces_hard_limit():
    bots = [SubBotFactory().create_fleet([role])[0] for role in SubBotRole]
    with pytest.raises(ValueError):
        run_fleet(".", bots * 5)


def test_read_only_fleet_reports_inventory_tests_docs_and_patterns(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_example.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / "unsafe.py").write_text("eval('1 + 1')\n", encoding="utf-8")
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    findings = run_fleet(tmp_path, SubBotFactory().create_fleet())
    after = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert before == after
    assert any("Indexed" in item.message for item in findings)
    assert any("test files" in item.message for item in findings)
    assert any("README" in item.message for item in findings)
    assert any("Dynamic code execution" in item.message for item in findings)


def test_symlink_is_not_followed(tmp_path: Path):
    outside = tmp_path.parent / "blue-ant-outside-secret.txt"
    outside.write_text("eval('outside')\n", encoding="utf-8")
    (tmp_path / "external.txt").symlink_to(outside)
    findings = run_fleet(tmp_path, SubBotFactory().create_fleet())
    assert not any(item.path == "external.txt" for item in findings)
    outside.unlink()


def test_rejects_non_directory(tmp_path: Path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    bot = SubBotFactory().create_fleet()[0]
    with pytest.raises(NotADirectoryError):
        bot.run(file_path)



def test_docs_auditor_flags_broken_relative_links_and_unclosed_fences(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "# Example\n\n[Missing](docs/not-found.md)\n\n```python\nprint('unfinished')\n",
        encoding="utf-8",
    )
    bot = SubBotFactory().create_fleet([SubBotRole.DOCS_AUDITOR])[0]
    findings = bot.run(tmp_path)
    warnings = [item for item in findings if item.severity == "warning"]
    assert len(warnings) == 2
    assert all(item.path == "README.md" for item in warnings)
    assert any("missing repository file" in item.message for item in warnings)
    assert any("unclosed fenced code block" in item.message for item in warnings)


def test_test_auditor_flags_workflow_without_a_test_command(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_example.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\non: [push]\njobs: {}\n", encoding="utf-8")
    bot = SubBotFactory().create_fleet([SubBotRole.TEST_AUDITOR])[0]
    findings = bot.run(tmp_path)
    assert any(
        item.severity == "warning"
        and item.path == ".github/workflows/ci.yml"
        and "no recognized test command" in item.message
        for item in findings
    )


def test_test_auditor_accepts_recognized_unittest_workflow(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_example.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.write_text("name: CI\njobs:\n  test:\n    steps:\n      - run: python -m unittest discover\n", encoding="utf-8")
    bot = SubBotFactory().create_fleet([SubBotRole.TEST_AUDITOR])[0]
    findings = bot.run(tmp_path)
    assert not any(item.severity == "warning" for item in findings)
