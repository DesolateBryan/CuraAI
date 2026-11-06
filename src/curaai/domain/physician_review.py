"""PhysicianReview: the Human-In-The-Loop gate (Governance ADR 3, steward Bryan Ponce).

"The doctor approves every clinical decision, prescription, and patient reply. AI only asks
pre-approved follow-up questions and fetches records."

Every delivered review packet opens a gate in AWAITING_PHYSICIAN. Nothing written for the
patient leaves CuraAI until a physician from the approver list (owned by Main) decides:

    APPROVE  the physician's own reply text goes to the patient, labeled with who approved it
    RETURN   nothing is sent; the case goes back to the clinic queue for normal handling

A gate decides once. A second decision, a decision by someone who is not an approver, an
approval with no reply, or a return that tries to carry text are all refused (HitlRejected),
and the gate stays as it was. The AI never writes the reply and never holds the port that
sends it.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from curaai.domain.errors import HitlRejected
from curaai.domain.values import require_aware

MAX_REPLY_CHARS = 2_000


class GateStatus(Enum):
    AWAITING_PHYSICIAN = "awaiting_physician"
    APPROVED = "approved"
    RETURNED = "returned"


class Decision(Enum):
    APPROVE = "approve"
    RETURN = "return"


def physician_sender_label(physician_id: str) -> str:
    """How an approved reply is labeled in the patient's thread (never 'automated')."""
    return f"Reply approved by {physician_id}"


@dataclass(frozen=True)
class PhysicianReview:
    case_id: str
    patient_id: str
    opened_at: datetime
    status: GateStatus = GateStatus.AWAITING_PHYSICIAN
    physician_id: str | None = None
    decided_at: datetime | None = None
    reply_text: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.opened_at, "opened_at")
        if not self.case_id or not self.patient_id:
            raise ValueError("a physician review needs a case and a patient")

    @classmethod
    def open(cls, case_id: str, patient_id: str, at: datetime) -> "PhysicianReview":
        return cls(case_id, patient_id, at)

    @property
    def is_open(self) -> bool:
        return self.status is GateStatus.AWAITING_PHYSICIAN

    def decide(self, decision: Decision, physician_id: str, reply_text: str | None, at: datetime,
               approvers: frozenset[str]) -> "PhysicianReview":
        require_aware(at, "at")
        physician_id = (physician_id or "").strip()
        reply = (reply_text or "").strip()
        if not self.is_open:
            raise HitlRejected("already_decided", f"case was already {self.status.value} by {self.physician_id}")
        if physician_id not in approvers:
            raise HitlRejected("not_an_approver", f"{physician_id or 'nobody'} is not on the approver list")
        if decision is Decision.APPROVE:
            if not reply:
                raise HitlRejected("empty_reply", "an approval must carry the physician's reply")
            if len(reply) > MAX_REPLY_CHARS:
                raise HitlRejected("reply_too_long", f"reply is longer than {MAX_REPLY_CHARS} characters")
            return replace(self, status=GateStatus.APPROVED, physician_id=physician_id, decided_at=at,
                           reply_text=reply)
        if reply:
            raise HitlRejected("return_with_text", "a returned case sends nothing to the patient")
        return replace(self, status=GateStatus.RETURNED, physician_id=physician_id, decided_at=at)
