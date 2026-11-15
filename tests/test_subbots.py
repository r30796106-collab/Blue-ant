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


def test_rejects_non_directory(tmp_path: Path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    bot = SubBotFactory().create_fleet()[0]
    with pytest.raises(NotADirectoryError):
        bot.run(file_path)
