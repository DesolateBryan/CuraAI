"""RecordPhysicianDecision: the physician's side of the HITL gate (Governance ADR 3).

AssembleReviewPacket opens a gate for every delivered packet ("hitl_gate_opened"). This
use case is the only way to close it, and the only holder of PhysicianReplyPort:

    approve  -> the physician's reply is sent, labeled with who approved it   "hitl_decision"
    return   -> nothing is sent; the case goes back to the clinic queue        "hitl_decision"
    refused  -> wrong person, second decision, empty approval, ...             "hitl_blocked"

The approver list comes from Main (CURAAI_HITL_APPROVERS). The audit log records who
decided, when and how long the reply was, never the reply text itself (ADR-007: no
patient-message text in the log).
"""

from curaai.application.dto.messaging import PhysicianReply
from curaai.application.errors import UnknownCase
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.ports.physician_reply_port import PhysicianReplyPort
from curaai.application.ports.review_gate_port import ReviewGatePort
from curaai.application.use_cases._audit import Auditor
from curaai.domain.errors import HitlRejected
from curaai.domain.physician_review import Decision, PhysicianReview, physician_sender_label

ACTOR = "hitl_gate"


class RecordPhysicianDecision:
    def __init__(self, gates: ReviewGatePort, replies: PhysicianReplyPort, approvers: frozenset[str],
                 audit_log: AuditLogPort, clock: ClockPort) -> None:
        if not approvers:
            raise ValueError("the HITL gate needs at least one approver")
        self._gates = gates
        self._replies = replies
        self._approvers = frozenset(approvers)
        self._audit = Auditor(audit_log, clock)
        self._clock = clock

    def gate(self, case_id: str) -> PhysicianReview | None:
        return self._gates.get(case_id)

    def execute(self, case_id: str, decision: str, physician_id: str, reply_text: str | None) -> PhysicianReview:
        review = self._gates.get(case_id)
        if review is None:
            raise UnknownCase(case_id)
        try:
            choice = Decision(decision)
        except ValueError:
            self._blocked(review, "unknown_decision", physician_id)
            raise HitlRejected("unknown_decision", f"decision must be one of: {', '.join(d.value for d in Decision)}")
        try:
            decided = review.decide(choice, physician_id, reply_text, self._clock.now(), self._approvers)
        except HitlRejected as exc:
            self._blocked(review, exc.reason, physician_id)
            raise

        if decided.status.value == "approved":
            self._replies.send_physician_reply(PhysicianReply(
                decided.patient_id, decided.case_id, decided.physician_id, decided.reply_text,
                physician_sender_label(decided.physician_id)))
        self._gates.save(decided)
        self._audit(ACTOR, "hitl_decision", case_id, gate="physician_sign_off", decision=choice.value,
                    physician=decided.physician_id, reply_sent=decided.status.value == "approved",
                    reply_chars=len(decided.reply_text or ""))
        return decided

    def _blocked(self, review: PhysicianReview, reason: str, physician_id: str) -> None:
        self._audit(ACTOR, "hitl_blocked", review.case_id, gate="physician_sign_off", reason=reason,
                    attempted_by=(physician_id or "").strip()[:64] or None, gate_status=review.status.value)
