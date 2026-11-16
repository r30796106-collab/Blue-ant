"""Bounded, deterministic repository sub-bots.

Workers inspect repository text only. They never execute project code, invoke a
shell, access credentials, or modify the inspected repository.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import posixpath
import re
from typing import Iterable


class SubBotRole(StrEnum):
    REPO_ANALYST = "repo_analyst"
    TEST_AUDITOR = "test_auditor"
    DOCS_AUDITOR = "docs_auditor"
    SAFETY_AUDITOR = "safety_auditor"


@dataclass(frozen=True, slots=True)
class Finding:
    bot_id: str
    role: str
    severity: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class SubBot:
    bot_id: str
    role: SubBotRole

    @staticmethod
    def index_files(root: str | Path) -> tuple[tuple[str, str], ...]:
        """Read a repository snapshot once for reuse by fixed read-only specialists."""
        repo = Path(root).resolve()
        if not repo.is_dir():
            raise NotADirectoryError(str(repo))
        return tuple(_iter_text_files(repo))

    def run(
        self,
        root: str | Path,
        *,
        indexed_files: tuple[tuple[str, str], ...] | None = None,
    ) -> list[Finding]:
        repo = Path(root).resolve()
        if not repo.is_dir():
            raise NotADirectoryError(str(repo))
        files = list(indexed_files) if indexed_files is not None else list(_iter_text_files(repo))
        if self.role == SubBotRole.REPO_ANALYST:
            return _inventory(self.bot_id, files)
        if self.role == SubBotRole.TEST_AUDITOR:
            return _test_audit(self.bot_id, files)
        if self.role == SubBotRole.DOCS_AUDITOR:
            return _docs_audit(self.bot_id, files)
        if self.role == SubBotRole.SAFETY_AUDITOR:
            return _safety_audit(self.bot_id, files)
        raise ValueError(f"unsupported sub-bot role: {self.role}")


class SubBotFactory:
    """Create a small, bounded fleet from approved built-in role templates."""

    def __init__(self, max_bots: int = 4) -> None:
        if max_bots < 1 or max_bots > 16:
            raise ValueError("max_bots must be between 1 and 16")
        self.max_bots = max_bots

    def create_fleet(self, roles: Iterable[SubBotRole] | None = None) -> tuple[SubBot, ...]:
        selected = tuple(SubBotRole) if roles is None else tuple(roles)
        if not selected:
            raise ValueError("at least one sub-bot role is required")
        if len(selected) > self.max_bots:
            raise ValueError("requested fleet exceeds configured max_bots")
        if len(set(selected)) != len(selected):
            raise ValueError("duplicate sub-bot roles are not allowed")
        if any(not isinstance(role, SubBotRole) for role in selected):
            raise ValueError("roles must use approved SubBotRole templates")
        return tuple(SubBot(bot_id=f"blue-ant-{role.value}", role=role) for role in selected)


def run_fleet(
    root: str | Path,
    bots: Iterable[SubBot],
    *,
    max_workers: int = 4,
) -> list[Finding]:
    """Run specialist workers concurrently with a hard bound and stable output."""
    fleet = tuple(bots)
    if not fleet:
        raise ValueError("at least one sub-bot is required")
    if len(fleet) > 16:
        raise ValueError("fleet exceeds hard maximum of 16 sub-bots")
    if not 1 <= max_workers <= 16:
        raise ValueError("max_workers must be between 1 and 16")
    if any(not isinstance(bot, SubBot) for bot in fleet):
        raise ValueError("fleet must contain approved SubBot instances")
    findings: list[Finding] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(fleet)), thread_name_prefix="blue-ant-subbot") as pool:
        futures = [pool.submit(bot.run, root) for bot in fleet]
        for future in futures:
            findings.extend(future.result())
    return sorted(findings, key=lambda item: (item.path, item.bot_id, item.message))


def _iter_text_files(root: Path):
    """Walk only relevant source directories; prune generated trees before descent."""
    ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}
    repo = root.resolve()
    for current_text, dir_names, file_names in os.walk(repo, topdown=True, followlinks=False):
        current = Path(current_text)
        dir_names[:] = [
            name for name in sorted(dir_names)
            if name not in ignored and not (current / name).is_symlink()
        ]
        for name in sorted(file_names):
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(repo)
                if resolved.stat().st_size > 1_000_000:
                    continue
                content = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeError, ValueError):
                continue
            yield path.relative_to(repo).as_posix(), content


def _inventory(bot_id: str, files: list[tuple[str, str]]) -> list[Finding]:
    suffixes: dict[str, int] = {}
    for name, _ in files:
        suffix = Path(name).suffix.lower() or "[no extension]"
        suffixes[suffix] = suffixes.get(suffix, 0) + 1
    summary = ", ".join(f"{key}: {suffixes[key]}" for key in sorted(suffixes))
    return [Finding(bot_id, SubBotRole.REPO_ANALYST.value, "info", ".", f"Indexed {len(files)} text files ({summary}).")]


def _test_audit(bot_id: str, files: list[tuple[str, str]]) -> list[Finding]:
    names = [name for name, _ in files]
    tests = [name for name in names if name.startswith(("tests/", "test/")) or Path(name).name.startswith("test_")]
    workflows = [(name, content) for name, content in files if name.startswith(".github/workflows/")]
    findings = []
    if not tests:
        findings.append(Finding(bot_id, SubBotRole.TEST_AUDITOR.value, "warning", ".", "No conventional test files found."))
    if not workflows:
        findings.append(Finding(bot_id, SubBotRole.TEST_AUDITOR.value, "warning", ".", "No GitHub Actions workflow files found."))
    elif tests:
        test_command = re.compile(r"\b(pytest|unittest|tox|nox)\b|\b(cargo\s+test|go\s+test|npm\s+test|dotnet\s+test)\b", re.IGNORECASE)
        if not any(test_command.search(content) for _, content in workflows):
            findings.append(Finding(
                bot_id, SubBotRole.TEST_AUDITOR.value, "warning", workflows[0][0],
                "Test files exist, but no recognized test command was found in the repository's GitHub Actions workflows."
            ))
    findings.append(Finding(bot_id, SubBotRole.TEST_AUDITOR.value, "info", ".", f"Found {len(tests)} test files and {len(workflows)} workflow files; tests were not executed."))
    return findings


def _docs_audit(bot_id: str, files: list[tuple[str, str]]) -> list[Finding]:
    readmes = [
        (name, content) for name, content in files
        if Path(name).name.lower() in {"readme.md", "readme.rst", "readme"}
    ]
    if not readmes:
        return [Finding(bot_id, SubBotRole.DOCS_AUDITOR.value, "warning", ".", "No README file found.")]

    names = {name for name, _ in files}
    findings: list[Finding] = []
    for readme_path, content in readmes:
        lines = content.splitlines()
        fence_open = False
        for line_no, line in enumerate(lines, 1):
            if line.lstrip().startswith("```"):
                fence_open = not fence_open
        if fence_open:
            findings.append(Finding(
                bot_id, SubBotRole.DOCS_AUDITOR.value, "warning", readme_path,
                "README contains an unclosed fenced code block."
            ))

        link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
        for match in link_pattern.finditer(content):
            destination = match.group(1).strip().split()[0].strip("<>")
            if (not destination or destination.startswith(("#", "/", "//"))
                or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", destination)):
                continue
            local_target = destination.split("#", 1)[0].split("?", 1)[0]
            if not local_target:
                continue
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(readme_path), local_target))
            if resolved.startswith("../") or resolved not in names:
                findings.append(Finding(
                    bot_id, SubBotRole.DOCS_AUDITOR.value, "warning", readme_path,
                    f"README contains a relative link to a missing repository file: {destination[:160]}"
                ))
                if len(findings) >= 20:
                    break
    if not findings:
        findings.append(Finding(
            bot_id, SubBotRole.DOCS_AUDITOR.value, "info",
            readmes[0][0], "README is present; no unclosed code fences or broken relative links were detected."
        ))
    return findings


_SENSITIVE_PATTERNS = (
    (re.compile(r"\b(eval|exec)\s*\("), "Dynamic code execution pattern found."),
    (re.compile(r"subprocess\.(run|Popen|call)\s*\("), "Subprocess invocation pattern found; review its inputs and controls."),
    (re.compile(r"\bos\.system\s*\("), "Shell invocation pattern found; review its necessity and inputs."),
)


def _safety_audit(bot_id: str, files: list[tuple[str, str]]) -> list[Finding]:
    findings = []
    for name, content in files:
        for line_no, line in enumerate(content.splitlines(), 1):
            for pattern, message in _SENSITIVE_PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(bot_id, SubBotRole.SAFETY_AUDITOR.value, "review", name, f"Line {line_no}: {message}"))
    if not findings:
        findings.append(Finding(bot_id, SubBotRole.SAFETY_AUDITOR.value, "info", ".", "No configured high-risk code patterns detected; this is not a security certification."))
    return findings
