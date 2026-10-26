"""SickMessage: a message the patient sent through the portal."""

from dataclasses import dataclass
from datetime import datetime

from curaai.domain.values import MessageId, Origin, PatientId, require_aware, require_text


@dataclass(frozen=True)
class SickMessage:
    message_id: MessageId
    patient_id: PatientId
    sent_at: datetime
    text: str              # kept exactly as the patient wrote it
    origin: Origin = Origin.PATIENT

    def __post_init__(self) -> None:
        require_text(self.message_id, "SickMessage.message_id")
        require_text(self.patient_id, "SickMessage.patient_id")
        require_text(self.text, "SickMessage.text")
        require_aware(self.sent_at, "SickMessage.sent_at")
        if self.origin is not Origin.PATIENT:
            raise ValueError("a SickMessage must originate from the patient")
