"""MockEpicAdapter: EhrPort over the FHIR bundle the MockChart page posts (ADR-005).

The API key stays behind this constructor (SMART on FHIR deferred, ADR-017).
"""

from curaai.application.dto.ehr import ActiveMedicationQuery, ChartItemRecord, ChartQuery
from curaai.application.ports.ehr_port import EhrPort


class MockEpicAdapter(EhrPort):
    def __init__(self, bundle_source: object, api_key: str) -> None:
        self._bundles = bundle_source
        self._api_key = api_key

    def items_between(self, query: ChartQuery) -> tuple[ChartItemRecord, ...]:
        raise NotImplementedError("Ring 3 stub")

    def active_medications(self, query: ActiveMedicationQuery) -> tuple[ChartItemRecord, ...]:
        raise NotImplementedError("Ring 3 stub")
