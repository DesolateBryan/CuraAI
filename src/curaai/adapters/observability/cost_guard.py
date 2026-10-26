"""CostGuard: wraps GatewayClient and enforces CaseLimits.max_cost_usd plus a daily budget (ADR-011).

On a trip it raises ModelUnavailable, which Ring 2 already treats as "AI off,
fixed chart pull continues", and writes the trip to the audit log.
"""

from typing import Protocol

from curaai.domain.case_budget import CaseLimits


class CompletionClient(Protocol):
    """Structural type matching GatewayClient, so this package never imports adapters.model."""

    def complete(self, prompt_version: str, payload: str) -> str: ...


class CostGuard:
    def __init__(self, inner: CompletionClient, limits: CaseLimits, daily_budget_usd: float) -> None:
        self._inner = inner
        self._limits = limits
        self._daily_budget = daily_budget_usd

    def complete(self, prompt_version: str, payload: str) -> str:
        raise NotImplementedError("Ring 3 stub")
