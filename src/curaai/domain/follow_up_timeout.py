"""FollowUpTimeout: a follow-up question unanswered for 24 hours expires.

Team decision (2026-10-26): on expiry the case is handed to the physician as
incomplete, with the patient messages only and NO chart pre-fetch.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from curaai.domain.values import require_aware

FOLLOW_UP_TIMEOUT = timedelta(hours=24)


@dataclass(frozen=True)
class FollowUpTimeout:
    duration: timedelta = FOLLOW_UP_TIMEOUT

    def __post_init__(self) -> None:
        if self.duration <= timedelta(0):
            raise ValueError("timeout duration must be positive")

    def deadline(self, asked_at: datetime) -> datetime:
        require_aware(asked_at, "asked_at")
        return asked_at + self.duration

    def is_expired(self, asked_at: datetime, now: datetime) -> bool:
        require_aware(now, "now")
        return now >= self.deadline(asked_at)
