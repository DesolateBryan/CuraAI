"""MockEpicMessagingAdapter: PatientMessagingPort for the MockChart demo.

The backend can't write into the browser page directly, so follow-up questions
go into an InMemoryOutbox. The page bridge polls the outbox and posts each
question into the patient's MockChart thread with window.MockEpic.send().
Only catalog question text ever goes in (ADR-009); the DTO has no free-text field.

MockChart can only post messages as the doctor, so the required automated-sender label
is put in front of the question (team decision, 2026-10-26). A real Epic adapter should
use the EHR's own sender/automation field instead.
"""

import threading
from collections import defaultdict
from dataclasses import dataclass

from curaai.application.dto.messaging import OutboundFollowUp, PhysicianReply
from curaai.application.ports.messaging_port import PatientMessagingPort
from curaai.application.ports.physician_reply_port import PhysicianReplyPort

PHYSICIAN_REPLY_KIND = "physician_reply"   # OutboxItem.question_id for an approved reply (not a catalog id)


def mockchart_display_text(follow_up: OutboundFollowUp) -> str:
    """Pure: how a follow-up appears in the MockChart thread."""
    return f"{follow_up.sender_label}: {follow_up.text}"


@dataclass(frozen=True)
class OutboxItem:
    patient_id: str
    question_id: str
    text: str            # the catalog text, unchanged
    sender_label: str
    display_text: str    # what the bridge posts into the page


class InMemoryOutbox:
    def __init__(self) -> None:
        self._pending: dict[str, list[OutboxItem]] = defaultdict(list)
        self._lock = threading.Lock()

    def add(self, item: OutboxItem) -> None:
        with self._lock:
            self._pending[item.patient_id].append(item)

    def drain(self, patient_id: str | None = None) -> tuple[OutboxItem, ...]:
        """Return and remove pending follow-ups, for one patient or for all."""
        with self._lock:
            ids = [patient_id] if patient_id is not None else list(self._pending)
            out = tuple(f for pid in ids for f in self._pending.pop(pid, []))
        return out


class MockEpicMessagingAdapter(PatientMessagingPort):
    def __init__(self, outbox: InMemoryOutbox) -> None:
        self._outbox = outbox

    def send_follow_up(self, follow_up: OutboundFollowUp) -> None:
        self._outbox.add(OutboxItem(follow_up.patient_id, follow_up.question_id, follow_up.text,
                                    follow_up.sender_label, mockchart_display_text(follow_up)))


class MockEpicPhysicianReplyAdapter(PhysicianReplyPort):
    """PhysicianReplyPort for MockChart: an approved reply goes through the same outbox, marked
    PHYSICIAN_REPLY_KIND so the bridge knows the patient's answer to it is not a new sick message.
    Main gives this adapter only to RecordPhysicianDecision (Governance ADR 3)."""

    def __init__(self, outbox: InMemoryOutbox) -> None:
        self._outbox = outbox

    def send_physician_reply(self, reply: PhysicianReply) -> None:
        self._outbox.add(OutboxItem(reply.patient_id, PHYSICIAN_REPLY_KIND, reply.text, reply.sender_label,
                                    f"{reply.sender_label}: {reply.text}"))
