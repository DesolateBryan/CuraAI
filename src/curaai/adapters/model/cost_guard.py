"""CostGuard: GatewayClient decorator that enforces the dollar caps from ADR-011.

    * per case:  CaseLimits.max_cost_usd (proposed $0.25)
    * per day:   daily_budget_usd across all cases, reset by the injected clock

The call-count, lookup and follow-up caps are enforced in Ring 2 (CaseBudget);
dollars are measured here because only the gateway knows token usage.
A trip raises ModelUnavailable, which Ring 2 already handles as "AI off for this
case, fixed chart pull continues". Every trip is written to the audit log.

Lives in adapters/model (not observability) because it wraps GatewayClient, and
adapter packages never import each other.

Deferred: tripping on a spike in failed validations. That signal lives in the
audit log (model_output_rejected) and needs a threshold from the first evaluation run.
"""

import threading
from collections import defaultdict
from datetime import date
from decimal import Decimal

from curaai.adapters.model.gateway_client import GatewayClient, GatewayReply, Prompt
from curaai.application.dto.audit import AuditEvent
from curaai.application.errors import ModelUnavailable
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.domain.case_budget import CaseLimits


class CostGuard:
    def __init__(self, inner: GatewayClient, limits: CaseLimits, daily_budget_usd: Decimal,
                 audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._inner = inner
        self._limits = limits
        self._daily_budget = Decimal(daily_budget_usd)
        self._audit = audit_log
        self._clock = clock
        self._per_case: dict[str, Decimal] = defaultdict(Decimal)
        self._per_day: dict[date, Decimal] = defaultdict(Decimal)
        self._lock = threading.Lock()

    def complete(self, prompt: Prompt) -> GatewayReply:
        case, today = prompt.case_id, self._clock.today()
        with self._lock:
            if self._per_case[case] >= self._limits.max_cost_usd:
                self._trip(prompt, "max_cost_usd", self._per_case[case])
            if self._per_day[today] >= self._daily_budget:
                self._trip(prompt, "daily_budget_usd", self._per_day[today])
        reply = self._inner.complete(prompt)
        with self._lock:
            self._per_case[case] += reply.cost_usd
            self._per_day[today] += reply.cost_usd
        return reply

    def spent(self, case_id: str) -> Decimal:
        with self._lock:
            return self._per_case[case_id]

    def _trip(self, prompt: Prompt, limit: str, spent: Decimal) -> None:
        self._audit.record(AuditEvent(at=self._clock.now(), actor="cost_guard", action="cost_guard_tripped",
                                      subject_id=prompt.case_id,
                                      detail={"limit": limit, "spent_usd": float(spent),
                                              "request_id": prompt.request_id, "port": prompt.port}))
        raise ModelUnavailable(f"cost guard: {limit} reached")
