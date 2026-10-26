"""MockEpicMessagingAdapter: PatientMessagingPort for the MockChart demo.

The backend can't write into the browser page directly, so follow-up questions
go into an InMemoryOutbox. The page bridge polls the outbox and posts each
question into the patient's MockChart thread with window.MockEpic.send().
Only catalog question text ever goes in (ADR-009); the DTO has no free-text field.
"""

import threading
from collections import defaultdict

from curaai.application.dto.messaging import OutboundFollowUp
from curaai.application.ports.messaging_port import PatientMessagingPort


class InMemoryOutbox:
    def __init__(self) -> None:
        self._pending: dict[str, list[OutboundFollowUp]] = defaultdict(list)
        self._lock = threading.Lock()

    def add(self, follow_up: OutboundFollowUp) -> None:
        with self._lock:
            self._pending[follow_up.patient_id].append(follow_up)

    def drain(self, patient_id: str | None = None) -> tuple[OutboundFollowUp, ...]:
        """Return and remove pending follow-ups, for one patient or for all."""
        with self._lock:
            ids = [patient_id] if patient_id is not None else list(self._pending)
            out = tuple(f for pid in ids for f in self._pending.pop(pid, []))
        return out


class MockEpicMessagingAdapter(PatientMessagingPort):
    def __init__(self, outbox: InMemoryOutbox) -> None:
        self._outbox = outbox

    def send_follow_up(self, follow_up: OutboundFollowUp) -> None:
        self._outbox.add(follow_up)
