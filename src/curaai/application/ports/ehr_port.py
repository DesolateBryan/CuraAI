"""EhrPort: read-only, one patient per query (ADR-005, ADR-010)."""

from abc import ABC, abstractmethod

from curaai.application.dto.ehr import ActiveMedicationQuery, ChartItemRecord, ChartQuery


class EhrPort(ABC):
    @abstractmethod
    def items_between(self, query: ChartQuery) -> tuple[ChartItemRecord, ...]:
        """Medication changes, labs and encounters dated inside the query window."""

    @abstractmethod
    def active_medications(self, query: ActiveMedicationQuery) -> tuple[ChartItemRecord, ...]:
        """Medications active on the given date, however long ago they started."""
