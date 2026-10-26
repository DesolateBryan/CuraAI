"""Model boundary: the four narrow model ports.

Data minimization (ADR-002, ADR-013): requests carry symptom text, enums, ids and
short labels only, never chart detail. Responses carry ids, enum strings and
dates only, and the core validates all of them before use.
Response fields are typed loosely (plain str) on purpose: they are untrusted
until ModelOutputValidator accepts them.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ExtractionRequest:
    request_id: str
    message_text: str                 # the patient's own words; redacted by the gateway
    reference_date: date              # lets the model resolve "last Friday"
    catalog_ids: frozenset[str]


@dataclass(frozen=True)
class SymptomExtraction:
    symptom_ids: tuple[str, ...]
    onset: date | None
    onset_is_approx: bool
    trend: str | None                 # must be a Trend value


@dataclass(frozen=True)
class FollowUpRequest:
    request_id: str
    missing: frozenset[str]           # MissingField values
    candidate_question_ids: frozenset[str]


@dataclass(frozen=True)
class FollowUpChoice:
    question_id: str


@dataclass(frozen=True)
class LabeledItem:
    item_id: str
    label: str                        # short label only, e.g. "Lisinopril" or "Potassium"


@dataclass(frozen=True)
class SelectionRequest:
    request_id: str
    symptom_ids: frozenset[str]
    items: tuple[LabeledItem, ...]


@dataclass(frozen=True)
class ItemSelection:
    item_ids: tuple[str, ...]


@dataclass(frozen=True)
class FlagMatchRequest:
    request_id: str
    symptom_ids: frozenset[str]
    items: tuple[LabeledItem, ...]
    flag_ids: frozenset[str]          # Flag values the model may choose from


@dataclass(frozen=True)
class FlagMatch:
    item_id: str
    flag_id: str
