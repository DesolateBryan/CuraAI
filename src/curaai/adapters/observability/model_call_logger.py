"""Logging decorators around each model port (ADR-007 transparency, ADR-008 observability).

Each wrapper implements the SAME port it wraps, so Main can put it around any
model adapter (or a fake) without the use cases noticing. Per call it writes one
"model_port_call" audit event: port, request id, outcome, latency. Errors are
re-raised unchanged so Ring 2 still decides what happens next.

Together with the gateway's "model_gateway_call" events (tokens, cost, raw output)
and Ring 2's "model_output_accepted/rejected" events, any case can be replayed:
what went in, what came out, and who accepted it.
"""

import time
from collections.abc import Callable
from typing import TypeVar

from curaai.application.dto.audit import AuditEvent
from curaai.application.dto.model import (
    ExtractionRequest, FlagMatch, FlagMatchRequest, FollowUpChoice, FollowUpRequest,
    ItemSelection, SelectionRequest, SymptomExtraction,
)
from curaai.application.errors import ModelOutputRejected, ModelUnavailable
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.ports.model_ports import (
    ExtractSymptomsPort, MatchFlagsPort, PickRelevantItemsPort, SelectFollowUpPort,
)

T = TypeVar("T")


class _CallLogger:
    def __init__(self, port: str, audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._port, self._audit, self._clock = port, audit_log, clock

    def call(self, request_id: str, fn: Callable[[], T]) -> T:
        started = time.monotonic()
        try:
            result = fn()
        except ModelOutputRejected as exc:
            self._log(request_id, "unparseable", started, error=exc.reason)
            raise
        except ModelUnavailable as exc:
            self._log(request_id, "unavailable", started, error=str(exc))
            raise
        self._log(request_id, "ok", started)
        return result

    def _log(self, request_id: str, outcome: str, started: float, **detail) -> None:
        case_id = request_id.rsplit(":", 2)[0]
        self._audit.record(AuditEvent(
            at=self._clock.now(), actor=f"model:{self._port}", action="model_port_call", subject_id=case_id,
            detail={"port": self._port, "request_id": request_id, "outcome": outcome,
                    "latency_ms": int((time.monotonic() - started) * 1000), **detail}))


class LoggedExtractSymptoms(ExtractSymptomsPort):
    def __init__(self, inner: ExtractSymptomsPort, audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._inner, self._log = inner, _CallLogger("extract_symptoms", audit_log, clock)

    def extract(self, request: ExtractionRequest) -> SymptomExtraction:
        return self._log.call(request.request_id, lambda: self._inner.extract(request))


class LoggedSelectFollowUp(SelectFollowUpPort):
    def __init__(self, inner: SelectFollowUpPort, audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._inner, self._log = inner, _CallLogger("select_follow_up", audit_log, clock)

    def select(self, request: FollowUpRequest) -> FollowUpChoice:
        return self._log.call(request.request_id, lambda: self._inner.select(request))


class LoggedPickRelevantItems(PickRelevantItemsPort):
    def __init__(self, inner: PickRelevantItemsPort, audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._inner, self._log = inner, _CallLogger("pick_relevant_items", audit_log, clock)

    def pick(self, request: SelectionRequest) -> ItemSelection:
        return self._log.call(request.request_id, lambda: self._inner.pick(request))


class LoggedMatchFlags(MatchFlagsPort):
    def __init__(self, inner: MatchFlagsPort, audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._inner, self._log = inner, _CallLogger("match_flags", audit_log, clock)

    def match(self, request: FlagMatchRequest) -> tuple[FlagMatch, ...]:
        return self._log.call(request.request_id, lambda: self._inner.match(request))
