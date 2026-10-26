"""FixedClock: ClockPort that always returns one moment.

For demos against MockChart, whose chart is frozen at "today = 2026-10-16".
Set CURAAI_CLOCK_NOW so the 3-week window lines up with the mock's dates.
Never use in production: the 24-hour timeout cannot expire on a frozen clock.
"""

from datetime import datetime

from curaai.application.ports.clock_port import ClockPort


class FixedClock(ClockPort):
    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = now

    def now(self) -> datetime:
        return self._now
