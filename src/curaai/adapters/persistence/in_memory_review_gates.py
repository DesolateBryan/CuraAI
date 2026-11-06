"""InMemoryReviewGates: ReviewGatePort for the prototype (one process, thread-safe).

Like the conversation store, a restart forgets open gates; a database-backed store
replaces this when gates must survive a restart (ADR-017).
"""

import threading

from curaai.application.ports.review_gate_port import ReviewGatePort
from curaai.domain.physician_review import PhysicianReview


class InMemoryReviewGates(ReviewGatePort):
    def __init__(self) -> None:
        self._gates: dict[str, PhysicianReview] = {}
        self._lock = threading.Lock()

    def save(self, review: PhysicianReview) -> None:
        with self._lock:
            self._gates[review.case_id] = review

    def get(self, case_id: str) -> PhysicianReview | None:
        with self._lock:
            return self._gates.get(case_id)
