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
