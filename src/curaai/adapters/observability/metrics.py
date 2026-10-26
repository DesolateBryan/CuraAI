"""case_metrics: the ADR-008 numbers, computed from the audit log. Pure function.

The audit log is the single source of truth, so the metrics can never disagree
with what auditors see. Reported per 100 cases (ADR-008); alert thresholds are
set later from the evaluation baseline.

    off_ramp_rate        share of cases handed off incomplete (timeout or follow-ups used up)
    failed_guardrails    model answers the core validator rejected
    follow_ups           follow-up questions sent
    timeouts             24-hour follow-up timeouts
    ai_fallbacks         cases where AI was switched off and the fixed pull ran alone
    cost_guard_trips     dollar-cap trips
    model_calls, tokens, cost, latency    from the gateway's events
"""

from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median

from curaai.application.dto.audit import AuditEvent


@dataclass(frozen=True)
class MetricsReport:
    cases: int
    packets_delivered: int
    off_ramp_rate: float
    failed_guardrails_per_100: float
    follow_ups_per_100: float
    timeouts_per_100: float
    ai_fallbacks_per_100: float
    cost_guard_trips: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd_total: float
    cost_usd_per_case: float
    median_model_latency_ms: int


def case_metrics(events: Iterable[AuditEvent]) -> MetricsReport:
    events = list(events)
    by_action: dict[str, list[AuditEvent]] = {}
    for e in events:
        by_action.setdefault(e.action, []).append(e)

    def count(action: str) -> int:
        return len(by_action.get(action, ()))

    cases = count("case_opened")
    packets = by_action.get("review_packet_delivered", [])
    incomplete = sum(1 for e in packets if e.detail.get("status") == "messages_only")
    fallbacks = sum(1 for e in packets if e.detail.get("ai_fallback"))
    calls = by_action.get("model_gateway_call", [])
    cost = sum(float(e.detail.get("cost_usd") or 0) for e in calls)
    per_100 = (100.0 / cases) if cases else 0.0

    return MetricsReport(
        cases=cases,
        packets_delivered=len(packets),
        off_ramp_rate=(incomplete / cases) if cases else 0.0,
        failed_guardrails_per_100=count("model_output_rejected") * per_100,
        follow_ups_per_100=count("follow_up_sent") * per_100,
        timeouts_per_100=count("follow_up_timed_out") * per_100,
        ai_fallbacks_per_100=fallbacks * per_100,
        cost_guard_trips=count("cost_guard_tripped"),
        model_calls=len(calls),
        input_tokens=sum(int(e.detail.get("input_tokens") or 0) for e in calls),
        output_tokens=sum(int(e.detail.get("output_tokens") or 0) for e in calls),
        cost_usd_total=round(cost, 6),
        cost_usd_per_case=round(cost / cases, 6) if cases else 0.0,
        median_model_latency_ms=int(median([int(e.detail.get("latency_ms") or 0) for e in calls])) if calls else 0,
    )
