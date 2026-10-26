"""Review output boundary: the plain response the use case hands to the presenter.

The presenter (Ring 3) turns this into a ReviewView: section order, date formats,
the "patient-reported" tag, the "approximate" onset wording and the banner text.
The use case never formats a date or writes a label (ADR-014).
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ReviewRow:
    section: str                  # Section value
    text: str                     # verbatim
    source_ref: str
    origin: str                   # Origin value
    title: str | None
    day: date | None
    days_from_anchor: int | None
    author: str | None
    documented_flag: str | None
    flags: tuple[str, ...]        # Flag values
    ai_selected: bool


@dataclass(frozen=True)
class ReviewResponse:
    case_id: str
    patient_id: str
    status: str                   # PacketStatus value
    incomplete_reason: str | None
    anchor_date: date
    onset: date | None
    onset_is_approx: bool
    trend: str | None
    symptom_labels: tuple[str, ...]
    rows: tuple[ReviewRow, ...]
    ai_fallback: bool
    rejected_item_count: int
    requires_in_person_verification: bool
