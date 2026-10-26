"""SystemClock: ClockPort over the real clock, in the clinic timezone."""

from datetime import datetime, tzinfo

from curaai.application.ports.clock_port import ClockPort


class SystemClock(ClockPort):
    def __init__(self, tz: tzinfo) -> None:
        self._tz = tz

    def now(self) -> datetime:
        return datetime.now(self._tz)
