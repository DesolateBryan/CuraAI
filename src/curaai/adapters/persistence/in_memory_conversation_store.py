"""InMemoryConversationStore: ConversationStorePort kept in a dict (ADR-005)."""

from curaai.application.dto.conversation import ConversationSnapshot
from curaai.application.ports.conversation_store_port import ConversationStorePort


class InMemoryConversationStore(ConversationStorePort):
    def __init__(self) -> None:
        self._by_case: dict[str, ConversationSnapshot] = {}

    def get_open(self, patient_id: str) -> ConversationSnapshot | None:
        raise NotImplementedError("Ring 3 stub")

    def put(self, snapshot: ConversationSnapshot) -> None:
        raise NotImplementedError("Ring 3 stub")

    def list_awaiting_patient(self) -> tuple[ConversationSnapshot, ...]:
        raise NotImplementedError("Ring 3 stub")
