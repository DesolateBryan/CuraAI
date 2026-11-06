"""Patient messaging boundary."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    patient_id: str
    sent_at: datetime
    text: str
    origin: str = "patient"     # required label; flows through to the "patient-reported" tag


@dataclass(frozen=True)
class OutboundFollowUp:
    patient_id: str
    question_id: str
    text: str                   # always copied from the fixed FollowUpCatalog, never model text
    sender_label: str           # "Automated question from CuraAI"; adapters must display it

    def __post_init__(self) -> None:
        if not self.sender_label.strip():
            raise ValueError("an automated follow-up must carry its sender label")


@dataclass(frozen=True)
class PhysicianReply:
    """A reply a physician wrote and approved at the HITL gate. Only RecordPhysicianDecision
    builds one; the AI pipeline never holds the port that sends it."""

    patient_id: str
    case_id: str
    physician_id: str
    text: str                   # the physician's own words, unchanged
    sender_label: str           # "Reply approved by <physician>"

    def __post_init__(self) -> None:
        if not (self.physician_id.strip() and self.text.strip() and self.sender_label.strip()):
            raise ValueError("a physician reply needs an approving physician, text and a sender label")
