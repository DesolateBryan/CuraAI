"""ReviewGatePort: keeps each case's HITL gate (PhysicianReview) between requests."""

from abc import ABC, abstractmethod

from curaai.domain.physician_review import PhysicianReview


class ReviewGatePort(ABC):
    @abstractmethod
    def save(self, review: PhysicianReview) -> None:
        """Store the gate (insert or replace by case_id)."""

    @abstractmethod
    def get(self, case_id: str) -> PhysicianReview | None:
        """The gate for a case, or None if no packet was delivered for it."""
