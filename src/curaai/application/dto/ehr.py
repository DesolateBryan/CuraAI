"""EHR read boundary. FHIR bundles and resource types stay behind the adapter."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ChartQuery:
    patient_id: str
    from_date: date
    to_date: date


@dataclass(frozen=True)
class ActiveMedicationQuery:
    patient_id: str
    on_date: date


@dataclass(frozen=True)
class ChartItemRecord:
    """Named ChartItem in the M2 table; renamed so it does not clash with the Ring 1 entity."""

    item_id: str
    kind: str                     # "medication" | "lab" | "encounter"
    date: date
    title: str
    detail: str                   # verbatim
    source_ref: str
    author: str | None = None
    end_date: date | None = None
    flag: str | None = None
    code: str | None = None
    code_system: str | None = None
    stopped: bool = False         # FHIR status stopped/completed/cancelled
