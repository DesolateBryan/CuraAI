"""WebController: every decision the HTTP layer makes, with no web framework imported.

The FastAPI routes (routers.py) are humble: each one calls one method here and
returns what it gets back. So request validation, status codes and response
shapes are all tested with plain dicts (ADR-014).

Collaborators are injected as small Protocols, so this package never imports
another adapter package (adapters never import each other, ADR-015). Main wires
the concrete InMemoryBundleSource, InMemoryOutbox, InMemoryReviewSink and the
render/serialize functions from the presenters package.

The raw FHIR bundle stops at bundle_sink.put(); only an InboundMessage DTO
reaches the use case (M2 crossing table: fhir_bundle is not allowed past the adapter).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from curaai.application.dto.messaging import InboundMessage
from curaai.application.errors import ExternalSourceUnavailable, RejectedInboundMessage, UnknownCase
from curaai.application.use_cases import PipelineTrigger, RecordPhysicianDecision
from curaai.domain.errors import HitlRejected

MAX_TEXT_CHARS = 5_000
MAX_ID_CHARS = 128
MAX_REPLY_BODY_CHARS = 4_000


# ---- collaborators -------------------------------------------------------------------
class BundleSink(Protocol):
    def put(self, patient_id: str, bundle: Mapping) -> None: ...


class OutboxEntry(Protocol):
    patient_id: str
    question_id: str
    text: str
    sender_label: str
    display_text: str


class Outbox(Protocol):
    def drain(self, patient_id: str | None = None) -> tuple[OutboxEntry, ...]: ...


class ReviewStore(Protocol):
    views: Mapping[str, Any]


@dataclass(frozen=True)
class WebResponse:
    status: int
    body: Any                              # dict for JSON, str for HTML
    media_type: str = "application/json"


@dataclass
class WebController:
    trigger: PipelineTrigger
    bundles: BundleSink
    outbox: Outbox
    reviews: ReviewStore
    render_html: Callable[[Any, Any], str]          # (review view, gate view) -> page
    to_json: Callable[[Any], dict]
    decisions: RecordPhysicianDecision             # the HITL gate (Governance ADR 3)
    gate_view: Callable[[Any], Any]                # PhysicianReview | None -> GateView
    gate_to_json: Callable[[Any], dict]
    run_log: Callable[[], str]                     # readable run log (Governance ADR 1 and 2)
    instance_id: str = ""            # new on every server start; the bridge uses it to resend after a restart
    _latest_case: dict[str, tuple[str, str]] = field(default_factory=dict)   # patient -> (case_id, outcome)

    # ---- GET /api/health ---------------------------------------------------------------------
    def health(self) -> WebResponse:
        return WebResponse(200, {"status": "ok", "instance": self.instance_id})

    # ---- POST /api/messages ------------------------------------------------------------
    def post_message(self, body: object) -> WebResponse:
        try:
            message, bundle = parse_message_body(body)
        except ValueError as exc:
            return WebResponse(400, {"error": str(exc)})
        if bundle is not None:
            self.bundles.put(message.patient_id, bundle)
        try:
            result = self.trigger.on_patient_message(message)
        except RejectedInboundMessage as exc:
            return WebResponse(422, {"error": str(exc)})
        except ExternalSourceUnavailable as exc:
            return WebResponse(503, {"error": str(exc)})
        self._latest_case[result.patient_id] = (result.case_id, result.outcome.value)
        has_review = result.case_id in self.reviews.views
        return WebResponse(200, {
            "case_id": result.case_id,
            "patient_id": result.patient_id,
            "outcome": result.outcome.value,
            "review_url": f"/reviews/{result.case_id}" if has_review else None,
        })

    # ---- GET /api/outbox ----------------------------------------------------------------
    def get_outbox(self, patient_id: str | None) -> WebResponse:
        items = self.outbox.drain(patient_id)
        return WebResponse(200, {"follow_ups": [
            {"patient_id": f.patient_id, "question_id": f.question_id, "text": f.text,
             "sender_label": f.sender_label, "display_text": f.display_text} for f in items]})

    # ---- GET /api/reviews/{case_id}, /reviews/{case_id}, /api/patients/{id}/review --------------
    def get_review_json(self, case_id: str) -> WebResponse:
        view = self.reviews.views.get(case_id)
        if view is None:
            return WebResponse(404, {"error": "no review for case"})
        return WebResponse(200, {**self.to_json(view),
                                 "physician_review": self.gate_to_json(self.gate_view(self.decisions.gate(case_id)))})

    def get_review_html(self, case_id: str) -> WebResponse:
        view = self.reviews.views.get(case_id)
        if view is None:
            return WebResponse(404, "<p>No CuraAI review for this case yet.</p>", "text/html")
        return WebResponse(200, self.render_html(view, self.gate_view(self.decisions.gate(case_id))), "text/html")

    # ---- POST /api/reviews/{case_id}/decision: the physician's sign-off (HITL gate) ------------
    def post_decision(self, case_id: str, body: object) -> WebResponse:
        if not isinstance(body, Mapping):
            return WebResponse(400, {"error": "body must be a JSON object"})
        decision, physician, reply = body.get("decision"), body.get("physician_id"), body.get("reply_text")
        if not isinstance(decision, str) or not isinstance(physician, str) or len(physician) > MAX_ID_CHARS:
            return WebResponse(400, {"error": "decision and physician_id are required strings"})
        if reply is not None and (not isinstance(reply, str) or len(reply) > MAX_REPLY_BODY_CHARS):
            return WebResponse(400, {"error": "reply_text must be a string"})
        try:
            review = self.decisions.execute(case_id, decision, physician, reply)
        except UnknownCase:
            return WebResponse(404, {"error": "no review packet for this case"})
        except HitlRejected as exc:
            status = 403 if exc.reason == "not_an_approver" else 409 if exc.reason == "already_decided" else 422
            return WebResponse(status, {"error": str(exc), "reason": exc.reason})
        return WebResponse(200, {"case_id": case_id, "physician_review": self.gate_to_json(self.gate_view(review))})

    # ---- GET /runlog ----------------------------------------------------------------------------
    def get_run_log(self) -> WebResponse:
        return WebResponse(200, self.run_log(), "text/plain")

    def get_latest_for_patient(self, patient_id: str) -> WebResponse:
        latest = self._latest_case.get(patient_id)
        if latest is None:
            return WebResponse(404, {"error": "no case for patient"})
        case_id, outcome = latest
        has_review = case_id in self.reviews.views
        return WebResponse(200, {"case_id": case_id, "outcome": outcome, "has_review": has_review,
                                 "review_url": f"/reviews/{case_id}" if has_review else None})

    # ---- POST /api/sweep ---------------------------------------------------------------------
    def sweep(self) -> WebResponse:
        results = self.trigger.sweep_timeouts()
        for r in results:
            self._latest_case[r.patient_id] = (r.case_id, r.outcome.value)
        return WebResponse(200, {"handed_off": [r.case_id for r in results]})


# ---- pure request parsing --------------------------------------------------------------------
def parse_message_body(body: object) -> tuple[InboundMessage, Mapping | None]:
    """Validate the bridge's POST body. Raises ValueError with a message safe to return."""
    if not isinstance(body, Mapping):
        raise ValueError("body must be a JSON object")
    message_id = _short_text(body, "message_id")
    patient_id = _short_text(body, "patient_id")
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"text is longer than {MAX_TEXT_CHARS} characters")
    sent_at = _aware_datetime(body.get("sent_at"))
    origin = body.get("origin", "patient")
    if not isinstance(origin, str):
        raise ValueError("origin must be a string")
    bundle = body.get("fhir_bundle")
    if bundle is not None and (not isinstance(bundle, Mapping) or bundle.get("resourceType") != "Bundle"):
        raise ValueError("fhir_bundle must be a FHIR Bundle")
    return InboundMessage(message_id, patient_id, sent_at, text, origin), bundle


def _short_text(body: Mapping, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_ID_CHARS:
        raise ValueError(f"{key} is required (1-{MAX_ID_CHARS} characters)")
    return value


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("sent_at must be an ISO 8601 timestamp with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("sent_at must be an ISO 8601 timestamp with a timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError("sent_at must include a timezone (e.g. ...Z or ...-04:00)")
    return parsed
