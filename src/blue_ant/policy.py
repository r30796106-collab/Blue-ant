"""Small deny-by-default policy gateway for task actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Policy:
    allowed_actions: frozenset[str] = frozenset({"local_task", "read_only", "test"})
    approval_required: frozenset[str] = frozenset(
        {"write_files", "network_access", "package_install", "security_scan", "deploy", "delete"}
    )

    def check(self, action: str, approved_actions: frozenset[str] = frozenset()) -> bool:
        """Return True only for explicitly allowed or specifically approved actions."""
        if action in self.allowed_actions:
            return True
        return action in self.approval_required and action in approved_actions
