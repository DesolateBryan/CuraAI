"""LookbackWindow: the fixed chart window, from 21 days before symptom onset through today.

Team decision (2026-10-26): the window ends at TODAY, not at onset, so results
documented after symptoms began (e.g. a same-day STAT lab) are included.
"""

from dataclasses import dataclass
from datetime import date, timedelta

LOOKBACK_DAYS = 21


@dataclass(frozen=True)
class LookbackWindow:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("LookbackWindow end is before start")

    @classmethod
    def for_onset(cls, onset: date, today: date) -> "LookbackWindow":
        if onset > today:
            raise ValueError("symptom onset cannot be after today")
        return cls(start=onset - timedelta(days=LOOKBACK_DAYS), end=today)

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end
