"""Value types shared across the domain: identifiers and enumerations."""

from datetime import datetime
from enum import Enum
from typing import NewType

PatientId = NewType("PatientId", str)
MessageId = NewType("MessageId", str)
ItemId = NewType("ItemId", str)
SymptomId = NewType("SymptomId", str)
QuestionId = NewType("QuestionId", str)


class Trend(Enum):
    """How the patient says symptoms have changed since they started."""

    IMPROVING = "improving"
    WORSENING = "worsening"
    UNCHANGED = "unchanged"


class Origin(Enum):
    """Where a piece of displayed text came from. Patient words are always labeled."""

    PATIENT = "patient"            # shown to the physician as "patient-reported"
    CHART = "chart"                # documented in the EHR
    DRUG_DATABASE = "drug_database"
    CATALOG = "catalog"            # clinician-approved follow-up question text


class ChartItemKind(Enum):
    MEDICATION = "medication"
    LAB = "lab"
    ENCOUNTER = "encounter"


class MissingField(Enum):
    """The two details a sick message must contain before the chart pull runs."""

    ONSET = "onset"
    TREND = "trend"


class Flag(Enum):
    """Markers the model may attach to a medication row. A flag opens verbatim drug text."""

    POSSIBLE_ADVERSE_EFFECT = "possible_adverse_effect"
    POSSIBLE_INTERACTION = "possible_interaction"


def require_aware(value: datetime, name: str) -> None:
    """Every timestamp in the core must carry a timezone, so comparisons are unambiguous."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
