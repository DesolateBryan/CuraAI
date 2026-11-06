"""PhysicianReplyPort: delivers a reply that a physician approved at the HITL gate.

Separate from PatientMessagingPort on purpose (Governance ADR 3 and ADR 4, least
privilege): the AI pipeline is given only the catalog-question port. This port is
injected into exactly one use case, RecordPhysicianDecision, and a test checks that
no other application module refers to it.
"""

from abc import ABC, abstractmethod

from curaai.application.dto.messaging import PhysicianReply


class PhysicianReplyPort(ABC):
    @abstractmethod
    def send_physician_reply(self, reply: PhysicianReply) -> None:
        """Deliver the approved reply into the patient's message thread."""
