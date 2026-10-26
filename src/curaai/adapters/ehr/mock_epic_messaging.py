"""MockEpicMessagingAdapter: PatientMessagingPort that posts catalog text into the MockChart thread."""

from curaai.application.dto.messaging import OutboundFollowUp
from curaai.application.ports.messaging_port import PatientMessagingPort


class MockEpicMessagingAdapter(PatientMessagingPort):
    def __init__(self, outbox: object) -> None:
        self._outbox = outbox

    def send_follow_up(self, follow_up: OutboundFollowUp) -> None:
        raise NotImplementedError("Ring 3 stub")
