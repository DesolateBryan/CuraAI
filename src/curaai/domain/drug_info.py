"""DrugInfo: verbatim drug-database text for one medication.

ADR-012: DrugRecord is the DTO that crosses the drug port; DrugInfo is this
Ring 1 entity, and it rejects a missing source_ref.
"""

from dataclasses import dataclass

from curaai.domain.errors import MissingSourceReference
from curaai.domain.values import require_text


@dataclass(frozen=True)
class DrugInfo:
    drug_name: str
    source_ref: str
    class_text: str | None = None
    adverse_text: str | None = None
    interactions_text: str | None = None
    boxed_warning_text: str | None = None
    contraindications_text: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise MissingSourceReference(f"drug info for {self.drug_name!r} has no source_ref")
        require_text(self.drug_name, "DrugInfo.drug_name")
        if not any((self.class_text, self.adverse_text, self.interactions_text,
                    self.boxed_warning_text, self.contraindications_text)):
            raise ValueError("DrugInfo must carry at least one verbatim text field")

    def matches(self, medication_title: str) -> bool:
        """Case-insensitive name match, so "Ferrous sulfate" finds the "ferrous sulfate" record."""
        return self.drug_name.casefold() in medication_title.casefold() or \
            medication_title.casefold() in self.drug_name.casefold()
