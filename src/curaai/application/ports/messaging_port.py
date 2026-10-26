"""PatientMessagingPort: sends one catalog follow-up question to the patient.

The DTO carries a catalog question id and its approved text. There is no way to
send free text through this port (ADR-009).
"""

from abc import ABC, abstractmethod

from curaai.application.dto.messaging import OutboundFollowUp


class PatientMessagingPort(ABC):
    @abstractmethod
    def send_follow_up(self, follow_up: OutboundFollowUp) -> None:
        """Deliver a catalog question into the patient's message thread."""
