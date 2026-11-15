"""Fail-closed policy checks for high-impact operations."""
from __future__ import annotations

from dataclasses import dataclass


HIGH_IMPACT_ACTIONS = frozenset({
    "delete", "deploy", "install_package", "external_network_write",
    "real_money_trade", "credential_access", "security_test",
})


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str


class PolicyGateway:
    """Allow ordinary internal work; gate sensitive side effects."""

    def __init__(self, approved_actions: set[str] | None = None) -> None:
        self._approved_actions = set(approved_actions or ())

    def evaluate(self, action: str, *, scope_authorized: bool = False) -> PolicyDecision:
        if action == "real_money_trade":
            return PolicyDecision(False, False, "Real-money trading is prohibited.")
        if action == "security_test" and not scope_authorized:
            return PolicyDecision(False, False, "Security testing requires explicit authorized scope.")
        if action in HIGH_IMPACT_ACTIONS and action not in self._approved_actions:
            return PolicyDecision(False, True, "Explicit human approval is required.")
        return PolicyDecision(True, False, "Allowed by current policy.")

    def approve(self, action: str) -> None:
        if action == "real_money_trade":
            raise ValueError("Real-money trading cannot be approved.")
        self._approved_actions.add(action)
