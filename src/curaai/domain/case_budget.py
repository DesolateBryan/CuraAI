"""CaseLimits and CaseBudget: per-case caps from ADR-011 (Governance ADR 5).

Model calls doubled from the proposed 6 to 12 (team decision, 2026-10-26): a case with two
follow-ups used all 6 in the MockChart run and lost medication flagging. Other caps are
still the ADR-011 proposals, to be tuned after the first evaluation run. When a cap is hit
the AI stops for that case; the fixed chart pull still runs.
Dollar cost is measured by the Ring 3 CostGuard, which reads max_cost_usd.
"""

from dataclasses import dataclass, replace
from decimal import Decimal

from curaai.domain.errors import BudgetExceeded


@dataclass(frozen=True)
class CaseLimits:
    max_model_calls: int = 12
    max_lookups: int = 5
    max_follow_ups: int = 2
    max_cost_usd: Decimal = Decimal("0.25")

    def __post_init__(self) -> None:
        if min(self.max_model_calls, self.max_lookups, self.max_follow_ups) < 0 or self.max_cost_usd < 0:
            raise ValueError("case limits cannot be negative")


@dataclass(frozen=True)
class CaseBudget:
    limits: CaseLimits = CaseLimits()
    model_calls: int = 0
    lookups: int = 0
    follow_ups: int = 0

    def can_call_model(self) -> bool:
        return self.model_calls < self.limits.max_model_calls

    def can_lookup(self) -> bool:
        return self.lookups < self.limits.max_lookups

    def can_follow_up(self) -> bool:
        return self.follow_ups < self.limits.max_follow_ups

    def record_model_call(self) -> "CaseBudget":
        if not self.can_call_model():
            raise BudgetExceeded("max_model_calls")
        return replace(self, model_calls=self.model_calls + 1)

    def record_lookup(self) -> "CaseBudget":
        if not self.can_lookup():
            raise BudgetExceeded("max_lookups")
        return replace(self, lookups=self.lookups + 1)

    def record_follow_up(self) -> "CaseBudget":
        if not self.can_follow_up():
            raise BudgetExceeded("max_follow_ups")
        return replace(self, follow_ups=self.follow_ups + 1)
