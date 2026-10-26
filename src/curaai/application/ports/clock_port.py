"""ClockPort: the only way Ring 2 learns the time, so tests can fix it (ADR-005)."""

from abc import ABC, abstractmethod
from datetime import date, datetime


class ClockPort(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Current time, timezone-aware, in the clinic's timezone."""

    def today(self) -> date:
        return self.now().date()
