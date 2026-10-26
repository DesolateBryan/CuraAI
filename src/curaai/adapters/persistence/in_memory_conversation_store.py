"""InMemoryConversationStore: ConversationStorePort kept in a dict (ADR-005).

Holds snapshots (DTOs), never Ring 1 entities (ADR-012). One snapshot per case,
replaced on every put(). Open/awaiting checks use the constants Ring 2 exports,
so the store never re-implements the state machine.

Deferred (ADR-017): a database-backed store. Until then, open cases and their
24-hour timers are lost on restart. The trigger to build it is "the timeout
must survive a restart".
"""

import threading

from curaai.application.dto.conversation import AWAITING_PATIENT_VALUE, OPEN_STATE_VALUES, ConversationSnapshot
from curaai.application.ports.conversation_store_port import ConversationStorePort


class InMemoryConversationStore(ConversationStorePort):
    def __init__(self) -> None:
        self._by_case: dict[str, ConversationSnapshot] = {}
        self._lock = threading.Lock()

    def get_open(self, patient_id: str) -> ConversationSnapshot | None:
        with self._lock:
            open_cases = [s for s in self._by_case.values()
                          if s.patient_id == patient_id and s.state in OPEN_STATE_VALUES]
        # newest first, in case an old case was never closed
        return max(open_cases, key=lambda s: s.messages[-1].sent_at, default=None)

    def put(self, snapshot: ConversationSnapshot) -> None:
        with self._lock:
            self._by_case[snapshot.case_id] = snapshot

    def list_awaiting_patient(self) -> tuple[ConversationSnapshot, ...]:
        with self._lock:
            return tuple(s for s in self._by_case.values() if s.state == AWAITING_PATIENT_VALUE)
