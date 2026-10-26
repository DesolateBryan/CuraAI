"""fhir_to_chart_items: FHIR R4 Bundle -> ChartItemRecord DTOs. Pure function, no I/O (ADR-014).

What crosses inward: one ChartItemRecord per MedicationRequest, Observation and
Encounter that belongs to the requested patient. What stays behind: the Bundle,
resource types, references, the Patient resource (demographics) and
Communication resources (messages arrive through the messaging boundary).

Verbatim rule (ADR-004): text fields are copied exactly. When a resource has
two documented text fields (dosage + note, value + reference range), they are
joined with a fixed separator, never reworded or trimmed.

Source rule (ADR-012): source_ref is "<resourceType>/<id>". A resource with no
id gets an EMPTY source_ref on purpose, so the core rejects it, audits it and
counts it in rejected_item_count, instead of the adapter hiding it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from curaai.application.dto.ehr import ChartItemRecord

JOIN = " · "
STOPPED_STATUSES = frozenset({"stopped", "completed", "cancelled"})
EXCLUDED_STATUSES = frozenset({"entered-in-error"})    # never shown: the chart says it was a mistake


@dataclass(frozen=True)
class FhirMapping:
    records: tuple[ChartItemRecord, ...]
    skipped_other_patient: int = 0     # least privilege: another patient's data never crosses
    skipped_entered_in_error: int = 0
    skipped_unreadable: int = 0        # no usable date or title


def fhir_to_chart_items(bundle: Mapping, patient_id: str) -> FhirMapping:
    if not isinstance(bundle, Mapping) or bundle.get("resourceType") != "Bundle":
        raise ValueError("expected a FHIR Bundle")

    records: list[ChartItemRecord] = []
    other = error = unreadable = 0
    for entry in bundle.get("entry") or ():
        resource = (entry or {}).get("resource") or {}
        mapper = _MAPPERS.get(resource.get("resourceType"))
        if mapper is None:
            continue
        if _subject(resource) != f"Patient/{patient_id}":
            other += 1
            continue
        if resource.get("status") in EXCLUDED_STATUSES:
            error += 1
            continue
        record = mapper(resource)
        if record is None:
            unreadable += 1
            continue
        records.append(record)
    return FhirMapping(tuple(records), other, error, unreadable)


# ---- one mapper per resource type ---------------------------------------------
def _medication(r: Mapping) -> ChartItemRecord | None:
    concept = r.get("medicationCodeableConcept") or {}
    title = concept.get("text") or _first(concept.get("coding"), "display")
    start = _date(r.get("authoredOn"))
    if not title or start is None:
        return None
    dosage = r.get("dosageInstruction") or []
    detail = _join([d.get("text") for d in dosage] + _texts(r.get("note")))
    bounds = (((dosage[0] if dosage else {}).get("timing") or {}).get("repeat") or {}).get("boundsPeriod") or {}
    code, system = _coding(concept)
    return ChartItemRecord(
        item_id=r.get("id") or "", kind="medication", date=start, end_date=_date(bounds.get("end")),
        title=title, detail=detail, source_ref=_ref(r), author=(r.get("requester") or {}).get("display"),
        code=code, code_system=system, stopped=r.get("status") in STOPPED_STATUSES,
    )


def _observation(r: Mapping) -> ChartItemRecord | None:
    concept = r.get("code") or {}
    title = concept.get("text") or _first(concept.get("coding"), "display")
    day = _date(r.get("effectiveDateTime") or (r.get("effectivePeriod") or {}).get("start"))
    if not title or day is None:
        return None
    value = r.get("valueString")
    if value is None and isinstance(r.get("valueQuantity"), Mapping):
        q = r["valueQuantity"]
        value = _join([str(q["value"]) if "value" in q else None, q.get("unit")], sep=" ")
    ref_range = _join(_texts(r.get("referenceRange")))
    detail = f"{value} (ref {ref_range})" if value and ref_range else (value or "")
    interpretation = r.get("interpretation") or []
    flag = (interpretation[0].get("text") or _first(interpretation[0].get("coding"), "code")) if interpretation else None
    code, system = _coding(concept)
    return ChartItemRecord(
        item_id=r.get("id") or "", kind="lab", date=day, title=title, detail=detail,
        source_ref=_ref(r), author=_first(r.get("performer"), "display"), flag=flag or None,
        code=code, code_system=system,
    )


def _encounter(r: Mapping) -> ChartItemRecord | None:
    title = _first(r.get("type"), "text")
    period = r.get("period") or {}
    day = _date(period.get("start"))
    if not title or day is None:
        return None
    participants = r.get("participant") or []
    author = ((participants[0] if participants else {}).get("individual") or {}).get("display")
    return ChartItemRecord(
        item_id=r.get("id") or "", kind="encounter", date=day, end_date=_date(period.get("end")),
        title=title, detail=_join(_texts(r.get("reasonCode"))), source_ref=_ref(r), author=author,
    )


_MAPPERS = {"MedicationRequest": _medication, "Observation": _observation, "Encounter": _encounter}


# ---- helpers (pure) -------------------------------------------------------------
def _subject(r: Mapping) -> str | None:
    return (r.get("subject") or {}).get("reference")


def _ref(r: Mapping) -> str:
    return f"{r['resourceType']}/{r['id']}" if r.get("id") else ""


def _date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _texts(items: object) -> list[str | None]:
    return [i.get("text") for i in items] if isinstance(items, list) else []


def _first(items: object, key: str) -> str | None:
    return items[0].get(key) if isinstance(items, list) and items and isinstance(items[0], Mapping) else None


def _coding(concept: Mapping) -> tuple[str | None, str | None]:
    coding = concept.get("coding")
    if isinstance(coding, list) and coding:
        return coding[0].get("code"), coding[0].get("system")
    return None, None


def _join(parts: list[str | None], sep: str = JOIN) -> str:
    return sep.join(p for p in parts if p)
