"""ConversationStorePort: holds open cases between patient replies.

In memory for the prototype (ADR-005). A database-backed store is deferred
until the 24-hour timeout must survive restarts (ADR-017).
"""

from abc import ABC, abstractmethod

from curaai.application.dto.conversation import ConversationSnapshot


class ConversationStorePort(ABC):
    @abstractmethod
    def get_open(self, patient_id: str) -> ConversationSnapshot | None:
        """The patient's open case, if any."""

    @abstractmethod
    def put(self, snapshot: ConversationSnapshot) -> None:
        """Save the latest snapshot of a case (insert or replace by case_id)."""

    @abstractmethod
    def list_awaiting_patient(self) -> tuple[ConversationSnapshot, ...]:
        """Every case waiting on a patient answer, for the timeout sweep."""
