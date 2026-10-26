"""SymptomReport: what the patient has told us so far (symptoms, onset, trend)."""

from dataclasses import dataclass, replace
from datetime import date

from curaai.domain.errors import InvalidSymptomReport
from curaai.domain.values import SymptomId, Trend


@dataclass(frozen=True)
class SymptomReport:
    symptom_ids: frozenset[SymptomId] = frozenset()
    onset: date | None = None
    onset_is_approx: bool = False   # "around Oct 9th" -> shown as approximate
    trend: Trend | None = None

    def __post_init__(self) -> None:
        if self.onset_is_approx and self.onset is None:
            raise InvalidSymptomReport("onset_is_approx requires an onset date")

    def merge(self, newer: "SymptomReport") -> "SymptomReport":
        """Fill gaps from a later patient answer.

        Symptoms accumulate. Onset and trend already on file are kept; a later
        answer only fills a field that is still empty. This keeps every value
        traceable to the first message that supplied it.
        """
        onset, approx = (self.onset, self.onset_is_approx) if self.onset else (newer.onset, newer.onset_is_approx)
        return replace(
            self,
            symptom_ids=self.symptom_ids | newer.symptom_ids,
            onset=onset,
            onset_is_approx=approx,
            trend=self.trend if self.trend is not None else newer.trend,
        )
