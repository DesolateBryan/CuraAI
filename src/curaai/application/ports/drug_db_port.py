"""DrugDbPort: read-only lookup. No write methods exist (M1 sketch, ISP)."""

from abc import ABC, abstractmethod

from curaai.application.dto.drug import DrugQuery, DrugRecord


class DrugDbPort(ABC):
    @abstractmethod
    def lookup(self, query: DrugQuery) -> DrugRecord | None:
        """Verbatim database text for one drug, or None when the drug is not found."""
