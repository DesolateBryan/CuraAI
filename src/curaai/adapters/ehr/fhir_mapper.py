"""fhir_to_chart_items: pure function, FHIR R4 Bundle (dict) -> ChartItemRecord tuple.

Maps MedicationRequest, Observation and Encounter resources. Sets source_ref to
"<resourceType>/<id>" and copies text fields verbatim. Tested against fixed
FHIR data captured from MockChart's FHIR tab.
"""

from curaai.application.dto.ehr import ChartItemRecord


def fhir_to_chart_items(bundle: dict) -> tuple[ChartItemRecord, ...]:
    raise NotImplementedError("Ring 3 stub")
