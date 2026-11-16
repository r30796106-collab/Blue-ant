from pathlib import Path

import pytest

from blue_ant.subbots import SubBot, SubBotFactory, SubBotRole, run_fleet


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
    (tmp_path / "unsafe.py").write_text("ev" + "al('1 + 1')\n", encoding="utf-8")
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
    outside.write_text("ev" + "al('outside')\n", encoding="utf-8")
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



def test_index_prunes_ignored_directories_and_does_not_follow_directory_symlinks(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Example\\n", encoding="utf-8")
    for directory in (".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"):
        ignored = tmp_path / directory
        ignored.mkdir()
        (ignored / "hidden.py").write_text("secret = True\\n", encoding="utf-8")

    outside = tmp_path.parent / "blue-ant-outside-tree"
    outside.mkdir()
    (outside / "outside.py").write_text("outside = True\\n", encoding="utf-8")
    (tmp_path / "linked-tree").symlink_to(outside, target_is_directory=True)

    indexed = SubBot.index_files(tmp_path)

    assert [name for name, _ in indexed] == ["README.md"]
    outside.joinpath("outside.py").unlink()
    outside.rmdir()



def test_index_enforces_file_count_limit(tmp_path: Path, monkeypatch):
    import blue_ant.subbots as subbots

    monkeypatch.setattr(subbots, "_MAX_INDEX_FILES", 2)
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    indexed = SubBot.index_files(tmp_path)

    assert [name for name, _ in indexed] == ["a.txt", "b.txt"]


def test_index_enforces_total_byte_limit_without_partial_files(tmp_path: Path, monkeypatch):
    import blue_ant.subbots as subbots

    monkeypatch.setattr(subbots, "_MAX_INDEX_BYTES", 5)
    monkeypatch.setattr(subbots, "_MAX_INDEX_FILE_BYTES", 5)
    (tmp_path / "a.txt").write_text("1234", encoding="utf-8")
    (tmp_path / "b.txt").write_text("5678", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")

    indexed = SubBot.index_files(tmp_path)

    assert indexed == (("a.txt", "1234"), ("c.txt", "x"))


def test_index_skips_single_file_over_per_file_limit(tmp_path: Path, monkeypatch):
    import blue_ant.subbots as subbots

    monkeypatch.setattr(subbots, "_MAX_INDEX_FILE_BYTES", 3)
    (tmp_path / "large.txt").write_text("1234", encoding="utf-8")
    (tmp_path / "small.txt").write_text("12", encoding="utf-8")

    indexed = SubBot.index_files(tmp_path)

    assert indexed == (("small.txt", "12"),)



def test_index_bounds_actual_file_read_when_file_grows_after_stat(tmp_path: Path, monkeypatch):
    import blue_ant.subbots as subbots

    monkeypatch.setattr(subbots, "_MAX_INDEX_FILE_BYTES", 3)
    target = tmp_path / "growing.txt"
    target.write_text("x", encoding="utf-8")
    original_read = subbots.os.read
    requested_sizes = []

    def oversized_read(descriptor, size):
        requested_sizes.append(size)
        return b"data" if len(requested_sizes) == 1 else original_read(descriptor, size)

    monkeypatch.setattr(subbots.os, "read", oversized_read)

    assert SubBot.index_files(tmp_path) == ()
    assert requested_sizes == [4]


def test_index_rejects_symlink_swapped_in_before_open(tmp_path: Path, monkeypatch):
    import os
    import blue_ant.subbots as subbots

    target = tmp_path / "source.txt"
    held = tmp_path / "source.held"
    outside = tmp_path / "outside.txt"
    target.write_text("ordinary", encoding="utf-8")
    outside.write_text("sensitive", encoding="utf-8")
    original_open = os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == target and not swapped:
            swapped = True
            target.rename(held)
            target.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(subbots.os, "open", swap_then_open)

    assert SubBot.index_files(tmp_path) == ()
    assert swapped
    assert held.read_text(encoding="utf-8") == "ordinary"
    assert outside.read_text(encoding="utf-8") == "sensitive"
