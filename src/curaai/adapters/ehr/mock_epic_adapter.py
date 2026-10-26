"""MockEpicAdapter: EhrPort over the FHIR bundles the MockChart page posts (ADR-005).

Humble by design: fetch the bundle, call the pure mapper, filter by the query.
Read-only and one patient per query (ADR-010). The API key stays behind this
constructor until SMART on FHIR replaces it (ADR-017); it is never logged.
A second EHR means a new adapter next to this one, with no core change.
"""

from curaai.adapters.ehr.bundle_source import BundleSource
from curaai.adapters.ehr.fhir_mapper import fhir_to_chart_items
from curaai.application.dto.ehr import ActiveMedicationQuery, ChartItemRecord, ChartQuery
from curaai.application.errors import ExternalSourceUnavailable
from curaai.application.ports.ehr_port import EhrPort


class MockEpicAdapter(EhrPort):
    def __init__(self, bundle_source: BundleSource, api_key: str) -> None:
        if not api_key:
            raise ValueError("MockEpicAdapter needs the MockEpic API key")
        self._source = bundle_source
        self._api_key = api_key

    def __repr__(self) -> str:                    # keep the key out of logs and tracebacks
        return "MockEpicAdapter(api_key=***)"

    def items_between(self, query: ChartQuery) -> tuple[ChartItemRecord, ...]:
        lo, hi = query.from_date, query.to_date
        return tuple(r for r in self._records(query.patient_id)
                     if lo <= r.date <= hi or (r.end_date is not None and lo <= r.end_date <= hi))

    def active_medications(self, query: ActiveMedicationQuery) -> tuple[ChartItemRecord, ...]:
        day = query.on_date
        return tuple(r for r in self._records(query.patient_id)
                     if r.kind == "medication" and not r.stopped and r.date <= day
                     and (r.end_date is None or r.end_date > day))

    def _records(self, patient_id: str) -> tuple[ChartItemRecord, ...]:
        bundle = self._source.bundle_for(patient_id)
        if bundle is None:
            raise ExternalSourceUnavailable(f"no FHIR bundle posted for patient {patient_id!r}")
        try:
            return fhir_to_chart_items(bundle, patient_id).records
        except ValueError as exc:
            raise ExternalSourceUnavailable(f"unreadable FHIR bundle: {exc}") from exc
