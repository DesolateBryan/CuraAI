"""ReviewPresenter: ReviewResponse -> ReviewView, a screen-ready model made only of strings.

Humble-object split (ADR-014). Every display decision is made HERE, in plain
code tested with plain data:
    * section order and section titles
    * row order: chronological against symptom onset (ADR-004)
    * date format ("Sep 22, 2026") and the offset ("17 days before onset"); current
      medications show "Since <start date>" with no offset, since years-old starts add noise
    * origin labels, including "Patient-reported" on every patient word (ADR-002)
    * the "approximate" onset wording
    * the in-person verification banner (ADR-006 / ADR-009), always present
    * notices for incomplete cases, the AI fallback and withheld records
    * the source reference on every row
The view (html_view.py, or the MockChart page later) only loops, escapes and
fills slots. It never truncates, rewords, sorts, formats dates or decides labels.

Row TEXT is passed through untouched: the presenter never edits documented text.
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Protocol

from curaai.application.dto.review import ReviewResponse, ReviewRow
from curaai.application.ports.review_output_port import ReviewOutputPort

SECTION_ORDER = (
    ("patient_messages", "Patient messages"),
    ("medication_changes", "Medication changes in the window"),
    ("current_medications", "Current medications"),
    ("visits", "Visits and provider notes"),
    ("labs", "Labs and results"),
    ("drug_information", "Drug information for changed medications"),
    ("ai_suggested_lookups", "AI-suggested drug lookups (check relevance)"),
)
# Shown even when empty, so "nothing found" is visible rather than silent.
ALWAYS_SHOWN = frozenset({"patient_messages", "medication_changes", "current_medications", "visits", "labs"})
CHART_SECTIONS = frozenset(key for key, _ in SECTION_ORDER) - {"patient_messages"}

ORIGIN_LABELS = {"patient": "Patient-reported", "chart": "Chart", "drug_database": "Drug database",
                 "catalog": "CuraAI follow-up question"}
FLAG_LABELS = {"possible_adverse_effect": "AI flag: possible adverse effect, see drug information",
               "possible_interaction": "AI flag: possible interaction, see drug information"}
TREND_LABELS = {"improving": "Getting better", "worsening": "Getting worse", "unchanged": "About the same"}

BANNER = ("Verify in person before prescribing. Symptom details are patient-reported and have not been "
          "clinically confirmed. CuraAI does not make clinical decisions.")
NOTICES = {
    "timed_out": "The patient did not answer the follow-up question within 24 hours. Chart history was not pulled.",
    "follow_ups_exhausted": "The patient's answers did not give the symptom start date and trend after two "
                            "follow-up questions. Chart history was not pulled.",
    "ai_unavailable": "AI screening was unavailable for this message, so the symptom start date was not established. "
                      "The chart window is measured from the first message date instead.",
}
AI_FALLBACK_NOTICE = "AI assistance was switched off partway through this case. Rows were not ranked or flagged by AI."
EMPTY_ROW_TEXT = "None found."


# ---- view model (strings only) -------------------------------------------------------
@dataclass(frozen=True)
class ViewRow:
    date: str
    offset: str
    title: str
    text: str           # verbatim, unchanged from the response
    author: str
    documented_flag: str
    ai_tags: str
    origin_label: str
    source_ref: str


@dataclass(frozen=True)
class ViewSection:
    key: str
    title: str
    rows: tuple[ViewRow, ...]


@dataclass(frozen=True)
class ReviewView:
    case_id: str
    patient_label: str
    status_label: str
    onset: str
    trend: str
    symptoms: str
    window: str
    banners: tuple[str, ...]     # always at least the in-person verification banner
    notices: tuple[str, ...]
    sections: tuple[ViewSection, ...]


# ---- pure presentation -----------------------------------------------------------------
def format_date(day: date | None) -> str:
    return f"{day:%b} {day.day}, {day.year}" if day else ""


def format_offset(days: int | None, anchor_name: str) -> str:
    if days is None:
        return ""
    if days == 0:
        return f"Same day as {anchor_name}"
    unit = "day" if abs(days) == 1 else "days"
    return f"{abs(days)} {unit} {'before' if days < 0 else 'after'} {anchor_name}"


def present_review(r: ReviewResponse) -> ReviewView:
    anchor_name = "onset" if r.onset else "first message"
    has_chart = r.window_start is not None

    sections = []
    for key, title in SECTION_ORDER:
        if key in CHART_SECTIONS and not has_chart:
            continue
        rows = _ordered([row for row in r.rows if row.section == key])
        if not rows and key not in ALWAYS_SHOWN:
            continue
        view_rows = tuple(_row(row, anchor_name) for row in rows) or (_empty_row(),)
        sections.append(ViewSection(key, title, view_rows))

    notices = []
    if r.incomplete_reason:
        notices.append(NOTICES[r.incomplete_reason])
    if r.ai_fallback and r.incomplete_reason != "ai_unavailable":
        notices.append(AI_FALLBACK_NOTICE)
    if r.rejected_item_count:
        noun = "record was" if r.rejected_item_count == 1 else "records were"
        notices.append(f"{r.rejected_item_count} chart or drug {noun} withheld because a source check failed. "
                       f"See the audit log for case {r.case_id}.")

    return ReviewView(
        case_id=r.case_id,
        patient_label=f"Patient {r.patient_id}",
        status_label="Ready for review" if r.status == "prefetched" else "Incomplete: patient messages only",
        onset=_onset(r),
        trend=f"{TREND_LABELS[r.trend]} (patient-reported)" if r.trend else "Not reported",
        symptoms=", ".join(r.symptom_labels) if r.symptom_labels else "None identified",
        window=(f"{format_date(r.window_start)} to {format_date(r.window_end)} "
                f"(21 days before {anchor_name} through today)") if has_chart else "No chart pull",
        banners=(BANNER,),          # the core refuses a packet with the banner off, so it is always shown
        notices=tuple(notices),
        sections=tuple(sections),
    )


def _onset(r: ReviewResponse) -> str:
    if r.onset is None:
        return "Not reported"
    prefix = "Around " if r.onset_is_approx else ""
    suffix = " (approximate, patient-reported)" if r.onset_is_approx else " (patient-reported)"
    return f"{prefix}{format_date(r.onset)}{suffix}"


def _ordered(rows: list[ReviewRow]) -> list[ReviewRow]:
    """Chronological; undated rows (drug text) keep their original order after dated ones."""
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda pair: (pair[1].day is None, pair[1].day or date.min, pair[0]))
    return [row for _, row in indexed]


def _row(row: ReviewRow, anchor_name: str) -> ViewRow:
    tags = [FLAG_LABELS[f] for f in row.flags if f in FLAG_LABELS]
    if row.ai_selected and row.section != "ai_suggested_lookups":
        tags.insert(0, "AI: likely relevant")
    current = row.section == "current_medications"
    return ViewRow(
        date=f"Since {format_date(row.day)}" if current and row.day else format_date(row.day),
        offset="" if current else format_offset(row.days_from_anchor, anchor_name),
        title=row.title or "",
        text=row.text,
        author=row.author or "",
        documented_flag=row.documented_flag or "",
        ai_tags="; ".join(tags),
        origin_label=ORIGIN_LABELS.get(row.origin, row.origin),
        source_ref=row.source_ref,
    )


def _empty_row() -> ViewRow:
    return ViewRow("", "", "", EMPTY_ROW_TEXT, "", "", "", "", "")


def review_view_to_dict(view: ReviewView) -> dict:
    """Plain JSON-ready dict for GET /api/reviews/{case_id}."""
    return asdict(view)


# ---- port implementation ------------------------------------------------------------------
class ReviewSink(Protocol):
    def publish(self, view: ReviewView) -> None: ...


class InMemoryReviewSink:
    """Keeps the latest view per case; the web layer will serve it to the MockChart page."""

    def __init__(self) -> None:
        self.views: dict[str, ReviewView] = {}

    def publish(self, view: ReviewView) -> None:
        self.views[view.case_id] = view


class ReviewPresenter(ReviewOutputPort):
    def __init__(self, sink: ReviewSink) -> None:
        self._sink = sink

    def present(self, response: ReviewResponse) -> None:
        self._sink.publish(present_review(response))
