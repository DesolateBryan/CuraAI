"""AssembleReviewPacket: build the ReviewPacket and hand a plain DTO to the presenter.

The use case never formats a date or writes a label (ADR-014); it maps the
packet to a ReviewResponse and calls ReviewOutputPort.

It then opens the case's HITL gate (Governance ADR 3): the packet is a briefing for
the physician, and nothing written for the patient leaves until a physician decides
in RecordPhysicianDecision. "hitl_gate_opened" in the audit log shows the gate firing.
"""

from curaai.application.mapping import review_response_from
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.ports.review_gate_port import ReviewGatePort
from curaai.application.ports.review_output_port import ReviewOutputPort
from curaai.application.use_cases._audit import Auditor
from curaai.application.use_cases.prefetch_history import PrefetchResult
from curaai.domain.conversation import Conversation
from curaai.domain.physician_review import PhysicianReview
from curaai.domain.symptom_catalog import SymptomCatalog
from curaai.domain.timeline import ReviewPacket

ACTOR = "assemble_review_packet"


class AssembleReviewPacket:
    def __init__(self, review_output: ReviewOutputPort, gates: ReviewGatePort, catalog: SymptomCatalog,
                 audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._output = review_output
        self._gates = gates
        self._clock = clock
        self._catalog = catalog
        self._audit = Auditor(audit_log, clock)

    def execute(self, conversation: Conversation, prefetch: PrefetchResult | None) -> ReviewPacket:
        if prefetch is None:
            packet = ReviewPacket.messages_only(conversation)
        else:
            packet = ReviewPacket.prefetched(conversation, prefetch.window, prefetch.entries,
                                         prefetch.rejected_item_count)
        self._output.present(review_response_from(packet, self._catalog))
        self._audit(ACTOR, "review_packet_delivered", packet.case_id, status=packet.status.value,
                    rows=len(packet.entries), ai_fallback=packet.ai_fallback,
                    incomplete_reason=packet.incomplete_reason.value if packet.incomplete_reason else None)
        self._gates.save(PhysicianReview.open(packet.case_id, conversation.patient_id, self._clock.now()))
        self._audit(ACTOR, "hitl_gate_opened", packet.case_id, gate="physician_sign_off",
                    waiting_for="physician", blocks="patient reply and clinical decisions")
        return packet
